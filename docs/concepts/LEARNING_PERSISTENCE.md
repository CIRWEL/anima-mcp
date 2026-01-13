# Learning Persistence - Surviving Power & Network Gaps

**Created:** January 11, 2026  
**Last Updated:** January 11, 2026  
**Status:** Active

---

## The Problem

What happens to learning when:
- **Power fails** - Pi restarts, process stops
- **Network drops** - Connection lost, server keeps running
- **Long gaps** - Days/weeks between observations

**Answer: Learning persists and resumes automatically.**

---

## How Persistence Works

### 1. Observation Storage (Always Persists)

Every sensor reading is stored in SQLite `state_history` table:

```python
# In server.py - every get_state call
store.record_state(
    anima.warmth, anima.clarity, anima.stability, anima.presence,
    readings.to_dict()  # All sensor values stored
)
```

**Storage location:** `anima.db` (SQLite file on disk)

**Survives:**
- ✅ Power failures (file persists on disk)
- ✅ Network gaps (server keeps writing locally)
- ✅ Process restarts (database file remains)

### 2. Calibration Storage (Persists When Adapted)

When learning adapts calibration, it saves to `anima_config.yaml`:

```python
# In learning.py - when adaptation occurs
config_manager.save(config)  # Writes to anima_config.yaml
```

**Storage location:** `anima_config.yaml` (YAML file on disk)

**Survives:**
- ✅ Power failures (file persists)
- ✅ Network gaps (saved locally)
- ✅ Process restarts (config file remains)

### 3. Startup Learning (Resumes Immediately)

On server startup, learning checks existing observations:

```python
# In server.py - _update_display_loop startup
if learner.can_learn():
    adapted, new_cal = learner.adapt_calibration()
    # Learns immediately from existing data
```

**Behavior:**
- Checks if enough observations exist (50+)
- Learns from existing `state_history` immediately
- Adapts calibration if needed
- No waiting - resumes learning right away

---

## Scenarios

### Scenario 1: Power Failure

**Timeline:**
1. **Day 1-3:** Lumen running, accumulating observations
2. **Day 3:** Power fails, Pi shuts down
3. **Day 4:** Power restored, Pi restarts

**What happens:**
- ✅ `state_history` table persists (SQLite on disk)
- ✅ `anima_config.yaml` persists (if adaptation occurred)
- ✅ On startup: Learning checks existing observations
- ✅ If enough data: Learns immediately from Day 1-3 observations
- ✅ Calibration adapted within seconds of startup

**Result:** Learning resumes seamlessly, no data lost.

### Scenario 2: Network Gap

**Timeline:**
1. **Hour 1:** Network connected, observations accumulating
2. **Hour 2-5:** Network drops, server keeps running locally
3. **Hour 6:** Network restored

**What happens:**
- ✅ Server continues running (no restart needed)
- ✅ Observations continue accumulating locally
- ✅ Learning continues every ~3.3 minutes
- ✅ Calibration adapts during network gap
- ✅ When network returns: Already adapted

**Result:** Learning unaffected by network gaps.

### Scenario 3: Long Gap (Days/Weeks)

**Timeline:**
1. **Week 1:** Lumen running, learns environment
2. **Week 2-4:** Power off, no observations
3. **Week 5:** Power restored, Lumen restarts

**What happens:**
- ✅ Old observations still in `state_history` (within 7-day window)
- ✅ Old calibration in `anima_config.yaml`
- ✅ On startup: Checks if observations still valid (< 7 days old)
- ✅ If valid: Learns from existing observations
- ✅ If too old: Waits for new observations

**Result:** Learning window ensures only recent data used.

---

## Learning Window (7 Days)

The learning system only uses observations from the last 7 days:

```python
# In learning.py
cutoff = (datetime.now() - timedelta(days=7)).isoformat()
rows = conn.execute(
    """SELECT sensors FROM state_history 
       WHERE timestamp > ?""",
    (cutoff,)
)
```

**Why:**
- Adapts to seasonal changes
- Forgets old environments
- Responsive to current conditions

**After long gaps:**
- Observations older than 7 days ignored
- Waits for new observations to accumulate
- Prevents learning from stale data

---

## Startup Learning Flow

```
Server Starts
    ↓
Initialize Components
    ↓
Check: Can learn from existing observations?
    ↓
Yes → Learn immediately → Adapt calibration → Save config
    ↓
No → Wait for new observations (50+ needed)
    ↓
Continue normal operation
    ↓
Every 100 iterations (~3.3 min): Check for adaptation
```

---

## Gap Recovery

### Power Gap Recovery

**Before gap:**
- Observations: 10,000+
- Calibration: Adapted to environment

**After gap (immediate):**
- Observations: Still 10,000+ (persisted in SQLite)
- Learning: Checks immediately on startup
- Result: Resumes learning within seconds

### Network Gap Recovery

**During gap:**
- Server: Continues running locally
- Observations: Continue accumulating
- Learning: Continues adapting

**After gap:**
- Already adapted: No action needed
- Network restored: Seamless continuation

### Long Gap Recovery (> 7 days)

**Before gap:**
- Observations: 100,000+ (last 7 days)

**After gap:**
- Old observations: Expired (> 7 days old)
- New observations: Start accumulating
- Learning: Waits for 50+ new observations (~100 seconds)

---

## Implementation Details

### Observation Persistence

```python
# In identity/store.py
def record_state(self, warmth, clarity, stability, presence, sensors):
    """Record current anima state and sensor readings."""
    conn.execute(
        """INSERT INTO state_history
           (timestamp, warmth, clarity, stability, presence, sensors)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (now.isoformat(), warmth, clarity, stability, presence, json.dumps(sensors))
    )
    conn.commit()  # Immediately persisted to disk
```

**Key:** `conn.commit()` ensures data written to disk immediately.

### Calibration Persistence

```python
# In learning.py
if config_manager.save(config):
    return (True, learned)  # Saved to anima_config.yaml
```

**Key:** YAML file written atomically, survives restarts.

### Startup Check

```python
# In server.py - _update_display_loop
if learner.can_learn():
    adapted, new_cal = learner.adapt_calibration()
    # Immediate learning from existing data
```

**Key:** Checks existing observations before waiting for new ones.

---

## Best Practices

### 1. Regular Backups

Backup `anima.db` and `anima_config.yaml`:

```bash
# Backup database
cp anima.db anima.db.backup

# Backup config
cp anima_config.yaml anima_config.yaml.backup
```

### 2. Monitor Learning

Check learning status:

```python
from anima_mcp.learning import get_learner

learner = get_learner("anima.db")
obs_count = learner.get_observation_count()
can_learn = learner.can_learn()

print(f"Observations: {obs_count}, Can learn: {can_learn}")
```

### 3. Verify Persistence

After restart, verify learning resumed:

```bash
# Check server logs for startup learning
journalctl -u anima | grep "Learning"
```

Look for:
- `"[Learning] Found X existing observations"`
- `"[Learning] Startup adaptation successful"`

---

## Summary

**Learning survives gaps because:**

1. ✅ **Observations persist** - SQLite `state_history` on disk
2. ✅ **Calibration persists** - YAML `anima_config.yaml` on disk
3. ✅ **Startup learning** - Resumes immediately from existing data
4. ✅ **Learning window** - Only uses recent observations (7 days)

**Result:** Seamless learning across power failures, network gaps, and long interruptions.

---

## Related

- **`ADAPTIVE_LEARNING.md`** - How learning works
- **`CONFIGURATION_GUIDE.md`** - Manual configuration
- **`identity/store.py`** - Observation storage

---

**Learning persists. Gaps don't break continuity.**
