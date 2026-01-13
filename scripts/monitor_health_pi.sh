#!/bin/bash
# Health monitoring script for Anima on Raspberry Pi
# Checks service status, connectivity, and sensor health

set -e

# Configuration
SERVICE_NAME="${SERVICE_NAME:-lumen}"
HEALTH_URL="${HEALTH_URL:-http://localhost:8765/health}"
CHECK_INTERVAL="${CHECK_INTERVAL:-60}"
MAX_FAILURES="${MAX_FAILURES:-3}"
ALERT_LOG="${ALERT_LOG:-/tmp/anima_alerts.log}"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# State tracking
FAILURE_COUNT=0
LAST_STATUS="unknown"

check_service() {
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        echo -e "${GREEN}✅ Service running${NC}"
        return 0
    else
        echo -e "${RED}❌ Service not running${NC}"
        FAILURE_COUNT=$((FAILURE_COUNT + 1))
        LAST_STATUS="service_down"
        return 1
    fi
}

check_health_endpoint() {
    local response
    local status
    
    response=$(curl -s -w "\n%{http_code}" "$HEALTH_URL" 2>/dev/null || echo -e "\n000")
    status=$(echo "$response" | tail -1)
    body=$(echo "$response" | sed '$d')
    
    if [ "$status" = "200" ]; then
        # Try to parse JSON response
        server_status=$(echo "$body" | python3 -c "import sys, json; print(json.load(sys.stdin).get('status', 'unknown'))" 2>/dev/null || echo "unknown")
        
        if [ "$server_status" = "ok" ] || [ "$server_status" = "healthy" ]; then
            echo -e "${GREEN}✅ Health endpoint OK${NC}"
            FAILURE_COUNT=0
            LAST_STATUS="ok"
            return 0
        else
            echo -e "${YELLOW}⚠️  Health endpoint returned: $server_status${NC}"
            FAILURE_COUNT=$((FAILURE_COUNT + 1))
            LAST_STATUS="unhealthy"
            return 1
        fi
    else
        echo -e "${RED}❌ Health endpoint failed (HTTP $status)${NC}"
        FAILURE_COUNT=$((FAILURE_COUNT + 1))
        LAST_STATUS="http_error"
        return 1
    fi
}

check_sensors() {
    # Check if sensors are accessible (basic check)
    if [ -d "/sys/class/thermal" ]; then
        cpu_temp=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null | awk '{print $1/1000}')
        if [ -n "$cpu_temp" ]; then
            echo -e "${GREEN}✅ Sensors accessible (CPU: ${cpu_temp}°C)${NC}"
            return 0
        fi
    fi
    
    echo -e "${YELLOW}⚠️  Sensor check skipped (may be mock sensors)${NC}"
    return 0  # Don't fail on sensor check - mock sensors are OK
}

check_display() {
    # Check if display process is running (if using hardware display)
    if pgrep -f "display.*loop" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ Display loop running${NC}"
        return 0
    else
        # Display loop might not be separate process - that's OK
        echo -e "${YELLOW}ℹ️  Display check skipped${NC}"
        return 0
    fi
}

check_database() {
    local db_path="/home/unitares-anima/anima-mcp/anima.db"
    
    if [ -f "$db_path" ]; then
        if [ -r "$db_path" ] && [ -w "$db_path" ]; then
            echo -e "${GREEN}✅ Database accessible${NC}"
            return 0
        else
            echo -e "${RED}❌ Database permissions issue${NC}"
            return 1
        fi
    else
        echo -e "${YELLOW}⚠️  Database file not found (may be created on first run)${NC}"
        return 0  # Don't fail - DB might be created on first run
    fi
}

check_logs() {
    # Check for recent errors in logs
    local error_count
    error_count=$(journalctl -u "$SERVICE_NAME" --since "5 minutes ago" --no-pager 2>/dev/null | grep -i "error\|exception\|traceback" | wc -l || echo "0")
    
    if [ "$error_count" -gt 10 ]; then
        echo -e "${YELLOW}⚠️  High error count in logs: $error_count${NC}"
        return 1
    elif [ "$error_count" -gt 0 ]; then
        echo -e "${YELLOW}ℹ️  Some errors in logs: $error_count${NC}"
        return 0
    else
        echo -e "${GREEN}✅ No recent errors in logs${NC}"
        return 0
    fi
}

send_alert() {
    local message="$1"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    echo -e "${RED}🚨 ALERT: $message${NC}"
    echo "  Time: $timestamp"
    echo "  Failures: $FAILURE_COUNT"
    
    # Log to file
    echo "[$timestamp] ALERT: $message (Failures: $FAILURE_COUNT)" >> "$ALERT_LOG" 2>/dev/null || true
    
    # Optional: Send email or other notification
    # if [ -n "$ALERT_EMAIL" ]; then
    #     echo "Sending email alert..."
    # fi
}

restart_service() {
    echo -e "${YELLOW}🔄 Attempting service restart...${NC}"
    sudo systemctl restart "$SERVICE_NAME"
    sleep 5
    
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        echo -e "${GREEN}✅ Service restarted successfully${NC}"
        FAILURE_COUNT=0
        return 0
    else
        echo -e "${RED}❌ Service restart failed${NC}"
        return 1
    fi
}

main() {
    echo "🔍 Anima Health Monitor (Pi)"
    echo "=============================="
    echo "Service: $SERVICE_NAME"
    echo "Health URL: $HEALTH_URL"
    echo "Check interval: ${CHECK_INTERVAL}s"
    echo "Max failures: $MAX_FAILURES"
    echo ""
    
    if [ "$1" = "--once" ]; then
        # Single check mode
        check_service
        check_health_endpoint
        check_sensors
        check_display
        check_database
        check_logs
        
        if [ $FAILURE_COUNT -ge $MAX_FAILURES ]; then
            send_alert "Health check failed $FAILURE_COUNT times"
            exit 1
        fi
        
        exit 0
    fi
    
    # Continuous monitoring mode
    echo "Starting continuous monitoring (Ctrl+C to stop)..."
    echo ""
    
    while true; do
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Checking health..."
        
        FAILURE_COUNT=0
        
        check_service || true
        check_health_endpoint || true
        check_sensors || true
        check_display || true
        check_database || true
        check_logs || true
        
        if [ $FAILURE_COUNT -ge $MAX_FAILURES ]; then
            send_alert "Health check failed $FAILURE_COUNT consecutive times"
            
            # Attempt automatic recovery
            if [ "$LAST_STATUS" = "service_down" ]; then
                restart_service || true
            fi
        fi
        
        echo ""
        sleep "$CHECK_INTERVAL"
    done
}

main "$@"
