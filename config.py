# config.py

from dotenv import load_dotenv
import os

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SUPABASE_URL = "https://wftngeyasceytcpyzctk.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6IndmdG5nZXlhc2NleXRjcHl6Y3RrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDYwNTEwMTgsImV4cCI6MjA2MTYyNzAxOH0.z4bcEKeQU9u1BUDhIbrYJW-kQfmCLR7OwUCXRE9C1lg"
THREAD_CHANNEL_ID = 1