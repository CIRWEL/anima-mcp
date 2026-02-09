#!/bin/bash
# Find Pi on phone hotspot network

echo "🔍 Finding Pi on hotspot network..."
echo ""

# Common hotspot IP ranges
# Android: 192.168.43.0/24
# iPhone: 172.20.10.0/24
# Other: 192.168.1.0/24

# Get MacBook's IP to determine network
MY_IP=$(ifconfig | grep "inet " | grep -v 127.0.0.1 | head -1 | awk '{print $2}')
NETWORK=$(echo $MY_IP | cut -d'.' -f1-3)

echo "Your IP: $MY_IP"
echo "Network: $NETWORK.0/24"
echo ""
echo "Scanning for Pi..."

# Try common hotspot ranges
for range in "${NETWORK}.0/24" "192.168.43.0/24" "172.20.10.0/24"; do
    echo "Checking $range..."
    # Try pinging common IPs
    for i in {1..10}; do
        IP="${range%.0/24}.$i"
        if ping -c 1 -W 1 "$IP" &>/dev/null; then
            # Try SSH
            if nc -zv -w 1 "$IP" 2222 &>/dev/null; then
                echo "✅ Found Pi at: $IP"
                echo ""
                echo "SSH command:"
                echo "  ssh -p 2222 unitares-anima@$IP"
                exit 0
            fi
        fi
    done
done

echo "❌ Pi not found. Make sure:"
echo "  1. Pi is connected to hotspot"
echo "  2. MacBook is on same hotspot"
echo "  3. Run 'hostname -I' on Pi to get IP"

