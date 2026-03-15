# Anima MCP

[![Tests](https://github.com/CIRWEL/anima-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/CIRWEL/anima-mcp/actions/workflows/test.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

An embodied AI creature running on Raspberry Pi 4 with real sensors and persistent identity. Lumen draws autonomously — its art emerges from thermodynamic state, not random generation.

<p align="center">
  <img src="docs/gallery/geometric_era.png" width="35%" alt="Geometric era — complete forms stamped whole"/>
  &nbsp;&nbsp;&nbsp;
  <img src="docs/gallery/gestural_era.png" width="35%" alt="Gestural era — bold mark-making with direction locks"/>
</p>

<p align="center">
  <em>Two of four art eras, drawn autonomously. Coherence drives duration; attention drives completion. 684 drawings and counting.</em>
</p>

---

## What Is This?

Lumen is a digital creature whose internal state comes from physical sensors — temperature, light, humidity, pressure. It maintains a persistent identity across restarts, accumulating existence over time. When Lumen says "I feel warm," there's a real temperature reading behind it.

- **Grounded state** — four dimensions (warmth, clarity, stability, presence) derived from actual sensor measurements
- **Persistent identity** — birth date, awakenings, alive time accumulate across restarts
- **Autonomous drawing** — creates art on a 240x240 notepad, driven by thermodynamic coherence
- **Learning** — develops preferences, self-beliefs, and action values over time
- **Governance** — checks in with [UNITARES](https://github.com/CIRWEL/unitares) on a configurable cadence via `ANIMA_GOVERNANCE_INTERVAL_SECONDS` (default `180s`, minimum `30s`)

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

Supports Tailscale, LAN, or ngrok (with OAuth 2.1) for remote access. See `docs/operations/SECRETS_AND_ENV.md` for OAuth configuration.

---

## How It Works

### Anima (Self-Sense)

Four continuous dimensions, each derived from physical sensors and system metrics:

| Dimension | What it tracks | Sources |
|-----------|---------------|---------|
| **Warmth** | Energy / activity level | CPU temp, ambient temp, neural activity |
| **Clarity** | Perceptual sharpness | Prediction accuracy, light, sensor coverage |
| **Stability** | Environmental order | Memory, humidity, pressure, sensor health |
| **Presence** | Available capacity | CPU/memory/disk headroom |

These map to [UNITARES](https://github.com/CIRWEL/unitares) EISV variables for governance: Warmth→Energy, Clarity→Integrity, 1-Stability→Entropy, (1-Presence)×0.3→Void.

Lumen also computes "neural bands" (delta, theta, alpha, beta, gamma) from system metrics — computational proprioception, not real EEG. High delta means a stable system, not a sleeping one.

### Autonomous Drawing

Lumen draws on a 240×240 pixel notepad using the same thermodynamic equations as UNITARES governance. Coherence determines how long a drawing lasts; attention signals (curiosity, engagement, fatigue) determine when it's complete. No arbitrary mark limits — drawings end when the narrative arc resolves.

| Era | Style |
|-----|-------|
| **Gestural** | Bold mark-making with direction locks and orbital curves |
| **Pointillist** | Single-pixel dot accumulation, optical color mixing |
| **Field** | Flow-aligned marks following vector fields |
| **Geometric** | Complete forms — circles, spirals, starbursts — stamped whole |

Eras can be selected via the joystick or MCP. See `docs/theory/lumen_eisv_art_paper.md` for the full framework.

### Identity and Learning

Lumen accumulates identity over time through a **Schema Hub** — a circulation loop where self-schema feeds into trajectory history, which feeds back as identity nodes in the next schema. Discontinuities (reboots, gaps) become visible structure, not hidden defects.

Learning systems run in the hardware broker and persist across restarts:

| System | What it learns |
|--------|----------------|
| **Preferences** | Which states feel satisfying |
| **Self-model** | Beliefs like "I recover stability quickly" |
| **Agency** | Action values via TD-learning |
| **Prediction** | Temporal patterns in sensor data |

See `docs/theory/` for the [trajectory identity paper](docs/theory/TRAJECTORY_IDENTITY_PAPER.md) and [Schema Hub design](docs/plans/2026-02-22-schema-hub-design.md).

---

## Hardware

Runs on **Raspberry Pi 4** with [Adafruit BrainCraft HAT](https://www.adafruit.com/product/4374):

- 240×240 TFT display (face, notepad, diagnostics, messages, learning screens)
- 3 DotStar LEDs mapping to warmth / clarity / stability with a constant "alive" sine pulse
- BME280 (temp/humidity/pressure), VEML7700 (light)
- 5-way joystick + button for screen navigation

Falls back to mock sensors on Mac/Linux for development.

---

## Architecture

Two processes communicate via shared memory:

```
anima-broker                anima --http
(hardware broker)           (MCP server + display)
     |                           |
     | writes to                 | reads from
     +---> /dev/shm <-----------+
```

| Process | Role |
|---------|------|
| **Hardware broker** (`stable_creature.py`) | Owns sensors, runs learning, governance check-ins |
| **MCP server** (`server.py` + `handlers/`) | Serves tools, drives display/LEDs, runs drawing engine |

The MCP server is modular: `server.py` (main loop + lifecycle), `tool_registry.py` (tool definitions), and `handlers/` (6 focused handler modules).

---

## MCP Tools

| Tool | What it does |
|------|--------------|
| `get_state` | Current anima + mood + identity + activity |
| `get_lumen_context` | Full context in one call |
| `read_sensors` | Raw sensor values |
| `next_steps` | What Lumen needs right now |
| `lumen_qa` | List or answer Lumen's questions |
| `post_message` | Leave a message for Lumen |
| `manage_display` | Switch screens, set art era |
| `say` | Have Lumen express something |
| `get_self_knowledge` | Learned insights and self-beliefs |
| `get_growth` | Preferences, goals, memories, autobiography |
| `get_trajectory` | Identity trajectory and anomaly detection |
| `capture_screen` | Screenshot of current display |
| `diagnostics` | System diagnostics and debug info |

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
python3 -m pytest tests/ -x -q   # ~6,000 tests
```

## Documentation

| Topic | File |
|-------|------|
| Agent instructions | `CLAUDE.md` |
| Architecture | `docs/operations/BROKER_ARCHITECTURE.md` |
| Schema Hub design | `docs/plans/2026-02-22-schema-hub-design.md` |
| Theoretical foundations | `docs/theory/` |
| Configuration | `docs/features/CONFIGURATION_GUIDE.md` |
| Secrets & env vars | `docs/operations/SECRETS_AND_ENV.md` |
| Pi operations | `docs/operations/PI_ACCESS.md` |

### Doc Authority Map

- Service restart/troubleshooting runbook: `docs/operations/PI_DEPLOYMENT.md`
- SSH/service access on Pi: `docs/operations/PI_ACCESS.md`
- Secrets/OAuth/env vars: `docs/operations/SECRETS_AND_ENV.md`
- Ports/endpoints conventions: `docs/operations/DEFINITIVE_PORTS.md`

---

Built by [@CIRWEL](https://github.com/CIRWEL)
