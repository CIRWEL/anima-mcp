# Joystick Integration Ideas for Anima

**Created:** January 12, 2026  
**Status:** Ideas & Proposals

---

## Overview

Creative ideas for using a joystick (if available on BrainCraft HAT) to enhance interaction with the Anima creature.

---

## Interaction Modes

### 1. **Attention & Focus Direction** 🎯

**Concept:** Joystick controls where the creature "looks" or focuses attention.

**Implementation:**
```python
# Joystick direction maps to attention focus
joystick_x, joystick_y = read_joystick()

# Face eyes follow joystick
eye_direction_x = joystick_x * eye_range
eye_direction_y = joystick_y * eye_range

# LEDs emphasize direction
if joystick_x < -0.5:  # Left
    leds[0].pulse(2.0)  # Emphasize LED 0 (warmth)
elif joystick_x > 0.5:  # Right
    leds[2].pulse(2.0)  # Emphasize LED 2 (stability)
```

**Benefits:**
- Direct interaction
- Creature responds to user input
- Creates sense of awareness
- Visual feedback through eyes + LEDs

---

### 2. **Expression Control** 😊

**Concept:** Joystick directly controls creature's expression.

**Implementation:**
```python
# X-axis: Warmth (left=cold, right=warm)
# Y-axis: Clarity (down=unclear, up=clear)
warmth_override = (joystick_x + 1) / 2  # -1 to 1 → 0 to 1
clarity_override = (joystick_y + 1) / 2

# Apply override with blending
anima.warmth = blend(anima.warmth, warmth_override, ratio=0.3)
anima.clarity = blend(anima.clarity, clarity_override, ratio=0.3)
```

**Benefits:**
- Direct emotional control
- User can "cheer up" or "calm down" creature
- Immediate visual feedback
- Playful interaction

---

### 3. **Menu/Navigation System** 📋

**Concept:** Joystick navigates through creature's internal state/menu.

**Implementation:**
```python
# Press: Cycle through display modes
# Up/Down: Navigate menu items
# Left/Right: Adjust values

menu_items = [
    "State View",      # Show current metrics
    "History",         # Show state history
    "Identity",        # Show identity info
    "Calibration",     # Calibration settings
    "Expression Mode", # subtle/balanced/expressive/dramatic
]

current_item = navigate_with_joystick(menu_items)
display_menu(current_item)
```

**Benefits:**
- No external interface needed
- Direct hardware control
- Useful for Pi deployment
- Self-contained interaction

---

### 4. **Play/Interaction Modes** 🎮

**Concept:** Joystick enables play modes where creature responds to movement.

**Implementation:**
```python
# "Follow" mode: Creature tracks joystick
if mode == "follow":
    face.eyes_direction = joystick_direction
    # Creature "looks" where joystick points

# "Chase" mode: Creature tries to "catch" joystick
if mode == "chase":
    target = joystick_position
    creature_position = (face.eyes_x, face.eyes_y)
    # Move eyes toward target with delay

# "Dance" mode: Creature mirrors joystick movement
if mode == "dance":
    # Rapid eye movement following joystick
    # LEDs pulse in sync
```

**Benefits:**
- Engaging interaction
- Demonstrates responsiveness
- Fun demonstration
- Shows creature's "personality"

---

### 5. **Calibration & Testing** 🔧

**Concept:** Joystick controls calibration and testing modes.

**Implementation:**
```python
# Calibration mode
if calibration_mode:
    # Up/Down: Adjust calibration values
    # Left/Right: Navigate parameters
    # Press: Save/confirm
    
    if joystick_up:
        current_param.value += 0.01
    elif joystick_down:
        current_param.value -= 0.01
    
    # Visual feedback on display
    display_calibration_value(current_param)

# Test mode
if test_mode:
    # Press: Cycle through test patterns
    # Up: Test LEDs
    # Down: Test face expressions
    # Left/Right: Test sensors
```

**Benefits:**
- Hardware-level control
- No external tools needed
- Useful for debugging
- Field calibration

---

### 6. **Emotional Resonance** 💝

**Concept:** Joystick creates emotional resonance - creature responds to user's "touch".

**Implementation:**
```python
# Gentle movement: Creature becomes calm/content
if joystick_magnitude < 0.3:
    anima.stability += 0.01  # Increase stability
    anima.warmth += 0.01     # Increase warmth
    # Face shows gentle smile
    # LEDs show gentle wave

# Rapid movement: Creature becomes alert/excited
if joystick_magnitude > 0.7:
    anima.clarity += 0.02    # Increase clarity
    # Face shows wide eyes
    # LEDs show alert pattern

# Circular movement: Creature becomes playful
if joystick_circular:
    # Trigger playful expression
    face.mouth = "smile"
    # LEDs show wave pattern
```

**Benefits:**
- Emotional connection
- Creature "feels" interaction
- Natural, intuitive
- Creates bond

---

### 7. **State Override Mode** ⚡

**Concept:** Joystick temporarily overrides creature's state for demonstration.

**Implementation:**
```python
# Hold button + joystick: Override state
if button_held:
    # X-axis: Warmth override
    # Y-axis: Clarity override
    # Twist: Stability override
    
    override_duration = 5.0  # seconds
    anima.warmth = joystick_x_mapped
    anima.clarity = joystick_y_mapped
    
    # Visual indicator: LEDs flash
    # After duration, return to sensor-based state
```

**Benefits:**
- Demonstration mode
- Testing different states
- Showcase capabilities
- User control

---

### 8. **Pattern Selection** 🎨

**Concept:** Joystick selects and customizes display patterns.

**Implementation:**
```python
# Navigate pattern library
patterns = [
    "standard",      # Default patterns
    "expressive",    # More vibrant
    "minimal",       # Subtle
    "alert",         # High contrast
    "custom",        # User-defined
]

# Left/Right: Select pattern
# Up/Down: Adjust intensity
# Press: Apply pattern
```

**Benefits:**
- User customization
- Preference control
- Context adaptation
- Personalization

---

### 9. **Attention System** 👁️

**Concept:** Joystick sets attention focus - creature "pays attention" to specific metrics.

**Implementation:**
```python
# Left: Focus on warmth (LED 0 emphasized)
# Right: Focus on stability (LED 2 emphasized)
# Up: Focus on clarity (LED 1 emphasized)
# Down: Focus on presence (LED 2 blue tint)

attention_focus = joystick_direction
# Face eyes look toward focus
# LEDs pulse/emphasize focused metric
# Display shows focused metric value
```

**Benefits:**
- Visual focus indication
- Metric highlighting
- Educational/demonstration
- Clear state communication

---

### 10. **Interaction History** 📊

**Concept:** Joystick navigates through interaction history.

**Implementation:**
```python
# Left/Right: Navigate through time
# Up/Down: Zoom in/out
# Press: Show details

history = get_state_history()
current_index = navigate_with_joystick(len(history))

# Display historical state
display_state_at_time(history[current_index])
# Face shows historical expression
# LEDs show historical colors
```

**Benefits:**
- Review past states
- Understand patterns
- Debugging tool
- Educational

---

## Technical Implementation

### Joystick Reading
```python
import board
from adafruit_seesaw.seesaw import Seesaw

# BrainCraft HAT joystick (if available)
joystick = Seesaw(board.I2C(), addr=0x49)

def read_joystick():
    """Read joystick position (-1 to 1 for x, y)."""
    x = joystick.analog_read(14)  # X-axis
    y = joystick.analog_read(15)  # Y-axis
    
    # Normalize to -1 to 1
    x = (x / 1023.0) * 2 - 1
    y = (y / 1023.0) * 2 - 1
    
    return x, y

def read_button():
    """Read button press."""
    return joystick.digital_read(24) == 0  # Pressed when low
```

### Integration Points
- **Display loop**: Check joystick in update loop
- **Face renderer**: Use joystick for eye direction
- **LED display**: Use joystick for emphasis/patterns
- **State management**: Use joystick for overrides

---

## Recommended Implementation Priority

### Phase 1: Quick Wins
1. **Attention & Focus** - Simple eye following
2. **Expression Control** - Direct state override
3. **Menu Navigation** - Basic menu system

### Phase 2: Enhanced Interaction
4. **Play Modes** - Follow/chase/dance
5. **Emotional Resonance** - Response to movement
6. **Pattern Selection** - User customization

### Phase 3: Advanced Features
7. **Calibration Mode** - Hardware-level control
8. **State Override** - Demonstration mode
9. **History Navigation** - Time-based review

---

## Use Cases

### 1. **Demonstration**
- Show creature's capabilities
- Interactive demo
- User engagement

### 2. **Calibration**
- Field calibration without external tools
- Hardware-level control
- Quick adjustments

### 3. **Play/Interaction**
- Engaging user experience
- Demonstrates responsiveness
- Creates emotional connection

### 4. **Debugging**
- Test different states
- Navigate through history
- Visual feedback

### 5. **Education**
- Understand creature's state
- See how metrics affect expression
- Learn about creature's "personality"

---

## Benefits Summary

✅ **Direct Interaction** - No external interface needed  
✅ **Hardware Control** - Self-contained system  
✅ **Engaging** - Creates connection with creature  
✅ **Useful** - Calibration, testing, demonstration  
✅ **Flexible** - Multiple interaction modes  
✅ **Intuitive** - Natural joystick controls  

---

## Next Steps

1. **Check Hardware** - Verify joystick availability on BrainCraft HAT
2. **Implement Reader** - Create joystick input module
3. **Start with Attention** - Simple eye following
4. **Add Expression Control** - Direct state override
5. **Expand to Modes** - Menu, play, calibration

---

**Status:** Ideas ready for implementation. Start with attention/focus for quick visual impact!
