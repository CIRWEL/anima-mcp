import json
from pathlib import Path

import pytest

from anima_mcp.light_attribution import (
    LED_PROPRIOCEPTION_SCHEMA,
    LearnedLedLuxResidual,
    gated_external_light_lux,
    led_optical_drive,
    publish_led_proprioception,
    read_led_proprioception,
)
from anima_mcp.self_model import SelfModel


def test_gated_external_light_lux_has_one_admission_rule():
    assert gated_external_light_lux(None) is None
    assert gated_external_light_lux({
        "status": "warming",
        "external_lux_residual": 12.0,
    }) is None
    assert gated_external_light_lux({
        "status": "ready_shadow",
        "external_lux_residual": float("nan"),
    }) is None
    assert gated_external_light_lux({
        "status": "ready_shadow",
        "external_lux_residual": 12.0,
    }) == 12.0


def led_state(drive: float) -> dict:
    """White LEDs make normalized brightness equal optical drive."""
    return {
        "schema": LED_PROPRIOCEPTION_SCHEMA,
        "source": "led_hardware_controller",
        "brightness": drive,
        "colors": [[255, 255, 255]] * 3,
        "fresh": True,
    }


def breathing_state(applied_channel: int) -> dict:
    """Vary applied pulse output while the logical LED command stays fixed."""
    return {
        "schema": LED_PROPRIOCEPTION_SCHEMA,
        "source": "led_hardware_controller",
        "brightness": 0.08,
        "target_brightness": 0.08,
        "colors": [[255, 255, 255]] * 3,
        "applied_colors": [[applied_channel] * 3] * 3,
        "is_dancing": False,
        "is_flashing": False,
        "fresh": True,
    }


def train_clean_bidirectional_model(
    model: LearnedLedLuxResidual,
    *,
    ambient_lux: float = 100.0,
    slope: float = 500.0,
) -> tuple[float, dict, float]:
    timestamp = 100.0
    filtered_drive = None

    def observe(state: dict) -> None:
        nonlocal filtered_drive, timestamp
        drive = led_optical_drive(state)
        assert drive is not None
        filtered_drive = (
            drive
            if filtered_drive is None
            else 0.8 * filtered_drive + 0.2 * drive
        )
        model.observe(
            ambient_lux + slope * filtered_drive,
            state,
            observed_at=timestamp,
        )
        timestamp += 1.0

    current = breathing_state(64)
    observe(current)
    for index in range(28):
        current = breathing_state(192 if index % 2 == 0 else 64)
        observe(current)
    assert filtered_drive is not None
    return ambient_lux, current, filtered_drive


def test_optical_drive_is_color_aware():
    white = {"brightness": 0.12, "colors": [[255, 255, 255]] * 3}
    half = {"brightness": 0.12, "colors": [[128, 128, 128]] * 3}
    black = {"brightness": 0.12, "colors": [[0, 0, 0]] * 3}

    assert led_optical_drive(white) == pytest.approx(0.12)
    assert led_optical_drive(half) == pytest.approx(0.12 * 128 / 255)
    assert led_optical_drive(black) == 0.0

    scaled = {
        "brightness": 0.12,
        "colors": [[255, 255, 255]] * 3,
        "applied_colors": [[64, 64, 64]] * 3,
    }
    assert led_optical_drive(scaled) == pytest.approx(0.12 * 64 / 255)


def test_action_copy_round_trip_and_staleness(tmp_path):
    path = tmp_path / "led.json"
    state = {
        "brightness": 0.08,
        "colors": [(255, 128, 0), (0, 64, 255), (10, 20, 30)],
        "expression_mode": "balanced",
    }

    published = publish_led_proprioception(state, path=path, captured_at=100.0)
    fresh = read_led_proprioception(path=path, now=105.0, max_age_seconds=10.0)

    assert published["schema"] == LED_PROPRIOCEPTION_SCHEMA
    assert fresh is not None
    assert fresh["source"] == "led_hardware_controller"
    assert fresh["brightness"] == pytest.approx(0.08)
    assert fresh["target_brightness"] == pytest.approx(0.08)
    assert fresh["fresh"] is True
    assert fresh["age_seconds"] == pytest.approx(5.0)
    assert read_led_proprioception(path=path, now=111.0, max_age_seconds=10.0) is None


def test_action_history_aligns_efference_copy_to_light_capture_time(tmp_path):
    path = tmp_path / "led-history.json"
    for captured_at, channel in [(100.0, 64), (100.5, 128), (101.0, 192)]:
        state = breathing_state(channel)
        publish_led_proprioception(state, path=path, captured_at=captured_at)

    paired = read_led_proprioception(
        path=path,
        now=101.2,
        max_age_seconds=2.0,
        at_time=100.6,
        max_alignment_error_seconds=0.3,
    )
    assert paired is not None
    assert paired["captured_at_unix"] == 100.5
    assert paired["alignment_error_seconds"] == pytest.approx(0.1)
    assert paired["paired_to_light_observed_at_unix"] == 100.6

    assert (
        read_led_proprioception(
            path=path,
            now=101.2,
            max_age_seconds=2.0,
            at_time=90.0,
            max_alignment_error_seconds=0.3,
        )
        is None
    )


def test_action_copy_rejects_malformed_or_future_data(tmp_path):
    path = tmp_path / "led.json"
    path.write_text(json.dumps({"schema": LED_PROPRIOCEPTION_SCHEMA}))
    assert read_led_proprioception(path=path, now=100.0) is None

    publish_led_proprioception(
        {"brightness": 0.08, "colors": [[255, 255, 255]] * 3},
        path=path,
        captured_at=105.0,
    )
    assert read_led_proprioception(path=path, now=100.0) is None


def test_residual_is_unknown_while_model_is_cold():
    model = LearnedLedLuxResidual()
    result = model.observe(110.0, led_state(0.02), observed_at=100.0)

    assert result["status"] == "warming"
    assert result["self_glow_estimate_lux"] is None
    assert result["external_lux_residual"] is None
    assert result["raw_lux"] == 110.0
    assert result["clarity_input"] is None
    assert result["used_by_clarity"] is False
    assert result["used_by_environment_preferences"] is False


def test_bidirectional_breathing_differences_unlock_shadow_residual():
    model = LearnedLedLuxResidual()
    ambient_lux, current_state, filtered_drive = train_clean_bidirectional_model(model)

    result = model.attribute(
        ambient_lux + 500.0 * filtered_drive,
        current_state,
    )

    assert result["status"] == "ready_shadow"
    assert result["authority"] == "gated_secondary_signal"
    assert result["model"]["instrument"] == "internal_led_breathing_pulse"
    assert result["model"]["instrument_sample_count"] == 24
    assert result["model"]["up_transitions"] == 12
    assert result["model"]["down_transitions"] == 12
    assert result["model"]["slope_lux_per_drive"] == pytest.approx(500.0)
    assert result["estimate_confidence"] >= result["model"]["confidence_gate"]
    assert result["self_glow_estimate_lux"] == pytest.approx(500.0 * filtered_drive)
    assert result["external_lux_residual"] == pytest.approx(ambient_lux)
    assert result["used_by_clarity"] is True
    assert result["clarity_input"] == "external_lux_residual"
    assert result["used_by_environment_preferences"] is True
    assert result["environment_preference_input"] == "external_lux_residual"


def test_ready_model_reports_conflict_instead_of_clamping():
    model = LearnedLedLuxResidual()
    _, current_state, _ = train_clean_bidirectional_model(model)

    result = model.attribute(1.0, current_state)

    assert result["status"] == "model_conflict"
    assert result["candidate_self_glow_lux"] > result["raw_lux"]
    assert result["self_glow_estimate_lux"] is None
    assert result["external_lux_residual"] is None


def test_robust_median_tolerates_one_coincident_room_light_change():
    transitions = []
    for i, slope in enumerate([500.0] * 23 + [-2000.0]):
        before = 0.02 if i % 2 == 0 else 0.06
        after = 0.06 if i % 2 == 0 else 0.02
        delta_drive = after - before
        transitions.append(
            {
                "before_drive": before,
                "after_drive": after,
                "delta_lux": slope * delta_drive,
                "slope_lux_per_drive": slope,
                "captured_at_unix": 100.0 + i,
            }
        )
    model = LearnedLedLuxResidual(
        {
            "model_kind": LearnedLedLuxResidual.MODEL_KIND,
            "transitions": transitions,
        }
    )

    stats = model.model_stats()
    assert stats["slope_lux_per_drive"] == 500.0
    assert stats["positive_fraction"] == pytest.approx(23 / 24)
    assert stats["ready"] is True


def test_inconsistent_transition_directions_remain_unknown():
    transitions = []
    for i, slope in enumerate([500.0, -500.0] * 12):
        before = 0.02 if i % 2 == 0 else 0.06
        after = 0.06 if i % 2 == 0 else 0.02
        delta_drive = after - before
        transitions.append(
            {
                "before_drive": before,
                "after_drive": after,
                "delta_lux": slope * delta_drive,
                "slope_lux_per_drive": slope,
                "captured_at_unix": 100.0 + i,
            }
        )
    model = LearnedLedLuxResidual(
        {
            "model_kind": LearnedLedLuxResidual.MODEL_KIND,
            "transitions": transitions,
        }
    )

    result = model.attribute(120.0, led_state(0.08))
    assert result["status"] == "warming"
    assert result["external_lux_residual"] is None
    assert (
        "breathing_response_is_inconsistent" in result["model"]["unknown_reasons"]
    )


def test_persisted_evidence_from_another_instrument_is_rejected():
    model = LearnedLedLuxResidual(
        {
            "model_kind": LearnedLedLuxResidual.MODEL_KIND,
            "transitions": [
                {
                    "before_drive": 0.02,
                    "after_drive": 0.06,
                    "delta_lux": 20.0,
                    "slope_lux_per_drive": 500.0,
                    "captured_at_unix": 100.0,
                    "instrument": "endogenous_activity_change",
                }
            ],
        }
    )

    assert model.model_stats()["instrument_sample_count"] == 0


def test_pre_capture_timestamp_model_evidence_is_invalidated():
    model = LearnedLedLuxResidual(
        {
            "model_kind": "stable_command_breathing_delta_median",
            "transitions": [
                {
                    "before_drive": 0.02,
                    "after_drive": 0.06,
                    "delta_lux": 20.0,
                    "slope_lux_per_drive": 500.0,
                    "captured_at_unix": 100.0,
                    "instrument": LearnedLedLuxResidual.INSTRUMENT,
                }
            ],
        }
    )

    assert model.model_stats()["instrument_sample_count"] == 0


def test_kindless_legacy_evidence_is_invalidated():
    model = LearnedLedLuxResidual(
        {
            "transitions": [
                {
                    "before_drive": 0.02,
                    "after_drive": 0.06,
                    "delta_lux": 20.0,
                    "slope_lux_per_drive": 500.0,
                    "captured_at_unix": 100.0,
                    "instrument": LearnedLedLuxResidual.INSTRUMENT,
                }
            ]
        }
    )

    assert model.model_stats()["instrument_sample_count"] == 0


def _persisted_sign_sequence(signs):
    transitions = []
    for i, positive in enumerate(signs):
        before, after = ((0.02, 0.06) if i % 2 == 0 else (0.06, 0.02))
        delta_drive = after - before
        slope = 500.0 if positive else -500.0
        transitions.append(
            {
                "before_drive": before,
                "after_drive": after,
                "delta_lux": slope * delta_drive,
                "slope_lux_per_drive": slope,
                "captured_at_unix": 100.0 + i,
                "instrument": LearnedLedLuxResidual.INSTRUMENT,
            }
        )
    return {
        "model_kind": LearnedLedLuxResidual.MODEL_KIND,
        "transitions": transitions,
    }


def test_sign_readiness_uses_confidence_bound_and_hysteresis():
    # 26/37 clears the raw 70% point threshold, but the 95% Wilson lower
    # bound is only ~0.542 and must not activate the gated residual.
    borderline = [True, True, False] * 8 + [False, False, False] + [True] * 10
    model = LearnedLedLuxResidual(_persisted_sign_sequence(borderline))

    stats = model.model_stats()
    assert stats["positive_fraction"] == pytest.approx(26 / 37)
    assert stats["positive_wilson_lower_bound"] == pytest.approx(0.542169, abs=1e-6)
    assert stats["sign_consistency_ready"] is False
    assert stats["ready"] is False

    # Four more positive samples establish the confidence bound. One adjacent
    # negative sample no longer chatters readiness back off.
    established = borderline + [True] * 4 + [False]
    model = LearnedLedLuxResidual(_persisted_sign_sequence(established))

    stats = model.model_stats()
    assert stats["positive_fraction"] == pytest.approx(30 / 42)
    assert stats["positive_wilson_lower_bound"] == pytest.approx(0.564328, abs=1e-6)
    assert stats["sign_consistency_ready"] is True
    assert stats["ready"] is True

    model = LearnedLedLuxResidual(
        _persisted_sign_sequence(established + [False])
    )
    stats = model.model_stats()
    assert stats["positive_fraction"] < stats["positive_fraction_gate"]
    assert stats["positive_wilson_lower_bound"] > stats[
        "sign_deactivation_lower_bound_gate"
    ]
    assert stats["sign_consistency_ready"] is True
    assert stats["ready"] is True

    # Sustained contrary evidence still withdraws the residual.
    model = LearnedLedLuxResidual(
        _persisted_sign_sequence(established + [False] * 8)
    )
    stats = model.model_stats()
    assert stats["positive_wilson_lower_bound"] < stats[
        "sign_deactivation_lower_bound_gate"
    ]
    assert stats["sign_consistency_ready"] is False
    assert stats["ready"] is False


def test_endogenous_logical_brightness_changes_are_not_training_evidence():
    model = LearnedLedLuxResidual()
    for i in range(40):
        drive = 0.02 if i % 2 == 0 else 0.08
        # Lux and LED target move together, but the target itself changed. This
        # is the closed-loop correlation the causal gate must reject.
        model.observe(100.0 + 500.0 * drive, led_state(drive), observed_at=100 + i)

    assert model.model_stats()["instrument_sample_count"] == 0


def test_repeated_reads_of_one_physical_light_capture_do_not_inflate_evidence():
    model = LearnedLedLuxResidual()
    for i, channel in enumerate([64, 96, 144, 192, 144, 96, 64]):
        state = breathing_state(channel)
        model.observe(
            100.0 + i,
            state,
            observed_at=100.0 + i,
            observation_id=f"capture-{i}",
        )

    repeated_state = breathing_state(96)
    model.observe(
        108.0,
        repeated_state,
        observed_at=108.0,
        observation_id="same-capture",
    )
    before = model.model_stats()["instrument_sample_count"]
    for i in range(10):
        model.observe(
            108.0,
            repeated_state,
            observed_at=109.0 + i,
            observation_id="same-capture",
        )

    assert model.model_stats()["instrument_sample_count"] == before


def test_breathing_instrument_survives_slow_ambient_drift_and_sensor_noise():
    model = LearnedLedLuxResidual()
    pulse = [64, 96, 144, 192, 144, 96]
    noise = [0.04, -0.03, 0.02, -0.01, 0.03, -0.04]
    final_state = breathing_state(pulse[0])
    filtered_drive = None
    for i in range(49):
        final_state = breathing_state(pulse[i % len(pulse)])
        drive = led_optical_drive(final_state)
        assert drive is not None
        filtered_drive = (
            drive
            if filtered_drive is None
            else 0.8 * filtered_drive + 0.2 * drive
        )
        ambient = 100.0 + i * 0.01
        raw_lux = ambient + 500.0 * filtered_drive + noise[i % len(noise)]
        model.observe(raw_lux, final_state, observed_at=100.0 + 2.0 * i)

    stats = model.model_stats()
    assert stats["ready"] is True
    assert stats["slope_lux_per_drive"] == pytest.approx(500.0, rel=0.08)


def test_estimated_brightness_without_colors_cannot_train_or_claim_residual():
    model = LearnedLedLuxResidual()
    fallback = {"brightness": 0.08, "source": "broker_brightness_estimate"}
    for i in range(20):
        model.observe(100.0 + i, fallback, observed_at=100.0 + i)

    result = model.attribute(120.0, fallback)
    assert result["status"] == "unavailable"
    assert result["model"]["transition_count"] == 0
    assert result["external_lux_residual"] is None


def test_transition_model_persists_inside_self_model(tmp_path):
    path = tmp_path / "self_model.json"
    writer = SelfModel(persistence_path=path)
    train_clean_bidirectional_model(writer._light_attribution_model)
    assert writer.save()

    reader = SelfModel(persistence_path=path, read_only=True)
    stats = reader._light_attribution_model.model_stats()
    assert stats["instrument_sample_count"] == 24
    assert stats["ready"] is True


def test_led_display_proprioception_includes_post_scaling_colors():
    from anima_mcp.display.leds.display import LEDDisplay
    from anima_mcp.display.leds.types import LEDState

    display = LEDDisplay.__new__(LEDDisplay)
    display._last_applied_brightness = 0.04
    display._cached_pipeline_brightness = 0.04
    display._expression_mode = "balanced"
    display._current_dance = None
    display._manual_brightness_factor = 1.0
    display._flash_until = 0.0
    display._last_state = LEDState(
        led0=(255, 0, 0),
        led1=(0, 255, 0),
        led2=(0, 0, 255),
        brightness=0.04,
    )
    display._last_applied_colors = [(64, 0, 0), (0, 64, 0), (0, 0, 64)]

    state = display.get_proprioceptive_state()
    assert state["colors"] == [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
    assert state["applied_colors"] == display._last_applied_colors
    assert state["target_brightness"] == 0.04
    assert led_optical_drive(state) == pytest.approx(0.04 * 64 / (3 * 255))


def test_operator_surfaces_name_gated_efference_semantics():
    from anima_mcp.tool_registry import TOOLS

    context_tool = next(tool for tool in TOOLS if tool.name == "get_lumen_context")
    include_values = context_tool.inputSchema["properties"]["include"]["items"]["enum"]
    assert "light_attribution" in include_values

    dashboard = (Path(__file__).parents[1] / "docs" / "control_center.html").read_text(
        encoding="utf-8"
    )
    assert "LED efference copy" in dashboard
    assert "clarity uses gated residual" in dashboard
    assert "clarity light contribution paused" in dashboard
