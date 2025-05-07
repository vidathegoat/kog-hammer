#!/bin/bash
cd ~/kog-hammer
source .venv/bin/activate
git pull origin main
python bot.py