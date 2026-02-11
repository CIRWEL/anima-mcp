#!/bin/bash
# Restore Lumen from Mac backup
# Run when Pi is reachable (after reflash or reboot)
# Usage: ./scripts/restore_lumen.sh [host]
#   host: lumen.local, 192.168.1.165, or IP (default: tries lumen.local then 192.168.1.165)

set -e

PI_USER="unitares-anima"
PI_HOST="${1:-lumen.local}"
BACKUP="${HOME}/backups/lumen/anima_data"
ANIMA_DIR="/Users/cirwel/projects/anima-mcp"

# Fallback hosts if primary fails
if [ "$PI_HOST" = "lumen.local" ]; then
    HOSTS="lumen.local 192.168.1.165 100.83.45.66"
else
    HOSTS="$PI_HOST"
fi

log() { echo "[$(date '+%H:%M:%S')] $1"; }

# Resolve host
RESOLVED=""
for h in $HOSTS; do
    if ping -c 1 -W 2 "$h" >/dev/null 2>&1; then
        RESOLVED="$h"
        break
    fi
done

if [ -z "$RESOLVED" ]; then
    echo "Pi unreachable. Tried: $HOSTS"
    echo "Connect Pi to network, then run: $0"
    exit 1
fi

PI_HOST="$RESOLVED"
log "Using Pi at $PI_HOST"

if [ ! -d "$BACKUP" ]; then
    echo "Backup not found: $BACKUP"
    exit 1
fi

# 1. Deploy code
log "Deploying code..."
cd "$ANIMA_DIR"
./deploy.sh --host "$PI_HOST" || { echo "Deploy failed"; exit 1; }

# 2. Restore data
log "Restoring Lumen data to ~/.anima/ on Pi..."

# Ensure .anima exists
ssh -o ConnectTimeout=10 "$PI_USER@$PI_HOST" "mkdir -p ~/.anima"

# Database (copy main file; WAL/shm are optional for restore)
if [ -f "$BACKUP/anima.db" ]; then
    scp -o ConnectTimeout=10 "$BACKUP/anima.db" "$PI_USER@$PI_HOST:~/.anima/anima.db"
    log "  anima.db restored"
else
    # Use latest dated snapshot if anima.db missing
    LATEST=$(ls -t "$(dirname "$BACKUP")"/anima_*.db 2>/dev/null | head -1)
    if [ -n "$LATEST" ]; then
        scp -o ConnectTimeout=10 "$LATEST" "$PI_USER@$PI_HOST:~/.anima/anima.db"
        log "  anima.db restored from $LATEST"
    else
        log "  WARNING: No anima.db found - Lumen will start fresh"
    fi
fi

# JSON files
for f in messages.json canvas.json knowledge.json preferences.json patterns.json self_model.json anima_history.json display_brightness.json metacognition_baselines.json; do
    if [ -f "$BACKUP/$f" ]; then
        scp -o ConnectTimeout=10 "$BACKUP/$f" "$PI_USER@$PI_HOST:~/.anima/"
        log "  $f restored"
    fi
done

# Drawings (optional, can be large)
if [ -d "$BACKUP/drawings" ]; then
    log "  Syncing drawings..."
    rsync -az -e "ssh -o ConnectTimeout=10" "$BACKUP/drawings/" "$PI_USER@$PI_HOST:~/.anima/drawings/" 2>/dev/null || log "  drawings skip (optional)"
fi

# 3. Restart services
log "Restarting services..."
ssh -o ConnectTimeout=10 "$PI_USER@$PI_HOST" "sudo systemctl restart anima-broker anima" 2>/dev/null || log "  (services may not be installed yet - run setup_pi_service.sh on Pi)"

log "Done. Check: ssh $PI_USER@$PI_HOST 'journalctl -u anima -u anima-broker -f'"
