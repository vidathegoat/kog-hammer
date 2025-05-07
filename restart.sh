#!/bin/bash
cd ~/kog-hammer
source .venv/bin/activate
git pull origin main

while true; do
    python3 bot.py
    echo "Bot crashed with exit code $? — restarting in 5 seconds..."
    sleep 5
done