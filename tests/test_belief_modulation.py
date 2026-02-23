"""Tests for generalized belief-based sensor-to-anima edge modulation."""

import pytest
from unittest.mock import MagicMock
from anima_mcp.self_schema import (
    extract_self_schema,
    BELIEF_EDGE_MODULATIONS,
    BELIEF_SENSITIVITY_MODULATIONS,
)


def _make_self_model(**belief_overrides):
    """Create a mock SelfModel with specified belief values.

    Each belief gets high enough confidence and evidence to pass the
    inclusion filter (confidence >= 0.3, total_evidence >= 1).
    """
    defaults = {
        "light_sensitive": {"confidence": 0.8, "value": 0.5, "strength": "confident", "evidence": "20+ / 5-"},
        "temp_sensitive": {"confidence": 0.8, "value": 0.5, "strength": "confident", "evidence": "20+ / 3-"},
        "stability_recovery": {"confidence": 0.7, "value": 0.8, "strength": "confident", "evidence": "10+ / 2-"},
        "warmth_recovery": {"confidence": 0.6, "value": 0.5, "strength": "moderate", "evidence": "8+ / 4-"},
        "temp_clarity_correlation": {"confidence": 0.5, "value": 0.5, "strength": "moderate", "evidence": "15+ / 10-"},
        "light_warmth_correlation": {"confidence": 0.5, "value": 0.5, "strength": "moderate", "evidence": "12+ / 8-"},
        "interaction_clarity_boost": {"confidence": 0.5, "value": 0.7, "strength": "moderate", "evidence": "5+ / 2-"},
        "evening_warmth_increase": {"confidence": 0.5, "value": 0.7, "strength": "moderate", "evidence": "5+ / 2-"},
        "morning_clarity": {"confidence": 0.9, "value": 0.85, "strength": "confident", "evidence": "30+ / 2-"},
        "question_asking_tendency": {"confidence": 0.5, "value": 0.7, "strength": "moderate", "evidence": "5+ / 3-"},
        "my_leds_affect_lux": {"confidence": 0.5, "value": 0.5, "strength": "moderate", "evidence": "16+ / 0-"},
    }
    defaults.update(belief_overrides)
    mock = MagicMock()
    mock.get_belief_summary.return_value = defaults
    return mock


class TestDeclarativeMapsExist:
    def test_edge_modulations_has_expected_keys(self):
        assert "temp_clarity_correlation" in BELIEF_EDGE_MODULATIONS
        assert "light_warmth_correlation" in BELIEF_EDGE_MODULATIONS
        assert "my_leds_affect_lux" in BELIEF_EDGE_MODULATIONS

    def test_sensitivity_modulations_has_expected_keys(self):
        assert "temp_sensitive" in BELIEF_SENSITIVITY_MODULATIONS
        assert "light_sensitive" in BELIEF_SENSITIVITY_MODULATIONS

    def test_non_correlation_beliefs_not_in_maps(self):
        excluded = [
            "stability_recovery", "warmth_recovery", "interaction_clarity_boost",
            "evening_warmth_increase", "morning_clarity", "question_asking_tendency",
        ]
        for key in excluded:
            assert key not in BELIEF_EDGE_MODULATIONS
            assert key not in BELIEF_SENSITIVITY_MODULATIONS


class TestCorrelationBeliefModulation:
    def test_temp_clarity_positive_creates_positive_edge(self):
        """temp_clarity_correlation value > 0.5 creates positive sensor_temp->anima_clarity."""
        model = _make_self_model(temp_clarity_correlation={
            "confidence": 0.8, "value": 0.9, "strength": "confident", "evidence": "15+ / 2-",
        })
        schema = extract_self_schema(self_model=model)
        edges = [e for e in schema.edges
                 if e.source_id == "sensor_temp" and e.target_id == "anima_clarity"]
        assert len(edges) == 1
        assert edges[0].weight > 0

    def test_light_warmth_negative_creates_negative_edge(self):
        """light_warmth_correlation value < 0.5 creates negative sensor_light->anima_warmth."""
        model = _make_self_model(light_warmth_correlation={
            "confidence": 0.8, "value": 0.1, "strength": "confident", "evidence": "15+ / 2-",
        })
        schema = extract_self_schema(self_model=model)
        edges = [e for e in schema.edges
                 if e.source_id == "sensor_light" and e.target_id == "anima_warmth"]
        assert len(edges) == 1
        assert edges[0].weight < 0

    def test_my_leds_modulates_light_to_presence(self):
        """my_leds_affect_lux modulates sensor_light->anima_presence edge."""
        model = _make_self_model(my_leds_affect_lux={
            "confidence": 0.9, "value": 0.8, "strength": "confident", "evidence": "100+ / 3-",
        })
        schema = extract_self_schema(self_model=model)
        edges = [e for e in schema.edges
                 if e.source_id == "sensor_light" and e.target_id == "anima_presence"]
        assert len(edges) == 1
        # value 0.8 -> learned = (0.8-0.5)*2 = 0.6, weight = 0.6 * 0.4 = 0.24
        assert abs(edges[0].weight - 0.24) < 0.05


class TestSensitivityBeliefModulation:
    def test_temp_sensitive_high_amplifies_temp_edges(self):
        """High temp_sensitive (>0.5) amplifies sensor_temp->anima_warmth edge."""
        model_high = _make_self_model(temp_sensitive={
            "confidence": 0.8, "value": 0.9, "strength": "confident", "evidence": "20+ / 3-",
        })
        model_neutral = _make_self_model(temp_sensitive={
            "confidence": 0.8, "value": 0.5, "strength": "confident", "evidence": "20+ / 3-",
        })
        schema_high = extract_self_schema(self_model=model_high)
        schema_neutral = extract_self_schema(self_model=model_neutral)

        def _get_temp_warmth_weight(schema):
            edges = [e for e in schema.edges
                     if e.source_id == "sensor_temp" and e.target_id == "anima_warmth"]
            return edges[0].weight if edges else 0.0

        w_high = _get_temp_warmth_weight(schema_high)
        w_neutral = _get_temp_warmth_weight(schema_neutral)
        # High sensitivity (0.9) -> multiplier 1.4, neutral (0.5) -> 1.0
        assert abs(w_high) > abs(w_neutral)

    def test_light_sensitive_low_dampens_light_edges(self):
        """Low light_sensitive (<0.5) dampens sensor_light->anima_warmth edge.

        We set light_warmth_correlation to a non-neutral value to ensure a light
        edge exists, then verify sensitivity dampens its magnitude.
        """
        # Both have the same light_warmth_correlation, only sensitivity differs
        model_low = _make_self_model(
            light_sensitive={"confidence": 0.8, "value": 0.2, "strength": "confident", "evidence": "20+ / 3-"},
            light_warmth_correlation={"confidence": 0.8, "value": 0.8, "strength": "confident", "evidence": "15+ / 2-"},
        )
        model_neutral = _make_self_model(
            light_sensitive={"confidence": 0.8, "value": 0.5, "strength": "confident", "evidence": "20+ / 3-"},
            light_warmth_correlation={"confidence": 0.8, "value": 0.8, "strength": "confident", "evidence": "15+ / 2-"},
        )
        schema_low = extract_self_schema(self_model=model_low)
        schema_neutral = extract_self_schema(self_model=model_neutral)

        def _get_light_warmth_weight(schema):
            edges = [e for e in schema.edges
                     if e.source_id == "sensor_light" and e.target_id == "anima_warmth"]
            return edges[0].weight if edges else 0.0

        w_low = _get_light_warmth_weight(schema_low)
        w_neutral = _get_light_warmth_weight(schema_neutral)
        # Low sensitivity (0.2) -> multiplier 0.7, neutral (0.5) -> 1.0
        assert abs(w_low) < abs(w_neutral)


class TestNonCorrelationBeliefsUnchanged:
    def test_stability_recovery_still_has_belief_edge(self):
        """stability_recovery belief creates belief_stability_recovery->anima_stability edge."""
        model = _make_self_model(stability_recovery={
            "confidence": 0.7, "value": 0.8, "strength": "confident", "evidence": "10+ / 2-",
        })
        schema = extract_self_schema(self_model=model)
        edges = [e for e in schema.edges if e.source_id == "belief_stability_recovery"]
        assert len(edges) == 1
        assert edges[0].target_id == "anima_stability"
