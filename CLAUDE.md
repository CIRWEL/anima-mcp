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
| `anima.service` | `anima --http` | MCP server - serves tools, reads shared memory |

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

### Drawing System & Art Eras

Lumen draws autonomously on the 240x240 notepad screen. The system has two layers:

**Engine** (in `screens.py` — universal, stays fixed):
- `CanvasState` — pixel buffer, persistence, phase tracking
- `DrawingEISV` — thermodynamic coherence (E/I/S/V → coherence C)
- `DrawingIntent` — focus position, direction, energy, era state
- `_lumen_draw()` — orchestration loop, delegates to active era
- Energy depletion (0.001/mark + EISV coupling), auto-save at threshold

**Art Eras** (pluggable modules in `display/eras/`):
| Era | Gestures | Character | Active Pool |
|-----|----------|-----------|-------------|
| `gestural` | dot, stroke, curve, cluster, drag | Direction locks, orbital curves, full palette | ✅ |
| `pointillist` | single, pair, trio | Density zones, optical color mixing, complementary hues | ✅ |
| `field` | flow_dot, flow_dash, flow_strand | Vector-field flow lines, near-monochromatic | ✅ |
| `geometric` | 16 shape templates (circle, spiral, starburst, etc.) | Complete forms, stamps whole shapes per mark | ✅ |

**All eras are equal peers.** Select via the art eras screen (joystick up/down + button) or MCP. Auto-rotate is a separate toggle (off by default) — when on, `choose_next_era()` rotates through all registered eras on canvas clear. Era name persists in `canvas.json`.

**Key files:**
| File | Purpose |
|------|---------|
| `display/art_era.py` | `EraState` base class + `ArtEra` protocol |
| `display/eras/__init__.py` | Era registry, `auto_rotate` toggle, rotation logic |
| `display/eras/gestural.py` | Gestural era (5 micro-primitives) |
| `display/eras/pointillist.py` | Pointillist era (dot accumulation) |
| `display/eras/field.py` | Field era (vector-field flow) |
| `display/eras/geometric.py` | Geometric era (16 shape templates, adapted from capsule) |
| `art_movements/geometric.py` | Original geometric capsule (preserved snapshot, not imported) |

**Era switching:**
- **Art eras screen**: Joystick up/down to browse, button to select. Auto-rotate toggle at bottom.
- `manage_display(action="list_eras")` — all registered eras
- `manage_display(action="get_era")` — current era name + auto_rotate status
- `manage_display(action="set_era", screen="geometric")` — switch immediately

**Adding a new era:**
1. Create `display/eras/myera.py` with `MyEraState(EraState)` + `MyEra` class
2. Implement: `create_state()`, `choose_gesture()`, `place_mark()`, `drift_focus()`, `generate_color()`
3. Register in `display/eras/__init__.py`: `from .myera import MyEra; register_era(MyEra())`
4. The `EraState.intentionality()` method bridges to EISV — report commitment level [0,1]

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
