"""
Input modules for Anima creature interaction.
"""

from .joystick import get_joystick, JoystickReader, JoystickState, JoystickDirection

__all__ = [
    "get_joystick",
    "JoystickReader",
    "JoystickState",
    "JoystickDirection",
]
