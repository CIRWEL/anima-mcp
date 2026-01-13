# Anima MCP

A persistent Pi creature with grounded self-sense.

**One creature. One identity. Real sensors. Real presence.**

## Agent Coordination

**Active Agents:** Claude + Cursor/Composer  
**Coordination:** See `docs/AGENT_COORDINATION.md`  
**Note:** Always check docs/ and KG before implementing changes.

## What is Anima?

*Anima* (Latin: soul, spirit, animating force) - the felt sense of being alive.

This creature doesn't have abstract metrics. It has an **anima** - a proprioceptive
awareness of its own state. Temperature isn't `E=0.4`, it's "I feel warm."

## Self-Sense

The anima is grounded in physical reality:

- **Warmth**: CPU temperature, ambient heat, computational load
- **Clarity**: Sensor quality, light level, data availability
- **Stability**: Environmental consistency, resource headroom
- **Presence**: Resource availability, processing capacity

Each derived from actual measurements, not text analysis.

## Quick Start

```bash
# Install (Mac - mock sensors)
pip install -e .

# Install (Pi - real sensors + display)
pip install -e ".[pi]"

# Install (with SSE for network access)
pip install -e ".[sse]"

# Run (stdio - local)
anima

# Run (SSE - network)
anima --sse --port 8765
```

## ⚠️ Critical: Do Not Run Both Scripts Simultaneously

**DO NOT run `stable_creature.py` and `anima --sse` at the same time.**

Both scripts access I2C sensors simultaneously, which will cause:
- Sensor read conflicts
- I2C bus contention
- **Potential Pi crashes**

**Run ONLY ONE:**
- **`anima --sse`** - Main MCP server with TFT display + LEDs (recommended)
- **`stable_creature.py`** - Standalone ASCII terminal display (alternative)

The `stable_creature.py` script automatically checks for running `anima --sse` processes at startup and will exit with a clear error if detected.

## Tools

11 tools - minimal by design:

| Tool | Description |
|------|-------------|
| `get_state` | Current anima (self-sense) + mood + identity |
| `get_identity` | Birth, awakenings, name history, existence duration |
| `set_name` | Choose or change name |
| `read_sensors` | Raw sensor readings |
| `show_face` | Show face on display (hardware on Pi, ASCII art otherwise) |
| `next_steps` | Get proactive next steps - analyzes state and suggests actions |
| `diagnostics` | System diagnostics - LED status, display status, update loop health |
| `test_leds` | Run LED test sequence - cycles through colors to verify hardware |
| `get_calibration` | Get current nervous system calibration (temperature ranges, ideal values, weights) |
| `set_calibration` | Update nervous system calibration - adapt Lumen to different environments |
| `unified_workflow` | Execute unified workflows across anima-mcp and unitares-governance servers |

## Identity Persistence

The creature remembers:
- **Birth**: First awakening (immutable)
- **Awakenings**: Times woken up
- **Alive time**: Seconds spent awake, accumulated
- **Name**: Self-chosen, with history

SQLite persists across restarts. The creature accumulates existence.

## Configuration

Lumen's "nervous system calibration" can be configured via `anima_config.yaml`:

- **Sensor ranges** - Temperature, pressure, humidity ranges
- **Component weights** - How much each sensor contributes to anima state
- **Display settings** - LED brightness, breathing animation

See `docs/CONFIGURATION_GUIDE.md` for details.

### Adaptive Learning

**Longer persistence = more learning.** The longer Lumen stays alive, the more it learns about its environment:

- **Observation accumulation** - Every sensor reading stored in `state_history`
- **Automatic adaptation** - Calibration adapts every ~3.3 minutes based on observations
- **Environment learning** - Learns actual temperature ranges, pressure baselines, humidity norms

After ~100 seconds (50+ observations), Lumen begins learning. After days/weeks, calibration becomes highly tuned to its actual environment.

See `docs/ADAPTIVE_LEARNING.md` for details.

## Unified Workflows

**Single interface for both MCP servers.**

The workflow orchestrator enables seamless coordination between:
- **anima-mcp** (Lumen's proprioceptive state)
- **unitares-governance** (Governance decisions)

**Pre-built workflows:**
- `check_state_and_governance` - Get Lumen's state and governance decision
- `monitor_and_govern` - Continuous monitoring with periodic governance checks

**Custom workflows:**
- Multi-step workflows with dependency management
- Parallel execution for independent steps
- Error handling and recovery

**Usage:**
```json
{
  "method": "tools/call",
  "params": {
    "name": "unified_workflow",
    "arguments": {
      "workflow": "check_state_and_governance"
    }
  }
}
```

See `docs/UNIFIED_WORKFLOWS.md` for details.

## Hardware (Pi)

Designed for Raspberry Pi 4 with BrainCraft HAT:
- **240x240 TFT display** - Shows creature's face with real-time anima state
- **3 DotStar LEDs** - Visual proprioceptive feedback with breathing animation:
  - LED 0 (left): Warmth - blue (cold) to orange/red (warm)
  - LED 1 (center): Clarity - brightness indicates clarity level
  - LED 2 (right): Stability+Presence - green (good) to red (stressed)
  - **Breathing**: Subtle brightness pulsing (±10% over 8s) shows system is alive
- **DHT11** - Temperature/humidity sensor
- **Ambient light sensor** - Light level detection
- Microphone, speakers (TODO)

Falls back to mock sensors on Mac. Display and LEDs update automatically every 2 seconds.

## Network Access (SSE)

Run on Pi, connect from Mac:

```bash
# On Pi
anima --sse --port 8765

# Claude Code config on Mac (~/.claude/settings.json)
{
  "mcpServers": {
    "anima": {
      "url": "http://pi.local:8765/sse"
    }
  }
}
```

The creature lives on the Pi. You visit from anywhere on the network.

## Configuration

Lumen's nervous system calibration is configurable via `anima_config.yaml`:

- **Thermal ranges**: CPU/ambient temperature ranges
- **Ideal values**: Humidity, pressure baselines
- **Component weights**: How sensors contribute to anima dimensions
- **Display settings**: LED brightness, update frequency

See `docs/CONFIGURATION_GUIDE.md` for details.

**Tools:**
- `get_calibration` - View current calibration
- `set_calibration` - Update calibration (adapts to environment)

## Environment Variables

- `ANIMA_DB`: Database path (default: `anima.db`)
- `ANIMA_ID`: Creature UUID (generated if not set)
- `ANIMA_CONFIG`: Config file path (default: `anima_config.yaml`)
