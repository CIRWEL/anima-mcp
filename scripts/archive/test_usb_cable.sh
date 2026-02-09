#!/bin/bash
# Quick test to see if USB cable is data-capable

echo "=== USB Cable Test ==="
echo ""
echo "Step 1: Connect your phone to Mac via this USB-C cable"
echo "       (If you have a phone with USB-C)"
read -p "Press Enter when phone is connected..."

if system_profiler SPUSBDataType 2>/dev/null | grep -i "iphone\|android\|device" >/dev/null; then
    echo "✅ Mac recognizes device - cable is DATA-CAPABLE"
    CABLE_TYPE="data"
else
    echo "⚠️  Mac doesn't see device - cable might be charge-only"
    CABLE_TYPE="unknown"
fi

echo ""
echo "Step 2: Now connect Pi 4 to Mac via USB-C"
echo "        (Pi's USB-C power port → Mac's USB-C port)"
read -p "Press Enter when Pi is connected..."

echo ""
echo "Waiting 10 seconds for system to detect..."
sleep 10

echo ""
echo "Checking for Raspberry Pi USB Gadget interface..."
if networksetup -listallhardwareports 2>/dev/null | grep -i "raspberry\|usb.*gadget" >/dev/null; then
    INTERFACE=$(networksetup -listallhardwareports 2>/dev/null | grep -B 1 -i "raspberry\|usb.*gadget" | grep "^Device:" | awk '{print $2}')
    echo "✅ Found Raspberry Pi USB Gadget interface: $INTERFACE"
    echo ""
    echo "Next step: Run ./scripts/configure_usb_gadget.sh"
else
    echo "❌ Raspberry Pi USB Gadget not detected"
    echo ""
    echo "Possible reasons:"
    echo "1. Cable is charge-only (not data-capable)"
    echo "2. Pi hasn't finished booting (wait 30-60 seconds)"
    echo "3. USB gadget mode not enabled (need to edit SD card)"
    echo ""
    echo "Check USB devices:"
    system_profiler SPUSBDataType 2>/dev/null | grep -i "product\|manufacturer" | head -10
fi
