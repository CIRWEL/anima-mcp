#!/bin/bash
# Setup SSH key authentication for Pi access

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$SCRIPT_DIR/envelope.pi" ] && source "$SCRIPT_DIR/envelope.pi"

PI_IP="${PI_HOST:-192.168.1.165}"
PI_USER="${PI_USER:-unitares-anima}"
PI_PORT="${PI_PORT:-22}"
PI_PASSWORD="${PI_PASSWORD:-}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519_pi}"

[ -z "$PI_PASSWORD" ] && { echo "Set PI_PASSWORD in scripts/envelope.pi (copy from envelope.pi.example)"; exit 1; }

echo "🔑 Setting up SSH key authentication for Pi..."
echo ""

# Check if key exists
if [ ! -f "$SSH_KEY" ]; then
    echo "❌ SSH key not found at $SSH_KEY"
    exit 1
fi

# Copy public key to Pi using expect
expect << EOF
set timeout 30
spawn ssh-copy-id -i "$SSH_KEY.pub" -p $PI_PORT $PI_USER@$PI_IP
expect {
    "password:" {
        send "$PI_PASSWORD\r"
        exp_continue
    }
    "yes/no" {
        send "yes\r"
        exp_continue
    }
    eof
}
EOF

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ SSH key copied successfully!"
    echo ""
    echo "Testing connection..."
    ssh -i "$SSH_KEY" -p $PI_PORT -o StrictHostKeyChecking=no $PI_USER@$PI_IP "echo '✅ Passwordless SSH connection successful!' && hostname && pwd"
    
    if [ $? -eq 0 ]; then
        echo ""
        echo "✅ Setup complete! You can now connect with:"
        echo "   ssh -i $SSH_KEY -p $PI_PORT $PI_USER@$PI_IP"
        echo ""
        echo "Or add to ~/.ssh/config for easier access."
    else
        echo "⚠️  Key copied but connection test failed. You may need to try manually."
    fi
else
    echo "❌ Failed to copy SSH key"
    exit 1
fi
