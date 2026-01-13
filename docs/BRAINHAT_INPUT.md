# BrainCraft HAT Input Guide

**Created:** January 12, 2026  
**Last Updated:** January 12, 2026  
**Status:** Active

---

## Hardware Configuration

BrainCraft HAT uses **GPIO pins directly** (not analog/Seesaw):

- **Joystick Left**: GPIO #22 (D22)
- **Joystick Right**: GPIO #24 (D24)
- **Joystick Up**: GPIO #23 (D23)
- **Joystick Down**: GPIO #27 (D27)
- **Joystick Button** (center press): GPIO #16 (D16)
- **Separate Button**: GPIO #17 (D17)

All inputs have 10K pull-up resistors to 3.3V, so **pressed = LOW (False)**.

---

## Screen Switching Controls

### Joystick Left/Right
- **Left** → Previous screen
- **Right** → Next screen
- Edge detection: Only triggers on direction change (not while held)

### Joystick Button (Center Press)
- Press down on joystick → Cycle to next screen

### Separate Button
- Press separate button → Return to Face screen

---

## Screen Order

1. **Face** (default) - Lumen's expressive face
2. **Sensors** - CPU temp, ambient temp, humidity, light, CPU/memory usage
3. **Identity** - Name, age, awake time, alive ratio, awakenings
4. **Diagnostics** - Anima state (W/C/S/P), governance status

**Auto-return**: After 10 seconds on any non-Face screen, returns to Face screen.

---

## MCP Tool Fallback

If joystick hardware isn't available, use the MCP tool:

```json
{
  "name": "switch_screen",
  "arguments": {
    "mode": "next"  // or "previous", "face", "sensors", "identity", "diagnostics"
  }
}
```

---

## Troubleshooting

### Input Not Working

1. **Check GPIO pins**: Verify pins D16, D17, D22, D23, D24, D27 are accessible
2. **Check logs**: `journalctl --user -u anima | grep -i "brainhat\|input"`
3. **Test directly**: Run `python3 -m anima_mcp.input.brainhat_input` (if test script exists)

### Buttons Not Responding

- Pull-up resistors: Pressed = LOW (False), Released = HIGH (True)
- Check if pins are already in use by another process
- Verify BrainCraft HAT is properly connected

---

## Implementation

- **File**: `src/anima_mcp/input/brainhat_input.py`
- **Integration**: `src/anima_mcp/server.py` (display loop)
- **Edge detection**: Prevents repeated triggers while button/joystick held
