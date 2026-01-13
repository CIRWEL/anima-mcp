# Display Fix & Next Steps Advocate

**Created:** January 11, 2026  
**Last Updated:** January 11, 2026  
**Status:** Active

---

## Problem: Grey Screen on HAT Display

The BrainCraft HAT display was showing a grey/blank screen because:
1. **No continuous update loop** - Display only updated when `show_face` tool was called
2. **Display may not initialize properly** - Need diagnostics to verify hardware

## Solution: Display Diagnostics + Continuous Updates

### 1. Display Diagnostics Tool

Run diagnostics to check display hardware:

```bash
# On Pi
python3 -m anima_mcp.display_diagnostics

# Or use script
./scripts/run_display_diagnostics.sh
```

This will:
- ✅ Check if PIL/Pillow is installed
- ✅ Verify display hardware is detected
- ✅ Test display with different colors
- ✅ Render a test face
- ✅ Provide troubleshooting steps

### 2. Continuous Display Update Loop

**NEW**: Display and LEDs now update automatically every 2 seconds!

- **TFT Display**: Face shows real-time anima state
- **LED Display**: 3 DotStar LEDs provide proprioceptive feedback
  - LED 0: Warmth (blue → orange/red)
  - LED 1: Clarity (brightness)
  - LED 2: Stability+Presence (green → red)
- No need to call `show_face` manually
- Updates in background while server runs

### 3. Next Steps Advocate System

**NEW**: Proactive system that suggests what to do next!

Call the `next_steps` tool to get:
- Analysis of current state
- Prioritized list of next steps
- Action items with blockers and time estimates
- Integration suggestions

## Usage

### Fix Grey Screen

1. **Run diagnostics**:
   ```bash
   python3 -m anima_mcp.display_diagnostics
   ```

2. **Check output**:
   - If display not detected → Check SPI enabled, HAT connected
   - If colors work but face doesn't → Check sensor readings
   - If everything works → Display should update automatically

3. **Verify continuous updates**:
   - Start anima server: `anima`
   - Display should update every 2 seconds automatically
   - Face reflects current anima state

### Get Next Steps

Use the `next_steps` tool in MCP:

```json
{
  "tool": "next_steps"
}
```

Returns:
- Current state analysis
- Prioritized next steps (critical → low)
- Action items with:
  - What to do
  - Why it matters
  - What's blocking it
  - Estimated time
  - Related files

## What the Advocate Analyzes

1. **Display Status** - Is display working?
2. **Brain HAT** - Is EEG connected?
3. **UNITARES** - Is governance connected?
4. **Sensor Quality** - Clarity, stability, entropy
5. **Integration Gaps** - Missing connections
6. **Optimization Needs** - Performance issues

## Example Next Steps

The advocate might suggest:

### Critical Priority
- **Reduce System Entropy** - If entropy > 0.6, system unstable

### High Priority
- **Fix Grey Screen** - Display not working
- **Improve Sensor Clarity** - Sensors not reading well
- **Integrate Anima-MCP with UNITARES-MCP** - Two servers need unified workflow

### Medium Priority
- **Connect Brain HAT** - Neural proprioception not available
- **Add Continuous Display Update** - Face should update automatically
- **Connect UNITARES** - Governance system not connected

### Low Priority
- **Validate Neural Proprioception** - Test if neural signals help

## Integration with UNITARES-MCP

The advocate recognizes complexity from having two MCP servers:
- **anima-mcp**: Creature with proprioception
- **unitares-mcp**: Governance system

Suggests unified workflow to manage both together.

## Files Created

1. **`src/anima_mcp/display_diagnostics.py`** - Display diagnostic tool
2. **`src/anima_mcp/next_steps_advocate.py`** - Proactive advocate system
3. **`src/anima_mcp/display/leds.py`** - LED display module
4. **`scripts/run_display_diagnostics.sh`** - Quick diagnostic script
5. **`docs/DISPLAY_FIX_AND_NEXT_STEPS.md`** - This file
6. **`docs/LED_DISPLAY.md`** - LED documentation

## Files Modified

1. **`src/anima_mcp/server.py`**:
   - Added `next_steps` tool
   - Added continuous display update loop
   - Auto-updates TFT display and LEDs every 2 seconds
   - Integrated LED support

## Next Actions

1. **On Pi**: Run `python3 -m anima_mcp.display_diagnostics` to fix grey screen
2. **In MCP**: Call `next_steps` tool to see what to do next
3. **Verify**: Display should update automatically when server runs

---

**The system is now proactive - it tells you what to do next instead of waiting for you to ask!**
