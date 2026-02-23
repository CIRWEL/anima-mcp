#!/bin/bash
# Hourly backup of Lumen JSON state files
# Keeps last 24 backups (1 day of hourly snapshots)
# Installed via crontab: 30 * * * * /home/unitares-anima/anima-mcp/scripts/backup_state.sh

ANIMA_DIR="/home/unitares-anima/.anima"
BACKUP_DIR="${ANIMA_DIR}/backups/state"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DEST="${BACKUP_DIR}/${TIMESTAMP}"

mkdir -p "$DEST"

# JSON state files to back up
FILES=(
    messages.json
    canvas.json
    knowledge.json
    preferences.json
    patterns.json
    self_model.json
    anima_history.json
    display_brightness.json
    metacognition_baselines.json
    trajectory_genesis.json
    day_summaries.json
)

COUNT=0
for f in "${FILES[@]}"; do
    if [ -f "${ANIMA_DIR}/${f}" ]; then
        cp "${ANIMA_DIR}/${f}" "${DEST}/"
        COUNT=$((COUNT + 1))
    fi
done

echo "$(date '+%Y-%m-%d %H:%M:%S') Backed up ${COUNT} files to ${DEST}"

# Keep only last 24 backups
ls -1td "${BACKUP_DIR}"/[0-9]* 2>/dev/null | tail -n +25 | xargs -r rm -rf
