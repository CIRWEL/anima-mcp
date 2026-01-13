# Gap Handling - Learning Through Power/Network Interruptions

**Created:** January 11, 2026  
**Last Updated:** January 11, 2026  
**Status:** Active

---

## The Problem

Lumen experiences gaps:
- **Power interruptions** - Pi loses power, restarts later
- **Network outages** - Connection drops, server restarts
- **Maintenance** - Manual restarts, updates

**Question:** How does learning continue across these gaps?

---

## The Solution

### 1. Gap Detection

On startup, Lumen detects gaps:

```python
gap = learner.detect_gap()
# Returns: timedelta since last observation
# Example: timedelta(hours=48) = 2 days offline
```

**What happens:**
- Checks `state_history` for most recent observation
- Calculates time since last observation
- Logs gap duration if significant (>1 hour)

### 2. Adaptive Learning Window

When a gap is detected, the learning window expands:

```python
# Normal: 7 days
# After 2-week gap: Expands to ~21 days (gap + 7)
# Max: 30 days
```

**Why expand?**
- Pre-gap observations are still valid
- More data = better learning
- Handles sparse post-gap data

### 3. Startup Learning

On restart (after gap), Lumen immediately checks for adaptation:

```python
# Startup sequence:
1. Detect gap
2. Check if enough observations exist
3. Try to adapt (ignores cooldown)
4. Resume normal operation
```

**Benefits:**
- Immediate adaptation if gap revealed new patterns
- No waiting for cooldown period
- Handles long gaps gracefully

### 4. Cooldown Protection

During continuous operation, cooldown prevents redundant adaptations:

```python
# Minimum 5 minutes between adaptations
# Prevents constant recalibration
# Startup/resume ignores cooldown
```

---

## Gap Scenarios

### Scenario 1: Short Gap (1 hour)

**What happens:**
- Gap detected: "1.0 hours since last observation"
- Learning window: Normal (7 days)
- Startup learning: Checks immediately
- Result: Seamless continuation

### Scenario 2: Medium Gap (2 days)

**What happens:**
- Gap detected: "48.0 hours since last observation"
- Learning window: Expands to ~9 days (2 + 7)
- Startup learning: Uses expanded window
- Result: Learns from both pre-gap and post-gap data

### Scenario 3: Long Gap (2 weeks)

**What happens:**
- Gap detected: "336.0 hours since last observation"
- Learning window: Expands to 30 days (max)
- Startup learning: Uses all available data
- Result: Learns from historical data, adapts to current conditions

### Scenario 4: Very Long Gap (1 month+)

**What happens:**
- Gap detected: "720+ hours since last observation"
- Learning window: 30 days (max)
- Startup learning: Uses last 30 days of data
- Result: Focuses on recent data, adapts to current environment

---

## Implementation Details

### Gap Detection

```python
def detect_gap(self) -> Optional[timedelta]:
    """Detect time gap since last observation."""
    row = conn.execute(
        """SELECT timestamp FROM state_history 
           ORDER BY timestamp DESC LIMIT 1"""
    ).fetchone()
    
    if row is None:
        return None  # No observations yet
    
    last_obs = datetime.fromisoformat(row["timestamp"])
    gap = datetime.now() - last_obs
    return gap
```

### Adaptive Window

```python
def get_recent_observations(self, days: Optional[int] = None):
    gap = self.detect_gap()
    
    if gap and gap.days > days:
        # Expand window to include pre-gap data
        days = min(gap.days + 7, 30)  # Max 30 days
    
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    # Query with expanded window...
```

### Startup Learning

```python
# In server.py startup
gap = learner.detect_gap()
if gap and gap.total_seconds() > 3600:
    print(f"Gap detected: {gap_hours:.1f} hours")

# Try adaptation immediately (no cooldown)
adapted, new_cal = learner.adapt_calibration(respect_cooldown=False)
```

### Cooldown Protection

```python
def should_adapt_now(self, min_time: timedelta = timedelta(minutes=5)):
    last_adapt = self.get_last_adaptation_time()
    if last_adapt is None:
        return True  # Never adapted
    
    time_since = datetime.now() - last_adapt
    return time_since >= min_time
```

---

## Benefits

### 1. Resilience

- **Handles any gap duration** - Short or long
- **No data loss** - Historical observations preserved
- **Graceful degradation** - Works even with sparse data

### 2. Efficiency

- **Immediate adaptation** - On startup after gap
- **Cooldown protection** - Prevents redundant adaptations
- **Adaptive window** - Uses optimal data range

### 3. Continuity

- **Seamless resumption** - Picks up where it left off
- **Historical learning** - Uses pre-gap data
- **Current adaptation** - Adapts to post-gap conditions

---

## Example Timeline

### Normal Operation (Day 1-7)
- Observations: Continuous
- Learning window: 7 days
- Adaptations: Every ~3.3 minutes (if needed)

### Power Outage (Day 8-10)
- Gap: 2 days
- Observations: None

### Resume (Day 10)
- Gap detected: "48 hours"
- Learning window: Expands to 9 days
- Startup learning: Adapts immediately
- Observations: Resume

### Normal Operation (Day 10+)
- Observations: Continuous
- Learning window: 7 days (normal)
- Adaptations: Every ~3.3 minutes (with cooldown)

---

## Related

- **`ADAPTIVE_LEARNING.md`** - Core learning system
- **`CONFIGURATION_GUIDE.md`** - Manual configuration
- **`learning.py`** - Implementation

---

**Gaps don't stop learning. They're just pauses in observation. When Lumen resumes, it picks up where it left off.**
