#!/bin/bash
# Build and restart the Elixir sensor broker only when its deployed inputs change.

set -euo pipefail

RESTART=true
if [ "${1:-}" = "--no-restart" ]; then
    RESTART=false
elif [ "$#" -gt 0 ]; then
    echo "Usage: $0 [--no-restart]" >&2
    exit 2
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BROKER_ROOT="$REPO_ROOT/anima_broker"
UNIT_SOURCE="$BROKER_ROOT/systemd/anima-broker-ex.service"
UNIT_DEST="/etc/systemd/system/anima-broker-ex.service"
RELEASE_ROOT="$BROKER_ROOT/_build/prod/rel/anima_broker"
RELEASE_BIN="$RELEASE_ROOT/bin/anima_broker"
SOURCE_STAMP="$RELEASE_ROOT/.source-sha256"
RESTART_STAMP="$RELEASE_ROOT/.restart-required"
SHADOW_PATH="/dev/shm/anima_state.shadow.json"

configured=false
if systemctl is-active --quiet anima-broker-ex 2>/dev/null \
    || systemctl is-enabled --quiet anima-broker-ex 2>/dev/null \
    || grep -Eq '^[[:space:]]*ANIMA_ENV_SENSORS_FROM_SHM=[^[:space:]#]+' "$HOME/.anima/anima.env" 2>/dev/null; then
    configured=true
fi

unit_changed=false
if [ -f "$UNIT_SOURCE" ] && ! cmp -s "$UNIT_SOURCE" "$UNIT_DEST"; then
    sudo install -m 0644 "$UNIT_SOURCE" "$UNIT_DEST"
    sudo systemctl daemon-reload
    unit_changed=true
fi

if [ "$configured" != true ]; then
    echo "Elixir sensor broker is not configured on this host; release build skipped"
    exit 0
fi

sudo systemctl enable anima-broker-ex >/dev/null

source_hash="$({
    for directory in lib config priv rel; do
        if [ -d "$BROKER_ROOT/$directory" ]; then
            find "$BROKER_ROOT/$directory" -type f -print0
        fi
    done
    printf '%s\0' "$BROKER_ROOT/mix.exs" "$BROKER_ROOT/mix.lock"
} | sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}')"

release_changed=false
installed_hash=""
if [ -f "$SOURCE_STAMP" ]; then
    installed_hash="$(tr -d '[:space:]' < "$SOURCE_STAMP")"
fi

if [ ! -x "$RELEASE_BIN" ] || [ "$installed_hash" != "$source_hash" ]; then
    echo "Building changed Elixir sensor broker release..."
    (
        cd "$BROKER_ROOT"
        MIX_ENV=prod mix deps.get --only prod
        MIX_ENV=prod mix compile --warnings-as-errors
        MIX_ENV=prod mix release --overwrite
    )
    stamp_tmp="$(mktemp "$RELEASE_ROOT/.source-sha256.XXXXXX")"
    printf '%s\n' "$source_hash" > "$stamp_tmp"
    mv "$stamp_tmp" "$SOURCE_STAMP"
    release_changed=true
else
    echo "Elixir sensor broker release already matches deployed source"
fi

if [ "$release_changed" = true ] || [ "$unit_changed" = true ]; then
    touch "$RESTART_STAMP"
fi

if [ "$RESTART" != true ]; then
    if [ -f "$RESTART_STAMP" ]; then
        echo "Elixir sensor broker restart deferred (--no-restart)"
    fi
    exit 0
fi

verification_started="$(date +%s)"
restart_required=false
if [ -f "$RESTART_STAMP" ]; then
    restart_required=true
    sudo systemctl restart anima-broker-ex
elif ! systemctl is-active --quiet anima-broker-ex; then
    restart_required=true
    sudo systemctl start anima-broker-ex
fi

systemctl is-active --quiet anima-broker-ex
python3 - "$SHADOW_PATH" "$verification_started" "$restart_required" <<'PY'
import json
import os
import sys
import time

path, started_raw, restart_required = sys.argv[1:]
must_be_new = restart_required == "true"
started = float(started_raw)
deadline = time.time() + 45

while time.time() < deadline:
    try:
        envelope = json.load(open(path, encoding="utf-8"))
        data = envelope.get("data", {})
        mtime = os.path.getmtime(path)
        fresh = mtime >= started if must_be_new else time.time() - mtime < 15
        if fresh and isinstance(data.get("readings"), dict):
            raise SystemExit(0)
    except (OSError, ValueError, TypeError):
        pass
    time.sleep(1)

raise SystemExit("Elixir broker is active but did not publish fresh shadow state")
PY

rm -f "$RESTART_STAMP"
echo "Elixir sensor broker active; fresh shadow state verified"
