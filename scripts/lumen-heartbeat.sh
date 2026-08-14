#!/bin/bash
# Lumen outbound heartbeat — the dead-man's switch.
#
# WHY THIS EXISTS AND WHY IT LIVES ON THE PI
#
# Every other liveness surface Lumen has runs on the Mac: the Discord bridge
# poller, the tailscale watchdog, the governance health watchdog. All of them
# share a failure domain with the Mac, so none can report "the Mac is asleep" —
# and that silence is indistinguishable from Lumen being fine. In July 2026 the
# Pi was unplugged for ~3.5 days and the outage was found by hand on the
# operator's return.
#
# A dead-man's switch inverts the burden: instead of something watching for a
# failure, the healthy state must keep asserting itself, and ABSENCE is the
# alarm. That only works if the assertion leaves both machines, so this pings a
# third party that neither the Mac nor the Pi owns.
#
# WHAT IT ASSERTS
#
# "Lumen is alive", NOT "the Pi has power". A cron line that curls a URL
# unconditionally proves only that the box boots and has network — it would have
# reported healthy through every software failure Lumen has ever had. That is
# the exact fail-toward-healthy shape CLAUDE.md invariant 2 forbids.
#
# So the heartbeat gates on Lumen's own WORK OUTPUT. Deliberately NOT
# `systemctl is-active` — a live PID is not work output, the same distinction
# the BEAM lease plane learned the hard way.
#
# THREE processes make up the creature, and the same argument says one process's
# work output is not the creature's:
#
#   anima-broker      sensors + learning -> /dev/shm/anima_state.json
#   anima-broker-ex   Elixir, owns the governance check-ins -> ...shadow.json
#   anima             MCP server: agency learner (authoritative), metacognition,
#                     growth, drawing, display, the whole tool surface
#
# The first version of this script checked only the first envelope. If the MCP
# server died, the broker kept writing, the envelope stayed fresh, and the switch
# would have pinged green forever while most of Lumen was gone. Each component is
# now probed by its own work output and the WORST result decides.
#
# It does NOT gate on governance reachability. Governance lives on the Mac, so
# folding it in here would page the operator about a Mac outage under the
# heading "Lumen is dead" — conflating two failures with different responses.
# That layer is the bridge's job. This one answers exactly one question.
#
# FAILURE DIRECTION
#
#   envelope fresh        -> ping success
#   envelope stale/absent -> ping the /fail endpoint (alerts immediately,
#                            instead of waiting out the provider grace period)
#   this script dead      -> no ping at all -> alerts after the grace period
#
# All three roads lead to the operator. There is no path where a broken
# heartbeat reads as a healthy Lumen.
#
# SETUP (see docs/operations/HEARTBEAT.md)
#   ANIMA_HEARTBEAT_URL=https://hc-ping.com/<uuid>   in ~/.anima/anima.env
# Unset -> this exits 0 silently, so an un-provisioned Pi is not a crash loop.
# Note that anima.env is deliberately excluded from backups, so a reflash drops
# the URL, the pings stop, and the provider alerts. Loud, not silent — correct.

set -uo pipefail

ENV_FILE="${ANIMA_ENV_FILE:-$HOME/.anima/anima.env}"
LOGFILE="${ANIMA_HEARTBEAT_LOG:-$HOME/.anima/heartbeat.log}"
SHM_PATH="${ANIMA_SHM_PATH:-/dev/shm/anima_state.json}"
SHADOW_PATH="${ANIMA_HEARTBEAT_SHADOW_PATH:-/dev/shm/anima_state.shadow.json}"
# Functional probe of the MCP server. It answers 200 or it does not; there is no
# cached artifact to go stale in a way that reads healthy.
SERVER_URL="${ANIMA_HEARTBEAT_SERVER_URL:-http://127.0.0.1:8766/health}"
# Comma list of components to skip, for documented rollbacks (e.g. reverting the
# Elixir broker leaves a stale shadow envelope that would otherwise page forever).
# Values: broker, broker_ex, server.
SKIP="${ANIMA_HEARTBEAT_SKIP:-}"

# Broker ticks ~every 2s. 120s tolerates a service restart and a slow tick
# without tolerating a dead broker.
MAX_AGE="${ANIMA_HEARTBEAT_MAX_AGE:-120}"

log() {
    mkdir -p "$(dirname "$LOGFILE")" 2>/dev/null
    echo "$(date '+%Y-%m-%d %H:%M:%S'): $1" >> "$LOGFILE"
}

# shellcheck disable=SC1090
[ -f "$ENV_FILE" ] && set -a && . "$ENV_FILE" && set +a

URL="${ANIMA_HEARTBEAT_URL:-}"
if [ -z "$URL" ]; then
    # Unprovisioned. Note it at most daily: the timer fires every 5 minutes, so
    # logging every run would put 288 lines/day in the file an operator reads to
    # find real trouble. Do NOT exit non-zero — a box that was never set up is
    # not a failing box, and a red unit would train the operator to ignore it.
    MARK="${ANIMA_HEARTBEAT_INERT_MARK:-$HOME/.anima/.heartbeat-inert}"
    mkdir -p "$(dirname "$MARK")" 2>/dev/null
    NOW=$(date +%s)
    LAST=0
    [ -f "$MARK" ] && LAST=$(cat "$MARK" 2>/dev/null || echo 0)
    if [ $((NOW - LAST)) -ge 86400 ]; then
        log "ANIMA_HEARTBEAT_URL unset — heartbeat inert (see docs/operations/HEARTBEAT.md)"
        echo "$NOW" > "$MARK"
    fi
    exit 0
fi

FAIL_URL="${ANIMA_HEARTBEAT_FAIL_URL:-${URL%/}/fail}"

# --- Is Lumen alive? -------------------------------------------------------
skipped() { case ",$SKIP," in *",$1,"*) return 0;; *) return 1;; esac; }

fail_out() {
    log "$1 — signalling failure"
    curl -fsS -m 10 --retry 2 -o /dev/null "$FAIL_URL" \
        || log "WARNING: could not reach heartbeat provider to report failure"
    exit 0
}

# Age of an envelope in seconds, or empty if unreadable. Missing file, corrupt
# JSON and unparseable timestamp all resolve to "not fresh" rather than to a
# default that would read as healthy.
envelope_age() {
    python3 - "$1" <<'PY' 2>/dev/null
import json, sys, os
from datetime import datetime
try:
    path = sys.argv[1]
    # mtime is the honest floor: the writer rewrites the file every tick, so a
    # stale mtime means it stopped writing regardless of what the payload says.
    age_mtime = (datetime.now().timestamp() - os.path.getmtime(path))
    with open(path) as fh:
        stamp = json.load(fh).get("updated_at")
    age_field = None
    if stamp:
        try:
            age_field = (datetime.now() - datetime.fromisoformat(stamp)).total_seconds()
        except (ValueError, TypeError):
            age_field = None
    # Take the WORSE of the two. A payload timestamp that looks fresh while the
    # file has not been touched means something is rewriting a cached value.
    print(int(max(age_mtime, age_field if age_field is not None else age_mtime)))
except Exception:
    sys.exit(1)
PY
}

check_envelope() {
    local label="$1" path="$2" age
    skipped "$label" && return 0
    age=$(envelope_age "$path")
    [ -z "${age:-}" ] && fail_out "$label envelope unreadable at $path"
    [ "$age" -gt "$MAX_AGE" ] && fail_out "$label envelope stale (${age}s > ${MAX_AGE}s)"
    return 0
}

check_envelope broker    "$SHM_PATH"
check_envelope broker_ex "$SHADOW_PATH"

if ! skipped server; then
    # A slow answer is still an answer; only a refusal/timeout counts as dead.
    curl -fsS -m 10 --retry 1 -o /dev/null "$SERVER_URL" \
        || fail_out "MCP server not answering at $SERVER_URL"
fi

if curl -fsS -m 10 --retry 2 -o /dev/null "$URL"; then
    # Quiet on the happy path — this runs every 5 minutes forever.
    exit 0
fi

# Reaching the provider failed. Do NOT treat that as Lumen being unwell; it is
# almost always the Pi's own uplink, which is itself an outage the provider will
# notice as absence. Log it so a chronically unreachable provider is visible.
log "all components healthy but heartbeat ping failed — provider unreachable"
exit 0
