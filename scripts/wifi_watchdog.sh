#!/bin/bash
# WiFi Watchdog - Auto-reconnect if WiFi drops
# Run via cron every 2 minutes: */2 * * * * /home/unitares-anima/anima-mcp/scripts/wifi_watchdog.sh
#
# Escalation levels:
#   1. nmcli reconnect (soft)
#   2. rfkill cycle + driver reload (hardware reset)
#   3. Full reboot (nuclear)

LOGFILE="/home/unitares-anima/.anima/wifi_watchdog.log"
FAIL_COUNT_FILE="/tmp/wifi_watchdog_fails"
MAX_SOFT_RETRIES=3  # After 3 soft fails (6 min), escalate to hardware reset
MAX_HARD_RETRIES=5  # After 5 total fails (10 min), reboot

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S'): $1" >> "$LOGFILE"
}

# Read consecutive fail count
FAIL_COUNT=0
if [ -f "$FAIL_COUNT_FILE" ]; then
    FAIL_COUNT=$(cat "$FAIL_COUNT_FILE" 2>/dev/null || echo 0)
fi

# Check if wlan0 even exists as an interface
if ! ip link show wlan0 > /dev/null 2>&1; then
    log "CRITICAL: wlan0 interface missing! Driver may have crashed."
    FAIL_COUNT=$((FAIL_COUNT + 1))
    echo "$FAIL_COUNT" > "$FAIL_COUNT_FILE"
    # Try to reload the driver
    modprobe -r brcmfmac 2>/dev/null
    sleep 2
    modprobe brcmfmac 2>/dev/null
    log "Attempted brcmfmac driver reload"
    exit 1
fi

# Check if we can reach the gateway
GATEWAY=$(ip route | grep default | awk '{print $3}')

# Also try router directly if no gateway in route table
if [ -z "$GATEWAY" ]; then
    GATEWAY="192.168.1.1"
fi

# Test connectivity
CONNECTED=false
if ping -c 2 -W 5 "$GATEWAY" > /dev/null 2>&1; then
    CONNECTED=true
fi

# Also test internet (in case gateway responds but upstream is down)
if [ "$CONNECTED" = true ]; then
    if ! ping -c 1 -W 5 8.8.8.8 > /dev/null 2>&1; then
        # Gateway reachable but no internet - still count as connected
        # (router might be up but ISP down, not our problem)
        true
    fi
fi

if [ "$CONNECTED" = true ]; then
    # Success - reset fail counter
    if [ "$FAIL_COUNT" -gt 0 ]; then
        log "WiFi recovered after $FAIL_COUNT failures (gateway: $GATEWAY)"
    fi
    echo 0 > "$FAIL_COUNT_FILE"

    # Log once per hour
    CURRENT_HOUR=$(date +"%Y-%m-%d %H")
    LAST_OK=$(grep "WiFi OK" "$LOGFILE" 2>/dev/null | tail -1 | cut -d: -f1-3 | xargs -I{} date -d "{}" +"%Y-%m-%d %H" 2>/dev/null)
    if [ "$LAST_OK" != "$CURRENT_HOUR" ]; then
        SIGNAL=$(iwconfig wlan0 2>/dev/null | grep -o 'Signal level=.*' | head -1)
        log "WiFi OK (gateway: $GATEWAY, $SIGNAL)"
    fi
    exit 0
fi

# --- WiFi is DOWN ---
FAIL_COUNT=$((FAIL_COUNT + 1))
echo "$FAIL_COUNT" > "$FAIL_COUNT_FILE"

if [ "$FAIL_COUNT" -le "$MAX_SOFT_RETRIES" ]; then
    # Level 1: Soft reconnect
    log "WARN: WiFi down (attempt $FAIL_COUNT/$MAX_SOFT_RETRIES) - soft reconnect"
    nmcli device wifi rescan 2>/dev/null
    sleep 3
    nmcli device wifi connect "Verizon_NJ7CC3" password "forty5fitch2jug" 2>> "$LOGFILE" || \
        wpa_cli -i wlan0 reconfigure 2>> "$LOGFILE"

elif [ "$FAIL_COUNT" -le "$MAX_HARD_RETRIES" ]; then
    # Level 2: Hardware reset - rfkill cycle + driver reload
    log "WARN: WiFi down (attempt $FAIL_COUNT) - HARDWARE RESET"

    # Bring interface down
    ip link set wlan0 down 2>/dev/null
    sleep 1

    # Unblock wifi radio
    rfkill unblock wifi 2>/dev/null
    sleep 1

    # Reload the brcmfmac driver (fixes firmware crashes)
    modprobe -r brcmfmac 2>/dev/null
    sleep 3
    modprobe brcmfmac 2>/dev/null
    sleep 5

    # Bring interface back up
    ip link set wlan0 up 2>/dev/null
    sleep 2

    # Restart NetworkManager to pick up the interface
    systemctl restart NetworkManager 2>/dev/null
    sleep 5

    # Try to connect
    nmcli device wifi connect "Verizon_NJ7CC3" password "forty5fitch2jug" 2>> "$LOGFILE"
    log "Hardware reset complete, reconnect attempted"

else
    # Level 3: Nuclear - reboot
    log "CRITICAL: WiFi down for $((FAIL_COUNT * 2)) minutes. REBOOTING."
    sync
    sleep 1
    reboot
fi

# Keep log file from growing too large (keep last 200 lines)
if [ -f "$LOGFILE" ]; then
    tail -200 "$LOGFILE" > "${LOGFILE}.tmp" && mv "${LOGFILE}.tmp" "$LOGFILE"
fi
