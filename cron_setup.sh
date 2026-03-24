#!/usr/bin/env bash
# Sets up a daily cron job to run the auction scraper.
# Run this once: bash cron_setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$(which python3)"
LOGFILE="$SCRIPT_DIR/scraper.log"

# Cron line: run at 7 AM every day
CRON_LINE="0 7 * * * cd \"$SCRIPT_DIR\" && \"$PYTHON_BIN\" scraper.py >> \"$LOGFILE\" 2>&1"

echo "Installing cron job..."
echo "  Schedule : daily at 07:00"
echo "  Command  : $PYTHON_BIN scraper.py"
echo "  Log      : $LOGFILE"
echo "  Working  : $SCRIPT_DIR"
echo ""

# Append to crontab if not already present
( crontab -l 2>/dev/null | grep -vF "scraper.py"; echo "$CRON_LINE" ) | crontab -

echo "Done. Current crontab:"
crontab -l
