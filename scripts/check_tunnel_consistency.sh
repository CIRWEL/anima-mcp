#!/bin/bash
# Check connection consistency for multiple ngrok tunnels
# Usage: ./scripts/check_tunnel_consistency.sh [primary_url] [backup_url]

PRIMARY_URL="${1:-https://lumen-anima.ngrok.io/mcp/}"
BACKUP_URL="${2:-https://anima-backup.ngrok.io/mcp/}"

echo "🔍 Checking tunnel connection consistency..."
echo ""

check_tunnel() {
    local url=$1
    local name=$2
    
    echo "Testing $name: $url"
    
    # Try to connect with proper MCP headers
    response=$(curl -s -w "\n%{http_code}" --max-time 5 \
        -H "Accept: text/event-stream" \
        -H "Content-Type: application/json" \
        "$url" 2>&1)
    
    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | head -n-1)
    
    if [ "$http_code" = "200" ] || echo "$body" | grep -q "event: endpoint"; then
        echo "   ✅ $name: Connected (HTTP $http_code)"
        return 0
    elif [ "$http_code" = "000" ]; then
        echo "   ❌ $name: Connection failed (timeout/unreachable)"
        return 1
    else
        echo "   ⚠️  $name: HTTP $http_code"
        echo "   Response: $(echo "$body" | head -c 100)"
        return 2
    fi
}

# Check both tunnels
primary_status=0
backup_status=0

check_tunnel "$PRIMARY_URL" "Primary" || primary_status=$?
echo ""
check_tunnel "$BACKUP_URL" "Backup" || backup_status=$?

echo ""
echo "📊 Consistency Report:"
echo ""

if [ $primary_status -eq 0 ] && [ $backup_status -eq 0 ]; then
    echo "   ✅ Both tunnels operational"
    echo "   ✅ High availability - redundancy active"
elif [ $primary_status -eq 0 ]; then
    echo "   ✅ Primary tunnel operational"
    echo "   ⚠️  Backup tunnel unavailable"
elif [ $backup_status -eq 0 ]; then
    echo "   ⚠️  Primary tunnel unavailable"
    echo "   ✅ Backup tunnel operational (failover active)"
else
    echo "   ❌ Both tunnels unavailable"
    echo "   ⚠️  Check ngrok services and network connectivity"
fi

echo ""
echo "💡 Tip: Run this script periodically to monitor connection consistency"
echo "   Add to crontab: */5 * * * * /path/to/check_tunnel_consistency.sh"
