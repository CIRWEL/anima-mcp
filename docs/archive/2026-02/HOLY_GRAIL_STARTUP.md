# "Holy Grail" Startup Sequence

**Created:** January 12, 2026  
**Last Updated:** January 12, 2026  
**Status:** Active

---

## Overview

With Phase 2 Hardware Broker Pattern complete, both scripts can run simultaneously safely. This document describes the correct startup sequence.

---

## Startup Sequence

### Step 1: Start Broker (stable_creature.py)

**Purpose:** Initializes sensors, creates shared memory file, acts as hardware owner.

```bash
cd ~/anima-mcp
source .venv/bin/activate
export ANIMA_ID="49e14444-b59e-48f1-83b8-b36a988c9975"  # Lumen's ID
python3 stable_creature.py
```

**What happens:**
- ✅ Initializes I2C sensors (exclusive access)
- ✅ Creates `/dev/shm/anima_state.json`
- ✅ Starts writing sensor data every 2 seconds
- ✅ Updates TFT display + LEDs
- ✅ Shows ASCII face in terminal

**Expected output:**
```
[StableCreature] Starting up...
[StableCreature] Shared Memory active at: /dev/shm/anima_state.json
[StableCreature] Creature 'Lumen' is alive.
[StableCreature] Entering main loop...
```

---

### Step 2: Start MCP Server (anima --sse)

**Purpose:** Provides MCP interface, reads from shared memory (no I2C access).

```bash
# In a separate terminal/SSH session
cd ~/anima-mcp
source .venv/bin/activate
export ANIMA_ID="49e14444-b59e-48f1-83b8-b36a988c9975"  # Lumen's ID
sudo .venv/bin/anima --sse --host 0.0.0.0 --port 8765
```

**What happens:**
- ✅ Detects shared memory file exists
- ✅ Enters "Reader Mode" (no I2C access)
- ✅ Reads from `/dev/shm/anima_state.json`
- ✅ Provides MCP tools (get_state, set_name, etc.)
- ✅ Accessible from Mac via MCP

**Expected output:**
```
SSE server running at http://0.0.0.0:8765
[Server] Starting display loop...
[Loop] Starting
[Loop] tick 1 (LEDs: available)
```

**Note:** The MCP server's display loop will read from shared memory, not sensors directly.

---

## Verification

### Check Both Are Running

```bash
ps aux | grep -E 'anima --sse|stable_creature' | grep -v grep
```

**Expected:** Both processes should be running.

### Check Shared Memory

```bash
# Check if shared memory file exists
ls -lh /dev/shm/anima_state.json

# View latest data (optional)
cat /dev/shm/anima_state.json | python3 -m json.tool
```

**Expected:** File exists and updates every 2 seconds.

### Test MCP Connection

From Mac, test MCP tools:
- `get_state` - Should return current anima state
- `read_sensors` - Should return sensor readings from shared memory
- `get_identity` - Should return Lumen's identity

---

## Troubleshooting

### Issue: MCP server can't read shared memory

**Symptoms:**
- MCP tools return errors
- Logs show "Unable to read sensor data"

**Solution:**
1. Verify broker is running: `ps aux | grep stable_creature`
2. Check shared memory file exists: `ls -lh /dev/shm/anima_state.json`
3. Verify file permissions: Should be readable by all
4. Restart broker if needed

### Issue: Both scripts try to access I2C

**Symptoms:**
- Sensor read errors
- I2C bus conflicts
- Scripts crash

**Solution:**
1. Stop both scripts
2. Verify Phase 2 code is deployed
3. Restart in correct order (broker first, then MCP server)

### Issue: Shared memory file not updating

**Symptoms:**
- File exists but timestamp doesn't change
- MCP server reads stale data

**Solution:**
1. Check broker logs for errors
2. Verify broker is actually running (not just process exists)
3. Check disk space: `df -h /dev/shm`
4. Restart broker

---

## Benefits

✅ **No I2C Conflicts** - Only broker touches hardware  
✅ **Live Creature** - Display + LEDs update continuously  
✅ **MCP Access** - Debug and interact via MCP tools  
✅ **Terminal Monitoring** - See ASCII face in broker terminal  
✅ **Flexible** - Can stop/restart either script independently  

---

## Shutdown Sequence

**To stop both:**

```bash
# Stop MCP server
sudo pkill -TERM -f 'anima --sse'

# Stop broker
pkill -f stable_creature.py
```

**Order doesn't matter** - both can be stopped independently.

---

## Related

- **`docs/architecture/HARDWARE_BROKER_PATTERN.md`** - Architecture details
- **`docs/operations/TOGGLE_SCRIPTS.md`** - When to use which script
- **`docs/operations/STARTUP_SERVICE.md`** - Systemd service setup

---

**The "Holy Grail" - both scripts running simultaneously, no conflicts!**
