import discord
from math import log2
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from db import (
    get_all_punishment_options,
    add_punishment,
    get_user_stage,
    get_catalog_punishment,
    fetch_user_infractions,
    calculate_total_decayed_points,
    log_infraction
)
from config import DISCORD_TOKEN, THREAD_CHANNEL_ID, ADMIN_BOT_CHANNEL_ID, GUILD_ID


# ======================================================================================================================
VERSION = "Version 0.11.1"
# ======================================================================================================================


intents = discord.Intents.default()
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Game(name=f"on {VERSION}"))
    print(f"🔨🛡️  {bot.user} is now online and watching over the realm! [{VERSION}]")
    try:
        synced = await bot.tree.sync()
        print(f"⚔️🔁  Synced: {len(synced)} slash command ready for battle!")
    except Exception as e:
        print(f"⚠️  **Error** syncing commands: {e}")

class ConfirmPunishmentButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Confirm", style=discord.ButtonStyle.green)

    async def callback(self, interaction: discord.Interaction):
        view: PunishmentSelectView = self.view

        if view.confirmed:
            if not interaction.response.is_done():
                await interaction.response.send_message("⚠️ Punishment already confirmed.", ephemeral=True)
            else:
                await interaction.followup.send("⚠️ Punishment already confirmed.", ephemeral=True)
            return

        view.confirmed = True

        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except discord.NotFound:
            print("⚠️ Confirm button interaction expired or unknown.")
            return

        await process_ban(interaction, view.selected_reasons, view.username, view.ip)

        for child in view.children:
            child.disabled = True

        try:
            await interaction.edit_original_response(view=view)
        except discord.NotFound:
            print("⚠️ Could not update original message — it may have been deleted.")


class PunishmentSelect(discord.ui.Select):
    def __init__(self, punishments):
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

    async def callback(self, interaction: discord.Interaction):
        view: PunishmentSelectView = self.view
        view.selected_reasons = self.values

        if not interaction.response.is_done():
            await interaction.response.send_message(
                f"✅ Selected: {', '.join(self.values)}.\nClick confirm to apply punishment.",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"✅ Selected: {', '.join(self.values)}.\nClick confirm to apply punishment.",
                ephemeral=True
            )


class PunishmentSelectView(discord.ui.View):
    def __init__(self, punishments, username, ip):
        super().__init__(timeout=None)
        self.username = username
        self.ip = ip
        self.selected_reasons = []
        self.confirmed = False
        self.add_item(PunishmentSelect(punishments))
        self.add_item(ConfirmPunishmentButton())

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
    decayed_points = calculate_total_decayed_points(infractions, now, test_mode=True)

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

    admin_bot_channel = bot.get_channel(ADMIN_BOT_CHANNEL_ID)
    if admin_bot_channel:
        cmd = f"$admin banip {ip} \"{username}\" \"{reason_list}\" {final_duration}"
        await admin_bot_channel.send(cmd)
        print(f"📨 Sent banip command: {cmd}")

    await interaction.followup.send(
        f"""```ansi
[2;34m[1;34m{username}[0m[2;34m[0m has been punished for [2;34m[1;34m{final_duration_value} {unit}[0m[2;34m[0m due to [2;34m[1;34m{reason_list}[0m[2;34m[0m
```
"""
        f"**[View punishment thread]({link})**"
    )


@bot.tree.command(name="banip", description="Ban a user using a points-based system.", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(username="Username of the user to ban", ip="IPv4 address of the user")
async def banip(interaction: discord.Interaction, username: str, ip: str):
    await interaction.response.defer(ephemeral=True)

    punishment_options = get_all_punishment_options()
    if punishment_options:
        view = PunishmentSelectView(punishment_options, username, ip)
        # 👇 Use followup after deferring
        await interaction.followup.send("Please select a punishment template:", view=view, ephemeral=True)
    else:
        await interaction.followup.send("No punishment templates found.", ephemeral=True)

bot.run(DISCORD_TOKEN)
