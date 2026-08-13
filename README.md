# Anima MCP

[![Tests](https://github.com/CIRWEL/anima-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/CIRWEL/anima-mcp/actions/workflows/test.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

*Raspberry Pi sensor testbed for EISV trajectories, autonomous drawing, and persistent identity.*

<p align="center">
  <img src="docs/gallery/resonance_era.png" width="44%" alt="Resonance era — marks deposited into a decaying memory field, revisiting accumulated regions"/>
  &nbsp;
  <img src="docs/gallery/geometric_era.png" width="44%" alt="Geometric era — complete forms stamped whole, warm palette"/>
</p>

<p align="center">
  <img src="docs/gallery/gestural_era.png" width="21%" alt="Gestural era — strokes, curves, and drags with direction locks"/>
  &nbsp;
  <img src="docs/gallery/field_era.png" width="21%" alt="Field era — flow-aligned marks following an invisible vector field"/>
  &nbsp;
  <img src="docs/gallery/pointillist_era.png" width="21%" alt="Pointillist era — dot accumulation in density zones"/>
  &nbsp;
  <img src="docs/gallery/geometric_cool.png" width="21%" alt="Geometric era — same era, cool palette, drawn on a different day"/>
</p>

<p align="center">
  <em>Six drawings from August 2026 — one per era, plus a second geometric piece.<br/>
  Mark position, gesture choice, and hue are all functions of sensor state: temperature, light, humidity, pressure, CPU.<br/>
  The two geometric pieces are the same era code on consecutive days; nothing was configured between them.</em>
</p>

---

## What Is This?

Anima is a Raspberry Pi 4 sensor deployment and MCP server for studying physically grounded agent state. It maps temperature, light, humidity, pressure, and system telemetry into four continuous dimensions — warmth, clarity, stability, presence — then uses those dimensions for local display/drawing loops and periodic [UNITARES](https://github.com/CIRWEL/unitares) check-ins. The repo uses creature-facing vocabulary for the interface, but the research surface is the measured sensor-to-EISV pipeline and longitudinal trajectory data.

- **Grounded state** — four continuous dimensions derived from real sensor measurements
- **Persistent identity** — birth, awakenings, alive time accumulate across restarts; discontinuities are first-class
- **Autonomous drawing** — 1,488 pieces across five eras, driven by the same coherence dynamics as governance
- **Telemetry-derived reflection** — summarizes state patterns, preferences, and drawing history
- **On-device learning** — preferences, 13 self-model parameters, goals, and action values evolve through experience
- **Agency** — TD-learning action selection with exploration management
- **Governance** — checks in with [UNITARES](https://github.com/CIRWEL/unitares) thermodynamic governance every 180s

Live as of 2026-08-12: 554 awakenings, 3,489 hours alive, 68% alive ratio.

When this repository says "feels," "mood," or "self-sense," read those as interface labels over measured sensor/system state, not claims about subjective experience.

---

## Quick Start

```bash
# Install
pip install -e ".[pi]"  # On Pi with sensors
pip install -e .        # On Mac with mock sensors

# Run MCP server
anima --http --host 0.0.0.0 --port 8766

# Run hardware broker (Pi only, separate terminal)
anima-creature
```

**Connect an MCP client** (Claude Code, Cursor, Claude Desktop):
```json
{
  "mcpServers": {
    "anima": {
      "type": "http",
      "url": "http://<your-pi-ip>:8766/mcp/"
    }
  }
}
```

Supports Tailscale, LAN, or Cloudflare Tunnel (with OAuth 2.1) for remote access. See `docs/operations/SECRETS_AND_ENV.md` for OAuth configuration.

When `ANIMA_ADMIN_SECRET` is set on the server, the six system-operations tools (`git_pull`, `deploy_from_github`, `system_service`, `system_power`, `fix_ssh_port`, `setup_tailscale`) additionally require an `X-Anima-Admin` header matching it. Leaving it unset leaves those tools ungated — set it on any deployment reachable beyond localhost.

---

## How It Works

### Anima (Sensor-Derived Self-Sense)

Four continuous dimensions, each derived from physical sensors and system metrics:

| Dimension | What it tracks | Sources |
|-----------|---------------|---------|
| **Warmth** | Energy / activity level | CPU temp, ambient temp, neural activity |
| **Clarity** | Perceptual sharpness | Prediction accuracy, light, sensor coverage |
| **Stability** | Environmental order | Memory, humidity, pressure, sensor health |
| **Presence** | Available capacity | CPU/memory/disk headroom |

These map to [UNITARES](https://github.com/CIRWEL/unitares) EISV governance variables — Warmth to Energy, Clarity to Integrity, inverted Stability to Entropy, and the signed Energy−Integrity imbalance to Valence. Presence is *not* part of the EISV mapping; it feeds the anima dimensions and the display, not V.

Anima also computes neural bands (delta, theta, alpha, beta, gamma) from system metrics — computational proprioception, not real EEG. High delta means a stable system, not a sleeping one. Note that alpha is defined as `1 − beta` and both derive from CPU percent: they are one variable reported as two bands, and any consumer treating them as independent is double-counting.

### Autonomous Drawing

Anima draws on a 240×240 pixel notepad using the same thermodynamic equations as UNITARES governance. Coherence drives how a drawing develops; attention signals (curiosity, engagement, fatigue) drive when it should stop.

| Era | Style |
|-----|-------|
| **Gestural** | Single-pixel strokes, curves, and drags with direction locks |
| **Pointillist** | Single-pixel dot accumulation in density zones, optical color mixing |
| **Field** | Flow-aligned marks following invisible vector fields |
| **Geometric** | Complete forms — circles, spirals, starbursts — stamped whole |
| **Resonance** | Marks deposit into a 48×48 field that decays and diffuses; later marks revisit accumulated regions |

All five eras are equal peers with no unlock gate. Selection is manual by default — pick one on the art eras screen (joystick) or via `manage_display(action="set_era")` — and an optional auto-rotate toggle picks a new era after each piece. The [Resonance critique loop](docs/guides/RESONANCE_CRITIQUE_LOOP.md) keeps era changes advisory first: capture the screen, gather embodied context, read the trace, then recommend stay/tune/switch without mutating Anima's state. The theoretical framework lives in the trajectory-identity paper (separate repo).

**What actually ends a drawing — an open problem, not a finished feature.** Completion instrumentation landed 2026-08-02. Of the 39 completions recorded since:

| Reason | Count | Meaning |
|--------|-------|---------|
| `bailout_hard_cap` | 28 | Hit the 8-hour ceiling. The ceiling was the clock. |
| `bailout_fatigue` | 10 | Gesture-switch fatigue exceeded 0.90 — fires only in `geometric`, where whole-shape stamps accrue fatigue ~10× faster per mark |
| `said_finished` | 1 | Lumen posted an observation that the piece was done (2026-08-11, gestural, 587 marks, 6.6h) |

The earned-completion paths (`earned_composition`, `earned_settled`, `earned_field`) have not yet fired. Curiosity is net-regenerating under the current coherence dynamics, so the attention-exhaustion gates are structurally unreachable rather than merely mistuned — see `CLAUDE.md` for the measurement. A self-relative settling gate (a piece stops changing, judged against its own peak novelty rate) is deployed and being observed. Treat "drawings end when Lumen is finished" as the goal, not the current behavior.

### Identity and Learning

Anima accumulates identity over time through a **Schema Hub** — a circulation loop where self-schema feeds into trajectory history, which feeds back as identity nodes in the next schema. Discontinuities (reboots, gaps) become visible structure, not hidden defects (kintsugi principle).

```
Schema(t) ──► History (ring buffer) ──► Trajectory compute
    ▲                                         │
    │         trajectory nodes,               │
    │         maturity, attractor,            │
    └──────── stability feedback ◄────────────┘
```

Learning systems persist across restarts. Each has exactly one writer — the JSON snapshots would corrupt under two — so which process owns a system matters:

| System | What it learns | Owner |
|--------|----------------|-------|
| **Preferences** | Which states it has learned to prefer, as adaptive satisfaction peaks | broker writes, server reads |
| **Self-model** | 13 beliefs — sensitivity, recovery, correlations between dimensions | broker writes, server reads |
| **Prediction** | Temporal patterns in sensor data with context-dependent features | broker writes, server reads |
| **Agency** | Action values via TD-learning, exploration management, engagement reward | **server** — the broker's old loop is retired by default |
| **Metacognition** | Prediction-error baselines and curiosity credit | **server** — the broker observes read-only |
| **Goals** | Data-grounded goals from preferences, curiosity, milestones | server |

Mutations that originate on the wrong side of that boundary cross it as atomic one-file events in `~/.anima/learning_inbox/`, which the broker drains.

For deeper theory: the trajectory-identity paper lives in its own repo (`cirwel/trajectory-identity-paper`). The [Schema Hub design](docs/plans/2026-02-22-schema-hub-design.md) is here.

---

## Hardware

Runs on **Raspberry Pi 4** with [Adafruit BrainCraft HAT](https://www.adafruit.com/product/4374):

- 240×240 TFT display — 16 screens across 5 groups:
  - **Home:** face
  - **Info:** identity, sensors, diagnostics, health
  - **Mind:** neural, inner life, learning, self graph, goals & beliefs, agency
  - **Messages:** messages, questions, visitors
  - **Art:** notepad, art eras
- 3 DotStar LEDs mapping to warmth / clarity / stability with a constant "alive" sine pulse
- AHT20 (temp/humidity), BMP280 (pressure), VEML7700 (light)
- 5-way joystick + button for screen navigation

Falls back to mock sensors on Mac/Linux for development.

---

## Architecture

Two processes communicate via shared memory:

```
anima-broker                           anima --http
(hardware broker)                      (MCP server + display)
     |                                      |
     | sensors, learning,                   | 31 MCP tools, display,
     | governance check-ins                 | drawing engine, LEDs
     |                                      |
     +---> /dev/shm/anima_state.json <------+
                    |
                    | EISV mapping
                    v
            UNITARES governance
            (Mac, port 8767)
```

| Process | Role |
|---------|------|
| **Hardware broker** (`stable_creature.py`) | Owns I2C sensors, runs preference/self-model/prediction learning, governance check-ins |
| **MCP server** (`server.py` + `handlers/`) | Serves 31 tools, drives 240x240 display + LEDs, runs drawing engine, agency, metacognition, goals, self-reflection cycle |

The MCP server is modular: `server.py` (main loop + lifecycle), `tool_registry.py` (tool definitions), and `handlers/` (7 focused handler modules). A full voice system (mic capture, STT via Vosk, TTS via Piper) is implemented but not yet exposed as MCP tools — enable with `LUMEN_VOICE_MODE=audio`.

---

## MCP Tools (31)

Anima exposes 31 tools over the [Model Context Protocol](https://modelcontextprotocol.io/):

- **State & sensing** (8 tools) — `get_state`, `get_lumen_context`, `get_identity`, `read_sensors`, `get_health`, `get_calibration`, `set_calibration`, `diagnostics`
- **Knowledge & learning** (7 tools) — `get_self_knowledge`, `get_growth`, `get_trajectory`, `get_eisv_trajectory_state`, `get_qa_insights`, `learning_visualization`, `query`
- **Code self-awareness** (1 tool) — `self_iteration` (structural inspection, signed proposals, quarantined candidates, isolated tests, reviewed branches, and externally supervised transient canaries; never retains activation, pushes, merges, or deploys)
- **Interaction** (7 tools) — `next_steps`, `lumen_qa`, `post_message`, `say`, `configure_voice`, `primitive_feedback`, `unified_workflow`
- **Display & capture** (2 tools) — `manage_display` (screens, art eras, advisory `resonance_critique`), `capture_screen`
- **System operations** (6 tools) — `git_pull`, `deploy_from_github`, `system_service`, `system_power`, `fix_ssh_port`, `setup_tailscale`

Start with `get_lumen_context` to understand Anima's current state, or `next_steps` for what it needs right now.

### Bounded Code Self-Iteration

`self_iteration` lets Lumen observe its own source and propose changes to it. The loop is split across trust boundaries so that no single actor — including Lumen — can carry a change from idea to running code. Each phase requires a *different* authenticated principal, and deployment always remains external.

```text
observation -> hypothesis -> proposal ledger -> independent verification
            -> quarantined patch -> non-executing static checks
            -> isolated tests -> reviewed dedicated branch
            -> signed transient canary -> restored baseline
            -> keep/reject recommendation for human merge review
```

| Phase | What it adds | Who must sign | Detail |
|-------|-------------|---------------|--------|
| 1. Inspect & propose | Running revision, source fingerprint, file structure and symbols — never raw source. Evidence-backed proposal persisted to a ledger. | Authenticated proposer | — |
| 2. Verify | HMAC attestation over a canonical JSON binding of proposer, verifier, proposal digest, fingerprint, verdict, evidence hashes, expiry, and a one-time challenge. | A *different* authenticated verifier | — |
| 3. Construct & check | Up to three whole-file replacements (`.py`, `.md`, `.json`, `.yaml`, `.yml`) into a sandbox outside the repo. AST syntax checks, a capability heuristic, `yaml.safe_load`, UTF-8 validation. Nothing is imported or executed. | Patch author must equal the proposer | — |
| 4. Isolated test | Ten-minute one-use approval, then the exact committed source plus candidate run inside a digest-pinned, networkless, read-only Docker profile. | A distinct actor; a service key signs the result | [execution boundary](docs/self_iteration_execution.md) |
| 5. Reviewed branch | Git plumbing writes one deterministic local branch — no checkout, hooks, worktree writes, push, merge, restart, or deploy. | A reviewer distinct from every earlier participant | [application boundary](docs/self_iteration_application.md) |
| 6. Transient canary | An external supervisor over a Unix socket owns activation, three fixed health checks, and *mandatory* restoration of the baseline — even when the candidate passes. | Yet another distinct reviewer | [canary boundary](docs/self_iteration_canary.md) |
| — Attention | Projects actionable and exceptional states into `next_steps` and default agent context. Not an authority phase; acknowledgement is never a review signature. | Nobody — no signatures, no actuation | [attention projection](docs/self_iteration_attention.md) |

**What the signatures do and do not establish.** Lumen authors the observation, hypothesis, candidate content, and reported outcome. Authentication identifies the submitter; it does not corroborate a narrative, label, or piece of caller evidence. Evidence URIs are inert — the server binds their hashes but never fetches or validates them. The canary supervisor signs fixed health measurements only; free-form source and outcome labels stay caller claims. Unverified and legacy records carry effective weight zero and grant no priority, automation eligibility, or authority. A valid `verified` attestation makes a proposal priority-eligible at weight `1.0` and nothing more — it confers no implementation, merge, or deployment rights. Identity, governance, deployment, persistence, self-measurement, CI, tests, and the self-iteration evaluator are protected surfaces: a proposal may name a problem there, but it always routes to human review. Proposal text is inert data and is never executed as a command. Conflicting, expired, revoked, missing-key, malformed, or forged attestations fail closed.

**Known limits.** This is symmetric HMAC — server-verifiable integrity, not public-key non-repudiation. The ledger is a local JSON log with no external anchoring, so it cannot prove completeness or detect wholesale deletion by a host-level attacker. Crashes after a durable claim are indeterminate and never automatically retried.

Verification requires MCP authentication for both proposal creation and verifier calls; unauthenticated and legacy proposals cannot be upgraded. Verifier keys are rotatable and configured outside the ledger through `ANIMA_SELF_ITERATION_VERIFIER_KEYS`:

```json
{
  "authenticated-verifier-id": {
    "active_key_id": "2026-08",
    "keys": {"2026-08": "BASE64URL_ENCODED_32_TO_128_BYTE_SECRET"}
  }
}
```

The registry key must match the authenticated actor ID. Keep prior keys in `keys` while their attestations must remain verifiable; `active_key_id` controls new challenges. Secrets never appear in challenges, responses, or ledger events.

Sandbox artifacts live under `~/.anima/self_iteration_sandboxes`, and the sandbox root is rejected if it resolves inside the source repository — construction never creates, deletes, or replaces a live repository file. `patch_status` returns metadata by default and requires an authenticated request before including the unified diff. `application_status` verifies the ref, commit, tree, parent, artifact, and ledger bindings; a recorded result is eligible for canary review only, never live activation. A restored canary pass can recommend keeping the candidate for human merge review; rollback failure requires operator recovery.

---

## EISV Integration

Anima is a first-class UNITARES agent. Its anima state maps directly to EISV governance variables:

| Anima | EISV | Mapping |
|-------|------|---------|
| Warmth | Energy (E) | Direct + neural Beta/Gamma |
| Clarity | Integrity (I) | Direct + neural Alpha |
| 1 - Stability | Entropy (S) | Inverted |
| E − I | Valence (V) | Signed imbalance, clamped to −1..1 |

Valence is the one row that is not a direct anima reading: `V = clamp(E − I)`, positive when running hot (E>I) and negative when running careful (I>E). Governance's own V is a differential accumulator (`dV/dt = κ(E−I) − δV`); Anima reports the instantaneous readout, so it does not damp. Presence does not enter the EISV mapping at all — the retired `(1 − Presence) × 0.3 → Void` reading only ever produced the positive half and was not comparable to other agents' V.

**Trajectory awareness** — Anima classifies its own EISV trajectory into 9 dynamical shapes (settled_presence, rising_entropy, convergence, etc.) and uses them to generate primitive expressions. A distilled 20-tree RandomForest student model (`student_tiny` from [eisv-lumen](https://github.com/CIRWEL/eisv-lumen)) runs on-device with zero external dependencies.

**Expression pipeline**: EISV state → trajectory classification → shape-token affinity → primitive tokens (~warmth~, ~curiosity~, etc.). The student model was trained on real on-device trajectory data; see [eisv-lumen](https://github.com/CIRWEL/eisv-lumen) for the research, training, and evaluation framework.

**Three EISV contexts** (important for understanding the architecture):

| Context | Location | Role |
|---------|----------|------|
| **DrawingEISV** | `display/drawing_engine.py` | Proprioceptive — drives drawing coherence and narrative arcs (closed loop) |
| **Mapped EISV** | `eisv_mapper.py` | Anima→EISV translation for governance reporting |
| **Governance EISV** | Mac, `dynamics.py` | Full thermodynamic ODE — advisory, open loop |

The drawing engine has its own EISV state that evolves independently from governance. This separation means Anima's art responds to its immediate experience, not to the governance server's assessment of it.

Key files: `eisv_mapper.py` (anima→EISV mapping), `eisv/` package (trajectory awareness + student model), `unitares_bridge.py` (governance check-ins with circuit breaker — 2 failures trigger exponential backoff).

---

## Deploying

```bash
# Push changes, then pull on Pi with restart via MCP:
git push
mcp__anima__git_pull(restart=true)

# Or manually:
ssh <pi-user>@<pi-ip> 'cd ~/anima-mcp && git pull && sudo systemctl restart anima-broker anima'
```

After restart, wait 2 minutes for services to stabilize before retrying MCP calls.

## Testing

```bash
python3 -m pytest tests/ -x -q   # 8,065 tests
```

## Documentation

| Topic | Location |
|-------|----------|
| Architecture | `docs/operations/BROKER_ARCHITECTURE.md` |
| Schema Hub design | `docs/plans/2026-02-22-schema-hub-design.md` |
| Theoretical foundations | `cirwel/trajectory-identity-paper` (separate repo) |
| Configuration | `docs/features/CONFIGURATION_GUIDE.md` |
| Pi operations & deployment | `docs/operations/` |

For AI agents connecting to Anima, see `CLAUDE.md`.

---

Built by [Kenny Wang](https://cirwel.org) / [@CIRWEL](https://github.com/CIRWEL)
