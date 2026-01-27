#!/bin/bash
# Quick restart script for Lumen when network access is blocked

PI_IP="${PI_IP:-192.168.1.164}"
SSH_KEY="${SSH_KEY:-~/.ssh/id_ed25519_pi}"
SSH_PORT="${SSH_PORT:-22}"
SSH_USER="${SSH_USER:-cirwel}"

echo "=== Restarting Lumen on $PI_IP ==="

# Check SSH access (try with key first, then password auth)
if ! ssh -p $SSH_PORT -i $SSH_KEY -o ConnectTimeout=5 $SSH_USER@$PI_IP 'echo "SSH works"' 2>/dev/null; then
    if ! ssh -p $SSH_PORT -o ConnectTimeout=5 $SSH_USER@$PI_IP 'echo "SSH works"' 2>/dev/null; then
        echo "❌ Cannot SSH to Pi at $PI_IP"
        echo "Check:"
        echo "  1. Pi is on network"
        echo "  2. SSH key: $SSH_KEY (or password auth)"
        echo "  3. SSH port: $SSH_PORT"
        exit 1
    fi
fi

echo "1. Checking current status..."
ssh -p $SSH_PORT $SSH_USER@$PI_IP \
  "systemctl --user status anima anima-broker --no-pager | head -15"

echo ""
echo "2. Checking ports..."
ssh -p $SSH_PORT $SSH_USER@$PI_IP \
  "for port in 8765 8766 8767; do echo -n \"Port \$port: \"; lsof -i :\$port 2>&1 | grep LISTEN && echo \" ✅\" || echo \" ❌\"; done"

echo ""
echo "3. Killing stale processes..."
ssh -p $SSH_PORT $SSH_USER@$PI_IP \
  "pkill -f 'anima.*--sse' 2>&1; sleep 1"

echo ""
echo "4. Resetting failed state..."
ssh -p $SSH_PORT $SSH_USER@$PI_IP \
  "systemctl --user reset-failed anima anima-broker 2>&1"

echo ""
echo "5. Restarting services..."
ssh -p $SSH_PORT $SSH_USER@$PI_IP \
  "systemctl --user restart anima-broker"
sleep 2
ssh -p $SSH_PORT $SSH_USER@$PI_IP \
  "systemctl --user restart anima"
sleep 3

echo ""
echo "6. Checking status..."
ssh -p $SSH_PORT $SSH_USER@$PI_IP \
  "systemctl --user status anima anima-broker --no-pager | head -15"

echo ""
echo "7. Checking which port is listening..."
ssh -p $SSH_PORT $SSH_USER@$PI_IP \
  "for port in 8765 8766 8767; do echo -n \"Port \$port: \"; lsof -i :\$port 2>&1 | grep LISTEN && echo \" ✅\" || echo \" ❌\"; done"

echo ""
echo "=== Restart complete ==="
echo ""
echo "If a port is listening, update your MCP config to use:"
echo "  http://$PI_IP:<port>/sse"
