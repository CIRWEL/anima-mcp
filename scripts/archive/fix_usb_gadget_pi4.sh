#!/bin/bash
# Fix USB Gadget Mode for Pi 4
# Run this when SD card is mounted on Mac

BOOT_MOUNT="/Volumes/bootfs"
if [ ! -d "$BOOT_MOUNT" ]; then
    BOOT_MOUNT="/Volumes/boot"
fi

if [ ! -d "$BOOT_MOUNT" ]; then
    echo "❌ Boot partition not found"
    echo "Insert SD card and wait for it to mount"
    exit 1
fi

echo "=== Fixing USB Gadget Mode for Pi 4 ==="
echo "Boot partition: $BOOT_MOUNT"
echo ""

CONFIG_FILE="$BOOT_MOUNT/config.txt"
CMDLINE_FILE="$BOOT_MOUNT/cmdline.txt"

# Backup files
cp "$CONFIG_FILE" "$CONFIG_FILE.backup.$(date +%Y%m%d_%H%M%S)"
cp "$CMDLINE_FILE" "$CMDLINE_FILE.backup.$(date +%Y%m%d_%H%M%S)"
echo "✅ Backed up original files"

# Fix config.txt - remove conflicting dwc2 entries and add correct one
echo ""
echo "1. Fixing config.txt..."

# Remove any existing dwc2 entries in [all] section
sed -i.bak '/^\[all\]/,/^\[/ { /^dtoverlay=dwc2/d; }' "$CONFIG_FILE" 2>/dev/null || true

# Remove the one we added if it exists
sed -i.bak '/^dtoverlay=dwc2$/d' "$CONFIG_FILE" 2>/dev/null || true

# Add correct dwc2 entry for Pi 4 USB gadget (peripheral mode)
if ! grep -q "dtoverlay=dwc2,dr_mode=peripheral" "$CONFIG_FILE"; then
    # Add to [all] section
    if grep -q "^\[all\]" "$CONFIG_FILE"; then
        # Add after [all] line
        sed -i.bak '/^\[all\]/a\
dtoverlay=dwc2,dr_mode=peripheral
' "$CONFIG_FILE"
    else
        # Add at end of file
        echo "" >> "$CONFIG_FILE"
        echo "[all]" >> "$CONFIG_FILE"
        echo "dtoverlay=dwc2,dr_mode=peripheral" >> "$CONFIG_FILE"
    fi
    echo "   ✅ Added dtoverlay=dwc2,dr_mode=peripheral"
else
    echo "   ✅ Already has correct dwc2 entry"
fi

# Fix cmdline.txt - ensure modules-load is correct
echo ""
echo "2. Fixing cmdline.txt..."

# Check if modules-load already exists
if grep -q "modules-load=dwc2,g_ether" "$CMDLINE_FILE"; then
    echo "   ✅ modules-load already present"
else
    # Add modules-load (be careful - single line!)
    CMDLINE=$(cat "$CMDLINE_FILE")
    # Remove trailing whitespace and add modules-load
    CMDLINE=$(echo "$CMDLINE" | sed 's/[[:space:]]*$//')
    echo "$CMDLINE modules-load=dwc2,g_ether" > "$CMDLINE_FILE"
    echo "   ✅ Added modules-load=dwc2,g_ether"
fi

echo ""
echo "=== Verification ==="
echo ""
echo "config.txt - dwc2 entries:"
grep "dtoverlay=dwc2" "$CONFIG_FILE" || echo "  (none found)"
echo ""
echo "cmdline.txt - modules-load:"
grep "modules-load=dwc2,g_ether" "$CMDLINE_FILE" || echo "  (not found)"
echo ""
echo "✅ Configuration fixed!"
echo ""
echo "Next steps:"
echo "1. Eject SD card safely"
echo "2. Insert into Pi 4"
echo "3. Power on Pi"
echo "4. Wait 60 seconds"
echo "5. Connect USB-C cable"
echo "6. Run: sudo ifconfig en8 169.254.1.2 netmask 255.255.0.0"
echo "7. Try: ping -c 2 169.254.1.1"
