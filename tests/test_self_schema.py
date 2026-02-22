"""
Tests for self_schema module.

Validates the G_t self-schema graph: node/edge extraction, serialization,
VQA ground truth generation, and belief/preference inclusion thresholds.
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from anima_mcp.self_schema import (
    SchemaNode,
    SchemaEdge,
    SelfSchema,
    extract_self_schema,
    get_current_schema,
    _get_sensor_anima_weights,
    _belief_label,
)


class TestSchemaNode:
    """Test SchemaNode dataclass."""

    def test_to_dict_basic(self):
        """Test basic serialization."""
        node = SchemaNode(
            node_id="anima_warmth",
            node_type="anima",
            label="Warmth",
            value=0.75,
            raw_value=0.75,
        )
        d = node.to_dict()
        assert d["id"] == "anima_warmth"
        assert d["type"] == "anima"
        assert d["label"] == "Warmth"
        assert d["value"] == 0.75
        assert d["raw_value"] == 0.75

    def test_to_dict_with_complex_raw_value(self):
        """Test serialization with dict raw_value."""
        node = SchemaNode(
            node_id="pref_warmth",
            node_type="preference",
            label="PW",
            value=0.6,
            raw_value={"valence": 0.2, "optimal_range": (0.4, 0.7), "confidence": 0.8},
        )
        d = node.to_dict()
        assert d["raw_value"]["valence"] == 0.2
        assert d["raw_value"]["confidence"] == 0.8


class TestSchemaEdge:
    """Test SchemaEdge dataclass."""

    def test_to_dict(self):
        """Test edge serialization."""
        edge = SchemaEdge(source_id="sensor_light", target_id="anima_clarity", weight=0.4)
        d = edge.to_dict()
        assert d["source"] == "sensor_light"
        assert d["target"] == "anima_clarity"
        assert d["weight"] == 0.4

    def test_negative_weight(self):
        """Test edge with negative weight (inhibitory)."""
        edge = SchemaEdge(source_id="sensor_memory", target_id="anima_stability", weight=-0.3)
        d = edge.to_dict()
        assert d["weight"] == -0.3


class TestSelfSchema:
    """Test SelfSchema dataclass."""

    def test_to_dict(self):
        """Test schema serialization."""
        now = datetime.now()
        schema = SelfSchema(
            timestamp=now,
            nodes=[
                SchemaNode("identity", "identity", "Lumen", 1.0),
                SchemaNode("anima_warmth", "anima", "Warmth", 0.5),
            ],
            edges=[
                SchemaEdge("identity", "anima_warmth", 0.5),
            ],
        )
        d = schema.to_dict()
        assert d["node_count"] == 2
        assert d["edge_count"] == 1
        assert len(d["nodes"]) == 2
        assert len(d["edges"]) == 1
        assert "timestamp" in d

    def test_generate_vqa_counting_questions(self):
        """Test VQA generates counting questions."""
        schema = SelfSchema(
            timestamp=datetime.now(),
            nodes=[
                SchemaNode("identity", "identity", "Lumen", 1.0),
                SchemaNode("anima_warmth", "anima", "Warmth", 0.5),
                SchemaNode("anima_clarity", "anima", "Clarity", 0.7),
                SchemaNode("sensor_light", "sensor", "Light", 0.3),
            ],
            edges=[
                SchemaEdge("identity", "anima_warmth", 0.5),
                SchemaEdge("sensor_light", "anima_clarity", 0.4),
            ],
        )
        qa = schema.generate_vqa_ground_truth()

        # Should have counting questions
        counting_qs = [q for q in qa if q["type"] == "counting"]
        assert len(counting_qs) >= 3  # at least: identity, anima, sensor counts + total + edges

        # Check total node count question
        total_q = [q for q in counting_qs if "total nodes" in q["question"]]
        assert len(total_q) == 1
        assert total_q[0]["answer"] == "4"

        # Check edge count question
        edge_q = [q for q in counting_qs if "connections" in q["question"] or "edges" in q["question"]]
        assert len(edge_q) == 1
        assert edge_q[0]["answer"] == "2"

    def test_generate_vqa_existence_questions(self):
        """Test VQA generates existence questions for each node."""
        schema = SelfSchema(
            timestamp=datetime.now(),
            nodes=[
                SchemaNode("identity", "identity", "Lumen", 1.0),
                SchemaNode("anima_warmth", "anima", "Warmth", 0.5),
            ],
            edges=[],
        )
        qa = schema.generate_vqa_ground_truth()

        existence_qs = [q for q in qa if q["type"] == "existence"]
        assert len(existence_qs) == 2

        labels = [q["question"] for q in existence_qs]
        assert any("Lumen" in q for q in labels)
        assert any("Warmth" in q for q in labels)

    def test_generate_vqa_attribute_questions(self):
        """Test VQA generates attribute questions for anima nodes."""
        schema = SelfSchema(
            timestamp=datetime.now(),
            nodes=[
                SchemaNode("anima_warmth", "anima", "Warmth", 0.8),  # high
                SchemaNode("anima_clarity", "anima", "Clarity", 0.2),  # low
                SchemaNode("anima_stability", "anima", "Stability", 0.5),  # medium
            ],
            edges=[],
        )
        qa = schema.generate_vqa_ground_truth()

        attr_qs = [q for q in qa if q["type"] == "attribute"]
        assert len(attr_qs) == 3

        # Check high warmth
        warmth_q = [q for q in attr_qs if "Warmth" in q["question"]]
        assert len(warmth_q) == 1
        assert "high" in warmth_q[0]["question"]

        # Check low clarity
        clarity_q = [q for q in attr_qs if "Clarity" in q["question"]]
        assert len(clarity_q) == 1
        assert "low" in clarity_q[0]["question"]


class TestBeliefLabel:
    """Test _belief_label helper."""

    def test_known_belief_labels(self):
        """Test known belief IDs return correct labels."""
        assert _belief_label("light_sensitive") == "BLit"
        assert _belief_label("temp_sensitive") == "BTmp"
        assert _belief_label("stability_recovery") == "BRec"
        assert _belief_label("my_leds_affect_lux") == "BLED"
        assert _belief_label("question_asking_tendency") == "BQst"

    def test_unknown_belief_fallback(self):
        """Test unknown belief IDs use fallback format."""
        label = _belief_label("some_unknown_belief")
        assert label.startswith("B")
        assert len(label) == 4  # "B" + first 3 chars


class TestExtractSelfSchema:
    """Test extract_self_schema function."""

    def test_minimal_extraction(self):
        """Test extraction with no inputs returns base graph."""
        schema = extract_self_schema()

        # Should have 12 base nodes: 1 identity + 4 anima + 4 sensors + 3 resources
        assert len(schema.nodes) == 12

        # Check node types
        node_types = [n.node_type for n in schema.nodes]
        assert node_types.count("identity") == 1
        assert node_types.count("anima") == 4
        assert node_types.count("sensor") == 4
        assert node_types.count("resource") == 3

        # Should have edges from identity to each anima
        identity_edges = [e for e in schema.edges if e.source_id == "identity"]
        assert len(identity_edges) == 4

    def test_extraction_with_identity(self):
        """Test identity name is used when provided."""
        mock_identity = MagicMock()
        mock_identity.name = "TestCreature"

        schema = extract_self_schema(identity=mock_identity)

        identity_node = [n for n in schema.nodes if n.node_type == "identity"][0]
        assert identity_node.label == "TestCreature"

    def test_extraction_with_anima(self):
        """Test anima values are mapped to nodes."""
        mock_anima = MagicMock()
        mock_anima.warmth = 0.8
        mock_anima.clarity = 0.6
        mock_anima.stability = 0.4
        mock_anima.presence = 0.9

        schema = extract_self_schema(anima=mock_anima)

        warmth = [n for n in schema.nodes if n.node_id == "anima_warmth"][0]
        assert warmth.value == 0.8

        clarity = [n for n in schema.nodes if n.node_id == "anima_clarity"][0]
        assert clarity.value == 0.6

    def test_extraction_with_readings(self):
        """Test sensor readings are normalized to nodes."""
        mock_readings = MagicMock()
        mock_readings.light_lux = 500  # Should normalize to 0.5 (500/1000)
        mock_readings.ambient_temp_c = 27.5  # Should normalize to 0.5 ((27.5-15)/25)
        mock_readings.humidity_pct = 50  # Should normalize to 0.5 (50/100)
        mock_readings.pressure_hpa = None
        mock_readings.cpu_percent = 25  # Should normalize to 0.25
        mock_readings.memory_percent = 50  # Should normalize to 0.5
        mock_readings.disk_percent = 30  # Should normalize to 0.3

        schema = extract_self_schema(readings=mock_readings)

        light = [n for n in schema.nodes if n.node_id == "sensor_light"][0]
        assert abs(light.value - 0.5) < 0.01

        temp = [n for n in schema.nodes if n.node_id == "sensor_temp"][0]
        assert abs(temp.value - 0.5) < 0.01

        cpu = [n for n in schema.nodes if n.node_id == "sensor_cpu"][0]
        assert abs(cpu.value - 0.25) < 0.01

    def test_extraction_excludes_low_confidence_preferences(self):
        """Test preferences below threshold are excluded."""
        mock_growth = MagicMock()
        mock_growth.get_dimension_preferences.return_value = {
            "warmth": {"valence": 0.5, "optimal_range": (0.3, 0.7), "confidence": 0.1},  # Below 0.2
            "clarity": {"valence": 0.3, "optimal_range": (0.4, 0.8), "confidence": 0.5},  # Above 0.2
        }

        schema = extract_self_schema(growth_system=mock_growth, include_preferences=True)

        pref_nodes = [n for n in schema.nodes if n.node_type == "preference"]
        assert len(pref_nodes) == 1
        assert pref_nodes[0].node_id == "pref_clarity"

    def test_extraction_includes_high_confidence_preferences(self):
        """Test preferences above threshold are included."""
        mock_growth = MagicMock()
        mock_growth.get_dimension_preferences.return_value = {
            "warmth": {"valence": 0.5, "optimal_range": (0.3, 0.7), "confidence": 0.8},
            "clarity": {"valence": 0.3, "optimal_range": (0.4, 0.8), "confidence": 0.6},
            "stability": {"valence": -0.2, "optimal_range": (0.5, 0.9), "confidence": 0.4},
            "presence": {"valence": 0.1, "optimal_range": (0.4, 0.7), "confidence": 0.3},
        }

        schema = extract_self_schema(growth_system=mock_growth, include_preferences=True)

        pref_nodes = [n for n in schema.nodes if n.node_type == "preference"]
        assert len(pref_nodes) == 4

    def test_extraction_excludes_untested_beliefs(self):
        """Test beliefs without evidence are excluded."""
        mock_self_model = MagicMock()
        mock_self_model.get_belief_summary.return_value = {
            "light_sensitive": {
                "description": "I am sensitive to light",
                "confidence": 0.7,
                "value": 0.8,
                "strength": "confident",
                "evidence": "0+ / 0-",  # No evidence
            },
        }

        schema = extract_self_schema(self_model=mock_self_model)

        belief_nodes = [n for n in schema.nodes if n.node_type == "belief"]
        assert len(belief_nodes) == 0

    def test_extraction_excludes_low_confidence_beliefs(self):
        """Test beliefs below confidence threshold are excluded."""
        mock_self_model = MagicMock()
        mock_self_model.get_belief_summary.return_value = {
            "light_sensitive": {
                "description": "I am sensitive to light",
                "confidence": 0.2,  # Below 0.3
                "value": 0.8,
                "strength": "doubtful",
                "evidence": "5+ / 3-",
            },
        }

        schema = extract_self_schema(self_model=mock_self_model)

        belief_nodes = [n for n in schema.nodes if n.node_type == "belief"]
        assert len(belief_nodes) == 0

    def test_extraction_includes_confident_tested_beliefs(self):
        """Test beliefs with evidence and confidence are included."""
        mock_self_model = MagicMock()
        mock_self_model.get_belief_summary.return_value = {
            "light_sensitive": {
                "description": "I am sensitive to light",
                "confidence": 0.7,
                "value": 0.8,
                "strength": "confident",
                "evidence": "10+ / 2-",
            },
            "my_leds_affect_lux": {
                "description": "My LEDs affect my light sensor",
                "confidence": 0.5,
                "value": 0.6,
                "strength": "moderate",
                "evidence": "5+ / 1-",
            },
        }

        schema = extract_self_schema(self_model=mock_self_model)

        belief_nodes = [n for n in schema.nodes if n.node_type == "belief"]
        assert len(belief_nodes) == 2

        # Check labels
        labels = [n.label for n in belief_nodes]
        assert "BLit" in labels
        assert "BLED" in labels

    def test_belief_edges_connect_to_anima(self):
        """Test belief nodes have edges to their mapped anima dimension."""
        mock_self_model = MagicMock()
        mock_self_model.get_belief_summary.return_value = {
            "light_sensitive": {
                "description": "I am sensitive to light",
                "confidence": 0.7,
                "value": 0.8,
                "strength": "confident",
                "evidence": "10+ / 2-",
            },
            "question_asking_tendency": {
                "description": "I ask questions when surprised",
                "confidence": 0.5,
                "value": 0.6,
                "strength": "moderate",
                "evidence": "5+ / 1-",
            },
        }

        schema = extract_self_schema(self_model=mock_self_model)

        # light_sensitive should connect to anima_clarity
        light_edges = [e for e in schema.edges if e.source_id == "belief_light_sensitive"]
        assert len(light_edges) == 1
        assert light_edges[0].target_id == "anima_clarity"

        # question_asking_tendency should connect to anima_clarity
        question_edges = [e for e in schema.edges if e.source_id == "belief_question_asking_tendency"]
        assert len(question_edges) == 1
        assert question_edges[0].target_id == "anima_clarity"

    def test_my_leds_belief_connects_to_presence(self):
        """Test my_leds_affect_lux belief connects to anima_presence."""
        mock_self_model = MagicMock()
        mock_self_model.get_belief_summary.return_value = {
            "my_leds_affect_lux": {
                "description": "My LEDs affect my light sensor",
                "confidence": 0.6,
                "value": 0.7,
                "strength": "confident",
                "evidence": "8+ / 2-",
            },
        }

        schema = extract_self_schema(self_model=mock_self_model)

        led_edges = [e for e in schema.edges if e.source_id == "belief_my_leds_affect_lux"]
        assert len(led_edges) == 1
        assert led_edges[0].target_id == "anima_presence"

    def test_node_ids_unique(self):
        """Test all node IDs are unique."""
        mock_anima = MagicMock()
        mock_anima.warmth = 0.5
        mock_anima.clarity = 0.5
        mock_anima.stability = 0.5
        mock_anima.presence = 0.5

        mock_growth = MagicMock()
        mock_growth.get_dimension_preferences.return_value = {
            "warmth": {"valence": 0.5, "optimal_range": (0.3, 0.7), "confidence": 0.8},
        }

        mock_self_model = MagicMock()
        mock_self_model.get_belief_summary.return_value = {
            "light_sensitive": {
                "confidence": 0.7, "value": 0.8, "evidence": "10+ / 2-",
            },
        }

        schema = extract_self_schema(
            anima=mock_anima,
            growth_system=mock_growth,
            self_model=mock_self_model,
        )

        node_ids = [n.node_id for n in schema.nodes]
        assert len(node_ids) == len(set(node_ids))

    def test_edge_references_valid_nodes(self):
        """Test all edge source/target IDs exist in nodes."""
        mock_self_model = MagicMock()
        mock_self_model.get_belief_summary.return_value = {
            "light_sensitive": {
                "confidence": 0.7, "value": 0.8, "evidence": "10+ / 2-",
            },
        }

        schema = extract_self_schema(self_model=mock_self_model)

        node_ids = {n.node_id for n in schema.nodes}

        for edge in schema.edges:
            assert edge.source_id in node_ids, f"Edge source {edge.source_id} not in nodes"
            assert edge.target_id in node_ids, f"Edge target {edge.target_id} not in nodes"


class TestGetCurrentSchema:
    """Test get_current_schema wrapper."""

    def test_delegates_to_extract(self):
        """Test get_current_schema calls extract_self_schema."""
        schema = get_current_schema()
        assert isinstance(schema, SelfSchema)
        assert len(schema.nodes) == 12  # Base graph


class TestSensorAnimaWeights:
    """Test _get_sensor_anima_weights helper."""

    def test_returns_dict_of_weights(self):
        """Test function returns weight dictionary."""
        weights = _get_sensor_anima_weights()
        assert isinstance(weights, dict)

        # Should have some known mappings
        assert len(weights) > 0

        # Keys should be (source, target) tuples
        for key in weights:
            assert isinstance(key, tuple)
            assert len(key) == 2

    def test_weights_in_valid_range(self):
        """Test all weights are in [-1, 1]."""
        weights = _get_sensor_anima_weights()

        for (source, target), weight in weights.items():
            assert -1.0 <= weight <= 1.0, f"Weight {weight} for {source}->{target} out of range"
