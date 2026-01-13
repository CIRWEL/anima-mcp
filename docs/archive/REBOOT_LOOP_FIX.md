# Reboot Loop Fix

**Created:** January 11, 2026  
**Last Updated:** January 11, 2026  
**Status:** Active

---

## Issue

Lumen was rebooting in a loop, likely due to uncaught exceptions in the display loop or startup sequence.

---

## Fixes Applied

### 1. Color Transition Safety Check

**Problem:** `_last_colors` could be `[None, None, None]` even when `_last_state` exists, causing potential AttributeError.

**Fix:** Added check for `_last_colors[0] is not None` before applying transitions:

```python
# Before
if self._color_transitions_enabled and self._last_state:

# After  
if self._color_transitions_enabled and self._last_state and self._last_colors[0] is not None:
```

### 2. Display Loop Startup Safety

**Problem:** `start_display_loop()` might be called before event loop is running, causing RuntimeError.

**Fix:** Added event loop check and error handling:

```python
def start_display_loop():
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No event loop running - will be started later
        return
    
    # ... create task ...
```

---

## Debugging Steps

If rebooting continues:

1. **Check logs:**
   ```bash
   ssh pi-anima "journalctl -u anima -n 100"
   # or
   ssh pi-anima "tail -f ~/anima-mcp/anima.log"
   ```

2. **Check for Python errors:**
   ```bash
   ssh pi-anima "cd ~/anima-mcp && python3 -m py_compile src/anima_mcp/server.py"
   ```

3. **Test display loop manually:**
   ```bash
   ssh pi-anima "cd ~/anima-mcp && source .venv/bin/activate && python3 -c 'from src.anima_mcp.server import start_display_loop; import asyncio; asyncio.run(start_display_loop())'"
   ```

4. **Check systemd service:**
   ```bash
   ssh pi-anima "systemctl status anima"
   ```

---

## Related

- **`ERROR_RECOVERY.md`** - Error handling system
- **`LED_ENHANCEMENTS.md`** - LED features

---

**Fixes prevent uncaught exceptions from crashing the server.**
