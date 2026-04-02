"""Tests for memory_retrieval — context queries, ranking, session search, local knowledge."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from anima_mcp.memory_retrieval import (
    MemoryContext,
    MemoryRetriever,
    RetrievedMemory,
    retrieve_relevant_memories,
)


class TestMemoryContext:
    def test_to_query_terms_empty_for_neutral_state(self):
        ctx = MemoryContext()
        terms = ctx.to_query_terms()
        assert terms == []

    def test_to_query_terms_extreme_warmth_and_clarity(self):
        ctx = MemoryContext(warmth=0.1, clarity=0.9, stability=0.1)
        terms = set(ctx.to_query_terms())
        assert "cold" in terms
        assert "clear" in terms
        assert "unstable" in terms

    def test_to_query_terms_time_light_and_events(self):
        ctx = MemoryContext(
            time_of_day="evening",
            light_level="dim",
            recent_events=["event_a", "event_b", "event_c", "event_d"],
        )
        terms = ctx.to_query_terms()
        assert "evening" in terms
        assert "dim" in terms
        assert "event_a" in terms
        assert "event_b" in terms
        assert "event_c" in terms
        assert "event_d" not in terms


class TestMemoryRetrieverSessionSearch:
    def test_search_session_memories_scores_matching_terms(self):
        r = MemoryRetriever()
        r.add_session_memory("quiet morning light", tags=["calm"])
        hits = r._search_session_memories(["morning", "light"])
        assert len(hits) == 1
        assert hits[0].relevance_score > 0

    def test_search_session_memories_no_match(self):
        r = MemoryRetriever()
        r.add_session_memory("unrelated text", tags=[])
        hits = r._search_session_memories(["quantum"])
        assert hits == []


class TestMemoryRetrieverRanking:
    def test_rank_memories_dedupes_by_summary_prefix(self):
        r = MemoryRetriever()
        dup = "identical summary for dedupe"
        a = RetrievedMemory(
            memory_id="1",
            summary=dup,
            source="session",
            relevance_score=0.5,
        )
        b = RetrievedMemory(
            memory_id="2",
            summary=dup,
            source="local",
            relevance_score=0.6,
        )
        ctx = MemoryContext()
        out = r._rank_memories([a, b], ctx, [])
        assert len(out) == 1
        assert out[0].relevance_score == pytest.approx(0.6)

    def test_rank_memories_boosts_recent_timestamp(self):
        r = MemoryRetriever()
        old = RetrievedMemory(
            memory_id="o",
            summary="old insight",
            source="session",
            relevance_score=0.5,
            timestamp=datetime.now() - timedelta(days=2),
        )
        new = RetrievedMemory(
            memory_id="n",
            summary="new insight",
            source="session",
            relevance_score=0.5,
            timestamp=datetime.now() - timedelta(minutes=30),
        )
        ctx = MemoryContext()
        out = r._rank_memories([old, new], ctx, [])
        assert out[0].summary == "new insight"

    def test_rank_memories_tag_match_boost(self):
        r = MemoryRetriever()
        m = RetrievedMemory(
            memory_id="t",
            summary="tagged",
            source="session",
            relevance_score=0.4,
            tags=["evening"],
        )
        ctx = MemoryContext()
        out = r._rank_memories([m], ctx, ["evening"])
        assert out[0].relevance_score >= 0.4 * 1.2


class TestMemoryRetrieverLocalKnowledge:
    def test_search_local_knowledge_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        r = MemoryRetriever()
        assert r._search_local_knowledge(["x"]) == []

    def test_search_local_knowledge_entries_format(self, tmp_path, monkeypatch):
        anima = tmp_path / ".anima"
        anima.mkdir()
        (anima / "knowledge.json").write_text(
            json.dumps(
                {
                    "entries": [
                        {
                            "id": "e1",
                            "text": "warm sunlight on the desk",
                            "category": "environment",
                        }
                    ]
                }
            )
        )
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        r = MemoryRetriever()
        hits = r._search_local_knowledge(["warm", "environment"])
        assert len(hits) == 1
        assert hits[0].source == "local"
        assert "sunlight" in hits[0].summary

    def test_search_local_knowledge_insights_key(self, tmp_path, monkeypatch):
        anima = tmp_path / ".anima"
        anima.mkdir()
        (anima / "knowledge.json").write_text(
            json.dumps({"insights": [{"text": "stable patterns", "category": "meta"}]})
        )
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        r = MemoryRetriever()
        hits = r._search_local_knowledge(["stable"])
        assert len(hits) == 1


class TestMemoryRetrieverAsync:
    @pytest.mark.asyncio
    async def test_retrieve_empty_when_no_terms(self):
        r = MemoryRetriever()
        ctx = MemoryContext()
        out = await r.retrieve(ctx, query=None)
        assert out == []

    @pytest.mark.asyncio
    async def test_retrieve_with_explicit_query(self):
        r = MemoryRetriever()
        r.add_session_memory("evening calm reflection")
        ctx = MemoryContext()
        out = await r.retrieve(ctx, query="evening", limit=3)
        assert len(out) >= 1
        assert "evening" in out[0].summary or out[0].relevance_score > 0

    @pytest.mark.asyncio
    async def test_retrieve_uses_cache_within_ttl(self):
        r = MemoryRetriever()
        r.add_session_memory("cached topic alpha")
        ctx = MemoryContext()
        q = await r.retrieve(ctx, query="alpha", limit=5)
        with patch.object(r, "_search_unitares", new_callable=AsyncMock) as u:
            u.return_value = []
            q2 = await r.retrieve(ctx, query="alpha", limit=5)
            u.assert_not_called()
        assert len(q) == len(q2)


class TestMemoryRetrieverHelpers:
    def test_format_for_context_empty(self):
        r = MemoryRetriever()
        assert r.format_for_context([]) == ""

    def test_format_for_context_truncates_to_three(self):
        r = MemoryRetriever()
        mems = [
            RetrievedMemory(
                memory_id=str(i),
                summary=f"line {i}",
                source="session",
                relevance_score=0.9 if i == 0 else 0.5,
            )
            for i in range(5)
        ]
        text = r.format_for_context(mems)
        assert text.count("[") == 3
        assert "line 0" in text

    def test_get_retrieval_stats(self):
        r = MemoryRetriever()
        r.add_session_memory("s")
        assert r.get_retrieval_stats()["session_memories"] == 1

    def test_mark_helpful_adjusts_patterns(self):
        r = MemoryRetriever()
        m = RetrievedMemory(
            memory_id="1",
            summary="x",
            source="local",
            relevance_score=0.5,
        )
        r.mark_helpful(m, True)
        r.mark_helpful(m, True)
        assert r.get_retrieval_stats()["helpful_patterns"].get("local") == 2
        r.mark_helpful(m, False)
        assert r.get_retrieval_stats()["helpful_patterns"].get("local") == 1


class TestRetrieveRelevantMemoriesConvenience:
    @pytest.mark.asyncio
    async def test_convenience_function_runs(self):
        with patch(
            "anima_mcp.memory_retrieval.get_memory_retriever",
            return_value=MemoryRetriever(),
        ):
            out = await retrieve_relevant_memories(
                surprise_sources=["test"],
                current_question=None,
                limit=2,
            )
        assert isinstance(out, list)
