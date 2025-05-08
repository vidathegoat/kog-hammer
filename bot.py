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

VERSION = "Version 1.2.7"

# ======================================================================================================================


# ─── helpers ─────────────────────────────────────────────────────────────
UNIT_TO_HOURS = {"minutes": 1/60, "hours": 1, "days": 24, "weeks": 168}

def hours_from(amount: float, unit: str) -> float:
    """Convert catalogue amount+unit to hours."""
    return amount * UNIT_TO_HOURS[unit]

def pick_unit(units: set[str]) -> str:
    """Return the ‘largest’ unit present so display is stable."""
    for u in ("weeks", "days", "hours", "minutes"):
        if u in units:
            return u
    return "hours"
# ─────────────────────────────────────────────────────────────────────────


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

        # ─── NEW: lock the UI so it can’t be used again ─────────────────
        for child in self.view.children:  # disable every component
            child.disabled = True

        try:  # update the original message
            await interaction.edit_original_response(view=self.view)
        except discord.NotFound:  # message was deleted / timed‑out
            pass

class PunishmentSelectView(discord.ui.View):
    def __init__(self, punishments, username, ip):
        super().__init__(timeout=None)
        self.add_item(PunishmentSelect(punishments, username, ip))

async def process_ban(interaction, reasons, username, ip):
    """Normal ban **or** re‑ban when '__AVOID__' is present."""
    # ── split the special flag ───────────────────────────────────────────
    avoid_mode = "__AVOID__" in reasons
    reasons    = [r for r in reasons if r != "__AVOID__"]

    if not reasons:
        await interaction.followup.send(
            "⚠ Select at least one offence together with **Avoid Ban**.",
            ephemeral=True
        )
        return

    # helpers / accumulators
    total_hours       = 0.0
    total_points      = 0
    seen_units        = set()
    reused_multiplier = 1

    # ── collect data offence by offence ──────────────────────────────────
    for reason in reasons:
        if avoid_mode:                                    # re‑apply previous ban
            prev = get_latest_punishment(username, reason)
            if not prev:
                await interaction.followup.send(
                    f"⚠ No previous ban found for **{reason}** – cannot avoid.",
                    ephemeral=True
                )
                return

            unit = prev.get("unit") or "days"
            seen_units.add(unit)
            total_hours       += hours_from(prev["base_days"], unit)
            reused_multiplier  = max(reused_multiplier, prev["multiplier"])

        else:                                             # fresh catalogue ban
            stage = get_user_stage(username, reason)
            tmpl  = get_catalog_punishment(reason, stage)
            if not tmpl:
                await interaction.followup.send(
                    f"⚠ No template for `{reason}` at stage {stage}.",
                    ephemeral=True
                )
                return

            seen_units.add(tmpl["unit"])
            total_hours  += hours_from(tmpl["amount"], tmpl["unit"])
            total_points += tmpl["points"]

    # ── multiplier ───────────────────────────────────────────────────────
    if avoid_mode or len(reasons) == 1:        # ← multiplier **disabled** for single‑offence bans
        multiplier     = reused_multiplier if avoid_mode else 1
        decayed_points = 0                 if avoid_mode else 0  # just display; unused
    else:
        now            = datetime.now(ZoneInfo("America/New_York"))
        decayed_points = calculate_total_decayed_points(
            fetch_user_infractions(username), now, test_mode=True
        )
        multiplier     = max(log2(decayed_points + 1), 1)

    final_hours          = int(total_hours * multiplier)

    # ── display values ───────────────────────────────────────────────────
    unit_display         = pick_unit(seen_units)
    value_display        = int(final_hours / UNIT_TO_HOURS[unit_display])
    unit_abbrev          = unit_display[0]       # w|d|h|m
    final_duration       = f"{value_display}{unit_abbrev}"
    final_duration_str   = f"{value_display} {unit_display}"

    # timestamps
    now     = datetime.now(ZoneInfo("America/New_York"))
    ban_end = now + timedelta(hours=final_hours)
    unix_ts = int(ban_end.timestamp())
    # ── build thread text exactly like before (only vars changed) ───────
    forum_channel = interaction.client.get_channel(THREAD_CHANNEL_ID) \
                    or await interaction.client.fetch_channel(THREAD_CHANNEL_ID)
    if not isinstance(forum_channel, discord.ForumChannel):
        await interaction.followup.send("❌ Forum channel not found.", ephemeral=True)
        return

    reason_list = ", ".join(reasons)
    mode_tag    = " [AVOID]" if avoid_mode else ""
    multiplier_txt = multiplier if not avoid_mode else reused_multiplier

    embed_desc = (
        f"**IP Address:** `{ip}`\n"
        f"**Reasons{mode_tag}:** {reason_list}\n\n"
        
        f"**Base Duration Sum:** `{total_hours:.1f} hours`\n"
        f"**Multiplier Applied:** `x{multiplier_txt:.2f}`\n\n"
        
        f"**Points Added:** {total_points}  |  **Decayed Total:** {decayed_points}\n\n"
        
        f"**Final Duration:** `{final_duration_str}`\n"
        f"**Ends:** <t:{unix_ts}:F>\n"
        f"**Issued By:** {interaction.user.mention} [{interaction.user.display_name}]"
    )

    thread = discord.utils.get(forum_channel.threads, name=username)
    if thread:
        await thread.send(embed_desc, silent=True)
        thread_link = thread.id
    else:
        thread = await forum_channel.create_thread(
            name=username,
            content=embed_desc,
            auto_archive_duration=60,
            reason="Punishment issued",
            allowed_mentions=discord.AllowedMentions.none()
        )

        thread_link = thread.thread.id

    link = f"https://discord.com/channels/{interaction.guild.id}/{forum_channel.id}/{thread_link}"

    try:
        admin_chan = await interaction.client.fetch_channel(ADMIN_BOT_CHANNEL_ID)
        await admin_chan.send(
            f"$admin banip {ip} \"{username}\" \"{reason_list}{mode_tag}\" {final_duration}"
        )
    except Exception as e:
        print("❌ Failed to send admin command:", e)

    # moderator feedback
    await interaction.followup.send(
        f"""```ansi
[2;34m[1;34m{username}[0m[2;34m[0m has been punished for [2;34m[1;34m{final_duration_str}[0m[2;34m[0m due to [2;34m[1;34m{reason}[0m[2;34m[0m
```\n"""
    f"**[View punishment thread]({link})**"
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
