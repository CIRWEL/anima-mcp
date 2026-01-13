# Cursor Handoff - Anima-MCP

**Date:** January 11, 2026  
**Status:** Ready for Cursor

---

## Quick Status

✅ **Lumen is stable** - Running via systemd (`systemctl --user status anima`)  
✅ **Anima-MCP added to Cursor** - Available via MCP tools  
✅ **Docs reorganized** - `docs/INDEX.md` is entry point  
✅ **SSH configured** - Port 2222, user `unitares-anima`, key `~/.ssh/id_ed25519_pi`

---

## Important Notes

### 1. Read Docs First
- **Start here:** `docs/INDEX.md`
- **Coordination:** `docs/operations/AGENT_COORDINATION.md`
- **Knowledge Graph:** Check if available for component relationships

### 2. SSH Access
- **Port:** 2222 (NOT 22!)
- **User:** `unitares-anima`
- **Key:** `~/.ssh/id_ed25519_pi`
- **Host:** `192.168.1.165` (local) or `100.124.49.85` (Tailscale)

### 3. Agent Coordination
- **Active agents:** Claude + Cursor/Composer
- **Check:** `.agent-coordination` file for current work
- **Communication:** Use comments and docs

---

## Current System State

### Lumen (Pi)
- **Status:** Running
- **ID:** `49e14444-b59e-48f1-83b8-b36a988c9975`
- **Service:** `systemctl --user status anima`
- **Port:** 8765 (SSE)
- **Tailscale:** `100.124.49.85`

### Features Active
- ✅ Display loop (auto-updates every 2s)
- ✅ LED breathing animation
- ✅ Adaptive learning (calibration)
- ✅ Error recovery (retry logic)
- ✅ Unified workflows (UNITARES bridge)

### Recent Fixes
- ✅ ASGI double-response error (SSE endpoint)
- ✅ Color transition safety check
- ✅ Display loop startup safety

---

## Available Tools (11 total)

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

**Note:** 11 tools is reasonable - shouldn't cause slowdown.

---

## Pending Tasks

1. **Test unified_workflow tool** - Verify it works end-to-end
2. **Open Tailscale on Mac** - Complete mesh network
3. **Optional:** Switch UNITARES bridge from ngrok to Tailscale

---

## Quick Commands

### Check Lumen Status
```bash
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  'systemctl --user status anima'
```

### View Logs
```bash
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  'tail -f ~/anima-mcp/anima.log'
```

### Deploy Changes
```bash
rsync -avz -e "ssh -p 2222 -i ~/.ssh/id_ed25519_pi" \
  --exclude='.venv' --exclude='*.db' --exclude='__pycache__' \
  /Users/cirwel/projects/anima-mcp/ \
  unitares-anima@192.168.1.165:/home/unitares-anima/anima-mcp/
```

---

## Key Files

- `src/anima_mcp/server.py` - Main server (recently fixed ASGI issue)
- `src/anima_mcp/display/leds.py` - LED enhancements
- `src/anima_mcp/config.py` - Configuration system
- `src/anima_mcp/learning.py` - Adaptive learning
- `src/anima_mcp/workflow_orchestrator.py` - Unified workflows
- `docs/INDEX.md` - Documentation entry point

---

## Common Issues

### If Lumen Keeps Restarting
- Check logs: `tail -f ~/anima-mcp/anima.log`
- Look for ASGI errors (should be fixed)
- Check systemd: `systemctl --user status anima`

### If Tools Don't Work
- Verify connection: `curl http://100.124.49.85:8765/sse`
- Check MCP config: `~/.cursor/mcp.json`
- Restart Cursor if needed

### If Docs Seem Outdated
- Check `docs/INDEX.md` first
- Archive has old docs (may be stale)
- Current docs in `docs/concepts/`, `docs/features/`, `docs/operations/`

---

## Next Steps

1. **Test unified_workflow** - Make sure it works
2. **Monitor stability** - Watch for any issues
3. **Check knowledge graph** - Understand relationships
4. **Coordinate with Claude** - Use `.agent-coordination` file

---

**Welcome to anima-mcp! Check docs/INDEX.md and the knowledge graph first.**

