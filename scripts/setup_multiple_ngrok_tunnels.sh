#!/bin/bash
# Setup multiple ngrok tunnels for anima-mcp with redundancy
# Usage: ./scripts/setup_multiple_ngrok_tunnels.sh [authtoken] [domain1] [domain2]

set -e

AUTHTOKEN="${1:-}"
DOMAIN1="${2:-lumen-anima.ngrok.io}"
DOMAIN2="${3:-anima-backup.ngrok.io}"

echo "🔧 Setting up multiple ngrok tunnels for anima-mcp..."
echo ""

# Check if ngrok is installed
if ! command -v ngrok &> /dev/null; then
    echo "❌ ngrok not found. Installing..."
    cd ~
    wget -q https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-arm64.tgz
    tar xzf ngrok-v3-stable-linux-arm64.tgz
    sudo mv ngrok /usr/local/bin/
    rm ngrok-v3-stable-linux-arm64.tgz
    echo "✅ ngrok installed"
fi

# Configure authtoken if provided
if [ -n "$AUTHTOKEN" ]; then
    echo "🔑 Configuring ngrok authtoken..."
    ngrok config add-authtoken "$AUTHTOKEN"
    echo "✅ Authtoken configured"
else
    echo "⚠️  No authtoken provided. You'll need to run:"
    echo "   ngrok config add-authtoken YOUR_AUTHTOKEN"
    echo "   Get it from: https://dashboard.ngrok.com/get-started/your-authtoken"
fi

echo ""
echo "📋 Tunnel Configuration:"
echo "   Primary:   $DOMAIN1 → localhost:8766"
echo "   Backup:    $DOMAIN2 → localhost:8766"
echo ""

# Create systemd service files for multiple tunnels
echo "📝 Creating systemd services..."

# Primary tunnel service
cat > /tmp/anima-ngrok-primary.service <<EOF
[Unit]
Description=ngrok tunnel for anima-mcp (Primary)
After=network.target anima.service
Wants=network-online.target

[Service]
Type=simple
User=unitares-anima
Group=unitares-anima
WorkingDirectory=/home/unitares-anima/anima-mcp
ExecStart=/usr/local/bin/ngrok http --url=$DOMAIN1 8766
Restart=on-failure
RestartSec=10
StartLimitInterval=300
StartLimitBurst=3

[Install]
WantedBy=multi-user.target
EOF

# Backup tunnel service
cat > /tmp/anima-ngrok-backup.service <<EOF
[Unit]
Description=ngrok tunnel for anima-mcp (Backup)
After=network.target anima.service
Wants=network-online.target

[Service]
Type=simple
User=unitares-anima
Group=unitares-anima
WorkingDirectory=/home/unitares-anima/anima-mcp
ExecStart=/usr/local/bin/ngrok http --url=$DOMAIN2 8766
Restart=on-failure
RestartSec=10
StartLimitInterval=300
StartLimitBurst=3

[Install]
WantedBy=multi-user.target
EOF

echo "✅ Service files created"
echo ""
echo "📋 To install and start tunnels:"
echo ""
echo "   # Install services"
echo "   sudo cp /tmp/anima-ngrok-primary.service /etc/systemd/system/"
echo "   sudo cp /tmp/anima-ngrok-backup.service /etc/systemd/system/"
echo "   sudo systemctl daemon-reload"
echo ""
echo "   # Enable and start"
echo "   sudo systemctl enable anima-ngrok-primary"
echo "   sudo systemctl enable anima-ngrok-backup"
echo "   sudo systemctl start anima-ngrok-primary"
echo "   sudo systemctl start anima-ngrok-backup"
echo ""
echo "   # Check status"
echo "   sudo systemctl status anima-ngrok-primary"
echo "   sudo systemctl status anima-ngrok-backup"
echo ""
echo "   # View logs"
echo "   sudo journalctl -u anima-ngrok-primary -f"
echo "   sudo journalctl -u anima-ngrok-backup -f"
echo ""
echo "✅ Setup complete!"
echo ""
echo "📊 Tunnel URLs:"
echo "   Primary:   https://$DOMAIN1/mcp/"
echo "   Backup:    https://$DOMAIN2/mcp/"
echo ""
echo "💡 Use Streamable HTTP (/mcp/) endpoint for connection consistency monitoring"
