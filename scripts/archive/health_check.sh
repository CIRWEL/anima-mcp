#!/bin/bash
# Quick health check for Lumen - verify everything is working

PI_HOST="${PI_HOST:-lumen.local}"
PI_USER="${PI_USER:-unitares-anima}"
SSH_KEY="${SSH_KEY:-~/.ssh/id_ed25519_pi}"

echo "=== Lumen Health Check ==="
echo ""

# Check services
echo "1. Services:"
ssh -i $SSH_KEY $PI_USER@$PI_HOST \
  "sudo systemctl is-active anima anima-broker 2>&1 | grep -q 'active' && echo '  ✅ Both services active' || echo '  ❌ Service issue'"

# Check port
echo "2. Port 8766:"
if ssh -i $SSH_KEY $PI_USER@$PI_HOST \
  "lsof -i :8766 2>&1 | grep -q LISTEN"; then
  echo "  ✅ Port bound correctly"
else
  echo "  ❌ Port not bound (stale process?)"
fi

# Check code imports
echo "3. Code:"
IMPORT_OUTPUT=$(ssh -i $SSH_KEY $PI_USER@$PI_HOST \
  "cd ~/anima-mcp && source .venv/bin/activate && python3 -c 'from anima_mcp.server import create_server' 2>&1")
if echo "$IMPORT_OUTPUT" | grep -q "Traceback\|Error\|ImportError"; then
  echo "  ❌ Import error"
  echo "$IMPORT_OUTPUT" | head -3 | sed 's/^/    /'
else
  echo "  ✅ Code imports OK"
fi

# Check recent logs for errors
echo "4. Recent errors:"
ERRORS=$(ssh -i $SSH_KEY $PI_USER@$PI_HOST \
  "sudo journalctl -u anima --since '5 minutes ago' --no-pager 2>&1 | grep -i 'error\|fatal\|traceback' | wc -l")
if [ "$ERRORS" -eq "0" ]; then
  echo "  ✅ No recent errors"
else
  echo "  ⚠️  $ERRORS errors in last 5 minutes"
fi

# Check uptime
echo "5. Uptime:"
UPTIME=$(ssh -i $SSH_KEY $PI_USER@$PI_HOST \
  "sudo systemctl show anima -p ActiveEnterTimestamp --value 2>&1 | xargs -I {} date -d {} +%s 2>/dev/null || echo 0")
NOW=$(date +%s)
if [ "$UPTIME" -gt 0 ]; then
  ELAPSED=$((NOW - UPTIME))
  MINUTES=$((ELAPSED / 60))
  if [ "$MINUTES" -gt 5 ]; then
    echo "  ✅ Running for ${MINUTES} minutes (stable)"
  else
    echo "  ⚠️  Only ${MINUTES} minutes (recent restart?)"
  fi
else
  echo "  ❓ Could not determine uptime"
fi

echo ""
echo "=== Check complete ==="
