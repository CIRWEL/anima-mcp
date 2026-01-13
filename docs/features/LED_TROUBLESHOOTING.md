# LED Troubleshooting Guide

**Created:** January 11, 2026  
**Last Updated:** January 11, 2026  
**Status:** Active

---

## Problem: LEDs Not Updating

If LEDs are static (not changing) or not working, follow these diagnostic steps.

---

## Quick Diagnostics

### 1. Test LEDs Directly

Run the LED test script on the Pi:

```bash
cd ~/anima-mcp
python3 scripts/test_leds.py
```

This will:
- Test LED hardware initialization
- Test individual LED control
- Test brightness control
- Test anima state mapping
- Test continuous updates

**Expected:** All tests should pass. If LEDs don't work here, it's a hardware/library issue.

---

### 2. Check Display Loop Status

Run the display loop diagnostic:

```bash
python3 scripts/check_display_loop.py
```

This checks:
- Component availability (sensors, display, LEDs)
- Manual LED update capability
- Server process status

---

### 3. Check Server Logs

Look for `[Loop]` messages in server output:

```bash
# If running via systemd
journalctl -u anima -f

# If running manually, check stderr
# Should see:
# [Loop] Starting
# [Loop] store=True sensors=True leds=True
# [Loop] tick 1 (LEDs: available)
# [Loop] LED update: warmth=0.65 ...
```

**If you don't see `[Loop] Starting`:** The display loop isn't starting.

---

## Common Issues

### Issue 1: Display Loop Not Starting

**Symptoms:**
- No `[Loop]` messages in logs
- LEDs initialized but never update
- Display shows default but never changes

**Causes:**
- SSE server lifespan not running properly
- Event loop issue
- Task creation failure

**Fix:**
1. Check server startup logs for errors
2. Verify `start_display_loop()` is being called
3. Check for exceptions in server startup

**Debug:**
```python
# In server.py, lifespan function should log:
print("[Server] Starting display loop...", file=sys.stderr, flush=True)
start_display_loop()
print("[Server] Display loop started", file=sys.stderr, flush=True)
```

---

### Issue 2: LEDs Available But Not Updating

**Symptoms:**
- `leds.is_available()` returns `True`
- LEDs set once but don't change
- No LED update errors in logs

**Causes:**
- Display loop running but `_store` or `_sensors` not initialized
- Exception in LED update being silently caught
- LED update code not being reached

**Fix:**
1. Check logs for `[Loop] store=... sensors=...` - both should be `True`
2. Check for `[Display] Update error` messages
3. Verify LED update code is being executed

**Debug:**
Look for these log messages:
```
[Loop] Starting
[Loop] store=True sensors=True leds=True
[Loop] LED update: warmth=0.65 clarity=0.72 ...
[Loop] tick 1 (LEDs: available)
```

---

### Issue 3: LED Hardware Not Available

**Symptoms:**
- `leds.is_available()` returns `False`
- LEDs never initialize
- Error messages about DotStar library

**Causes:**
- SPI not enabled
- Library not installed
- Hardware not connected
- Pin configuration wrong

**Fix:**
1. Enable SPI: `sudo raspi-config` → Interface Options → SPI
2. Install library: `pip install adafruit-circuitpython-dotstar`
3. Check hardware connection (D5=data, D6=clock)
4. Verify pins in code match hardware

**Debug:**
```bash
# Check SPI
lsmod | grep spi

# Check library
pip list | grep dotstar

# Test manually
python3 -c "import adafruit_dotstar; print('OK')"
```

---

### Issue 4: LEDs Update Once Then Stop

**Symptoms:**
- LEDs update on first loop iteration
- Then stay static
- No errors in logs

**Causes:**
- Exception after first update
- Loop continuing but LED code not reached
- State not changing (unlikely)

**Fix:**
1. Check for exceptions being caught silently
2. Add more logging around LED update
3. Verify loop is continuing (check tick messages)

**Debug:**
Look for periodic `[Loop] tick N` messages. If they stop, the loop crashed.

---

## Enhanced Logging

The updated code includes better logging:

### Server Logs

```
[Server] Starting display loop...
[Server] Display loop started
[Loop] Starting
[Loop] store=True sensors=True leds=True
[Loop] LED update: warmth=0.65 clarity=0.72 stability=0.68 presence=0.71
[Loop] LED colors: led0=(255, 200, 100) led1=(184, 184, 184) led2=(0, 255, 50)
[Loop] tick 1 (LEDs: available)
[Loop] tick 6 (LEDs: available)
...
```

### Error Logs

```
[Loop] LED update error: <exception details>
[Display] Update error: <exception details>
[LEDs] Error setting LEDs: <exception details>
```

---

## Manual Testing

### Test LEDs Independently

```python
from anima_mcp.display.leds import get_led_display

leds = get_led_display()
if leds.is_available():
    # Set red
    leds.set_led(0, (255, 0, 0))
    time.sleep(1)
    
    # Set green
    leds.set_led(1, (0, 255, 0))
    time.sleep(1)
    
    # Set blue
    leds.set_led(2, (0, 0, 255))
    time.sleep(1)
    
    # Clear
    leds.clear()
```

### Test Anima Mapping

```python
from anima_mcp.display.leds import get_led_display

leds = get_led_display()
state = leds.update_from_anima(
    warmth=0.7,    # Should be orange/red
    clarity=0.8,    # Should be bright white
    stability=0.6,  # Combined with presence
    presence=0.7    # Should be green
)
print(f"LED 0: {state.led0}")  # Warmth
print(f"LED 1: {state.led1}")  # Clarity
print(f"LED 2: {state.led2}")  # Stability+Presence
```

---

## Verification Checklist

- [ ] LEDs initialize (`leds.is_available()` returns `True`)
- [ ] Manual LED control works (`set_led()` changes colors)
- [ ] Server is running (`pgrep -f anima`)
- [ ] Display loop is starting (`[Loop] Starting` in logs)
- [ ] Store and sensors initialized (`store=True sensors=True` in logs)
- [ ] LED updates happening (`[Loop] LED update` in logs)
- [ ] Loop continuing (`[Loop] tick N` messages periodic)
- [ ] No errors in logs (`[Display] Update error` or `[LEDs] Error`)

---

## Next Steps

If LEDs still don't work after following this guide:

1. **Run full diagnostic:**
   ```bash
   python3 scripts/test_leds.py
   python3 scripts/check_display_loop.py
   ```

2. **Check server logs:**
   ```bash
   journalctl -u anima -n 100
   ```

3. **Verify code is up to date:**
   ```bash
   git pull  # or sync from Mac
   ```

4. **Report issue with:**
   - Output of diagnostic scripts
   - Relevant log lines
   - Hardware setup details

---

**Most LED issues are either hardware/library problems or the display loop not running. The diagnostic scripts will identify which.**
