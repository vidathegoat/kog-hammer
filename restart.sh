#!/bin/bash
cd ~/kog-hammer/src
source .venv/bin/activate
pkill -f bot.py
git pull origin main

while true; do
    python3 bot.py
    echo "Bot crashed with exit code $? — restarting in 5 seconds..."
    sleep 5
done