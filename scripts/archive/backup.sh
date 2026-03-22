#!/bin/bash
#
# Lumen Backup Script
#
# Backs up:
# 1. Identity database (anima.db) from Pi
# 2. Knowledge files (knowledge.json, messages.json)
# 3. Drawings and canvas
#
# Usage: ./backup.sh [--full]
#   --full: Include all drawings (larger backup)
#

PI_USER="unitares-anima"
PI_HOST="${LUMEN_HOST:-lumen}"
BACKUP_DIR="${HOME}/lumen-backups"
DATE=$(date '+%Y-%m-%d_%H%M%S')
BACKUP_PATH="$BACKUP_DIR/$DATE"

log() {
    echo "[$(date '+%H:%M:%S')] $1"
}

# Create backup directory
mkdir -p "$BACKUP_PATH"

log "=== Lumen Backup Starting ==="
log "Backup location: $BACKUP_PATH"

# 1. Backup identity database
log "Backing up identity database..."
scp -o ConnectTimeout=10 "$PI_USER@$PI_HOST:anima-mcp/anima.db" "$BACKUP_PATH/" 2>/dev/null
if [ $? -eq 0 ]; then
    log "  - anima.db: $(du -h "$BACKUP_PATH/anima.db" | cut -f1)"
else
    log "  - anima.db: FAILED (trying ~/.anima location)"
    scp -o ConnectTimeout=10 "$PI_USER@$PI_HOST:.anima/anima.db" "$BACKUP_PATH/" 2>/dev/null
fi

# 2. Backup knowledge files
log "Backing up knowledge files..."
scp -o ConnectTimeout=10 "$PI_USER@$PI_HOST:.anima/knowledge.json" "$BACKUP_PATH/" 2>/dev/null && \
    log "  - knowledge.json: $(du -h "$BACKUP_PATH/knowledge.json" 2>/dev/null | cut -f1)"

scp -o ConnectTimeout=10 "$PI_USER@$PI_HOST:.anima/messages.json" "$BACKUP_PATH/" 2>/dev/null && \
    log "  - messages.json: $(du -h "$BACKUP_PATH/messages.json" 2>/dev/null | cut -f1)"

scp -o ConnectTimeout=10 "$PI_USER@$PI_HOST:.anima/canvas.json" "$BACKUP_PATH/" 2>/dev/null && \
    log "  - canvas.json: $(du -h "$BACKUP_PATH/canvas.json" 2>/dev/null | cut -f1)"

# 3. Full backup includes drawings
if [ "$1" == "--full" ]; then
    log "Backing up drawings (full backup)..."
    mkdir -p "$BACKUP_PATH/drawings"
    rsync -az --progress "$PI_USER@$PI_HOST:.anima/drawings/" "$BACKUP_PATH/drawings/" 2>/dev/null
    DRAWING_COUNT=$(ls -1 "$BACKUP_PATH/drawings/" 2>/dev/null | wc -l)
    log "  - drawings: $DRAWING_COUNT files"
fi

# 4. Create backup manifest
log "Creating backup manifest..."
cat > "$BACKUP_PATH/manifest.json" << EOF
{
    "date": "$(date -Iseconds)",
    "host": "$PI_HOST",
    "files": [
$(ls -1 "$BACKUP_PATH" | grep -v manifest.json | while read f; do
    SIZE=$(du -h "$BACKUP_PATH/$f" 2>/dev/null | cut -f1)
    echo "        {\"name\": \"$f\", \"size\": \"$SIZE\"},"
done | sed '$ s/,$//')
    ],
    "type": "${1:-incremental}"
}
EOF

# 5. Sync key insights to UNITARES (if available)
if command -v curl &> /dev/null; then
    UNITARES_URL="${UNITARES_URL:-https://unitares.ngrok.io}"
    log "Syncing backup record to UNITARES..."

    # Just log that backup happened - actual sync is done through MCP
    curl -s -X POST "$UNITARES_URL/mcp" \
        -H "Content-Type: application/json" \
        -H "X-Agent-Id: lumen-backup" \
        -d "{
            \"jsonrpc\": \"2.0\",
            \"id\": 1,
            \"method\": \"tools/call\",
            \"params\": {
                \"name\": \"leave_note\",
                \"arguments\": {
                    \"note\": \"Backup completed: $DATE\",
                    \"tags\": [\"backup\", \"lumen\", \"automated\"]
                }
            }
        }" > /dev/null 2>&1
fi

# 6. Cleanup old backups (keep last 10)
log "Cleaning up old backups..."
cd "$BACKUP_DIR"
ls -1t | tail -n +11 | while read old; do
    log "  - Removing: $old"
    rm -rf "$old"
done

# Summary
TOTAL_SIZE=$(du -sh "$BACKUP_PATH" | cut -f1)
log "=== Backup Complete ==="
log "Total size: $TOTAL_SIZE"
log "Location: $BACKUP_PATH"

# List contents
echo ""
echo "Backup contents:"
ls -lh "$BACKUP_PATH"
