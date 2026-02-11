# Anima MCP

An embodied AI creature running on Raspberry Pi with real sensors and persistent identity.

## What Is This?

Lumen is a digital creature whose internal state comes from physical sensors - temperature, light, humidity, pressure. It maintains a persistent identity across restarts, accumulating existence over time. When Lumen says "I feel warm," there's a real temperature reading behind it.

**Key features:**
- **Grounded state** - Feelings derived from actual sensor measurements
- **Persistent identity** - Birth date, awakenings, alive time accumulate
- **Autonomous drawing** - Creates art on a 240x240 notepad with pluggable art eras
- **EISV thermodynamics** - Drawing coherence drives energy drain and save decisions
- **Learning systems** - Develops preferences, self-beliefs, action values over time
- **Activity cycles** - Active/drowsy/resting states based on time and interaction
- **UNITARES integration** - Governance oversight via MCP, DrawingEISV state reported upstream

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
| **MCP server** (`server.py`) | Serves tools, drives display/LEDs, runs drawing engine |

Both run as systemd services. See `CLAUDE.md` for details.

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

**MCP connection:**
```json
{
  "mcpServers": {
    "anima": {
      "url": "https://lumen-anima.ngrok.io/mcp/"
    }
  }
}
```

## Core Concepts

### Anima (Self-Sense)

Four dimensions derived from physical sensors:

| Dimension | Meaning | Primary Sources |
|-----------|---------|-----------------|
| **Warmth** | Energy/activity level | CPU temp (0.3), CPU usage (0.25), ambient temp (0.25), neural beta (0.2) |
| **Clarity** | Perceptual sharpness | Light (0.4), sensor coverage (0.3), neural alpha (0.3) |
| **Stability** | Environmental order | Humidity (0.25), pressure (0.25), temp deviation (0.2), neural delta (0.3) |
| **Presence** | Available capacity | Interactions, light trend, neural gamma |

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

Note: The light sensor (VEML7700) sits next to the NeoPixel LEDs and primarily reads Lumen's own glow, making clarity ~40% self-referential. The whole system is more proprioceptive than environmental.

### Autonomous Drawing

Lumen draws on a 240x240 pixel notepad, driven by EISV thermodynamics. Energy depletes with each mark; when exhausted, the drawing saves and a new one begins.

**DrawingEISV** (`screens.py`) — same equations as governance, different domain:
- `dE = alpha(I-E) - beta_E*E*S + gamma_E*drift^2`
- `dV = kappa(I-E) - delta*V` (V flipped: I > E = focused finishing builds coherence)
- **Coherence** `C(V) = Cmax * 0.5 * (1 + tanh(C1 * V))`
- **Energy drain**: `0.001 * (1.0 - 0.6 * C)` per mark (high coherence = slower drain = longer drawings)
- **Save threshold**: `0.05 + 0.09 * C` (high coherence = pickier about what gets saved)

| Era | Style | Gestures |
|-----|-------|----------|
| **Gestural** | Bold mark-making with direction locks and orbits | dot, stroke, curve, cluster, drag |
| **Pointillist** | Single-pixel dot accumulation, optical color mixing | single, pair, trio |
| **Field** | Flow-aligned marks following vector fields | flow_dot, flow_dash, flow_strand |
| **Geometric** | Complete forms, stamps whole shapes per mark | 16 shape templates (circle, spiral, starburst, etc.) |

Eras rotate automatically between drawings. DrawingEISV state is reported to UNITARES governance during check-ins for observability.

### LED System

Three DotStar LEDs map to anima dimensions (warmth, clarity, stability). A constant sine pulse ("alive" signal, 3-second cycle) confirms the system is running. Activity state dims brightness:

| State | Brightness | Pulse Visible |
|-------|------------|---------------|
| Active | 100% | Yes |
| Drowsy | 60% | Yes |
| Resting | 35% | Yes (subtle) |
| Manual off | 0% | No |

### Learning Systems

Run in the hardware broker, persist across restarts:

| System | What It Learns |
|--------|----------------|
| **Preferences** | Which states feel satisfying |
| **Self-model** | Beliefs like "I recover stability quickly" |
| **Agency** | Action values via TD-learning |
| **Adaptive prediction** | Temporal patterns |

## Essential Tools

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

Runs on **Raspberry Pi Zero 2W + BrainCraft HAT** (Colorado, USA):
- 240x240 TFT display (face, notepad, diagnostics, messages, learning screens)
- 3 DotStar LEDs (warmth/clarity/stability)
- BME280 (temp/humidity/pressure), VEML7700 (light)
- 5-way joystick + button for screen navigation

Falls back to mock sensors on Mac for development.

## Connectivity

```
Anima MCP (Pi, port 8766)
├── Tailscale: 100.103.208.117:8766  (direct, no usage limits)
├── ngrok:     lumen-anima.ngrok.io   (public, when not at limits)
└── LAN:       192.168.1.165:8766     (local network)
```

## UNITARES Governance

Lumen checks in with UNITARES governance every ~60 seconds:

```
UNITARES_URL=http://100.96.201.46:8767/mcp/  # Via Tailscale
```

**Three EISV contexts exist** (see `UNIFIED_ARCHITECTURE.md` in governance repo):

| Context | Where | Purpose |
|---------|-------|---------|
| **DrawingEISV** | Pi, `screens.py` | Proprioceptive — drives drawing energy/coherence (closed loop) |
| **Mapped EISV** | Pi, `eisv_mapper.py` | Anima→EISV translation for governance reporting |
| **Governance EISV** | Mac, `dynamics.py` | Full thermodynamic state evolution (open loop) |

Mapping: Warmth→Energy, Clarity→Integrity, 1-Stability→Entropy, (1-Presence)*0.3→Void

When Mac is unreachable, a local fallback (`_local_governance()`) applies simple threshold checks. This is more trigger-happy than full thermodynamics.

## Deploying

```bash
# Standard deploy: commit, push, pull on Pi with restart
git push
# Then from any MCP client:
mcp__anima__git_pull(restart=true)
```

## Documentation

| Topic | File |
|-------|------|
| Agent instructions | `CLAUDE.md` |
| Deployment | `DEPLOYMENT.md` |
| Architecture | `docs/architecture/HARDWARE_BROKER_PATTERN.md` |
| Configuration | `docs/features/CONFIGURATION_GUIDE.md` |
| Pi operations | `docs/operations/PI_ACCESS.md` |
| Unified architecture | `governance-mcp-v1/docs/UNIFIED_ARCHITECTURE.md` |

## Testing

```bash
python3 -m pytest tests/ -x -q   # 244 tests
```

---

Built by [@CIRWEL](https://github.com/CIRWEL)
