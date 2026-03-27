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
class TestGetStateExtended:
    async def test_get_state_includes_inner_life_and_records_state(self):
        from anima_mcp.handlers.state_queries import handle_get_state

        class FakeReadings:
            def to_dict(self):
                return {
                    "timestamp": "now",
                    "ambient_temp_c": 22,
                    "humidity_pct": 40,
                    "light_lux": 100,
                    "pressure_hpa": 1012,
                    "cpu_temp_c": 50,
                    "cpu_percent": 20,
                    "memory_percent": 30,
                    "disk_percent": 40,
                }

        identity = SimpleNamespace(
            name="Lumen",
            creature_id="creature-123456",
            total_awakenings=5,
            age_seconds=lambda: 3600,
            total_alive_seconds=1200,
            alive_ratio=lambda: 0.33,
        )
        store = SimpleNamespace(
            get_identity=lambda: identity,
            get_session_alive_seconds=lambda: 100,
            record_state=MagicMock(),
        )
        sensors = SimpleNamespace(is_pi=lambda: False)
        anima = SimpleNamespace(
            warmth=0.4,
            clarity=0.5,
            stability=0.6,
            presence=0.7,
            feeling=lambda: {"mood": "calm"},
        )
        recent = [SimpleNamespace(author="user", timestamp=datetime.now().timestamp() - 30)]

        with patch("anima_mcp.accessors._get_store", return_value=store), \
             patch("anima_mcp.accessors._get_sensors", return_value=sensors), \
             patch("anima_mcp.accessors._get_readings_and_anima", return_value=(FakeReadings(), anima)), \
             patch("anima_mcp.handlers.state_queries.extract_neural_bands", return_value={"alpha": 0.2}), \
             patch("anima_mcp.accessors._get_last_shm_data", return_value={"inner_life": {"temperament": "gentle", "drives": {"curiosity": 0.8}, "strongest_drive": "curiosity"}}), \
             patch("anima_mcp.messages.get_recent_messages", return_value=recent):
            data = _parse(await handle_get_state({}))

        assert data["mood"] == "calm"
        assert data["identity"]["name"] == "Lumen"
        assert data["inner_life"]["temperament"] == "gentle"
        store.record_state.assert_called_once()
        assert "interaction_level" in store.record_state.call_args[0][4]

    async def test_get_state_identity_error_returns_error(self):
        from anima_mcp.handlers.state_queries import handle_get_state

        store = SimpleNamespace(get_identity=lambda: (_ for _ in ()).throw(RuntimeError("identity fail")))
        with patch("anima_mcp.accessors._get_store", return_value=store), \
             patch("anima_mcp.accessors._get_sensors", return_value=SimpleNamespace(is_pi=lambda: False)), \
             patch("anima_mcp.accessors._get_readings_and_anima", return_value=(SimpleNamespace(to_dict=lambda: {}), SimpleNamespace())):
            data = _parse(await handle_get_state({}))
        assert "error" in data
        assert "identity fail" in data["error"]


@pytest.mark.asyncio
class TestReadSensorsExtended:
    async def test_read_sensors_uses_shared_memory_source(self):
        from anima_mcp.handlers.state_queries import handle_read_sensors

        class FakeReadings:
            def to_dict(self):
                return {"timestamp": "now", "cpu_temp_c": 50, "ambient_temp_c": None}

        shm = SimpleNamespace(read=lambda: {"ok": True})
        with patch("anima_mcp.accessors._get_sensors", return_value=SimpleNamespace(available_sensors=lambda: ["cpu"], is_pi=lambda: True)), \
             patch("anima_mcp.accessors._get_readings_and_anima", return_value=(FakeReadings(), None)), \
             patch("anima_mcp.accessors._get_shm_client", return_value=shm):
            data = _parse(await handle_read_sensors({}))

        assert data["source"] == "shared_memory"
        assert "ambient_temp_c" not in data["readings"]  # null suppressed

    async def test_read_sensors_direct_source_when_no_shm(self):
        from anima_mcp.handlers.state_queries import handle_read_sensors

        class FakeReadings:
            def to_dict(self):
                return {"timestamp": "now", "cpu_temp_c": 50}

        with patch("anima_mcp.accessors._get_sensors", return_value=SimpleNamespace(available_sensors=lambda: ["cpu"], is_pi=lambda: False)), \
             patch("anima_mcp.accessors._get_readings_and_anima", return_value=(FakeReadings(), None)), \
             patch("anima_mcp.accessors._get_shm_client", return_value=None):
            data = _parse(await handle_read_sensors({}))

        assert data["source"] == "direct_sensors"


@pytest.mark.asyncio
class TestGetIdentityAndCalibrationExtended:
    async def test_get_identity_success_shape(self):
        from anima_mcp.handlers.state_queries import handle_get_identity

        identity = SimpleNamespace(
            creature_id="id-123",
            name="Lumen",
            born_at=datetime(2026, 1, 1),
            total_awakenings=7,
            current_awakening_at=None,
            total_alive_seconds=1500,
            age_seconds=lambda: 5000,
            alive_ratio=lambda: 0.3,
            name_history=["Lumen"],
        )
        store = SimpleNamespace(get_identity=lambda: identity, get_session_alive_seconds=lambda: 120)
        with patch("anima_mcp.accessors._get_store", return_value=store):
            data = _parse(await handle_get_identity({}))
        assert data["name"] == "Lumen"
        assert data["total_awakenings"] == 7
        assert data["session_alive_seconds"] == 120

    async def test_get_calibration_metadata_defaults(self):
        from anima_mcp.handlers.state_queries import handle_get_calibration

        config = SimpleNamespace(
            nervous_system=SimpleNamespace(to_dict=lambda: {"ambient_temp_min": 10}),
            metadata={},
        )
        manager = SimpleNamespace(
            reload=lambda: config,
            config_path=SimpleNamespace(exists=lambda: False, __str__=lambda self: "/tmp/nope"),
        )
        with patch("anima_mcp.handlers.state_queries.ConfigManager", return_value=manager):
            data = _parse(await handle_get_calibration({}))
        assert data["calibration"]["ambient_temp_min"] == 10
        assert data["metadata"]["update_count"] == 0
