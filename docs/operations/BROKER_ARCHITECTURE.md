# Broker Architecture - Lumen's Body & Mind Separation

**Created:** January 12, 2026  
**Last Updated:** January 12, 2026  
**Status:** Active Architecture

---

## Overview

Lumen is now split into two systemd services that run independently:

1. **`anima-broker.service`** - Lumen's **Body** (Hardware Broker)
   - Owns I2C sensors
   - Writes sensor data to Redis/shared memory
   - Runs `stable_creature.py`
   - Displays ASCII face in logs

2. **`anima.service`** - Lumen's **Mind** (MCP Server)
   - Reads sensor data from Redis/shared memory
   - Provides MCP interface for external tools
   - Runs `anima --sse`
   - Depends on broker service

**Key Benefit:** You can restart the MCP server (mind) without interrupting the hardware broker (body). No more cascading reboots or I2C hangs.

**Data Flow:**
- Broker → Shared Memory (`/dev/shm/anima_state.json`): readings, anima, governance
- MCP Server ← Shared Memory: reads all data for display and tools
- Governance: Broker calls UNITARES, MCP server reads result from shared memory

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Hardware Layer                        │
│  (I2C Sensors: AHT20, BMP280, Light Sensor, LEDs)      │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│         anima-broker.service (Lumen's Body)            │
│  ┌──────────────────────────────────────────────────┐   │
│  │  stable_creature.py                              │   │
│  │  - Reads sensors (owns I2C bus)                  │   │
│  │  - Computes anima state                         │   │
│  │  - Writes to Redis/shared memory                │   │
│  │  - Displays ASCII face                           │   │
│  └──────────────────────────────────────────────────┘   │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ Redis/Shared Memory
                     │ (State: sensor readings, anima state)
                     ▼
┌─────────────────────────────────────────────────────────┐
│          anima.service (Lumen's Mind)                   │
│  ┌──────────────────────────────────────────────────┐   │
│  │  anima --sse (MCP Server)                       │   │
│  │  - Reads from Redis/shared memory               │   │
│  │  - Provides MCP tools (get_state, show_face)   │   │
│  │  - Handles external connections                 │   │
│  │  - Updates display/LEDs (via shared memory)    │   │
│  └──────────────────────────────────────────────────┘   │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              External MCP Clients                      │
│  (Cursor IDE, UNITARES Governance, etc.)              │
└─────────────────────────────────────────────────────────┘
```

---

## Service Dependencies

**Startup Order:**
1. Redis (system service) - if using Redis backend
2. `anima-broker.service` - must start first
3. `anima.service` - depends on broker

**Shutdown Order:**
- Stopping `anima.service` does NOT stop broker
- Broker continues running, sensors keep reading
- Face keeps displaying in broker logs

---

## Usage

### Restart Only the Mind (MCP Server)

When iterating on MCP server code:

```bash
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  "systemctl --user restart anima"
```

**Result:**
- ✅ Broker keeps running (sensors uninterrupted)
- ✅ Face keeps displaying
- ✅ No I2C conflicts
- ✅ MCP server restarts with new code

### Restart Only the Body (Hardware Broker)

When debugging sensor issues:

```bash
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  "systemctl --user restart anima-broker"
```

**Result:**
- ✅ MCP server waits for broker to restart
- ✅ Sensors reinitialize cleanly
- ✅ State persists in Redis

### View Live ASCII Face

Watch the broker's terminal output:

```bash
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  "journalctl --user -u anima-broker -f"
```

### Check Service Status

```bash
# Check both services
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  "systemctl --user status anima anima-broker"

# Check broker only
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  "systemctl --user status anima-broker"

# Check MCP server only
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  "systemctl --user status anima"
```

---

## Benefits

### ✅ No Cascading Reboots

**Before:** Restarting MCP server could cause I2C hang → Pi reboot  
**After:** Restarting MCP server leaves broker untouched → No hardware interruption

### ✅ Rapid Iteration

**Before:** Every code change required full restart → Risk of I2C conflicts  
**After:** Iterate on MCP server code freely → Broker stays stable

### ✅ Hardware Stability

**Before:** Both processes could fight for I2C bus  
**After:** Only broker touches hardware → Single point of control

### ✅ State Persistence

**Before:** State lost on restart  
**After:** Redis persists state → Broker can restart without losing context

---

## Setup

### 1. Install Redis (if using Redis backend)

```bash
# On Pi
sudo apt-get install redis-server
sudo systemctl enable redis-server
sudo systemctl start redis-server
```

### 2. Install Service Files

```bash
# Copy service files to Pi
scp -P 2222 systemd/anima-broker.service \
  unitares-anima@192.168.1.165:~/.config/systemd/user/

scp -P 2222 systemd/anima.service \
  unitares-anima@192.168.1.165:~/.config/systemd/user/

# On Pi, reload systemd
ssh -p 2222 unitares-anima@192.168.1.165 \
  "systemctl --user daemon-reload"
```

### 3. Enable Services

```bash
# Enable broker (starts automatically)
ssh -p 2222 unitares-anima@192.168.1.165 \
  "systemctl --user enable anima-broker"

# Enable MCP server (starts automatically after broker)
ssh -p 2222 unitares-anima@192.168.1.165 \
  "systemctl --user enable anima"

# Start both
ssh -p 2222 unitares-anima@192.168.1.165 \
  "systemctl --user start anima-broker anima"
```

---

## Troubleshooting

### Broker Not Starting

```bash
# Check broker logs
ssh -p 2222 unitares-anima@192.168.1.165 \
  "journalctl --user -u anima-broker -n 50"

# Check if Redis is running (if using Redis)
ssh -p 2222 unitares-anima@192.168.1.165 \
  "systemctl status redis-server"
```

### MCP Server Waiting for Broker

```bash
# Check if broker is running
ssh -p 2222 unitares-anima@192.168.1.165 \
  "systemctl --user is-active anima-broker"

# If not active, start it
ssh -p 2222 unitares-anima@192.168.1.165 \
  "systemctl --user start anima-broker"
```

### I2C Conflicts (Should Not Happen)

If you see I2C errors, verify only broker is accessing hardware:

```bash
# Check what's accessing I2C
ssh -p 2222 unitares-anima@192.168.1.165 \
  "lsof /dev/i2c-1 2>/dev/null || echo 'No I2C access detected'"
```

---

## Related Documentation

- **`docs/architecture/HARDWARE_BROKER_PATTERN.md`** - Architecture details
- **`docs/operations/HOLY_GRAIL_STARTUP.md`** - Previous startup guide (now superseded)
- **`stable_creature.py`** - Broker implementation
- **`src/anima_mcp/shared_memory.py`** - Shared memory client

---

## Status

✅ **Architecture Active** - Both services configured and running  
✅ **No I2C Conflicts** - Only broker touches hardware  
✅ **Rapid Iteration** - MCP server can restart independently  
✅ **State Persistence** - Redis maintains state across restarts
