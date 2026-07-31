#!/usr/bin/env bash
# One-shot calibration watch for the resonance earned_field completion signal
# (anima-mcp 25f2016). The revisit-ratio thresholds were calibrated from one
# live field snapshot — provisional BY DESIGN. This runs daily from launchd
# (com.cirwel.earned-field-watch, Mac-local plist) and self-removes:
#   - earned_field observed in the Pi journal -> post info finding, retire.
#   - never observed by DEADLINE -> post medium finding pointing the operator
#     at diagnostics.drawing.settling (which now reports WHICH gate held it
#     back), then retire. It deliberately does NOT conclude the calibration is
#     too strict: a piece drawn on a "sparse" goal legitimately never revisits
#     accumulated field, and refusing to earn completion there is the signal
#     working, not failing.
# Wired-wake-condition pattern: parked items get automation, not memory notes.

set -uo pipefail

LABEL="com.cirwel.earned-field-watch"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
# Extended from 2026-08-05. The original clock started 2026-07-29, but until
# 2026-07-30 (#116) revisit_window and settled_streak were not persisted, so
# every service restart reset them — and the earned path needs 50 deposits plus
# a 5-check streak, roughly 100 min of uninterrupted uptime at observed mark
# rates. Twelve deploys that day made a fire impossible regardless of
# thresholds, so the signal never had a fair window. This gives it one.
DEADLINE="2026-08-14"
PI_HOST="${LUMEN_SSH_HOST:-pi-anima}"
GOV_API_URL="${UNITARES_GOVERNANCE_HTTP_URL:-http://127.0.0.1:8767}"
SECRETS_FILE="${UNITARES_SECRETS_ENV:-$HOME/.config/cirwel/secrets.env}"

HTTP_API_TOKEN="$( ( [ -f "$SECRETS_FILE" ] && set -a && . "$SECRETS_FILE" >/dev/null 2>&1; printf '%s' "${UNITARES_HTTP_API_TOKEN:-}" ) || true )"

post_finding() {
  local severity="$1" fingerprint="$2" message="$3" payload
  payload=$(python3 -c '
import json,sys
print(json.dumps({
  "type": "drawing_calibration_finding",
  "severity": sys.argv[1], "message": sys.argv[2],
  "agent_id": "earned-field-watch", "agent_name": "earned-field-watch",
  "fingerprint": sys.argv[3],
}))' "$severity" "$message" "$fingerprint" 2>/dev/null) || return 0
  curl -s --max-time 10 -o /dev/null \
    ${HTTP_API_TOKEN:+-H "Authorization: Bearer $HTTP_API_TOKEN"} \
    -H "Content-Type: application/json" \
    -X POST "$GOV_API_URL/api/findings" -d "$payload" 2>/dev/null || true
}

retire() {
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "[$(date '+%F %T')] earned-field-watch retired: $1"
}

hits="$(ssh -o BatchMode=yes -o ConnectTimeout=15 "$PI_HOST" \
  "sudo journalctl -u anima --since '-8 days' --no-pager 2>/dev/null | grep -c 'Era earned completion'" 2>/dev/null || echo ssh_failed)"

if [ "$hits" = "ssh_failed" ]; then
  echo "[$(date '+%F %T')] Pi unreachable — will retry tomorrow"
  exit 0
fi

if [ "${hits:-0}" -gt 0 ] 2>/dev/null; then
  line="$(ssh -o BatchMode=yes -o ConnectTimeout=15 "$PI_HOST" \
    "sudo journalctl -u anima --since '-8 days' --no-pager | grep 'Era earned completion' | tail -1" 2>/dev/null)"
  post_finding "info" "earned-field-first-fire" \
    "resonance earned_field completion fired (${hits}x) — calibration reachable, no retune needed. Last: ${line:0:300}"
  retire "signal confirmed (${hits} fires)"
  exit 0
fi

if [ "$(date '+%F')" \> "$DEADLINE" ] || [ "$(date '+%F')" = "$DEADLINE" ]; then
  post_finding "medium" "earned-field-never-fired" \
    "resonance earned_field has NOT fired by the deadline. Do NOT assume the calibration is too strict — read diagnostics.drawing.settling first (anima-mcp #115): it reports every gate and its margin (marks / fatigue / revisit_ratio / revisit_window_filled / settled_streak), so the failing gate is now identifiable rather than inferred. Two benign explanations to rule out before retuning: (1) pieces drawn on a sparse drawing_goal legitimately never revisit accumulated field, so not earning completion is correct behaviour, not miscalibration; (2) frequent service restarts truncate the run — the counters persist since #116, but the window still needs 50 deposits plus a 5-check streak. Only if settling shows revisit_ratio plateauing well below 0.6 on a NON-sparse goal across an uninterrupted run is SETTLED_REVISIT_RATIO the thing to change."
  retire "deadline reached without a fire — operator finding posted"
  exit 0
fi

echo "[$(date '+%F %T')] no earned_field yet (deadline $DEADLINE) — watching"
