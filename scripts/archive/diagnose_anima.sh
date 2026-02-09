#!/bin/bash
# Diagnose why anima MCP server isn't working
# Usage: ./scripts/diagnose_anima.sh

set -e

echo "🔍 Diagnosing anima MCP server..."
echo ""

# Check 1: Is server running?
echo "1️⃣  Checking if anima server is running..."
if systemctl --user is-active --quiet anima.service 2>/dev/null || systemctl is-active --quiet anima.service 2>/dev/null; then
    echo "   ✅ anima service is running"
else
    echo "   ❌ anima service is NOT running"
    echo "   Start with: systemctl --user start anima"
fi

# Check 2: Is port in use?
echo ""
echo "2️⃣  Checking port 8766..."
if lsof -i :8766 &> /dev/null; then
    echo "   ✅ Port 8766 is in use"
    lsof -i :8766 | head -2
else
    echo "   ❌ Port 8766 is NOT in use"
    echo "   Server may not be running"
fi

# Check 3: Can we connect locally?
echo ""
echo "3️⃣  Testing local connection..."
if curl -s http://localhost:8766/health &> /dev/null; then
    echo "   ✅ Server responds to /health"
    curl -s http://localhost:8766/health
else
    echo "   ❌ Server does NOT respond to /health"
fi

# Check 4: Check for FastMCP
echo ""
echo "4️⃣  Checking FastMCP availability..."
if python3 -c "from mcp.server.fastmcp import FastMCP" 2>/dev/null; then
    echo "   ✅ FastMCP is available"
else
    echo "   ❌ FastMCP is NOT available"
    echo "   Install with: pip install 'mcp[cli]'"
fi

# Check 5: Check logs
echo ""
echo "5️⃣  Recent logs (last 10 lines):"
if systemctl --user status anima.service &> /dev/null; then
    journalctl --user -u anima.service -n 10 --no-pager || true
elif systemctl status anima.service &> /dev/null; then
    journalctl -u anima.service -n 10 --no-pager || true
else
    echo "   ⚠️  Cannot access logs (service may not exist)"
fi

# Check 6: Check for common errors
echo ""
echo "6️⃣  Checking for common issues..."
if pgrep -f "anima.*--sse" &> /dev/null; then
    echo "   ✅ anima process found"
else
    echo "   ❌ No anima process found"
fi

# Check 7: Check database
echo ""
echo "7️⃣  Checking database..."
DB_PATH="${ANIMA_DB:-$HOME/.anima/anima.db}"
if [ -f "$DB_PATH" ]; then
    echo "   ✅ Database exists: $DB_PATH"
    DB_SIZE=$(stat -f%z "$DB_PATH" 2>/dev/null || stat -c%s "$DB_PATH" 2>/dev/null || echo "unknown")
    echo "   Size: $DB_SIZE bytes"
else
    echo "   ⚠️  Database not found: $DB_PATH"
    echo "   Will be created on first run"
fi

# Check 8: Check ngrok (if configured)
echo ""
echo "8️⃣  Checking ngrok tunnel..."
if pgrep -f "ngrok.*8766" &> /dev/null; then
    echo "   ✅ ngrok tunnel is running"
    TUNNEL_URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | python3 -c "import sys, json; data=json.load(sys.stdin); print(data['tunnels'][0]['public_url'] if data.get('tunnels') else 'Not available')" 2>/dev/null || echo "Not available")
    if [ "$TUNNEL_URL" != "Not available" ]; then
        echo "   URL: $TUNNEL_URL"
    fi
else
    echo "   ⚠️  ngrok tunnel is NOT running"
    echo "   Set up with: ./scripts/setup_ngrok_basic_auth.sh"
fi

echo ""
echo "✅ Diagnosis complete!"
echo ""
echo "Quick fixes:"
echo "  Start server: systemctl --user start anima"
echo "  Check logs: journalctl --user -u anima -f"
echo "  Restart: systemctl --user restart anima"
echo "  Setup ngrok: ./scripts/setup_ngrok_basic_auth.sh"
