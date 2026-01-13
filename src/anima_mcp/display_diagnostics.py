"""
Display Diagnostics - Fix grey screen and verify HAT display.

Helps diagnose and fix display issues on BrainCraft HAT.
"""

import sys
from pathlib import Path
from typing import Optional

# Ensure UTF-8 encoding for emoji support
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

try:
    from PIL import Image, ImageDraw
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    print("PIL/Pillow not installed. Install with: pip install pillow")


def check_display_hardware() -> dict:
    """Check if display hardware is available."""
    diagnostics = {
        "pil_available": HAS_PIL,
        "display_available": False,
        "error": None,
        "details": {},
    }
    
    if not HAS_PIL:
        diagnostics["error"] = "PIL/Pillow not installed"
        return diagnostics
    
    try:
        import board
        import digitalio
        from adafruit_rgb_display import st7789
        
        # Try to initialize display
        cs_pin = digitalio.DigitalInOut(board.CE0)
        dc_pin = digitalio.DigitalInOut(board.D25)
        reset_pin = digitalio.DigitalInOut(board.D24)
        spi = board.SPI()
        
        display = st7789.ST7789(
            spi,
            height=240,
            width=240,
            y_offset=80,
            rotation=180,
            cs=cs_pin,
            dc=dc_pin,
            rst=reset_pin,
        )
        
        diagnostics["display_available"] = True
        diagnostics["details"] = {
            "width": 240,
            "height": 240,
            "rotation": 180,
        }
        
        # Test render
        test_image = Image.new("RGB", (240, 240), (255, 0, 0))  # Red test
        display.image(test_image)
        
        diagnostics["test_render"] = "Red test image sent to display"
        
    except ImportError as e:
        diagnostics["error"] = f"Missing dependencies: {e}"
        diagnostics["details"]["missing"] = str(e)
    except Exception as e:
        diagnostics["error"] = f"Display initialization failed: {e}"
        diagnostics["details"]["exception"] = str(e)
    
    return diagnostics


def test_display_colors():
    """Test display with different colors."""
    if not HAS_PIL:
        print("❌ PIL/Pillow required")
        return
    
    try:
        from .display import get_display
        
        display = get_display()
        
        if not display.is_available():
            print("❌ Display hardware not available")
            print("   Check SPI/I2C enabled: sudo raspi-config")
            print("   Check BrainCraft HAT connected properly")
            return
        
        print("✅ Display available! Testing colors...")
        
        # Test colors
        colors = [
            ("RED", (255, 0, 0)),
            ("GREEN", (0, 255, 0)),
            ("BLUE", (0, 0, 255)),
            ("WHITE", (255, 255, 255)),
            ("BLACK", (0, 0, 0)),
        ]
        
        for name, color in colors:
            print(f"  Rendering {name}...")
            image = Image.new("RGB", (240, 240), color)
            if hasattr(display, '_display') and display._display:
                display._display.image(image)
            import time
            time.sleep(1)
        
        print("✅ Color test complete!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()


def render_test_face():
    """Render a test face to verify display works."""
    try:
        from .display import get_display, derive_face_state
        from .anima import Anima
        from .sensors.base import SensorReadings
        from datetime import datetime
        
        display = get_display()
        
        if not display.is_available():
            print("❌ Display not available")
            return
        
        # Create test anima state (happy/content)
        test_readings = SensorReadings(
            timestamp=datetime.now(),
            cpu_temp_c=50.0,
            ambient_temp_c=22.0,
            humidity_pct=45.0,
            light_lux=500.0,
            cpu_percent=30.0,
            memory_percent=50.0,
            disk_percent=40.0,
        )
        
        test_anima = Anima(
            warmth=0.6,
            clarity=0.7,
            stability=0.8,
            presence=0.7,
            readings=test_readings
        )
        
        face_state = derive_face_state(test_anima)
        display.render_face(face_state, name="TEST")
        
        print("✅ Test face rendered!")
        print(f"   Eyes: {face_state.eyes.value}")
        print(f"   Mouth: {face_state.mouth.value}")
        print(f"   Mood: {test_anima.feeling()['mood']}")
        
    except Exception as e:
        print(f"❌ Render failed: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Run diagnostics."""
    print("Display Diagnostics for BrainCraft HAT\n")
    
    # Check hardware
    print("1. Checking display hardware...")
    diag = check_display_hardware()
    
    if diag["pil_available"]:
        print("   ✅ PIL/Pillow available")
    else:
        print("   ❌ PIL/Pillow not available")
        print("      Install: pip install pillow")
        return
    
    if diag["display_available"]:
        print("   ✅ Display hardware detected")
        print(f"      Details: {diag['details']}")
    else:
        print("   ❌ Display hardware not detected")
        if diag["error"]:
            print(f"      Error: {diag['error']}")
        print("\n   Troubleshooting:")
        print("   1. Check BrainCraft HAT is connected")
        print("   2. Enable SPI: sudo raspi-config → Interface Options → SPI")
        print("   3. Check pins: CE0, D25, D24")
        print("   4. Verify adafruit-circuitpython-rgb-display installed")
        return
    
    # Test colors
    print("\n2. Testing display colors...")
    test_display_colors()
    
    # Test face render
    print("\n3. Testing face render...")
    render_test_face()
    
    print("\n✅ Diagnostics complete!")


if __name__ == "__main__":
    main()
