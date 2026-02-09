#!/bin/bash
# Configure Mac's USB gadget interface to connect to Pi

MAC_IP="169.254.1.2"
PI_IP="169.254.1.1"

echo "=== Configuring USB Gadget Interface ==="
echo ""

# Auto-detect Raspberry Pi USB Gadget interface
INTERFACE=""
for en in en4 en5 en6 en7 en8 en9 en10; do
    if networksetup -listallhardwareports 2>/dev/null | grep -A 2 "$en" | grep -q "Raspberry\|USB.*Gadget"; then
        INTERFACE="$en"
        break
    fi
done

# If not found by name, try to find any inactive ethernet interface
if [ -z "$INTERFACE" ]; then
    for en in en4 en5 en6 en7 en8 en9 en10; do
        if ifconfig $en >/dev/null 2>&1; then
            STATUS=$(ifconfig $en | grep "status:" | awk '{print $2}')
            if [ "$STATUS" = "inactive" ]; then
                INTERFACE="$en"
                echo "⚠️  Auto-detected interface: $INTERFACE (status: inactive)"
                break
            fi
        fi
    done
fi

# Check if interface exists
if [ -z "$INTERFACE" ] || ! ifconfig $INTERFACE >/dev/null 2>&1; then
    echo "❌ Raspberry Pi USB Gadget interface not found"
    echo ""
    echo "Troubleshooting:"
    echo "1. Make sure Pi is connected via USB-C cable"
    echo "2. Make sure Pi is powered on"
    echo "3. Wait 30-60 seconds for Pi to boot"
    echo "4. Check: networksetup -listallhardwareports | grep -i raspberry"
    exit 1
fi

echo "✅ Found interface: $INTERFACE"

echo "✅ Found interface: $INTERFACE"
echo ""

# Configure Mac's IP
echo "1. Configuring Mac IP: $MAC_IP"
sudo ifconfig $INTERFACE $MAC_IP netmask 255.255.0.0

if [ $? -eq 0 ]; then
    echo "   ✅ Mac IP configured"
else
    echo "   ❌ Failed to configure IP (need sudo)"
    exit 1
fi

echo ""
echo "2. Waiting for Pi to be ready..."
sleep 5

echo ""
echo "3. Testing Pi connectivity..."
if ping -c 2 -W 1000 $PI_IP >/dev/null 2>&1; then
    echo "   ✅ Pi is responding!"
else
    echo "   ⚠️  Pi not responding yet"
    echo "   This might mean:"
    echo "   - Pi is still booting (wait 30-60 seconds)"
    echo "   - USB gadget mode not fully enabled"
    echo "   - Try: ping -c 2 $PI_IP"
fi

echo ""
echo "4. Testing SSH..."
if ssh -o ConnectTimeout=3 -o StrictHostKeyChecking=no cirwel@$PI_IP 'echo "SSH works!"' 2>/dev/null; then
    echo "   ✅ SSH is working!"
    echo ""
    echo "   You can now connect:"
    echo "   ssh cirwel@$PI_IP"
else
    echo "   ⚠️  SSH not working yet"
    echo "   Pi might still be booting, or SSH not enabled"
    echo ""
    echo "   Try manually:"
    echo "   ssh cirwel@$PI_IP"
fi

echo ""
echo "=== Done ==="
