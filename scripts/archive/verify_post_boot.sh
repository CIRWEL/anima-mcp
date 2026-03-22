#!/bin/bash
# Post-boot verification after SD card fixes
# Verifies SSH access, canvas cleanup, and Lumen services

PI_HOST="${PI_HOST:-lumen.local}"
SSH_USER="${SSH_USER:-unitares-anima}"
SSH_PORT="${SSH_PORT:-22}"

echo "=== Post-Boot Verification ==="
echo "Pi host: $PI_HOST"
echo "SSH Port: $SSH_PORT"
echo ""

# 1. Test SSH access
echo "1. Testing SSH access..."
if ssh -p $SSH_PORT -o ConnectTimeout=5 $SSH_USER@$PI_HOST 'echo "SSH works"' 2>/dev/null; then
    echo "  ✅ SSH access working on port $SSH_PORT"
else
    echo "  ❌ SSH not working on port $SSH_PORT"
    echo "  Trying port 2222..."
    if ssh -p 2222 -o ConnectTimeout=5 $SSH_USER@$PI_HOST 'echo "SSH works"' 2>/dev/null; then
        echo "  ✅ SSH works on port 2222 (fallback)"
        SSH_PORT=2222
    else
        echo "  ❌ SSH not working on either port"
        echo "  Check:"
        echo "    - Pi is fully booted (wait 60+ seconds)"
        echo "    - /boot/ssh file exists"
        echo "    - Network connectivity: ping $PI_HOST"
        exit 1
    fi
fi

echo ""
echo "2. Checking canvas.json cleanup..."
CANVAS_EXISTS=$(ssh -p $SSH_PORT $SSH_USER@$PI_HOST '[ -f ~/.anima/canvas.json ] && echo "exists" || echo "deleted"' 2>/dev/null)
if [ "$CANVAS_EXISTS" = "deleted" ]; then
    echo "  ✅ canvas.json was successfully deleted"
else
    echo "  ⚠️  canvas.json still exists (may need manual deletion)"
    echo "  Run: ssh -p $SSH_PORT $SSH_USER@$PI_HOST 'rm -f ~/.anima/canvas.json'"
fi

echo ""
echo "3. Checking Lumen services..."
SERVICES=$(ssh -p $SSH_PORT $SSH_USER@$PI_HOST 'sudo systemctl status anima anima-broker --no-pager 2>&1' | grep -E "Active:|Loaded:")
echo "$SERVICES" | sed 's/^/  /'

ANIMA_ACTIVE=$(ssh -p $SSH_PORT $SSH_USER@$PI_HOST 'sudo systemctl is-active anima 2>&1')
if [ "$ANIMA_ACTIVE" = "active" ]; then
    echo "  ✅ anima service is active"
else
    echo "  ⚠️  anima service status: $ANIMA_ACTIVE"
    echo "  May need restart: ssh -p $SSH_PORT $SSH_USER@$PI_HOST 'sudo systemctl restart anima-broker && sleep 2 && sudo systemctl restart anima'"
fi

echo ""
echo "4. Checking MCP server port (8766)..."
PORT_CHECK=$(ssh -p $SSH_PORT $SSH_USER@$PI_HOST 'lsof -i :8766 2>&1' | grep LISTEN)
if [ -n "$PORT_CHECK" ]; then
    echo "  ✅ Port 8766 is listening"
    echo "$PORT_CHECK" | sed 's/^/    /'
    echo ""
    echo "  MCP endpoint should be: http://$PI_HOST:8766/mcp/"
else
    echo "  ❌ Port 8766 is NOT listening"
    echo "  Checking other ports..."
    for port in 8765 8767; do
        CHECK=$(ssh -p $SSH_PORT $SSH_USER@$PI_HOST "lsof -i :$port 2>&1" | grep LISTEN)
        if [ -n "$CHECK" ]; then
            echo "    Port $port is listening:"
            echo "$CHECK" | sed 's/^/      /'
        fi
    done
fi

echo ""
echo "5. Checking recent errors..."
ERRORS=$(ssh -p $SSH_PORT $SSH_USER@$PI_HOST 'sudo journalctl -u anima --since "2 minutes ago" --no-pager 2>&1' | grep -iE "error|fatal|traceback|canvas" | tail -5)
if [ -n "$ERRORS" ]; then
    echo "  Recent errors found:"
    echo "$ERRORS" | sed 's/^/    /'
else
    echo "  ✅ No recent errors"
fi

echo ""
echo "=== Verification Complete ==="
echo ""
echo "⚠️  IMPORTANT: After confirming everything works, remove the cleanup command from cmdline.txt:"
echo "   ssh -p $SSH_PORT $SSH_USER@$PI_HOST 'sudo nano /boot/cmdline.txt'"
echo "   Remove: systemd.run=/bin/rm+-f+/home/unitares-anima/.anima/canvas.json"
echo "   (Otherwise it will try to delete canvas.json on every boot)"
echo ""
echo "If Lumen's display is working, you're all set! 🎉"
