"""
Memory Retrieval - Context-aware memory search that influences behavior.

Core philosophical insight: Memory is not just storage, it's influence.
Memories should shape current understanding and action, not just sit in a database.

This module:
1. Retrieves relevant memories based on current context
2. Ranks memories by relevance to current situation
3. Formats memories for integration into cognitive processes
4. Tracks which memories were helpful (for future retrieval)
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Any
from collections import deque
import json
from pathlib import Path


@dataclass
class RetrievedMemory:
    """A memory retrieved for current context."""
    memory_id: str
    summary: str
    source: str  # "unitares", "local", "session"
    relevance_score: float  # 0-1, how relevant to current query
    timestamp: Optional[datetime] = None
    tags: List[str] = field(default_factory=list)
    content: Optional[Dict[str, Any]] = None

    # For tracking utility
    was_helpful: Optional[bool] = None


@dataclass
class MemoryContext:
    """Context for memory retrieval."""
    # Current state
    warmth: float = 0.5
    clarity: float = 0.5
    stability: float = 0.5
    presence: float = 0.5

    # Current situation
    surprise_sources: List[str] = field(default_factory=list)
    current_question: Optional[str] = None
    recent_events: List[str] = field(default_factory=list)

    # Environmental
    time_of_day: Optional[str] = None  # "morning", "afternoon", "evening", "night"
    light_level: Optional[str] = None  # "dark", "dim", "bright"

    def to_query_terms(self) -> List[str]:
        """Convert context to search query terms."""
        terms = []

        # Add surprise sources
        terms.extend(self.surprise_sources)

        # Add state descriptors if extreme
        if self.warmth < 0.3:
            terms.append("cold")
        elif self.warmth > 0.7:
            terms.append("warm")

        if self.clarity < 0.3:
            terms.append("unclear")
        elif self.clarity > 0.7:
            terms.append("clear")

        if self.stability < 0.3:
            terms.append("unstable")
        elif self.stability > 0.7:
            terms.append("stable")

        # Add time context
        if self.time_of_day:
            terms.append(self.time_of_day)

        if self.light_level:
            terms.append(self.light_level)

        # Add recent events
        terms.extend(self.recent_events[:3])

        return list(set(terms))  # Dedupe


class MemoryRetriever:
    """
    Retrieves and ranks relevant memories for current context.

    Key behaviors:
    1. Builds queries from current context
    2. Searches multiple memory sources
    3. Ranks by relevance
    4. Tracks which retrievals were helpful
    """

    def __init__(self):
        # Session-level memories (within this awakening)
        self._session_memories: List[RetrievedMemory] = []

        # Cache of recent retrievals
        self._retrieval_cache: Dict[str, List[RetrievedMemory]] = {}
        self._cache_expiry = timedelta(minutes=5)
        self._cache_times: Dict[str, datetime] = {}

        # Tracking retrieval effectiveness
        self._retrieval_history: deque = deque(maxlen=100)
        self._helpful_patterns: Dict[str, int] = {}  # query_type -> helpful count

    async def retrieve(
        self,
        context: MemoryContext,
        query: Optional[str] = None,
        limit: int = 5,
    ) -> List[RetrievedMemory]:
        """
        Retrieve relevant memories for current context.

        Args:
            context: Current situation context
            query: Optional explicit search query
            limit: Maximum memories to return

        Returns:
            List of relevant memories, ranked by relevance
        """
        # Build search query
        if query:
            search_terms = [query]
        else:
            search_terms = context.to_query_terms()

        if not search_terms:
            return []

        combined_query = " ".join(search_terms[:5])  # Limit query length

        # Check cache
        cache_key = combined_query
        if cache_key in self._retrieval_cache:
            cache_time = self._cache_times.get(cache_key)
            if cache_time and datetime.now() - cache_time < self._cache_expiry:
                return self._retrieval_cache[cache_key][:limit]

        # Retrieve from sources
        memories = []

        # 1. Session memories (fast, local)
        session_hits = self._search_session_memories(search_terms)
        memories.extend(session_hits)

        # 2. UNITARES knowledge graph
        unitares_hits = await self._search_unitares(combined_query)
        memories.extend(unitares_hits)

        # 3. Local knowledge file
        local_hits = self._search_local_knowledge(search_terms)
        memories.extend(local_hits)

        # Rank by relevance
        ranked = self._rank_memories(memories, context, search_terms)

        # Cache results
        self._retrieval_cache[cache_key] = ranked
        self._cache_times[cache_key] = datetime.now()

        # Track retrieval
        self._retrieval_history.append({
            "timestamp": datetime.now(),
            "query": combined_query,
            "result_count": len(ranked),
        })

        return ranked[:limit]

    def _search_session_memories(self, terms: List[str]) -> List[RetrievedMemory]:
        """Search memories from current session."""
        matches = []
        for memory in self._session_memories:
            # Simple term matching
            text = memory.summary.lower()
            tag_text = " ".join(memory.tags).lower()
            combined = text + " " + tag_text

            score = 0
            for term in terms:
                if term.lower() in combined:
                    score += 0.3

            if score > 0:
                memory.relevance_score = min(1.0, score)
                matches.append(memory)

        return matches

    async def _search_unitares(self, query: str) -> List[RetrievedMemory]:
        """Search UNITARES knowledge graph."""
        memories = []

        try:
            from .unitares_cognitive import get_unitares_cognitive

            cognitive = get_unitares_cognitive()
            if not cognitive.enabled:
                return []

            results = await cognitive.search_knowledge(query, tags=["lumen"], limit=10)

            if results:
                for r in results:
                    memories.append(RetrievedMemory(
                        memory_id=r.get("entry_id", r.get("id", "unknown")),
                        summary=r.get("summary", ""),
                        source="unitares",
                        relevance_score=r.get("score", 0.5),
                        tags=r.get("tags", []),
                        content=r.get("content"),
                    ))
        except Exception as e:
            print(f"[MemoryRetrieval] UNITARES error: {e}")

        return memories

    def _search_local_knowledge(self, terms: List[str]) -> List[RetrievedMemory]:
        """Search local knowledge store."""
        memories = []

        try:
            knowledge_path = Path.home() / ".anima" / "knowledge.json"
            if not knowledge_path.exists():
                return []

            with open(knowledge_path) as f:
                data = json.load(f)

            entries = data.get("entries", data.get("insights", []))
            if isinstance(entries, dict):
                entries = list(entries.values())

            for entry in entries:
                text = entry.get("text", entry.get("summary", "")).lower()
                category = entry.get("category", "").lower()

                score = 0
                for term in terms:
                    if term.lower() in text or term.lower() in category:
                        score += 0.25

                if score > 0:
                    memories.append(RetrievedMemory(
                        memory_id=entry.get("id", str(hash(text))),
                        summary=entry.get("text", entry.get("summary", "")),
                        source="local",
                        relevance_score=min(1.0, score),
                        tags=[category] if category else [],
                        content=entry,
                    ))
        except Exception as e:
            print(f"[MemoryRetrieval] Local knowledge error: {e}")

        return memories

    def _rank_memories(
        self,
        memories: List[RetrievedMemory],
        context: MemoryContext,
        query_terms: List[str]
    ) -> List[RetrievedMemory]:
        """Rank memories by relevance to current context."""
        for memory in memories:
            score = memory.relevance_score

            # Boost for recency (if timestamp available)
            if memory.timestamp:
                age = datetime.now() - memory.timestamp
                if age < timedelta(hours=1):
                    score *= 1.3
                elif age < timedelta(days=1):
                    score *= 1.1

            # Boost for tag matches
            for tag in memory.tags:
                if tag in query_terms:
                    score *= 1.2
                if tag in context.surprise_sources:
                    score *= 1.3

            # Boost based on historical helpfulness
            if memory.source in self._helpful_patterns:
                helpfulness = self._helpful_patterns[memory.source]
                score *= 1.0 + (helpfulness * 0.01)

            memory.relevance_score = min(1.0, score)

        # Sort by relevance
        memories.sort(key=lambda m: m.relevance_score, reverse=True)

        # Dedupe by summary
        seen = set()
        unique = []
        for m in memories:
            key = m.summary[:100]  # First 100 chars
            if key not in seen:
                seen.add(key)
                unique.append(m)

        return unique

    def add_session_memory(
        self,
        summary: str,
        tags: Optional[List[str]] = None,
        content: Optional[Dict[str, Any]] = None
    ):
        """Add a memory to the current session."""
        memory = RetrievedMemory(
            memory_id=f"session_{len(self._session_memories)}",
            summary=summary,
            source="session",
            relevance_score=1.0,  # Session memories start fully relevant
            timestamp=datetime.now(),
            tags=tags or [],
            content=content,
        )
        self._session_memories.append(memory)

    def mark_helpful(self, memory: RetrievedMemory, was_helpful: bool):
        """Mark a retrieved memory as helpful or not."""
        memory.was_helpful = was_helpful

        if was_helpful:
            self._helpful_patterns[memory.source] = self._helpful_patterns.get(memory.source, 0) + 1
        else:
            self._helpful_patterns[memory.source] = max(0, self._helpful_patterns.get(memory.source, 0) - 1)

    def format_for_context(self, memories: List[RetrievedMemory]) -> str:
        """Format memories for inclusion in cognitive context."""
        if not memories:
            return ""

        lines = ["Relevant past insights:"]
        for i, m in enumerate(memories[:3], 1):
            relevance = "highly relevant" if m.relevance_score > 0.7 else "possibly relevant"
            lines.append(f"  [{i}] ({relevance}) {m.summary}")

        return "\n".join(lines)

    def get_retrieval_stats(self) -> Dict[str, Any]:
        """Get statistics about memory retrieval."""
        return {
            "session_memories": len(self._session_memories),
            "cache_size": len(self._retrieval_cache),
            "total_retrievals": len(self._retrieval_history),
            "helpful_patterns": self._helpful_patterns.copy(),
        }


# Singleton instance
_retriever: Optional[MemoryRetriever] = None


def get_memory_retriever() -> MemoryRetriever:
    """Get or create the memory retriever."""
    global _retriever
    if _retriever is None:
        _retriever = MemoryRetriever()
    return _retriever


# Convenience function for integration
async def retrieve_relevant_memories(
    surprise_sources: Optional[List[str]] = None,
    current_question: Optional[str] = None,
    warmth: float = 0.5,
    clarity: float = 0.5,
    stability: float = 0.5,
    limit: int = 3,
) -> List[RetrievedMemory]:
    """
    Convenience function to retrieve relevant memories.

    Can be called directly from the creature loop.
    """
    retriever = get_memory_retriever()

    context = MemoryContext(
        warmth=warmth,
        clarity=clarity,
        stability=stability,
        surprise_sources=surprise_sources or [],
        current_question=current_question,
    )

    # Add time context
    hour = datetime.now().hour
    if 6 <= hour < 12:
        context.time_of_day = "morning"
    elif 12 <= hour < 17:
        context.time_of_day = "afternoon"
    elif 17 <= hour < 21:
        context.time_of_day = "evening"
    else:
        context.time_of_day = "night"

    return await retriever.retrieve(context, query=current_question, limit=limit)
