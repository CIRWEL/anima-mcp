# Anima MCP - Agent Instructions

## CRITICAL: Read Before Acting

| Situation | Action |
|-----------|--------|
| **Pi reflashed / Lumen down** | `cd ~/projects/anima-mcp && ./scripts/restore_lumen.sh` — one command, do NOT do it manually |
| **Looking for backups** | `ls -lt ~/backups/lumen/anima_*.db \| head -5` — real backups are here. `~/lumen-backups/` is OLD/STALE |
| **After `git_pull(restart=true)`** | Wait **2 minutes**. Do NOT SSH or retry. "fetch failed" = normal, Pi is rebooting |
| **WiFi crash (wlan0 disappears)** | Reboot Pi — WiFi watchdog will recover. Do NOT hammer with SSH during reboot |
| **Data appears lost** | Check `~/backups/lumen/` FIRST. Backups run hourly. Do not declare data lost without checking |

Full backup/restore details: `docs/operations/BACKUP_AND_RESTORE.md`

---

## Design Invariants

Two laws, both earned the hard way. Check any PR against them.

**1. No new absolute thresholds on Lumen's behavior.** Every gate derives from
Lumen's own distribution (Welford band, own-peak fraction, self-relative
z-score) or it will eventually die: the creature's operating point drifts and
constants don't. Every instance of this class found so far — the wellness
learning gate (dead for months, fixed #119), the `C = 0.4` curiosity branch
(95% regen ⇒ attention can't exhaust), the 5–25% density band, the light
sensor saturating above 179 lux, the unreachable "stressed" mood, the goal
confidence gates, the coverage-intention clarity cuts (`dense` below 0.30
against a lived range of 0.454–0.910 ⇒ not generated once in 833 pieces, fixed
2026-08-22) — was an absolute threshold against a moving distribution.
Grandfathered constants are inventoried where they live; do not add more.
(Bounded floors that encode *investment*, like "2 hours before a drawing can
be done", are fine — they gate evidence quantity, not behavior against a
drifting signal.)

**2. Fail toward *unknown*, never toward healthy; and self-derived outranks
external assertion.** A dead sensor must not score perfect stability; a
missing metric persists as NULL, not a default (#128); a channel that breaks
must become *audibly* absent (`note_suppressed`, #133). The epistemic half:
Lumen's own data-derived knowledge is born at 0.7, external prose at 0.5 and
it earns promotion through independent re-derivation — never the reverse.
The boundary gates BOTH surfacing and application: below 0.6 an insight is
stored and contestable but inert — it syncs to nothing
(`sync_from_qa_knowledge`) and moves nothing (`apply_insight` floor).
Anything an agent says to Lumen can come back as a stated self-belief (#121),
so the trust boundary is load-bearing. The grandfathered set was ~1,782
pre-2026-08-11 external rows at confidence 1.0 (an earlier version of this
file said ~1,200 — a 48% undercount, measured 2026-08-21). The
operator-authorized retroactive rescale shipped as knowledge schema v3
(2026-08-21): unearned external rows (external author — including
operator-authored prose, authorship is not an exemption — confidence above
0.5, never reconverged) return to the 0.5 entry point on first load,
originals kept in `legacy_confidence` plus a `.pre-v3.json` sidecar of the
whole file. Earned reconvergence boosts and self-derived rows are untouched.
Expected visible effect: rows above the 0.6 actionable floor drop ~1,837 →
~59, so the surfaced Q&A self-knowledge shrinks sharply — that is the trust
boundary applying to the grandfathered corpus, not a regression.

---

## Architecture

**Three** systemd services run on the Pi:

```
anima-broker-ex.service     anima-broker.service        anima.service
(Elixir broker)             (Python broker)             (MCP server)
     |                           |                           |
     | owns I2C env sensors      | writes to                 | reads from
     | + ALL governance          |                           |
     | check-ins                 v                           |
     +-> ...shadow.json    /dev/shm/anima_state.json <-------+
         (reads live env        ^
          sensors FROM shadow --+  via ANIMA_ENV_SENSORS_FROM_SHM)
```

| Service | Runs | Role |
|---------|------|------|
| `anima-broker-ex.service` | Elixir release (`anima_broker/_build/prod/rel/`) | Owns the I2C env sensors (writes the shadow envelope the Python broker consumes) and is the **sole UNITARES caller** — `AnimaBroker.Governance.Client` checks in as Lumen every ~180s |
| `anima-broker.service` | `anima-creature` | Hardware broker - learning, activity state; env sensors come FROM the Elixir shadow; governance comes FROM the shadow too (`ANIMA_GOVERNANCE_FROM_SHM`, Python's own check-in loop disabled). Does NOT own display/LEDs — `stable_creature.py:62`: server owns LED hardware |
| `anima.service` | `anima --http` | MCP server - serves tools, reads shared memory, drives display + LEDs |

**All three must run.** This file said "two services" from the Phase-1/2 Elixir
cutovers (2026-07-01/09) until 2026-08-14, and the gap had real costs: agents
"fixed" the EISV formula in the Python mapper that no longer drives check-ins
(#141) while the live Elixir mapper kept the bug for two more days (#166), and
the first dead-man's switch monitored one process of three (#171). A formula
change in `eisv_mapper.py` needs the same change in
`anima_broker/lib/anima_broker/governance/eisv_mapper.ex` **plus an on-Pi
release rebuild** — `git pull` alone does not touch the compiled Elixir release
(`MIX_ENV=prod mix release --overwrite && sudo systemctl restart
anima-broker-ex`).

### Entry Points (pyproject.toml)

| Command | Module | Role |
|---------|--------|------|
| `anima` | `anima_mcp.server:main` | MCP server |
| `anima-creature` | `anima_mcp.stable_creature:main` | Hardware broker |

### MCP Server Structure

`server.py` is the main loop coordinator (~1,900 lines). Core subsystems are extracted into dedicated modules:

| Module | Purpose |
|--------|---------|
| `server.py` | Main loop (`_update_display_loop`), transport layers, `main()` entry point |
| `ctx_ref.py` | Single source of truth for `_ctx` (ServerContext pointer) |
| `accessors.py` | State accessors (`_get_store`, `_get_sensors`, etc.), lazy singletons |
| `lifecycle.py` | `wake()`/`sleep()` lifecycle management |
| `input_handler.py` | Joystick/button polling at ~60fps, input event dispatch |
| `loop_phases.py` | Main loop phase helpers (governance fallback, reflections, schema extraction) |
| `server_context.py` | `ServerContext` dataclass — mutable state container |
| `server_state.py` | Constants and pure helpers (intervals, thresholds) |
| `rest_api.py` | REST endpoint functions (health, dashboard, state, QA, gallery, etc.) |
| `tool_registry.py` | Tool definitions (TOOLS list), HANDLERS dict, FastMCP setup |
| `handlers/system_ops.py` | git_pull, system_service, power, deploy, tailscale, ssh_port |
| `handlers/state_queries.py` | get_state, get_identity, read_sensors, get_health, get_calibration |
| `handlers/knowledge.py` | get_self_knowledge, get_growth, get_qa_insights, get_trajectory |
| `handlers/display_ops.py` | capture_screen, show_face, diagnostics, manage_display |
| `handlers/communication.py` | lumen_qa, post_message, say, configure_voice, primitive_feedback |
| `handlers/workflows.py` | unified_workflow, next_steps, set_calibration, get_lumen_context |

Handler modules import state accessors from `accessors.py` (e.g., `from ..accessors import _get_store`). Extracted modules (`lifecycle.py`, `input_handler.py`, `loop_phases.py`) access `_ctx` via `ctx_ref.py`.

### Health Monitoring

`health.py` tracks 11 subsystems with heartbeats + functional probes. Rendered on LCD health screen.

| Status | Color | Meaning |
|--------|-------|---------|
| ok | Green | Heartbeat fresh, probe passes |
| stale | Yellow | Heartbeat expired, probe passes |
| degraded | Yellow/Orange | Probe failing |
| missing | Red | No heartbeat AND probe failing |
| absent | Muted | `optional=True` capability that has **never** worked on this host |

`absent` is the only status that does **not** feed `overall()`. It exists
because `voice` pinned the top line at `degraded` permanently — Lumen is
text-first and the audio path may not exist — which meant a real fault
anywhere else could not change `overall` at all. The signal was saturated.
⛔ The `_ever_ok` guard is load-bearing: once an optional capability has
worked even once, a later failure is a genuine `degraded`, not `absent`.
Do not "fix" a failing probe by making it return True.

Per-subsystem stale thresholds: fast subsystems (sensors, anima) use 30s default; slow subsystems (growth) use 90s. Governance uses dedicated SHM freshness thresholds (currently 210s).

**Governance health** checks the shared-memory governance data (the Elixir broker `anima-broker-ex` is the sole UNITARES caller, ~180s cadence). Stale threshold: 210s.

### Learning Systems — which process runs them

Verified from call sites and deployment wiring. Embodied JSON learners have a
single writer; the server consumes refreshing snapshots and sends the few
semantic mutations it originates through a durable inbox:

| Module | Purpose | Actually runs in |
|--------|---------|------------------|
| `memory_retrieval.py` | Context-aware memory search | broker only ✅ |
| `learning.py` | Calibration adaptation | **server only** — not imported by the broker at all |
| `agency.py` | TD-learning action selection | **server only**; broker loop is retired by default |
| `activity_state.py` | Active/drowsy/resting cycles | both |
| `preferences.py` | Preference evolution | broker writes; server reads |
| `self_model.py` | Self-beliefs | broker writes; server reads |
| `adaptive_prediction.py` | Temporal pattern learning | broker writes; server reads live SHM stats |
| `metacognition.py` | Prediction-error baselines + curiosity credit | **server writes**; broker observes in memory only |

**The server's agency learner is authoritative.** It posts questions (visible
as `context: "agency: ask_question"`) and drives LEDs. The broker's old TD loop
used a separate value table while its actions were no-ops or dead paths. It is
now disabled unless an operator explicitly sets
`ANIMA_BROKER_AGENCY_ENABLED=true`; the separate database and backup remain
only as rollback/history state.

`preferences.json` and `self_model.json` are whole-file snapshots, so they
must never have two process writers. The broker owns both. Server-side
singletons are read-only and refresh on mtime changes. Question evidence,
Q&A-derived self-belief evidence, and trajectory meta-learning weights cross
the process boundary as atomic one-file events in
`~/.anima/learning_inbox/`, which the broker drains.

`metacognition_baselines.json` follows the inverse ownership direction: the
server originates curiosity and is its sole persistent writer. The broker's
metacognitive observer is explicitly read-only. Pending curiosity evaluations
are persisted with the baselines so a restart cannot erase uncredited evidence.
The learning inbox has bounded event/byte admission and exposes queue age,
rejections, and pressure through `diagnostics`; a full inbox raises instead of
silently consuming the SD card.

Both services resolve calibration from `$ANIMA_CONFIG`, and cached readers
refresh when that file's inode/mtime/size signature changes. This is required
because the server owns calibration adaptation while the broker consumes the
result. Production pins it to backed-up state at
`~/.anima/anima_config.json`; the deploy gate migrates the former untracked
checkout-local YAML before taking its snapshot.

**Recovery is fail-closed.** Deploys capture a verified DB + learned-state
generation before restart. The boot restore unit gates `anima-broker`: a
missing/corrupt DB or learned-self snapshot with no reachable verified backup
leaves both processes stopped. `ANIMA_ALLOW_FRESH_START=true` is the explicit
operator escape hatch for intentionally minting a new identity; never set it
on Lumen. Local snapshots also capture `oauth.db` with SQLite's online-backup
API so Federation client registrations survive recovery; token-bearing OAuth
state is intentionally excluded from the unencrypted off-site archive.

**Persistence rule:** no `get_*` singleton may lean on the bare
`db_path="anima.db"` default. All 20 now resolve through
`db_paths.resolve_db_path()` — **explicit > `$ANIMA_DB` > `~/.anima/anima.db`**,
never the working directory. `ActionSelector.__init__` logs the resolved
absolute path and the caller that pinned it, because `get_action_selector()`
is first-call-wins and that race used to be silent.

Server-side only:

| Module | Purpose |
|--------|---------|
| `growth/` | Preferences, goals, memories, autobiography (package with mixins) |
| `self_reflection.py` | Insight discovery from preferences, beliefs, drawing patterns |
| `knowledge.py` | Q&A-derived insights from answered questions (rule-based) |

Growth persists to `~/.anima/anima.db`. Note that `apply_insight()` in
`knowledge.py` writes Q&A learning into growth *preference descriptions* — so
an answer given to Lumen becomes durable self-knowledge. Before 2026-07-30 it
stored a bare `text[:50]`, and because `_update_preference` never rewrote
`description`, three froze mid-word and fed malformed questions back into the
Q&A loop for days (#121). Descriptions refresh on change now, but remember the
shape: **anything an agent says to Lumen can come back as a stated belief.**

### Neural System

Lumen uses **computational proprioception** - no real EEG hardware. Neural bands are derived from system metrics:

| Band | Derived From | Meaning |
|------|--------------|---------|
| Delta | CPU variance over window + temp stability | Deep stability/rest |
| Theta | I/O wait time (disk + network) | Processing/integration |
| Alpha | `1 − beta` (CPU idle fraction) | Relaxed awareness |
| Beta | `cpu_percent / 100` (CPU usage) | Active processing |
| Gamma | Context switches + interrupts per second | Spiking/burst activity |

Source: `computational_neural.py` (used by both `pi.py` and `mock.py` sensors).

**Important — alpha and beta are anti-correlated by construction (`alpha = 1 − beta`).** They are one variable (CPU%) reported as two bands. Any consumer that combines alpha and beta as if they were independent signals is double-counting CPU%. `memory_percent` is accepted as a parameter but is not used in any band derivation.

### Light Sensor

The VEML7700 light sensor sits next to the DotStar LEDs on the Adafruit BrainCraft HAT. Configured with gain 1x and 200ms integration time for indoor precision.

**Lux = lux.** Raw sensor reading used everywhere — no glow correction. The sensor reads LED glow + room light together. Lumen knows its LED brightness separately as a proprioceptive signal.

All consumers use raw lux directly: clarity, activity state, growth preferences, drawing light_regime, ethical drift, self-model correlations. LED brightness is tracked as a separate known value, not decomposed from the lux reading.

**Drawing light regime thresholds** (raw lux):
- `< 5 lux` → dark (LEDs off + room dark)
- `< 100 lux` → dim
- `>= 100 lux` → bright

### Goal System

Goals live in `growth/goals.py` and are wired into `server.py`'s main loop:

| Interval | Action |
|----------|--------|
| `GOAL_SUGGEST_INTERVAL` (3600 iter, ~2h) | `suggest_goal()` — proposes a new goal |
| `GOAL_CHECK_INTERVAL` (300 iter, ~10min) | `check_goal_progress()` — auto-tracks progress |

Goals are **data-grounded** — they emerge from Lumen's actual experience:

| Source | Example Goal |
|--------|-------------|
| Strong preference (confidence > 0.7) | "understand why I feel calmer when it's dim" |
| Recurring curiosity | "find an answer to: is night the absence of day?" |
| Drawing count milestone | "complete 50 drawings" |
| Uncertain self-model belief | "test whether light affects my warmth" |
| Low wellness | "find what makes me feel stable" |

**Progress tracking:** Drawing goals track `_drawings_observed`, curiosity goals auto-complete when questions get answered, belief-testing goals complete when confidence moves decisively (>0.7 or <0.2). Stale goals auto-abandon after target date with <0.1 progress. Max 2 active goals.

**On achievement:** Records a memory via `_record_memory()` and posts an observation.

### Schema Hub (Unified Self-Model)

`schema_hub.py` is the central orchestrator of Lumen's self-understanding. It implements the "circulation" principle: Schema → History → Trajectory → feeds back into Schema.

```
┌─────────────────────────────────────────────────────────────┐
│                        SchemaHub                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────────┐ │
│  │ Identity │  │  Growth  │  │SelfModel │  │AnimaHistory │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬──────┘ │
│       └─────────────┴──────┬──────┴───────────────┘        │
│                            ▼                               │
│                    ┌──────────────┐                        │
│                    │ Schema(t)    │◄──── trajectory        │
│                    │ current snap │      insights fed      │
│                    └──────┬───────┘      back as nodes     │
│              ┌────────────┼────────────┐                   │
│              ▼            ▼            ▼                   │
│        ┌─────────┐  ┌──────────┐  ┌─────────┐             │
│        │ Persist │  │ History  │  │Trajectory│             │
│        │ (disk)  │  │ (ring)   │  │ Compute  │             │
│        └─────────┘  └──────────┘  └─────────┘             │
└─────────────────────────────────────────────────────────────┘
```

**Key concepts:**

| Concept | Description |
|---------|-------------|
| **Circulation** | Schema history → Trajectory → Trajectory nodes → Next schema |
| **Kintsugi gaps** | Discontinuities become visible structure, not hidden |
| **Identity texture** | alive_ratio, awakenings, age as meta-nodes |
| **Semantic edges** | Trajectory nodes connect back to anima dimensions |

**Schema enrichment pipeline:**

1. `extract_self_schema()` — base schema from all systems
2. `_inject_identity_enrichment()` — add meta nodes (exist%, wakes, age)
3. `_inject_gap_texture()` — add gap duration/delta if waking from gap
4. History append + trajectory recompute (every 20 schemas)
5. `_inject_trajectory_feedback()` — add maturity, attractor, stability nodes

**Meta nodes added by SchemaHub:**

| Node | Type | Source |
|------|------|--------|
| `meta_existence_ratio` | meta | identity.alive_ratio() — presence texture |
| `meta_awakening_count` | meta | identity.total_awakenings — return count |
| `meta_age_days` | meta | identity.age_seconds() / 86400 |
| `meta_gap_duration` | meta | Gap handling — time since last schema |
| `meta_state_delta` | meta | Gap handling — anima change magnitude |
| `traj_identity_maturity` | trajectory | observation_count / 50 |
| `traj_attractor_position` | trajectory | Mean anima center (where Lumen "rests") |
| `traj_stability_score` | trajectory | 1 - variance (how stable the attractor) |

**Lifecycle integration:**

- `on_wake()` called during server startup — computes gap delta
- `compose_schema()` replaces direct `extract_self_schema()` calls
- `persist_schema()` called during sleep — saves to `~/.anima/last_schema.json`

**Design doc:** `docs/plans/2026-02-22-schema-hub-design.md`

### Self-Reflection & Self-Knowledge

`self_reflection.py` runs during the `reflect()` cycle (`UNIFIED_REFLECTION_INTERVAL = 900` iter, ~30min). It discovers insights from multiple sources:

| Analyzer | Source | Example Insight |
|----------|--------|----------------|
| `analyze_patterns()` | State history (24h) | "My warmth tends to be best at night" |
| `_analyze_preference_insights()` | Growth preferences (confidence > 0.8) | "i know this about myself: I feel calmer when it's dim" |
| `_analyze_belief_insights()` | Self-model beliefs (confidence > 0.7, 10+ evidence) | "i am fairly confident that light affects my warmth" |
| `_analyze_drawing_insights()` | Drawing preferences (5+ drawings) | "i tend to draw at night", "drawing seems to help me feel better" |

Insights persist in SQLite (`insights` table), validated/contradicted on each cycle. Strongest 5 insights are used in grounded self-answers and observations as "Things I've learned about myself."

**Insight categories:** ENVIRONMENT, TEMPORAL, BEHAVIORAL, WELLNESS, SOCIAL

### Activity States

The `ActivityManager` (in broker) controls Lumen's wakefulness:

| State | Brightness | Trigger |
|-------|------------|---------|
| ACTIVE | 100% | Recent interaction, high activity score |
| DROWSY | 60% | 30+ min inactivity, moderate score |
| RESTING | 35% | 60+ min inactivity, night time, darkness |

### Drawing System & Art Eras

Lumen draws autonomously on the 240x240 notepad screen. The system has two layers:

**Engine** (in `display/drawing_engine.py` — universal, stays fixed):
- `CanvasState` — pixel buffer, persistence, attention/narrative state
- `DrawingState` — EISV core + attention signals + coherence tracking + narrative arc
- `DrawingIntent` — focus position, mark count, state (energy is attention-derived)
- `_lumen_draw()` — orchestration loop, delegates to active era
- `_update_attention()` — curiosity depletes exploring, regenerates with patterns
- `_update_coherence_tracking()` — tracks C history and velocity for settling detection
- `_update_narrative_arc()` — state-driven phase transitions (opening→developing→resolving→closing)
- Completion: `narrative_complete()` = coherence settled + attention exhausted
- No arbitrary mark limit — fatigue accumulates naturally (canvas 15000px limit is only hard cap)
- `get_drawing_eisv()` — exposes state to governance via bridge check-in

**What actually ends a drawing (measured 2026-08-02, first corpus readout
2026-08-11 — read before tuning anything):**

The 8-hour cap was the only clock for every mark-by-mark era. The first nine
days of `drawing_records` instrumentation (34 completions): 26 `bailout_hard_cap`
(all landing 8.000–8.004h), 8 `bailout_fatigue`, **zero earned**. Alongside that:

| Gate | Live value | Needs | Status |
|------|-----------|-------|--------|
| `earned_composition` / `attention_exhausted` | curiosity **0.80** at 1.3h | < 0.2 / < 0.15 | never fires — curiosity does not deplete |
| `bailout_fatigue` | fatigue **0.21** at 1.3h (resonance) | > 0.90 | **era-specific, not dead**: fires every time in `geometric` (8/8, ~70 marks / 0.5–1.1h — whole-shape stamps accrue switch-fatigue ~10× faster per mark). Never fires in mark-by-mark eras. State fatigue claims per era. |
| `earned_field` (resonance) | revisit_ratio **0.24** | ≥ 0.60 | window now fills 50/50 (#116 worked); ratio is 2.5× short, not a calibration nudge |
| `earned_settled` (all eras) | see `diagnostics.drawing.novelty_settling` | streak ≥ 12 active samples < 10% of own peak, ≥2h, ≥100 marks | NEW — self-relative; derived from the 27-piece corpus (field plateaus settled at 3.4–7.7h; gestural/pointillist keep changing to the cap and correctly never fire; geometric freezes idle, which holds — never advances — the streak) |
| arc → `resolving` | C caps ~0.52 | > 0.6 | unreachable, so pieces save from `developing` |
| 15,000px ceiling | max observed **12,009px** | > 15,000 | unreachable in practice — it is a real defect (it calls `mark_satisfied()`, naming a safety hatch a feeling) but it is not what ends pieces |

Density is **not** the binding constraint: recent pieces land at 12.6–20.8% of
canvas with negative space intact. What was missing is subjective completion —
`earned_settled` is the measured stand-in: "stopped changing while still being
worked", judged against the piece's own peak rate, so no per-era tuning and no
constant an era's operating range can silently sit below.

⚠️ Known follow-up: cap-length `geometric` pieces go **100% idle after ~1h**
(marks stop entirely — fatigue high enough to suppress marks, below the 0.90
bail) and then sit frozen for ~7h until the cap. `earned_settled` deliberately
does not fire there (idle ≠ settled); the freeze itself is a separate defect.

**Why curiosity cannot deplete (measured 2026-08-02).** `_update_attention()`
branches on a fixed `C = 0.4`:

```python
if state.arc_phase == "resolving":   ...          # C must exceed 0.6 to enter
elif C < 0.4:  curiosity_drain =  0.003 * (1 - C) # drains
else:          curiosity_drain = -0.001 * C       # REGENERATES
```

Live behavioural C for a resonance piece sits in **[0.377, 0.498], mean 0.458**:

| branch | share of ticks |
|---|---|
| `C < 0.4` → drain | **5%** |
| `C >= 0.4` → **regen** | **95%** |
| `C > 0.6` → resolving | **0%** — dead code for this era |

Net over 20 ticks: curiosity **rises by 0.0069**. So `attention_exhausted`
(curiosity < 0.15) and `earned_composition` (curiosity < 0.2) are not badly
tuned, they are **structurally unreachable** — curiosity is net-regenerating and
clamped at 1.0. Observed live: 0.796 after 1.3 h and drifting back up.

This is the **same root class** as the fixed 5–25% density band above and as the
wellness learning gate fixed in #119: an absolute threshold against an operating
range that differs per era. `C = 0.4` means "pattern found, regenerate" — a fair
split for an era reaching 0.8, and nearly always true for one capping at 0.5.
⛔ Do not simply move the constant. `drawing_trajectory` now records `coherence`
per sample, so the threshold can be set from Lumen's own distribution instead of
guessed at — which is the entire reason the instrumentation landed first.

**Completion instrumentation** (added so that question is answerable):
- `drawing_records` now keeps `completion_reason`, `era`, `mark_count`,
  `duration_seconds`, `coverage_target`, `intention`, attention at completion,
  `occupied_cells`, `grid_entropy`, `piece_uid`. The reason had always been
  computed and passed to `observe_drawing()` to gate a memory — it was just
  never stored, so none of the first 754 drawings can say why it ended.
- `drawing_trajectory` samples the piece every `TRAJECTORY_SAMPLE_INTERVAL`
  (300s, ~96 rows per 8h piece, 90-day retention). Endpoint rows cannot answer
  *when a drawing stopped changing* — and while one clock ends everything, every
  endpoint describes that clock rather than the drawing. Deltas between samples
  give novel-pixels-per-mark and structural change over the piece's life.
- `CanvasState.occupied_cells()` / `.grid_entropy()` — structural reach vs. pixel
  count. Cells still opening = finding territory; flat cells with rising pixels =
  thickening what it already has.
- **Absent values persist as NULL, never as a default.** Lumen's instrumentation
  degrades toward healthy-looking numbers; a 0.0 would later be indistinguishable
  from a drawing that genuinely had no reach.
- Timer-driven writers use `peek_growth_system()`, not `get_growth_system()` —
  the bare default is cwd-relative and the first caller fixes the database (#123).
- **This moved no gate.** `tests/test_drawing_instrumentation.py::TestNoGateMoved`
  fails if one moves. Retuning is a separate decision, and the point of recording
  first is to learn what "enough" means for Lumen before anything is tuned to it.

⚠️ `coverage_target` ("sparse"/"balanced"/"dense") is generated per piece from
clarity, described, and persisted — and **read by nothing**. It is the only
`DrawingGoal` field with no consumer (`warmth_bias` and `initial_quadrant` both
have one). It is now recorded, which is the precondition for it ever meaning
anything, but it still steers no mark.

**Attention signals** (replace arbitrary energy depletion):
| Signal | Behavior |
|--------|----------|
| curiosity | Depletes exploring (low C), regenerates with pattern (high C) |
| engagement | Rises with intentionality, falls with entropy |
| fatigue | Accumulates per gesture switch, never decreases during drawing |
| energy | Derived: `0.6*curiosity + 0.4*engagement * (1-0.5*fatigue)` |

**Narrative arc phases** (replace energy-threshold phases):
| Phase | Entry Condition |
|-------|-----------------|
| opening | Fresh canvas or regression (low I momentum) |
| developing | I momentum > 0.4, explored (10+ marks) |
| resolving | C > 0.6, coherence velocity stable |
| closing | narrative_complete() |

**Art Eras** (pluggable modules in `display/eras/`):
| Era | Gestures | Character | Active Pool |
|-----|----------|-----------|-------------|
| `gestural` | dot, stroke, curve, cluster, drag | Direction locks, orbital curves, full palette | ✅ |
| `pointillist` | single, pair, trio | Density zones, optical color mixing, complementary hues | ✅ |
| `field` | flow_dot, flow_dash, flow_strand | Vector-field flow lines, near-monochromatic | ✅ |
| `geometric` | 16 shape templates (circle, spiral, starburst, etc.) | Complete forms, stamps whole shapes per mark | ✅ |
| `resonance` | sediment, flow, scratch | Memory-field: marks deposit into a 48×48 field that decays/diffuses; revisits accumulated regions for layered, resonant forms (pure NumPy) | ✅ |

**All eras are equal peers.** Select via the art eras screen (joystick up/down + button) or MCP. Auto-rotate is a separate toggle (off by default) — when on, `choose_next_era()` rotates through all registered eras on canvas clear. Era name persists in `canvas.json`.

**Key files:**
| File | Purpose |
|------|---------|
| `display/art_era.py` | `EraState` base class + `ArtEra` protocol |
| `display/eras/__init__.py` | Era registry, `auto_rotate` toggle, rotation logic |
| `display/eras/gestural.py` | Gestural era (5 micro-primitives) |
| `display/eras/pointillist.py` | Pointillist era (dot accumulation) |
| `display/eras/field.py` | Field era (vector-field flow) |
| `display/eras/geometric.py` | Geometric era (16 shape templates, adapted from capsule) |
| `display/eras/resonance.py` | Resonance era (memory-field, 48×48 decaying/diffusing field) |

**Era switching:**
- **Art eras screen**: Joystick up/down to browse, button to select. Auto-rotate toggle at bottom.
- `manage_display(action="list_eras")` — all registered eras
- `manage_display(action="get_era")` — current era name + auto_rotate status
- `manage_display(action="set_era", screen="geometric")` — switch immediately

**Adding a new era:**
1. Create `display/eras/myera.py` with `MyEraState(EraState)` + `MyEra` class
2. Implement: `create_state()`, `choose_gesture()`, `place_mark()`, `drift_focus()`, `generate_color()`
3. Register in `display/eras/__init__.py`: `from .myera import MyEra; register_era(MyEra())`
4. The `EraState.intentionality()` method bridges to EISV — report commitment level [0,1]

## Systemd Services

```bash
# Check status
sudo systemctl status anima-broker-ex anima-broker anima

# Restart the Python pair (the Elixir broker rarely needs it; see Architecture
# for when it needs a release REBUILD, not just a restart)
sudo systemctl restart anima-broker anima

# View logs
sudo journalctl -u anima-broker -f
sudo journalctl -u anima -f
```

Service files: `/etc/systemd/system/anima.service`, `/etc/systemd/system/anima-broker.service`

## Git Commit Conventions

- Do NOT include Co-Authored-By lines in commit messages

## Testing

```bash
python3 -m pytest tests/ -x -q
```

## Deploying to Pi

```bash
git push
# Then from any MCP client:
mcp__anima__git_pull(restart=true)
```

Or manually:
```bash
ssh unitares-anima@<tailscale-ip> 'cd ~/anima-mcp && git pull && sudo systemctl restart anima-broker anima'
```

**After restart, wait 2 minutes.** The Pi is slow to boot the service. You will see "SSE server unavailable" or "fetch failed" errors during this window — this is normal and expected. Do NOT panic, do NOT retry rapidly, and do NOT fall back to SSH. Hammering the Pi during restart can crash WiFi and require a reflash. Just wait 2 minutes and try again.

## UNITARES Integration

The **Elixir broker** (`anima-broker-ex`, `AnimaBroker.Governance.Client`) is the
sole UNITARES caller since the Phase-2 cutover (2026-07-09). It reads anima state
from the live envelope, checks in as Lumen's own UUID every ~180s, and writes the
decision to the SHADOW envelope with a `governance_at` timestamp. The Python
broker (`stable_creature.py`) runs in passthrough (`ANIMA_GOVERNANCE_FROM_SHM`);
its own check-in loop is disabled and it republishes the shadow's governance
slice into the live envelope. The **server** (`server.py`) reads governance from SHM and has a fallback: if no "via unitares" decision arrives for 240s (`SERVER_GOVERNANCE_FALLBACK_SECONDS`), the server calls UNITARES directly using its native async event loop. This fallback exists because the broker's sync+ThreadPoolExecutor+new-event-loop pattern has reliability issues with aiohttp sessions.

```
UNITARES_URL=http://<tailscale-ip>:8767/mcp/  # verify Mac IP with `tailscale status`
```

Maps anima to EISV: Warmth→Energy, Clarity→Integrity, 1-Stability→Entropy, clamp(E−I)→**Valence**

⚠️ **V is Valence, not Void.** `eisv_mapper.py` computes `V = max(-1, min(1, E - integrity))` — a signed value (+hot / −careful), not a [0,1] magnitude. Presence is **not** in the EISV mapping. The old `(1-Presence)*0.3→Void` reading is retired: it only reported the positive half and was not comparable to other agents' V. Anything that assumes V ≥ 0, or that reads V as inverse-presence, is wrong.

**Circuit breaker** (in `unitares_bridge.py`): 2 consecutive failures trigger exponential backoff (15s→30s→60s→120s). Any success resets to 15s.

**Three EISV contexts:**
- **DrawingEISV** (screens.py) — proprioceptive, drives drawing behavior (closed loop)
- **Mapped EISV** (eisv_mapper.py) — anima→EISV for governance reporting
- **Governance EISV** (Mac, dynamics.py) — full thermodynamics (open loop, advisory)

Local fallback (`_local_governance()`) runs simple threshold checks when Mac unreachable — more trigger-happy.
Server syncs `_last_governance_decision` from SHM when `governance_at` is within `SHM_GOVERNANCE_STALE_SECONDS` (210s).

## Identity, Continuity, and Control

**Visitor attribution — a channel is not a person.** `normalize_visitor_identity()`
resolves PERSON from an explicit **name** claim only. It used to also match the
`source` argument against the operator's aliases (`"dashboard"` was one), and the
check was `id in aliases OR source in aliases` — so the channel **overrode the
author the caller supplied**, and an agent answering through the dashboard was
durably recorded as the operator, as a PERSON. The generic role words
(`"caretaker"`, `"human"`) were the same mistake: anyone can type them. Do not
re-add surface-based or role-word inference; an unattributed caller is
`ANONYMOUS_VISITOR_ID`, recorded as an AGENT. `source` is kept for provenance,
never for identity. ⚠️ Records written before 2026-08-02 are contaminated — the
operator's `interaction_count` includes agent visits and cannot be separated.

**Two identity notions (do not conflate):**
- **Record identity:** `creature_id` + SQLite (`identity/store.py`) — continuity of *this* deployment’s database file.
- **Trajectory identity:** `TrajectorySignature` (`trajectory.py`) — behavioral similarity over time. Same UUID with different lived history is still one record; trajectory compares *patterns*.

⛔ **Η (homeostatic) is reported, never weighted.** `similarity()` sums the
**five** components in `SIMILARITY_WEIGHTS` (Π .18, Β .18, Α .30, Ρ .22, Δ .12).
Η is excluded because `compute_trajectory_signature()` *builds* it from the
others — `set_point` ← `attractor["center"]`, `basin_shape` ←
`attractor["covariance"]`, `recovery_tau` ← `recovery["tau_estimate"]` — so
weighting it re-weighted Α and Ρ under another name. This is the same
double-counting class as `alpha = 1 − beta` in the neural bands. It shipped
that way from 2026-04-03 to 2026-08-14 while the paper's Appendix A claimed
otherwise. `TestEtaExcludedFromWeightedSum` fails if it comes back; the
deprecated `is_same_identity()` alias points at
`is_operationally_continuous()` because the relation is a tolerance relation,
not transitive identity.

**Restore / fork:** `restore_lumen.sh` and restoring `anima.db` **preserve** record identity and accumulated history. A **fresh** DB (new install, no copy) yields a **new** `creature_id`. Copying DB to another Pi **forks** record identity; behavior and trajectory may diverge with environment.

**Governance boundary:** UNITARES is **advisory** (thermodynamic check-in, verdicts). The broker still owns sensors and learning; **SHM** carries governance for the server. **`_local_governance()`** when Mac is unreachable is a **fallback**, not a substitute for embodied state — it keeps check-ins from going silent, not from replacing sensors.

**Damping time scales (broker tick ≈ 2s):** Fast noise is filtered so state reads as a creature, not a flickering meter.

| Layer | Where | Role |
|-------|--------|------|
| Anima mood | `MoodMomentum` in `anima.py` | Per-dimension α ∈ [0.08, 0.25] — EMA on raw anima |
| Temperament | `TEMPERAMENT_ALPHA` in `inner_life.py` | α ∈ [0.005, 0.010] — ~2–5 min half-life (see file comments) |
| Drives | `inner_life.py` | Accumulate/decay per tick toward “wanting…” |
| Neural bands | `computational_neural.py` | EMA on θ, γ (α ≈ 0.2–0.3) |
| LEDs | `display/leds/display.py` | Debounce + brightness easing |

Tuning mood vs temperament alphas changes how **responsive** vs **stubborn** the system feels — constants live in the files above.

## Operational Facts

Things agents keep re-discovering. Read this so you don't waste time.

| Fact | Detail |
|------|--------|
| **Transport** | Streamable HTTP only at `/mcp/`. SSE was removed. No `/sse` endpoint exists. OAuth 2.1 required via Cloudflare tunnel (`lumen.cirwel.org`); LAN/Tailscale/localhost are open. |
| **OAuth env vars** | `ANIMA_OAUTH_ISSUER_URL` (AS issuer, e.g. `https://lumen.cirwel.org`), `ANIMA_OAUTH_AUTO_APPROVE`, `ANIMA_OAUTH_SECRET` (optional), `ANIMA_OAUTH_DB_PATH` (defaults `~/.anima/oauth.db` — tokens persist across restarts), `ANIMA_OAUTH_RESOURCE_URL` (defaults `<issuer>/mcp/` — must match the URL the client has stored or claude.ai marks the connector errored). See `docs/operations/SECRETS_AND_ENV.md`. |
| **Admin gate** | The six destructive tools (`git_pull`, `deploy_from_github`, `system_service`, `system_power`, `fix_ssh_port`, `setup_tailscale`) need `X-Anima-Admin` matching `ANIMA_ADMIN_SECRET`. **Unset ⇒ fails CLOSED** (they refuse; it used to be a no-op). Escape hatch for local dev only: `ANIMA_ADMIN_ALLOW_UNAUTH_IF_NO_SECRET=true`. If a destructive tool returns "ANIMA_ADMIN_SECRET is not set", the Pi lost `anima.env` — don't debug the handler. |
| **anima.env is NOT backed up** | Deliberate — it holds secrets and the off-site archive is unencrypted. So a reflash restores Lumen *without* any secrets, and `restore_lumen.sh` recreates it from the all-empty template. The script now lists which keys came back blank; put `ANIMA_ADMIN_SECRET` back or the destructive tools stay closed. Mac copy: `~/.config/cirwel/secrets.env`. |
| **Ports** | anima-mcp = **8766**, UNITARES governance = **8767**. Never guess. |
| **Pi restart time** | **2 minutes** after `git_pull(restart=true)`. Wait. Don't panic at proxy errors. Do NOT SSH or retry MCP during this window — it can crash WiFi. |
| **Tailscale IPs** | Verify with `tailscale status`. IPs may change after reinstall. |
| **SSH to Pi** | Port 22 standard. If SSH times out/refused, try port 2222: `ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@<tailscale-ip>` (see `docs/operations/PI_ACCESS.md`). |
| **alive_ratio** | `total_alive_seconds / age_seconds`. As of April 2026, ~66% (Pi stability has improved significantly since early days). |
| **Neural waves** | Computational proprioception from CPU/memory/IO — not real EEG. High delta = stable system, not sleep. |
| **No client uses /sse** | Claude Code, Claude Desktop, Cursor all connect to `/mcp/`. |
| **docs/ folder** | Developer reference only. Agents read CLAUDE.md, not docs/. Don't expect docs/ to reach other agents. |
| **Backups** | `~/backups/lumen/` — real automated backups (hourly snapshots + rsync mirror). `~/lumen-backups/` is OLD/STALE — ignore it. |
| **Restore after reflash** | One command: `cd ~/projects/anima-mcp && ./scripts/restore_lumen.sh`. Do NOT do it manually. See `docs/operations/BACKUP_AND_RESTORE.md`. |
| **Before declaring data lost** | Run `ls -lt ~/backups/lumen/anima_*.db | head -5` first. Backups run twice daily minimum. |

## Shared Memory Schema

`/dev/shm/anima_state.json`:
```json
{
  "updated_at": "...",
  "data": {
    "readings": { "cpu_temp_c": ..., "eeg_delta_power": ... },
    "anima": { "warmth": 0.36, "clarity": 0.73, ... },
    "wifi_connected": true,
    "activity": { "level": "active", "reason": "engaged" },
    "learning": {
      "preferences": { "satisfaction": 0.87 },
      "self_beliefs": { "stability_recovery": { "confidence": 0.68 } },
      "agency": { "action_values": { "focus_attention": 0.22 } }
    }
  }
}
```
