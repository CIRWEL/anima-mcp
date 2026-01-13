#!/bin/bash
# Find Raspberry Pi on local network

echo "🔍 Searching for Raspberry Pi..."
echo ""

# Try common hostnames
echo "Trying hostnames..."
for hostname in raspberrypi.local unitares-anima.local raspberrypi unitares-anima; do
    if ping -c 1 -W 1 "$hostname" &>/dev/null; then
        IP=$(ping -c 1 "$hostname" | grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}' | head -1)
        echo "✅ Found: $hostname → $IP"
        echo ""
        echo "SSH command:"
        echo "  ssh unitares-anima@$IP"
        exit 0
    fi
done

echo "Hostname not found. Checking ARP table for Pi MAC addresses..."
echo ""

# Check ARP for Raspberry Pi MAC address prefixes
# Common Pi MAC prefixes: b8:27:eb, dc:a6:32, e4:5f:01
arp -a | grep -iE "b8:27:eb|dc:a6:32|e4:5f:01" | while read line; do
    IP=$(echo "$line" | grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}')
    MAC=$(echo "$line" | grep -oE '([0-9a-f]{2}:){5}[0-9a-f]{2}')
    echo "Possible Pi: $IP ($MAC)"
done

echo ""
echo "If no results, try:"
echo "  1. Connect Pi to same WiFi network"
echo "  2. Run on Pi: hostname -I"
echo "  3. Or check your router's connected devices list"

