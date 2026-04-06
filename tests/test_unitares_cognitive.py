"""Tests for unitares_cognitive — URL normalization, headers, and async tool helpers."""

import pytest
from unittest.mock import AsyncMock, patch

import anima_mcp.unitares_cognitive as uc_mod
from anima_mcp.unitares_cognitive import UnitaresCognitive


@pytest.fixture(autouse=True)
def reset_unitares_singleton():
    """Avoid cross-test pollution of the module singleton."""
    uc_mod._unitares_cognitive = None
    yield
    uc_mod._unitares_cognitive = None


class TestUnitaresCognitiveConfig:
    def test_enabled_false_without_url(self, monkeypatch):
        monkeypatch.delenv("UNITARES_URL", raising=False)
        c = UnitaresCognitive(unitares_url=None)
        assert c.enabled is False

    def test_enabled_true_with_url(self):
        c = UnitaresCognitive(unitares_url="http://127.0.0.1:8767/mcp/")
        assert c.enabled is True

    def test_get_mcp_url_preserves_mcp_suffix(self):
        c = UnitaresCognitive(unitares_url="http://host:8767/mcp/")
        assert c._get_mcp_url() == "http://host:8767/mcp/"

    def test_get_mcp_url_replaces_sse_with_mcp(self):
        c = UnitaresCognitive(unitares_url="http://host:8767/sse")
        assert c._get_mcp_url() == "http://host:8767/mcp"

    def test_get_mcp_url_appends_mcp_when_missing(self):
        c = UnitaresCognitive(unitares_url="http://host:8767")
        assert c._get_mcp_url() == "http://host:8767/mcp"

    def test_set_agent_id_updates_session_header_shape(self):
        c = UnitaresCognitive(unitares_url="http://x/mcp/")
        c.set_agent_id("abcdef1234567890")
        assert c._agent_id == "abcdef1234567890"
        assert c._session_id == "anima-abcdef12"

    def test_get_headers_includes_agent_and_session_when_set(self):
        c = UnitaresCognitive(unitares_url="http://x/mcp/")
        c.set_agent_id("feedface")
        h = c._get_headers()
        assert h["Content-Type"] == "application/json"
        assert h["X-Agent-Id"] == "feedface"
        assert h["X-Session-ID"] == "anima-feedface"

    def test_get_headers_minimal_when_no_agent(self):
        c = UnitaresCognitive(unitares_url="http://x/mcp/")
        h = c._get_headers()
        assert "X-Agent-Id" not in h
        assert "X-Session-ID" not in h


class TestCallToolDisabled:
    @pytest.mark.asyncio
    async def test_call_tool_returns_none_when_not_enabled(self, monkeypatch):
        monkeypatch.delenv("UNITARES_URL", raising=False)
        c = UnitaresCognitive(unitares_url=None)
        out = await c._call_tool("any_tool", {})
        assert out is None


class TestSearchKnowledgeParsing:
    @pytest.mark.asyncio
    async def test_search_parses_dict_with_entries(self):
        c = UnitaresCognitive(unitares_url="http://127.0.0.1/mcp/")
        with patch.object(c, "_call_tool", new_callable=AsyncMock) as m:
            m.return_value = {"entries": [{"entry_id": "e1", "summary": "alpha"}]}
            out = await c.search_knowledge("light", tags=["lumen"], limit=3)
        assert out == [{"entry_id": "e1", "summary": "alpha"}]
        m.assert_awaited_once()
        call_kw = m.await_args[0][1]
        assert call_kw["query"] == "light"
        assert call_kw["limit"] == 3
        assert call_kw["tags"] == ["lumen"]

    @pytest.mark.asyncio
    async def test_search_returns_list_when_tool_returns_list(self):
        c = UnitaresCognitive(unitares_url="http://127.0.0.1/mcp/")
        raw = [{"id": "1"}]
        with patch.object(c, "_call_tool", new_callable=AsyncMock) as m:
            m.return_value = raw
            out = await c.search_knowledge("q")
        assert out == raw

    @pytest.mark.asyncio
    async def test_search_returns_none_when_tool_returns_unexpected_shape(self):
        c = UnitaresCognitive(unitares_url="http://127.0.0.1/mcp/")
        with patch.object(c, "_call_tool", new_callable=AsyncMock) as m:
            m.return_value = "unexpected"
            out = await c.search_knowledge("q")
        assert out is None


class TestStoreKnowledge:
    @pytest.mark.asyncio
    async def test_store_builds_arguments_with_tags(self):
        c = UnitaresCognitive(unitares_url="http://127.0.0.1/mcp/")
        with patch.object(c, "_call_tool", new_callable=AsyncMock) as m:
            m.return_value = {"ok": True}
            await c.store_knowledge(
                "summary text",
                discovery_type="insight",
                tags=["extra"],
                content={"k": "v"},
            )
        m.assert_awaited_once()
        name, args = m.await_args[0]
        assert name == "store_knowledge_graph"
        assert args["summary"] == "summary text"
        assert args["discovery_type"] == "insight"
        assert args["tags"][:2] == ["lumen", "embodied"]
        assert "extra" in args["tags"]
        assert "content" in args
        assert "lumen_cognitive" in args["content"]


class TestDialecticHelpers:
    @pytest.mark.asyncio
    async def test_request_dialectic_review_forwards_summary(self):
        c = UnitaresCognitive(unitares_url="http://127.0.0.1/mcp/")
        with patch.object(c, "_call_tool", new_callable=AsyncMock) as m:
            m.return_value = {"session_id": "s1"}
            out = await c.request_dialectic_review("thesis", tags=["t1"])
        assert out == {"session_id": "s1"}
        name, args = m.await_args[0]
        assert name == "request_dialectic_review"
        assert args["summary"] == "thesis"
        assert "t1" in args["tags"]

    @pytest.mark.asyncio
    async def test_get_dialectic_session_forwards_id(self):
        c = UnitaresCognitive(unitares_url="http://127.0.0.1/mcp/")
        with patch.object(c, "_call_tool", new_callable=AsyncMock) as m:
            await c.get_dialectic_session("sid-99")
        name, args = m.await_args[0]
        assert name == "get_dialectic_session"
        assert args["session_id"] == "sid-99"


class TestGetSingleton:
    def test_get_unitares_cognitive_caches_instance(self):
        uc_mod._unitares_cognitive = None
        a = uc_mod.get_unitares_cognitive("http://a/mcp/")
        b = uc_mod.get_unitares_cognitive()
        assert a is b
