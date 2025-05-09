import discord
from math import log2
from discord.ext import commands
from discord import app_commands
from discord.app_commands import CheckFailure, AppCommandError
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
    get_latest_punishment,
    get_previous_reasons_for_user
)
from config import DISCORD_TOKEN, THREAD_CHANNEL_ID, ADMIN_BOT_CHANNEL_ID, GUILD_ID


# ======================================================================================================================

VERSION = "Version 1.2.13"

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
        guild = discord.Object(id=GUILD_ID)
        print(guild)
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

        for child in self.view.children:       # disable every component
            child.disabled = True

        try:                                   # update the original message
            await interaction.edit_original_response(view=self.view)
        except discord.NotFound:               # message was deleted / timed‑out
            pass


class PunishmentSelectView(discord.ui.View):
    def __init__(self, punishments, username, ip):
        super().__init__(timeout=None)
        self.add_item(PunishmentSelect(punishments, username, ip))


class PunishmentAvoidSelect(discord.ui.Select):
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


        super().__init__(
            placeholder="Select a reason to re-apply",
            min_values=1,
            max_values=len(options),
            options=options
        )
        self.username = username
        self.ip = ip

    async def callback(self, interaction: discord.Interaction):
        reason = self.values[0]
        prev = get_latest_punishment(self.username, reason)

        if not prev:
            await interaction.response.send_message(
                f"⚠️ No previous punishment found for `{reason}`.", ephemeral=True
            )
            return

        # Compute ban time
        now = datetime.now(ZoneInfo("America/New_York"))
        unit = prev.get("unit")
        if not unit:
            catalog = get_catalog_punishment(prev["reason"], prev["stage"])
            unit = catalog["unit"] if catalog else "days"
        base = prev.get("amount") or prev.get("base_days")  # use fallback
        hours = base * {"minutes": 1 / 60, "hours": 1, "days": 24, "weeks": 168}.get(unit, 24)
        end = now + timedelta(hours=hours)
        unix_timestamp = int(end.timestamp())
        final_duration = f"{int(base)}{unit[0]}"
        final_duration_value = int(base)
        final_duration_string = f"{final_duration_value} {unit}"

        # Apply punishment
        add_punishment(
            self.username,
            self.ip,
            reason,
            base,
            0,
            prev["multiplier"],
            prev["total_points_at_ban"],
            explicit_stage=prev["stage"]
        )

        # Build thread text
        moderator = interaction.user.mention
        mod_name = interaction.user.display_name
        reason_list = reason
        message = (
            f"**IP Address:** {self.ip}\n"
            f"**Reasons:** {reason_list} [AVOID]\n\n"
            f"**Base Duration:** {base} {unit}\n"
            f"**Multiplier Applied:** x{prev['multiplier']:.2f}\n\n"
            f"**Points Added:** 0  |  **Decayed Total:** {prev['total_points_at_ban']}\n\n"
            f"**Final Duration:** `{final_duration_string}`\n"
            f"**Ban Ends:** <t:{unix_timestamp}:F>\n\n"
            f"**Issued By:** {moderator} ({mod_name})"
        )

        # Send to forum
        forum_channel = interaction.client.get_channel(THREAD_CHANNEL_ID) \
                        or await interaction.client.fetch_channel(THREAD_CHANNEL_ID)

        thread = discord.utils.get(forum_channel.threads, name=self.username)
        if thread:
            await thread.send(message, silent=True)
            thread_link = thread.id
        else:
            thread = await forum_channel.create_thread(
                name=self.username,
                content=message,
                auto_archive_duration=60,
                reason="Punishment issued",
                allowed_mentions=discord.AllowedMentions.none()
            )
            thread_link = thread.thread.id

        link = f"https://discord.com/channels/{interaction.guild_id}/{thread_link}"

        # Admin bot command
        try:
            admin_chan = await interaction.client.fetch_channel(ADMIN_BOT_CHANNEL_ID)
            await admin_chan.send(
                f"$admin banip {self.ip} \"{self.username}\" \"{reason_list} [AVOID]\" {final_duration}"
            )
        except Exception as e:
            print("❌ Failed to send admin avoid command:", e)

        # Respond to moderator
        await interaction.response.send_message(
            f"""```ansi
[2;34m[1;34m{self.username}[0m[2;34m[0m has been re-banned for [2;34m[1;34m{final_duration_value} {unit}[0m[2;34m[0m due to [2;34m[1;34m{reason_list} [AVOID][0m[2;34m[0m
```\n"""
            f"**[View punishment thread]({link})**"
        )

        # Disable dropdown
        self.disabled = True
        await self.view.message.edit(view=self.view)


class PunishmentAvoidView(discord.ui.View):
    def __init__(self, reasons, username, ip):
        super().__init__(timeout=None)
        self.add_item(PunishmentAvoidSelect(reasons, username, ip))



class PunishmentAvoidView(discord.ui.View):
    def __init__(self, reasons, username, ip):
        super().__init__(timeout=None)
        self.add_item(PunishmentAvoidSelect(reasons, username, ip))


async def process_ban(interaction, reasons, username, ip):
    total_amount = 0
    total_points = 0
    unit = "days"

    for reason in reasons:
        stage = get_user_stage(username, reason)
        template = get_catalog_punishment(reason, stage)
        if not template:
            await interaction.followup.send(f"⚠️ No template found for `{reason}` at stage {stage}.", ephemeral=True)
            return
        total_amount += template['amount']
        total_points += template['points']
        unit = template.get('unit', unit)

    now = datetime.now(ZoneInfo("America/New_York"))
    infractions = fetch_user_infractions(username)
    decayed_points = calculate_total_decayed_points(infractions, now, test_mode=False)

    multiplier = max(log2(decayed_points + 1), 1)

    unit_abbrev = {"minutes": "m", "hours": "h", "days": "d", "weeks": "w"}.get(unit, "d")
    final_duration_value = int(total_amount * multiplier)
    final_duration = f"{final_duration_value}{unit_abbrev}"
    final_duration_string = f"{final_duration_value} {unit}"

    match unit:
        case "minutes": duration_converted = total_amount / 60
        case "hours": duration_converted = total_amount
        case "days": duration_converted = total_amount * 24
        case "weeks": duration_converted = total_amount * 168

    ban_end = now + timedelta(hours=duration_converted)
    unix_timestamp = int(ban_end.timestamp())

    for reason in reasons:
        stage = get_user_stage(username, reason)
        template = get_catalog_punishment(reason, stage)
        add_punishment(username, ip, reason, template['amount'], template['points'], multiplier, decayed_points)
        log_infraction(username, template['points'], reason)

    forum_channel = bot.get_channel(THREAD_CHANNEL_ID)
    if forum_channel is None:
        forum_channel = await bot.fetch_channel(THREAD_CHANNEL_ID)

    if not isinstance(forum_channel, discord.ForumChannel):
        print("❌ Forum channel not found or incorrect type.")
        return

    moderator = interaction.user.mention
    mod_name = interaction.user.display_name
    reason_list = ", ".join(reasons)

    message = (
        f"**IP Address:** {ip}\n"
        f"**Reasons:** {reason_list}\n\n"
        f"**Base Duration Sum:** {total_amount} {unit}\n"
        f"**Multiplier Applied:** x{multiplier:.2f}\n\n"
        f"**Points Added:** {total_points}  |  **Decayed Total:** {decayed_points}\n\n"
        f"**Final Duration:** `{final_duration_string}`\n"
        f"**Ban Ends:** <t:{unix_timestamp}:F>\n\n"
        f"**Issued By:** {moderator} ({mod_name})"
    )

    thread = discord.utils.get(forum_channel.threads, name=username)
    if thread:
        await thread.send(message, silent=True)
        thread_link = thread.id
    else:
        thread = await forum_channel.create_thread(
            name=username,
            content=message,
            auto_archive_duration=60,
            reason="Punishment issued",
            allowed_mentions=discord.AllowedMentions.none()
        )
        thread_link = thread.thread.id

    link = f"https://discord.com/channels/{interaction.guild_id}/{thread_link}"

    cmd = f"$admin banip {ip} \"{username}\" \"{reason_list}\" {final_duration}"
    try:
        admin_bot_channel = await bot.fetch_channel(ADMIN_BOT_CHANNEL_ID)
        print(f"[Debug] Fetched admin channel: {admin_bot_channel}")
        await admin_bot_channel.send(cmd)
        print(f"📨 Sent banip command: {cmd}")
    except Exception as e:
        print(f"❌ Failed to send admin command: {e}")

    try:
        await interaction.followup.send(
            f"""```ansi
[2;34m[1;34m{username}[0m[2;34m[0m has been punished for [2;34m[1;34m{final_duration_value} {unit}[0m[2;34m[0m due to [2;34m[1;34m{reason_list}[0m[2;34m[0m
```
"""
            f"**[View punishment thread]({link})**"
        )
    except discord.errors.NotFound:
        print("⚠️ Could not send followup message — interaction expired.")


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


@bot.tree.command(name="banip", description="Ban a user using a points-based system.")
@app_commands.describe(username="Username of the user to ban", ip="IPv4 address of the user")
@in_mod_channel()
async def banip(interaction: discord.Interaction, username: str, ip: str):
    try:
        await interaction.response.defer(ephemeral=True)
        print(f"[banip] Interaction deferred successfully for {username} @ {ip}")
    except discord.errors.InteractionResponded:
        print(f"[banip] ⚠️ Interaction already responded to for {username} @ {ip}")
        return
    except discord.errors.NotFound:
        print(f"[banip] ⚠️ Interaction expired or unknown for {username} @ {ip}")
        return

    punishment_options = get_all_punishment_options()
    print(f"[banip] Fetched punishment options: {len(punishment_options)} found")

    if punishment_options:
        view = PunishmentSelectView(punishment_options, username, ip)
        await interaction.followup.send(content="", view=view, ephemeral=True)
    else:
        await interaction.followup.send("No punishment templates found.", ephemeral=True)


@banip.error
async def banip_error(interaction: discord.Interaction, error: AppCommandError):
    """Runs only if banip raised an exception *before* it replied."""
    if isinstance(error, CheckFailure):
        # the channel gate failed
        await interaction.response.send_message(
            "❌ This command can only be used in <#{}>.".format(ADMIN_BOT_CHANNEL_ID),
            ephemeral=True
        )
    else:
        # re‑raise or log other kinds of errors
        raise error


@bot.tree.command(name="avoid", description="Re-ban a user who is avoiding ban.")
@app_commands.describe(username="Username of the user to ban", ip="IPv4 address of the user")
@in_mod_channel()
async def avoid(interaction: discord.Interaction, username: str, ip: str):
    try:
        await interaction.response.defer(ephemeral=True)
        print(f"[avoid] Interaction deferred successfully for {username} @ {ip}")
    except discord.errors.InteractionResponded:
        print(f"[avoid] ⚠️ Interaction already responded to for {username} @ {ip}")
        return
    except discord.errors.NotFound:
        print(f"[avoid] ⚠️ Interaction expired or unknown for {username} @ {ip}")
        return

    punishment_options = get_all_punishment_options()
    print(f"[avoid] Fetched punishment options: {len(punishment_options)} found")

    if punishment_options:
        view = PunishmentAvoidView(punishment_options, username, ip)
        message = await interaction.followup.send(content="", view=view, ephemeral=True)
        view.message = message
    else:
        await interaction.followup.send("No punishment templates found.", ephemeral=True)

@avoid.error
async def avoid_error(interaction: discord.Interaction, error: AppCommandError):
    """Runs only if avoid raised an exception *before* it replied."""
    if isinstance(error, CheckFailure):
        # the channel gate failed
        await interaction.response.send_message(
            "❌ This command can only be used in <#{}>.".format(ADMIN_BOT_CHANNEL_ID),
            ephemeral=True
        )
    else:
        # re‑raise or log other kinds of errors
        raise error

bot.run(DISCORD_TOKEN)
