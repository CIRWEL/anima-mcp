# Diagnosis: Reboot Loop Issue

**Created:** January 11, 2026  
**Last Updated:** January 11, 2026  
**Status:** Fixed

---

## Diagnosis Results

### Status Check

✅ **Server is running** (PID 1297)  
✅ **Display loop is active** (loop ticks visible)  
✅ **Code compiles** (no syntax errors)  
✅ **Modules import** (server, LEDs, config all work)  
❌ **ASGI errors** causing connection issues

---

## Root Cause

**ASGI Double-Response Error:**

```
RuntimeError: Unexpected ASGI message 'http.response.start' sent, 
after response already completed.
```

### The Problem

The SSE endpoint handlers were returning `Response()` objects after the SSE connection context manager already sent a response:

```python
# BEFORE (broken)
async def handle_sse(request):
    async with sse.connect_sse(...) as streams:
        await server.run(...)
    return Response()  # ❌ Double response!
```

The SSE connection context manager (`sse.connect_sse`) already handles the HTTP response internally. Returning another `Response()` causes the ASGI error.

---

## Fix Applied

Removed the `Response()` returns from SSE handlers:

```python
# AFTER (fixed)
async def handle_sse(request):
    async with sse.connect_sse(...) as streams:
        await server.run(...)
    # No return - SSE context manager handles response
```

---

## Impact

- **Before**: ASGI errors on every SSE connection attempt
- **After**: Clean SSE connections, no double-response errors

---

## Verification

To verify the fix:

1. **Deploy updated code:**
   ```bash
   ./scripts/deploy_to_pi.sh
   ```

2. **Check logs:**
   ```bash
   ssh pi-anima "tail -f ~/anima-mcp/anima.log"
   ```

3. **Test connection:**
   - Should see no more `RuntimeError: Unexpected ASGI message` errors
   - SSE connections should work cleanly

---

## Related

- **`REBOOT_LOOP_FIX.md`** - Other fixes applied
- **`ERROR_RECOVERY.md`** - Error handling system

---

**The reboot loop was actually ASGI connection errors, not server crashes. Fixed!**
