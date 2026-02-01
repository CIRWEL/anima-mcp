#!/bin/bash
# Quick deploy script - Run from Mac to deploy changes to Pi

set -e

# Configuration
PI_HOST="${PI_HOST:-lumen.local}"
PI_USER="${PI_USER:-unitares-anima}"
PI_PORT="${PI_PORT:-22}"
PI_PATH="${PI_PATH:-~/anima-mcp}"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}=========================================${NC}"
echo -e "${BLUE}Anima MCP - Deploy to Pi${NC}"
echo -e "${BLUE}=========================================${NC}"
echo ""

# Check if we're in the right directory
if [ ! -f "pyproject.toml" ] || ! grep -q "anima-mcp" pyproject.toml; then
    echo -e "${RED}Error: Must run from anima-mcp directory${NC}"
    exit 1
fi

# Parse arguments
RESTART=true
SHOW_LOGS=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --no-restart)
            RESTART=false
            shift
            ;;
        --logs)
            SHOW_LOGS=true
            shift
            ;;
        --host)
            PI_HOST="$2"
            shift 2
            ;;
        --help)
            echo "Usage: ./deploy.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --no-restart    Don't restart anima service after deploy"
            echo "  --logs          Show logs after deploy"
            echo "  --host HOST     Override Pi hostname/IP (default: lumen.local)"
            echo "  --help          Show this help"
            echo ""
            echo "Environment variables:"
            echo "  PI_HOST         Pi hostname/IP (default: lumen.local)"
            echo "  PI_USER         Pi username (default: unitares-anima)"
            echo "  PI_PORT         SSH port (default: 22)"
            echo "  PI_PATH         Path on Pi (default: ~/anima-mcp)"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use --help for usage"
            exit 1
            ;;
    esac
done

echo -e "${BLUE}Target:${NC} $PI_USER@$PI_HOST:$PI_PATH"
echo ""

# Step 0: Pull Pi's database before deploying (backup state)
# Skip backup if Pi is unreachable - deployment can proceed without it
echo -e "${BLUE}[0/3] Backing up Pi state...${NC}"
if ping -c 1 -W 2 "$PI_HOST" >/dev/null 2>&1; then
    if python3 scripts/sync_state.py pull 2>/dev/null; then
        echo -e "${GREEN}  State backed up${NC}"
    else
        echo -e "${BLUE}  Could not pull state (Pi may be offline). Continuing...${NC}"
    fi
else
    echo -e "${BLUE}  Pi unreachable (WiFi down?) - skipping backup, deployment will proceed${NC}"
    echo -e "${BLUE}  Note: Lumen operates autonomously without WiFi - code changes will apply when connection returns${NC}"
fi
echo ""

# Step 1: Sync code
echo -e "${BLUE}[1/3] Syncing code...${NC}"
# Check connectivity first
if ! ping -c 1 -W 2 "$PI_HOST" >/dev/null 2>&1; then
    echo -e "${RED}✗ Pi unreachable (WiFi down?)${NC}"
    echo -e "${BLUE}  Cannot deploy while Pi is offline${NC}"
    echo -e "${BLUE}  Lumen continues operating autonomously - deploy when WiFi returns${NC}"
    exit 1
fi

rsync -avz \
    --exclude='.venv' \
    --exclude='*.db' \
    --exclude='*.log' \
    --exclude='__pycache__' \
    --exclude='.git' \
    --exclude='*.pyc' \
    --exclude='.pytest_cache' \
    --exclude='.mypy_cache' \
    --exclude='htmlcov' \
    -e "ssh -p $PI_PORT -o ConnectTimeout=5" \
    ./ "$PI_USER@$PI_HOST:$PI_PATH/"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Code synced${NC}"
else
    echo -e "${RED}✗ Sync failed (connection timeout?)${NC}"
    echo -e "${BLUE}  Lumen continues operating autonomously - deploy when WiFi returns${NC}"
    exit 1
fi

# Step 2: Restart service (if requested)
if [ "$RESTART" = true ]; then
    echo ""
    echo -e "${BLUE}[2/3] Restarting anima service...${NC}"
    
    # Check if systemd service exists (system-level, not user)
    if ssh -p $PI_PORT -o ConnectTimeout=5 "$PI_USER@$PI_HOST" "systemctl is-enabled anima-broker.service" 2>/dev/null; then
        # Restart broker first (anima depends on it)
        if ssh -p $PI_PORT -o ConnectTimeout=5 "$PI_USER@$PI_HOST" "sudo systemctl restart anima-broker && sudo systemctl restart anima" 2>/dev/null; then
            echo -e "${GREEN}✓ Services restarted (broker + mind)${NC}"
        else
            echo -e "${YELLOW}⚠ Service restart may have failed (connection issue?)${NC}"
            echo -e "${BLUE}  Services will auto-restart on next boot if needed${NC}"
        fi
    else
        echo -e "${BLUE}ℹ No systemd service found (that's OK)${NC}"
        echo "  To set up service, run on Pi:"
        echo "  ./scripts/setup_pi_service.sh"
    fi
else
    echo ""
    echo -e "${BLUE}[2/3] Skipping restart (--no-restart)${NC}"
fi

# Step 3: Show logs (if requested)
if [ "$SHOW_LOGS" = true ]; then
    echo ""
    echo -e "${BLUE}[3/3] Showing logs...${NC}"
    echo -e "${BLUE}=========================================${NC}"
    ssh -p $PI_PORT "$PI_USER@$PI_HOST" "journalctl -u anima -u anima-broker -n 50 --no-pager" || \
        echo -e "${BLUE}ℹ Could not read logs${NC}"
else
    echo ""
    echo -e "${BLUE}[3/3] Done${NC}"
fi

echo ""
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}Deploy complete!${NC}"
echo -e "${GREEN}=========================================${NC}"
echo ""

if [ "$SHOW_LOGS" = false ]; then
    echo "To view logs, run:"
    echo "  ssh $PI_USER@$PI_HOST 'journalctl -u anima -u anima-broker -f'"
    echo ""
fi

echo "To check status:"
echo "  ssh $PI_USER@$PI_HOST 'systemctl status anima anima-broker'"
echo ""
