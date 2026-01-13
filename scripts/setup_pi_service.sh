#!/bin/bash
# Setup systemd service and health monitoring on Raspberry Pi
# Run this script ON THE PI (not from Mac)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SERVICE_NAME="lumen"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
HEALTH_SCRIPT="$HOME/monitor_health.sh"

echo "=== Anima Pi Service Setup ==="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "❌ This script must be run as root (use sudo)"
    exit 1
fi

# Check if user exists
if ! id "unitares-anima" &>/dev/null; then
    echo "⚠️  User 'unitares-anima' not found. Creating..."
    adduser --disabled-password --gecos "" unitares-anima
    usermod -aG gpio,i2c,spi unitares-anima
    echo "✅ User created"
fi

# Step 1: Copy service file
echo "1. Installing systemd service..."
if [ -f "$PROJECT_DIR/systemd/anima.service" ]; then
    cp "$PROJECT_DIR/systemd/anima.service" "$SERVICE_FILE"
    echo "✅ Service file copied"
else
    echo "❌ Service file not found at $PROJECT_DIR/systemd/anima.service"
    exit 1
fi

# Step 2: Verify paths in service file
echo "2. Verifying service configuration..."
ANIMA_HOME=$(getent passwd unitares-anima | cut -d: -f6)
if [ -z "$ANIMA_HOME" ]; then
    echo "❌ Could not determine home directory for unitares-anima"
    exit 1
fi

# Update service file with correct paths
sed -i "s|/home/unitares-anima|$ANIMA_HOME|g" "$SERVICE_FILE"
echo "✅ Service paths updated"

# Step 3: Reload systemd
echo "3. Reloading systemd..."
systemctl daemon-reload
echo "✅ Systemd reloaded"

# Step 4: Copy health monitoring script
echo "4. Setting up health monitoring..."
if [ -f "$PROJECT_DIR/scripts/monitor_health_pi.sh" ]; then
    cp "$PROJECT_DIR/scripts/monitor_health_pi.sh" "$HEALTH_SCRIPT"
    chmod +x "$HEALTH_SCRIPT"
    chown unitares-anima:unitares-anima "$HEALTH_SCRIPT"
    echo "✅ Health monitor script installed"
else
    echo "⚠️  Health monitor script not found (optional)"
fi

# Step 5: Enable service
echo "5. Enabling service (auto-start on boot)..."
systemctl enable "$SERVICE_NAME"
echo "✅ Service enabled"

# Step 6: Check if service should be started
echo ""
echo "=== Setup Complete ==="
echo ""
echo "Service file: $SERVICE_FILE"
echo "Health monitor: $HEALTH_SCRIPT"
echo ""
echo "Next steps:"
echo "  1. Verify service file: sudo nano $SERVICE_FILE"
echo "  2. Start service: sudo systemctl start $SERVICE_NAME"
echo "  3. Check status: sudo systemctl status $SERVICE_NAME"
echo "  4. View logs: sudo journalctl -u $SERVICE_NAME -f"
echo "  5. Test health: sudo -u unitares-anima $HEALTH_SCRIPT --once"
echo ""
