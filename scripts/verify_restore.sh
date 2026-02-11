#!/bin/bash
# Verify Lumen restore on Pi — run when SSH works
# Usage: ./scripts/verify_restore.sh [host]

PI_USER="unitares-anima"
PI_HOST="${1:-192.168.1.165}"
SSH_KEY="${HOME}/.ssh/id_ed25519_pi"
SSH_OPTS="-i ${SSH_KEY} -o ConnectTimeout=10"

echo "=== Verifying Lumen restore on $PI_HOST ==="
echo ""

# 1. Data files
echo "1. ~/.anima/ data files:"
ssh $SSH_OPTS "$PI_USER@$PI_HOST" "ls -la ~/.anima/*.json ~/.anima/anima.db 2>/dev/null | head -15"
echo ""

# 2. Database integrity
echo "2. Database integrity:"
ssh $SSH_OPTS "$PI_USER@$PI_HOST" "sqlite3 ~/.anima/anima.db 'PRAGMA integrity_check;' 2>/dev/null"
echo ""

# 3. Identity (from DB or logs)
echo "3. Identity check:"
ssh $SSH_OPTS "$PI_USER@$PI_HOST" "sqlite3 ~/.anima/anima.db 'SELECT creature_id, total_awakenings, total_alive_seconds FROM identity LIMIT 1;' 2>/dev/null || echo '(check journalctl -u anima for Awake: Lumen)'"
echo ""

# 4. Service status
echo "4. anima.service:"
ssh $SSH_OPTS "$PI_USER@$PI_HOST" "systemctl is-active anima 2>/dev/null"
echo ""

# 5. Recent logs (identity, learning, errors)
echo "5. Recent logs (last 20 lines):"
ssh $SSH_OPTS "$PI_USER@$PI_HOST" "journalctl -u anima -n 20 --no-pager 2>/dev/null | grep -E 'Awake|Identity|Learning|observations|Error|MCP server'"
echo ""

# 6. Health endpoint
echo "6. Health check:"
curl -s -o /dev/null -w "HTTP %{http_code}\n" "http://${PI_HOST}:8766/health" 2>/dev/null || echo "curl failed (not on same network?)"
echo ""
echo "Done."
