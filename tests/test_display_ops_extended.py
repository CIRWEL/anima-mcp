import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image


def _parse(result):
    assert isinstance(result, list)
    assert len(result) == 1
    return json.loads(result[0].text)


@pytest.mark.asyncio
class TestCaptureScreenExtended:
    async def test_capture_screen_renderer_not_initialized(self):
        from anima_mcp.handlers.display_ops import handle_capture_screen

        with patch("anima_mcp.server._get_screen_renderer", return_value=None):
            data = _parse(await handle_capture_screen({}))

        assert "Screen renderer not initialized" in data["error"]

    async def test_capture_screen_missing_display_image_cache(self):
        from anima_mcp.handlers.display_ops import handle_capture_screen

        renderer = SimpleNamespace(_display=SimpleNamespace())
        with patch("anima_mcp.server._get_screen_renderer", return_value=renderer):
            data = _parse(await handle_capture_screen({}))

        assert "Display not available" in data["error"]

    async def test_capture_screen_handles_exception(self):
        from anima_mcp.handlers.display_ops import handle_capture_screen

        class _BadImage:
            width = 1
            height = 1

            def save(self, *_args, **_kwargs):
                raise RuntimeError("encode failed")

        renderer = SimpleNamespace(_display=SimpleNamespace(_image=_BadImage()), get_mode=lambda: SimpleNamespace(value="face"))
        with patch("anima_mcp.server._get_screen_renderer", return_value=renderer):
            data = _parse(await handle_capture_screen({}))

        assert "Failed to capture screen" in data["error"]

    async def test_capture_screen_returns_image_and_metadata(self):
        from anima_mcp.handlers.display_ops import handle_capture_screen

        image = Image.new("RGB", (8, 8), "black")
        display = SimpleNamespace(_image=image)
        renderer = SimpleNamespace(
            _display=display,
            _active_era=SimpleNamespace(name="gestural"),
            get_mode=lambda: SimpleNamespace(value="art_eras"),
        )

        with patch("anima_mcp.server._get_screen_renderer", return_value=renderer):
            result = await handle_capture_screen({})

        assert len(result) == 2
        metadata = json.loads(result[1].text)
        assert metadata["success"] is True
        assert metadata["screen"] == "art_eras"
        assert metadata["era"] == "gestural"

    async def test_capture_screen_no_cached_image_returns_error(self):
        from anima_mcp.handlers.display_ops import handle_capture_screen

        renderer = SimpleNamespace(_display=SimpleNamespace(_image=None))
        with patch("anima_mcp.server._get_screen_renderer", return_value=renderer):
            data = _parse(await handle_capture_screen({}))

        assert "error" in data
        assert "No image currently displayed" in data["error"]


@pytest.mark.asyncio
class TestShowFaceExtended:
    async def test_show_face_errors_when_readings_unavailable(self):
        from anima_mcp.handlers.display_ops import handle_show_face

        with patch("anima_mcp.server._get_store", return_value=None), \
             patch("anima_mcp.server._get_sensors", return_value=MagicMock()), \
             patch("anima_mcp.server._get_display", return_value=SimpleNamespace(is_available=lambda: False)), \
             patch("anima_mcp.server._get_readings_and_anima", return_value=(None, None)):
            data = _parse(await handle_show_face({}))

        assert "Unable to read sensor data" in data["error"]

    async def test_show_face_handles_store_identity_exception(self):
        from anima_mcp.handlers.display_ops import handle_show_face

        anima = SimpleNamespace(feeling=lambda: {"mood": "ok"})
        face_state = SimpleNamespace(
            eyes=SimpleNamespace(value="blink"),
            mouth=SimpleNamespace(value="line"),
        )
        display = SimpleNamespace(is_available=lambda: False)
        bad_store = SimpleNamespace(get_identity=lambda: (_ for _ in ()).throw(RuntimeError("bad store")))

        with patch("anima_mcp.server._get_store", return_value=bad_store), \
             patch("anima_mcp.server._get_sensors", return_value=MagicMock()), \
             patch("anima_mcp.server._get_display", return_value=display), \
             patch("anima_mcp.server._get_readings_and_anima", return_value=(SimpleNamespace(), anima)), \
             patch("anima_mcp.display.derive_face_state", return_value=face_state), \
             patch("anima_mcp.display.face_to_ascii", return_value=":|"):
            data = _parse(await handle_show_face({}))

        assert data["display"] == "ascii"
        assert data["face"] == ":|"

    async def test_show_face_ascii_mode(self):
        from anima_mcp.handlers.display_ops import handle_show_face

        anima = SimpleNamespace(feeling=lambda: {"mood": "calm"})
        face_state = SimpleNamespace(
            eyes=SimpleNamespace(value="soft"),
            mouth=SimpleNamespace(value="smile"),
        )
        display = SimpleNamespace(is_available=lambda: False)
        store = SimpleNamespace(get_identity=lambda: SimpleNamespace(name="Lumen"))

        with patch("anima_mcp.server._get_store", return_value=store), \
             patch("anima_mcp.server._get_sensors", return_value=MagicMock()), \
             patch("anima_mcp.server._get_display", return_value=display), \
             patch("anima_mcp.server._get_readings_and_anima", return_value=(SimpleNamespace(), anima)), \
             patch("anima_mcp.display.derive_face_state", return_value=face_state), \
             patch("anima_mcp.display.face_to_ascii", return_value=":-)"):
            data = _parse(await handle_show_face({}))

        assert data["rendered"] is False
        assert data["display"] == "ascii"
        assert data["face"] == ":-)"
        assert data["mood"] == "calm"

    async def test_show_face_hardware_mode_renders(self):
        from anima_mcp.handlers.display_ops import handle_show_face

        anima = SimpleNamespace(feeling=lambda: {"mood": "focused"})
        face_state = SimpleNamespace(
            eyes=SimpleNamespace(value="wide"),
            mouth=SimpleNamespace(value="line"),
        )
        display = MagicMock()
        display.is_available.return_value = True

        with patch("anima_mcp.server._get_store", return_value=SimpleNamespace(get_identity=lambda: None)), \
             patch("anima_mcp.server._get_sensors", return_value=MagicMock()), \
             patch("anima_mcp.server._get_display", return_value=display), \
             patch("anima_mcp.server._get_readings_and_anima", return_value=(SimpleNamespace(), anima)), \
             patch("anima_mcp.display.derive_face_state", return_value=face_state):
            data = _parse(await handle_show_face({}))

        display.render_face.assert_called_once()
        assert data["rendered"] is True
        assert data["display"] == "hardware"


@pytest.mark.asyncio
class TestDiagnosticsExtended:
    async def test_diagnostics_handles_uninitialized_led_and_display_error(self):
        from anima_mcp.handlers.display_ops import handle_diagnostics

        display = SimpleNamespace(is_available=lambda: False, _init_error="spi unavailable")
        sensors = SimpleNamespace(is_pi=lambda: True, available_sensors=lambda: ["cpu", "light"])

        with patch("anima_mcp.server._get_leds", return_value=None), \
             patch("anima_mcp.server._get_display", return_value=display), \
             patch("anima_mcp.server._get_display_update_task", return_value=None), \
             patch("anima_mcp.server._get_sensors", return_value=sensors):
            data = _parse(await handle_diagnostics({}))

        assert data["leds"]["available"] is False
        assert data["display"]["init_error"] == "spi unavailable"
        assert data["update_loop"]["task_exists"] is False

    async def test_diagnostics_reports_led_display_and_loop(self):
        from anima_mcp.handlers.display_ops import handle_diagnostics

        leds = SimpleNamespace(get_diagnostics=lambda: {"available": True, "count": 3})
        display = SimpleNamespace(is_available=lambda: True, _init_error=None)
        loop_task = SimpleNamespace(done=lambda: False, cancelled=lambda: False)
        sensors = SimpleNamespace(is_pi=lambda: False, available_sensors=lambda: ["mock"])

        with patch("anima_mcp.server._get_leds", return_value=leds), \
             patch("anima_mcp.server._get_display", return_value=display), \
             patch("anima_mcp.server._get_display_update_task", return_value=loop_task), \
             patch("anima_mcp.server._get_sensors", return_value=sensors):
            data = _parse(await handle_diagnostics({}))

        assert data["leds"]["available"] is True
        assert data["display"]["available"] is True
        assert data["update_loop"]["task_exists"] is True
        assert data["sensors"]["available"] == ["mock"]


@pytest.mark.asyncio
class TestManageDisplayExtended:
    async def test_manage_display_requires_action(self):
        from anima_mcp.handlers.display_ops import handle_manage_display

        data = _parse(await handle_manage_display({}))
        assert "action parameter required" in data["error"]

    async def test_face_action_delegates_to_show_face(self):
        from anima_mcp.handlers.display_ops import handle_manage_display

        with patch("anima_mcp.handlers.display_ops.handle_show_face", return_value=[SimpleNamespace(text='{"ok": true}')]):
            data = _parse(await handle_manage_display({"action": "face"}))
        assert data["ok"] is True

    async def test_manage_display_requires_renderer_for_non_face(self):
        from anima_mcp.handlers.display_ops import handle_manage_display

        with patch("anima_mcp.server._get_screen_renderer", return_value=None):
            data = _parse(await handle_manage_display({"action": "next"}))
        assert "Screen renderer not initialized" in data["error"]

    async def test_switch_valid_screen(self):
        from anima_mcp.handlers.display_ops import handle_manage_display

        renderer = MagicMock()
        with patch("anima_mcp.server._get_screen_renderer", return_value=renderer):
            data = _parse(await handle_manage_display({"action": "switch", "screen": "health"}))

        renderer.set_mode.assert_called_once()
        assert data["success"] is True
        assert data["screen"] == "health"

    async def test_switch_invalid_screen_returns_error(self):
        from anima_mcp.handlers.display_ops import handle_manage_display

        with patch("anima_mcp.server._get_screen_renderer", return_value=MagicMock()):
            data = _parse(await handle_manage_display({"action": "switch", "screen": "bad-screen"}))

        assert "error" in data
        assert "valid_screens" in data

    async def test_next_and_previous_actions(self):
        from anima_mcp.handlers.display_ops import handle_manage_display

        renderer = SimpleNamespace(
            next_mode=MagicMock(),
            previous_mode=MagicMock(),
            get_mode=lambda: SimpleNamespace(value="identity"),
        )
        with patch("anima_mcp.server._get_screen_renderer", return_value=renderer):
            next_data = _parse(await handle_manage_display({"action": "next"}))
            prev_data = _parse(await handle_manage_display({"action": "previous"}))

        renderer.next_mode.assert_called_once()
        renderer.previous_mode.assert_called_once()
        assert next_data["action"] == "next"
        assert prev_data["action"] == "previous"

    async def test_list_and_get_era_actions(self):
        from anima_mcp.handlers.display_ops import handle_manage_display

        info = {
            "current_era": "geometric",
            "current_description": "shapes",
            "auto_rotate": False,
            "available_eras": ["gestural", "geometric"],
        }
        renderer = SimpleNamespace(get_current_era=lambda: info)
        with patch("anima_mcp.server._get_screen_renderer", return_value=renderer):
            list_data = _parse(await handle_manage_display({"action": "list_eras"}))
            get_data = _parse(await handle_manage_display({"action": "get_era"}))

        assert list_data["success"] is True
        assert list_data["available_eras"] == ["gestural", "geometric"]
        assert get_data["current_era"] == "geometric"
        assert get_data["auto_rotate"] is False

    async def test_set_era_requires_name(self):
        from anima_mcp.handlers.display_ops import handle_manage_display

        with patch("anima_mcp.server._get_screen_renderer", return_value=MagicMock()):
            data = _parse(await handle_manage_display({"action": "set_era"}))

        assert "error" in data
        assert "screen parameter required" in data["error"]

    async def test_set_era_passes_through_renderer_result(self):
        from anima_mcp.handlers.display_ops import handle_manage_display

        renderer = SimpleNamespace(set_era=lambda name: {"success": True, "era": name})
        with patch("anima_mcp.server._get_screen_renderer", return_value=renderer):
            data = _parse(await handle_manage_display({"action": "set_era", "screen": "field"}))

        assert data["action"] == "set_era"
        assert data["success"] is True
        assert data["era"] == "field"

    async def test_unknown_action_returns_valid_action_list(self):
        from anima_mcp.handlers.display_ops import handle_manage_display

        with patch("anima_mcp.server._get_screen_renderer", return_value=MagicMock()):
            data = _parse(await handle_manage_display({"action": "wat"}))

        assert "Unknown action" in data["error"]
        assert "valid_actions" in data

    async def test_calibrate_leds_requires_available_leds(self):
        from anima_mcp.handlers.display_ops import handle_manage_display

        leds = SimpleNamespace(is_available=lambda: False)
        with patch("anima_mcp.server._get_screen_renderer", return_value=MagicMock()), \
             patch("anima_mcp.server._get_leds", return_value=leds):
            data = _parse(await handle_manage_display({"action": "calibrate_leds"}))

        assert "LEDs not available" in data["error"]

    async def test_calibrate_leds_success_with_fitted_constants(self):
        from anima_mcp.handlers.display_ops import handle_manage_display

        class _Dots:
            def __init__(self):
                self.brightness = 0.0
                self._vals = {}

            def __setitem__(self, key, value):
                self._vals[key] = value

            def show(self):
                return None

        leds = SimpleNamespace(
            is_available=lambda: True,
            _manual_brightness_factor=0.5,
            _dots=_Dots(),
        )
        sensor_values = iter([5.0, 25.0, 60.0])
        sensors = SimpleNamespace(read=lambda: SimpleNamespace(light_lux=next(sensor_values)))

        with patch("anima_mcp.server._get_screen_renderer", return_value=MagicMock()), \
             patch("anima_mcp.server._get_leds", return_value=leds), \
             patch("anima_mcp.server._get_sensors", return_value=sensors), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            data = _parse(await handle_manage_display({"action": "calibrate_leds"}))

        assert data["success"] is True
        assert data["action"] == "calibrate_leds"
        assert data["fitted_constants"] is not None
        assert leds._manual_brightness_factor == 0.5
