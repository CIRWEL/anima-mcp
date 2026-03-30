import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _parse(result):
    assert isinstance(result, list)
    assert len(result) == 1
    return json.loads(result[0].text)


@pytest.mark.asyncio
class TestNextStepsExtended:
    async def test_next_steps_success_with_bridge_connected(self):
        from anima_mcp.handlers.workflows import handle_next_steps

        class Bridge:
            async def check_availability(self):
                return True

        advocate = SimpleNamespace(
            analyze_current_state=lambda **kwargs: [{"priority": "high"}],
            get_next_steps_summary=lambda: {
                "next_action": {
                    "priority": "high",
                    "feeling": "calm",
                    "desire": "observe",
                    "action": "watch",
                },
                "total_steps": 3,
                "critical": 1,
                "high": 1,
                "medium": 1,
                "low": 0,
                "all_steps": ["watch", "reflect"],
            },
        )
        anima = SimpleNamespace(warmth=0.6, clarity=0.7, stability=0.8, presence=0.5)
        readings = SimpleNamespace()
        display = SimpleNamespace(is_available=lambda: True)
        eisv = SimpleNamespace(to_dict=lambda: {"E": 0.7})

        with patch("anima_mcp.accessors._get_store", return_value=SimpleNamespace()), \
             patch("anima_mcp.accessors._get_sensors", return_value=SimpleNamespace()), \
             patch("anima_mcp.accessors._get_display", return_value=display), \
             patch("anima_mcp.accessors._get_readings_and_anima", return_value=(readings, anima)), \
             patch("anima_mcp.accessors._get_server_bridge", return_value=Bridge()), \
             patch("anima_mcp.accessors._get_last_shm_data", return_value=None), \
             patch("anima_mcp.next_steps_advocate.get_advocate", return_value=advocate), \
             patch("anima_mcp.eisv_mapper.anima_to_eisv", return_value=eisv):
            data = _parse(await handle_next_steps({}))

        assert data["summary"]["priority"] == "high"
        assert data["current_state"]["unitares_connected"] is True
        assert data["current_state"]["eisv"]["E"] == 0.7

    async def test_next_steps_bridge_exception_sets_error_status(self):
        from anima_mcp.handlers.workflows import handle_next_steps

        class Bridge:
            async def check_availability(self):
                raise RuntimeError("bridge down")

        advocate = SimpleNamespace(
            analyze_current_state=lambda **kwargs: [],
            get_next_steps_summary=lambda: {"next_action": {}, "total_steps": 0, "critical": 0, "high": 0, "medium": 0, "low": 0, "all_steps": []},
        )
        anima = SimpleNamespace(warmth=0.1, clarity=0.2, stability=0.3, presence=0.4)
        readings = SimpleNamespace()
        display = SimpleNamespace(is_available=lambda: False)
        eisv = SimpleNamespace(to_dict=lambda: {"E": 0.1})

        with patch("anima_mcp.accessors._get_store", return_value=SimpleNamespace()), \
             patch("anima_mcp.accessors._get_sensors", return_value=SimpleNamespace()), \
             patch("anima_mcp.accessors._get_display", return_value=display), \
             patch("anima_mcp.accessors._get_readings_and_anima", return_value=(readings, anima)), \
             patch("anima_mcp.accessors._get_server_bridge", return_value=Bridge()), \
             patch("anima_mcp.accessors._get_last_shm_data", return_value=None), \
             patch("anima_mcp.next_steps_advocate.get_advocate", return_value=advocate), \
             patch("anima_mcp.eisv_mapper.anima_to_eisv", return_value=eisv):
            data = _parse(await handle_next_steps({}))

        assert data["current_state"]["unitares_connected"] is False
        assert "error:" in data["current_state"]["unitares_status"]


@pytest.mark.asyncio
class TestSetCalibrationExtended:
    async def test_set_calibration_rejects_invalid_calibration(self):
        from anima_mcp.handlers.workflows import handle_set_calibration

        calibration = SimpleNamespace(to_dict=lambda: {"ambient_temp_min": 10.0})
        updated_cal = SimpleNamespace(validate=lambda: (False, "bad bounds"), to_dict=lambda: {"ambient_temp_min": 10.0})

        with patch("anima_mcp.config.get_calibration", return_value=calibration), \
             patch("anima_mcp.config.ConfigManager", return_value=MagicMock()), \
             patch("anima_mcp.config.NervousSystemCalibration.from_dict", return_value=updated_cal):
            data = _parse(await handle_set_calibration({"updates": {"ambient_temp_min": 99.0}}))

        assert "error" in data
        assert "Invalid calibration" in data["error"]

    async def test_set_calibration_success_includes_metadata(self):
        from anima_mcp.handlers.workflows import handle_set_calibration

        calibration = SimpleNamespace(to_dict=lambda: {"ambient_temp_min": 10.0})
        updated_cal = SimpleNamespace(
            validate=lambda: (True, None),
            to_dict=lambda: {"ambient_temp_min": 12.0},
        )
        cfg = SimpleNamespace(nervous_system=None)
        cfg_with_meta = SimpleNamespace(metadata={
            "calibration_last_updated": "2026-03-14T00:00:00",
            "calibration_last_updated_by": "agent",
            "calibration_update_count": 3,
        })
        manager = MagicMock()
        manager.load.return_value = cfg
        manager.save.return_value = True
        manager.reload.return_value = cfg_with_meta

        with patch("anima_mcp.config.get_calibration", return_value=calibration), \
             patch("anima_mcp.config.ConfigManager", return_value=manager), \
             patch("anima_mcp.config.NervousSystemCalibration.from_dict", return_value=updated_cal):
            data = _parse(await handle_set_calibration({"updates": {"ambient_temp_min": 12.0}, "source": "agent"}))

        assert data["success"] is True
        assert data["metadata"]["update_count"] == 3

    async def test_set_calibration_save_failure(self):
        from anima_mcp.handlers.workflows import handle_set_calibration

        calibration = SimpleNamespace(to_dict=lambda: {"ambient_temp_min": 10.0})
        updated_cal = SimpleNamespace(validate=lambda: (True, None), to_dict=lambda: {"ambient_temp_min": 12.0})
        manager = MagicMock()
        manager.load.return_value = SimpleNamespace()
        manager.save.return_value = False

        with patch("anima_mcp.config.get_calibration", return_value=calibration), \
             patch("anima_mcp.config.ConfigManager", return_value=manager), \
             patch("anima_mcp.config.NervousSystemCalibration.from_dict", return_value=updated_cal):
            data = _parse(await handle_set_calibration({"updates": {"ambient_temp_min": 12.0}}))

        assert data["error"] == "Failed to save calibration"


@pytest.mark.asyncio
class TestLumenContextExtended:
    async def test_get_lumen_context_records_interaction_level_and_eisv(self):
        from anima_mcp.handlers.workflows import handle_get_lumen_context

        class FakeReadings:
            def to_dict(self):
                return {"light_lux": 100}

        identity = SimpleNamespace(
            name="Lumen",
            creature_id="lmn-1",
            born_at=datetime(2026, 1, 1),
            total_awakenings=5,
            age_seconds=lambda: 3600,
            total_alive_seconds=1800,
            alive_ratio=lambda: 0.5,
        )
        store = SimpleNamespace(
            get_identity=lambda: identity,
            get_session_alive_seconds=lambda: 100,
            record_state=MagicMock(),
        )
        sensors = SimpleNamespace(is_pi=lambda: False)
        anima = SimpleNamespace(
            warmth=0.3,
            clarity=0.4,
            stability=0.5,
            presence=0.6,
            feeling=lambda: {"mood": "calm"},
        )
        recent_message = SimpleNamespace(author="user", timestamp=datetime.now().timestamp() - 60)
        eisv = SimpleNamespace(to_dict=lambda: {"E": 0.3})

        with patch("anima_mcp.accessors._get_store", return_value=store), \
             patch("anima_mcp.accessors._get_sensors", return_value=sensors), \
             patch("anima_mcp.accessors._get_readings_and_anima", return_value=(FakeReadings(), anima)), \
             patch("anima_mcp.messages.get_recent_messages", return_value=[recent_message]), \
             patch("anima_mcp.eisv_mapper.anima_to_eisv", return_value=eisv):
            data = _parse(await handle_get_lumen_context({"include": ["identity", "anima", "sensors", "mood", "eisv"]}))

        assert data["identity"]["name"] == "Lumen"
        assert data["eisv"]["E"] == 0.3
        assert "mood" in data
        store.record_state.assert_called_once()
        recorded_sensor_data = store.record_state.call_args[0][4]
        assert "interaction_level" in recorded_sensor_data

    async def test_get_lumen_context_handles_identity_error(self):
        from anima_mcp.handlers.workflows import handle_get_lumen_context

        store = SimpleNamespace(get_identity=lambda: (_ for _ in ()).throw(RuntimeError("identity fail")))
        with patch("anima_mcp.accessors._get_store", return_value=store), \
             patch("anima_mcp.accessors._get_sensors", return_value=SimpleNamespace(is_pi=lambda: False)), \
             patch("anima_mcp.accessors._get_readings_and_anima", return_value=(None, None)):
            data = _parse(await handle_get_lumen_context({"include": "identity"}))

        assert "error" in data["identity"]


@pytest.mark.asyncio
class TestLearningVisualizationExtended:
    async def test_learning_visualization_success(self):
        from anima_mcp.handlers.workflows import handle_learning_visualization

        store = SimpleNamespace(db_path=":memory:")
        summary = {"dominant_pattern": "night calm"}
        visualizer = SimpleNamespace(get_learning_summary=lambda readings, anima: summary)

        with patch("anima_mcp.accessors._get_store", return_value=store), \
             patch("anima_mcp.accessors._get_readings_and_anima", return_value=(SimpleNamespace(), SimpleNamespace())), \
             patch("anima_mcp.learning_visualization.LearningVisualizer", return_value=visualizer):
            data = _parse(await handle_learning_visualization({}))

        assert data["dominant_pattern"] == "night calm"

    async def test_learning_visualization_sensor_error(self):
        from anima_mcp.handlers.workflows import handle_learning_visualization

        with patch("anima_mcp.accessors._get_store", return_value=SimpleNamespace(db_path=":memory:")), \
             patch("anima_mcp.accessors._get_readings_and_anima", return_value=(None, None)):
            data = _parse(await handle_learning_visualization({}))

        assert data["error"] == "Unable to read sensor data"
