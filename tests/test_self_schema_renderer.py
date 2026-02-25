"""Tests for self_schema_renderer.py - pure rendering functions."""

import math
from datetime import datetime

import pytest

from anima_mcp.self_schema_renderer import (
    _get_anima_color,
    _get_sensor_color,
    _get_resource_color,
    _draw_glow,
    _get_node_position,
    _draw_filled_circle,
    _draw_line,
    _build_node_positions,
    render_schema_to_pixels,
    compute_visual_integrity_stub,
    CENTER,
    WIDTH,
    HEIGHT,
    COLORS,
    RING_1_RADIUS,
    RING_2_RADIUS,
    RING_2B_RADIUS,
    RING_3_RADIUS,
    RING_4_RADIUS,
)
from anima_mcp.self_schema import SelfSchema, SchemaNode, SchemaEdge


# --- Helpers ---


def make_schema():
    return SelfSchema(
        timestamp=datetime.now(),
        nodes=[
            SchemaNode("identity", "identity", "Lumen", 1.0, 1.0),
            SchemaNode("anima_warmth", "anima", "Warmth", 0.5, 0.5),
            SchemaNode("anima_clarity", "anima", "Clarity", 0.7, 0.7),
            SchemaNode("anima_stability", "anima", "Stability", 0.6, 0.6),
            SchemaNode("anima_presence", "anima", "Presence", 0.4, 0.4),
            SchemaNode("sensor_light", "sensor", "Light", 0.8, 300),
            SchemaNode("sensor_memory", "resource", "Mem", 0.6, 60),
        ],
        edges=[
            SchemaEdge("sensor_light", "anima_clarity", 0.5),
        ],
    )


def _assert_rgb_tuple(color):
    """Assert color is a 3-tuple of ints in [0, 255]."""
    assert isinstance(color, tuple)
    assert len(color) == 3
    for c in color:
        assert isinstance(c, int)
        assert 0 <= c <= 255


# --- 1. _get_anima_color ---


class TestGetAnimaColor:
    def test_zero(self):
        color = _get_anima_color(0.0)
        _assert_rgb_tuple(color)
        # At value=0.0 the formula returns the base blue unchanged
        assert color == (60, 90, 150)

    def test_mid(self):
        color = _get_anima_color(0.5)
        _assert_rgb_tuple(color)
        # Brighter than zero
        assert color[0] > 60
        assert color[1] > 90
        assert color[2] > 150

    def test_one(self):
        color = _get_anima_color(1.0)
        _assert_rgb_tuple(color)
        # Brightest possible
        assert color[0] >= _get_anima_color(0.5)[0]
        assert color[1] >= _get_anima_color(0.5)[1]
        assert color[2] >= _get_anima_color(0.5)[2]

    def test_monotonic_brightness(self):
        """Higher value should produce brighter (or equal) color."""
        for lo, hi in [(0.0, 0.3), (0.3, 0.6), (0.6, 1.0)]:
            c_lo = _get_anima_color(lo)
            c_hi = _get_anima_color(hi)
            assert sum(c_hi) >= sum(c_lo)


# --- 2. _get_sensor_color ---


class TestGetSensorColor:
    def test_zero_floored(self):
        color = _get_sensor_color(0.0)
        _assert_rgb_tuple(color)
        # value=0.0 is floored to 0.25, so should equal _get_sensor_color(0.25)
        assert color == _get_sensor_color(0.25)

    def test_mid(self):
        color = _get_sensor_color(0.5)
        _assert_rgb_tuple(color)
        # Brighter than the floor value
        assert sum(color) > sum(_get_sensor_color(0.0))

    def test_one(self):
        color = _get_sensor_color(1.0)
        _assert_rgb_tuple(color)
        assert sum(color) >= sum(_get_sensor_color(0.5))

    def test_floor_prevents_black(self):
        """Even at value=0 the node is visible (not black)."""
        color = _get_sensor_color(0.0)
        assert sum(color) > 0


# --- 3. _get_resource_color ---


class TestGetResourceColor:
    def test_zero_floored(self):
        color = _get_resource_color(0.0)
        _assert_rgb_tuple(color)
        assert color == _get_resource_color(0.25)

    def test_mid(self):
        color = _get_resource_color(0.5)
        _assert_rgb_tuple(color)
        assert sum(color) > sum(_get_resource_color(0.0))

    def test_one(self):
        color = _get_resource_color(1.0)
        _assert_rgb_tuple(color)
        assert sum(color) >= sum(_get_resource_color(0.5))

    def test_floor_prevents_black(self):
        color = _get_resource_color(0.0)
        assert sum(color) > 0


# --- 4. _draw_glow ---


class TestDrawGlow:
    def test_low_intensity_no_pixels(self):
        pixels = {}
        _draw_glow(pixels, CENTER[0], CENTER[1], 10, (200, 200, 200), 0.3)
        assert len(pixels) == 0

    def test_exactly_half_no_pixels(self):
        pixels = {}
        _draw_glow(pixels, CENTER[0], CENTER[1], 10, (200, 200, 200), 0.49)
        assert len(pixels) == 0

    def test_high_intensity_adds_pixels(self):
        pixels = {}
        _draw_glow(pixels, CENTER[0], CENTER[1], 10, (200, 200, 200), 0.8)
        assert len(pixels) > 0

    def test_glow_pixels_outside_node_radius(self):
        """Glow ring should only populate pixels outside the node radius."""
        cx, cy = CENTER
        radius = 10
        pixels = {}
        _draw_glow(pixels, cx, cy, radius, (200, 200, 200), 0.9)
        for (x, y) in pixels:
            dist_sq = (x - cx) ** 2 + (y - cy) ** 2
            assert dist_sq > radius * radius


# --- 5. _get_node_position ---


class TestGetNodePosition:
    def test_identity_at_center(self):
        node = SchemaNode("identity", "identity", "Lumen", 1.0, 1.0)
        pos = _get_node_position(node, 0, 1)
        assert pos == CENTER

    def test_anima_ring1(self):
        for i in range(4):
            node = SchemaNode(f"anima_{i}", "anima", f"A{i}", 0.5, 0.5)
            pos = _get_node_position(node, i, 4)
            # Should be on ring 1, not at center
            dist = math.sqrt((pos[0] - CENTER[0]) ** 2 + (pos[1] - CENTER[1]) ** 2)
            assert dist == pytest.approx(RING_1_RADIUS, abs=1)

    def test_sensor_ring2(self):
        node = SchemaNode("sensor_light", "sensor", "Light", 0.5, 0.5)
        pos = _get_node_position(node, 0, 4)
        dist = math.sqrt((pos[0] - CENTER[0]) ** 2 + (pos[1] - CENTER[1]) ** 2)
        assert dist == pytest.approx(RING_2_RADIUS, abs=2)

    def test_resource_ring2b(self):
        node = SchemaNode("sensor_memory", "resource", "Mem", 0.5, 0.5)
        pos = _get_node_position(node, 0, 3)
        dist = math.sqrt((pos[0] - CENTER[0]) ** 2 + (pos[1] - CENTER[1]) ** 2)
        assert dist == pytest.approx(RING_2B_RADIUS, abs=2)

    def test_preference_ring3(self):
        node = SchemaNode("pref_warmth", "preference", "Pref warmth", 0.5, 0.5)
        pos = _get_node_position(node, 0, 2)
        dist = math.sqrt((pos[0] - CENTER[0]) ** 2 + (pos[1] - CENTER[1]) ** 2)
        assert dist == pytest.approx(RING_3_RADIUS, abs=2)

    def test_belief_ring4(self):
        node = SchemaNode("belief_light", "belief", "BLit", 0.5, 0.5)
        pos = _get_node_position(node, 0, 3)
        dist = math.sqrt((pos[0] - CENTER[0]) ** 2 + (pos[1] - CENTER[1]) ** 2)
        assert dist == pytest.approx(RING_4_RADIUS, abs=2)

    def test_unknown_type_at_center(self):
        node = SchemaNode("foo", "unknown_type", "Foo", 0.5, 0.5)
        pos = _get_node_position(node, 0, 1)
        assert pos == CENTER


# --- 6. _draw_filled_circle ---


class TestDrawFilledCircle:
    def test_small_circle_has_pixels(self):
        pixels = {}
        _draw_filled_circle(pixels, CENTER[0], CENTER[1], 3, (255, 0, 0))
        assert len(pixels) > 0

    def test_center_pixel_set(self):
        pixels = {}
        _draw_filled_circle(pixels, CENTER[0], CENTER[1], 5, (255, 0, 0))
        assert pixels[CENTER] == (255, 0, 0)

    def test_pixel_count_approximates_area(self):
        """Pixel count should be roughly pi*r^2."""
        pixels = {}
        r = 10
        _draw_filled_circle(pixels, CENTER[0], CENTER[1], r, (100, 100, 100))
        expected = math.pi * r * r
        assert abs(len(pixels) - expected) / expected < 0.1

    def test_all_pixels_within_radius(self):
        cx, cy = CENTER
        r = 8
        pixels = {}
        _draw_filled_circle(pixels, cx, cy, r, (0, 255, 0))
        for (x, y) in pixels:
            dist_sq = (x - cx) ** 2 + (y - cy) ** 2
            assert dist_sq <= r * r

    def test_out_of_bounds_clipped(self):
        """Circle at corner should not crash; pixels clipped to canvas."""
        pixels = {}
        _draw_filled_circle(pixels, 0, 0, 5, (255, 255, 255))
        for (x, y) in pixels:
            assert 0 <= x < WIDTH
            assert 0 <= y < HEIGHT


# --- 7. _draw_line ---


class TestDrawLine:
    def test_horizontal_line_pixels(self):
        pixels = {}
        _draw_line(pixels, 10, 50, 30, 50, (255, 255, 255), thickness=1)
        assert len(pixels) > 0
        # All pixels on y=50
        for (x, y) in pixels:
            assert y == 50

    def test_thickness_2_more_pixels(self):
        thin = {}
        _draw_line(thin, 10, 50, 50, 50, (255, 255, 255), thickness=1)
        thick = {}
        _draw_line(thick, 10, 50, 50, 50, (255, 255, 255), thickness=2)
        assert len(thick) > len(thin)

    def test_diagonal_line(self):
        pixels = {}
        _draw_line(pixels, 10, 10, 30, 30, (128, 128, 128), thickness=1)
        assert len(pixels) > 0

    def test_zero_length_line(self):
        """A point line (same start/end) should set at least one pixel."""
        pixels = {}
        _draw_line(pixels, 50, 50, 50, 50, (255, 0, 0), thickness=1)
        assert (50, 50) in pixels


# --- 8. _build_node_positions ---


class TestBuildNodePositions:
    def test_all_nodes_present(self):
        schema = make_schema()
        positions = _build_node_positions(schema)
        for node in schema.nodes:
            assert node.node_id in positions

    def test_identity_at_center(self):
        schema = make_schema()
        positions = _build_node_positions(schema)
        assert positions["identity"] == CENTER

    def test_mixed_types(self):
        """Schema with preference and belief nodes also included."""
        schema = make_schema()
        schema.nodes.append(SchemaNode("pref_warmth", "preference", "Pref warmth", 0.6, 0.6))
        schema.nodes.append(SchemaNode("belief_light_sensitive", "belief", "Light sensitive", 0.5, 0.5))
        positions = _build_node_positions(schema)
        assert "pref_warmth" in positions
        assert "belief_light_sensitive" in positions
        assert len(positions) == len(schema.nodes)

    def test_empty_schema(self):
        schema = SelfSchema(timestamp=datetime.now(), nodes=[], edges=[])
        positions = _build_node_positions(schema)
        assert positions == {}


# --- 9. render_schema_to_pixels ---


class TestRenderSchemaToPixels:
    def test_empty_nodes_empty_dict(self):
        schema = SelfSchema(timestamp=datetime.now(), nodes=[], edges=[])
        pixels = render_schema_to_pixels(schema)
        assert pixels == {}

    def test_with_nodes_non_empty(self):
        schema = make_schema()
        pixels = render_schema_to_pixels(schema)
        assert len(pixels) > 0

    def test_all_pixels_in_bounds(self):
        schema = make_schema()
        pixels = render_schema_to_pixels(schema)
        for (x, y) in pixels:
            assert 0 <= x < WIDTH
            assert 0 <= y < HEIGHT

    def test_identity_node_rendered_at_center(self):
        """The center pixel should have the identity gold color."""
        schema = SelfSchema(
            timestamp=datetime.now(),
            nodes=[SchemaNode("identity", "identity", "Lumen", 1.0, 1.0)],
            edges=[],
        )
        pixels = render_schema_to_pixels(schema)
        assert pixels[CENTER] == COLORS["identity"]

    def test_edge_adds_pixels(self):
        """Rendering with an edge should produce more pixels than without."""
        schema_no_edge = SelfSchema(
            timestamp=datetime.now(),
            nodes=[
                SchemaNode("sensor_light", "sensor", "Light", 0.8, 300),
                SchemaNode("anima_clarity", "anima", "Clarity", 0.7, 0.7),
            ],
            edges=[],
        )
        schema_with_edge = SelfSchema(
            timestamp=datetime.now(),
            nodes=[
                SchemaNode("sensor_light", "sensor", "Light", 0.8, 300),
                SchemaNode("anima_clarity", "anima", "Clarity", 0.7, 0.7),
            ],
            edges=[SchemaEdge("sensor_light", "anima_clarity", 0.5)],
        )
        px_no = render_schema_to_pixels(schema_no_edge)
        px_yes = render_schema_to_pixels(schema_with_edge)
        assert len(px_yes) >= len(px_no)


# --- 10. compute_visual_integrity_stub ---


class TestComputeVisualIntegrityStub:
    def test_empty_schema_returns_zeros(self):
        schema = SelfSchema(timestamp=datetime.now(), nodes=[], edges=[])
        result = compute_visual_integrity_stub({}, schema)
        assert result["v_f"] == 0.0
        assert result["v_c"] == 0.0
        assert result["V"] == 0.0
        assert result["stub"] is True

    def test_empty_pixels_returns_zeros(self):
        schema = make_schema()
        result = compute_visual_integrity_stub({}, schema)
        assert result["v_f"] == 0.0
        assert result["v_c"] == 0.0
        assert result["V"] == 0.0

    def test_with_rendered_schema(self):
        schema = make_schema()
        pixels = render_schema_to_pixels(schema)
        result = compute_visual_integrity_stub(pixels, schema)
        assert 0.0 < result["v_f"] <= 1.0
        assert 0.0 < result["v_c"] <= 1.0
        assert 0.0 < result["V"] <= 1.0
        assert result["stub"] is True
        assert result["actual_pixels"] == len(pixels)
        assert result["expected_pixels"] > 0

    def test_combined_score_formula(self):
        """V = 0.6 * v_f + 0.4 * v_c"""
        schema = make_schema()
        pixels = render_schema_to_pixels(schema)
        result = compute_visual_integrity_stub(pixels, schema)
        expected_V = round(0.6 * result["v_f"] + 0.4 * result["v_c"], 3)
        assert result["V"] == expected_V
