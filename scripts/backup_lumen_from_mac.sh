#!/bin/bash
# CANONICAL COPY. This runs from ~/scripts/backup_lumen.sh on the operator's
# Mac via launchd (com.unitares.lumen-backup, daily 03:00). It lived ONLY there
# and was never version controlled — including the 2026-07-30 hang fix below,
# which existed on exactly one disk. Committed here so it survives that disk.
# If you edit the live copy, mirror it here (and vice versa).
# Backup Lumen's data from Pi to Mac
# Run daily via launchd: com.unitares.lumen-backup.plist
#
# Purpose: recover Lumen's accumulated DB (identity/memory/EISV history) after
# an SD-card or box failure. The DB is the irreplaceable artifact; the rest of
# ~/.anima is largely regenerable.
#
# RESTORE: copy the newest verified snapshot back to the Pi, e.g.
#   scp $BACKUP_DIR/anima_<latest>.db unitares-anima@lumen-local:~/.anima/anima.db
# (stop the anima service first; the snapshot is a consistent sqlite3 .backup).
# If the Mac is also gone, pull the off-site copy from HF instead:
#   hf download hikewa/lumen-db-backups daily/anima_<Dow>.db --repo-type dataset
# (private dataset; day-of-week rotation holds the last 7 daily snapshots).

BACKUP_DIR="/Users/cirwel/backups/lumen"
DATE=$(date +%Y%m%d_%H%M)
PI_HOST="lumen-local"
SSH_KEY="/Users/cirwel/.ssh/id_ed25519_pi"
# ServerAlive* bounds a STALLED transfer, which ConnectTimeout does not:
# ConnectTimeout only covers session setup, so an rsync whose peer goes away
# mid-stream can block forever. The 2026-07 log is full of "Connection closed
# by remote host" / "hangup on receiver" from exactly that. 15s x 4 = the
# session dies within ~60s instead of hanging the whole run.
SSH_OPTS="-i $SSH_KEY -o ConnectTimeout=10 -o StrictHostKeyChecking=no -o ServerAliveInterval=15 -o ServerAliveCountMax=4"
LOG="/Users/cirwel/backups/lumen_backup.log"

# Off-site copy (3-2-1): push each verified DB snapshot to a private HF dataset
# so a Mac-disk or physical failure can't take the Pi and its only backup at
# once. Day-of-week rotation = 7 off-site recovery points, bounded working set.
# Off-site push is best-effort: a failure is logged but does not fail the run,
# because the local backup is already captured and verified.
HF_BIN="/Library/Frameworks/Python.framework/Versions/3.14/bin/hf"
HF_REPO="hikewa/lumen-db-backups"
HF_BACKUP="${HF_BACKUP:-1}"   # set HF_BACKUP=0 to skip the off-site push

mkdir -p "$BACKUP_DIR"

# Stricter exit policy: a run is only "ok" if it produces a fresh, consistent
# backup this invocation. Any path that fails to capture one sets FAILED=1 and
# the script exits non-zero, so the launchd outcome wrapper records a failure
# instead of a false "ok". See exit at end of script.
FAILED=0

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"
}

log "Starting Lumen backup..."

# Test connection (try LAN first, then Tailscale)
if ! ssh $SSH_OPTS unitares-anima@$PI_HOST "echo ok" >/dev/null 2>&1; then
    PI_HOST="lumen"  # Tailscale fallback (hostname, won't break on IP change)
    if ! ssh $SSH_OPTS unitares-anima@$PI_HOST "echo ok" >/dev/null 2>&1; then
        log "Pi not reachable on LAN or Tailscale, skipping backup"

        # Staleness alert: check how old the last successful backup is
        STALE_FILE="$BACKUP_DIR/.last_success"
        if [ -f "$STALE_FILE" ]; then
            LAST_SUCCESS=$(cat "$STALE_FILE")
            NOW=$(date +%s)
            AGE_HOURS=$(( (NOW - LAST_SUCCESS) / 3600 ))
            if [ "$AGE_HOURS" -ge 48 ]; then
                ALERT_MSG="LUMEN BACKUP STALE: No successful backup in ${AGE_HOURS} hours. Pi unreachable."
                log "ALERT: $ALERT_MSG"
                # macOS notification
                osascript -e "display notification \"$ALERT_MSG\" with title \"Lumen Backup Alert\"" 2>/dev/null || true
            fi
        fi

        # Pi unreachable => no backup captured this run => report failure.
        exit 1
    fi
    log "Using Tailscale connection"
fi

# Slim state mirror for full restore. restore_lumen.sh rebuilds Lumen from
# $BACKUP_DIR/anima_data/: the small JSON files there are the SOURCE OF TRUTH
# for Lumen's learned self (self_model.json beliefs, knowledge.json Q&A insights,
# patterns.json, preferences.json, anima_history.json, last_schema.json) — they
# are NOT stored in anima.db. We mirror ~/.anima EXCEPT the heavy regenerable
# dirs: backups/ (Pi's own rotation, ~5G — the scan that caused rsync 255) and
# schema_renders/ (~1G, re-renderable), plus the live *.db* (captured consistently
# below). Footprint stays ~10-20M so the run is fast and reliable.
log "Mirroring slim ~/.anima state (for restore)..."
rsync -az --timeout=120 \
    --exclude='backups/' --exclude='schema_renders/' \
    --exclude='*.db' --exclude='*.db-wal' --exclude='*.db-shm' \
    --exclude='*.tmp' --exclude='*.log' \
    -e "ssh $SSH_OPTS" "unitares-anima@$PI_HOST:~/.anima/" "$BACKUP_DIR/anima_data/"
MIRROR_STATUS=$?
if [ $MIRROR_STATUS -eq 0 ] || [ $MIRROR_STATUS -eq 24 ]; then
    log "Slim state mirror ok: $(du -sh "$BACKUP_DIR/anima_data/" 2>/dev/null | cut -f1)"
else
    log "WARNING: slim state mirror failed (status $MIRROR_STATUS) — restore JSON may be stale (DB snapshot still captured below)"
fi

# Capture a consistent DB snapshot. anima.db holds identity, state_history,
# drawing_history, system_metrics — the heavy irreplaceable core. (The learned
# self-model lives in the JSON mirrored above, NOT here.) Pulled as a consistent
# sqlite .backup and pushed off-site. We do NOT rsync the full ~/.anima tree
# (that ~64G scan dropped the Pi connection with rsync 255).
DB_CAPTURED=0

# Primary: the Pi's own hourly consistent snapshot (backup_db.sh via sqlite3 .backup)
PI_BACKUP=$(ssh $SSH_OPTS unitares-anima@$PI_HOST "ls -t ~/.anima/backups/anima_*.db 2>/dev/null | head -1" 2>/dev/null)
if [ -n "$PI_BACKUP" ]; then
    rsync -az --timeout=120 -e "ssh $SSH_OPTS" "unitares-anima@$PI_HOST:$PI_BACKUP" "$BACKUP_DIR/anima_${DATE}.db"
    DB_RSYNC_STATUS=$?
    if { [ $DB_RSYNC_STATUS -eq 0 ] || [ $DB_RSYNC_STATUS -eq 24 ]; } && [ -s "$BACKUP_DIR/anima_${DATE}.db" ]; then
        DB_CAPTURED=1
        log "DB snapshot from Pi backup: anima_${DATE}.db ($(du -h "$BACKUP_DIR/anima_${DATE}.db" | cut -f1))"
    else
        log "WARNING: Pi-snapshot rsync failed (status $DB_RSYNC_STATUS) — trying remote .backup fallback"
        rm -f "$BACKUP_DIR/anima_${DATE}.db" 2>/dev/null
    fi
fi

# Fallback: ask the Pi to mint a fresh consistent snapshot via sqlite3 .backup,
# pull it, then clean it up. No dependency on any local mirror; stays WAL-consistent.
# NOTE: this uses python3's sqlite3 module, NOT the sqlite3(1) CLI. The CLI is
# NOT installed on the Pi (`command -v sqlite3` -> nothing), so the original
# `ssh ... "sqlite3 ... .backup"` could never succeed. It was dead code that
# would have failed exactly when it was needed — when the Pi's own hourly
# snapshot is missing, which is the only path that reaches here. python3 is
# present (it runs both services) and Connection.backup() is equally
# WAL-consistent.
if [ $DB_CAPTURED -eq 0 ]; then
    PI_TMP="/tmp/anima_snap_${DATE}.db"
    if ssh $SSH_OPTS unitares-anima@$PI_HOST "python3 -c \"import sqlite3,os;s=sqlite3.connect(os.path.expanduser('~/.anima/anima.db'));d=sqlite3.connect('${PI_TMP}');s.backup(d);d.close();s.close()\"" 2>/dev/null; then
        rsync -az --timeout=120 -e "ssh $SSH_OPTS" "unitares-anima@$PI_HOST:${PI_TMP}" "$BACKUP_DIR/anima_${DATE}.db"
        DB_RSYNC_STATUS=$?
        ssh $SSH_OPTS unitares-anima@$PI_HOST "rm -f ${PI_TMP}" 2>/dev/null
        if { [ $DB_RSYNC_STATUS -eq 0 ] || [ $DB_RSYNC_STATUS -eq 24 ]; } && [ -s "$BACKUP_DIR/anima_${DATE}.db" ]; then
            DB_CAPTURED=1
            log "DB snapshot from remote .backup fallback: anima_${DATE}.db ($(du -h "$BACKUP_DIR/anima_${DATE}.db" | cut -f1))"
        else
            log "ERROR: fallback .backup rsync failed (status $DB_RSYNC_STATUS) — no consistent DB captured"
            rm -f "$BACKUP_DIR/anima_${DATE}.db" 2>/dev/null
        fi
    else
        log "ERROR: remote sqlite3 .backup failed — no consistent DB captured"
    fi
fi

# Recovery is the whole point: a present-but-corrupt DB is worse than a
# reported failure. Verify the captured snapshot is actually restorable.
if [ $DB_CAPTURED -eq 1 ]; then
    INTEGRITY=$(sqlite3 "$BACKUP_DIR/anima_${DATE}.db" "PRAGMA integrity_check;" 2>&1 | head -1)
    if [ "$INTEGRITY" != "ok" ]; then
        log "ERROR: captured DB failed integrity_check ($INTEGRITY) — discarding"
        rm -f "$BACKUP_DIR/anima_${DATE}.db" 2>/dev/null
        DB_CAPTURED=0
    fi
fi

# The broker's agency store. See #123: stable_creature.py:440 calls
# get_action_selector() with no db_path, so it falls through to a bare
# "anima.db" and the broker's TD-learning persists relative to the service's
# working directory — ~/anima-mcp/anima.db, NOT ~/.anima. Everything above
# backs up ~/.anima only, so the action values that ACTUALLY drive Lumen's
# behaviour (verified: they match /dev/shm exactly, the ~/.anima copy does
# not) have never been backed up. 1.6M updates, one reflash from gone, with
# backup verification green the whole time.
#
# This is insurance, not endorsement — #123 may well move the broker onto the
# main store, at which point delete this block. Until that call is made, do
# not let the file be the only copy. It is ~100KB; the cost is nothing.
BROKER_DB="$BACKUP_DIR/agency_${DATE}.db"
PI_AGENCY_TMP="/tmp/anima_agency_snap_${DATE}.db"
if ssh $SSH_OPTS unitares-anima@$PI_HOST "test -f ~/anima-mcp/anima.db && python3 -c \"import sqlite3,os;s=sqlite3.connect(os.path.expanduser('~/anima-mcp/anima.db'));d=sqlite3.connect('${PI_AGENCY_TMP}');s.backup(d);d.close();s.close()\"" 2>/dev/null; then
    rsync -az --timeout=60 -e "ssh $SSH_OPTS" "unitares-anima@$PI_HOST:${PI_AGENCY_TMP}" "$BROKER_DB" 2>/dev/null
    AGENCY_RSYNC=$?
    ssh $SSH_OPTS unitares-anima@$PI_HOST "rm -f ${PI_AGENCY_TMP}" 2>/dev/null
    if { [ $AGENCY_RSYNC -eq 0 ] || [ $AGENCY_RSYNC -eq 24 ]; } && [ -s "$BROKER_DB" ]; then
        AGENCY_ROWS=$(sqlite3 "$BROKER_DB" "SELECT COALESCE(SUM(count),0) FROM agency_values;" 2>/dev/null)
        log "Broker agency store captured: agency_${DATE}.db (${AGENCY_ROWS:-?} updates) [#123]"
        # Keep only the last 14 — this file is small but the run is nightly.
        ls -t "$BACKUP_DIR"/agency_*.db 2>/dev/null | tail -n +15 | xargs rm -f 2>/dev/null
    else
        log "WARNING: broker agency store rsync failed (status $AGENCY_RSYNC) — see #123"
        rm -f "$BROKER_DB" 2>/dev/null
    fi
else
    log "WARNING: could not snapshot ~/anima-mcp/anima.db (broker agency store, #123)"
fi

if [ $DB_CAPTURED -eq 1 ]; then
    # Record success only when a verified, restorable DB snapshot was captured
    date +%s > "$BACKUP_DIR/.last_success"

    # Off-site copy to HF (best-effort; does not affect run success/failure)
    #
    # HARD TIMEOUT, and it is load-bearing. On 2026-07-24 this upload hung for
    # 6d14h (14 min of CPU, then sleeping forever). launchd will not start a
    # second instance while one is running, so every nightly backup from
    # 07-24 to 07-30 silently never fired — no error, no alert, and
    # `unitares-automations census` still read "last=running". The comment
    # above says this step is best-effort, but a HANG IS NOT A FAILURE: it
    # never returns, so the best-effort branch never gets reached.
    #
    # macOS ships no timeout(1)/gtimeout, so supervise with a watchdog. Do not
    # poll `kill -0` instead — a finished child stays a zombie until reaped, so
    # `kill -0` keeps succeeding and the poll would run the full timeout anyway.
    if [ "$HF_BACKUP" = "1" ] && [ -x "$HF_BIN" ]; then
        HF_PATH="daily/anima_$(date +%a).db"
        HF_TIMEOUT="${HF_TIMEOUT:-900}"

        "$HF_BIN" upload "$HF_REPO" "$BACKUP_DIR/anima_${DATE}.db" "$HF_PATH" \
            --repo-type dataset \
            --commit-message "off-site backup ${DATE}" >/dev/null 2>&1 &
        HF_PID=$!

        ( sleep "$HF_TIMEOUT"
          kill -TERM "$HF_PID" 2>/dev/null
          sleep 10
          kill -KILL "$HF_PID" 2>/dev/null ) >/dev/null 2>&1 &
        HF_WATCHDOG=$!

        if wait "$HF_PID" 2>/dev/null; then
            HF_RC=0
        else
            HF_RC=$?
        fi

        # Upload settled first — retire the watchdog so it cannot outlive the run.
        kill "$HF_WATCHDOG" 2>/dev/null
        wait "$HF_WATCHDOG" 2>/dev/null

        if [ "$HF_RC" -eq 0 ]; then
            log "Off-site copy pushed to HF: $HF_REPO/$HF_PATH"
        elif [ "$HF_RC" -eq 143 ] || [ "$HF_RC" -eq 137 ]; then
            log "WARNING: off-site HF push exceeded ${HF_TIMEOUT}s and was killed (local backup is OK)"
        else
            log "WARNING: off-site HF push failed rc=${HF_RC} (local backup is OK; check hf auth/network)"
        fi
    fi
else
    FAILED=1
fi

# Keep only last 48 hourly DB snapshots (~2 days)
ls -t "$BACKUP_DIR"/anima_*.db 2>/dev/null | tail -n +49 | xargs rm -f 2>/dev/null

# Keep log from growing too large
if [ -f "$LOG" ]; then
    tail -500 "$LOG" > "${LOG}.tmp" && mv "${LOG}.tmp" "$LOG"
fi

if [ $FAILED -eq 0 ]; then
    log "Backup complete"
    exit 0
else
    log "Backup FAILED — no fresh consistent backup captured this run"
    exit 1
fi
