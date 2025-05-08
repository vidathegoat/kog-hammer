import discord
from math import log2
from discord.ext import commands
from discord import app_commands
from discord.app_commands import CheckFailure
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from db import (
    get_all_punishment_options,
    add_punishment,
    get_user_stage,
    get_catalog_punishment,
    fetch_user_infractions,
    calculate_total_decayed_points,
    log_infraction,
    get_latest_punishment
)
from config import DISCORD_TOKEN, THREAD_CHANNEL_ID, ADMIN_BOT_CHANNEL_ID


# ======================================================================================================================

VERSION = "Version 1.2.2"

# ======================================================================================================================


intents = discord.Intents.default()
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Game(name=f"on {VERSION}"))
    print(f"🔨🗡️  {bot.user} is now online and watching over the realm! [{VERSION}]")
    try:
        synced = await bot.tree.sync()
        print(f"⚔️🔁  Synced: {len(synced)} slash command ready for battle!")
    except Exception as e:
        print(f"⚠️  **Error** syncing commands: {e}")

class PunishmentSelect(discord.ui.Select):
    def __init__(self, punishments, username, ip):
        MAX_LENGTH = 100

        options = []
        seen_reasons = set()

        for p in punishments:
            reason = p["reason"]
            if reason in seen_reasons:
                continue
            seen_reasons.add(reason)

            label = reason[:90] + "..." if len(reason) > MAX_LENGTH else reason
            value = reason[:MAX_LENGTH]

            options.append(discord.SelectOption(label=label, value=value))

        options.append(
            discord.SelectOption(
                label="Avoid Ban",
                value="__AVOID__",
                description="Select this option together with the offence(s) being avoided"
            )
        )

        super().__init__(
            placeholder="Choose one or more punishment reasons",
            min_values=1,
            max_values=len(options),
            options=options
        )
        self.username = username
        self.ip = ip

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await process_ban(interaction, self.values, self.username, self.ip)

class PunishmentSelectView(discord.ui.View):
    def __init__(self, punishments, username, ip):
        super().__init__(timeout=None)
        self.add_item(PunishmentSelect(punishments, username, ip))

async def process_ban(interaction, reasons, username, ip):
    """Apply a normal ban **or** re‑apply a previous ban if '__AVOID__' is present."""
    # ─────────────────────────────────────────────────────────────────────────────
    # 1.  Split off the special option
    # ─────────────────────────────────────────────────────────────────────────────
    avoid_mode = "__AVOID__" in reasons
    reasons    = [r for r in reasons if r != "__AVOID__"]          # only real offences

    if not reasons:            # we always need at least one real reason
        await interaction.followup.send(
            "⚠ Select at least one offence together with **Avoid Ban**.", ephemeral=True
        )
        return

    # ─────────────────────────────────────────────────────────────────────────────
    # 2.  Fetch catalogue / previous‑ban data
    # ─────────────────────────────────────────────────────────────────────────────
    total_amount     = 0            # raw catalogue amount sum (normal path)
    total_points     = 0
    unit             = "days"
    reused_multiplier = 1           # largest multiplier reused in avoid mode
    total_hours      = 0            # we’ll sum everything in hours for avoid

    def hours_from(amount, unit):
        return amount * {"minutes": 1/60, "hours": 1, "days": 24, "weeks": 168}[unit]

    if avoid_mode:
        for reason in reasons:
            prev = get_latest_punishment(username, reason)
            if not prev:
                await interaction.followup.send(
                    f"⚠ No previous ban found for **{reason}** – cannot avoid.",
                    ephemeral=True
                )
                return

            reused_multiplier  = max(reused_multiplier, prev["multiplier"])
            total_hours       += hours_from(prev["base_days"], prev["unit"])
            unit               = prev["unit"]        # keep for display later

        # durations
        duration_converted   = total_hours           # already in hours
        final_duration_value = int(total_hours)
        decayed_points       = 0
        total_points         = 0

    else:
        # ───────────────────────────── normal *new* ban ─────────────────────────
        for reason in reasons:
            stage    = get_user_stage(username, reason)
            template = get_catalog_punishment(reason, stage)
            if not template:
                await interaction.followup.send(
                    f"⚠️ No template found for `{reason}` at stage {stage}.",
                    ephemeral=True
                )
                return
            total_amount += template["amount"]
            total_points += template["points"]
            unit          = template.get("unit", unit)

        now             = datetime.now(ZoneInfo("America/New_York"))
        infractions      = fetch_user_infractions(username)
        decayed_points   = calculate_total_decayed_points(infractions, now, test_mode=True)
        multiplier       = max(log2(decayed_points + 1), 1)
        unit_abbrev      = {"minutes": "m", "hours": "h", "days": "d", "weeks": "w"}.get(unit, "d")
        final_duration_value = int(total_amount * multiplier)
        duration_converted   = (
            total_amount * {"minutes": 1/60, "hours": 1, "days": 24, "weeks": 168}[unit]
        )                                # hours for timestamp
    # ─────────────────────────────────────────────────────────────────────────────
    # 3.  Compute dates / strings common to both paths
    # ─────────────────────────────────────────────────────────────────────────────
    now        = datetime.now(ZoneInfo("America/New_York"))
    ban_end    = now + timedelta(hours=duration_converted)
    unix_ts    = int(ban_end.timestamp())
    unit_abbrev = {"minutes": "m", "hours": "h", "days": "d",
                   "weeks": "w"}.get(unit, "d")
    final_duration = f"{final_duration_value}{unit_abbrev}"
    final_duration_string = f"{final_duration_value} {unit}"

    # ─────────────────────────────────────────────────────────────────────────────
    # 4.  Write rows back to DB
    #     • avoid‑ban: 0 pts, reuse prev multiplier
    # ─────────────────────────────────────────────────────────────────────────────
    for reason in reasons:
        if avoid_mode:
            prev = get_latest_punishment(username, reason)
            add_punishment(
                username, ip, reason,
                prev["base_days"],          # same base
                0,                          # ⬅ NO points added
                prev["multiplier"],
                prev["total_points_at_ban"]
            )
            # no log_infraction → we don’t want decay/points
        else:
            stage    = get_user_stage(username, reason)
            template = get_catalog_punishment(reason, stage)
            add_punishment(
                username, ip, reason,
                template["amount"],
                template["points"],
                multiplier,
                decayed_points
            )
            log_infraction(username, template["points"], reason)

    # ─────────────────────────────────────────────────────────────────────────────
    # 5.  Build & send thread + admin command
    # ─────────────────────────────────────────────────────────────────────────────
    forum_channel = interaction.client.get_channel(THREAD_CHANNEL_ID)
    if forum_channel is None:
        forum_channel = await interaction.client.fetch_channel(THREAD_CHANNEL_ID)
    if not isinstance(forum_channel, discord.ForumChannel):
        await interaction.followup.send("❌ Forum channel not found.", ephemeral=True)
        return

    reason_list = ", ".join(reasons)
    moderator   = interaction.user.mention
    mod_name    = interaction.user.display_name
    mode_tag    = " (ban avoided)" if avoid_mode else ""

    embed_desc = (
        f"**IP:** `{ip}`\n"
        f"**Reasons{mode_tag}:** {reason_list}\n"
        f"**Duration:** `{final_duration_string}`\n"
        f"**Ends:** <t:{unix_ts}:F>\n"
        f"**Issued By:** {moderator} ({mod_name})"
    )

    message = f"**Punishment Record**\n\n{embed_desc}"

    thread = discord.utils.get(forum_channel.threads, name=username)
    if thread:
        await thread.send(message, silent=True)
    else:
        thread = await forum_channel.create_thread(
            name=username,
            content=message,
            auto_archive_duration=60,
            reason="Punishment issued",
            allowed_mentions=discord.AllowedMentions.none()
        )

    # admin bot command (send even for avoid‑ban, same duration)
    try:
        admin_chan = await interaction.client.fetch_channel(ADMIN_BOT_CHANNEL_ID)
        await admin_chan.send(
            f"$admin banip {ip} \"{username}\" \"{reason_list}{mode_tag}\" {final_duration}"
        )
    except Exception as e:
        print("❌ Failed to send admin command:", e)

    # moderator feedback
    await interaction.followup.send(
        f"✅ **{username}** re‑banned for `{final_duration_string}` "
        f"({'Ban Avoid' if avoid_mode else 'New Ban'})\n"
        f"[[Thread]]({thread.jump_url})",
        ephemeral=True
    )


ALLOWED_CHANNELS: set[int] = {
    ADMIN_BOT_CHANNEL_ID,
}

def in_mod_channel():
    async def predicate(interaction: discord.Interaction):
        return interaction.channel_id == ADMIN_BOT_CHANNEL_ID
    return app_commands.check(predicate)


def in_allowed_channel(inter: discord.Interaction):
    cid = inter.channel_id
    # if the command was executed in a thread, also allow its parent
    parent = getattr(inter.channel, "parent_id", None)
    return cid in ALLOWED_CHANNELS or parent in ALLOWED_CHANNELS


# ──────────────────────────────────────────────────────────────────────────────
#  /banip  <username>  <ipv4>
#    • gated to the moderator channel via @in_mod_channel()
#    • immediately defers → interaction stays alive 15 min
#    • shows only the punishment‑select View (no extra text)
# ──────────────────────────────────────────────────────────────────────────────
from discord.app_commands import CheckFailure, AppCommandError

@bot.tree.command(
    name="banip",
    description="Ban a user using the points‑based system."
)
@app_commands.describe(
    username="Username of the user to ban",
    ip="IPv4 address of the user"
)
@in_mod_channel()
async def banip(interaction: discord.Interaction, username: str, ip: str):
    try:
        # keep the interaction alive so the View can answer later
        await interaction.response.defer(ephemeral=True)
        print(f"[banip] Deferred for {username} @ {ip}")
    except discord.errors.InteractionResponded:
        print(f"[banip] Interaction already responded ({username})")
        return
    except discord.errors.NotFound:
        print(f"[banip] Interaction expired / unknown ({username})")
        return

    # pull catalogue rows once
    punishment_options = get_all_punishment_options()
    if not punishment_options:
        await interaction.followup.send("No punishment templates found.", ephemeral=True)
        return

    # attach the single‑dropdown View (no leading text)
    view = PunishmentSelectView(punishment_options, username, ip)
    await interaction.followup.send(content="", view=view, ephemeral=True)


# ──────────────────────────────────────────────────────────────────────────────
#  Error handler – runs only if *banip* raised **before** it replied / deferred
# ──────────────────────────────────────────────────────────────────────────────
@banip.error
async def banip_error(interaction: discord.Interaction, error: AppCommandError):
    if isinstance(error, CheckFailure):
        await interaction.response.send_message(
            f"❌ This command can only be used in <#{ADMIN_BOT_CHANNEL_ID}>.",
            ephemeral=True
        )
    else:
        raise error


bot.run(DISCORD_TOKEN)
