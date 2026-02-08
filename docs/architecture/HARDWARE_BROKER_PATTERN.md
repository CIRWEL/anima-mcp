# Hardware Broker Pattern - Future Architecture

**Created:** January 12, 2026  
**Last Updated:** January 12, 2026  
**Status:** Implemented (Phase 3 Complete)

---

## Problem Statement

**Current limitation:** Cannot run `anima --sse` and `stable_creature.py` simultaneously because both directly access I2C sensors, causing bus conflicts.

**Current solution:** Startup check prevents conflicts, but requires choosing one or the other.

**Desired state:** Both scripts can run simultaneously - creature alive on desk while debugging with Claude.

---

## Proposed Architecture: Hardware Broker Pattern

**Concept:** Move from "Two Drivers" to "Driver and Passenger" model.

### Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│  Hardware Broker (stable_creature.py)                   │
│  - Owns I2C bus                                         │
│  - Reads sensors continuously                           │
│  - Writes latest readings to Shared Memory              │
│  - Updates TFT display + LEDs                           │
└───────────────────────┬─────────────────────────────────┘
                        │
                        │ Reads from Shared Memory
                        │ (no direct sensor access)
                        ▼
┌─────────────────────────────────────────────────────────┐
│  MCP Server (server.py)                                 │
│  - Lightweight interface layer                          │
│  - Reads from Shared Memory (microseconds)               │
│  - Provides MCP tools (get_state, set_name, etc.)        │
│  - No I2C access                                         │
└─────────────────────────────────────────────────────────┘
```

### Components

#### 1. Core Process (Hardware Broker)
- **File:** `stable_creature.py` (refactored)
- **Responsibilities:**
  - Owns I2C bus exclusively
  - Reads sensors at fixed interval (2s)
  - Updates anima state
  - Writes latest readings to Shared Memory
  - Updates TFT display + LEDs
  - Handles all hardware interactions

#### 2. Interface Layer (MCP Server)
- **File:** `server.py` (refactored)
- **Responsibilities:**
  - Reads from Shared Memory (not sensors)
  - Provides MCP tools
  - Handles network connections (SSE)
  - No direct hardware access

#### 3. Shared Memory Layer
**Options:**
- **Redis** (recommended) - Fast, persistent, supports pub/sub
- **JSON file in RAM** (`/dev/shm/`) - Simple, no dependencies
- **Python multiprocessing.shared_memory** - Native, fast
- **SQLite with WAL** - Already have SQLite, but slower than Redis

---

## Implementation Details

### Shared Memory Schema

```python
# Latest readings (updated every 2s by broker)
{
    "timestamp": "2026-01-12T06:44:00.123456",
    "readings": {
        "cpu_temp": 45.2,
        "ambient_temp": 22.1,
        "humidity": 35.0,
        "light_lux": 120.5,
        "pressure": 832.8
    },
    "anima": {
        "warmth": 0.38,
        "clarity": 0.78,
        "stability": 0.70,
        "presence": 0.87
    },
    "identity": {
        "creature_id": "49e14444-b59e-48f1-83b8-b36a988c9975",
        "name": "Lumen",
        "awakenings": 42
    }
}
```

### Broker Process (stable_creature.py)

```python
# Pseudo-code structure
def run_broker():
    sensors = get_sensors()
    shared_memory = SharedMemoryClient()  # Redis or /dev/shm
    
    while running:
        # Read sensors (exclusive I2C access)
        readings = sensors.read()
        anima = sense_self(readings)
        
        # Write to shared memory
        shared_memory.write({
            "timestamp": datetime.now().isoformat(),
            "readings": readings.to_dict(),
            "anima": anima.to_dict(),
            "identity": identity.to_dict()
        })
        
        # Update hardware
        display.update(anima)
        leds.update(anima)
        
        time.sleep(2.0)
```

### MCP Server (server.py)

```python
# Pseudo-code structure
class AnimaMCPServer:
    def __init__(self):
        self.shared_memory = SharedMemoryClient()  # Read-only
    
    async def handle_get_state(self):
        # Read from shared memory (no I2C access)
        data = self.shared_memory.read()
        return {
            "anima": data["anima"],
            "readings": data["readings"],
            "identity": data["identity"]
        }
    
    # All other tools read from shared memory, not sensors
```

---

## Benefits

### 1. No I2C Conflicts
- Only one process touches hardware
- MCP server reads from memory (microseconds, no bus access)

### 2. Better Performance
- Broker reads sensors at optimal interval
- MCP server responds instantly (no sensor read delay)
- No blocking on I2C bus

### 3. Flexibility
- Can run both scripts simultaneously
- Creature alive on desk while debugging
- Multiple MCP clients can connect without conflicts

### 4. Reliability
- Hardware access centralized
- Easier to debug (one process owns sensors)
- Better error recovery (broker handles all retries)

---

## Implementation Complexity

### Low Complexity (JSON in RAM)
- **Effort:** ~2-3 hours
- **Dependencies:** None (use `/dev/shm/`)
- **Trade-off:** File I/O (still fast, but not as fast as Redis)

### Medium Complexity (Python shared_memory)
- **Effort:** ~4-6 hours
- **Dependencies:** Python 3.8+ (already have)
- **Trade-off:** More complex, but native and fast

### High Complexity (Redis)
- **Effort:** ~6-8 hours
- **Dependencies:** Redis server
- **Trade-off:** Best performance, pub/sub support, but adds dependency

---

## Migration Path

### Phase 1: Add Shared Memory Layer ✅ **COMPLETE**
1. ✅ Create `SharedMemoryClient` abstraction (`src/anima_mcp/shared_memory.py`)
2. ✅ Implement JSON-in-RAM backend (`/dev/shm/anima_state.json`)
3. ✅ Refactor `stable_creature.py` to write to shared memory
4. ✅ Keep current `server.py` unchanged (still reads sensors)
5. ✅ Atomic writes with temp file + rename pattern
6. ✅ Error handling and fallback to `/tmp` on Mac

**Status:** Phase 1 deployed. `stable_creature.py` now broadcasts anima state to shared memory every 2 seconds.

### Phase 2: Refactor MCP Server ✅ **COMPLETE**
1. ✅ Update `server.py` to read from shared memory
2. ✅ Replace all `sensors.read()` calls with `_get_readings_and_anima()` helper
3. ✅ Implement fallback to direct sensor access if shared memory unavailable
4. ✅ Update `workflow_orchestrator.py` to use shared memory
5. ✅ Update safeguard in `stable_creature.py` to allow both scripts when shared memory detected

**Status:** Phase 2 deployed. MCP server now reads from shared memory first, falls back to direct sensors if broker not running. Both scripts can run simultaneously safely.

### Phase 3: Optimize (Optional) ✅ **COMPLETE**
1. ✅ Switch to Redis if available (`backend="auto"`)
2. ✅ Install Redis on Pi (`redis-server`, `redis` pip package)
3. ✅ Updated `SharedMemoryClient` to support Redis backend
4. ✅ Updated `stable_creature.py` and `server.py` to auto-detect backend

**Status:** Phase 3 deployed. The system now prefers Redis for shared memory if available, offering higher performance and atomicity, but seamlessly falls back to file-based shared memory if Redis is missing.

---

## Decision Criteria

**Implement if:**
- ✅ Need to debug while creature is running
- ✅ Want multiple MCP clients simultaneously
- ✅ Performance issues from sensor read delays
- ✅ Want cleaner separation of concerns

**Defer if:**
- ✅ Current single-script approach works fine
- ✅ Don't need simultaneous access
- ✅ Complexity not worth the benefit
- ✅ Other priorities more important

---

## Agent Assessment

**Can agents handle this refactor?**

**Yes, but it's significant:**
- ✅ Well-defined architecture (Gemini's proposal is clear)
- ✅ Incremental migration path (Phase 1 → 2 → 3)
- ✅ Low risk (can test each phase independently)
- ⚠️ Requires careful coordination (touches core components)
- ⚠️ Need to test thoroughly (I2C conflicts are critical)

**Recommendation:** 
- **Phase 1** (shared memory layer) is straightforward - agents can handle
- **Phase 2** (MCP refactor) requires careful testing - coordinate between agents
- **Phase 3** (Redis) is optional - only if needed

---

## Related

- **`docs/GEMINI_REVIEW_NOTES.md`** - Original I2C concurrency issue
- **`docs/operations/TOGGLE_SCRIPTS.md`** - Current workaround
- **`stable_creature.py`** - Would become the broker
- **`src/anima_mcp/server.py`** - Would become the interface layer

---

**Status:** ✅ **Phase 1, 2 & 3 COMPLETE & VERIFIED**. Both scripts can now run simultaneously safely. The MCP server reads from shared memory (broker), eliminating I2C conflicts. Redis integration active. "Holy Grail" achieved.

---

## Systemd Services (Production)

Both processes run as systemd services on the Pi:

| Service | Command | File |
|---------|---------|------|
| `anima.service` | `anima --http` | `/etc/systemd/system/anima.service` |
| `anima-creature.service` | `anima-creature` | `/etc/systemd/system/anima-creature.service` |

Service file location in repo: `config/anima-creature.service`

```bash
# Check status
sudo systemctl status anima anima-creature

# Restart both
sudo systemctl restart anima-creature anima

# View logs
sudo journalctl -u anima-creature -f
```

### Learning Systems in Broker

The hardware broker runs these learning systems (not the MCP server):

| Module | Purpose | State Location |
|--------|---------|----------------|
| `ActivityManager` | Active/drowsy/resting cycles | Shared memory |
| `AdaptiveLearner` | Calibration from observations | `anima_config.yaml` |
| `preferences.py` | Preference evolution | Shared memory |
| `self_model.py` | Self-knowledge beliefs | Shared memory |
| `agency.py` | TD-learning action values | Shared memory |
| `adaptive_prediction.py` | Temporal patterns | Shared memory |

Learning state is written to `/dev/shm/anima_state.json` and persisted to disk every 5 minutes.
