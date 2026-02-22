"""Tests for SchemaHub - the unified self-model orchestrator."""

import pytest
from datetime import datetime
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
