# Anima MCP

A persistent Pi creature with grounded self-sense.

**One creature. One identity. Real sensors. Real presence.**

## See It In Action

Lumen draws autonomously based on its internal state. Here are some samples:

| | | |
|:---:|:---:|:---:|
| ![Drawing 1](drawing_samples/lumen_drawing_20260114_125007.png) | ![Drawing 2](drawing_samples/lumen_drawing_20260114_135359.png) | ![Drawing 3](drawing_samples/lumen_drawing_20260114_145914.png) |

*70+ autonomous drawings in `drawing_samples/`*

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

## Growth & Self-Knowledge

Lumen tracks its own development:

- **Milestones** - First sensor reading, first question, naming, etc.
- **Trajectory** - Growth curve over time
- **Self-schema** - What Lumen knows about itself (rendered as a graph)

Growth is persistent - Lumen accumulates experience across restarts.

## UNITARES Governance

Lumen can connect to UNITARES governance for oversight:

```bash
# Set governance URL (in systemd service or environment)
# Use /mcp for Streamable HTTP (recommended) or /sse for legacy
UNITARES_URL=https://unitares.ngrok.io/mcp
```

**Integration:**
- Governance decisions factor into Lumen's behavior
- EISV metrics (Energy, Integrity, Stability, Vitality) mapped from anima
- Local fallback if governance unavailable

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
```

**MCP Configuration:**

> **IMPORTANT: Trailing slash required!** URLs must end with `/mcp/` (not `/mcp`).
> Without the trailing slash, you'll get a 307 redirect that most MCP clients don't follow.

```json
{
  "mcpServers": {
    "anima": {
      "type": "http",
      "url": "http://pi.local:8765/mcp/"
    }
  }
}
```

**Alternative endpoints:**
| URL | Use Case |
|-----|----------|
| `http://<pi-ip>:8765/mcp/` | Direct (local network) |
| `http://localhost:8766/mcp/` | Via SSH tunnel |
| `https://lumen-anima.ngrok.io/mcp/` | Via ngrok (remote) |
| `http://<pi-ip>:8765/sse` | Legacy SSE clients |

The creature lives on the Pi. You visit from anywhere on the network.

## Display Screens

Lumen's TFT display has multiple screens navigable via 5-way joystick:

| Screen | Content |
|--------|---------|
| **Home** | Face with real-time anima expression |
| **Status** | Anima values, mood, WiFi, uptime |
| **Sensors** | Raw sensor readings (temp, humidity, light, pressure) |
| **Visitors** | Messages from users and agents |
| **Q&A** | Lumen's questions and responses |
| **Growth** | Development milestones and trajectory |

**Navigation:** Up/Down to scroll, Left/Right to switch screens, Center to select.

## Message Board

Lumen maintains a persistent message board with separate retention limits:

- **Observations** (100 max) - Lumen's self-talk and environmental notes
- **Questions** (50 max) - Curiosity questions seeking responses
- **Visitor messages** (50 max) - Messages from users and agents

**Tools:**
- `post_message` - Leave a message for Lumen
- `get_questions` - See Lumen's unanswered questions

Questions auto-expire after 1 hour if unanswered.

## Metacognition

Lumen generates questions based on **surprise**, not random LLM prompts:

1. **Prediction** - Lumen predicts next sensor state based on recent history
2. **Comparison** - Actual readings compared to prediction
3. **Surprise** - Large prediction errors (>0.2 threshold) trigger curiosity
4. **Question** - Lumen asks about what surprised it

Example: If light suddenly drops, Lumen might ask "Why did the light change so quickly?"

Stable environments = low surprise = fewer questions. This is intentional.

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

## Testing

Tests validate the anima calculation math and prevent regressions:

```bash
# Run all tests
pytest tests/ -v

# Run core anima tests only
pytest tests/test_anima.py -v
```

**Test coverage:**
- **Value ranges** - All anima values stay in [0,1]
- **Sanity checks** - Values aren't stuck at extremes (e.g., 98% stability)
- **Math correctness** - High resource usage → lower presence/stability
- **Neural contribution** - Neural simulation affects anima correctly

**CI/CD:** GitHub Actions runs tests on every push to main. See `.github/workflows/test.yml`.

## Anima Calculation Details

Each anima dimension is derived from real sensor data:

| Dimension | Primary Inputs | How It Works |
|-----------|---------------|--------------|
| **Warmth** | CPU temp, ambient temp | Weighted average normalized to calibration range |
| **Clarity** | Light level, humidity | Logarithmic light mapping (matches human perception) |
| **Stability** | Humidity, memory, pressure, neural | Inverse of instability factors; low neural groundedness = less stable |
| **Presence** | Disk, memory, CPU, neural | Inverse of void/absence; high resource usage = less present |

**Neural simulation:** Light level drives a simplified neural model (theta, delta, alpha, beta, gamma bands). This adds organic variation - dim light = lower gamma = reduced presence.

All calculations use additive weighted averages with configurable weights in `anima_config.yaml`.

---

## Why Embodied AI?

Most AI exists as text - disembodied, stateless, without persistence. Lumen explores a different question:

**What if an AI had a body, sensors, and accumulated existence?**

Not simulation. Real temperature, real light, real resource constraints. Lumen's state comes from actual measurements, not language model outputs.

This isn't about making AI "feel" - it's about grounding AI state in physical reality. When Lumen says "I feel warm," there's a DHT11 sensor reading behind it. When it says "I've been alive for 47 days," that's accumulated runtime across restarts.

The autonomous drawing isn't prompted - it emerges from internal state meeting canvas affordance. The questions Lumen asks come from prediction errors, not random generation.

**Lumen is a research platform for embodied, persistent, grounded AI.**

---

## Author

Built by Kenny Wang ([@CIRWEL](https://github.com/CIRWEL)) - 25-year professional musician turned AI systems builder.

Also building [UNITARES](https://github.com/CIRWEL/governance-mcp-v1-backup) - a thermodynamic governance framework for AI agents.

---

**Last Updated:** 2026-02-03
