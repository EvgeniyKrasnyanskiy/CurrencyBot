#!/bin/bash
# ==============================================================================
# Auto-deploy script for CurrencyBot on Linux/Debian.
# Checks for new commits in origin/main and restarts systemd service if updated.
#
# Recommended cron setup (runs every 2 minutes):
# */2 * * * * /root/projects/CurrencyBot/scripts/auto_deploy.sh >> /root/projects/CurrencyBot/logs/auto_deploy.log 2>&1
# ==============================================================================

set -e

# Determine repository root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_DIR"

# Prevent concurrent runs
LOCK_FILE="/tmp/currency_bot_autodeploy.lock"
exec 200>"$LOCK_FILE"
flock -n 200 || exit 0

# Fetch latest state from remote without merging
git fetch origin main > /dev/null 2>&1

LOCAL_HASH=$(git rev-parse HEAD)
REMOTE_HASH=$(git rev-parse origin/main)

# If hashes match, we are already up to date
if [ "$LOCAL_HASH" = "$REMOTE_HASH" ]; then
    exit 0
fi

TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")
echo "======================================================================"
echo "[$TIMESTAMP] 🚀 New updates detected: $LOCAL_HASH -> $REMOTE_HASH"
echo "[$TIMESTAMP] Pulling changes..."

git pull origin main

# Check if requirements changed and update virtualenv if active
if git diff --name-only "$LOCAL_HASH" "$REMOTE_HASH" | grep -q "^requirements.txt$"; then
    echo "[$TIMESTAMP] 📦 requirements.txt modified, updating Python packages..."
    if [ -d "venv" ]; then
        ./venv/bin/pip install -r requirements.txt --quiet
    elif [ -n "$VIRTUAL_ENV" ]; then
        pip install -r requirements.txt --quiet
    fi
fi

echo "[$TIMESTAMP] 🔄 Restarting currency_bot.service..."
systemctl restart currency_bot.service

echo "[$TIMESTAMP] ✅ Deployment complete! Service restarted on commit $REMOTE_HASH."
echo "======================================================================"
