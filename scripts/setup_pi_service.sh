#!/bin/bash
# Setup systemd services and health monitoring on Raspberry Pi
# Run this script ON THE PI (not from Mac)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
HEALTH_SCRIPT="$HOME/monitor_health.sh"

echo "=== Anima Pi Service Setup ==="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "This script must be run as root (use sudo)"
    exit 1
fi

# Check if user exists
if ! id "unitares-anima" &>/dev/null; then
    echo "User 'unitares-anima' not found. Creating..."
    adduser --disabled-password --gecos "" unitares-anima
    usermod -aG gpio,i2c,spi unitares-anima
    echo "User created"
fi

# Step 1: Copy service files
echo "1. Installing systemd services..."
for svc in anima.service anima-broker.service; do
    if [ -f "$PROJECT_DIR/systemd/$svc" ]; then
        cp "$PROJECT_DIR/systemd/$svc" "/etc/systemd/system/$svc"
        echo "  Copied $svc"
    else
        echo "  Service file not found: $PROJECT_DIR/systemd/$svc"
        exit 1
    fi
done

# Step 2: Verify paths in service files
echo "2. Verifying service configuration..."
ANIMA_HOME=$(getent passwd unitares-anima | cut -d: -f6)
if [ -z "$ANIMA_HOME" ]; then
    echo "Could not determine home directory for unitares-anima"
    exit 1
fi

# Update service files with correct paths
for svc in /etc/systemd/system/anima.service /etc/systemd/system/anima-broker.service; do
    sed -i "s|/home/unitares-anima|$ANIMA_HOME|g" "$svc"
done
echo "  Service paths updated"

# Step 3: Reload systemd
echo "3. Reloading systemd..."
systemctl daemon-reload
echo "  Systemd reloaded"

# Step 4: Copy health monitoring script
echo "4. Setting up health monitoring..."
if [ -f "$PROJECT_DIR/scripts/monitor_health_pi.sh" ]; then
    cp "$PROJECT_DIR/scripts/monitor_health_pi.sh" "$HEALTH_SCRIPT"
    chmod +x "$HEALTH_SCRIPT"
    chown unitares-anima:unitares-anima "$HEALTH_SCRIPT"
    echo "  Health monitor script installed"
else
    echo "  Health monitor script not found (optional)"
fi

# Step 5: Enable services
echo "5. Enabling services (auto-start on boot)..."
systemctl enable anima-broker anima
echo "  Services enabled"

# Step 6: Summary
echo ""
echo "=== Setup Complete ==="
echo ""
echo "Services: anima.service (MCP server), anima-broker.service (hardware broker)"
echo "Health monitor: $HEALTH_SCRIPT"
echo ""
echo "Next steps:"
echo "  1. Start services: sudo systemctl start anima-broker anima"
echo "  2. Check status: sudo systemctl status anima-broker anima"
echo "  3. View logs: sudo journalctl -u anima -f"
echo "  4. Test health: sudo -u unitares-anima $HEALTH_SCRIPT --once"
echo ""
