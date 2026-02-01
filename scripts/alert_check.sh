#!/bin/bash
# Simple alerting script - checks Lumen health and alerts on issues

LUMEN_HOST="localhost"
LUMEN_PORT="8766"
LOG_FILE="/Users/cirwel/Library/Logs/lumen-alerts.log"

log_alert() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') ALERT: $1" >> "$LOG_FILE"
    # macOS notification
    osascript -e "display notification \"$1\" with title \"Lumen Alert\""
}

# Check if MCP server responds
if ! curl -s --max-time 5 "http://${LUMEN_HOST}:${LUMEN_PORT}/" > /dev/null 2>&1; then
    log_alert "Lumen MCP server not responding"
    exit 1
fi

# Check if SSH tunnel is up
if ! pgrep -f "ssh.*8766" > /dev/null; then
    log_alert "SSH tunnel to Pi is down"
    exit 1
fi

# Check Pi services via SSH
if ! ssh -o ConnectTimeout=5 pi-anima "systemctl is-active anima anima-broker" > /dev/null 2>&1; then
    log_alert "Pi services may be down"
    exit 1
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') OK: All checks passed" >> "$LOG_FILE"
exit 0
