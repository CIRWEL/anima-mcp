#!/bin/bash
# DB maintenance - WAL checkpoint + integrity check
# Run hourly via cron: 0 * * * * /home/unitares-anima/anima-mcp/scripts/db_maintenance.sh

DB="/home/unitares-anima/.anima/anima.db"
LOGFILE="/home/unitares-anima/.anima/db_maintenance.log"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S'): $1" >> "$LOGFILE"
}

if [ ! -f "$DB" ]; then
    log "ERROR: DB not found at $DB"
    exit 1
fi

# WAL checkpoint - flush write-ahead log to main DB
WAL_SIZE=$(stat -c%s "${DB}-wal" 2>/dev/null || echo 0)
if [ "$WAL_SIZE" -gt 1048576 ]; then  # > 1MB
    sqlite3 "$DB" "PRAGMA wal_checkpoint(TRUNCATE);" 2>/dev/null
    NEW_WAL_SIZE=$(stat -c%s "${DB}-wal" 2>/dev/null || echo 0)
    log "WAL checkpoint: ${WAL_SIZE} -> ${NEW_WAL_SIZE} bytes"
fi

# Integrity check (only once per day at midnight hour)
HOUR=$(date +%H)
if [ "$HOUR" = "00" ]; then
    RESULT=$(sqlite3 "$DB" "PRAGMA integrity_check;" 2>&1)
    if [ "$RESULT" = "ok" ]; then
        log "Integrity check: OK"
    else
        log "INTEGRITY FAILURE: $RESULT"
        # Copy corrupted DB for forensics before backup overwrites it
        cp "$DB" "${DB}.corrupted.$(date +%Y%m%d_%H%M)"
        log "Corrupted DB saved for analysis"
    fi
fi

# Keep log from growing
if [ -f "$LOGFILE" ]; then
    tail -100 "$LOGFILE" > "${LOGFILE}.tmp" && mv "${LOGFILE}.tmp" "$LOGFILE"
fi
