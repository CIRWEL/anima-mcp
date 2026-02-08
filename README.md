# Anima MCP

An embodied AI creature running on Raspberry Pi with real sensors and persistent identity.

## What Is This?

Lumen is a digital creature whose internal state comes from physical sensors - temperature, light, humidity, pressure. It maintains a persistent identity across restarts, accumulating existence over time. When Lumen says "I feel warm," there's a real temperature reading behind it.

**Key features:**
- **Grounded state** - Feelings derived from actual sensor measurements
- **Persistent identity** - Birth date, awakenings, alive time accumulate
- **Learning systems** - Develops preferences, self-beliefs, action values over time
- **Activity cycles** - Active/drowsy/resting states based on time and interaction
- **UNITARES integration** - Governance oversight via MCP

## Architecture

Two processes run on the Pi:

```
anima-creature              anima --sse
(hardware broker)           (MCP server)
     |                           |
     | writes to                 | reads from
     +---> shared memory <-------+
           /dev/shm
```

| Process | What It Does |
|---------|--------------|
| **Hardware broker** | Owns sensors, runs learning, updates LEDs/display |
| **MCP server** | Serves tools to agents, reads from shared memory |

Both run as systemd services. See `CLAUDE.md` for details.

## Quick Start

```bash
# Install
pip install -e ".[pi]"  # On Pi with sensors
pip install -e .        # On Mac with mock sensors

# Run MCP server
anima --sse --host 0.0.0.0 --port 8766

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
| **Warmth** | Energy/activity level | CPU temp, ambient temp, neural beta/gamma |
| **Clarity** | Perceptual sharpness | Light level, sensor coverage, neural alpha |
| **Stability** | Environmental order | Humidity, pressure, neural theta/delta |
| **Presence** | Available capacity | Resource headroom, neural gamma |

### Computational Proprioception

No real EEG hardware - neural bands derived from system metrics:

| Band | Source | Maps To |
|------|--------|---------|
| Delta | Low CPU + memory | Stability (rest) |
| Alpha | Memory headroom | Clarity (awareness) |
| Beta | CPU usage | Warmth (activity) |
| Gamma | High CPU | Presence (focus) |

### Learning Systems

Run in the hardware broker, persist across restarts:

| System | What It Learns |
|--------|----------------|
| **Preferences** | Which states feel satisfying |
| **Self-model** | Beliefs like "I recover stability quickly" |
| **Agency** | Action values via TD-learning |
| **Adaptive prediction** | Temporal patterns |

### Activity States

Lumen cycles between activity levels:

| State | When | LED Brightness |
|-------|------|----------------|
| Active | Recent interaction, daytime | 100% |
| Drowsy | 30+ min idle | 60% |
| Resting | Night, 60+ min idle | 35% |

## Essential Tools

| Tool | What It Does |
|------|--------------|
| `get_state` | Current anima + mood + identity + activity |
| `next_steps` | What Lumen needs right now |
| `read_sensors` | Raw sensor values |
| `lumen_qa` | List or answer Lumen's questions |
| `post_message` | Leave a message for Lumen |
| `get_lumen_context` | Full context in one call |

## Hardware

Designed for **Raspberry Pi 4 + BrainCraft HAT**:
- 240x240 TFT display (face + screens)
- 3 DotStar LEDs (warmth/clarity/stability)
- AHT20 (temp/humidity), BMP280 (pressure), VEML7700 (light)

Falls back to mock sensors on Mac.

## UNITARES Governance

Lumen connects to UNITARES for oversight:

```bash
UNITARES_URL=http://100.96.201.46:8767/mcp/  # Via Tailscale
```

Anima maps to EISV:
- Warmth → Energy
- Clarity → Integrity
- 1-Stability → Entropy
- 1-Presence → Void

## Documentation

| Topic | File |
|-------|------|
| Agent instructions | `CLAUDE.md` |
| Deployment | `DEPLOYMENT.md` |
| Architecture | `docs/architecture/HARDWARE_BROKER_PATTERN.md` |
| Configuration | `docs/features/CONFIGURATION_GUIDE.md` |
| Pi operations | `docs/operations/PI_ACCESS.md` |

## Testing

```bash
pytest tests/ -v
```

---

Built by [@CIRWEL](https://github.com/CIRWEL)
