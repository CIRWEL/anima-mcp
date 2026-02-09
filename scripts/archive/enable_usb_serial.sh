#!/bin/bash
# Enable USB Serial Console on Pi via SD Card
# Run this while SD card is mounted on Mac

BOOT_MOUNT="/Volumes/boot"

echo "=== Enabling USB Serial Console ==="
echo ""

# Check if boot partition is mounted
if [ ! -d "$BOOT_MOUNT" ]; then
    echo "❌ Boot partition not found at $BOOT_MOUNT"
    echo ""
    echo "Please:"
    echo "1. Insert SD card into Mac"
    echo "2. Wait for 'boot' volume to mount"
    echo "3. Run this script again"
    exit 1
fi

echo "✅ Found boot partition at $BOOT_MOUNT"
echo ""

# Enable UART in config.txt
echo "1. Enabling UART in config.txt..."
if grep -q "^enable_uart=1" "$BOOT_MOUNT/config.txt" 2>/dev/null; then
    echo "   ✅ UART already enabled"
else
    echo "enable_uart=1" >> "$BOOT_MOUNT/config.txt"
    echo "   ✅ Added enable_uart=1"
fi

# Check cmdline.txt for serial console
echo ""
echo "2. Checking cmdline.txt for serial console..."
CMDLINE="$BOOT_MOUNT/cmdline.txt"

if [ ! -f "$CMDLINE" ]; then
    echo "   ⚠️  cmdline.txt not found - Pi might not boot with serial console"
    echo "   You may need to add: console=serial0,115200"
else
    if grep -q "console=serial0,115200\|console=ttyAMA0,115200\|console=ttyS0,115200" "$CMDLINE" 2>/dev/null; then
        echo "   ✅ Serial console already configured"
    else
        echo "   ⚠️  Serial console not found in cmdline.txt"
        echo "   Current cmdline.txt:"
        cat "$CMDLINE" | sed 's/^/      /'
        echo ""
        echo "   ⚠️  WARNING: Editing cmdline.txt is risky (single line, no spaces)"
        echo "   You may need to manually add: console=serial0,115200"
        echo "   But be VERY careful - one wrong edit can break boot!"
    fi
fi

echo ""
echo "=== Next Steps ==="
echo ""
echo "1. Eject SD card safely"
echo "2. Insert into Pi"
echo "3. Connect Pi to Mac via USB cable (data port, not power)"
echo "4. Power on Pi"
echo "5. Wait 30 seconds, then check for serial device:"
echo "   ls /dev/cu.usb*"
echo ""
echo "6. If device appears, connect:"
echo "   screen /dev/cu.usbserial-* 115200"
echo ""
echo "7. Login and enable SSH:"
echo "   sudo systemctl enable ssh"
echo "   sudo systemctl start ssh"
