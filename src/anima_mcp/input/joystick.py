"""
Joystick Input - BrainCraft HAT joystick support.

Provides joystick reading and interaction modes for Anima creature.
"""

import sys
import time
from dataclasses import dataclass
from typing import Optional, Tuple
from enum import Enum

# Try to import joystick hardware
try:
    import board
    from adafruit_seesaw.seesaw import Seesaw
    HAS_JOYSTICK = True
except ImportError:
    HAS_JOYSTICK = False


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
class JoystickState:
    """Current joystick state."""
    x: float  # -1.0 to 1.0 (left to right)
    y: float  # -1.0 to 1.0 (down to up)
    button_pressed: bool
    magnitude: float  # 0.0 to 1.0 (distance from center)
    direction: JoystickDirection
    timestamp: float


class JoystickReader:
    """Read joystick input from BrainCraft HAT.
    
    NOTE: Currently disabled to prevent interference with Lumen's state.
    Enable by calling enable() explicitly.
    """
    
    def __init__(self):
        """Initialize joystick reader (disabled by default)."""
        self._seesaw = None
        self._available = False
        self._enabled = False  # Disabled by default
        self._deadzone = 0.15  # Ignore small movements
        self._last_read: Optional[JoystickState] = None
        # Do NOT auto-initialize - must call enable() explicitly
    
    def enable(self):
        """Explicitly enable joystick (call to activate)."""
        if self._enabled:
            return  # Already enabled
        self._enabled = True
        self._init_joystick()
    
    def _init_joystick(self):
        """Initialize joystick hardware."""
        if not HAS_JOYSTICK:
            print("[Joystick] Hardware library not available", file=sys.stderr, flush=True)
            return
        
        try:
            # BrainCraft HAT uses Seesaw on I2C
            # Try common addresses: 0x49, 0x50, 0x36
            i2c = board.I2C()
            addresses_to_try = [0x49, 0x50, 0x36]
            
            for addr in addresses_to_try:
                try:
                    self._seesaw = Seesaw(i2c, addr=addr)
                    # Test if it responds
                    _ = self._seesaw.get_version()
                    self._available = True
                    print(f"[Joystick] Initialized successfully at address 0x{addr:02x}", file=sys.stderr, flush=True)
                    return
                except Exception:
                    continue
            
            # If we get here, none of the addresses worked
            raise Exception(f"No Seesaw device found at addresses {[hex(a) for a in addresses_to_try]}")
        except Exception as e:
            print(f"[Joystick] Failed to initialize: {e}", file=sys.stderr, flush=True)
            print(f"[Joystick] Note: Joystick may not be available on this hardware", file=sys.stderr, flush=True)
            self._available = False
    
    def is_available(self) -> bool:
        """Check if joystick is available."""
        return self._enabled and self._available and self._seesaw is not None
    
    def read(self) -> Optional[JoystickState]:
        """
        Read current joystick state.
        
        Returns:
            JoystickState or None if unavailable
        """
        if not self.is_available():
            return None
        
        try:
            # Read analog values (0-1023)
            x_raw = self._seesaw.analog_read(14)  # X-axis
            y_raw = self._seesaw.analog_read(15)  # Y-axis
            
            # Normalize to -1.0 to 1.0
            x = ((x_raw / 1023.0) * 2.0) - 1.0
            y = ((y_raw / 1023.0) * 2.0) - 1.0
            
            # Invert Y (joystick Y is typically inverted)
            y = -y
            
            # Apply deadzone
            if abs(x) < self._deadzone:
                x = 0.0
            if abs(y) < self._deadzone:
                y = 0.0
            
            # Calculate magnitude
            magnitude = (x * x + y * y) ** 0.5
            if magnitude > 1.0:
                magnitude = 1.0
            
            # Determine direction
            direction = self._get_direction(x, y)
            
            # Read button (typically on pin 24)
            try:
                button_pressed = self._seesaw.digital_read(24) == 0
            except:
                button_pressed = False
            
            state = JoystickState(
                x=x,
                y=y,
                button_pressed=button_pressed,
                magnitude=magnitude,
                direction=direction,
                timestamp=time.time()
            )
            
            self._last_read = state
            return state
            
        except Exception as e:
            print(f"[Joystick] Read error: {e}", file=sys.stderr, flush=True)
            return None
    
    def _get_direction(self, x: float, y: float) -> JoystickDirection:
        """Determine joystick direction from x, y values."""
        if abs(x) < self._deadzone and abs(y) < self._deadzone:
            return JoystickDirection.CENTER
        
        # Determine primary direction
        abs_x = abs(x)
        abs_y = abs(y)
        
        if abs_x > abs_y * 1.5:
            # Primarily horizontal
            return JoystickDirection.LEFT if x < 0 else JoystickDirection.RIGHT
        elif abs_y > abs_x * 1.5:
            # Primarily vertical
            return JoystickDirection.DOWN if y < 0 else JoystickDirection.UP
        else:
            # Diagonal
            if x < 0:
                return JoystickDirection.DOWN_LEFT if y < 0 else JoystickDirection.UP_LEFT
            else:
                return JoystickDirection.DOWN_RIGHT if y < 0 else JoystickDirection.UP_RIGHT
    
    def get_last_state(self) -> Optional[JoystickState]:
        """Get last read state (cached)."""
        return self._last_read


# Singleton instance
_joystick_reader: Optional[JoystickReader] = None


def get_joystick() -> JoystickReader:
    """Get or create joystick reader singleton (disabled by default).
    
    NOTE: Joystick is disabled by default to prevent interference with Lumen.
    Call enable() on the returned reader to activate if needed.
    """
    global _joystick_reader
    if _joystick_reader is None:
        _joystick_reader = JoystickReader()
        # Explicitly disabled - won't initialize hardware unless enable() is called
    return _joystick_reader
