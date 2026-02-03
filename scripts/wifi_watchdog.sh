#!/bin/bash
# WiFi Watchdog - Auto-reconnect if WiFi drops
# Run via cron every 5 minutes: */5 * * * * /home/unitares-anima/anima-mcp/scripts/wifi_watchdog.sh

LOGFILE="/home/unitares-anima/.anima/wifi_watchdog.log"

# Check if we can reach the gateway
GATEWAY=$(ip route | grep default | awk '{print $3}')

if [ -z "$GATEWAY" ]; then
    echo "$(date): No default gateway found, attempting WiFi reconnect" >> $LOGFILE
    nmcli device wifi rescan 2>/dev/null
    sleep 2
    nmcli device wifi connect "Verizon_NJ7CC3" password "forty5fitch2jug" 2>> $LOGFILE || \
        wpa_cli -i wlan0 reconfigure 2>> $LOGFILE
    echo "$(date): WiFi reconnect attempted" >> $LOGFILE
    exit 0
fi

# Try to ping gateway
if ! ping -c 1 -W 5 "$GATEWAY" > /dev/null 2>&1; then
    echo "$(date): Gateway unreachable, attempting WiFi reconnect" >> $LOGFILE
    nmcli device wifi rescan 2>/dev/null
    sleep 2
    nmcli device wifi connect "Verizon_NJ7CC3" password "forty5fitch2jug" 2>> $LOGFILE || \
        wpa_cli -i wlan0 reconfigure 2>> $LOGFILE
    echo "$(date): WiFi reconnect attempted" >> $LOGFILE
else
    # Only log once per hour to avoid spam
    HOUR=$(date +%H)
    LAST_LOG=$(tail -1 $LOGFILE 2>/dev/null | grep -o "^........................" | cut -d: -f1-2)
    CURRENT_TIME=$(date +"%b %d %H")
    if [ "$LAST_LOG" != "$CURRENT_TIME" ]; then
        echo "$(date): WiFi OK (gateway: $GATEWAY)" >> $LOGFILE
    fi
fi

# Keep log file from growing too large (keep last 100 lines)
if [ -f "$LOGFILE" ]; then
    tail -100 "$LOGFILE" > "${LOGFILE}.tmp" && mv "${LOGFILE}.tmp" "$LOGFILE"
fi
