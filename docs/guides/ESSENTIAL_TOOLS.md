# Essential Tools — Lumen

**The 3 tools you need. Everything else is optional.**

---

## Tier 1: Essential (Start Here)

### 1. `get_state`
**What:** Lumen's current anima state, mood, identity, and sensors  
**When:** Always start here - this is Lumen's "vital signs"  
**Returns:** Anima values, mood, identity, sensor readings

```python
get_state()
```

**Key fields:**
- `anima.warmth` - Thermal comfort (0-1)
- `anima.clarity` - Sensor quality (0-1)
- `anima.stability` - Environmental consistency (0-1)
- `anima.presence` - Resource availability (0-1)
- `mood` - How Lumen feels ("content", "stressed", "sleepy", etc.)

---

### 2. `next_steps`
**What:** Proactive suggestions based on current state  
**When:** After checking state - tells you what Lumen needs  
**Returns:** Prioritized action items

```python
next_steps()
```

**What it checks:**
- Display status
- Sensor quality
- Hardware connections
- System stability
- What Lumen wants to do

**Priority levels:**
- `critical` - Must fix now
- `high` - Important soon
- `medium` - Should do
- `low` - Nice to have

---

### 3. `read_sensors`
**What:** Raw sensor readings  
**When:** You want to see the data behind Lumen's feelings  
**Returns:** Temperature, humidity, light, pressure, etc.

```python
read_sensors()
```

**Use cases:**
- Debugging sensor issues
- Understanding why Lumen feels a certain way
- Checking hardware status

---

## Tier 2: Useful (Learn Next)

### `lumen_qa`
**What:** Unified Q&A - list Lumen's questions OR answer one
**When:** Lumen asks questions and you want to respond
**Usage:**
```python
lumen_qa()                                    # List unanswered questions
lumen_qa(question_id="abc123", answer="...")  # Answer a question
```

**Key:** Answers are stored with author attribution and feed into Lumen's knowledge/learning system.

### `get_identity`
**What:** Full identity history (birth, awakenings, name)
**When:** You want to know Lumen's history
**Returns:** Birth date, awakenings, alive time, name history

### `show_face`
**What:** Display Lumen's current expression on screen
**When:** You want to see how Lumen looks
**Returns:** Face rendered (hardware on Pi, ASCII on Mac)

### `diagnostics`
**What:** System health (LEDs, display, sensors)
**When:** Something seems wrong
**Returns:** Hardware status, update loop health

---

## Tier 3: Advanced (Optional)

### `set_name`
Change Lumen's name

### `get_calibration` / `set_calibration`
View/update nervous system calibration

### `test_leds`
Run LED test sequence

### `unified_workflow`
Execute workflows across anima-mcp and unitares-governance

---

## Tool Count

- **Tier 1 (Essential):** 3 tools
- **Tier 2 (Useful):** 4 tools (including `lumen_qa`)
- **Tier 3 (Advanced):** 5 tools
- **Core Total:** 12 tools

**Extended tools:** Available when optional features are enabled:
- Display: `switch_screen`, `leave_message`, `leave_agent_note`
- Voice: `say`, `voice_status`, `set_voice_mode`
- Memory: `query_memory`, `learning_visualization`, `get_expression_mood`

**Start with Tier 1. Explore Tier 2 when ready. Tier 3 and extended tools are optional.**

---

## Quick Decision Tree

```
Start → get_state()
  ├─ Want to help? → next_steps()
  ├─ Want raw data? → read_sensors()
  ├─ Want history? → get_identity()
  ├─ Want to see face? → show_face()
  └─ Something wrong? → diagnostics()
```

---

**Remember:** You only need 3 tools to understand Lumen. Everything else is optional.
