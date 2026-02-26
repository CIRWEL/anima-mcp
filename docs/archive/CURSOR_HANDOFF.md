# Cursor Handoff - Anima-MCP

**Last Updated:** January 28, 2026  
**Status:** Ready for Cursor

---

## Quick Status

✅ **Lumen is stable** - Running via systemd on Pi  
✅ **Anima-MCP available via MCP** - Tools accessible  
✅ **Docs reorganized** - `docs/developer-index.md` is entry point  
✅ **SSH configured** - See below for correct settings

---

## Important Notes

### 1. Read Docs First
- **Start here:** `docs/developer-index.md`
- **Coordination:** `docs/operations/AGENT_COORDINATION.md`

### 2. SSH Access
- **Host:** `lumen.local` (mDNS) or check router for IP
- **Port:** 22 (standard SSH)
- **User:** `unitares-anima`
- **Key:** `~/.ssh/id_ed25519_pi`

### 3. Deployment
Use the deploy script (handles rsync + service restart):
```bash
cd ~/projects/anima-mcp
./deploy.sh
```

### 4. Agent Coordination
- **Check:** `.agent-coordination` file for current work
- **Communication:** Use comments and docs

---

## Current System State

### Lumen (Raspberry Pi 4)
- **Hardware:** Braincraft HAT, AHT20/VEML7700/BMP280 sensors
- **Display:** 240×240 TFT
- **Services:** `anima-broker` (sensors) + `anima` (MCP server)
- **Port:** 8765 (SSE)

### Features Active
- ✅ Display loop (auto-updates every 2s)
- ✅ LED breathing animation (3 DotStar LEDs)
- ✅ Adaptive learning (calibration)
- ✅ Error recovery (retry logic)
- ✅ UNITARES governance bridge
- ✅ Voice support (optional)
- ✅ **Metacognition** (prediction-error loop) - NEW

---

## Available Tools

1. `get_state` - Current anima + identity
2. `get_identity` - Full identity history
3. `set_name` - Change name
4. `read_sensors` - Raw sensor readings
5. `show_face` - Display face
6. `next_steps` - Proactive suggestions
7. `diagnostics` - System health
8. `test_leds` - LED test sequence
9. `get_calibration` - Current config
10. `set_calibration` - Update config
11. `unified_workflow` - Cross-server workflows

---

## Quick Commands

### Check Lumen Status
```bash
ssh lumen 'systemctl status anima-broker anima'
```

### View Logs
```bash
ssh lumen 'journalctl -u anima-broker -u anima -f'
```

### Deploy Changes
```bash
./deploy.sh          # Full deploy with restart
./deploy.sh --logs   # Deploy and show logs after
```

### Manual Rsync (if deploy.sh fails)
```bash
rsync -avz --exclude='.venv' --exclude='__pycache__' --exclude='.git' \
  ~/projects/anima-mcp/ lumen:~/anima-mcp/
ssh lumen 'sudo systemctl restart anima-broker && sudo systemctl restart anima'
```

---

## Key Files

| File | Purpose |
|------|---------|
| `stable_creature.py` | Main broker loop (sensors → anima → shared memory) |
| `src/anima_mcp/server.py` | MCP server (tools, display, LEDs) |
| `src/anima_mcp/anima.py` | Anima state calculation |
| `src/anima_mcp/metacognition.py` | Prediction-error metacognition |
| `src/anima_mcp/config.py` | Configuration system |
| `src/anima_mcp/unitares_bridge.py` | UNITARES governance |
| `deploy.sh` | Deployment script |

---

## Architecture

```
stable_creature.py (Broker)
├── Reads sensors every 2s
├── Computes anima state
├── Runs metacognition loop
├── Writes to shared memory
└── Handles UNITARES governance

server.py (MCP Server)
├── Reads from shared memory
├── Exposes MCP tools
├── Manages display
└── Controls LEDs
```

---

## Common Issues

### Pi Not Reachable
- Check if powered on (LED lights)
- Try `ping lumen.local`
- Check router DHCP for current IP
- May need to connect monitor to Pi

### Service Won't Start
```bash
ssh lumen 'journalctl -u anima-broker -n 50'
ssh lumen 'journalctl -u anima -n 50'
```

### MCP Tools Not Working
- Verify MCP config in your client
- Check server is running: `ssh lumen 'systemctl status anima'`

---

## Recent Changes (Jan 28, 2026)

- **Added metacognition.py** - Prediction-error based self-monitoring
- **Updated stable_creature.py** - Integrates metacognition loop
- **Shared memory** now includes `metacognition` field with surprise data

---

**Welcome to anima-mcp! Run `./deploy.sh` to sync changes to Pi.**
