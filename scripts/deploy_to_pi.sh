#!/bin/bash
# Deploy anima code to Pi and restart service

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== Deploying Anima to Pi ==="

echo "1. Syncing code..."
rsync -avz --exclude='.venv' --exclude='*.db' --exclude='*.log' --exclude='__pycache__' \
  -e "ssh -p 2222 -i ~/.ssh/id_ed25519_pi" \
  "$PROJECT_DIR/" \
  unitares-anima@192.168.1.165:/home/unitares-anima/anima-mcp/

if [ $? -ne 0 ]; then
    echo "❌ Rsync failed"
    exit 1
fi

echo "2. Restarting anima service..."
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 "systemctl --user restart anima"
sleep 3

echo "3. Checking status..."
if ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 "systemctl --user is-active anima" | grep -q "active"; then
    echo "✅ Anima service is active"
else
    echo "❌ Anima service not active - check logs"
    ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 "journalctl --user -u anima -n 20 --no-pager"
    exit 1
fi

echo ""
echo "4. Recent logs:"
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 "journalctl --user -u anima -n 15 --no-pager"

echo ""
echo "=== Deploy complete ==="
