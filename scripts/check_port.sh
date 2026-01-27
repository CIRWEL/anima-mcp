#!/bin/bash
# Check what port Lumen is actually using

echo "=== Checking Lumen's Port ==="
echo ""

# Check service file
echo "1. Service file configuration:"
if [ -f ~/.config/systemd/user/anima.service ]; then
    PORT_IN_SERVICE=$(grep -oP '--port \K[0-9]+' ~/.config/systemd/user/anima.service | head -1)
    if [ -n "$PORT_IN_SERVICE" ]; then
        echo "  Service file says: port $PORT_IN_SERVICE"
    else
        echo "  ⚠️  No --port found in service file (using default)"
    fi
else
    echo "  ⚠️  Service file not found at ~/.config/systemd/user/anima.service"
fi

# Check what's actually running
echo ""
echo "2. What ports are actually listening:"
LISTENING=$(netstat -tlnp 2>/dev/null | grep LISTEN | grep -E ':(876[0-9]|87[0-9][0-9])' || ss -tlnp 2>/dev/null | grep LISTEN | grep -E ':(876[0-9]|87[0-9][0-9])')
if [ -n "$LISTENING" ]; then
    echo "  Found listening ports:"
    echo "$LISTENING" | sed 's/^/    /'
else
    echo "  ❌ No ports in 876x-87xx range are listening"
fi

# Check anima process
echo ""
echo "3. Anima process command line:"
ANIMA_PROC=$(ps aux | grep "anima.*--sse" | grep -v grep | head -1)
if [ -n "$ANIMA_PROC" ]; then
    echo "  Process found:"
    PORT_IN_PROC=$(echo "$ANIMA_PROC" | grep -oP '--port \K[0-9]+' || echo "not found")
    if [ "$PORT_IN_PROC" != "not found" ]; then
        echo "    Port in command: $PORT_IN_PROC"
    else
        echo "    ⚠️  No --port in command (using default)"
    fi
    echo "$ANIMA_PROC" | sed 's/^/    /'
else
    echo "  ❌ No anima --sse process found"
fi

# Check default in code
echo ""
echo "4. Default port in code:"
if [ -f ~/anima-mcp/src/anima_mcp/server.py ]; then
    DEFAULT_PORT=$(grep -oP 'default=[0-9]+.*876[0-9]' ~/anima-mcp/src/anima_mcp/server.py | grep -oP '[0-9]+' | head -1)
    if [ -n "$DEFAULT_PORT" ]; then
        echo "  Code default: port $DEFAULT_PORT"
    else
        echo "  Could not determine default from code"
    fi
else
    echo "  ⚠️  Code file not found"
fi

echo ""
echo "=== Summary ==="
echo "To find the right port, check:"
echo "  1. Service file: ~/.config/systemd/user/anima.service"
echo "  2. Running process: ps aux | grep 'anima.*--sse'"
echo "  3. Listening ports: netstat -tlnp | grep LISTEN"
echo ""
echo "Then update your MCP config to use that port!"
