#!/bin/bash
# Recover Lumen before either persistent-state writer starts.
#
# This unit is a continuity gate, not a best-effort convenience: an unavailable
# backup must not silently become a fresh identity.  Operators can explicitly
# opt into that outcome with ANIMA_ALLOW_FRESH_START=true in anima.env.

set -euo pipefail

# Overridable so the recovery logic is executable in a test harness; the
# systemd unit sets nothing, so production keeps the literal path.
ANIMA_DIR="${ANIMA_DIR:-/home/unitares-anima/.anima}"
DB_PATH="$ANIMA_DIR/anima.db"
SSH_KEY="${SSH_KEY:-/home/unitares-anima/.ssh/id_ed25519}"
SSH_OPTS="-i $SSH_KEY -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=4"
BACKUP_USER="${BACKUP_USER:-cirwel}"
BACKUP_DIR="${BACKUP_DIR:-backups/lumen}"
MARKER="$ANIMA_DIR/.restored_marker"
LOG_TAG="anima-restore"
ALLOW_FRESH="${ANIMA_ALLOW_FRESH_START:-false}"

if [ -n "${BACKUP_MAC_HOSTS:-}" ]; then
    # shellcheck disable=SC2206
    MAC_HOSTS=( $BACKUP_MAC_HOSTS )
else
    MAC_HOSTS=("lumen-mac")
fi

log() {
    logger -t "$LOG_TAG" "$1" 2>/dev/null || true
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

sqlite_ok() {
    [ -s "$1" ] || return 1
    python3 - "$1" <<'PY'
import sqlite3
import sys

try:
    with sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True) as connection:
        rows = connection.execute("PRAGMA integrity_check").fetchall()
except sqlite3.Error:
    raise SystemExit(1)
raise SystemExit(0 if rows == [("ok",)] else 1)
PY
}

json_ok() {
    python3 - "$1" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        json.load(handle)
except (OSError, UnicodeError, json.JSONDecodeError):
    raise SystemExit(1)
PY
}

learned_state_ok() {
    for required in anima_config.json preferences.json self_model.json patterns.json metacognition_baselines.json; do
        [ -f "$ANIMA_DIR/$required" ] || return 1
    done
    while IFS= read -r -d '' state_file; do
        json_ok "$state_file" || return 1
    done < <(find "$ANIMA_DIR" -maxdepth 1 -type f -name '*.json' -print0)
    if [ -e "$ANIMA_DIR/oauth.db" ] && ! sqlite_ok "$ANIMA_DIR/oauth.db"; then
        return 1
    fi
    return 0
}

continuity_failure() {
    log "ERROR: $1"
    case "$(printf '%s' "$ALLOW_FRESH" | tr '[:upper:]' '[:lower:]')" in
        1|true|yes|on)
            log "ANIMA_ALLOW_FRESH_START is explicit; allowing a new identity"
            exit 0
            ;;
        *)
            log "Refusing silent fresh start; services remain gated"
            exit 1
            ;;
    esac
}

mkdir -p "$ANIMA_DIR"

# A file-size check is not integrity. WAL damage can leave a large DB that
# SQLite cannot open, and an intact DB alone is not the whole identity. Both
# database and learned-state snapshots must clear the gate.
if sqlite_ok "$DB_PATH" && learned_state_ok; then
    log "Existing database and learned state passed continuity checks; restore not needed"
    exit 0
fi

log "Database or learned state missing/invalid — locating a complete recovery point"

# Recover from this host's OWN verified snapshots before reaching for another
# host's. A principal that cannot restore itself without holding a credential
# into someone else's machine has a shared administrative root, which is the
# thing the federation model exists to avoid. It is also simply better recovery:
# the local hourly snapshot is fresher than any pushed mirror and needs no
# network at boot.
#
# Scope is deliberately the DB-only case. The local learned-state generations
# under backups/state/ do NOT currently carry anima_config.json, so they cannot
# satisfy learned_state_ok on their own; when learned state is the broken half
# we fall through to the remote mirror that does carry it. Widening this to
# learned state requires fixing the state-backup contents first, not loosening
# the gate here.
try_local_db_recovery() {
    learned_state_ok || return 1
    [ -d "$ANIMA_DIR/backups" ] || return 1

    local candidate stage
    while IFS= read -r candidate; do
        [ -n "$candidate" ] || continue
        sqlite_ok "$candidate" || continue

        stage=$(mktemp "$ANIMA_DIR/.auto-restore-local-db.XXXXXX") || return 1
        if ! cp "$candidate" "$stage"; then
            rm -f "$stage"
            continue
        fi
        # Same durability discipline as the remote path: the staged file must be
        # on disk before a rename can make it the live identity.
        python3 - "$stage" <<'PY_FSYNC'
import os
import sys

with open(sys.argv[1], "rb") as handle:
    os.fsync(handle.fileno())
PY_FSYNC

        rm -f "$ANIMA_DIR/.pre-restore-anima.db"
        if [ -e "$DB_PATH" ]; then
            mv "$DB_PATH" "$ANIMA_DIR/.pre-restore-anima.db"
        fi
        # The WAL/SHM belong to the DB being replaced; carrying them across
        # would reapply the damage we are recovering from.
        rm -f "$DB_PATH-wal" "$DB_PATH-shm"
        mv "$stage" "$DB_PATH"
        chmod 600 "$DB_PATH"

        if ! sqlite_ok "$DB_PATH"; then
            # Put the original back rather than leaving a half-swapped identity;
            # the next candidate gets a clean attempt.
            rm -f "$DB_PATH"
            if [ -e "$ANIMA_DIR/.pre-restore-anima.db" ]; then
                mv "$ANIMA_DIR/.pre-restore-anima.db" "$DB_PATH"
            fi
            continue
        fi

        python3 - "$ANIMA_DIR" <<'PY_SYNCDIR'
import os
import sys
from pathlib import Path

root = Path(sys.argv[1])
with (root / "anima.db").open("rb") as handle:
    os.fsync(handle.fileno())
descriptor = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(descriptor)
finally:
    os.close(descriptor)
PY_SYNCDIR

        log "Recovered database from local snapshot $(basename "$candidate")"
        return 0
    done <<< "$(ls -t "$ANIMA_DIR"/backups/anima_*.db 2>/dev/null || true)"

    return 1
}

if try_local_db_recovery; then
    log "Local recovery complete; no cross-host access required"
    exit 0
fi
log "No usable local snapshot — falling back to the backup Mac"

if [ ! -f "$SSH_KEY" ]; then
    continuity_failure "no SSH key at $SSH_KEY"
fi

MAC_HOST=""
for host in "${MAC_HOSTS[@]}"; do
    if ssh $SSH_OPTS "$BACKUP_USER@$host" "echo ok" >/dev/null 2>&1; then
        MAC_HOST="$host"
        break
    fi
done
[ -n "$MAC_HOST" ] || continuity_failure "backup Mac is unreachable"
REMOTE="$BACKUP_USER@$MAC_HOST"
log "Backup Mac reachable at $MAC_HOST"

# The scheduled backup publishes anima_data only after its staging mirror is
# complete. If power failed during the two-directory swap, use the preserved
# previous generation rather than an absent primary.
REMOTE_STATE=$(ssh $SSH_OPTS "$REMOTE" \
    "if [ -d ~/$BACKUP_DIR/anima_data ]; then echo ~/$BACKUP_DIR/anima_data; elif [ -d ~/$BACKUP_DIR/anima_data.previous ]; then echo ~/$BACKUP_DIR/anima_data.previous; fi" \
    2>/dev/null || true)
[ -n "$REMOTE_STATE" ] || continuity_failure "no complete learned-state mirror on backup Mac"

STATE_STAGE=$(mktemp -d "$ANIMA_DIR/.auto-restore-state.XXXXXX") || \
    continuity_failure "could not allocate learned-state staging directory"
mkdir -p "$STATE_STAGE/drawings" "$STATE_STAGE/learning_inbox"
DB_STAGE=$(mktemp "$ANIMA_DIR/.auto-restore-db.XXXXXX") || {
    rm -rf "$STATE_STAGE"
    continuity_failure "could not allocate database staging file"
}

cleanup() {
    [ -n "${STATE_STAGE:-}" ] && rm -rf "$STATE_STAGE"
    [ -n "${DB_STAGE:-}" ] && rm -f "$DB_STAGE"
}
trap cleanup EXIT

log "Pulling learned-state generation from $REMOTE_STATE..."
if ! rsync -az --timeout=120 -e "ssh $SSH_OPTS" \
    --include='*/' \
    --include='*.json' \
    --include='oauth.db' \
    --include='drawings/***' \
    --include='learning_inbox/***' \
    --exclude='*' \
    "$REMOTE:$REMOTE_STATE/" "$STATE_STAGE/"; then
    continuity_failure "learned-state transfer failed"
fi

if ! find "$STATE_STAGE" -maxdepth 1 -type f -name '*.json' -print -quit | grep -q .; then
    continuity_failure "learned-state mirror contains no root JSON snapshots"
fi
for required in anima_config.json preferences.json self_model.json patterns.json metacognition_baselines.json; do
    if [ ! -f "$STATE_STAGE/$required" ]; then
        continuity_failure "learned-state mirror is missing $required"
    fi
done
while IFS= read -r -d '' state_file; do
    if ! json_ok "$state_file"; then
        continuity_failure "invalid learned-state JSON: $(basename "$state_file")"
    fi
done < <(find "$STATE_STAGE" -maxdepth 1 -type f -name '*.json' -print0)
if [ -e "$STATE_STAGE/oauth.db" ] && ! sqlite_ok "$STATE_STAGE/oauth.db"; then
    continuity_failure "OAuth persistence database failed integrity_check"
fi

log "Trying verified database snapshots..."
SNAPSHOTS=$(ssh $SSH_OPTS "$REMOTE" \
    "ls -t ~/$BACKUP_DIR/anima_*.db 2>/dev/null" 2>/dev/null || true)
DB_SOURCE=""
while IFS= read -r candidate; do
    [ -n "$candidate" ] || continue
    if rsync -az --timeout=180 -e "ssh $SSH_OPTS" \
        "$REMOTE:$candidate" "$DB_STAGE" >/dev/null 2>&1 && sqlite_ok "$DB_STAGE"; then
        DB_SOURCE="$candidate"
        break
    fi
    : > "$DB_STAGE"
done <<< "$SNAPSHOTS"
[ -n "$DB_SOURCE" ] || continuity_failure "no restorable anima_*.db snapshot found"

# rsync completion alone does not promise sudden-power-loss durability. Flush
# every staged recovery file before any rename can make the generation live.
python3 - "$STATE_STAGE" "$DB_STAGE" <<'PY'
import os
import sys
from pathlib import Path

paths = [Path(sys.argv[2])]
paths.extend(path for path in Path(sys.argv[1]).rglob("*") if path.is_file())
for path in paths:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())
PY

# Publish learned state first. The database is the final commit point: if power
# fails before it lands, the next boot retries instead of accepting a partial
# recovery as an existing identity.
rm -f "$ANIMA_DIR/.pre-restore-anima.db"
if [ -e "$DB_PATH" ]; then
    mv "$DB_PATH" "$ANIMA_DIR/.pre-restore-anima.db"
fi
rm -f "$DB_PATH-wal" "$DB_PATH-shm"
find "$ANIMA_DIR" -maxdepth 1 -type f -name '*.json' -delete
for source in "$STATE_STAGE"/*.json; do
    [ -e "$source" ] || break
    name=$(basename "$source")
    mv "$source" "$ANIMA_DIR/$name"
done
for directory in drawings learning_inbox; do
    rm -rf "$ANIMA_DIR/$directory"
    mv "$STATE_STAGE/$directory" "$ANIMA_DIR/$directory"
done
rm -f "$ANIMA_DIR/oauth.db" "$ANIMA_DIR/oauth.db-wal" "$ANIMA_DIR/oauth.db-shm"
if [ -e "$STATE_STAGE/oauth.db" ]; then
    mv "$STATE_STAGE/oauth.db" "$ANIMA_DIR/oauth.db"
    chmod 600 "$ANIMA_DIR/oauth.db"
fi

mv "$DB_STAGE" "$DB_PATH"
DB_STAGE=""
rm -f "$DB_PATH-wal" "$DB_PATH-shm"
sqlite_ok "$DB_PATH" || continuity_failure "installed database failed integrity_check"
python3 - "$ANIMA_DIR" <<'PY'
import os
import sys
from pathlib import Path

root = Path(sys.argv[1])
with (root / "anima.db").open("rb") as handle:
    os.fsync(handle.fileno())
descriptor = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(descriptor)
finally:
    os.close(descriptor)
PY
rm -f "$ANIMA_DIR/.pre-restore-anima.db"

python3 - "$MARKER" "$MAC_HOST" "$DB_SOURCE" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
tmp = path.with_name(path.name + ".tmp")
with tmp.open("w", encoding="utf-8") as handle:
    json.dump({
        "restored_at": datetime.now(timezone.utc).isoformat(),
        "source": sys.argv[2],
        "database_source": sys.argv[3],
        "db_restored": True,
        "reason": "boot_auto_restore",
    }, handle, indent=2)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
os.replace(tmp, path)
descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(descriptor)
finally:
    os.close(descriptor)
PY

chown -R unitares-anima:unitares-anima "$ANIMA_DIR"
log "Restore complete from $(basename "$DB_SOURCE"); continuity gate cleared"
