#!/bin/bash
# Safe WiFi network switching script
# Checks availability before switching to prevent disconnection

set -e

HOTSPOT_SSID="Kenneth Powers Esquire"
HOTSPOT_PASSWORD="dw0io3w047gob"
HOME_SSID="Verizon_NJ7CC3"
HOME_PASSWORD="forty5fitch2jug"

echo "🔌 Safe WiFi Network Switcher"
echo "============================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "⚠️  This script needs sudo privileges"
    echo "   Run: sudo bash safe_wifi_switch.sh"
    exit 1
fi

# Get current network
CURRENT_CONNECTION=$(nmcli -t -f active,ssid dev wifi | grep '^yes' | cut -d: -f2 || echo "none")
CURRENT_IP=$(hostname -I | awk '{print $1}')

echo "Current Status:"
echo "  Connection: $CURRENT_CONNECTION"
echo "  IP Address: $CURRENT_IP"
echo ""

# Function to check if network is available
check_network_available() {
    local ssid=$1
    nmcli device wifi list | grep -q "$ssid"
}

# Function to ensure network is configured
ensure_network_configured() {
    local ssid=$1
    local password=$2
    local priority=$3
    
    if ! nmcli connection show | grep -q "$ssid"; then
        echo "  Adding network: $ssid..."
        nmcli connection add \
            type wifi \
            con-name "$ssid" \
            ifname wlan0 \
            ssid "$ssid" \
            wifi-sec.key-mgmt wpa-psk \
            wifi-sec.psk "$password" \
            connection.autoconnect-priority "$priority" \
            connection.autoconnect yes
    else
        echo "  Network already configured: $ssid"
        # Update priority
        nmcli connection modify "$ssid" connection.autoconnect-priority "$priority"
    fi
}

# Menu
echo "Select action:"
echo "  1) Switch to Hotspot (if available)"
echo "  2) Switch to Home WiFi"
echo "  3) Ensure both networks configured (recommended)"
echo "  4) Show current status"
echo ""
read -p "Choice [1-4]: " choice

case $choice in
    1)
        echo ""
        echo "Switching to Hotspot..."
        
        # Check if hotspot is available
        if check_network_available "$HOTSPOT_SSID"; then
            echo "  ✅ Hotspot found"
            
            # Ensure configured
            ensure_network_configured "$HOTSPOT_SSID" "$HOTSPOT_PASSWORD" 10
            
            # Connect
            echo "  Connecting to hotspot..."
            nmcli connection up "$HOTSPOT_SSID"
            
            sleep 3
            NEW_IP=$(hostname -I | awk '{print $1}')
            echo ""
            echo "✅ Connected to hotspot"
            echo "  New IP: $NEW_IP"
        else
            echo "  ❌ Hotspot '$HOTSPOT_SSID' not found"
            echo "  Turn on hotspot and try again"
            exit 1
        fi
        ;;
        
    2)
        echo ""
        echo "Switching to Home WiFi..."
        
        # Ensure configured
        ensure_network_configured "$HOME_SSID" "$HOME_PASSWORD" 5
        
        # Connect
        echo "  Connecting to home WiFi..."
        nmcli connection up "$HOME_SSID"
        
        sleep 3
        NEW_IP=$(hostname -I | awk '{print $1}')
        echo ""
        echo "✅ Connected to home WiFi"
        echo "  New IP: $NEW_IP"
        ;;
        
    3)
        echo ""
        echo "Configuring both networks (recommended setup)..."
        echo ""
        
        # Configure hotspot (priority 10 - connects first if available)
        echo "1. Configuring hotspot..."
        ensure_network_configured "$HOTSPOT_SSID" "$HOTSPOT_PASSWORD" 10
        
        # Configure home WiFi (priority 5 - fallback)
        echo ""
        echo "2. Configuring home WiFi..."
        ensure_network_configured "$HOME_SSID" "$HOME_PASSWORD" 5
        
        echo ""
        echo "✅ Both networks configured"
        echo ""
        echo "Configuration:"
        echo "  - Hotspot: Priority 10 (connects first if available)"
        echo "  - Home WiFi: Priority 5 (fallback)"
        echo ""
        echo "Pi will automatically:"
        echo "  - Connect to hotspot if available"
        echo "  - Fall back to home WiFi if hotspot unavailable"
        echo ""
        echo "Current connections:"
        nmcli connection show
        ;;
        
    4)
        echo ""
        echo "Current Network Status:"
        echo "======================"
        echo ""
        echo "Active connection:"
        nmcli device status | grep -E "wlan0|connected"
        echo ""
        echo "Configured WiFi connections:"
        nmcli connection show | grep wifi
        echo ""
        echo "Available networks:"
        nmcli device wifi list | head -10
        echo ""
        echo "IP Address:"
        hostname -I
        ;;
        
    *)
        echo "Invalid choice"
        exit 1
        ;;
esac

echo ""
echo "Done!"
