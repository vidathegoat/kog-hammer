import discord
from discord.ext import commands
from discord import app_commands
from config import DISCORD_TOKEN, THREAD_CHANNEL_ID, ADMIN_BOT_CHANNEL_ID
from db import add_punishment, get_user_points

intents = discord.Intents.default()
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"🔨 🛡️ {bot.user} is now online and watching over the realm!")
    try:
        synced = await bot.tree.sync()
        print(f"⚔️ 🔁 Synced: {len(synced)} slash command ready for battle!")
    except Exception as e:
        print(f"⚠️  **Error** syncing commands: {e}")


@bot.tree.command(name="ban", description="Ban a user using a points-based system.")
@app_commands.describe(
    username="User to ban",
    ip="User's IPv4",
    reason="Reason for ban",
    base_days="Base ban duration in days",
    points="Points to assign"
)
async def ban(
        interaction: discord.Interaction,
        username: str,
        ip: str,
        reason: str,
        base_days: int,
        points: int
):
    await interaction.response.defer(ephemeral=True)

    current_points = get_user_points(username)
    total_points = current_points + points
    multiplier = total_points / 2
    if multiplier < 1:
        multiplier = 1
    final_duration = add_punishment(username, ip, reason, base_days, points, multiplier)

    # Get the forum channel
    forum_channel = bot.get_channel(THREAD_CHANNEL_ID)

    if not isinstance(forum_channel, discord.ForumChannel):
        print("Error: Forum channel not found or not a ForumChannel.")
        return

    # Format punishment message
    thread_message = (
        f"🔨  ### Ban Issued\n"
        f"👤  **Username:** {username}\n"
        f"🌐  **IP Address:** {ip}\n"
        f"📝  **Reason:** `{reason}`\n"
        f"📆  **Base:** {base_days} day | *Points: {points} (TOTAL: {total_points})*\n"
        f"🔁  **Multiplier:** x{multiplier:.2f} →\n"
        f"FINAL: **{final_duration} days**"
    )

    # Check for an existing thread with the user's name
    existing_thread = discord.utils.get(forum_channel.threads, name=username)

    if existing_thread:
        thread = existing_thread
        await thread.send(thread_message)
        print(f"ℹ️ Existing thread found for {username}, message sent.")
    else:
        thread = await forum_channel.create_thread(
            name=username,
            content=thread_message,
            auto_archive_duration=60,
            reason="Punishment issued"
        )
        print(f"🧵 New thread created for {username}, message sent.")

    # Send a ban command message to the admin bot
    admin_bot_channel = bot.get_channel(ADMIN_BOT_CHANNEL_ID)
    if admin_bot_channel:
        ip_address = f"{ip}"
        duration_str = f"{final_duration}d"
        banip_command = f"$admin banip {ip_address} \"{username}\" \"{reason}\" {duration_str}"
        await admin_bot_channel.send(banip_command)
        print(f"📨 Sent banip command to admin bot: {banip_command}")
    else:
        print("⚠️ Could not find the admin bot channel.")

    # Send ephemeral confirmation
    await interaction.followup.send(
        f"**{username}** has been punished for **{final_duration} days** due to **{reason}**.",
        ephemeral=True
    )


bot.run(DISCORD_TOKEN)