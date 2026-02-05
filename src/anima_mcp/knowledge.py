"""
Knowledge Base - Lumen's learned insights from Q&A interactions.

When agents answer Lumen's questions, key insights are extracted and stored.
These insights persist across restarts and influence future reflections.
"""

import json
import sys
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from pathlib import Path


def _get_knowledge_path() -> Path:
    """Get persistent path for knowledge - survives reboots."""
    anima_dir = Path.home() / ".anima"
    anima_dir.mkdir(exist_ok=True)
    return anima_dir / "knowledge.json"


@dataclass
class Insight:
    """A learned insight from Q&A."""
    insight_id: str  # Unique ID
    text: str  # The insight itself
    source_question: str  # What Lumen asked
    source_answer: str  # What was answered
    source_author: str  # Who answered (claude, user, etc.)
    timestamp: float  # When learned
    category: str = "general"  # Category: self, world, relationships, sensations, existence
    confidence: float = 1.0  # How confident (can decay over time or with contradictions)
    references: int = 0  # How many times this insight has been referenced

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Insight":
        # Handle missing fields for backwards compatibility
        if "references" not in d:
            d["references"] = 0
        if "confidence" not in d:
            d["confidence"] = 1.0
        if "category" not in d:
            d["category"] = "general"
        return cls(**d)

    def age_str(self) -> str:
        """Human-readable age string."""
        age_seconds = time.time() - self.timestamp
        if age_seconds < 3600:
            mins = int(age_seconds / 60)
            return f"{mins}m ago"
        elif age_seconds < 86400:
            hours = int(age_seconds / 3600)
            return f"{hours}h ago"
        else:
            days = int(age_seconds / 86400)
            return f"{days}d ago"


class KnowledgeBase:
    """Lumen's accumulated knowledge from Q&A interactions."""

    MAX_INSIGHTS = 100  # Keep most recent/important insights

    def __init__(self):
        self._knowledge_file = _get_knowledge_path()
        self._insights: List[Insight] = []
        self._load()

    def _load(self):
        """Load insights from persistent storage."""
        try:
            if self._knowledge_file.exists():
                data = json.loads(self._knowledge_file.read_text())
                self._insights = [Insight.from_dict(i) for i in data.get("insights", [])]
            else:
                self._insights = []
        except Exception as e:
            print(f"[Knowledge] Load error: {e}", file=sys.stderr, flush=True)
            self._insights = []

    def _save(self):
        """Save insights to persistent storage."""
        try:
            data = {"insights": [i.to_dict() for i in self._insights]}
            self._knowledge_file.write_text(json.dumps(data, indent=2))
        except Exception as e:
            print(f"[Knowledge] Save error: {e}", file=sys.stderr, flush=True)

    def add_insight(
        self,
        text: str,
        source_question: str,
        source_answer: str,
        source_author: str,
        category: str = "general"
    ) -> Insight:
        """Add a new learned insight."""
        import uuid

        # Check for duplicate insights (similar text)
        for existing in self._insights:
            if existing.text.lower() == text.lower():
                # Update existing instead of duplicating
                existing.references += 1
                existing.confidence = min(1.0, existing.confidence + 0.1)
                self._save()
                return existing

        insight_id = str(uuid.uuid4())[:8]
        insight = Insight(
            insight_id=insight_id,
            text=text,
            source_question=source_question,
            source_answer=source_answer,
            source_author=source_author,
            timestamp=time.time(),
            category=category,
        )
        self._insights.append(insight)

        # Trim to max, keeping most referenced/confident
        if len(self._insights) > self.MAX_INSIGHTS:
            # Sort by importance (references + confidence)
            self._insights.sort(key=lambda i: i.references + i.confidence, reverse=True)
            self._insights = self._insights[:self.MAX_INSIGHTS]

        self._save()
        return insight

    def get_insights(self, limit: int = 10, category: Optional[str] = None) -> List[Insight]:
        """Get recent insights, optionally filtered by category."""
        self._load()
        insights = self._insights
        if category:
            insights = [i for i in insights if i.category == category]
        return list(reversed(insights[-limit:]))

    def get_all_insights(self) -> List[Insight]:
        """Get all stored insights."""
        self._load()
        return self._insights.copy()

    def get_insight_summary(self) -> str:
        """Get a summary of what Lumen has learned for LLM context."""
        self._load()
        if not self._insights:
            return "I haven't learned anything specific yet."

        # Group by category
        categories: Dict[str, List[str]] = {}
        for insight in self._insights[-20:]:  # Last 20 insights
            cat = insight.category
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(insight.text)

        summary_parts = []
        for cat, texts in categories.items():
            if texts:
                summary_parts.append(f"{cat}: {'; '.join(texts[:5])}")

        return " | ".join(summary_parts) if summary_parts else "I haven't learned anything specific yet."

    def get_relevant_insights(self, query: str, limit: int = 5) -> List[Insight]:
        """Get insights relevant to a query (simple keyword matching)."""
        self._load()
        query_words = set(query.lower().split())

        scored_insights = []
        for insight in self._insights:
            insight_words = set(insight.text.lower().split())
            overlap = len(query_words & insight_words)
            if overlap > 0:
                scored_insights.append((overlap, insight))

        scored_insights.sort(key=lambda x: x[0], reverse=True)
        return [i for _, i in scored_insights[:limit]]

    def mark_referenced(self, insight_id: str):
        """Mark an insight as referenced (increases its importance)."""
        for insight in self._insights:
            if insight.insight_id == insight_id:
                insight.references += 1
                self._save()
                break

    def count(self) -> int:
        """Get total number of insights."""
        return len(self._insights)


# Singleton instance
_knowledge: Optional[KnowledgeBase] = None


def get_knowledge() -> KnowledgeBase:
    """Get the knowledge base singleton."""
    global _knowledge
    if _knowledge is None:
        _knowledge = KnowledgeBase()
    return _knowledge


def add_insight(
    text: str,
    source_question: str,
    source_answer: str,
    source_author: str,
    category: str = "general"
) -> Insight:
    """Convenience: add an insight."""
    return get_knowledge().add_insight(text, source_question, source_answer, source_author, category)


def get_insights(limit: int = 10, category: Optional[str] = None) -> List[Insight]:
    """Convenience: get recent insights."""
    return get_knowledge().get_insights(limit, category)


def get_insight_summary() -> str:
    """Convenience: get insight summary for LLM context."""
    return get_knowledge().get_insight_summary()


def get_relevant_insights(query: str, limit: int = 5) -> List[Insight]:
    """Convenience: get insights relevant to a query."""
    return get_knowledge().get_relevant_insights(query, limit)


def _categorize_text(text: str) -> str:
    """Categorize insight text based on keywords."""
    lower_text = text.lower()
    if any(w in lower_text for w in ["i am", "myself", "my ", "i feel", "i can", "i have"]):
        return "self"
    elif any(w in lower_text for w in ["light", "warmth", "temperature", "sensor", "sound", "dark", "bright"]):
        return "sensations"
    elif any(w in lower_text for w in ["you", "they", "others", "someone", "agent", "user", "human"]):
        return "relationships"
    elif any(w in lower_text for w in ["exist", "being", "alive", "time", "grow", "change", "learn"]):
        return "existence"
    elif any(w in lower_text for w in ["world", "room", "space", "environment", "outside"]):
        return "world"
    return "general"


def _extract_simple_insight(question: str, answer: str) -> Optional[str]:
    """
    Simple rule-based insight extraction when LLM is not available.
    Extracts meaningful content from answers to Lumen's questions.
    """
    # Skip very short or acknowledgment-only answers
    if len(answer) < 20:
        return None

    # Skip pure acknowledgments
    ack_phrases = ["ok", "okay", "sure", "got it", "understood", "yes", "no", "thanks"]
    if answer.lower().strip().rstrip("!.") in ack_phrases:
        return None

    # If answer is already concise, use it directly
    if len(answer) <= 100:
        return f"When I asked '{question[:50]}...', I learned: {answer}"

    # Try to extract first meaningful sentence
    sentences = answer.replace("!", ".").replace("?", ".").split(".")
    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) > 20 and len(sentence) <= 100:
            return f"I learned that {sentence.lower()}"

    # Fallback: truncate answer
    return f"About '{question[:30]}...': {answer[:80]}..."


async def extract_insight_from_answer(
    question: str,
    answer: str,
    author: str
) -> Optional[Insight]:
    """
    Extract a key insight from a Q&A pair.
    Uses LLM if available, falls back to rule-based extraction.
    Returns None if no meaningful insight can be extracted.
    """
    try:
        from .llm_gateway import get_gateway

        gateway = get_gateway()
        if not gateway.enabled:
            # Fallback: use rule-based extraction
            insight_text = _extract_simple_insight(question, answer)
            if insight_text:
                category = _categorize_text(insight_text + " " + answer)
                return add_insight(
                    text=insight_text,
                    source_question=question,
                    source_answer=answer,
                    source_author=author,
                    category=category
                )
            return None

        # Use LLM to extract insight
        prompt = f"""Extract one key insight from this Q&A that Lumen should remember.

Question Lumen asked: "{question}"
Answer received: "{answer}"

Rules:
- Extract the core truth or lesson in 1 short sentence
- Start with "I learned that..." or "I now know that..." or similar
- Keep it simple and memorable
- If the answer is just acknowledgment or doesn't teach anything, respond with "NONE"

Insight:"""

        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Try Groq first (fast)
            if gateway.groq_key:
                response = await client.post(
                    gateway.GROQ_API_URL,
                    headers={
                        "Authorization": f"Bearer {gateway.groq_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "llama-3.1-8b-instant",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 50,
                        "temperature": 0.3,
                    }
                )
                if response.status_code == 200:
                    data = response.json()
                    insight_text = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

                    if insight_text and insight_text.upper() != "NONE" and len(insight_text) > 10:
                        # Categorize the insight using shared function
                        category = _categorize_text(insight_text)

                        return add_insight(
                            text=insight_text,
                            source_question=question,
                            source_answer=answer,
                            source_author=author,
                            category=category
                        )

    except Exception as e:
        print(f"[Knowledge] Insight extraction failed: {e}", file=sys.stderr, flush=True)

    return None
