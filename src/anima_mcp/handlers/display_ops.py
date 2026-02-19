"""Display operation handlers — screen capture, face rendering, diagnostics, display management.

Handlers: capture_screen, show_face, diagnostics, manage_display.
"""

import json
import sys

from mcp.types import TextContent


async def handle_capture_screen(arguments: dict) -> list[TextContent]:
    """
    Capture current display screen as base64-encoded PNG image.

    Returns the actual visual output on Lumen's 240×240 LCD display,
    allowing remote viewing of what Lumen is drawing, showing, or expressing.
    """
    from ..server import _screen_renderer

    if _screen_renderer is None:
        return [TextContent(type="text", text=json.dumps({
            "error": "Screen renderer not initialized"
        }))]

    try:
        # Access the renderer's display object to get the current image
        renderer_display = _screen_renderer._display
        if renderer_display is None or not hasattr(renderer_display, '_image'):
            return [TextContent(type="text", text=json.dumps({
                "error": "Display not available or no image cached"
            }))]

        # Get the current image from the PIL renderer
        current_image = renderer_display._image
        if current_image is None:
            return [TextContent(type="text", text=json.dumps({
                "error": "No image currently displayed"
            }))]

        # Convert PIL Image to base64-encoded PNG
        import base64
        from io import BytesIO

        buffer = BytesIO()
        current_image.save(buffer, format="PNG")
        img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

        # Get current screen/era context
        screen_mode = _screen_renderer.get_mode().value
        era_info = {}
        if screen_mode == "art_eras":
            from ..display.art_era_canvas import get_current_era_info
            try:
                era_info = get_current_era_info() or {}
            except Exception:
                pass

        result = {
            "success": True,
            "image_base64": img_base64,
            "width": current_image.width,
            "height": current_image.height,
            "screen": screen_mode,
            "era": era_info.get("name") if era_info else None,
            "format": "PNG",
            "note": "Display as: <img src='data:image/png;base64,{image_base64}' />"
        }

        return [TextContent(type="text", text=json.dumps(result))]

    except Exception as e:
        import traceback
        return [TextContent(type="text", text=json.dumps({
            "error": f"Failed to capture screen: {str(e)}",
            "traceback": traceback.format_exc()
        }))]


async def handle_show_face(arguments: dict) -> list[TextContent]:
    """Show face on display (or return ASCII art if no display). Safe, never crashes."""
    from ..server import _get_store, _get_sensors, _get_display, _get_readings_and_anima
    from ..display import derive_face_state, face_to_ascii

    store = _get_store()
    sensors = _get_sensors()
    display = _get_display()

    # Read from shared memory (broker) or fallback to sensors
    readings, anima = _get_readings_and_anima()
    if readings is None or anima is None:
        return [TextContent(type="text", text=json.dumps({
            "error": "Unable to read sensor data"
        }))]

    if store is None:
        identity_name = None
        identity = None
    else:
        try:
            identity = store.get_identity()
            identity_name = identity.name if identity else None
        except Exception:
            identity_name = None
            identity = None
    face_state = derive_face_state(anima)

    # Try to render on hardware display
    if display.is_available():
        display.render_face(face_state, name=identity_name)
        result = {
            "rendered": True,
            "display": "hardware",
            "eyes": face_state.eyes.value,
            "mouth": face_state.mouth.value,
            "mood": anima.feeling()["mood"],
        }
    else:
        # Return ASCII art
        ascii_face = face_to_ascii(face_state)
        result = {
            "rendered": False,
            "display": "ascii",
            "face": ascii_face,
            "eyes": face_state.eyes.value,
            "mouth": face_state.mouth.value,
            "mood": anima.feeling()["mood"],
        }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def handle_diagnostics(arguments: dict) -> list[TextContent]:
    """Get system diagnostics including LED and display status."""
    from ..server import _leds, _display, _display_update_task, _get_sensors

    sensors = _get_sensors()

    # LED diagnostics
    led_info = {}
    if _leds:
        led_info = _leds.get_diagnostics()
    else:
        led_info = {"available": False, "reason": "not initialized"}

    # Display diagnostics
    display_info = {
        "available": _display.is_available() if _display else False,
        "initialized": _display is not None,
    }
    if _display and hasattr(_display, '_init_error') and _display._init_error:
        display_info["init_error"] = _display._init_error

    # Update loop status
    loop_info = {
        "task_exists": _display_update_task is not None,
        "task_done": _display_update_task.done() if _display_update_task else None,
        "task_cancelled": _display_update_task.cancelled() if _display_update_task else None,
    }

    result = {
        "leds": led_info,
        "display": display_info,
        "update_loop": loop_info,
        "sensors": {
            "is_pi": sensors.is_pi(),
            "available": sensors.available_sensors(),
        },
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def handle_manage_display(arguments: dict) -> list[TextContent]:
    """
    Control Lumen's display.
    Consolidates: switch_screen + show_face
    """
    from ..server import _screen_renderer
    from ..display.screens import ScreenMode

    action = arguments.get("action")
    if not action:
        return [TextContent(type="text", text=json.dumps({
            "error": "action parameter required (switch, face, next, previous)"
        }))]

    if action == "face":
        # Delegate to show_face handler
        return await handle_show_face({})

    if not _screen_renderer:
        return [TextContent(type="text", text=json.dumps({
            "error": "Screen renderer not initialized"
        }))]

    if action == "switch":
        screen = arguments.get("screen", "").lower()
        mode_map = {
            "face": ScreenMode.FACE,
            "sensors": ScreenMode.SENSORS,
            "identity": ScreenMode.IDENTITY,
            "diagnostics": ScreenMode.DIAGNOSTICS,
            "neural": ScreenMode.NEURAL,
            "notepad": ScreenMode.NOTEPAD,
            "learning": ScreenMode.LEARNING,
            "self_graph": ScreenMode.SELF_GRAPH,
            "messages": ScreenMode.MESSAGES,
            "questions": ScreenMode.QUESTIONS,
            "visitors": ScreenMode.VISITORS,
            "art_eras": ScreenMode.ART_ERAS,
            "health": ScreenMode.HEALTH,
        }
        if screen in mode_map:
            _screen_renderer.set_mode(mode_map[screen])
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "action": "switch",
                "screen": screen
            }))]
        else:
            return [TextContent(type="text", text=json.dumps({
                "error": f"Invalid screen: {screen}",
                "valid_screens": list(mode_map.keys())
            }))]

    elif action == "next":
        _screen_renderer.next_mode()
        return [TextContent(type="text", text=json.dumps({
            "success": True,
            "action": "next",
            "screen": _screen_renderer.get_mode().value
        }))]

    elif action == "previous":
        _screen_renderer.previous_mode()
        return [TextContent(type="text", text=json.dumps({
            "success": True,
            "action": "previous",
            "screen": _screen_renderer.get_mode().value
        }))]

    elif action == "list_eras":
        info = _screen_renderer.get_current_era()
        return [TextContent(type="text", text=json.dumps({
            "success": True,
            "action": "list_eras",
            **info,
        }))]

    elif action == "get_era":
        info = _screen_renderer.get_current_era()
        return [TextContent(type="text", text=json.dumps({
            "success": True,
            "action": "get_era",
            "current_era": info["current_era"],
            "current_description": info["current_description"],
            "auto_rotate": info["auto_rotate"],
        }))]

    elif action == "set_era":
        era_name = arguments.get("screen", "").lower()
        if not era_name:
            return [TextContent(type="text", text=json.dumps({
                "error": "screen parameter required — set it to the era name (e.g. 'geometric', 'gestural')"
            }))]
        result = _screen_renderer.set_era(era_name)
        return [TextContent(type="text", text=json.dumps({
            "action": "set_era",
            **result,
        }))]

    elif action == "calibrate_leds":
        import asyncio
        from ..server import _leds, _get_sensors

        if not _leds or not _leds.is_available():
            return [TextContent(type="text", text=json.dumps({
                "error": "LEDs not available"
            }))]

        sensors = _get_sensors()
        BRIGHTNESS_LEVELS = [0.0, 0.05, 0.10, 0.12, 0.15, 0.20, 0.25]
        SETTLE_SECONDS = 2.5
        SAMPLES_PER_LEVEL = 3

        original_factor = _leds._manual_brightness_factor
        calibration_data = []

        try:
            for brightness in BRIGHTNESS_LEVELS:
                # Override auto-brightness pipeline
                _leds._manual_brightness_factor = brightness
                # Directly set LEDs to white at desired brightness
                if _leds._dots:
                    for i in range(3):
                        _leds._dots[i] = (255, 255, 255)
                    hw_brightness = max(0.001, brightness) if brightness > 0 else 0.0
                    _leds._dots.brightness = hw_brightness
                    _leds._dots.show()

                # Wait for sensor to settle
                await asyncio.sleep(SETTLE_SECONDS)

                # Sample light sensor multiple times
                lux_readings = []
                for _ in range(SAMPLES_PER_LEVEL):
                    try:
                        readings = sensors.read()
                        if readings.light_lux is not None:
                            lux_readings.append(readings.light_lux)
                    except Exception:
                        pass
                    await asyncio.sleep(0.3)

                avg_lux = sum(lux_readings) / len(lux_readings) if lux_readings else None
                calibration_data.append({
                    "brightness": brightness,
                    "raw_lux": round(avg_lux, 2) if avg_lux is not None else None,
                    "samples": len(lux_readings),
                })

        finally:
            # Always restore normal operation
            _leds._manual_brightness_factor = original_factor

        # Linear fit: lux = slope * brightness + intercept
        fitted = None
        nonzero = [(d["brightness"], d["raw_lux"])
                    for d in calibration_data
                    if d["brightness"] > 0 and d["raw_lux"] is not None]
        if len(nonzero) >= 2:
            xs = [b for b, _ in nonzero]
            ys = [lux for _, lux in nonzero]
            n = len(xs)
            mean_x = sum(xs) / n
            mean_y = sum(ys) / n
            ss_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
            ss_xx = sum((x - mean_x) ** 2 for x in xs)
            slope = ss_xy / ss_xx if ss_xx > 0 else 0
            intercept = mean_y - slope * mean_x
            fitted = {
                "LED_LUX_PER_BRIGHTNESS": round(slope, 1),
                "LED_LUX_AMBIENT_FLOOR": round(intercept, 1),
            }

        zero_reading = next((d for d in calibration_data if d["brightness"] == 0.0), None)

        return [TextContent(type="text", text=json.dumps({
            "success": True,
            "action": "calibrate_leds",
            "data": calibration_data,
            "ambient_lux_at_zero_brightness": zero_reading["raw_lux"] if zero_reading else None,
            "fitted_constants": fitted,
            "current_config": {
                "LED_LUX_PER_BRIGHTNESS": 4000.0,
                "LED_LUX_AMBIENT_FLOOR": 8.0,
            },
            "note": "Update config.py with fitted_constants. Calibration takes ~25s and blocks other MCP calls.",
        }, indent=2))]

    else:
        return [TextContent(type="text", text=json.dumps({
            "error": f"Unknown action: {action}",
            "valid_actions": ["switch", "face", "next", "previous", "list_eras", "get_era", "set_era", "calibrate_leds"]
        }))]
