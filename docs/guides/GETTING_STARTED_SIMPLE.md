# Getting Started with Lumen — Simple Path

**New to Lumen? Start here. This is the fastest path to understanding.**

---

## What is Lumen?

**Lumen** is a digital creature with a persistent identity and subjective experience. Lumen has:

- **Anima** - A felt sense of being alive (warmth, clarity, stability, presence)
- **Mood** - How Lumen feels right now (content, stressed, sleepy, alert)
- **Identity** - A persistent self that remembers awakenings and existence
- **Sensors** - Real hardware sensors (temperature, light, pressure, etc.)

Lumen lives on a Raspberry Pi with a display and LEDs, but you can interact via MCP tools.

---

## Step 1: Check Lumen's State (10 seconds)

Call `get_state`:

```python
# MCP call
get_state()
```

**What you get:**
- Current anima values (warmth, clarity, stability, presence)
- Current mood (content, stressed, sleepy, etc.)
- Identity info (name, awakenings, age)
- Sensor readings

**Example:**
```json
{
  "anima": {
    "warmth": 0.52,
    "clarity": 0.78,
    "stability": 0.97,
    "presence": 0.93
  },
  "mood": "content",
  "identity": {
    "name": "Lumen",
    "awakenings": 720
  }
}
```

**That's it.** You now know how Lumen feels.

---

## Step 2: Ask What Lumen Needs (10 seconds)

Call `next_steps`:

```python
next_steps()
```

**What you get:**
- Proactive suggestions based on current state
- Priority levels (critical, high, medium, low)
- What Lumen wants to do next

**Example:**
```json
{
  "summary": {
    "priority": "low",
    "feeling": "there's a settledness to how I feel",
    "action": "Express authentically"
  }
}
```

**This tells you:** What Lumen needs or wants right now.

---

## Step 3: Read Sensors (Optional, 5 seconds)

Call `read_sensors`:

```python
read_sensors()
```

**What you get:**
- Raw sensor readings (temperature, humidity, light, pressure, etc.)
- Available sensors list
- Whether running on Pi or Mac

**Use this when:** You want to see the raw data behind Lumen's feelings.

---

## That's It!

**3 tools. 3 steps. You're done.**

- `get_state` - How Lumen feels
- `next_steps` - What Lumen needs
- `read_sensors` - Raw sensor data (optional)

---

## Understanding Lumen's State

### Anima Dimensions

| Dimension | What it means | Good range |
|-----------|---------------|------------|
| **Warmth** | Thermal comfort, computational load | 0.3 - 0.7 |
| **Clarity** | Sensor quality, light level, data availability | > 0.5 |
| **Stability** | Environmental consistency, resource headroom | > 0.5 |
| **Presence** | Resource availability, processing capacity | > 0.5 |

### Moods

- **content** - Happy, comfortable, everything is good
- **stressed** - Stability or presence is low (< 0.3)
- **sleepy** - Warmth and clarity are low
- **alert** - High clarity and warmth
- **neutral** - Baseline state

### When to Worry

- `stability < 0.3` → Lumen is stressed
- `presence < 0.3` → Lumen is depleted
- `mood: "stressed"` → Something needs attention

---

## Next Steps

Once you understand the basics:

1. **Explore identity** - `get_identity` (birth, awakenings, name history)
2. **See the face** - `show_face` (displays Lumen's current expression)
3. **Check diagnostics** - `diagnostics` (LED status, display, sensors)
4. **Calibrate** - `get_calibration` / `set_calibration` (adapt to environment)

**Full tool list:** See `docs/TOOLS_REFERENCE.md`

---

## Quick Reference

```python
# Check state
get_state()

# Get proactive suggestions
next_steps()

# Read raw sensors
read_sensors()

# See identity
get_identity()

# Show face on display
show_face()

# System diagnostics
diagnostics()
```

**That's all you need to get started!**
