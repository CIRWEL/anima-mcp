#!/bin/bash
# Diagnose why Pi network access isn't working

echo "=== Network Access Diagnosis ==="
echo ""

# Check if we can reach Pi
echo "1. Pi connectivity:"
if ping -c 1 raspberrypi.local &>/dev/null; then
    echo "  ✅ Pi is reachable"
else
    echo "  ❌ Pi not reachable via raspberrypi.local"
    echo "  Try: ping -c 1 <pi-ip-address>"
    exit 1
fi

# Check SSH access
echo "2. SSH access:"
if ssh -o ConnectTimeout=5 pi@raspberrypi.local 'echo "SSH works"' 2>/dev/null; then
    echo "  ✅ SSH works"
else
    echo "  ❌ SSH not working"
    echo "  Check: ssh pi@raspberrypi.local"
    exit 1
fi

# Check services
echo "3. Service status:"
SERVICES=$(ssh pi@raspberrypi.local 'systemctl --user status anima anima-broker --no-pager 2>&1' | grep -E "Active:|Loaded:")
echo "$SERVICES" | sed 's/^/  /'

# Check if anima service is actually running
ANIMA_ACTIVE=$(ssh pi@raspberrypi.local 'systemctl --user is-active anima 2>&1')
if [ "$ANIMA_ACTIVE" = "active" ]; then
    echo "  ✅ anima service is active"
else
    echo "  ❌ anima service is NOT active: $ANIMA_ACTIVE"
fi

# Check port 8766
echo "4. Port 8766:"
PORT_CHECK=$(ssh pi@raspberrypi.local 'lsof -i :8766 2>&1')
if echo "$PORT_CHECK" | grep -q LISTEN; then
    echo "  ✅ Port 8766 is listening"
    echo "$PORT_CHECK" | grep LISTEN | sed 's/^/    /'
else
    echo "  ❌ Port 8766 is NOT listening"
    echo "  Checking for stale processes..."
    STALE=$(ssh pi@raspberrypi.local 'pgrep -f "anima.*--sse" 2>&1')
    if [ -n "$STALE" ]; then
        echo "    Found stale processes: $STALE"
    else
        echo "    No stale processes found"
    fi
fi

# Check recent logs
echo "5. Recent errors:"
ERRORS=$(ssh pi@raspberrypi.local 'journalctl --user -u anima --since "5 minutes ago" --no-pager 2>&1 | grep -i "error\|fatal\|traceback\|address already in use" | tail -5')
if [ -n "$ERRORS" ]; then
    echo "$ERRORS" | sed 's/^/  /'
else
    echo "  ✅ No recent errors"
fi

# Check if process is running
echo "6. Process check:"
PROCESS=$(ssh pi@raspberrypi.local 'ps aux | grep "anima.*--sse" | grep -v grep')
if [ -n "$PROCESS" ]; then
    echo "  ✅ anima --sse process found:"
    echo "$PROCESS" | sed 's/^/    /'
else
    echo "  ❌ No anima --sse process found"
fi

# Check network binding
echo "7. Network binding:"
BINDING=$(ssh pi@raspberrypi.local 'netstat -tlnp 2>/dev/null | grep 8766 || ss -tlnp 2>/dev/null | grep 8766')
if [ -n "$BINDING" ]; then
    echo "  ✅ Port 8766 binding:"
    echo "$BINDING" | sed 's/^/    /'
    # Check if bound to 0.0.0.0 (accessible) or 127.0.0.1 (local only)
    if echo "$BINDING" | grep -q "0.0.0.0:8766\|:::8766"; then
        echo "  ✅ Bound to 0.0.0.0 (network accessible)"
    elif echo "$BINDING" | grep -q "127.0.0.1:8766"; then
        echo "  ⚠️  Bound to 127.0.0.1 (local only - not network accessible!)"
    fi
else
    echo "  ❌ Port 8766 not bound"
fi

echo ""
echo "=== Diagnosis complete ==="
echo ""
echo "If port 8766 is not listening, try:"
echo "  ssh pi@raspberrypi.local 'systemctl --user restart anima-broker && sleep 2 && systemctl --user restart anima'"
echo ""
echo "If port is bound to 127.0.0.1, check systemd service file for --host 0.0.0.0"
