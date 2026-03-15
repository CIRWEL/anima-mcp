# Broker Architecture -- Body & Mind Separation

**Last Updated:** March 14, 2026

---

## Overview

Lumen runs as two systemd services:

1. **`anima-broker.service`** -- Lumen's **Body** (Hardware Broker)
   - Owns I2C sensors, writes to shared memory
   - Runs learning systems
   - Command: `anima-creature` (`stable_creature.py`)

2. **`anima.service`** -- Lumen's **Mind** (MCP Server)
   - Reads from shared memory, serves MCP tools
   - Owns TFT display + LEDs
   - Command: `anima --http` (`server.py`)

**Key benefit:** Restart the MCP server without interrupting sensors or learning. No I2C conflicts.

---

## Architecture

```
Hardware Layer (I2C Sensors: AHT20, BMP280, VEML7700)
         |
         v
anima-broker.service (Body)
  stable_creature.py
  - Reads sensors (exclusive I2C for sensors)
  - Computes anima state
  - Runs learning systems
  - Writes to shared memory
         |
         | /dev/shm/anima_state.json
         v
anima.service (Mind)
  anima --http (MCP Server)
  - Reads from shared memory
  - Owns TFT display + LEDs (exclusive I2C for display)
  - Provides MCP tools
  - Handles external connections
         |
         v
External MCP Clients (Claude Code, Cursor, Claude.ai)
```

**Shared memory backends:** Prefers Redis if available, falls back to JSON file in `/dev/shm/`. Both are atomic and fast.

---

## Service Dependencies

- **Startup:** `anima-broker` starts first, then `anima`
- **Stopping `anima`** does NOT stop broker -- sensors keep reading, face keeps displaying
- **Stopping `anima-broker`** -- server falls back to direct sensor access

---

## Usage

### Restart Only the Mind (MCP Server)

```bash
sudo systemctl restart anima
```
Broker stays running -- no sensor interruption, no I2C conflicts.

### Restart Only the Body (Broker)

```bash
sudo systemctl restart anima-broker
```
Sensors reinitialize cleanly, state remains available.

### Check Status

```bash
sudo systemctl status anima-broker anima
```

### View Logs

```bash
sudo journalctl -u anima -f           # MCP server
sudo journalctl -u anima-broker -f    # Broker
```

---

## Learning Systems (Broker Only)

These modules run in the broker, not the MCP server:

| Module | Purpose | State Location |
|--------|---------|----------------|
| `adaptive_prediction.py` | Temporal pattern learning | Shared memory |
| `agency.py` | TD-learning action values | Shared memory |
| `preferences.py` | Preference evolution | Shared memory |
| `self_model.py` | Self-knowledge beliefs | Shared memory |
| `activity_state.py` | Active/drowsy/resting cycles | Shared memory |
| `learning.py` | Calibration adaptation | `anima_config.yaml` |

Learning state is written to `/dev/shm/anima_state.json` and persisted to disk every 5 minutes.

These modules run in the **server** (not broker):

| Module | Purpose |
|--------|---------|
| `growth/` | Preferences, goals, memories, autobiography |
| `self_reflection.py` | Insight discovery |
| `llm_gateway.py` | LLM reflections (Groq/Llama) |
| `knowledge.py` | Q&A-derived insights |

---

## Shared Memory Schema

```json
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
        "creature_id": "49e14444-...",
        "name": "Lumen",
        "awakenings": 42
    },
    "governance": { ... },
    "learning": {
        "preferences": { "satisfaction": 0.87 },
        "self_beliefs": { ... },
        "agency": { ... }
    }
}
```

---

## Systemd Service Files

| Service | File | Location |
|---------|------|----------|
| `anima.service` | `systemd/anima.service` | `/etc/systemd/system/anima.service` |
| `anima-broker.service` | `systemd/anima-broker.service` | `/etc/systemd/system/anima-broker.service` |

```bash
# Install
sudo cp systemd/anima-broker.service /etc/systemd/system/
sudo cp systemd/anima.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable anima-broker anima
sudo systemctl start anima-broker anima
```

---

## Troubleshooting

### Broker Not Starting
```bash
sudo journalctl -u anima-broker -n 50
```

### MCP Server Waiting for Broker
```bash
sudo systemctl is-active anima-broker
# If not active:
sudo systemctl start anima-broker
```

### I2C Conflicts (Should Not Happen)
```bash
lsof /dev/i2c-1 2>/dev/null || echo 'No I2C access detected'
```

---

## Design History

This architecture solves the original I2C concurrency problem: both `stable_creature.py` and `server.py` needed sensor access, causing bus conflicts. The "Hardware Broker Pattern" (Driver and Passenger model) was implemented in three phases:

1. **Phase 1:** Shared memory layer (`SharedMemoryClient`, `/dev/shm/anima_state.json`) -- broker writes, server reads
2. **Phase 2:** MCP server refactored to read from shared memory with fallback to direct sensors
3. **Phase 3:** Redis backend added for higher performance; auto-detected, falls back to file-based

All three phases are complete and verified. Both scripts can run simultaneously safely.
