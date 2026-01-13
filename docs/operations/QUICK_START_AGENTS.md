# Quick Start for Agents

**For Claude, Composer, and other AI agents working on anima-mcp**

---

## 🛑 STOP - Read Docs First

**Before writing ANY code, check the docs.** Most problems have already been solved.

1. **`docs/INDEX.md`** - Start here, find everything
2. **This file's "Code Gotchas" section** - Learn from past agent pain
3. **`docs/operations/RESTART_GUIDE.md`** - When things freeze

**Rule: If you're about to try something complex, check docs first. The simple solution is probably documented.**

---

## Before You Start

### 1. Read These First
- ✅ `docs/INDEX.md` - **START HERE** - Find all docs
- ✅ `README.md` - Project overview
- ✅ `docs/AGENT_COORDINATION.md` - How to coordinate

### 2. Check Current Work
- ✅ `.agent-coordination` - What's being worked on
- ✅ Recent git commits / file timestamps
- ✅ Knowledge graph (if available)

### 3. Understand the System
- ✅ `docs/CONFIGURATION_GUIDE.md` - Config system
- ✅ `docs/ERROR_RECOVERY.md` - Error handling
- ✅ `docs/ADAPTIVE_LEARNING.md` - Learning system
- ⚠️ **`docs/operations/REBOOT_LOOP_PREVENTION.md`** - **CRITICAL: Port 8765 trap!**

---

## Common Tasks

### Adding a Feature

1. **Check docs** - Does it exist? Should it?
2. **Check code** - Similar features? Patterns?
3. **Check running script** - Use `anima --sse` for normal work, `stable_creature.py` only for debugging
4. **Implement** - Follow existing patterns
5. **Update docs** - Document new feature
6. **Test** - Verify it works
7. **Update `.agent-coordination`** - Note what you did

### Fixing a Bug

1. **Reproduce** - Understand the issue
2. **🚨 CRITICAL: Check port 8765 trap first!** - If service won't start or reboot loops:
   ```bash
   ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
     "lsof -i :8765 && pkill -f 'anima.*--sse'; systemctl --user reset-failed anima"
   ```
   See `docs/operations/REBOOT_LOOP_PREVENTION.md` for details.
3. **Check logs** - What's actually happening?
4. **Check docs** - Known issues? Workarounds?
5. **Choose script** - Use `stable_creature.py` for sensor/I2C debugging, `anima --sse` otherwise
6. **Toggle if needed** - Automatically stop conflicting script, start appropriate one
7. **Fix** - Minimal change, maximum impact
8. **Test** - Verify fix works
9. **Update docs** - Document fix
10. **Restore default** - Switch back to `anima --sse` if you used `stable_creature.py`

### Changing Config

1. **Read `docs/CONFIGURATION_GUIDE.md`**
2. **Check `anima_config.yaml.example`**
3. **Understand impact** - What uses this config?
4. **Change** - Update config.py if needed
5. **Update docs** - Document change
6. **Test** - Verify behavior

---

## Code Patterns

### Error Handling
```python
from .error_recovery import safe_call, retry_with_backoff

# Use safe_call for non-critical operations
result = safe_call(lambda: risky_operation(), default=None)

# Use retry_with_backoff for transient failures
result = retry_with_backoff(lambda: operation(), config=RetryConfig())
```

### Configuration
```python
from .config import get_calibration, get_display_config

# Get current config
cal = get_calibration()
display = get_display_config()

# Use config values
if temp < cal.ambient_temp_min:
    # ...
```

### Logging
```python
import sys

# Use stderr for operational logs
print(f"[Component] Message", file=sys.stderr, flush=True)
```

---

## Documentation Standards

### When Creating Docs

```markdown
# Title

**Created:** {today_full()}  
**Last Updated:** {today_full()}  
**Status:** Active

---

## Overview

Brief description...

## Details

Content...

## Related

- **`OTHER_DOC.md`** - Related docs
```

### When Updating Code

- Add docstrings to new functions
- Update existing docstrings if behavior changes
- Add comments for complex logic
- Update README if adding tools/features

---

## Testing Checklist

Before considering work "done":

- [ ] Code compiles (`python3 -m py_compile`)
- [ ] Imports work (`python3 -c 'import ...'`)
- [ ] No obvious errors
- [ ] Docs updated
- [ ] `.agent-coordination` updated

---

## Common Pitfalls

### ❌ Don't Skip Docs
- Always check `docs/` before implementing
- Update docs with code changes
- Don't assume behavior

### ❌ Don't Break Patterns
- Follow existing code style
- Use existing abstractions
- Don't reinvent wheels

### ❌ Don't Work in Isolation
- Check `.agent-coordination`
- Leave notes for other agents
- Coordinate on shared files

---

## 🚨 Code Gotchas (Learn from Our Pain)

These are specific issues that have bitten agents before:

### EISV Keys Are Single Letters

**Wrong:**
```python
eisv.get("energy")  # Returns None!
eisv.get("integrity")  # Returns None!
```

**Correct:**
```python
eisv.get("E")  # Energy
eisv.get("I")  # Integrity
eisv.get("S")  # Entropy (Stability)
eisv.get("V")  # Void
```

### Color Constants Are Local to Functions in screens.py

When editing `src/anima_mcp/display/screens.py`, color constants like `CYAN`, `WHITE`, `LIGHT_CYAN` are defined **inside each function**, not globally. If you:
1. Change a color constant name
2. Grep only part of the function
3. Miss some references

You'll get `NameError: name 'GRAY' is not defined` at runtime.

**Fix:** After changing colors, grep the ENTIRE function for the old color name.

### Display Frozen? Just Restart the Service

Don't try:
- ❌ Different ports (8766, 8767)
- ❌ localhost binding
- ❌ Writing display-only scripts
- ❌ Complex debugging

**Just do:**
```bash
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  "systemctl --user restart anima"
```

The systemd service handles everything. See `docs/operations/RESTART_GUIDE.md`.

### HTTP Server Crashes (SSE Handler)

If you see `TypeError: 'NoneType' object is not callable` in Starlette:
- SSE handlers in `server.py` must return `Response(status_code=200)`
- Even though actual responses go through ASGI, Starlette expects a return value
- Add try/except to handlers to prevent crashes from malformed requests

### Governance Data Flow (Broker → Shared Memory → MCP Server)

The **broker** (`stable_creature.py`) calls UNITARES and writes governance to shared memory.
The **MCP server** (`server.py`) reads governance FROM shared memory - it doesn't call UNITARES directly.

If governance shows "waiting..." or null on diagnostics:
1. Check broker is running: `systemctl --user status anima-broker`
2. Check shared memory has governance: `cat /dev/shm/anima_state.json | python3 -c "import sys,json; print(json.load(sys.stdin).get('governance'))"`
3. If broker has governance but display doesn't, the MCP server isn't reading shared memory correctly

---

## Quick Reference

### Key Files
- `src/anima_mcp/server.py` - Main server
- `src/anima_mcp/anima.py` - Core anima logic
- `src/anima_mcp/config.py` - Configuration
- `src/anima_mcp/learning.py` - Adaptive learning
- `docs/` - All documentation

### Key Tools
- `get_state` - Current anima state
- `unified_workflow` - Cross-server workflows
- `diagnostics` - System health
- `get_calibration` - Current config

---

**Remember: Check docs first, coordinate with other agents, update docs after changes.**
