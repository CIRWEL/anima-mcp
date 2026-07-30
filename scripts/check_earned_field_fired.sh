#!/usr/bin/env bash
# One-shot calibration watch for the resonance earned_field completion signal
# (anima-mcp 25f2016). The revisit-ratio thresholds were calibrated from one
# live field snapshot — provisional BY DESIGN. This runs daily from launchd
# (com.cirwel.earned-field-watch, Mac-local plist) and self-removes:
#   - earned_field observed in the Pi journal -> post info finding, retire.
#   - never observed by DEADLINE -> post medium finding telling the operator
#     to recalibrate SETTLED_REVISIT_RATIO from the logged completion values
#     (every completion line carries curio/fatigue; revisit ratio is in the
#     era earned log line), then retire.
# Wired-wake-condition pattern: parked items get automation, not memory notes.

set -uo pipefail

LABEL="com.cirwel.earned-field-watch"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
DEADLINE="2026-08-05"
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
    "resonance earned_field completion has NOT fired since deploy (2026-07-29, anima 25f2016). The revisit-ratio calibration is too strict — lower SETTLED_REVISIT_RATIO (currently 0.6) or SETTLED_STREAK in display/eras/resonance.py using the logged completion-line values, or the earned path stays as unreachable as the one it replaced."
  retire "deadline reached without a fire — operator finding posted"
  exit 0
fi

echo "[$(date '+%F %T')] no earned_field yet (deadline $DEADLINE) — watching"
