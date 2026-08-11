# Broker Architecture -- Body & Mind Separation

**Last Updated:** August 11, 2026

---

## Overview

Lumen runs as two systemd services:

1. **`anima-broker.service`** -- Lumen's **Body** (Hardware Broker)
   - Owns I2C sensors, writes to shared memory
   - Sole writer for embodied learning snapshots
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
  - Writes preferences + self-model snapshots
  - Drains durable server learning events
  - Writes to shared memory
         |
         | /dev/shm/anima_state.json
         v
anima.service (Mind)
  anima --http (MCP Server)
  - Reads from shared memory
  - Owns TFT display + LEDs (exclusive I2C for display)
  - Owns the action policy and growth database
  - Reads broker-owned learning snapshots
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
- **Stopping `anima-broker`** -- server has no fresh sensor state. Its deployed
  `ANIMA_SENSORS_BACKEND=shm` safeguard prevents direct sensor fallback from
  opening a second I2C handle.

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

## Learning Ownership

Broker-owned learning:

| Module | Purpose | State Location |
|--------|---------|----------------|
| `adaptive_prediction.py` | Temporal pattern learning | Shared memory |
| `preferences.py` | Preference evolution | `~/.anima/preferences.json` |
| `self_model.py` | Self-knowledge beliefs | `~/.anima/self_model.json` |
| `activity_state.py` | Active/drowsy/resting cycles | Shared memory |

The server reads the JSON snapshots but cannot save them. Server-originated
question evidence, Q&A-derived belief evidence, and meta-learning weight
changes are atomically queued under `~/.anima/learning_inbox/`; the broker
applies and persists them as the sole writer.

Server-owned learning:

| Module | Purpose |
|--------|---------|
| `agency.py` | TD action selection (the only active action learner) |
| `learning.py` | Calibration adaptation |
| `growth/` | Preferences, goals, memories, autobiography |
| `self_reflection.py` | Insight discovery |
| `llm_gateway.py` | LLM reflections (Groq/Llama) |
| `knowledge.py` | Q&A-derived insights |

The historical broker agency loop and its separate
`~/anima-mcp/anima.db` table are retained only for rollback. They stay off
unless `ANIMA_BROKER_AGENCY_ENABLED=true` is explicitly set.

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
2. **Phase 2:** MCP server refactored to read from shared memory
3. **Phase 3:** Redis backend added for higher performance; auto-detected, falls back to file-based
4. **Phase 4:** Deployed server pinned to the SHM sensor backend; embodied
   learned-state snapshots made single-writer; duplicate broker agency retired

All four phases are complete. Both services can run simultaneously without
sharing sensor or learned-snapshot write ownership.
