#!/bin/bash
# Automated backup of Lumen's persistent state from Pi to Mac.
# Runs on Mac via launchd (see scripts/com.unitares.lumen-backup.plist).
# Keeps last 7 dated snapshots + a 'latest' symlink.
#
# What's backed up:
#   ~/.anima/anima.db         — all memories, learning, calibration
#   ~/.anima/*.json           — identity, schema, config
#   ~/anima-mcp/canvas.json   — current drawing state
#   ~/anima-mcp/anima_config.yaml

PI_USER="unitares-anima"
PI_HOST="100.95.133.98"  # Tailscale IP (stable)
PI_SSH_KEY="$HOME/.ssh/id_ed25519_pi"
BACKUP_ROOT="$HOME/lumen-backups"
LOG="$BACKUP_ROOT/backup.log"
KEEP_DAYS=7

mkdir -p "$BACKUP_ROOT"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S'): $1" | tee -a "$LOG"
}

# Check if Pi is reachable before attempting backup
if ! ssh -i "$PI_SSH_KEY" -o ConnectTimeout=10 -o StrictHostKeyChecking=no \
        "$PI_USER@$PI_HOST" "echo ok" &>/dev/null; then
    log "Pi unreachable — skipping backup"
    exit 0
fi

SNAPSHOT="$BACKUP_ROOT/$(date '+%Y-%m-%d_%H%M')"
mkdir -p "$SNAPSHOT"

# Pull critical state directories
rsync -az --delete \
    -e "ssh -i $PI_SSH_KEY -o StrictHostKeyChecking=no" \
    "$PI_USER@$PI_HOST:/home/$PI_USER/.anima/" \
    "$SNAPSHOT/anima/" 2>> "$LOG"

rsync -az \
    -e "ssh -i $PI_SSH_KEY -o StrictHostKeyChecking=no" \
    "$PI_USER@$PI_HOST:/home/$PI_USER/anima-mcp/canvas.json" \
    "$PI_USER@$PI_HOST:/home/$PI_USER/anima-mcp/anima_config.yaml" \
    "$SNAPSHOT/" 2>> "$LOG"

# Update 'latest' symlink
ln -sfn "$SNAPSHOT" "$BACKUP_ROOT/latest"

log "Backup complete → $SNAPSHOT"

# Prune snapshots older than KEEP_DAYS
find "$BACKUP_ROOT" -maxdepth 1 -type d -name "20*" \
    -mtime +$KEEP_DAYS -exec rm -rf {} + 2>/dev/null

# Keep log from growing unbounded
tail -200 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
