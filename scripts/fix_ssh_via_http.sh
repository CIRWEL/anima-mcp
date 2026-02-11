#!/bin/bash
# Fix SSH port via HTTP — for headless Pi when port 22 is blocked
# 
# Prerequisites:
#   1. Pi's HTTP (8766) is reachable: curl -s http://192.168.1.165:8766/health
#   2. Code with fix_ssh_port is pushed to git
#   3. Run from anima-mcp repo: ./scripts/fix_ssh_via_http.sh
#
# Flow: git_pull (gets new code, restarts) → wait → fix_ssh_port → SSH on 2222

set -e

PI_URL="${LUMEN_URL:-http://192.168.1.165:8766}"
PORT="${1:-2222}"

echo "=== Headless SSH fix via HTTP ==="
echo "Pi URL: $PI_URL"
echo "Target SSH port: $PORT"
echo ""

# Call tool via REST API
call_tool() {
    local name="$1"
    local args="$2"
    curl -s -X POST "$PI_URL/v1/tools/call" \
        -H "Content-Type: application/json" \
        -d "{\"name\": \"$name\", \"arguments\": $args}" \
        --connect-timeout 10 --max-time 30
}

echo "1. Pulling latest code (includes fix_ssh_port)..."
result=$(call_tool "git_pull" '{"restart": true, "stash": true}' 2>/dev/null || true)
if echo "$result" | grep -q '"success":true'; then
    echo "   ✅ Git pull OK, server restarting..."
else
    echo "   ⚠️  Git pull may have failed (or no new commits)"
    echo "   Response: $result"
fi

echo ""
echo "2. Waiting 15s for server restart..."
sleep 15

echo ""
echo "3. Switching SSH to port $PORT..."
result=$(call_tool "fix_ssh_port" "{\"port\": $PORT}" 2>/dev/null || true)

if echo "$result" | grep -q '"success":true'; then
    echo "   ✅ SSH now on port $PORT!"
    echo ""
    echo "Connect with:"
    echo "   ssh -p $PORT -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165"
    echo ""
else
    echo "   Response: $result"
    echo ""
    echo "If fix_ssh_port not found: push this repo to git, then run again."
fi
