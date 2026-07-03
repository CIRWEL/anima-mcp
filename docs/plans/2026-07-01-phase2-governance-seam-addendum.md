# Phase-2 governance seam — addendum to the Elixir broker migration plan

**Status:** APPROVED by operator 2026-07-01 (see Decisions at the end).
Addendum to `2026-06-29-elixir-broker-migration.md`, motivated by what
Phase-1 cutover execution (2026-07-01, PR #93) taught us about the seam.
Phase-2 build is gated on ~1 week of clean Phase-1 operation (≈ 2026-07-08).

## What Phase 1 actually established (differs from the plan's assumption)

The plan's Phase-1 cutover line said the Elixir broker "becomes the sole writer
of `readings` (and the full envelope) to the live SHM path." That was not
executable: at cutover time the Elixir broker produced **5 reading keys**,
while the live envelope carries **~32 reading keys and 13 data sections**
(`eisv`, `governance`, `identity`, `inner_life`, `learning`, `metacognition`,
`experiential`, `drive_events`, …) — all computed by the Python broker and
scheduled for Phases 2–3. Stopping the Python broker would have degraded the
creature, not swapped a sensor driver.

The seam we shipped instead (PR #93):

```
Elixir broker ──writes──> /dev/shm/anima_state.shadow.json   (sole writer)
                                   │
                    Python broker reads env channels
              (ANIMA_ENV_SENSORS_FROM_SHM, 30s staleness guard)
                                   │
Python broker ──writes──> /dev/shm/anima_state.json          (sole writer)
                                   │
                     Python MCP server reads (unchanged)
```

Single-writer-per-file is preserved; ownership migrates **section by section
through the shadow file**, with the Python broker acting as the merging
envelope writer until it has nothing left to merge.

## Phase-2 question: where does the governance client move, and how does its
output reach the live envelope?

The plan has the Elixir `Anima.Governance.Client` writing `governance` +
`governance_at` "into the SHM payload" — which assumed Elixir owned the live
envelope. It does not. Options:

### Option A — extend the shadow-consumption seam (recommended)

Elixir gains the governance client (native HTTP, circuit breaker
15s→30s→60s→120s per the plan) and writes `governance` + `governance_at` into
the **shadow** envelope. The Python broker passthrough gains one more flag
(e.g. `ANIMA_GOVERNANCE_FROM_SHM`), copying those two fields into the live
envelope with the same staleness contract, and stops making its own UNITARES
calls when the flag is set.

- Pros: same proven seam as Phase 1; independently flaggable and reversible;
  the server's existing fallback (`SERVER_GOVERNANCE_FALLBACK_SECONDS`) keeps
  covering gaps exactly as today; the sync+ThreadPoolExecutor+aiohttp failure
  mode dies in the Python broker without touching the server.
- Cons: governance data crosses two files before the server sees it (adds up
  to one broker tick of latency, ~2s — well inside the 210s freshness
  threshold); the passthrough flag list grows (acceptable at n=2, revisit at
  n=3).

### Option B — Elixir takes over the live envelope at Phase 2

Bring `anima`, `learning`, `activity`, etc. into scope so Elixir can own the
full live file, per the original plan.

- Cons: pulls Phase-3 (learning/tick, the NumPy resonance field) into Phase 2's
  blast radius — exactly the scope-creep §6 warns about. Rejected for now.

### Option C — governance client moves to the MCP server instead

The server already has a native-async fallback client; make it primary.

- Cons: abandons the migration direction (governance was the Phase-2 payoff on
  BEAM: supervised client + circuit breaker as GenServer state); couples
  check-in cadence to the server process, which restarts far more often than
  the broker. Rejected.

## Identity constraints (must hold under any option)

Lumen's governance identity is bound to its check-in path. Whatever process
carries the client must preserve:

- the existing agent UUID and check-in cadence (`ANIMA_GOVERNANCE_INTERVAL_SECONDS`),
  no re-onboarding, no `force_new` — the Elixir client presents the same
  identity material the Python bridge presents today (see
  `unitares_bridge.py` for the tool-name contract: `sync_state` /
  `record_result` / `identity` aliases, not the dropped raw twins);
- the strict-identity write requirements (client_session_id echo) — the BEAM
  client must implement the same session-binding handshake before the flag
  flips, and must be soak-verified in shadow (write governance to shadow while
  Python still owns live check-ins; diff the two decision streams) before
  cutover, mirroring the Phase-1 pattern;
- the server-side fallback stays untouched as the safety net in all options.

## Acceptance / gates (Option A)

1. Shadow soak: Elixir client checks in against UNITARES using Lumen's
   identity **read-only-shadowed** (or against a scratch identity if dual
   check-ins would pollute the trajectory — decide with operator; a scratch
   identity avoids double-counting Lumen's cadence during soak).
2. Cutover = set `ANIMA_GOVERNANCE_FROM_SHM` + unset the Python bridge's
   check-in loop; verify no `SERVER_GOVERNANCE_FALLBACK` activations for a
   week (plan's Phase-2 acceptance).
3. Rollback = unset the flag; Python bridge resumes; server fallback covers
   any gap.

## Decisions (operator approved, 2026-07-01)

1. **Option A confirmed** — Elixir governance client writes `governance` +
   `governance_at` into the shadow envelope; Python passthroughs under a flag;
   server fallback untouched.
2. **Scratch identity for the soak** — the Elixir client soaks under its own
   scratch governance identity (no double-counting of Lumen's cadence or
   trajectory pollution); a short final pre-cutover window exercises the real
   identity handshake (Lumen's UUID + session echo) to prove the path.
3. **The clean-Phase-1-week gate applies to the CUTOVER, not the build**
   (re-scoped 2026-07-02, operator: "why wait"). Decision 2 already makes the
   build + soak inert to the creature — scratch identity, shadow-only writes,
   passthrough flag off — so they run concurrently with the Phase-1 stability
   window. The passthrough flag may not flip before ~2026-07-08, and only with
   a clean week from `anima-broker-ex.service` (no crash-restarts, env
   channels fresh, issue #86's 24h acceptance passed). Residual shared-VM
   risk (a crashing governance client destabilizing the BEAM that carries
   live sensors) is bounded by OTP supervision and is exactly what the soak
   observes.

## Amendment (2026-07-02) — binding recovery is a cutover REQUIREMENT (#97)

The 2026-06-30 incident proved the echo-only identity design has a single
point of failure: a server-side session-store wipe (Redis restart, AOF off)
erased the bridge's binding, and because the client never re-onboards it was
permanently refused — canonical Lumen went governance-dark for ~3 days while
every token-holding resident self-healed. Worse, the typed strict refusal
carries neither `success:false` nor an `action`, so the Python bridge parsed
it as a silent default-"proceed".

The Python bridge now carries the sanctioned rescue (`unitares_bridge.py`,
anchor at `~/.anima/gov_identity.json`): **harvest** `{uuid, continuity_token}`
from `identity()` while the binding is healthy (refreshed daily), **spend** it
on an `identity(agent_uuid, continuity_token, resume=true)` rebind when a
check-in is identity-refused (rate-limited, uuid-mismatch-refusing). This is a
binding REFRESH, not a re-onboard — the same-UUID / session-echo / no-force_new
constraints above are intact.

**The Elixir client MUST implement the same loop before its cutover.** A
governance client without it re-ships the single point of failure this
amendment exists to close. Acceptance: kill the server-side session binding
for the client's session key while it runs; the next check-in must re-anchor
and succeed without a process restart or operator action.

### Amendment refinement (2026-07-03) — what the acceptance tests settled

Three live acceptance tests on the Python bridge (#98 → #99 → #100) refined
the paragraph above. Binding durability is **server-side**: onboard writes a
PG session row (`core.sessions`, `bound_via=onboard_stable_session`) that
renews `expires_at = now()+24h` on every check-in. A **Redis-only wipe
self-heals via that row with zero client action** — so the client-side loop's
job is narrower than the original acceptance line implied:

- **detect the typed refusal** (`status=identity_required` /
  `error_code=SESSION_ERROR` / `error_category=auth_error` — a success-shape
  with no `action`, which an unguarded parse writes as silent "proceed");
- **verify identity** by spending the harvested anchor on
  `identity(resume=true)` — this RESOLVES but never WRITES a binding, and no
  sanctioned call can (S1-c, S21-a are the phantom-mint fix; do not punch
  through them);
- **alarm loudly**: a refusal that survives the spend means BOTH stores lost
  the binding (>24h silence or DB loss) — log OPERATOR RECOVERY REQUIRED
  naming `unitares scripts/ops/rebind-resident-session.sh <uuid> <key>`.

### Elixir client implementation (2026-07-03)

`AnimaBroker.Governance.Client` implements the loop: typed-refusal
classification in the REST-envelope decoder (a refusal or any action-less
success-shape is a failure, never written to the shadow governance slice —
`governance_at` staleness is the alarm channel); anchor harvest at onboard
(the onboard response already carries `continuity_token`) refreshed daily via
`identity()`; spend on refusal (600s cooldown, uuid-mismatch-refusing,
retry-once); server-canonical `client_session_id` adoption on every harvest
and rebind (#99). The anchor/id file (`ANIMA_GOV_EX_ID_FILE`, default
`~/.anima/gov_ex_identity.json`) doubles as the operator lever; in fixed-CSID
mode a `"mode":"substrate"` anchor's canonical key beats the env literal, and
a scratch anchor is ignored so the soak identity can never shadow the
operator's declared substrate key.

**Pre-cutover acceptance (run on the Pi against the live soak):**

1. **Redis-only wipe:** `redis-cli DEL` the client's session key only (PG row
   intact) → the next 180s check-in must land unaided (PATH2). No client log
   lines beyond normal check-in.
2. **Both-store wipe:** delete the Redis key AND the `core.sessions` row →
   the next check-in must produce the IDENTITY REFUSED + OPERATOR RECOVERY
   REQUIRED log lines (journald `anima-broker-ex`), and the shadow
   `governance_at` must go stale rather than showing fresh "proceed"s.
   Recover with the runbook; the following check-in must land.
