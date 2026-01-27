#!/bin/bash
# Diagnose WiFi disconnection issues on Pi
# Run this script ON THE PI (via SSH or physical access)

echo "🔍 WiFi Disconnection Diagnostic"
echo "================================="
echo ""

# Check if running on Pi
if [ ! -f /proc/device-tree/model ] || ! grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
    echo "⚠️  This script should be run ON the Raspberry Pi"
    echo "   Copy to Pi and run: bash diagnose_wifi_disconnect.sh"
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo "1. WiFi Interface Status:"
echo "-------------------------"
if command -v iwconfig &>/dev/null; then
    iwconfig wlan0 2>/dev/null || echo "  ❌ wlan0 not found"
    echo ""
    echo "  Signal strength:"
    iwconfig wlan0 2>/dev/null | grep -i signal || echo "  (not available)"
else
    echo "  ⚠️  iwconfig not installed"
fi

if command -v ip &>/dev/null; then
    echo ""
    echo "  IP configuration:"
    ip addr show wlan0 2>/dev/null || echo "  ❌ wlan0 not configured"
fi

echo ""
echo "2. Network Connection Status:"
echo "----------------------------"
if command -v nmcli &>/dev/null; then
    echo "  NetworkManager status:"
    nmcli device status
    echo ""
    echo "  Active connections:"
    nmcli connection show --active
else
    echo "  ⚠️  NetworkManager not available"
fi

echo ""
echo "3. Power Status (Common Cause):"
echo "-------------------------------"
if command -v vcgencmd &>/dev/null; then
    THROTTLED=$(vcgencmd get_throttled | cut -d= -f2)
    echo "  Throttle status: $THROTTLED"
    
    if [ "$THROTTLED" != "0x0" ]; then
        echo "  ⚠️  WARNING: Power issues detected!"
        if [ "$((THROTTLED & 0x50000))" != "0" ]; then
            echo "     - Undervoltage detected"
        fi
        if [ "$((THROTTLED & 0x50005))" != "0" ]; then
            echo "     - Throttling active"
        fi
    else
        echo "  ✅ Power OK"
    fi
    
    echo ""
    echo "  Voltage:"
    vcgencmd measure_volts
else
    echo "  ⚠️  vcgencmd not available (not on Pi?)"
fi

echo ""
echo "4. Recent Network Events:"
echo "-------------------------"
if command -v journalctl &>/dev/null; then
    echo "  Last 20 network events:"
    journalctl --since "10 minutes ago" | grep -iE "wlan|network|wifi|disconnect|connect" | tail -20 || echo "  (no recent events)"
else
    echo "  ⚠️  journalctl not available"
fi

echo ""
echo "5. WiFi Configuration:"
echo "---------------------"
if [ -f /etc/wpa_supplicant/wpa_supplicant.conf ]; then
    echo "  wpa_supplicant.conf exists"
    echo "  Networks configured:"
    grep -E "^network=|ssid=" /etc/wpa_supplicant/wpa_supplicant.conf | head -10
else
    echo "  ⚠️  /etc/wpa_supplicant/wpa_supplicant.conf not found"
fi

echo ""
echo "6. Connectivity Test:"
echo "-------------------"
echo "  Testing internet connectivity..."
if ping -c 2 -W 2 8.8.8.8 &>/dev/null; then
    echo "  ✅ Internet accessible"
else
    echo "  ❌ No internet connection"
fi

echo ""
echo "7. Recommendations:"
echo "------------------"
echo ""
if [ "$THROTTLED" != "0x0" ] 2>/dev/null; then
    echo "  🔴 CRITICAL: Power issues detected!"
    echo "     - Use official Pi 4 power supply (5V, 3A)"
    echo "     - Check power cable quality"
    echo "     - If using power bank, ensure PD 3A+"
    echo ""
fi

if ! ping -c 1 -W 2 8.8.8.8 &>/dev/null; then
    echo "  🔴 No internet connection"
    echo "     - Check WiFi signal strength"
    echo "     - Verify network credentials"
    echo "     - Try: sudo nmcli radio wifi off && sudo nmcli radio wifi on"
    echo ""
fi

echo "  For more solutions, see:"
echo "  docs/WIFI_DISCONNECTION_TROUBLESHOOTING.md"
echo ""
