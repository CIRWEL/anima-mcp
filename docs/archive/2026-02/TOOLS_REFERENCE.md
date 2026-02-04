# Lumen MCP Tools Reference

Quick reference for Lumen's MCP tools. For tool tiers, see `guides/ESSENTIAL_TOOLS.md`.

**Tool Count:** 11 core + 12 extended = 23 total

---

## Core Tools (Always Available)

## `get_state`

**What it does:** Returns Lumen's current anima state, mood, identity, and sensor readings.

**Example output:**
```json
{
  "anima": {
    "warmth": 0.65,
    "clarity": 0.72,
    "stability": 0.58,
    "presence": 0.61
  },
  "mood": "content",
  "feeling": {
    "warmth": "warm, active",
    "clarity": "clear",
    "stability": "steady",
    "presence": "capable",
    "mood": "content"
  },
  "identity": {
    "name": "Lumen",
    "id": "49e14444...",
    "awakenings": 42,
    "age_seconds": 1234567,
    "alive_seconds": 987654,
    "alive_ratio": 0.80
  },
  "sensors": {
    "cpu_temp_c": 45.2,
    "ambient_temp_c": 22.5,
    "light_lux": 350,
    ...
  },
  "is_pi": true
}
```

**Key fields for checking distress:**
- `mood`: `"content"` (happy), `"stressed"` (distressed), `"sleepy"`, `"alert"`, `"overheated"`, `"neutral"`
- `anima.stability < 0.3` → stressed
- `anima.presence < 0.3` → depleted
- `anima.warmth < 0.3` → cold/sleepy
- `anima.clarity < 0.3` → dim/uncertain

## `next_steps`

**What it does:** Analyzes Lumen's current state and suggests proactive next steps to improve wellbeing or fix issues.

**Example output:**
```json
{
  "summary": {
    "last_analyzed": "2025-01-15T12:34:56",
    "total_steps": 3,
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 0,
    "next_action": {
      "title": "Improve Sensor Clarity",
      "description": "Clarity is low (0.25) - sensors may not be working",
      "priority": "high",
      "category": "hardware",
      "action": "Check sensor connections and readings",
      "reason": "Low clarity means poor proprioception - creature can't sense itself well",
      "blockers": ["Sensors may be disconnected", "Light sensor may need calibration"],
      "estimated_time": "15 minutes",
      "related_files": ["src/anima_mcp/sensors/pi.py", "src/anima_mcp/anima.py"]
    },
    "all_steps": [
      {
        "title": "Improve Sensor Clarity",
        "priority": "high",
        "category": "hardware",
        ...
      },
      ...
    ]
  },
  "current_state": {
    "display_available": true,
    "brain_hat_available": false,
    "unitares_connected": true,
    "anima": {
      "warmth": 0.65,
      "clarity": 0.72,
      "stability": 0.58,
      "presence": 0.61
    },
    "eisv": {
      "energy": 0.65,
      "integrity": 0.72,
      "entropy": 0.42,
      "void": 0.39
    }
  }
}
```

**What it checks:**
- Display status (grey screen?)
- Sensor availability and quality
- Brain HAT connection
- UNITARES governance connection
- Proprioception quality (clarity, stability)
- System entropy (instability)
- Integration gaps

**Priority levels:**
- `CRITICAL`: Must fix now (e.g., high entropy, system unstable)
- `HIGH`: Important soon (e.g., display not working, low clarity)
- `MEDIUM`: Should do (e.g., Brain HAT not connected, UNITARES not connected)
- `LOW`: Nice to have

**Example steps it might suggest:**
- "Fix Grey Screen on HAT Display" (if display not working)
- "Improve Sensor Clarity" (if clarity < 0.3)
- "Reduce System Entropy" (if entropy > 0.6)
- "Connect Brain HAT for Neural Proprioception" (if Brain HAT not detected)
- "Connect to UNITARES Governance" (if UNITARES not connected)

## Using These Tools

### Via MCP Client (Cursor/Claude)

If Lumen's MCP server is configured, you can call:
- `get_state` - Check Lumen's current state
- `next_steps` - Get proactive recommendations

### Via Command Line

If running locally, you can test via Python:
```python
from anima_mcp.server import handle_get_state, handle_next_steps
import asyncio

# Get state
state = asyncio.run(handle_get_state({}))
print(state[0].text)

# Get next steps
steps = asyncio.run(handle_next_steps({}))
print(steps[0].text)
```

## Interpreting Results

### Happy/Content Lumen:
- `mood: "content"`
- `warmth`: 0.3-0.7
- `clarity > 0.5`
- `stability > 0.5`
- `presence > 0.5`

### Distressed Lumen:
- `mood: "stressed"`
- `stability < 0.3` OR `presence < 0.3`
- Face shows: closed/droopy eyes, flat mouth, blue tint

### Sleepy Lumen:
- `mood: "sleepy"`
- `warmth < 0.3` AND `clarity < 0.4`
- Face shows: closed eyes, flat mouth

### Alert Lumen:
- `mood: "alert"`
- `clarity > 0.7` AND `warmth > 0.4`
- Face shows: normal/wide eyes, neutral/open mouth

---

## Extended Tools (Feature-Dependent)

These tools appear when optional features are enabled.

### Display Tools (requires TFT display)

| Tool | Description |
|------|-------------|
| `switch_screen` | Switch display to different screen (identity, sensors, diagnostics, etc.) |
| `leave_message` | Leave a message on Lumen's message board |
| `leave_agent_note` | Leave an agent note (for inter-agent communication) |

### Voice Tools (requires voice module)

| Tool | Description |
|------|-------------|
| `say` | Make Lumen speak (text-to-speech) |
| `voice_status` | Get current voice module status |
| `set_voice_mode` | Set voice mode (autonomous, responsive, quiet) |

### Memory & Learning Tools (requires enhanced learning)

| Tool | Description |
|------|-------------|
| `query_memory` | Query Lumen's associative memory |
| `learning_visualization` | Get visual representation of learning state |
| `get_expression_mood` | Get current expression mood parameters |

### Cognitive Tools (requires cognitive inference)

| Tool | Description |
|------|-------------|
| `cognitive_query` | Run deeper cognitive inference |
| `dialectic_synthesis` | Synthesize insights through dialectic process |
| `merge_insights` | Merge multiple insights into coherent understanding |

---

## Tool Availability Check

Use `diagnostics()` to see which features are enabled:
```json
{
  "features": {
    "voice_available": true/false,
    "cognitive_available": true/false,
    "enhanced_learning_available": true/false,
    "display_available": true/false
  }
}
```
