import discord
from discord.ext import commands
from discord import app_commands
from config import DISCORD_TOKEN, THREAD_CHANNEL_ID
from db import add_punishment, get_user_points

intents = discord.Intents.default()
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"{bot.user} is now online!")
    try:
        synced = await bot.tree.sync()
        print(f"Synced: {len(synced)} slash commands.")
    except Exception as e:
        print(f"Error syncing commands: {e}")

@bot.tree.command(name="punish", description="Punish a user using a points-based system.")
@app_commands.describe(
    user="User to punish",
    reason="Reason for punishment",
    base_days="Base punishment duration in days",
    points="Points to assign"
)
async def punish(
        interaction: discord.Interaction,
        user: discord.User,
        reason: str,
        base_days: int,
        points: int
):
    await interaction.response.defer(ephemeral=True)

    current_points = get_user_points(str(user.id))
    total_points = current_points + points
    multiplier = total_points / 2
    final_duration = add_punishment(str(user.id), reason, base_days, points, multiplier)

    thread_channel = bot.get_channel(THREAD_CHANNEL_ID)
    if thread_channel:
        await thread_channel.send(
            f"🔨 **Punishment Issued**\n"
            f"👤 User: {user.mention}\n"
            f"📝 Reason: `{reason}`\n"
            f"📆 Base: {base_days} day | Points: {points} (TOTAL: {total_points})\n"
            f"🔁 Multiplier: x{multiplier:.2f} →\n"
            f"FINAL: **{final_duration} days**"
        )

    await interaction.followup.send(
        f"{user.mention} has be punished for **{final_duration}** days due to **{reason}**.", ephemeral=True
    )

bot.run(DISCORD_TOKEN)
