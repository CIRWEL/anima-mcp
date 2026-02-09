#!/bin/bash
# Setup ngrok tunnel with basic auth for anima-mcp
# Usage: ./scripts/setup_ngrok_basic_auth.sh [username] [password] [domain]

set -e

USERNAME="${1:-anima-agent}"
PASSWORD="${2:-$(openssl rand -base64 16 | tr -d "=+/" | cut -c1-16)}"
DOMAIN="${3:-anima.ngrok.io}"
PORT="${4:-8766}"

echo "🔧 Setting up ngrok tunnel with basic auth for anima-mcp..."
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

# Check if authtoken is configured
if ! ngrok config check &> /dev/null; then
    echo "⚠️  ngrok authtoken not configured"
    echo "   Run: ngrok config add-authtoken YOUR_AUTHTOKEN"
    echo "   Get it from: https://dashboard.ngrok.com/get-started/your-authtoken"
    echo ""
    read -p "Enter your ngrok authtoken (or press Enter to skip): " AUTHTOKEN
    if [ -n "$AUTHTOKEN" ]; then
        ngrok config add-authtoken "$AUTHTOKEN"
        echo "✅ Authtoken configured"
    else
        echo "⚠️  Skipping authtoken - tunnel may not work"
    fi
fi

# Generate base64 auth header
AUTH_HEADER=$(echo -n "${USERNAME}:${PASSWORD}" | base64)

echo "📋 Configuration:"
echo "   Username: $USERNAME"
echo "   Password: $PASSWORD"
echo "   Auth Header: $AUTH_HEADER"
echo "   Domain: $DOMAIN"
echo "   Port: $PORT"
echo ""

# Check if port is in use
if lsof -i :$PORT &> /dev/null; then
    echo "⚠️  Port $PORT is already in use"
    echo "   Checking what's using it..."
    lsof -i :$PORT
    echo ""
    read -p "Kill existing process? (y/N): " KILL_PROCESS
    if [ "$KILL_PROCESS" = "y" ] || [ "$KILL_PROCESS" = "Y" ]; then
        echo "Killing processes on port $PORT..."
        pkill -f "anima.*--sse" || true
        lsof -ti :$PORT | xargs kill -9 2>/dev/null || true
        sleep 2
        echo "✅ Port cleared"
    fi
fi

# Create systemd service for ngrok with basic auth
SERVICE_FILE="/etc/systemd/system/anima-ngrok.service"
echo "📝 Creating systemd service: $SERVICE_FILE"

sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=ngrok tunnel for anima-mcp with basic auth
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=unitares-anima
Group=unitares-anima
WorkingDirectory=/home/unitares-anima/anima-mcp

# Restart policy
Restart=on-failure
RestartSec=10
StartLimitInterval=300
StartLimitBurst=3

# Environment
Environment="NGROK_AUTH=${USERNAME}:${PASSWORD}"

# Executable - start tunnel with basic auth
ExecStart=/usr/local/bin/ngrok http --basic-auth="${USERNAME}:${PASSWORD}" --url=${DOMAIN} ${PORT}

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=anima-ngrok

# Security
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

echo "✅ Service file created"
echo ""

# Reload systemd and start service
echo "🔄 Reloading systemd..."
sudo systemctl daemon-reload

echo "🚀 Starting ngrok tunnel..."
sudo systemctl enable anima-ngrok.service
sudo systemctl start anima-ngrok.service

# Wait a moment for tunnel to start
sleep 3

# Check status
if sudo systemctl is-active --quiet anima-ngrok.service; then
    echo "✅ ngrok tunnel is running"
else
    echo "❌ ngrok tunnel failed to start"
    echo "   Check logs: sudo journalctl -u anima-ngrok -n 50"
    exit 1
fi

# Get tunnel URL
echo ""
echo "🔍 Getting tunnel URL..."
sleep 2
TUNNEL_URL=$(curl -s http://localhost:4040/api/tunnels | python3 -c "import sys, json; data=json.load(sys.stdin); print(data['tunnels'][0]['public_url'] if data.get('tunnels') else 'Not available')" 2>/dev/null || echo "Not available")

if [ "$TUNNEL_URL" != "Not available" ]; then
    echo "✅ Tunnel URL: $TUNNEL_URL"
    echo ""
    echo "📝 For Cursor MCP config (~/.cursor/mcp.json):"
    echo ""
    echo "{"
    echo "  \"mcpServers\": {"
    echo "    \"anima\": {"
    echo "      \"type\": \"http\","
    echo "      \"url\": \"${TUNNEL_URL}/sse\","
    echo "      \"headers\": {"
    echo "        \"Authorization\": \"Basic ${AUTH_HEADER}\""
    echo "      }"
    echo "    }"
    echo "  }"
    echo "}"
    echo ""
else
    echo "⚠️  Could not get tunnel URL automatically"
    echo "   Check ngrok dashboard: http://localhost:4040"
    echo "   Or run: curl http://localhost:4040/api/tunnels | python3 -m json.tool"
fi

echo ""
echo "📋 Summary:"
echo "   Service: anima-ngrok.service"
echo "   Status: sudo systemctl status anima-ngrok"
echo "   Logs: sudo journalctl -u anima-ngrok -f"
echo "   Stop: sudo systemctl stop anima-ngrok"
echo "   Start: sudo systemctl start anima-ngrok"
echo ""
echo "✅ Setup complete!"
