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
