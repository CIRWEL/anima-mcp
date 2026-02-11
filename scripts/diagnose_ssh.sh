#!/bin/bash
# Diagnose SSH connectivity to Pi
# Usage: ./scripts/diagnose_ssh.sh [host]

PI_HOST="${1:-192.168.1.165}"
SSH_KEY="${HOME}/.ssh/id_ed25519_pi"

echo "=== SSH diagnostics for $PI_HOST ==="
echo ""

echo "1. Ping:"
ping -c 2 -W 3 "$PI_HOST" 2>&1 || echo "  FAILED"
echo ""

echo "2. Port 22 (nc):"
nc -zv -w 5 "$PI_HOST" 22 2>&1 || echo "  (nc not found or failed)"
echo ""

echo "3. SSH IPv4 (5s timeout):"
ssh -4 -o ConnectTimeout=5 -o BatchMode=yes -i "$SSH_KEY" unitares-anima@$PI_HOST "echo OK" 2>&1 || true
echo ""

echo "4. SSH with hostname:"
if ping -c 1 lumen.local >/dev/null 2>&1; then
  ssh -4 -o ConnectTimeout=5 -i "$SSH_KEY" unitares-anima@lumen.local "echo OK" 2>&1 || true
else
  echo "  lumen.local not reachable"
fi
echo ""

echo "5. SSH port 2222 (if Pi was configured for it):"
nc -zv -w 3 "$PI_HOST" 2222 2>&1 || echo "  Port 2222 not open"
echo ""

echo "See docs/operations/SSH_TIMEOUT_FIX.md for fixes."
