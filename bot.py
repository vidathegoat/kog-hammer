import discord
from math import log2
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from db import (
    get_all_punishment_options,
    get_user_points,
    add_punishment,
    get_user_stage,
    get_catalog_punishment
)
from config import DISCORD_TOKEN, THREAD_CHANNEL_ID, ADMIN_BOT_CHANNEL_ID, GUILD_ID

intents = discord.Intents.default()
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"🔨🛡️  {bot.user} is now online and watching over the realm!")
    try:
        synced = await bot.tree.sync()
        print(f"⚔️🔁  Synced: {len(synced)} slash command ready for battle!")
    except Exception as e:
        print(f"⚠️  **Error** syncing commands: {e}")

class PunishmentSelect(discord.ui.Select):
    def __init__(self, punishments, username, ip):
        # Get only unique reasons
        unique_reasons = {}
        for punishment in punishments:
            if punishment['reason'] not in unique_reasons:
                unique_reasons[punishment['reason']] = punishment

        unique_punishments_list = list(unique_reasons.values())[:25]

        MAX_VALUE_LENGTH = 100

        options = []
        for punishment in unique_punishments_list:
            label = punishment['reason']
            if len(label) > 50:
                label = label[:47] + "..."

            value = punishment['reason']
            if len(value) > MAX_VALUE_LENGTH:
                value = value[:MAX_VALUE_LENGTH]

            options.append(
                discord.SelectOption(
                    label=label,
                    value=value
                )
            )

        super().__init__(placeholder="Choose a punishment reason", min_values=1, max_values=1, options=options)
        self.username = username
        self.ip = ip

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        selected_reason = self.values[0]
        await process_ban(interaction, selected_reason, self.username, self.ip)

        self.disabled = True
        for child in self.view.children:
            child.disabled = True
        await interaction.message.edit(view=self.view)

class PunishmentSelectView(discord.ui.View):
    def __init__(self, punishments, username, ip):
        super().__init__(timeout=None)
        self.add_item(PunishmentSelect(punishments, username, ip))

async def process_ban(interaction, reason, username, ip):
    # Determine current stage and next stage
    current_stage = get_user_stage(username, reason)
    next_stage = current_stage  # stage already +1 in get_user_stage

    # Fetch punishment template for the reason and stage
    template = get_catalog_punishment(reason, next_stage)
    if not template:
        await interaction.followup.send(
            f"⚠️ No template found for `{reason}` at stage {next_stage}.",
            ephemeral=True
        )
        return

    amount = template['amount']
    points = template['points']
    unit = template.get('unit', 'days').lower()

    # Fetch current total points BEFORE adding this punishment
    current_points = get_user_points(username)
    multiplier = max(log2(current_points + 1), 1)

    # Calculate final duration
    unit_abbrev = {"minutes": "m", "hours": "h", "days": "d", "weeks": "w"}.get(unit, "d")
    final_duration_value = int(amount * multiplier)
    final_duration = f"{final_duration_value}{unit_abbrev}"
    final_duration_string = f"{final_duration_value} {unit}"

    match unit:
        case "minutes":
            duration_converted = amount / 60
        case "hours":
            duration_converted = amount
        case "days":
            duration_converted = amount * 24
        case "weeks":
            duration_converted = amount * 168



    now = datetime.now(ZoneInfo("America/New_York"))
    ban_end = now + timedelta(hours=duration_converted)

    unix_timestamp = int(ban_end.timestamp())

    # Add punishment record (AFTER calculating duration)
    add_punishment(username, ip, reason, amount, points, multiplier)

    # Total points after adding this one (for display only)
    total_points = current_points + points

    # Send to forum thread
    forum_channel = bot.get_channel(THREAD_CHANNEL_ID)
    if not isinstance(forum_channel, discord.ForumChannel):
        print("❌ Forum channel not found or incorrect type.")
        return

    moderator = interaction.user.mention
    mod_name = interaction.user.display_name

    message = (
        f"**IP Address:** {ip}\n"
        f"**Reason:** {reason}\n\n"
        
        f"**Base Duration:** {amount} {unit}\n"
        f"**Multiplier Applied:** x{multiplier:.2f}\n\n"
        f"**Points Added:** {points}  |  **Total:** {total_points}\n\n"
        
        f"**Final Duration:** `{final_duration_string}`\n"
        f"**Ban Ends:** <t:{unix_timestamp}:F>\n\n"

        f"**Issued By:** {moderator} ({mod_name})"
    )

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

    thread_link = thread.thread.id
    link = f"https://discord.com/channels/{interaction.guild_id}/{thread_link}"

    # Send banip command
    admin_bot_channel = bot.get_channel(ADMIN_BOT_CHANNEL_ID)
    if admin_bot_channel:
        cmd = f"$admin banip {ip} \"{username}\" \"{reason}\" {final_duration}"
        await admin_bot_channel.send(cmd)
        print(f"📨 Sent banip command: {cmd}")

    await interaction.followup.send(
        f"""```ansi
[2;31m[1;31m{username}[0m[2;31m[0m has been punished for [2;31m[1;31m{final_duration_value} {unit}[0m[2;31m[0m due to [2;31m[1;31m{reason}[0m[2;31m[0m
```\n"""
    f"**[View punishment thread]({link})**"
    )

@bot.tree.command(name="banip", description="Ban a user using a points-based system.")
@app_commands.describe(username="Username of the user to ban", ip="IPv4 address of the user")
async def banip(interaction: discord.Interaction, username: str, ip: str):
    punishment_options = get_all_punishment_options()
    if punishment_options:
        view = PunishmentSelectView(punishment_options, username, ip)
        await interaction.response.send_message("Please select a punishment template:", view=view)
    else:
        await interaction.response.send_message("No punishment templates found.", ephemeral=True)

bot.run(DISCORD_TOKEN)
