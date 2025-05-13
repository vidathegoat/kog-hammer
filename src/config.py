# config.py

from dotenv import load_dotenv
import os

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SUPABASE_URL=os.getenv("SUPABASE_URL")
SUPABASE_KEY=os.getenv("SUPABASE_KEY")
THREAD_CHANNEL_ID=int(os.getenv("THREAD_CHANNEL_ID"))
ADMIN_BOT_CHANNEL_ID=int(os.getenv("ADMIN_BOT_CHANNEL_ID"))
GUILD_ID=int(os.getenv("GUILD_ID"))