"""Tests that computational wiring and learned hypotheses stay distinct."""

from unittest.mock import MagicMock
from anima_mcp.self_schema import (
    extract_self_schema,
    BELIEF_SENSOR_ANIMA_HYPOTHESES,
    BELIEF_SENSOR_RELATIONS,
    BELIEF_SENSOR_SENSITIVITY_RELATIONS,
)


READY_EXTERNAL_LIGHT = {
    "status": "ready_shadow",
    "external_lux_residual": 125.0,
}


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
    def test_anima_hypotheses_have_expected_keys(self):
        assert "temp_clarity_correlation" in BELIEF_SENSOR_ANIMA_HYPOTHESES
        assert "light_warmth_correlation" in BELIEF_SENSOR_ANIMA_HYPOTHESES
        assert "my_leds_affect_lux" in BELIEF_SENSOR_RELATIONS

    def test_sensitivity_relations_have_expected_keys(self):
        assert "temp_sensitive" in BELIEF_SENSOR_SENSITIVITY_RELATIONS
        assert "light_sensitive" in BELIEF_SENSOR_SENSITIVITY_RELATIONS

    def test_non_correlation_beliefs_not_in_maps(self):
        excluded = [
            "stability_recovery", "warmth_recovery", "interaction_clarity_boost",
            "evening_warmth_increase", "morning_clarity", "question_asking_tendency",
        ]
        for key in excluded:
            assert key not in BELIEF_SENSOR_ANIMA_HYPOTHESES
            assert key not in BELIEF_SENSOR_SENSITIVITY_RELATIONS


class TestCorrelationBeliefSemantics:
    def test_temp_clarity_is_hypothesis_not_computational_edge(self):
        model = _make_self_model(temp_clarity_correlation={
            "confidence": 0.8, "value": 0.9, "strength": "confident", "evidence": "15+ / 2-",
        })
        schema = extract_self_schema(self_model=model)
        assert not any(
            e.source_id == "sensor_temp"
            and e.target_id == "anima_clarity"
            and e.relation == "computational_influence"
            for e in schema.edges
        )
        assert any(
            e.source_id == "belief_temp_clarity_correlation"
            and e.target_id == "anima_clarity"
            and e.relation == "belief_about"
            for e in schema.edges
        )

    def test_light_warmth_negative_is_typed_hypothesis(self):
        model = _make_self_model(light_warmth_correlation={
            "confidence": 0.8, "value": 0.1, "strength": "confident", "evidence": "15+ / 2-",
        })
        schema = extract_self_schema(
            self_model=model,
            light_attribution=READY_EXTERNAL_LIGHT,
        )
        assert not any(
            e.source_id == "sensor_external_light"
            and e.target_id == "anima_warmth"
            and e.relation == "computational_influence"
            for e in schema.edges
        )
        edges = [
            e for e in schema.edges
            if e.source_id == "belief_light_warmth_correlation"
            and e.target_id == "anima_warmth"
            and e.relation == "belief_about"
        ]
        assert len(edges) == 1
        assert edges[0].weight < 0

    def test_my_leds_is_semantic_relation_not_raw_lux_influence(self):
        """LED→lux evidence must not become raw-lux→presence wiring."""
        model = _make_self_model(my_leds_affect_lux={
            "confidence": 0.9, "value": 0.8, "strength": "confident", "evidence": "100+ / 3-",
        })
        schema = extract_self_schema(self_model=model)
        assert not any(
            e.source_id == "sensor_light" and e.target_id == "anima_presence"
            for e in schema.edges
        )
        assert any(
            e.source_id == "sensor_light"
            and e.target_id == "belief_my_leds_affect_lux"
            and e.relation == "evidence_source"
            for e in schema.edges
        )
        assert not any(
            e.target_id == "anima_presence"
            and e.source_id in {"sensor_light", "belief_my_leds_affect_lux"}
            for e in schema.edges
        )


class TestSensitivityBeliefSemantics:
    def test_temp_sensitive_does_not_rewrite_computational_edge(self):
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
        assert w_high == w_neutral

    def test_raw_light_sensitivity_does_not_modulate_external_light_edge(self):
        """Raw-sensor surprise and external-light effects are distinct wires."""
        model_low = _make_self_model(
            light_sensitive={"confidence": 0.8, "value": 0.2, "strength": "confident", "evidence": "20+ / 3-"},
            light_warmth_correlation={"confidence": 0.8, "value": 0.8, "strength": "confident", "evidence": "15+ / 2-"},
        )
        model_neutral = _make_self_model(
            light_sensitive={"confidence": 0.8, "value": 0.5, "strength": "confident", "evidence": "20+ / 3-"},
            light_warmth_correlation={"confidence": 0.8, "value": 0.8, "strength": "confident", "evidence": "15+ / 2-"},
        )
        schema_low = extract_self_schema(
            self_model=model_low,
            light_attribution=READY_EXTERNAL_LIGHT,
        )
        schema_neutral = extract_self_schema(
            self_model=model_neutral,
            light_attribution=READY_EXTERNAL_LIGHT,
        )

        def _get_light_warmth_weight(schema):
            edges = [e for e in schema.edges
                     if e.source_id == "sensor_external_light" and e.target_id == "anima_warmth"]
            return edges[0].weight if edges else 0.0

        w_low = _get_light_warmth_weight(schema_low)
        w_neutral = _get_light_warmth_weight(schema_neutral)
        assert w_low == w_neutral


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
        assert edges[0].relation == "belief_about"
