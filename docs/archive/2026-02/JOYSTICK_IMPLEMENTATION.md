# Joystick Implementation: Attention & Focus

**Created:** January 12, 2026  
**Last Updated:** January 12, 2026  
**Status:** ⚠️ Eye-following reverted (eyes closed most of time)

---

## Summary

Successfully implemented Phase 1 joystick features: joystick input reader and attention/focus system where creature's eyes follow joystick direction with LED emphasis.

---

## Implemented Features

### 1. Joystick Input Reader ✅

**File:** `src/anima_mcp/input/joystick.py`

**Features:**
- Reads joystick position (X, Y) from BrainCraft HAT
- Normalizes to -1.0 to 1.0 range
- Detects button press
- Calculates magnitude and direction
- Applies deadzone to ignore small movements
- Graceful fallback when hardware unavailable

**API:**
```python
from anima_mcp.input.joystick import get_joystick

joystick = get_joystick()
if joystick.is_available():
    state = joystick.read()
    # state.x, state.y, state.button_pressed, state.direction
```

**JoystickState:**
- `x`: -1.0 (left) to 1.0 (right)
- `y`: -1.0 (down) to 1.0 (up)
- `button_pressed`: bool
- `magnitude`: 0.0 to 1.0 (distance from center)
- `direction`: JoystickDirection enum
- `timestamp`: float

---

### 2. Attention & Focus System ⚠️

**Status:** Eye-following reverted - Lumen's eyes are closed most of the time, so eye movement wasn't visible.

**Joystick Reader:** Still available for future use (expression control, menu navigation, etc.)

**Note:** The joystick reader module (`src/anima_mcp/input/joystick.py`) is still available and can be used for:
- Expression control (direct state override)
- Menu navigation
- Play modes
- Calibration

See `JOYSTICK_IDEAS.md` for future implementation ideas.

---

## Code Changes

### New Files
1. `src/anima_mcp/input/joystick.py` - Joystick reader module
2. `src/anima_mcp/input/__init__.py` - Input module exports

### Modified Files
1. `src/anima_mcp/display/face.py` - Added `eye_offset_x`, `eye_offset_y` to FaceState
2. `src/anima_mcp/display/renderer.py` - Eye drawing applies offset
3. `src/anima_mcp/server.py` - Joystick reading and LED emphasis in display loop

---

## Usage

### Basic Usage
```python
from anima_mcp.input.joystick import get_joystick

joystick = get_joystick()
if joystick.is_available():
    state = joystick.read()
    if state:
        print(f"Joystick: x={state.x:.2f}, y={state.y:.2f}")
        print(f"Direction: {state.direction.value}")
        print(f"Button: {state.button_pressed}")
```

### Integration
Joystick is automatically integrated into the display loop:
- Eyes follow joystick when moved
- LEDs emphasize based on direction
- No additional configuration needed

---

## Visual Effects

### Eye Movement
- **Left**: Eyes look left (toward LED 0 - warmth)
- **Right**: Eyes look right (toward LED 2 - stability)
- **Up**: Eyes look up (toward LED 1 - clarity)
- **Down**: Eyes look down
- **Diagonal**: Eyes follow diagonal direction

### LED Emphasis
- **Left**: LED 0 (warmth) brightens 30%
- **Right**: LED 2 (stability) brightens 30%
- **Up**: LED 1 (clarity) brightens 30%
- **Center**: Normal brightness

---

## Hardware Support

### BrainCraft HAT
- Uses Seesaw I2C interface
- Address: 0x49 (default)
- X-axis: Analog pin 14
- Y-axis: Analog pin 15
- Button: Digital pin 24

### Fallback
- Gracefully handles missing hardware
- Returns None when unavailable
- No errors if joystick not present

---

## Testing

### Test Joystick Reader
```python
from anima_mcp.input.joystick import get_joystick

joystick = get_joystick()
if joystick.is_available():
    state = joystick.read()
    print(f"X: {state.x:.2f}, Y: {state.y:.2f}")
    print(f"Direction: {state.direction.value}")
else:
    print("Joystick not available (expected on Mac)")
```

### Test Eye Movement
```python
from anima_mcp.display.face import FaceState, EyeState, MouthState

face_state = FaceState(
    eyes=EyeState.NORMAL,
    mouth=MouthState.NEUTRAL,
    tint=(255, 255, 255),
    eye_openness=0.7,
    eye_offset_x=0.5,  # Look right
    eye_offset_y=-0.3  # Look down
)
# Eyes should render offset
```

---

## Next Steps (Phase 2)

1. **Expression Control** - Direct state override via joystick
2. **Menu Navigation** - Navigate through creature state/menu
3. **Play Modes** - Follow/chase/dance modes

---

## Benefits

✅ **Direct Interaction** - Creature responds to user input  
✅ **Visual Feedback** - Eyes + LEDs show attention  
✅ **Engaging** - Creates sense of awareness  
✅ **Intuitive** - Natural joystick controls  
✅ **Graceful** - Works with or without hardware  

---

**Status:** ✅ Phase 1 complete. Joystick attention/focus system implemented!
