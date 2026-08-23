"""Learned, raw-preserving attribution of VEML7700 lux to Lumen's LEDs.

The light sensor measures one physical quantity: room light plus DotStar glow.
This module never rewrites that measurement.  It carries the actual LED action
from the hardware-owning server to the sensor-owning broker, then learns a
robust response from the internal breathing pulse while the logical LED command
is fixed.  Until the evidence gate passes, the external-light residual is
explicitly unknown.

The ready residual is a gated secondary signal for environmental consumers.
It never rewrites the physical reading. Until ready, clarity omits its light
component and preferences pause rather than treating self-glow as room light.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
from statistics import median
import threading
import time
from typing import Any

from .atomic_write import atomic_json_write
from .config import LIGHT_SENSOR_EMA_ALPHA

LED_PROPRIOCEPTION_SCHEMA = "anima.led_proprioception.v1"
LIGHT_ATTRIBUTION_SCHEMA = "anima.light_attribution.v1"
LED_PROPRIOCEPTION_ENV = "ANIMA_LED_PROPRIOCEPTION_PATH"
DEFAULT_LED_PROPRIOCEPTION_PATH = Path("/dev/shm/anima_led_proprioception.json")
_LED_ACTION_HISTORIES: dict[str, deque[dict[str, Any]]] = {}
_LED_ACTION_HISTORY_LOCK = threading.Lock()
_LED_ACTION_HISTORY_LENGTH = 24


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def gated_external_light_lux(attribution: Any) -> float | None:
    """Return the secondary external-light signal only after its evidence gate.

    All consumers share this one admission rule so a UI, preference, or belief
    cannot accidentally promote the residual earlier than another subsystem.
    Raw lux remains available through its original sensor channel regardless.
    """
    if not isinstance(attribution, dict):
        return None
    if attribution.get("status") != "ready_shadow":
        return None
    return _finite_float(attribution.get("external_lux_residual"))


def _bounded_float(value: Any, lower: float, upper: float) -> float | None:
    result = _finite_float(value)
    if result is None or result < lower or result > upper:
        return None
    return result


def _normalize_colors(value: Any) -> list[list[int]] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    colors: list[list[int]] = []
    for color in value:
        if not isinstance(color, (list, tuple)) or len(color) != 3:
            return None
        normalized: list[int] = []
        for channel in color:
            if isinstance(channel, bool) or not isinstance(channel, (int, float)):
                return None
            channel_float = float(channel)
            if not math.isfinite(channel_float) or not 0.0 <= channel_float <= 255.0:
                return None
            normalized.append(int(round(channel_float)))
        colors.append(normalized)
    return colors


def led_proprioception_path() -> Path:
    """Return the runtime action-copy path, honoring the test/deploy override."""
    configured = os.environ.get(LED_PROPRIOCEPTION_ENV)
    return (
        Path(configured).expanduser() if configured else DEFAULT_LED_PROPRIOCEPTION_PATH
    )


def led_optical_drive(state: dict[str, Any] | None) -> float | None:
    """Reduce applied brightness and RGB energy to a measured action feature.

    This is not a lux model.  It is a dimensionless description of the emitted
    command in [0, 1], leaving the lux-per-drive response to be learned from
    transitions.  Including RGB energy avoids treating black and white at the
    same DotStar brightness as the same optical action.
    """
    if not isinstance(state, dict):
        return None
    brightness = _bounded_float(state.get("brightness"), 0.0, 1.0)
    colors = _normalize_colors(state.get("applied_colors"))
    if colors is None:
        colors = _normalize_colors(state.get("colors"))
    if brightness is None or colors is None:
        return None
    rgb_energy = sum(channel for color in colors for channel in color) / (9.0 * 255.0)
    return brightness * rgb_energy


def publish_led_proprioception(
    state: dict[str, Any],
    *,
    path: str | Path | None = None,
    captured_at: float | None = None,
) -> dict[str, Any]:
    """Atomically publish the DotStar action that was actually applied."""
    brightness = _bounded_float(state.get("brightness"), 0.0, 1.0)
    colors = _normalize_colors(state.get("colors"))
    if brightness is None or colors is None:
        raise ValueError(
            "LED proprioception requires finite brightness and three RGB colors"
        )
    applied_colors = _normalize_colors(state.get("applied_colors"))
    target_brightness = _bounded_float(state.get("target_brightness"), 0.0, 1.0)
    if target_brightness is None:
        target_brightness = brightness

    timestamp = time.time() if captured_at is None else _finite_float(captured_at)
    if timestamp is None or timestamp < 0.0:
        raise ValueError("captured_at must be a finite Unix timestamp")

    payload: dict[str, Any] = {
        "schema": LED_PROPRIOCEPTION_SCHEMA,
        "captured_at": datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
        "captured_at_unix": timestamp,
        "source": "led_hardware_controller",
        "brightness": brightness,
        "target_brightness": target_brightness,
        "colors": colors,
        "applied_colors": applied_colors or colors,
        "expression_mode": state.get("expression_mode"),
        "is_dancing": bool(state.get("is_dancing", False)),
        "is_flashing": bool(state.get("is_flashing", False)),
        "dance_type": state.get("dance_type"),
        "manual_dimmed": bool(state.get("manual_dimmed", False)),
    }
    payload["optical_drive"] = led_optical_drive(payload)
    target_path = Path(path) if path is not None else led_proprioception_path()
    history_key = str(target_path)
    with _LED_ACTION_HISTORY_LOCK:
        history = _LED_ACTION_HISTORIES.setdefault(
            history_key, deque(maxlen=_LED_ACTION_HISTORY_LENGTH)
        )
        history.append(dict(payload))
        payload["history"] = [dict(item) for item in history]
    atomic_json_write(target_path, payload)
    return payload


def _normalize_published_action(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict) or data.get("schema") != LED_PROPRIOCEPTION_SCHEMA:
        return None
    brightness = _bounded_float(data.get("brightness"), 0.0, 1.0)
    target_brightness = _bounded_float(data.get("target_brightness"), 0.0, 1.0)
    if target_brightness is None:
        target_brightness = brightness
    colors = _normalize_colors(data.get("colors"))
    applied_colors = _normalize_colors(data.get("applied_colors"))
    if applied_colors is None:
        applied_colors = colors
    captured = _finite_float(data.get("captured_at_unix"))
    if (
        brightness is None
        or target_brightness is None
        or colors is None
        or applied_colors is None
        or captured is None
    ):
        return None
    result = dict(data)
    result.pop("history", None)
    result["brightness"] = brightness
    result["target_brightness"] = target_brightness
    result["colors"] = colors
    result["applied_colors"] = applied_colors
    result["captured_at_unix"] = captured
    result["optical_drive"] = led_optical_drive(result)
    return result


def read_led_proprioception(
    *,
    path: str | Path | None = None,
    max_age_seconds: float = 10.0,
    now: float | None = None,
    at_time: float | None = None,
    max_alignment_error_seconds: float = 1.25,
) -> dict[str, Any] | None:
    """Read a fresh action copy, optionally aligned to a sensor capture time."""
    target = Path(path) if path is not None else led_proprioception_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    envelope = _normalize_published_action(data)
    current = time.time() if now is None else _finite_float(now)
    if envelope is None or current is None:
        return None
    envelope_age = current - envelope["captured_at_unix"]
    if envelope_age < -2.0 or envelope_age > max(0.0, float(max_age_seconds)):
        return None

    result = envelope
    alignment_error = None
    target_time = _finite_float(at_time) if at_time is not None else None
    if at_time is not None and target_time is None:
        return None
    if target_time is not None:
        candidates = [
            normalized
            for item in data.get("history", [])
            if (normalized := _normalize_published_action(item)) is not None
        ]
        if envelope not in candidates:
            candidates.append(envelope)
        if not candidates:
            return None
        result = min(
            candidates,
            key=lambda item: abs(item["captured_at_unix"] - target_time),
        )
        alignment_error = abs(result["captured_at_unix"] - target_time)
        if alignment_error > max(0.0, float(max_alignment_error_seconds)):
            return None

    result = dict(result)
    result["age_seconds"] = max(0.0, current - result["captured_at_unix"])
    result["envelope_age_seconds"] = max(0.0, envelope_age)
    result["alignment_error_seconds"] = alignment_error
    result["paired_to_light_observed_at_unix"] = target_time
    result["fresh"] = True
    return result


class LearnedLedLuxResidual:
    """Learn LED response from breathing while the logical command is fixed.

    Natural LED changes are not a safe causal instrument: raw lux helps choose
    activity state, which changes LED brightness, so a room-light step can move
    both channels in the same direction.  Lumen's gentle breathing pulse is
    different.  It varies the applied optical drive internally while logical
    color and target brightness remain fixed.  Short paired differences then
    cancel a locally constant room-light intercept without learning the
    closed-loop correlation as self-glow.
    """

    # v1 paired actions to the independent SHM flush timestamp, which can lag
    # the VEML7700 read by almost one 2s cycle. A distinct kind intentionally
    # rejects that contaminated durable evidence after capture timing is fixed.
    MODEL_KIND = "capture_timed_stable_command_breathing_delta_median_v2"
    INSTRUMENT = "internal_led_breathing_pulse"
    MAX_TRANSITIONS = 96
    MAX_SAMPLE_INTERVAL_SECONDS = 8.0
    TARGET_BRIGHTNESS_TOLERANCE = 0.0005
    MIN_DRIVE_DELTA = 0.00075
    MIN_READY_TRANSITIONS = 24
    MIN_READY_PER_DIRECTION = 6
    MIN_READY_DRIVE_SPAN = 0.0025
    MIN_POSITIVE_FRACTION = 0.70
    SIGN_WILSON_Z = 1.959963984540054
    SIGN_ACTIVATE_LOWER_BOUND = 0.55
    SIGN_DEACTIVATE_LOWER_BOUND = 0.50
    CONFIDENCE_GATE = 0.75
    DRIVE_FILTER_WARM_SAMPLES = 5

    def __init__(self, persisted: dict[str, Any] | None = None):
        self._transitions: deque[dict[str, float | str]] = deque(
            maxlen=self.MAX_TRANSITIONS
        )
        self._previous_sample: dict[str, Any] | None = None
        self._filtered_drive: float | None = None
        self._drive_filter_samples = 0
        self._sign_consistency_ready = False
        if persisted:
            self.load_dict(persisted)

    def load_dict(self, data: dict[str, Any] | None) -> None:
        """Replace durable transition evidence with validated persisted data."""
        self._transitions.clear()
        self._sign_consistency_ready = False
        if not isinstance(data, dict):
            return
        persisted_kind = data.get("model_kind")
        # Kindless evidence predates capture-provenance versioning, so it
        # cannot prove that it used the sensor-owned timing path either.
        if persisted_kind != self.MODEL_KIND:
            return
        transitions = data.get("transitions")
        if not isinstance(transitions, list):
            return
        for item in transitions[-self.MAX_TRANSITIONS :]:
            if not isinstance(item, dict):
                continue
            before = _bounded_float(item.get("before_drive"), 0.0, 1.0)
            after = _bounded_float(item.get("after_drive"), 0.0, 1.0)
            delta_lux = _finite_float(item.get("delta_lux"))
            slope = _finite_float(item.get("slope_lux_per_drive"))
            captured = _finite_float(item.get("captured_at_unix"))
            alignment_error = _bounded_float(
                item.get("alignment_error_seconds", 0.0), 0.0, 2.0
            )
            instrument = item.get("instrument", self.INSTRUMENT)
            if (
                None in (before, after, delta_lux, slope, captured, alignment_error)
                or instrument != self.INSTRUMENT
            ):
                continue
            delta_drive = after - before
            if abs(delta_drive) < self.MIN_DRIVE_DELTA:
                continue
            self._transitions.append(
                {
                    "before_drive": before,
                    "after_drive": after,
                    "delta_drive": delta_drive,
                    "delta_lux": delta_lux,
                    "slope_lux_per_drive": slope,
                    "direction": "up" if delta_drive > 0 else "down",
                    "instrument": self.INSTRUMENT,
                    "captured_at_unix": captured,
                    "alignment_error_seconds": alignment_error,
                }
            )
            self._update_sign_consistency_gate()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": LIGHT_ATTRIBUTION_SCHEMA,
            "model_kind": self.MODEL_KIND,
            "drive_filter_alpha": LIGHT_SENSOR_EMA_ALPHA,
            "transitions": [dict(item) for item in self._transitions],
        }

    @staticmethod
    def _logical_colors(state: dict[str, Any]) -> tuple[int, ...] | None:
        colors = _normalize_colors(state.get("colors"))
        if colors is None:
            return None
        return tuple(channel for color in colors for channel in color)

    def _sample(
        self,
        raw_lux: float,
        drive: float,
        led_state: dict[str, Any],
        observed_at: float,
        observation_id: str,
    ) -> dict[str, Any] | None:
        colors = self._logical_colors(led_state)
        target = _bounded_float(led_state.get("target_brightness"), 0.0, 1.0)
        if target is None:
            target = _bounded_float(led_state.get("brightness"), 0.0, 1.0)
        if colors is None or target is None:
            return None
        return {
            "lux": raw_lux,
            "drive": drive,
            "observed_at": observed_at,
            "observation_id": observation_id,
            "logical_colors": colors,
            "target_brightness": target,
            "is_dancing": bool(led_state.get("is_dancing", False)),
            "is_flashing": bool(led_state.get("is_flashing", False)),
            "alignment_error_seconds": _finite_float(
                led_state.get("alignment_error_seconds")
            ),
        }

    def _same_logical_command(
        self, before: dict[str, Any], after: dict[str, Any]
    ) -> bool:
        return (
            not before["is_dancing"]
            and not after["is_dancing"]
            and not before["is_flashing"]
            and not after["is_flashing"]
            and before["logical_colors"] == after["logical_colors"]
            and abs(before["target_brightness"] - after["target_brightness"])
            <= self.TARGET_BRIGHTNESS_TOLERANCE
        )

    @classmethod
    def _positive_wilson_lower_bound(cls, positive: int, total: int) -> float | None:
        """95% Wilson lower bound for the probability of a positive slope."""
        if total <= 0:
            return None
        fraction = positive / total
        z_squared = cls.SIGN_WILSON_Z**2
        denominator = 1.0 + z_squared / total
        center = fraction + z_squared / (2.0 * total)
        margin = cls.SIGN_WILSON_Z * math.sqrt(
            (fraction * (1.0 - fraction) + z_squared / (4.0 * total)) / total
        )
        return max(0.0, min(1.0, (center - margin) / denominator))

    def _update_sign_consistency_gate(self) -> None:
        """Latch strong sign evidence; withdraw only when significance is lost."""
        count = len(self._transitions)
        positive = sum(
            float(item["slope_lux_per_drive"]) > 0.0
            for item in self._transitions
        )
        fraction = positive / count if count else None
        lower_bound = self._positive_wilson_lower_bound(positive, count)
        if fraction is None or lower_bound is None:
            self._sign_consistency_ready = False
        elif not self._sign_consistency_ready:
            self._sign_consistency_ready = (
                count >= self.MIN_READY_TRANSITIONS
                and fraction >= self.MIN_POSITIVE_FRACTION
                and lower_bound >= self.SIGN_ACTIVATE_LOWER_BOUND
            )
        elif lower_bound < self.SIGN_DEACTIVATE_LOWER_BOUND:
            self._sign_consistency_ready = False

    def _observe_instrument(
        self,
        raw_lux: float,
        drive: float,
        led_state: dict[str, Any],
        observed_at: float,
        observation_id: str,
    ) -> None:
        sample = self._sample(
            raw_lux, drive, led_state, observed_at, observation_id
        )
        if sample is None:
            self._previous_sample = None
            return

        before = self._previous_sample
        self._previous_sample = sample
        if (
            before is None
            or before["observation_id"] == sample["observation_id"]
            or not self._same_logical_command(before, sample)
        ):
            return

        elapsed = observed_at - before["observed_at"]
        delta_drive = drive - before["drive"]
        if (
            elapsed <= 0.0
            or elapsed > self.MAX_SAMPLE_INTERVAL_SECONDS
            or abs(delta_drive) < self.MIN_DRIVE_DELTA
        ):
            return

        delta_lux = raw_lux - before["lux"]
        slope = delta_lux / delta_drive
        if not math.isfinite(slope):
            return
        self._transitions.append(
            {
                "before_drive": before["drive"],
                "after_drive": drive,
                "delta_drive": delta_drive,
                "delta_lux": delta_lux,
                "slope_lux_per_drive": slope,
                "direction": "up" if delta_drive > 0 else "down",
                "instrument": self.INSTRUMENT,
                "captured_at_unix": observed_at,
                "alignment_error_seconds": max(
                    before["alignment_error_seconds"] or 0.0,
                    sample["alignment_error_seconds"] or 0.0,
                ),
            }
        )
        self._update_sign_consistency_gate()

    def model_stats(self) -> dict[str, Any]:
        transitions = list(self._transitions)
        slopes = [float(item["slope_lux_per_drive"]) for item in transitions]
        count = len(slopes)
        up_count = sum(item["direction"] == "up" for item in transitions)
        down_count = sum(item["direction"] == "down" for item in transitions)
        endpoints = [
            float(item[key])
            for item in transitions
            for key in ("before_drive", "after_drive")
        ]
        drive_span = max(endpoints) - min(endpoints) if endpoints else 0.0
        alignment_errors = [
            float(item.get("alignment_error_seconds", 0.0))
            for item in transitions
        ]

        slope = median(slopes) if slopes else None
        mad = median(abs(value - slope) for value in slopes) if slopes else None
        positive_fraction = (
            sum(value > 0.0 for value in slopes) / count if count else None
        )
        positive_count = sum(value > 0.0 for value in slopes)
        positive_wilson_lower_bound = self._positive_wilson_lower_bound(
            positive_count, count
        )

        count_score = min(1.0, count / self.MIN_READY_TRANSITIONS)
        span_score = min(1.0, drive_span / self.MIN_READY_DRIVE_SPAN)
        direction_score = min(
            1.0,
            min(up_count, down_count) / self.MIN_READY_PER_DIRECTION,
        )
        sign_score = (
            max(0.0, min(1.0, (positive_fraction - 0.5) / 0.5))
            if positive_fraction is not None
            else 0.0
        )
        consistency_score = 0.0
        if slope is not None and mad is not None and slope > 0.0:
            consistency_score = 1.0 / (1.0 + mad / max(abs(slope), 1e-9))
        confidence = (
            0.30 * count_score
            + 0.20 * span_score
            + 0.15 * direction_score
            + 0.15 * sign_score
            + 0.20 * consistency_score
        )

        unknown_reasons: list[str] = []
        if count < self.MIN_READY_TRANSITIONS:
            unknown_reasons.append(
                f"need_{self.MIN_READY_TRANSITIONS}_breathing_differences"
            )
        if up_count < self.MIN_READY_PER_DIRECTION:
            unknown_reasons.append("need_more_breathing_increases")
        if down_count < self.MIN_READY_PER_DIRECTION:
            unknown_reasons.append("need_more_breathing_decreases")
        if drive_span < self.MIN_READY_DRIVE_SPAN:
            unknown_reasons.append("need_wider_led_drive_span")
        if slope is None or slope <= 0.0:
            unknown_reasons.append("positive_self_glow_response_not_established")
        if not self._sign_consistency_ready:
            unknown_reasons.append("breathing_response_is_inconsistent")
        if confidence < self.CONFIDENCE_GATE:
            unknown_reasons.append("confidence_below_gate")

        return {
            "kind": self.MODEL_KIND,
            "instrument": self.INSTRUMENT,
            "drive_filter_alpha": LIGHT_SENSOR_EMA_ALPHA,
            "transition_count": count,
            "instrument_sample_count": count,
            "up_transitions": up_count,
            "down_transitions": down_count,
            "drive_span": drive_span,
            "median_alignment_error_seconds": (
                median(alignment_errors) if alignment_errors else None
            ),
            "max_alignment_error_seconds": (
                max(alignment_errors) if alignment_errors else None
            ),
            "slope_lux_per_drive": slope,
            "median_absolute_deviation": mad,
            "positive_fraction": positive_fraction,
            "positive_fraction_gate": self.MIN_POSITIVE_FRACTION,
            "positive_wilson_lower_bound": positive_wilson_lower_bound,
            "sign_activation_lower_bound_gate": self.SIGN_ACTIVATE_LOWER_BOUND,
            "sign_deactivation_lower_bound_gate": self.SIGN_DEACTIVATE_LOWER_BOUND,
            "sign_consistency_ready": self._sign_consistency_ready,
            "confidence": max(0.0, min(1.0, confidence)),
            "confidence_gate": self.CONFIDENCE_GATE,
            "ready": not unknown_reasons,
            "unknown_reasons": unknown_reasons,
        }

    def attribute(
        self,
        raw_lux: Any,
        led_state: dict[str, Any] | None,
        *,
        model_drive: float | None = None,
        drive_filter_ready: bool | None = None,
    ) -> dict[str, Any]:
        """Return provenance-rich gated attribution without changing raw lux."""
        raw = _finite_float(raw_lux)
        if raw is not None and raw < 0.0:
            raw = None
        brightness = (
            _bounded_float(led_state.get("brightness"), 0.0, 1.0)
            if isinstance(led_state, dict)
            else None
        )
        drive = led_optical_drive(led_state)
        action_source = led_state.get("source") if isinstance(led_state, dict) else None
        stats = self.model_stats()
        if model_drive is None and action_source == "led_hardware_controller":
            model_drive = self._filtered_drive
        if drive_filter_ready is None:
            drive_filter_ready = (
                self._drive_filter_samples >= self.DRIVE_FILTER_WARM_SAMPLES
            )

        candidate = None
        slope = stats["slope_lux_per_drive"]
        if model_drive is not None and slope is not None and slope > 0.0:
            candidate = slope * model_drive

        status = "warming"
        reasons = list(stats["unknown_reasons"])
        self_glow = None
        external = None
        if raw is None:
            status = "unavailable"
            reasons = ["raw_lux_unavailable"]
        elif drive is None or action_source != "led_hardware_controller":
            status = "unavailable"
            reasons = ["fresh_color_aware_efference_copy_unavailable"]
        elif stats["ready"] and not drive_filter_ready:
            status = "warming"
            reasons = ["led_drive_filter_warming"]
        elif stats["ready"] and candidate is not None:
            if candidate > raw:
                status = "model_conflict"
                reasons = ["candidate_self_glow_exceeds_measured_raw_lux"]
            else:
                status = "ready_shadow"
                reasons = []
                self_glow = candidate
                external = raw - candidate

        def rounded(value: Any) -> Any:
            return round(value, 6) if isinstance(value, float) else value

        model = {
            key: rounded(value)
            for key, value in stats.items()
            if key not in {"unknown_reasons", "ready"}
        }
        model["ready"] = stats["ready"]
        model["unknown_reasons"] = reasons
        model["limitations"] = [
            "ambient light is assumed stable across each <=8s breathing difference",
            "RGB output is reduced to scalar channel energy; spectral response is not independently fitted",
            "self-glow is anchored to zero at zero optical drive",
        ]

        residual_ready = status == "ready_shadow" and external is not None

        return {
            "schema": LIGHT_ATTRIBUTION_SCHEMA,
            "mode": "raw_preserving_gated",
            "authority": "gated_secondary_signal",
            "status": status,
            "raw_lux": rounded(raw),
            "raw_lux_composition": "room_light_plus_dotstar_glow",
            "raw_lux_temporal_filter": f"ema_alpha_{LIGHT_SENSOR_EMA_ALPHA}",
            "led_brightness": rounded(brightness),
            "led_optical_drive": rounded(drive),
            "filtered_led_optical_drive": rounded(model_drive),
            "led_action_source": action_source or "unknown",
            "led_action_alignment_error_seconds": (
                rounded(_finite_float(led_state.get("alignment_error_seconds")))
                if isinstance(led_state, dict)
                else None
            ),
            "candidate_self_glow_lux": rounded(candidate),
            "self_glow_estimate_lux": rounded(self_glow),
            "external_lux_residual": rounded(external),
            "estimate_confidence": rounded(stats["confidence"]),
            "used_by_clarity": residual_ready,
            "clarity_input": (
                "external_lux_residual" if residual_ready else None
            ),
            "clarity_light_policy": "omit_until_gated_residual_ready",
            "used_by_environment_preferences": residual_ready,
            "used_by_environment_consumers": residual_ready,
            "environment_preference_input": (
                "external_lux_residual"
                if residual_ready
                else None
            ),
            "model": model,
            "provenance": {
                "raw_lux": {
                    "source": "VEML7700",
                    "role": "physical_measurement",
                    "processing": f"uncorrected_combined_lux_then_ema_alpha_{LIGHT_SENSOR_EMA_ALPHA}",
                },
                "led_action": {
                    "source": action_source or "unknown",
                    "schema": (
                        led_state.get("schema") if isinstance(led_state, dict) else None
                    ),
                    "role": "efference_copy",
                    "paired_to_light_observed_at_unix": (
                        led_state.get("paired_to_light_observed_at_unix")
                        if isinstance(led_state, dict)
                        else None
                    ),
                },
                "residual": {
                    "source": self.MODEL_KIND,
                    "role": "learned_gated_estimate",
                },
            },
        }

    def observe(
        self,
        raw_lux: Any,
        led_state: dict[str, Any] | None,
        *,
        observed_at: float | None = None,
        observation_id: str | None = None,
        learn: bool = True,
    ) -> dict[str, Any]:
        """Observe one paired sensor/action sample and return current attribution."""
        raw = _finite_float(raw_lux)
        drive = led_optical_drive(led_state)
        source = led_state.get("source") if isinstance(led_state, dict) else None
        timestamp = time.time() if observed_at is None else _finite_float(observed_at)
        evidence_id = (
            str(observation_id)
            if observation_id is not None
            else (f"{timestamp:.6f}" if timestamp is not None else "unknown")
        )
        model_drive = None
        if drive is not None and source == "led_hardware_controller":
            if self._filtered_drive is None:
                self._filtered_drive = drive
            else:
                alpha = LIGHT_SENSOR_EMA_ALPHA
                self._filtered_drive = (
                    (1.0 - alpha) * self._filtered_drive + alpha * drive
                )
            self._drive_filter_samples += 1
            model_drive = self._filtered_drive
        else:
            self._filtered_drive = None
            self._drive_filter_samples = 0
            self._previous_sample = None
        filter_ready = self._drive_filter_samples >= self.DRIVE_FILTER_WARM_SAMPLES
        if (
            learn
            and raw is not None
            and raw >= 0.0
            and model_drive is not None
            and timestamp is not None
            and source == "led_hardware_controller"
            and isinstance(led_state, dict)
            and filter_ready
        ):
            self._observe_instrument(
                raw,
                model_drive,
                led_state,
                timestamp,
                evidence_id,
            )
        elif not filter_ready:
            self._previous_sample = None
        return self.attribute(
            raw_lux,
            led_state,
            model_drive=model_drive,
            drive_filter_ready=filter_ready,
        )


__all__ = [
    "DEFAULT_LED_PROPRIOCEPTION_PATH",
    "LED_PROPRIOCEPTION_SCHEMA",
    "LIGHT_ATTRIBUTION_SCHEMA",
    "LearnedLedLuxResidual",
    "led_optical_drive",
    "led_proprioception_path",
    "publish_led_proprioception",
    "read_led_proprioception",
]
