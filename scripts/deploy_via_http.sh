#!/bin/bash
# Deploy code to Pi via HTTP (when SSH doesn't work)
# Uses curl to upload files to a simple HTTP endpoint

set -e

PI_HOST="${PI_HOST:-192.168.1.165}"
PI_PORT="${PI_PORT:-8766}"
PI_PATH="${PI_PATH:-/home/unitares-anima/anima-mcp}"

echo "🚀 Deploying via HTTP to Pi..."
echo ""

# Files to deploy (key files that changed)
FILES=(
    "src/anima_mcp/server.py"
    "src/anima_mcp/display/renderer.py"
    "src/anima_mcp/display/screens.py"
    "src/anima_mcp/growth.py"
    "src/anima_mcp/identity/store.py"
    "src/anima_mcp/llm_gateway.py"
    "src/anima_mcp/messages.py"
    "src/anima_mcp/metacognition.py"
    "src/anima_mcp/self_schema.py"
    "scripts/message_server.py"
    "scripts/alert_check.sh"
)

echo "📦 Files to deploy:"
for file in "${FILES[@]}"; do
    if [ -f "$file" ]; then
        echo "  ✓ $file"
    else
        echo "  ✗ $file (not found)"
    fi
done
echo ""

echo "⚠️  HTTP file upload not yet implemented in anima-mcp server"
echo ""
echo "Alternative options:"
echo ""
echo "1. Use git pull on Pi (if git access works):"
echo "   curl -X POST http://$PI_HOST:$PI_PORT/mcp/ \\"
echo "     -H 'Content-Type: application/json' \\"
echo "     -H 'Accept: application/json, text/event-stream' \\"
echo "     -d '{\"jsonrpc\":\"2.0\",\"method\":\"tools/call\",\"params\":{\"name\":\"git_pull\",\"arguments\":{\"restart\":true}},\"id\":1}'"
echo ""
echo "2. Wait for SSH to be fixed, then use:"
echo "   ./deploy.sh"
echo ""
echo "3. Manual deployment (if you can access Pi another way):"
echo "   - Copy files manually"
echo "   - Or use git pull on Pi: cd ~/anima-mcp && git pull && sudo systemctl restart anima"
echo ""
