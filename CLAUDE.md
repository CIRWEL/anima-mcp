# Anima MCP - Agent Instructions

## Architecture

Two systemd services run on the Pi:

```
anima-creature.service      anima.service
(hardware broker)           (MCP server)
     |                           |
     | writes to                 | reads from
     +---> /dev/shm/anima_state.json <--+
```

| Service | Command | Role |
|---------|---------|------|
| `anima-creature.service` | `anima-creature` | Hardware broker - owns I2C, runs learning |
| `anima.service` | `anima --sse` | MCP server - serves tools, reads shared memory |

**Both must run for full functionality.** The broker writes sensor data and learning state to shared memory; the server reads it.

### Entry Points (pyproject.toml)

| Command | Module | Role |
|---------|--------|------|
| `anima` | `anima_mcp.server:main` | MCP server |
| `anima-creature` | `anima_mcp.stable_creature:main` | Hardware broker |

### Learning Systems (run in broker only)

These modules run in `stable_creature.py`, not in `server.py`:

| Module | Purpose |
|--------|---------|
| `adaptive_prediction.py` | Temporal pattern learning |
| `memory_retrieval.py` | Context-aware memory search |
| `agency.py` | TD-learning action selection |
| `preferences.py` | Preference evolution |
| `self_model.py` | Self-knowledge accumulation |
| `activity_state.py` | Active/drowsy/resting cycles |
| `learning.py` | Calibration adaptation |

**Do NOT delete these files based on import analysis of server.py alone.**

### Neural System

Lumen uses **computational proprioception** - no real EEG hardware. Neural bands are derived from system metrics:

| Band | Derived From | Meaning |
|------|--------------|---------|
| Delta | Low CPU + low memory | Deep stability/rest |
| Theta | I/O wait time | Processing/integration |
| Alpha | Memory headroom | Relaxed awareness |
| Beta | CPU usage | Active processing |
| Gamma | High CPU activity | Intense focus |

Source: `computational_neural.py` (used by both `pi.py` and `mock.py` sensors)

### Activity States

The `ActivityManager` (in broker) controls Lumen's wakefulness:

| State | Brightness | Trigger |
|-------|------------|---------|
| ACTIVE | 100% | Recent interaction, high activity score |
| DROWSY | 60% | 30+ min inactivity, moderate score |
| RESTING | 35% | 60+ min inactivity, night time, darkness |

## Systemd Services

```bash
# Check status
sudo systemctl status anima anima-creature

# Restart both
sudo systemctl restart anima-creature anima

# View logs
sudo journalctl -u anima-creature -f
sudo journalctl -u anima -f
```

Service files: `/etc/systemd/system/anima.service`, `/etc/systemd/system/anima-creature.service`

## Git Commit Conventions

- Do NOT include Co-Authored-By lines in commit messages

## Testing

```bash
python3 -m pytest tests/ -x -q
```

## Deploying to Pi

```bash
git push
# Then from any MCP client:
mcp__anima__git_pull(restart=true)
```

Or manually:
```bash
ssh unitares-anima@100.89.201.36 'cd ~/anima-mcp && git pull && sudo systemctl restart anima-creature anima'
```

## UNITARES Integration

The broker connects to UNITARES governance via Tailscale:

```
UNITARES_URL=http://100.96.201.46:8767/mcp/
```

Maps anima to EISV: Warmth→Energy, Clarity→Integrity, 1-Stability→Entropy, 1-Presence→Void

## Shared Memory Schema

`/dev/shm/anima_state.json`:
```json
{
  "updated_at": "...",
  "data": {
    "readings": { "cpu_temp_c": ..., "eeg_delta_power": ... },
    "anima": { "warmth": 0.36, "clarity": 0.73, ... },
    "activity": { "level": "active", "reason": "engaged" },
    "learning": {
      "preferences": { "satisfaction": 0.87 },
      "self_beliefs": { "stability_recovery": { "confidence": 0.68 } },
      "agency": { "action_values": { "focus_attention": 0.22 } }
    }
  }
}
```
