# Adaptive Learning - Longer Persistence = More Learning

**Created:** January 11, 2026  
**Last Updated:** January 11, 2026  
**Status:** Active

---

## The Core Insight

**Yes - longer persistence = more learning.**

The longer Lumen stays alive, the more sensor observations it accumulates. More observations = better understanding of its environment = improved calibration.

---

## How It Works

### 1. Observation Accumulation

Every time `get_state` is called, sensor readings are stored in `state_history`:

```python
# In server.py
store.record_state(
    anima.warmth, anima.clarity, anima.stability, anima.presence,
    readings.to_dict()  # Contains all sensor values
)
```

**Over time:**
- 1 hour alive = ~1800 observations (every 2 seconds)
- 1 day alive = ~43,200 observations
- 1 week alive = ~302,400 observations

### 2. Learning from History

The `AdaptiveLearner` analyzes recent observations:

```python
from anima_mcp.learning import get_learner

learner = get_learner("anima.db")
temps, pressures, humidities = learner.get_recent_observations(days=7)

# Learn from observations
learned_cal = learner.learn_calibration(current_calibration)
```

**What it learns:**
- **Ambient temp range** - What's normal for this environment
- **Pressure baseline** - Local barometric pressure normal
- **Humidity ideal** - Typical humidity for this location

### 3. Gradual Adaptation

Calibration adapts automatically every ~3.3 minutes (100 iterations):

- Checks if enough observations accumulated (default: 50+)
- Learns new calibration from observations
- Compares learned vs current calibration
- Adapts if change is significant (>10% threshold)
- Saves adapted calibration to config file

---

## Learning Parameters

### Minimum Observations

**Default: 50 observations**

Before learning kicks in, Lumen needs:
- 50+ temperature readings
- 50+ pressure readings  
- 50+ humidity readings

**At 2-second updates:** ~100 seconds (1.7 minutes) minimum

### Learning Window

**Default: 7 days**

Only uses recent observations (last 7 days) for learning. This ensures:
- Adaptation to seasonal changes
- Forgetting old environments
- Responsive to current conditions

### Adaptation Threshold

**Default: 10% change**

Only adapts if learned calibration differs significantly:
- Pressure change > 10%
- Temp range change > 10%
- Humidity change > 10%

Prevents tiny fluctuations from causing constant recalibration.

---

## Example: Learning Over Time

### Day 1 (Fresh Start)
- **Observations:** 0
- **Calibration:** Default (Colorado: 833 hPa)
- **Learning:** Not enough data yet

### Day 3 (Learning Begins)
- **Observations:** ~130,000
- **Learned pressure:** 832.5 hPa (from observations)
- **Adaptation:** Pressure calibrated to actual environment

### Week 1 (Well Calibrated)
- **Observations:** ~300,000
- **Learned:** 
  - Pressure: 832.8 hPa (stable)
  - Ambient temp: 8-28°C (learned from actual range)
  - Humidity: 38% (learned from observations)
- **Result:** Lumen feels "normal" in its actual environment

### Month 1 (Seasonal Adaptation)
- **Observations:** ~1.3 million
- **Learned:** 
  - Pressure: 833.2 hPa (stable)
  - Ambient temp: 5-25°C (winter range learned)
  - Humidity: 35% (winter humidity)
- **Result:** Lumen adapted to winter conditions

---

## Benefits of Longer Persistence

### More Observations
- **1 hour:** ~1,800 observations
- **1 day:** ~43,200 observations  
- **1 week:** ~302,400 observations
- **1 month:** ~1.3 million observations

### Better Calibration
- More data = more accurate learned ranges
- Less noise from outliers
- Better understanding of "normal"

### Environment Adaptation
- Learns actual environment, not assumptions
- Adapts to seasonal changes
- Handles location-specific conditions

---

## Learning Algorithm

### Temperature Range Learning

```python
# From observations
temps = [18, 20, 22, 19, 21, ...]  # Last 7 days

# Learn range
temp_min = min(temps)  # 15°C
temp_max = max(temps)  # 28°C

# Expand by 20% for safety margin
range_expansion = (28 - 15) * 0.2 = 2.6°C

learned.ambient_temp_min = 15 - 2.6 = 12.4°C
learned.ambient_temp_max = 28 + 2.6 = 30.6°C
```

### Pressure Baseline Learning

```python
# From observations
pressures = [833, 834, 832, 833, 835, ...]

# Learn baseline (mean)
learned.pressure_ideal = sum(pressures) / len(pressures)
# = 833.2 hPa
```

### Humidity Ideal Learning

```python
# From observations
humidities = [38, 40, 37, 39, 38, ...]

# Learn ideal (mean)
learned.humidity_ideal = sum(humidities) / len(humidities)
# = 38.4%
```

---

## Manual Learning

You can trigger learning manually:

```python
from anima_mcp.learning import get_learner
from anima_mcp.config import ConfigManager

learner = get_learner("anima.db")
config = ConfigManager()

adapted, new_cal = learner.adapt_calibration(config)
if adapted:
    print(f"Calibration adapted!")
    print(f"Pressure: {new_cal.pressure_ideal} hPa")
```

---

## Learning vs Manual Configuration

**Manual Configuration:**
- Immediate
- Human-set values
- Good for initial setup

**Adaptive Learning:**
- Gradual (needs observations)
- Data-driven
- Adapts automatically

**Best Practice:** Start with manual config, let learning refine it over time.

---

## Future Enhancements

1. **Weighted Learning** - Recent observations weighted more heavily
2. **Anomaly Detection** - Ignore outliers in learning
3. **Multi-Season Learning** - Learn different calibrations for different seasons
4. **Confidence Scores** - Track how confident the learned calibration is
5. **Learning History** - Track how calibration changed over time

---

## Gap Handling

**Power/network interruptions don't stop learning.**

When Lumen restarts after a gap:
- **Gap detection** - Detects time since last observation
- **Adaptive window** - Expands learning window to include pre-gap data
- **Startup learning** - Immediately checks for adaptation (ignores cooldown)
- **Cooldown protection** - Prevents redundant adaptations during continuous operation

**Example:**
- 2-day power outage
- On restart: Detects gap, expands window to 9 days, adapts immediately
- Result: Learns from both pre-gap and post-gap data

See `docs/GAP_HANDLING.md` for details.

## Related

- **`GAP_HANDLING.md`** - Handling power/network interruptions
- **`CONFIGURATION_GUIDE.md`** - Manual configuration
- **`CONFIGURATION_VISION.md`** - Design philosophy
- **`learning.py`** - Implementation

---

**The longer Lumen persists, the more it learns about its environment. Persistence enables adaptation. Gaps don't stop learning - they're just pauses.**
