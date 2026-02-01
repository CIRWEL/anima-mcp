#!/bin/bash
# Hourly backup of anima.db
# Keeps last 24 backups (1 day of hourly snapshots)
# Installed via crontab: 0 * * * * /home/unitares-anima/anima-mcp/scripts/backup_db.sh

DB_PATH="/home/unitares-anima/anima-mcp/anima.db"
BACKUP_DIR="/home/unitares-anima/.anima/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

if [ -f "$DB_PATH" ]; then
    cp "$DB_PATH" "$BACKUP_DIR/anima.db.$TIMESTAMP"

    # Keep only last 24 backups
    ls -1t "$BACKUP_DIR"/anima.db.* 2>/dev/null | tail -n +25 | xargs -r rm
fi
