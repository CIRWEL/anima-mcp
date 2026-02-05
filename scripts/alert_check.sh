#!/bin/bash
# Simple alerting script - checks Lumen health and alerts on issues
# Updated 2026-02-03: Uses direct Pi access, no SSH tunnels

# Pi direct access (LAN or Tailscale)
# DEFINITIVE: anima-mcp runs on port 8766 - see docs/operations/DEFINITIVE_PORTS.md
PI_HOST="192.168.1.165"
PI_PORT="8766"
PI_TAILSCALE="100.89.201.36"

# Local UNITARES governance
UNITARES_HOST="localhost"
UNITARES_PORT="8767"

LOG_FILE="/Users/cirwel/Library/Logs/lumen-alerts.log"

log_alert() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') ALERT: $1" >> "$LOG_FILE"
    # macOS notification
    osascript -e "display notification \"$1\" with title \"Lumen Alert\""
}

# Check Pi MCP server (try LAN first, then Tailscale)
if ! curl -s --max-time 5 "http://${PI_HOST}:${PI_PORT}/health" > /dev/null 2>&1; then
    # Try Tailscale
    if ! curl -s --max-time 5 "http://${PI_TAILSCALE}:${PI_PORT}/health" > /dev/null 2>&1; then
        log_alert "Lumen (Pi) MCP server not responding on LAN or Tailscale"
        exit 1
    fi
fi

# Check UNITARES governance server
if ! curl -s --max-time 5 "http://${UNITARES_HOST}:${UNITARES_PORT}/health" > /dev/null 2>&1; then
    log_alert "UNITARES governance server not responding"
    exit 1
fi

# Check Pi anima service via SSH (optional, uses Tailscale)
if ! ssh -o ConnectTimeout=5 -o BatchMode=yes -i ~/.ssh/id_ed25519_pi unitares-anima@${PI_TAILSCALE} "systemctl is-active anima" > /dev/null 2>&1; then
    log_alert "Pi anima service may be down"
    # Don't exit 1 - SSH might fail but HTTP works
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') OK: All checks passed" >> "$LOG_FILE"
exit 0
