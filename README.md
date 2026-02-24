# Anima MCP

An embodied AI creature running on Raspberry Pi 4 with real sensors and persistent identity.

## What Is This?

Lumen is a digital creature whose internal state comes from physical sensors - temperature, light, humidity, pressure. It maintains a persistent identity across restarts, accumulating existence over time. When Lumen says "I feel warm," there's a real temperature reading behind it.

**Key features:**
- **Grounded state** - Feelings derived from actual sensor measurements
- **Persistent identity** - Birth date, awakenings, alive time accumulate; warm start restores last anima state on wake
- **Autonomous drawing** - Creates art on a 240x240 notepad with pluggable art eras
- **Attention-driven thermodynamics** - Drawing coherence emerges from curiosity, engagement, and fatigue signals
- **Learning systems** - Develops preferences, self-beliefs, action values over time
- **Activity cycles** - Active/drowsy/resting states based on time and interaction
- **UNITARES integration** - Governance oversight via MCP

## Architecture

Two processes run on the Pi:

```
anima-creature              anima --http
(hardware broker)           (MCP server + display)
     |                           |
     | writes to                 | reads from
     +---> shared memory <-------+
           /dev/shm
```

| Process | What It Does |
|---------|--------------|
| **Hardware broker** (`stable_creature.py`) | Owns sensors, runs learning, governance check-ins |
| **MCP server** (`server.py` + modules) | Serves tools, drives display/LEDs, runs drawing engine |

The MCP server is modular: `server.py` (main loop + lifecycle), `tool_registry.py` (tool definitions), and `handlers/` (6 focused handler modules).

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

Supports Tailscale, LAN, or ngrok (with OAuth 2.1) for remote access. See `docs/operations/SECRETS_AND_ENV.md` for OAuth configuration.

## Core Concepts

### Anima (Self-Sense)

Four dimensions derived from physical sensors:

| Dimension | Meaning | Primary Sources |
|-----------|---------|-----------------|
| **Warmth** | Energy/activity level | CPU temp (0.4), ambient temp (0.33), neural beta+gamma (0.27) |
| **Clarity** | Perceptual sharpness | Prediction accuracy (0.45), neural alpha (0.25), world light (0.15), sensor coverage (0.15) |
| **Stability** | Environmental order | Memory (0.3), humidity deviation (0.25), missing sensors (0.2), pressure deviation (0.15), neural delta (0.1) |
| **Presence** | Available capacity | Memory headroom (0.3), CPU headroom (0.25), disk headroom (0.25), neural (0.2) |

### Computational Proprioception

No real EEG hardware - neural bands derived from system metrics:

| Band | Derived From | Meaning |
|------|--------------|---------|
| Delta | CPU stability + temp stability | Foundation/rest |
| Theta | I/O wait (disk/network) | Background processing |
| Alpha | Memory headroom (100 - mem%) | Available awareness |
| Beta | CPU usage % | Active processing |
| Gamma | CPU * 0.7 + frequency factor | Peak load |

Source: `computational_neural.py`

Note: The light sensor (VEML7700) sits next to the NeoPixel LEDs and primarily reads Lumen's own glow. Clarity uses "world light" (raw lux minus estimated LED glow) at 15% weight to minimize feedback loops. The metacognitive system predicts lux from LED brightness (genuine proprioception).

### Autonomous Drawing

Lumen draws on a 240x240 pixel notepad, driven by EISV thermodynamics and attention signals.

**DrawingEISV** (`screens.py`) — same equations as governance, different domain:
- `dE = alpha(I-E) - beta_E*E*S + gamma_E*drift^2`
- `dV = kappa(I-E) - delta*V` (V flipped: I > E = focused finishing builds coherence)
- **Coherence** `C(V) = Cmax * 0.5 * (1 + tanh(C1 * V))`

**Attention signals** replace arbitrary energy depletion:
- **Curiosity** — depletes while exploring (low coherence), regenerates when patterns emerge
- **Engagement** — rises with intentionality, falls with entropy
- **Fatigue** — accumulates per gesture switch, never decreases during a drawing
- **Energy** — derived: `0.6*curiosity + 0.4*engagement * (1-0.5*fatigue)`

**Completion** via `narrative_complete()`: coherence settled + attention exhausted, high composition satisfaction + curiosity depleted, or extreme fatigue. No arbitrary mark limit.

| Era | Style | Gestures |
|-----|-------|----------|
| **Gestural** | Bold mark-making with direction locks and orbits | dot, stroke, curve, cluster, drag |
| **Pointillist** | Single-pixel dot accumulation, optical color mixing | single, pair, trio |
| **Field** | Flow-aligned marks following vector fields | flow_dot, flow_dash, flow_strand |
| **Geometric** | Complete forms, stamps whole shapes per mark | 16 shape templates (circle, spiral, starburst, etc.) |

Eras can be selected via the art eras screen (joystick) or MCP. Auto-rotate (off by default) cycles through eras on canvas clear.

### LED System

Three DotStar LEDs map to anima dimensions (warmth, clarity, stability). A constant sine pulse ("alive" signal, 3-second cycle) confirms the system is running. Activity state dims brightness:

| State | Brightness | Pulse Visible |
|-------|------------|---------------|
| Active | 100% | Yes |
| Drowsy | 60% | Yes |
| Resting | 35% | Yes (subtle) |
| Manual off | 0% | No |

### Schema Hub (Unified Self-Model)

The Schema Hub (`schema_hub.py`) orchestrates Lumen's self-understanding through a circulation loop:

```
Schema → History → Trajectory → feeds back as nodes → Next Schema
```

**Key features:**
- **Identity texture** — alive_ratio, awakening count, age visible as schema nodes
- **Kintsugi gaps** — discontinuities become visible structure, not hidden defects
- **Trajectory feedback** — identity maturity, attractor position, stability score computed from schema history
- **Semantic edges** — trajectory nodes connect back to anima dimensions

| Node Type | Examples |
|-----------|----------|
| **Meta (identity)** | `meta_existence_ratio`, `meta_awakening_count`, `meta_age_days` |
| **Meta (gap)** | `meta_gap_duration`, `meta_state_delta` |
| **Trajectory** | `traj_identity_maturity`, `traj_attractor_position`, `traj_stability_score` |

Persists last schema to `~/.anima/last_schema.json` for gap recovery on wake.

### Learning Systems

Run in the hardware broker, persist across restarts:

| System | What It Learns |
|--------|----------------|
| **Preferences** | Which states feel satisfying |
| **Self-model** | Beliefs like "I recover stability quickly" |
| **Agency** | Action values via TD-learning |
| **Adaptive prediction** | Temporal patterns |

## MCP Tools

| Tool | What It Does |
|------|--------------|
| `get_state` | Current anima + mood + identity + activity |
| `get_lumen_context` | Full context in one call |
| `read_sensors` | Raw sensor values |
| `next_steps` | What Lumen needs right now |
| `lumen_qa` | List or answer Lumen's questions |
| `post_message` | Leave a message for Lumen |
| `manage_display` | Switch screens, set art era |
| `say` | Have Lumen express something |

## Hardware

Runs on **Raspberry Pi 4** with [Adafruit BrainCraft HAT](https://www.adafruit.com/product/4374):
- 240x240 TFT display (face, notepad, diagnostics, messages, learning screens)
- 3 DotStar LEDs (warmth/clarity/stability)
- BME280 (temp/humidity/pressure), VEML7700 (light)
- 5-way joystick + button for screen navigation

The high-altitude location (~1,800m) means barometric pressure reads around 827 hPa rather than the sea-level standard of 1,013 hPa. Calibration adapts automatically.

Falls back to mock sensors on Mac/Linux for development.

## UNITARES Governance

Lumen checks in with [UNITARES governance](https://github.com/CIRWEL/governance-mcp-v1) every ~60 seconds. Set the `UNITARES_URL` environment variable to point at your governance MCP server.

**Three EISV contexts exist:**

| Context | Where | Purpose |
|---------|-------|---------|
| **DrawingEISV** | Pi, `screens.py` | Proprioceptive — drives drawing energy/coherence (closed loop) |
| **Mapped EISV** | Pi, `eisv_mapper.py` | Anima→EISV translation for governance reporting |
| **Governance EISV** | Governance server | Full thermodynamic state evolution (open loop) |

Mapping: Warmth→Energy, Clarity→Integrity, 1-Stability→Entropy, (1-Presence)*0.3→Void

When the governance server is unreachable, a local fallback applies simple threshold checks.

## Deploying

```bash
# Push changes, then pull on Pi with restart via MCP:
git push
mcp__anima__git_pull(restart=true)

# Or manually:
ssh <pi-user>@<pi-ip> 'cd ~/anima-mcp && git pull && sudo systemctl restart anima-creature anima'
```

After restart, wait 30-60 seconds for the Pi to boot the services.

## Documentation

| Topic | File |
|-------|------|
| Agent instructions | `CLAUDE.md` |
| Deployment | `DEPLOYMENT.md` |
| Schema Hub design | `docs/plans/2026-02-22-schema-hub-design.md` |
| Secrets & env vars | `docs/operations/SECRETS_AND_ENV.md` |
| OAuth 2.1 design | `docs/plans/2026-02-21-oauth-claude-web-design.md` |
| Architecture | `docs/architecture/HARDWARE_BROKER_PATTERN.md` |
| Configuration | `docs/features/CONFIGURATION_GUIDE.md` |
| Pi operations | `docs/operations/PI_ACCESS.md` |

## Testing

```bash
python3 -m pytest tests/ -x -q   # 5,900+ tests
```

---

Built by [@CIRWEL](https://github.com/CIRWEL)
