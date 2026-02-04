# Joystick Screen Switching

**Created:** January 12, 2026  
**Last Updated:** January 12, 2026  
**Status:** Implementation Complete (Hardware Dependent)

---

## Status

✅ **Code implemented** - Screen switching system is ready  
⚠️ **Hardware check needed** - Joystick may not be available on this BrainCraft HAT

---

## How It Works

1. **Press joystick button** → Cycles through screens:
   - Face (default) → Sensors → Identity → Diagnostics → Face

2. **Auto-return**: After 10 seconds on any non-Face screen, returns to Face

3. **Screens available**:
   - **Face**: Lumen's expressive face (default)
   - **Sensors**: CPU temp, ambient temp, humidity, light, CPU/memory usage
   - **Identity**: Name, age, awake time, alive ratio, awakenings
   - **Diagnostics**: Anima state (W/C/S/P), governance status

---

## Troubleshooting

### Joystick Not Working

**Symptoms**: Button press doesn't switch screens

**Possible causes**:

1. **Hardware not available**:
   - BrainCraft HAT may not have joystick
   - Joystick not connected
   - Check logs: `journalctl --user -u anima | grep -i joystick`

2. **Library not installed**:
   ```bash
   pip install adafruit-circuitpython-seesaw
   ```

3. **Wrong I2C address**:
   - Code tries: 0x49, 0x50, 0x36
   - Check actual address: `i2cdetect -y 1` (if available)

4. **Joystick disabled**:
   - Joystick is disabled by default (to prevent interference)
   - Auto-enables when display is available
   - Check logs for: `[Display] Joystick enabled`

---

## Alternative: Keyboard/SSH Control

If joystick isn't available, screen switching could be added via:
- MCP tool: `switch_screen(mode="sensors")`
- Keyboard shortcut (if running interactively)
- Web interface (future)

---

## Implementation Details

- **File**: `src/anima_mcp/display/screens.py`
- **Integration**: `src/anima_mcp/server.py` (display loop)
- **Joystick**: `src/anima_mcp/input/joystick.py`

Joystick is non-blocking - if unavailable, system continues normally with Face screen only.
