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
