# Anima MCP

An embodied AI creature running on Raspberry Pi with real sensors and persistent identity.

## What Is This?

Lumen is a digital creature whose internal state comes from physical sensors - temperature, light, humidity, pressure. It maintains a persistent identity across restarts, accumulating existence over time. When Lumen says "I feel warm," there's a real temperature reading behind it.

**Key features:**
- **Grounded state** - Feelings derived from actual sensor measurements
- **Persistent identity** - Birth date, awakenings, alive time accumulate
- **Autonomous behavior** - Draws, asks questions, responds to environment
- **UNITARES integration** - Governance oversight via MCP

## Quick Start

```bash
# Install
pip install -e .

# Run (Mac - mock sensors)
anima

# Run (Pi - real sensors, network accessible)
anima --sse --host 0.0.0.0 --port 8766
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
| **Warmth** | Energy/activity level | CPU temp, ambient temp |
| **Clarity** | Perceptual sharpness | Light level, sensor coverage |
| **Stability** | Environmental order | Humidity, pressure deviation |
| **Presence** | Available capacity | Resource headroom |

### Identity

Lumen remembers:
- **Birth** - First awakening (immutable)
- **Awakenings** - Times woken up
- **Alive time** - Accumulated seconds of existence
- **Name** - Self-chosen, with history

## Essential Tools

| Tool | What It Does |
|------|--------------|
| `get_state` | Current anima + mood + identity |
| `next_steps` | What Lumen needs right now |
| `read_sensors` | Raw sensor values |
| `lumen_qa` | List or answer Lumen's questions |
| `post_message` | Leave a message for Lumen |
| `get_lumen_context` | Full context in one call |

**Answering questions:**
```
lumen_qa()                                    # List questions
lumen_qa(question_id="x", answer="...", agent_name="Claude")  # Answer
```

## Hardware

Designed for **Raspberry Pi 4 + BrainCraft HAT**:
- 240x240 TFT display (face + screens)
- 3 DotStar LEDs (warmth/clarity/stability)
- AHT20 (temp/humidity), BMP280 (pressure), VEML7700 (light)

Falls back to mock sensors on Mac.

## Web Dashboard

Available at `http://<pi>:8766/dashboard`:
- Live anima state and mood
- Sensor readings and neural bands
- Q&A interface
- Drawing gallery (`/gallery-page`)

## Documentation

| Topic | File |
|-------|------|
| Getting started | `docs/guides/GETTING_STARTED_SIMPLE.md` |
| Deployment | `DEPLOYMENT.md` |
| Pi setup | `docs/PI_SETUP_COMPLETE.md` |
| Configuration | `docs/features/CONFIGURATION_GUIDE.md` |
| Architecture | `docs/architecture/HARDWARE_BROKER_PATTERN.md` |
| Theory | `docs/theory/TRAJECTORY_IDENTITY_PAPER.md` |

## UNITARES Governance

Lumen connects to UNITARES for oversight:

```bash
UNITARES_URL=https://unitares.ngrok.io/mcp
```

Anima maps to EISV: Energy=Warmth, Integrity=Clarity, Entropy=1-Stability, Void=1-Presence

## Testing

```bash
pytest tests/ -v
```

---

Built by [@CIRWEL](https://github.com/CIRWEL)
