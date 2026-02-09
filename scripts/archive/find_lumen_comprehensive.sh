#!/bin/bash
# Comprehensive Pi finder - checks all possible networks and methods

echo "🔍 Comprehensive Lumen/Pi Search"
echo "================================"
echo ""

# Get current network info
echo "Current Network Status:"
MY_IP=$(ifconfig | grep "inet " | grep -v 127.0.0.1 | head -1 | awk '{print $2}')
echo "  MacBook IP: $MY_IP"
NETWORK=$(echo $MY_IP | cut -d'.' -f1-3)
echo "  Network: $NETWORK.0/24"
echo ""

# Check if on hotspot (iPhone hotspot is typically 172.20.10.x)
if [[ "$MY_IP" == "172.20.10."* ]]; then
    echo "📍 You're on iPhone hotspot network"
    HOTSPOT_NET="172.20.10"
elif [[ "$MY_IP" == "192.168.43."* ]]; then
    echo "📍 You're on Android hotspot network"
    HOTSPOT_NET="192.168.43"
else
    echo "📍 You're on home/local network"
    HOTSPOT_NET=""
fi
echo ""

# Function to test IP
test_ip() {
    local ip=$1
    local port=${2:-22}
    
    # Quick ping
    if ping -c 1 -W 1 "$ip" &>/dev/null; then
        echo -n "  ✅ $ip: ping OK"
        
        # Test SSH
        if nc -zv -w 1 "$ip" "$port" &>/dev/null 2>&1; then
            echo " | SSH port $port OPEN"
            return 0
        fi
        
        # Test MCP port
        if nc -zv -w 1 "$ip" 8766 &>/dev/null 2>&1; then
            echo " | MCP port 8766 OPEN"
            return 0
        fi
        
        echo " | ports closed"
        return 1
    fi
    return 1
}

# Check known IPs first
echo "1. Checking known IPs:"
KNOWN_IPS=("192.168.1.165" "192.168.1.164" "172.20.10.2")
for ip in "${KNOWN_IPS[@]}"; do
    test_ip "$ip" 22 || test_ip "$ip" 2222
done
echo ""

# Check mDNS hostnames
echo "2. Checking mDNS hostnames:"
for hostname in "unitares-anima.local" "raspberrypi.local" "lumen.local"; do
    if ping -c 1 -W 1 "$hostname" &>/dev/null; then
        IP=$(ping -c 1 "$hostname" 2>&1 | grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}' | head -1)
        echo "  ✅ Found: $hostname → $IP"
        test_ip "$IP" 22 || test_ip "$IP" 2222
    fi
done
echo ""

# Scan current network subnet
echo "3. Scanning current network ($NETWORK.0/24)..."
FOUND=0
for i in {1..50}; do
    ip="${NETWORK}.$i"
    if test_ip "$ip" 22 || test_ip "$ip" 2222; then
        FOUND=1
        echo "    Potential Pi found at: $ip"
    fi
done
if [ $FOUND -eq 0 ]; then
    echo "  (No devices found in first 50 IPs)"
fi
echo ""

# If on hotspot, also check home network
if [ -n "$HOTSPOT_NET" ]; then
    echo "4. You're on hotspot - Pi might be on home WiFi (192.168.1.x)..."
    echo "   (This requires MacBook to be on home WiFi to scan)"
    echo "   Try switching MacBook to home WiFi and run this script again"
    echo ""
fi

# Check ARP table for Pi MAC addresses
echo "5. Checking ARP table for Pi MAC addresses:"
arp -a | grep -iE "88:a2:9e:33:f1:10|b8:27:eb|dc:a6:32|e4:5f:01" | while read line; do
    IP=$(echo "$line" | grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}')
    MAC=$(echo "$line" | grep -oE '([0-9a-f]{2}:){5}[0-9a-f]{2}')
    echo "  ✅ Possible Pi: $IP ($MAC)"
    test_ip "$IP" 22 || test_ip "$IP" 2222
done
echo ""

echo "================================"
echo "Recommendations:"
echo "  1. Make sure MacBook and Pi are on the SAME network"
echo "  2. If Pi is on hotspot, connect MacBook to hotspot"
echo "  3. If Pi is on home WiFi, connect MacBook to home WiFi"
echo "  4. Check router's connected devices list"
echo "  5. If you have physical access, run: hostname -I"
echo ""
