#!/bin/bash
# Enable USB Gadget Mode on Pi 4 via SD Card
# This makes Pi appear as USB network device to Mac

BOOT_MOUNT="/Volumes/boot"

echo "=== Enabling USB Gadget Mode for Pi 4 ==="
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

# Enable dwc2 overlay in config.txt
echo "1. Enabling dwc2 overlay in config.txt..."
CONFIG_FILE="$BOOT_MOUNT/config.txt"

if grep -q "^dtoverlay=dwc2" "$CONFIG_FILE" 2>/dev/null; then
    echo "   ✅ dwc2 overlay already enabled"
else
    echo "" >> "$CONFIG_FILE"
    echo "dtoverlay=dwc2" >> "$CONFIG_FILE"
    echo "   ✅ Added dtoverlay=dwc2"
fi

# Add modules-load to cmdline.txt
echo ""
echo "2. Adding USB gadget modules to cmdline.txt..."
CMDLINE_FILE="$BOOT_MOUNT/cmdline.txt"

if [ ! -f "$CMDLINE_FILE" ]; then
    echo "   ❌ cmdline.txt not found!"
    echo "   This file is critical - Pi might not boot properly"
    exit 1
fi

# Check if already has modules-load
if grep -q "modules-load=dwc2,g_ether" "$CMDLINE_FILE" 2>/dev/null; then
    echo "   ✅ USB gadget modules already configured"
else
    # Read current cmdline (it's ONE line)
    CMDLINE_CONTENT=$(cat "$CMDLINE_FILE")
    
    # Add modules-load (with space before it)
    NEW_CMDLINE="$CMDLINE_CONTENT modules-load=dwc2,g_ether"
    
    # Backup original
    cp "$CMDLINE_FILE" "$CMDLINE_FILE.backup"
    echo "   ✅ Backed up original cmdline.txt"
    
    # Write new cmdline
    echo "$NEW_CMDLINE" > "$CMDLINE_FILE"
    echo "   ✅ Added modules-load=dwc2,g_ether"
    echo ""
    echo "   Original cmdline.txt backed up to: cmdline.txt.backup"
fi

echo ""
echo "=== Configuration Complete ==="
echo ""
echo "Next steps:"
echo "1. Eject SD card safely"
echo "2. Insert into Pi 4"
echo "3. Connect Pi 4 to Mac via USB-C cable (data-capable cable)"
echo "4. Power on Pi (can use USB-C power adapter OR Mac USB-C)"
echo "5. Wait 30-60 seconds for boot"
echo ""
echo "6. On Mac, check for new network interface:"
echo "   ifconfig | grep -A 5 'en'"
echo ""
echo "7. Find Pi's IP (usually 169.254.1.1 or 192.168.7.2):"
echo "   ping -c 1 169.254.1.1"
echo "   ping -c 1 192.168.7.2"
echo ""
echo "8. SSH to Pi:"
echo "   ssh cirwel@169.254.1.1"
echo "   # or"
echo "   ssh cirwel@192.168.7.2"
echo ""
echo "9. Once connected, enable SSH:"
echo "   sudo systemctl enable ssh"
echo "   sudo systemctl start ssh"
echo ""
echo "⚠️  Note: USB gadget mode uses USB-C port (power port)"
echo "   Make sure you're using a DATA-CAPABLE USB-C cable"
