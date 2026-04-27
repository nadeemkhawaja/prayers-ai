#!/bin/bash
set -e

# Export env vars so cron can see them
printenv | grep -E '^(GITHUB_TOKEN|GITHUB_REPO|REPO_PATH)' > /etc/environment

# Run scraper immediately on start
echo "[entrypoint] Running scraper now..."
python /scraper/scrape.py

# Start cron daemon in foreground (keeps container alive for scheduled runs)
echo "[entrypoint] Starting cron daemon (runs every 15 days on 1st & 15th at 4 AM)..."
cron -f
