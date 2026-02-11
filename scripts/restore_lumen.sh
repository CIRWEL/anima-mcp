#!/bin/bash
# Restore Lumen from Mac backup — full post-reflash recovery
# Run when Pi is reachable (after reflash or reboot)
# Usage: ./scripts/restore_lumen.sh [host]
#   host: lumen.local, 192.168.1.165, or IP (default: tries lumen.local then 192.168.1.165)
#
# Fixes: installs adafruit-blinka (display/LEDs), server-only mode (no broker DB contention)

set -e

PI_USER="unitares-anima"
PI_HOST="${1:-lumen.local}"
BACKUP="${HOME}/backups/lumen/anima_data"
ANIMA_DIR="/Users/cirwel/projects/anima-mcp"
SSH_KEY="${HOME}/.ssh/id_ed25519_pi"
SSH_OPTS="-i ${SSH_KEY} -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new"

# Fallback hosts if primary fails
if [ "$PI_HOST" = "lumen.local" ]; then
    HOSTS="lumen.local 192.168.1.165 100.103.208.117"
else
    HOSTS="$PI_HOST"
fi

log() { echo "[$(date '+%H:%M:%S')] $1"; }

# Resolve host
RESOLVED=""
for h in $HOSTS; do
    if ping -c 1 -W 3 "$h" >/dev/null 2>&1; then
        RESOLVED="$h"
        break
    fi
done

if [ -z "$RESOLVED" ]; then
    echo "Pi unreachable. Tried: $HOSTS"
    echo "Boot Pi, connect to WiFi, then run: $0 [host]"
    exit 1
fi

PI_HOST="$RESOLVED"
log "Using Pi at $PI_HOST"

# Remove stale host key (reflash = new key)
ssh-keygen -R "$PI_HOST" -f ~/.ssh/known_hosts 2>/dev/null || true

if [ ! -d "$BACKUP" ]; then
    echo "Backup not found: $BACKUP"
    exit 1
fi

# 1. Deploy code
log "Deploying code..."
cd "$ANIMA_DIR"
PI_HOST="$PI_HOST" ./deploy.sh --host "$PI_HOST" --no-restart 2>/dev/null || true
rsync -avz -e "ssh $SSH_OPTS" \
    --exclude='.venv' --exclude='*.db' --exclude='*.log' --exclude='__pycache__' --exclude='.git' \
    ./ "$PI_USER@$PI_HOST:~/anima-mcp/" || { echo "Deploy failed"; exit 1; }

# 2. Restore data
log "Restoring Lumen data to ~/.anima/ on Pi..."
ssh $SSH_OPTS "$PI_USER@$PI_HOST" "mkdir -p ~/.anima"

# Prefer clean snapshot if main backup is corrupted (common after hot copy)
DB_TO_RESTORE=""
if [ -f "$BACKUP/anima.db" ]; then
    if sqlite3 "$BACKUP/anima.db" "PRAGMA integrity_check;" 2>/dev/null | grep -q "^ok$"; then
        DB_TO_RESTORE="$BACKUP/anima.db"
    else
        log "  anima_data/anima.db corrupted, using dated snapshot"
    fi
fi
if [ -z "$DB_TO_RESTORE" ]; then
    LATEST=$(ls -t "$(dirname "$BACKUP")"/anima_*.db 2>/dev/null | head -1)
    if [ -n "$LATEST" ]; then
        DB_TO_RESTORE="$LATEST"
    fi
fi
if [ -n "$DB_TO_RESTORE" ]; then
    scp $SSH_OPTS "$DB_TO_RESTORE" "$PI_USER@$PI_HOST:~/.anima/anima.db"
    log "  anima.db restored from $(basename "$DB_TO_RESTORE")"
else
    log "  WARNING: No anima.db found - Lumen will start fresh"
fi

for f in messages.json canvas.json knowledge.json preferences.json patterns.json self_model.json anima_history.json display_brightness.json metacognition_baselines.json; do
    if [ -f "$BACKUP/$f" ]; then
        scp $SSH_OPTS "$BACKUP/$f" "$PI_USER@$PI_HOST:~/.anima/"
        log "  $f restored"
    fi
done

if [ -d "$BACKUP/drawings" ]; then
    log "  Syncing drawings..."
    rsync -az -e "ssh $SSH_OPTS" "$BACKUP/drawings/" "$PI_USER@$PI_HOST:~/.anima/drawings/" 2>/dev/null || log "  drawings skip (optional)"
fi

# 3. Install Python deps (adafruit-blinka for display/LEDs/sensors)
log "Installing Pi dependencies (adafruit-blinka, etc.)..."
ssh $SSH_OPTS "$PI_USER@$PI_HOST" "cd ~/anima-mcp && python3 -m venv .venv 2>/dev/null || true && source .venv/bin/activate && pip install -q -e . && pip install -q -r requirements-pi.txt" || {
    log "  pip install failed - retrying without -q..."
    ssh $SSH_OPTS "$PI_USER@$PI_HOST" "cd ~/anima-mcp && source .venv/bin/activate && pip install -e . && pip install -r requirements-pi.txt"
}

# 4. Enable I2C and SPI (required for sensors + display after reflash)
log "Enabling I2C and SPI interfaces..."
ssh $SSH_OPTS "$PI_USER@$PI_HOST" "sudo raspi-config nonint do_i2c 0 2>/dev/null; sudo raspi-config nonint do_spi 0 2>/dev/null; true"
ssh $SSH_OPTS "$PI_USER@$PI_HOST" "sudo usermod -aG i2c,gpio,spi $PI_USER 2>/dev/null; true"

# 5. Install and enable broker (sensors) + anima (MCP server)
# Broker owns sensors, writes to shared memory; server owns DB (Option 1 - no contention)
log "Installing systemd services (broker + anima)..."
ssh $SSH_OPTS "$PI_USER@$PI_HOST" "sudo cp ~/anima-mcp/systemd/anima-broker.service /etc/systemd/system/ && sudo cp ~/anima-mcp/systemd/anima.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable anima-broker anima && sudo systemctl start anima-broker && sudo systemctl start anima"

# 7. Verify
sleep 3
log "Verifying..."
ssh $SSH_OPTS "$PI_USER@$PI_HOST" "systemctl is-active anima-broker anima" || log "  services may still be starting"

# 8. Tailscale (optional — for remote access when not on same WiFi)
if [ -n "${RESTORE_TAILSCALE:-}" ]; then
    log "Installing Tailscale..."
    TS_KEY="${TAILSCALE_AUTH_KEY:-}"
    if [ -n "$TS_KEY" ]; then
        ssh $SSH_OPTS "$PI_USER@$PI_HOST" "curl -fsSL https://tailscale.com/install.sh | sh 2>/dev/null; sudo tailscale up --authkey=$TS_KEY 2>/dev/null" || log "  Tailscale sign-in failed"
    else
        ssh $SSH_OPTS "$PI_USER@$PI_HOST" "curl -fsSL https://tailscale.com/install.sh | sh 2>/dev/null" || true
        log "  Tailscale installed. Run: ssh $PI_USER@$PI_HOST 'sudo tailscale up' to sign in"
    fi
else
    log "Tip: RESTORE_TAILSCALE=1 (or + TAILSCALE_AUTH_KEY=tskey-xxx) $0 to add Tailscale"
fi

log "Done. Lumen running (broker + server, no DB contention)."
log "If I2C sensors (temp/humidity/light) fail: reboot required for interfaces. Run: ssh $PI_USER@$PI_HOST 'sudo reboot'"
log "Check: ssh $PI_USER@$PI_HOST 'journalctl -u anima -f'"
log "MCP: http://$PI_HOST:8766/mcp/"
