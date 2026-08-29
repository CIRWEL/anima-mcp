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
# THREE processes make up the creature, plus one server-owned long-clock output;
# the same argument says one component's work output is not the creature's:
#
#   anima-broker      sensors + learning -> /dev/shm/anima_state.json
#   anima-broker-ex   Elixir, owns the governance check-ins -> ...shadow.json
#   anima             MCP server: agency learner (authoritative), metacognition,
#                     growth, drawing, display, the whole tool surface
#   day-summary writer long-term evidence -> ~/.anima/day_summaries.json
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
#   all unskipped probes healthy -> ping success
#   any probe stale/absent/bad   -> ping the /fail endpoint (alerts immediately,
#                                   instead of waiting out the provider grace)
#   this script dead             -> no ping -> alerts after the grace period
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
# Comma list of components to skip, for documented rollbacks (e.g. reverting the
# Elixir broker leaves a stale shadow envelope that would otherwise page forever).
# Values: broker, broker_ex, server, day_summary.

log() {
    mkdir -p "$(dirname "$LOGFILE")" 2>/dev/null
    echo "$(date '+%Y-%m-%d %H:%M:%S'): $1" >> "$LOGFILE"
}

# shellcheck disable=SC1090
[ -f "$ENV_FILE" ] && set -a && . "$ENV_FILE" && set +a

# Resolve every operator override after anima.env is sourced. The service unit
# intentionally needs only ANIMA_ENV_FILE; paths and thresholds belong in the
# same runtime configuration as the secret URL.
LOGFILE="${ANIMA_HEARTBEAT_LOG:-$HOME/.anima/heartbeat.log}"
SHM_PATH="${ANIMA_SHM_PATH:-/dev/shm/anima_state.json}"
SHADOW_PATH="${ANIMA_HEARTBEAT_SHADOW_PATH:-/dev/shm/anima_state.shadow.json}"
# Functional probe of the MCP server. It answers 200 or it does not; there is no
# cached artifact to go stale in a way that reads healthy.
SERVER_URL="${ANIMA_HEARTBEAT_SERVER_URL:-http://127.0.0.1:8766/health}"
# Broker ticks ~every 2s. 120s tolerates a service restart and a slow tick
# without tolerating a dead broker.
MAX_AGE="${ANIMA_HEARTBEAT_MAX_AGE:-120}"

URL="${ANIMA_HEARTBEAT_URL:-}"
MARK="${ANIMA_HEARTBEAT_INERT_MARK:-$HOME/.anima/.heartbeat-inert}"
NOTICE_MARK="${ANIMA_HEARTBEAT_INERT_NOTICE_MARK:-${MARK}.notice}"
if [ -z "$URL" ]; then
    # Unprovisioned. Note it at most daily: the timer fires every 5 minutes, so
    # logging every run would put 288 lines/day in the file an operator reads to
    # find real trouble. Do NOT exit non-zero — a box that was never set up is
    # not a failing box, and a red unit would train the operator to ignore it.
    mkdir -p "$(dirname "$MARK")" 2>/dev/null
    NOW=$(date +%s)
    # MARK is the immutable first-seen time used by /health/detailed.  The old
    # implementation rewrote it whenever it logged, so it could never become
    # "older than a day".  Keep log throttling in a separate disposable file.
    if [ ! -f "$MARK" ]; then
        echo "$NOW" > "$MARK" 2>/dev/null \
            || log "WARNING: could not persist heartbeat inert first-seen marker"
    fi
    LAST=0
    [ -f "$NOTICE_MARK" ] && LAST=$(cat "$NOTICE_MARK" 2>/dev/null || echo 0)
    if [ $((NOW - LAST)) -ge 86400 ]; then
        log "ANIMA_HEARTBEAT_URL unset — heartbeat inert (see docs/operations/HEARTBEAT.md)"
        echo "$NOW" > "$NOTICE_MARK" 2>/dev/null || true
    fi
    exit 0
fi

# A configured URL is recovery.  Do this before the probes so detailed health
# stops reporting a stale provisioning fault even if this run discovers a real
# Lumen failure and sends /fail.
rm -f "$MARK" "$NOTICE_MARK"

FAIL_URL="${ANIMA_HEARTBEAT_FAIL_URL:-${URL%/}/fail}"
SKIP="${ANIMA_HEARTBEAT_SKIP:-}"

# Long-clock work output. The writer targets a 24h cadence, so 36h tolerates
# scheduler and restart jitter without letting yesterday's evidence pass for
# current indefinitely. These are resolved after anima.env is sourced so an
# operator can redirect them without editing the service unit.
DAY_SUMMARY_PATH="${DAY_SUMMARY_PATH:-$HOME/.anima/day_summaries.json}"
ANIMA_HISTORY_PATH="${ANIMA_HISTORY_PATH:-$HOME/.anima/anima_history.json}"
DAY_SUMMARY_MAX_AGE="${DAY_SUMMARY_MAX_AGE:-129600}"
DAY_SUMMARY_BOOTSTRAP_GRACE_SECONDS="${DAY_SUMMARY_BOOTSTRAP_GRACE_SECONDS:-1800}"

# --- Is Lumen alive? -------------------------------------------------------
skipped() { case ",$SKIP," in *",$1,"*) return 0;; *) return 1;; esac; }

fail_out() {
    log "$1 — signalling failure"
    curl -fsS -m 10 --retry 2 -o /dev/null "$FAIL_URL" \
        || log "WARNING: could not reach heartbeat provider to report failure"
    exit 0
}

if ! python3 - "$MAX_AGE" <<'PY' 2>/dev/null
import sys

try:
    value = int(sys.argv[1])
    if value <= 0 or value > 2147483647 or str(value) != sys.argv[1].strip():
        raise ValueError
except (TypeError, ValueError, OverflowError):
    raise SystemExit(1)
PY
then
    fail_out "ANIMA_HEARTBEAT_MAX_AGE must be a positive 32-bit integer (got '$MAX_AGE')"
fi

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

# A day-summary file carries two independent freshness claims:
#
#   written_at (legacy files: mtime)  — the writer completed a commit
#   newest summary date              — the committed evidence is current
#
# The WORSE age wins. This catches both a stopped writer and a live writer that
# keeps republishing frozen evidence. An empty output is allowed only behind a
# durable, bounded writer-start marker and while the live source has fewer than
# the 100 recent observations consolidate() requires. A missing file is never a
# bootstrap signal: it cannot prove the writer ran at all.
day_summary_health() {
    python3 - "$DAY_SUMMARY_PATH" "$ANIMA_HISTORY_PATH" \
        "$DAY_SUMMARY_MAX_AGE" "$DAY_SUMMARY_BOOTSTRAP_GRACE_SECONDS" <<'PY' 2>/dev/null
import json
import math
import os
import sys
import time
from datetime import datetime


summary_path, history_path, raw_max_age, raw_bootstrap_grace = sys.argv[1:]
now = time.time()
future_tolerance = 5 * 60


def fail(message):
    print(message)
    raise SystemExit(1)


def parse_timestamp(value, label):
    if not isinstance(value, str) or not value.strip():
        fail(f"day_summary {label} timestamp missing or malformed")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp()
    except (ValueError, TypeError, OverflowError, OSError):
        fail(f"day_summary {label} timestamp malformed")


try:
    max_age = float(raw_max_age)
    if not math.isfinite(max_age) or max_age <= 0:
        raise ValueError
except (TypeError, ValueError, OverflowError):
    fail(f"day_summary max age invalid: {raw_max_age!r}")

try:
    bootstrap_grace = float(raw_bootstrap_grace)
    if not math.isfinite(bootstrap_grace) or bootstrap_grace <= 0:
        raise ValueError
except (TypeError, ValueError, OverflowError):
    fail(f"day_summary bootstrap grace invalid: {raw_bootstrap_grace!r}")


try:
    os.stat(summary_path)
    summary_exists = True
except FileNotFoundError:
    summary_exists = False
except OSError:
    fail(f"day_summary path unreadable at {summary_path}")


if not summary_exists:
    fail(f"day_summary writer has no bootstrap marker at {summary_path}")


try:
    with open(summary_path, encoding="utf-8") as handle:
        payload = json.load(handle)
except Exception:
    fail(f"day_summary unreadable at {summary_path}")

if not isinstance(payload, dict):
    fail("day_summary payload malformed")
rows = payload.get("summaries")
if not isinstance(rows, list):
    fail("day_summary summaries missing or malformed")

if not rows:
    writer_started = parse_timestamp(
        payload.get("writer_started_at"), "writer_started_at"
    )
    bootstrap_age = now - writer_started
    if bootstrap_age < -future_tolerance:
        fail(f"day_summary writer_started_at is future-dated ({int(bootstrap_age)}s)")

    # anima_history.json is saved only every 100 records, so it may honestly be
    # absent during first boot. The durable writer marker bounds that ambiguity.
    try:
        with open(history_path, encoding="utf-8") as handle:
            history = json.load(handle)
    except FileNotFoundError:
        observations = []
    except Exception:
        fail(f"day_summary bootstrap history unreadable at {history_path}")
    else:
        observations = history.get("observations") if isinstance(history, dict) else None
        if not isinstance(observations, list):
            fail("day_summary bootstrap history observations malformed")

    recent = 0
    for index, observation in enumerate(observations):
        if not isinstance(observation, dict):
            fail(f"day_summary bootstrap observation {index} malformed")
        stamp = observation.get("t", observation.get("timestamp"))
        observed_at = parse_timestamp(stamp, f"bootstrap observation {index}")
        age = now - observed_at
        if age < -future_tolerance:
            fail(f"day_summary bootstrap observation {index} is future-dated")
        if age <= 86400:
            recent += 1

    if recent >= 100:
        fail(f"day_summary empty with eligible source ({recent} observations in 24h)")
    if bootstrap_age > bootstrap_grace:
        fail(
            "day_summary bootstrap grace expired "
            f"({int(bootstrap_age)}s > {int(bootstrap_grace)}s)"
        )
    raise SystemExit(0)

evidence_times = []
for index, row in enumerate(rows):
    if not isinstance(row, dict):
        fail(f"day_summary row {index} malformed")
    evidence_times.append(parse_timestamp(row.get("date"), f"row {index} date"))
newest_evidence = max(evidence_times)

if "written_at" in payload:
    writer_time = parse_timestamp(payload.get("written_at"), "written_at")
else:
    try:
        writer_time = os.path.getmtime(summary_path)
    except OSError:
        fail(f"day_summary mtime unreadable at {summary_path}")

writer_age = now - writer_time
evidence_age = now - newest_evidence
if writer_age < -future_tolerance:
    fail(f"day_summary writer timestamp is future-dated ({int(writer_age)}s)")
if evidence_age < -future_tolerance:
    fail(f"day_summary evidence timestamp is future-dated ({int(evidence_age)}s)")

worst_age = max(writer_age, evidence_age)
if worst_age > max_age:
    fail(
        "day_summary stale "
        f"(writer {int(writer_age)}s, evidence {int(evidence_age)}s, "
        f"max {int(max_age)}s)"
    )
PY
}

if ! skipped day_summary; then
    if ! DAY_SUMMARY_ERROR=$(day_summary_health); then
        fail_out "${DAY_SUMMARY_ERROR:-day_summary health unknown}"
    fi
fi

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
