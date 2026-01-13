"""
BrainCraft HAT Input - Joystick and Button Support

BrainCraft HAT has:
- Joystick (analog X/Y via Seesaw or GPIO)
- Button on joystick (press down)
- Separate button (GPIO pin)

This module provides unified input handling for all three.
"""

import sys
import time
from dataclasses import dataclass
from typing import Optional
from enum import Enum

# Try to import hardware libraries
try:
    import board
    import digitalio
    HAS_GPIO = True
except ImportError:
    HAS_GPIO = False

try:
    from adafruit_seesaw.seesaw import Seesaw
    HAS_SEESAW = True
except ImportError:
    HAS_SEESAW = False


class JoystickDirection(Enum):
    """Joystick direction."""
    CENTER = "center"
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    UP_LEFT = "up_left"
    UP_RIGHT = "up_right"
    DOWN_LEFT = "down_left"
    DOWN_RIGHT = "down_right"


@dataclass
class InputState:
    """Complete input state from BrainCraft HAT."""
    # Joystick
    joystick_x: float = 0.0  # -1.0 to 1.0
    joystick_y: float = 0.0  # -1.0 to 1.0
    joystick_direction: JoystickDirection = JoystickDirection.CENTER
    joystick_button: bool = False  # Button on joystick (press down)
    
    # Separate button
    separate_button: bool = False
    
    timestamp: float = 0.0


class BrainHatInput:
    """Unified input handler for BrainCraft HAT joystick and buttons.
    
    BrainCraft HAT uses GPIO pins directly (not analog/Seesaw):
    - Joystick directions: D22 (left), D24 (right), D23 (up), D27 (down)
    - Joystick button: D16 (center press)
    - Separate button: D17
    """
    
    def __init__(self):
        """Initialize input handler."""
        self._joy_left = None
        self._joy_right = None
        self._joy_up = None
        self._joy_down = None
        self._joy_button = None
        self._separate_button_pin = None
        self._available = False
        self._enabled = False
        self._deadzone = 0.15
        self._last_state: Optional[InputState] = None
        self._prev_state: Optional[InputState] = None  # Previous state for edge detection
    
    def enable(self):
        """Explicitly enable input (call to activate)."""
        if self._enabled:
            return
        self._enabled = True
        self._init_hardware()
    
    def _init_hardware(self):
        """Initialize joystick and button hardware.
        
        BrainCraft HAT GPIO pin configuration:
        - Button: GPIO #17 (D17)
        - Joystick Select (Center Press): GPIO #16 (D16)
        - Joystick Left: GPIO #22 (D22)
        - Joystick Up: GPIO #23 (D23)
        - Joystick Right: GPIO #24 (D24)
        - Joystick Down: GPIO #27 (D27)
        """
        if not HAS_GPIO:
            print("[BrainHatInput] GPIO library not available", file=sys.stderr, flush=True)
            return
        
        try:
            # Initialize joystick direction pins (digital GPIO)
            self._joy_left = digitalio.DigitalInOut(board.D22)
            self._joy_left.direction = digitalio.Direction.INPUT
            self._joy_left.pull = digitalio.Pull.UP
            
            self._joy_right = digitalio.DigitalInOut(board.D24)
            self._joy_right.direction = digitalio.Direction.INPUT
            self._joy_right.pull = digitalio.Pull.UP
            
            self._joy_up = digitalio.DigitalInOut(board.D23)
            self._joy_up.direction = digitalio.Direction.INPUT
            self._joy_up.pull = digitalio.Pull.UP
            
            self._joy_down = digitalio.DigitalInOut(board.D27)
            self._joy_down.direction = digitalio.Direction.INPUT
            self._joy_down.pull = digitalio.Pull.UP
            
            # Joystick button (center press)
            self._joy_button = digitalio.DigitalInOut(board.D16)
            self._joy_button.direction = digitalio.Direction.INPUT
            self._joy_button.pull = digitalio.Pull.UP
            
            # Separate button
            self._separate_button_pin = digitalio.DigitalInOut(board.D17)
            self._separate_button_pin.direction = digitalio.Direction.INPUT
            self._separate_button_pin.pull = digitalio.Pull.UP
            
            self._available = True
            print("[BrainHatInput] BrainCraft HAT input initialized (GPIO pins)", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[BrainHatInput] Failed to initialize GPIO pins: {e}", file=sys.stderr, flush=True)
            self._available = False
    
    def is_available(self) -> bool:
        """Check if input hardware is available."""
        return self._enabled and self._available and (
            self._joy_left is not None or self._separate_button_pin is not None
        )
    
    def read(self) -> Optional[InputState]:
        """Read current input state from GPIO pins."""
        if not self.is_available():
            return None
        
        try:
            # Read joystick direction pins (pull-up: pressed = LOW = False)
            joy_left_pressed = not self._joy_left.value
            joy_right_pressed = not self._joy_right.value
            joy_up_pressed = not self._joy_up.value
            joy_down_pressed = not self._joy_down.value
            
            # Convert to analog-like values (-1.0 to 1.0)
            joystick_x = 0.0
            joystick_y = 0.0
            
            if joy_left_pressed:
                joystick_x = -1.0
            elif joy_right_pressed:
                joystick_x = 1.0
            
            if joy_up_pressed:
                joystick_y = 1.0
            elif joy_down_pressed:
                joystick_y = -1.0
            
            # Read joystick button (center press)
            joystick_button = not self._joy_button.value  # Pull-up: pressed = LOW
            
            # Read separate button
            separate_button = not self._separate_button_pin.value  # Pull-up: pressed = LOW
            
            # Determine direction
            direction = self._get_direction(joystick_x, joystick_y)
            
            state = InputState(
                joystick_x=joystick_x,
                joystick_y=joystick_y,
                joystick_direction=direction,
                joystick_button=joystick_button,
                separate_button=separate_button,
                timestamp=time.time()
            )
            
            # Store previous state BEFORE updating (for edge detection)
            self._prev_state = self._last_state
            self._last_state = state
            return state
            
        except Exception as e:
            print(f"[BrainHatInput] Read error: {e}", file=sys.stderr, flush=True)
            import traceback
            traceback.print_exc(file=sys.stderr)
            return None
    
    def get_prev_state(self) -> Optional[InputState]:
        """Get previous state (before last read) for edge detection."""
        return self._prev_state
    
    def _get_direction(self, x: float, y: float) -> JoystickDirection:
        """Determine joystick direction from x, y values."""
        # Use original deadzone - was too strict
        deadzone = 0.15
        
        if abs(x) < deadzone and abs(y) < deadzone:
            return JoystickDirection.CENTER
        
        abs_x = abs(x)
        abs_y = abs(y)
        
        # Prefer horizontal for screen switching, but don't be too strict
        if abs_x > abs_y * 1.2:  # Lower threshold - more forgiving
            return JoystickDirection.LEFT if x < 0 else JoystickDirection.RIGHT
        elif abs_y > abs_x * 1.2:
            return JoystickDirection.DOWN if y < 0 else JoystickDirection.UP
        else:
            # Diagonal - prefer horizontal for screen switching
            if abs_x >= abs_y:
                return JoystickDirection.LEFT if x < 0 else JoystickDirection.RIGHT
            else:
                return JoystickDirection.DOWN if y < 0 else JoystickDirection.UP
    
    def get_last_state(self) -> Optional[InputState]:
        """Get last read state (cached)."""
        return self._last_state


# Singleton instance
_brainhat_input: Optional[BrainHatInput] = None


def get_brainhat_input() -> BrainHatInput:
    """Get or create BrainHat input handler (disabled by default)."""
    global _brainhat_input
    if _brainhat_input is None:
        _brainhat_input = BrainHatInput()
    return _brainhat_input
