#!/bin/bash
# Remote Monitor
# Connects to UNITARES to view the REAL Anima state.

REMOTE_USER="unitares-anima"
REMOTE_HOST="lumen.local"
REMOTE_DIR="~/anima-mcp"

echo "Connecting to $REMOTE_HOST..."
echo "View: Dashboard (Remote)"

# SSH -t forces TTY allocation so curses (dashboard) works
ssh -t $REMOTE_USER@$REMOTE_HOST "cd $REMOTE_DIR && python3 scripts/anima_dashboard.py"
