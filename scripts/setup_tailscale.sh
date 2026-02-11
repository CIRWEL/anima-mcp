#!/bin/bash
# Install and configure Tailscale on Lumen's Pi for remote access
# Usage: ./scripts/setup_tailscale.sh [host]
#   Optional: TAILSCALE_AUTH_KEY=tskey-auth-xxx (from login.tailscale.com/admin/settings/keys)
#
# After setup: Pi gets 100.x.x.x IP — use in Cursor MCP: http://100.x.x.x:8766/mcp/

set -e

PI_USER="unitares-anima"
PI_HOST="${1:-lumen.local}"
SSH_KEY="${HOME}/.ssh/id_ed25519_pi"
SSH_OPTS="-i ${SSH_KEY} -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new"

# Try hosts
for h in "$PI_HOST" lumen.local 192.168.1.165; do
    if ping -c 1 -W 3 "$h" >/dev/null 2>&1; then
        PI_HOST="$h"
        break
    fi
done

log() { echo "[$(date '+%H:%M:%S')] $1"; }

echo "=== Tailscale setup for Lumen (Pi == $PI_HOST) ==="
echo ""

# 1. Install Tailscale
log "Installing Tailscale..."
ssh $SSH_OPTS "$PI_USER@$PI_HOST" "curl -fsSL https://tailscale.com/install.sh | sh"

# 2. Authenticate
TS_KEY="${TAILSCALE_AUTH_KEY:-}"
if [ -n "$TS_KEY" ]; then
    log "Signing in with auth key (headless)..."
    ssh $SSH_OPTS "$PI_USER@$PI_HOST" "sudo tailscale up --authkey=$TS_KEY 2>/dev/null" || {
        echo "  Auth key may be invalid or expired. Get one at: https://login.tailscale.com/admin/settings/keys"
        exit 1
    }
else
    log "No TAILSCALE_AUTH_KEY set — interactive sign-in required"
    echo ""
    echo "Run this on the Pi (or via SSH):"
    echo "  sudo tailscale up"
    echo ""
    echo "A URL will appear — open it in a browser to sign in to your Tailscale account."
    echo ""
    read -p "Have you run 'sudo tailscale up' on the Pi? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        :
    else
        ssh $SSH_OPTS "$PI_USER@$PI_HOST" "sudo tailscale up"
    fi
fi

# 3. Get Tailscale IP
sleep 2
log "Tailscale status:"
ssh $SSH_OPTS "$PI_USER@$PI_HOST" "tailscale status"

TS_IP=$(ssh $SSH_OPTS "$PI_USER@$PI_HOST" "tailscale ip -4" 2>/dev/null | head -1)
if [ -n "$TS_IP" ]; then
    echo ""
    log "Done. Pi Tailscale IP: $TS_IP"
    echo ""
    echo "Update Cursor MCP (~/.cursor/mcp.json):"
    echo "  \"url\": \"http://${TS_IP}:8766/mcp/\""
    echo ""
    echo "Or SSH: ssh -i $SSH_KEY $PI_USER@$TS_IP"
else
    echo ""
    log "Could not get Tailscale IP. Run: ssh $PI_USER@$PI_HOST 'tailscale status'"
fi
