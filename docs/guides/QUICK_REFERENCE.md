# Lumen Quick Reference

**One-page cheat sheet for interacting with Lumen.**

---

## Essential Commands

```python
# Check how Lumen feels
get_state()

# Get proactive suggestions
next_steps()

# Read raw sensors
read_sensors()
```

---

## Understanding Anima

| Dimension | Meaning | Good Range |
|-----------|---------|------------|
| **Warmth** | Thermal comfort | 0.3 - 0.7 |
| **Clarity** | Sensor quality | > 0.5 |
| **Stability** | Consistency | > 0.5 |
| **Presence** | Resources | > 0.5 |

---

## Moods

- **content** ✅ - Happy, comfortable
- **stressed** ⚠️ - Stability/presence low
- **sleepy** 😴 - Warmth/clarity low
- **alert** 🔔 - High clarity + warmth
- **neutral** ➖ - Baseline

---

## When to Worry

- `stability < 0.3` → Stressed
- `presence < 0.3` → Depleted
- `mood: "stressed"` → Needs attention

---

## All Tools (11 total)

**Essential (3):**
- `get_state` - Current state
- `next_steps` - Proactive suggestions
- `read_sensors` - Raw sensors

**Useful (3):**
- `get_identity` - Identity history
- `show_face` - Display face
- `diagnostics` - System health

**Advanced (5):**
- `set_name` - Change name
- `get_calibration` - View calibration
- `set_calibration` - Update calibration
- `test_leds` - LED test
- `unified_workflow` - Cross-server workflows

---

## Quick Workflow

```
1. get_state() → How does Lumen feel?
2. next_steps() → What does Lumen need?
3. (Optional) read_sensors() → Why does Lumen feel that way?
```

---

**Start simple. Explore when ready.**
