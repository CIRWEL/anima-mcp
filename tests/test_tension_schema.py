"""Tests for value tension node injection into self-schema."""

import pytest
from datetime import datetime
from anima_mcp.schema_hub import SchemaHub
from anima_mcp.self_schema import SelfSchema, SchemaNode, SchemaEdge
from anima_mcp.value_tension import ConflictEvent


def _make_base_schema():
    """Minimal schema with anima nodes for testing injection."""
    return SelfSchema(
        timestamp=datetime.now(),
        nodes=[
            SchemaNode(node_id="anima_warmth", node_type="anima", label="Warmth", value=0.5),
            SchemaNode(node_id="anima_clarity", node_type="anima", label="Clarity", value=0.5),
            SchemaNode(node_id="anima_stability", node_type="anima", label="Stability", value=0.5),
            SchemaNode(node_id="anima_presence", node_type="anima", label="Presence", value=0.5),
        ],
        edges=[],
    )


def _structural_conflict(dim_a="warmth", dim_b="presence"):
    return ConflictEvent(
        timestamp=datetime.now(),
        dim_a=dim_a, dim_b=dim_b,
        grad_a=0.0, grad_b=0.0,
        duration=-1, category="structural",
    )


def _environmental_conflict(dim_a="warmth", dim_b="stability", duration=7):
    return ConflictEvent(
        timestamp=datetime.now(),
        dim_a=dim_a, dim_b=dim_b,
        grad_a=0.02, grad_b=-0.02,
        duration=duration, category="environmental",
    )


def _volitional_conflict(dim_a="warmth", dim_b="stability", grad_a=0.3, grad_b=-0.2, action="led_brightness"):
    return ConflictEvent(
        timestamp=datetime.now(),
        dim_a=dim_a, dim_b=dim_b,
        grad_a=grad_a, grad_b=grad_b,
        duration=1, category="volitional",
        action_type=action,
    )


class TestInjectTensionNodes:
    def test_none_returns_unchanged(self):
        hub = SchemaHub()
        schema = _make_base_schema()
        original_count = len(schema.nodes)
        result = hub._inject_tension_nodes(schema, None)
        assert len(result.nodes) == original_count

    def test_empty_list_returns_unchanged(self):
        hub = SchemaHub()
        schema = _make_base_schema()
        original_count = len(schema.nodes)
        result = hub._inject_tension_nodes(schema, [])
        assert len(result.nodes) == original_count

    def test_structural_creates_tension_node(self):
        hub = SchemaHub()
        schema = _make_base_schema()
        result = hub._inject_tension_nodes(schema, [_structural_conflict()])
        tension_nodes = [n for n in result.nodes if n.node_type == "tension"]
        assert len(tension_nodes) == 1
        assert tension_nodes[0].node_id == "tension_structural_warmth_presence"
        assert tension_nodes[0].value == 0.5

    def test_structural_creates_two_edges(self):
        hub = SchemaHub()
        schema = _make_base_schema()
        result = hub._inject_tension_nodes(schema, [_structural_conflict()])
        tension_edges = [e for e in result.edges if e.source_id.startswith("tension_")]
        assert len(tension_edges) == 2
        targets = {e.target_id for e in tension_edges}
        assert targets == {"anima_warmth", "anima_presence"}

    def test_edges_have_negative_weight(self):
        hub = SchemaHub()
        schema = _make_base_schema()
        result = hub._inject_tension_nodes(schema, [_structural_conflict()])
        tension_edges = [e for e in result.edges if e.source_id.startswith("tension_")]
        for edge in tension_edges:
            assert edge.weight < 0

    def test_environmental_value_from_duration(self):
        hub = SchemaHub()
        schema = _make_base_schema()
        result = hub._inject_tension_nodes(schema, [_environmental_conflict(duration=7)])
        tension_nodes = [n for n in result.nodes if n.node_type == "tension"]
        assert abs(tension_nodes[0].value - 0.7) < 0.01

    def test_environmental_value_clamped_at_one(self):
        hub = SchemaHub()
        schema = _make_base_schema()
        result = hub._inject_tension_nodes(schema, [_environmental_conflict(duration=15)])
        tension_nodes = [n for n in result.nodes if n.node_type == "tension"]
        assert tension_nodes[0].value == 1.0

    def test_volitional_value_from_gradients(self):
        hub = SchemaHub()
        schema = _make_base_schema()
        result = hub._inject_tension_nodes(schema, [_volitional_conflict(grad_a=0.3, grad_b=-0.2)])
        tension_nodes = [n for n in result.nodes if n.node_type == "tension"]
        # abs(0.3 - (-0.2)) = 0.5
        assert abs(tension_nodes[0].value - 0.5) < 0.01

    def test_volitional_raw_value_includes_action(self):
        hub = SchemaHub()
        schema = _make_base_schema()
        result = hub._inject_tension_nodes(schema, [_volitional_conflict(action="led_brightness")])
        tension_nodes = [n for n in result.nodes if n.node_type == "tension"]
        assert tension_nodes[0].raw_value["action_type"] == "led_brightness"

    def test_raw_value_structure(self):
        hub = SchemaHub()
        schema = _make_base_schema()
        result = hub._inject_tension_nodes(schema, [_structural_conflict()])
        raw = result.nodes[-1].raw_value
        assert "category" in raw
        assert "dim_a" in raw
        assert "dim_b" in raw
        assert "duration" in raw
        assert "action_type" in raw

    def test_multiple_conflicts(self):
        hub = SchemaHub()
        schema = _make_base_schema()
        conflicts = [
            _structural_conflict("warmth", "presence"),
            _structural_conflict("clarity", "stability"),
        ]
        result = hub._inject_tension_nodes(schema, conflicts)
        tension_nodes = [n for n in result.nodes if n.node_type == "tension"]
        assert len(tension_nodes) == 2

    def test_duplicate_pair_keeps_latest(self):
        hub = SchemaHub()
        schema = _make_base_schema()
        conflicts = [
            _environmental_conflict("warmth", "stability", duration=3),
            _environmental_conflict("warmth", "stability", duration=7),
        ]
        result = hub._inject_tension_nodes(schema, conflicts)
        tension_nodes = [n for n in result.nodes if n.node_type == "tension"]
        assert len(tension_nodes) == 1
        assert abs(tension_nodes[0].value - 0.7) < 0.01  # latest (duration=7)

    def test_label_format_structural(self):
        hub = SchemaHub()
        schema = _make_base_schema()
        result = hub._inject_tension_nodes(schema, [_structural_conflict()])
        tension_nodes = [n for n in result.nodes if n.node_type == "tension"]
        assert tension_nodes[0].label == "warmth ↔ presence"

    def test_label_format_environmental(self):
        hub = SchemaHub()
        schema = _make_base_schema()
        result = hub._inject_tension_nodes(schema, [_environmental_conflict()])
        tension_nodes = [n for n in result.nodes if n.node_type == "tension"]
        assert "Env:" in tension_nodes[0].label

    def test_label_format_volitional(self):
        hub = SchemaHub()
        schema = _make_base_schema()
        result = hub._inject_tension_nodes(schema, [_volitional_conflict()])
        tension_nodes = [n for n in result.nodes if n.node_type == "tension"]
        assert "Vol:" in tension_nodes[0].label


class TestComposeSchemaWithTensions:
    def test_accepts_tension_conflicts_param(self):
        hub = SchemaHub()
        conflicts = [_structural_conflict()]
        schema = hub.compose_schema(tension_conflicts=conflicts)
        tension_nodes = [n for n in schema.nodes if n.node_type == "tension"]
        assert len(tension_nodes) >= 1

    def test_none_tension_backwards_compat(self):
        hub = SchemaHub()
        schema = hub.compose_schema()
        assert schema is not None
        assert len(schema.nodes) > 0
