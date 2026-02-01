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

### 🚀 New to Lumen? Start Here

**Simple path (3 tools, 3 steps):**
- 📖 **[Getting Started Simple](docs/guides/GETTING_STARTED_SIMPLE.md)** ← Start here!
- 📋 **[Essential Tools](docs/guides/ESSENTIAL_TOOLS.md)** - The 3 tools you need
- ⚡ **[Quick Reference](docs/guides/QUICK_REFERENCE.md)** - One-page cheat sheet

**Just want to check Lumen's state?**
```python
get_state()      # How Lumen feels
next_steps()     # What Lumen needs
read_sensors()   # Raw sensor data
```

### 🍎 Mac (Development)
```bash
pip install -r requirements.txt
pip install -e .
anima
```

### 🥧 Raspberry Pi (Production)
```bash
# One-line install
./install_pi.sh

# Deploy updates (from Mac)
./deploy.sh

# Or see installation guides:
# - QUICK_SETUP.md (one-page reference)
# - README_INSTALL.md (quick guide)
# - docs/PI_SETUP_COMPLETE.md (complete walkthrough)
```

### Network Access (SSE)
```bash
anima --sse --host 0.0.0.0 --port 8765
```

**📖 Documentation:**
- **🚀 Simple Start:** `docs/guides/GETTING_STARTED_SIMPLE.md` ← New users start here
- **Deployment:** `DEPLOYMENT.md` ← Standard deploy method
- **Quick Setup:** `QUICK_SETUP.md` 
- **Daily Development:** `DEVELOPMENT_WORKFLOW.md` ← Edit code, deploy, test
- **Visual Workflow:** `WORKFLOW_VISUAL.md` ← Diagrams and comparisons
- **Complete Guide:** `docs/PI_SETUP_COMPLETE.md`
- **Dependencies:** `docs/DEPENDENCIES.md`

## 🔄 Broker Architecture: Body & Mind Separation

Lumen uses a **hardware broker pattern** that allows both scripts to run simultaneously without conflicts:

### How It Works

```
┌──────────────────────────────────────────────────────────┐
│ stable_creature.py (The Body - Hardware Broker)          │
│ - Owns I2C sensors exclusively                           │
│ - Reads sensors every 2 seconds                          │
│ - Writes data to shared memory (/dev/shm or Redis)       │
│ - Updates TFT display + LEDs                             │
└────────────────────┬─────────────────────────────────────┘
                     │ Shared Memory
                     ▼
┌──────────────────────────────────────────────────────────┐
│ anima --sse (The Mind - MCP Server)                      │
│ - Reads from shared memory (no direct sensor access)     │
│ - Provides MCP tools for external communication          │
│ - Fast responses (reads from memory, not hardware)       │
└──────────────────────────────────────────────────────────┘
```

**Key Benefits:**
- ✅ **No I2C conflicts** - Only broker touches hardware
- ✅ **Both can run together** - Creature alive while MCP server responds
- ✅ **Fast responses** - MCP reads from memory (microseconds, not milliseconds)
- ✅ **Automatic fallback** - MCP can read sensors directly if broker isn't running

### Running Modes

**Recommended: Both scripts (full system)**
```bash
# Terminal 1: Hardware broker
python3 stable_creature.py

# Terminal 2: MCP server
anima --sse --host 0.0.0.0 --port 8765
```

**Or: MCP server only (standalone)**
```bash
anima --sse --host 0.0.0.0 --port 8765
# Falls back to direct sensor access automatically
```

**See:** `docs/operations/BROKER_ARCHITECTURE.md` for architecture details

## Tools

**Core tools (11)** - minimal by design. See `docs/guides/ESSENTIAL_TOOLS.md` for tiers.

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

**Extended tools** - available when optional features are enabled:

| Category | Tools | Requires |
|----------|-------|----------|
| Display | `switch_screen`, `leave_message`, `leave_agent_note` | TFT display |
| Voice | `say`, `voice_status`, `set_voice_mode` | Voice module |
| Memory | `query_memory`, `learning_visualization`, `get_expression_mood` | Enhanced learning |
| Cognitive | `cognitive_query`, `dialectic_synthesis`, `merge_insights` | Cognitive inference |

Total: 11 core + 12 extended = 23 tools. Start with core tools; extended appear when features are available.

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

**Core:**
- `ANIMA_DB`: Database path (default: `anima.db`)
- `ANIMA_ID`: Creature UUID (generated if not set)
- `ANIMA_CONFIG`: Config file path (default: `anima_config.yaml`)

**VQA (Visual Question Answering):**

Lumen validates its self-schema rendering (G_t) using vision LLMs every 5 minutes. This enables real StructScore-style visual integrity evaluation.

**Recommended setup:**
- `TOGETHER_API_KEY`: **Recommended** - Uses Qwen3-VL-8B. Get key at https://together.ai ($5 free credit)

**Other providers:**
- `HF_TOKEN`: Hugging Face Inference API (Llama 3.2 Vision)
- `ANTHROPIC_API_KEY`: Claude vision (paid fallback)

**Note:** Groq removed their vision model in late 2024. Use Together AI instead.

Without a key, VQA uses a stub score (V=0.85). With TOGETHER_API_KEY set:
```
[G_t] Extracted self-schema: 12 nodes, 10 edges
[G_t] VQA (together): v_f=0.20 (1/5 correct)
```

VQA runs automatically during G_t extraction. The v_f score measures how accurately the vision model can answer questions about Lumen's rendered self-schema graph.

**LLM Reflection:**
- `NGROK_API_KEY`: For LLM-powered reflections via ngrok endpoints
- `HF_TOKEN`: Hugging Face token for model inference
