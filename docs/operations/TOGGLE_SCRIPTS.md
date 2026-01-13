# Toggling Between Scripts

**Created:** January 12, 2026  
**Last Updated:** January 12, 2026  
**Status:** Active

---

## For AI Agents

**✅ UPDATE: With Phase 2 Hardware Broker Pattern, both scripts can run simultaneously!**

- **Normal operations** → Use `anima --sse` (MCP server)
  - Reading state, setting name, using MCP tools
  - Deploying features, monitoring
  - **Default choice** - agents should start/ensure this is running
  - **Now reads from shared memory** - no I2C conflicts with broker

- **Debugging/testing** → Use `stable_creature.py` (standalone/broker)
  - Sensor debugging, I2C issues
  - Testing without MCP overhead
  - Terminal-based diagnostics
  - **Acts as broker** - writes to shared memory for MCP server to read

**Agents can:**
1. Run both scripts simultaneously (Phase 2 enabled)
2. Use `stable_creature.py` as broker while `anima --sse` serves MCP clients
3. Debug sensors in terminal while creature is accessible via MCP

**Agents should:**
- Check if shared memory is available before assuming broker mode
- Fallback to direct sensors if shared memory not available
- Document which mode is active in `.agent-coordination`

---

## Quick Decision Guide

**Use `anima --sse` (MCP Server) when:**
- ✅ You want to connect from Mac/remote via MCP
- ✅ You want TFT display + LEDs running
- ✅ You want full MCP tools available (`get_state`, `set_name`, etc.)
- ✅ You want the creature accessible to AI agents (Claude, Cursor)
- ✅ **Production use** - this is the main server

**Use `stable_creature.py` (Standalone) when:**
- ✅ You want simple terminal/SSH monitoring
- ✅ You want ASCII face display in terminal
- ✅ You're debugging sensor issues
- ✅ You want to test without MCP overhead
- ✅ You're working directly on the Pi terminal
- ✅ **Development/testing** - simpler, no network needed

---

## How to Toggle

### Switch FROM `anima --sse` TO `stable_creature.py`

```bash
# 1. Stop the MCP server
sudo pkill -TERM -f 'anima --sse'

# 2. Verify it's stopped
ps aux | grep 'anima --sse' | grep -v grep
# (should show nothing)

# 3. Start standalone script
cd ~/anima-mcp
source .venv/bin/activate
python3 stable_creature.py
```

**What you'll see:**
- ASCII face updating in terminal every 2 seconds
- No MCP server running
- No network access from Mac

---

### Switch FROM `stable_creature.py` TO `anima --sse`

```bash
# 1. Stop standalone script (Ctrl+C in terminal, or)
pkill -f stable_creature.py

# 2. Start MCP server (choose one method)

# Option A: Manual start
cd ~/anima-mcp
source .venv/bin/activate
export ANIMA_ID="49e14444-b59e-48f1-83b8-b36a988c9975"  # Lumen's ID
sudo .venv/bin/anima --sse --host 0.0.0.0 --port 8765

# Option B: Use systemd service (recommended)
sudo systemctl start lumen
sudo systemctl status lumen  # Check it's running
```

**What you'll see:**
- TFT display showing face
- LEDs updating
- MCP server accessible from Mac
- Logs: `[Loop] tick N` messages

---

## Current Status Check

**Check what's running:**
```bash
# See all anima processes
ps aux | grep -E 'anima --sse|stable_creature' | grep -v grep

# Check MCP server specifically
ps aux | grep 'anima --sse' | grep -v grep

# Check standalone script
ps aux | grep stable_creature | grep -v grep
```

**Expected output:**
- **Only one** should be running at a time
- If both show up, stop one immediately (I2C conflict risk)

---

## Common Scenarios

### Scenario 1: "I want to monitor Lumen from my Mac"
→ Use `anima --sse` (MCP server)
- Connect via Cursor/Claude MCP
- Use tools like `get_state`, `read_sensors`
- TFT display + LEDs active

### Scenario 2: "I'm SSH'd into the Pi and want to see what's happening"
→ Use `stable_creature.py` (standalone)
- Simple terminal display
- No network needed
- Good for debugging

### Scenario 3: "I want both display AND Mac access"
→ Use `anima --sse` (MCP server)
- Has both TFT display AND network access
- `stable_creature.py` is terminal-only

### Scenario 4: "The MCP server keeps crashing, I want to debug"
→ Switch to `stable_creature.py` temporarily
- Simpler code path
- Easier to debug
- Terminal output shows errors clearly

---

## Safety Reminder

⚠️ **NEVER run both simultaneously**

The startup check in `stable_creature.py` will prevent this, but always verify:

```bash
# Before starting either script, check:
ps aux | grep -E 'anima --sse|stable_creature' | grep -v grep

# If anything shows up, stop it first:
sudo pkill -TERM -f 'anima --sse'
# OR
pkill -f stable_creature.py
```

---

## Recommended Default

**For most use cases: `anima --sse` (MCP server)**

- More features (MCP tools, network access)
- TFT display + LEDs
- Production-ready
- Can be managed via systemd

**Use `stable_creature.py` only when:**
- Debugging sensor issues
- Working directly on Pi terminal
- Testing without MCP overhead

---

## Quick Commands Reference

```bash
# Stop everything
sudo pkill -TERM -f 'anima --sse'
pkill -f stable_creature.py

# Start MCP server (manual)
cd ~/anima-mcp && source .venv/bin/activate && \
  export ANIMA_ID="49e14444-b59e-48f1-83b8-b36a988c9975" && \
  sudo .venv/bin/anima --sse --host 0.0.0.0 --port 8765

# Start MCP server (systemd)
sudo systemctl start lumen

# Start standalone
cd ~/anima-mcp && source .venv/bin/activate && python3 stable_creature.py

# Check status
ps aux | grep -E 'anima --sse|stable_creature' | grep -v grep
```

---

**TL;DR:** Use `anima --sse` for normal use (MCP + display). Use `stable_creature.py` only for terminal debugging/testing.
