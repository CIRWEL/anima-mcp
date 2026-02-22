"""Tests for SchemaHub - the unified self-model orchestrator."""

import pytest
from datetime import datetime, timedelta
from anima_mcp.schema_hub import SchemaHub
from anima_mcp.self_schema import SelfSchema


class TestSchemaHubFoundation:
    """Test SchemaHub creation and basic operations."""

    def test_schema_hub_initializes_with_empty_history(self):
        """SchemaHub starts with empty schema history."""
        hub = SchemaHub()
        assert len(hub.schema_history) == 0
        assert hub.last_trajectory is None

    def test_schema_hub_has_configurable_history_size(self):
        """SchemaHub history size is configurable."""
        hub = SchemaHub(history_size=50)
        assert hub.history_size == 50

    def test_schema_hub_default_history_size_is_100(self):
        """Default history size is 100 schemas."""
        hub = SchemaHub()
        assert hub.history_size == 100


class TestSchemaComposition:
    """Test SchemaHub schema composition."""

    def test_compose_schema_returns_self_schema(self):
        """compose_schema returns a SelfSchema instance."""
        hub = SchemaHub()
        schema = hub.compose_schema()
        assert isinstance(schema, SelfSchema)

    def test_compose_schema_adds_to_history(self):
        """Each compose_schema call adds to history."""
        hub = SchemaHub()
        hub.compose_schema()
        hub.compose_schema()
        assert len(hub.schema_history) == 2

    def test_compose_schema_respects_history_limit(self):
        """History doesn't exceed history_size."""
        hub = SchemaHub(history_size=3)
        for _ in range(5):
            hub.compose_schema()
        assert len(hub.schema_history) == 3

    def test_compose_schema_with_identity(self):
        """compose_schema uses provided identity."""
        from unittest.mock import MagicMock
        hub = SchemaHub()
        identity = MagicMock()
        identity.name = "TestLumen"
        identity.alive_ratio.return_value = 0.15
        identity.total_awakenings = 42
        identity.age_seconds.return_value = 86400 * 10

        schema = hub.compose_schema(identity=identity)

        # Should have identity node
        identity_nodes = [n for n in schema.nodes if n.node_id == "identity"]
        assert len(identity_nodes) == 1
        assert identity_nodes[0].label == "TestLumen"


class TestSchemaPersistence:
    """Test SchemaHub schema persistence for gap handling."""

    def test_persist_schema_creates_file(self, tmp_path):
        """persist_schema creates JSON file."""
        persist_path = tmp_path / "last_schema.json"
        hub = SchemaHub(persist_path=persist_path)
        hub.compose_schema()
        hub.persist_schema()
        assert persist_path.exists()

    def test_persist_schema_is_valid_json(self, tmp_path):
        """Persisted schema is valid JSON."""
        persist_path = tmp_path / "last_schema.json"
        hub = SchemaHub(persist_path=persist_path)
        hub.compose_schema()
        hub.persist_schema()

        import json
        data = json.loads(persist_path.read_text())
        assert "timestamp" in data
        assert "nodes" in data

    def test_load_previous_schema_returns_none_if_no_file(self, tmp_path):
        """load_previous_schema returns None if no persisted schema."""
        persist_path = tmp_path / "nonexistent.json"
        hub = SchemaHub(persist_path=persist_path)
        result = hub.load_previous_schema()
        assert result is None

    def test_load_previous_schema_restores_schema(self, tmp_path):
        """load_previous_schema restores persisted schema."""
        persist_path = tmp_path / "last_schema.json"
        hub1 = SchemaHub(persist_path=persist_path)
        hub1.compose_schema()
        hub1.persist_schema()

        hub2 = SchemaHub(persist_path=persist_path)
        loaded = hub2.load_previous_schema()
        assert loaded is not None
        assert isinstance(loaded, SelfSchema)


class TestIdentityEnrichment:
    """Test identity meta-nodes (alive_ratio, awakenings, age)."""

    def test_schema_includes_existence_ratio_node(self):
        """Schema includes existence_ratio meta-node."""
        from unittest.mock import MagicMock
        hub = SchemaHub()

        identity = MagicMock()
        identity.name = "Lumen"
        identity.alive_ratio.return_value = 0.15
        identity.total_awakenings = 47
        identity.age_seconds.return_value = 86400 * 42  # 42 days

        schema = hub.compose_schema(identity=identity)

        existence_nodes = [n for n in schema.nodes if n.node_id == "meta_existence_ratio"]
        assert len(existence_nodes) == 1
        assert abs(existence_nodes[0].value - 0.15) < 0.01

    def test_schema_includes_awakening_count_node(self):
        """Schema includes awakening_count meta-node."""
        from unittest.mock import MagicMock
        hub = SchemaHub()

        identity = MagicMock()
        identity.name = "Lumen"
        identity.alive_ratio.return_value = 0.15
        identity.total_awakenings = 47
        identity.age_seconds.return_value = 86400 * 42

        schema = hub.compose_schema(identity=identity)

        awakening_nodes = [n for n in schema.nodes if n.node_id == "meta_awakening_count"]
        assert len(awakening_nodes) == 1
        assert awakening_nodes[0].raw_value == 47

    def test_schema_includes_age_days_node(self):
        """Schema includes age_days meta-node."""
        from unittest.mock import MagicMock
        hub = SchemaHub()

        identity = MagicMock()
        identity.name = "Lumen"
        identity.alive_ratio.return_value = 0.15
        identity.total_awakenings = 47
        identity.age_seconds.return_value = 86400 * 42  # 42 days

        schema = hub.compose_schema(identity=identity)

        age_nodes = [n for n in schema.nodes if n.node_id == "meta_age_days"]
        assert len(age_nodes) == 1
        assert abs(age_nodes[0].raw_value - 42) < 0.1


class TestGapHandling:
    """Test gap detection and texture nodes."""

    def test_compute_gap_delta_returns_none_without_previous(self, tmp_path):
        """compute_gap_delta returns None if no previous schema."""
        persist_path = tmp_path / "last_schema.json"
        hub = SchemaHub(persist_path=persist_path)
        schema = hub.compose_schema()
        delta = hub.compute_gap_delta(schema)
        assert delta is None

    def test_compute_gap_delta_calculates_duration(self, tmp_path):
        """compute_gap_delta calculates gap duration."""
        persist_path = tmp_path / "last_schema.json"
        hub = SchemaHub(persist_path=persist_path)

        # Create and persist a schema
        hub.compose_schema()
        hub.persist_schema()

        # Simulate time passing by modifying persisted timestamp
        import json
        data = json.loads(persist_path.read_text())
        old_time = datetime.fromisoformat(data["timestamp"]) - timedelta(hours=2)
        data["timestamp"] = old_time.isoformat()
        persist_path.write_text(json.dumps(data))

        # New hub loads previous, computes delta
        hub2 = SchemaHub(persist_path=persist_path)
        hub2.load_previous_schema()  # Load into hub
        current = hub2.compose_schema()

        # The delta should be computed during on_wake
        hub2.on_wake()
        assert hub2.last_gap_delta is not None
        assert hub2.last_gap_delta.duration_seconds > 7000  # ~2 hours

    def test_on_wake_adds_gap_texture_nodes(self, tmp_path):
        """on_wake adds gap_duration meta-node to next schema."""
        persist_path = tmp_path / "last_schema.json"
        hub = SchemaHub(persist_path=persist_path)

        # Create and persist
        hub.compose_schema()
        hub.persist_schema()

        # Modify timestamp to simulate gap
        import json
        data = json.loads(persist_path.read_text())
        old_time = datetime.fromisoformat(data["timestamp"]) - timedelta(hours=1)
        data["timestamp"] = old_time.isoformat()
        persist_path.write_text(json.dumps(data))

        # New hub wakes up
        hub2 = SchemaHub(persist_path=persist_path)
        hub2.on_wake()

        # Next schema should have gap texture
        schema = hub2.compose_schema()
        gap_nodes = [n for n in schema.nodes if n.node_id == "meta_gap_duration"]
        assert len(gap_nodes) == 1

    def test_gap_includes_state_delta_when_anima_changed(self, tmp_path):
        """Gap texture includes state_delta when anima changed."""
        from unittest.mock import MagicMock
        persist_path = tmp_path / "last_schema.json"
        hub = SchemaHub(persist_path=persist_path)

        # Create and persist schema with specific anima values
        anima1 = MagicMock()
        anima1.warmth = 0.5
        anima1.clarity = 0.5
        anima1.stability = 0.5
        anima1.presence = 0.5
        hub.compose_schema(anima=anima1)
        hub.persist_schema()

        # Modify timestamp to simulate gap
        import json
        data = json.loads(persist_path.read_text())
        old_time = datetime.fromisoformat(data["timestamp"]) - timedelta(hours=1)
        data["timestamp"] = old_time.isoformat()
        persist_path.write_text(json.dumps(data))

        # New hub wakes with different anima values
        hub2 = SchemaHub(persist_path=persist_path)
        hub2.on_wake()

        anima2 = MagicMock()
        anima2.warmth = 0.8  # Changed!
        anima2.clarity = 0.5
        anima2.stability = 0.5
        anima2.presence = 0.5
        schema = hub2.compose_schema(anima=anima2)

        # Should have state_delta node
        delta_nodes = [n for n in schema.nodes if n.node_id == "meta_state_delta"]
        assert len(delta_nodes) == 1
        assert delta_nodes[0].raw_value.get("warmth", 0) > 0


class TestTrajectoryFeedback:
    """Test trajectory computation from schema history and feedback to schema."""

    def test_trajectory_computed_after_threshold(self):
        """Trajectory is computed after trajectory_compute_interval schemas."""
        hub = SchemaHub()
        hub._trajectory_compute_interval = 5  # Lower for testing

        # Add schemas until threshold
        for _ in range(6):
            hub.compose_schema()

        # Should have triggered trajectory computation
        assert hub.last_trajectory is not None

    def test_trajectory_nodes_injected(self):
        """Trajectory-derived nodes appear in schema after computation."""
        hub = SchemaHub()
        hub._trajectory_compute_interval = 3

        # Generate enough history
        for _ in range(4):
            hub.compose_schema()

        # Get latest schema
        schema = hub.schema_history[-1]

        # Should have trajectory-derived nodes
        traj_nodes = [n for n in schema.nodes if n.node_id.startswith("traj_")]
        assert len(traj_nodes) > 0

    def test_identity_maturity_node_exists(self):
        """identity_maturity trajectory node exists after computation."""
        hub = SchemaHub()
        hub._trajectory_compute_interval = 3

        for _ in range(4):
            hub.compose_schema()

        schema = hub.schema_history[-1]
        maturity_nodes = [n for n in schema.nodes if n.node_id == "traj_identity_maturity"]
        assert len(maturity_nodes) == 1


class TestSemanticEdges:
    """Test semantic edges connecting trajectory to anima."""

    def test_trajectory_creates_stability_edge(self):
        """Trajectory stability node creates edge to anima stability."""
        hub = SchemaHub()
        hub._trajectory_compute_interval = 3

        # Generate enough history for trajectory
        for _ in range(4):
            hub.compose_schema()

        schema = hub.schema_history[-1]

        # If trajectory was computed and stability node exists,
        # there should be an edge to anima_stability
        stability_nodes = [n for n in schema.nodes if n.node_id == "traj_stability_score"]
        if stability_nodes:
            stability_edges = [
                e for e in schema.edges
                if e.source_id == "traj_stability_score" and e.target_id == "anima_stability"
            ]
            assert len(stability_edges) == 1

    def test_trajectory_creates_attractor_edge(self):
        """Trajectory attractor position node creates edge to anima warmth."""
        hub = SchemaHub()
        hub._trajectory_compute_interval = 3

        # Generate enough history for trajectory
        for _ in range(4):
            hub.compose_schema()

        schema = hub.schema_history[-1]

        # If trajectory was computed and attractor position node exists,
        # there should be an edge to anima_warmth
        attractor_nodes = [n for n in schema.nodes if n.node_id == "traj_attractor_position"]
        if attractor_nodes:
            attractor_edges = [
                e for e in schema.edges
                if e.source_id == "traj_attractor_position" and e.target_id == "anima_warmth"
            ]
            assert len(attractor_edges) == 1
