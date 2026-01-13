#!/bin/bash
# Test Pi SSH connection

PI_IP="192.168.1.165"
PI_USER="unitares-anima"

echo "🔌 Testing SSH connection to Pi..."
echo ""

# Test connection
if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$PI_USER@$PI_IP" "echo '✅ Connected!' && hostname && pwd" 2>/dev/null; then
    echo ""
    echo "✅ SSH connection works!"
    echo ""
    echo "Next steps:"
    echo "  1. Install 'Remote - SSH' extension in Cursor"
    echo "  2. Press Cmd+Shift+P → 'Remote-SSH: Connect to Host'"
    echo "  3. Enter: $PI_USER@$PI_IP"
    echo "  4. Enter password: EISV-4E-CLDO"
    echo "  5. Open folder: /home/$PI_USER"
else
    echo "❌ Connection failed. Check:"
    echo "  - Pi is powered on"
    echo "  - Pi is on same network"
    echo "  - SSH is enabled (sudo systemctl status ssh)"
fi

