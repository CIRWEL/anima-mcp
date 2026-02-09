#!/bin/bash
# Setup ngrok tunnel for anima-mcp
# Usage: ./scripts/setup_ngrok.sh [authtoken] [domain]

set -e

AUTHTOKEN="${1:-}"
DOMAIN="${2:-anima.ngrok.io}"

echo "🔧 Setting up ngrok for anima-mcp..."
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

# Check if custom domain
if [ "$DOMAIN" != "anima.ngrok.io" ]; then
    echo "📝 Using custom domain: $DOMAIN"
    echo "⚠️  Make sure domain is created in ngrok dashboard first"
fi

echo ""
echo "✅ ngrok setup complete!"
echo ""
echo "To start tunnel:"
if [ "$DOMAIN" = "anima.ngrok.io" ]; then
    echo "  ngrok http 8766"
    echo "  # Or for custom domain:"
    echo "  ngrok http --url=$DOMAIN 8766"
else
    echo "  ngrok http --url=$DOMAIN 8766"
fi
echo ""
echo "To get tunnel URL:"
echo "  curl http://localhost:4040/api/tunnels | python3 -m json.tool"
