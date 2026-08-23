"""
Growth System data models - dataclasses and enums.

All shared types used across the growth package.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List


PREFERENCE_ESTABLISHED_MIN_EVIDENCE = 10
PREFERENCE_ESTABLISHED_MIN_CONFIDENCE = 0.8
RETIRED_QA_PREFERENCE_ORIGIN = "retired_qa_claim_bridge_v1"


def preference_evidence_confidence(
    supporting_count: int,
    contradicting_count: int,
) -> float:
    """Conservative confidence in the dominant direction of a preference.

    The persisted field names predate this directional interpretation:
    ``supporting_count`` means positive-direction evidence and
    ``contradicting_count`` means negative-direction evidence. Either direction
    can become a well-supported preference. Each count must represent an
    independent evidence window or event, not a broker tick. The score is the
    two-sided 95% Wilson lower bound for the majority direction, mapped from
    chance (0.5) to certainty (1.0). A 0.20 floor preserves the historical
    cold-start posture; a 0.95 ceiling keeps an observational association from
    presenting itself as causal certainty.
    """
    support = max(0, int(supporting_count))
    contradict = max(0, int(contradicting_count))
    total = support + contradict
    if total == 0:
        return 0.0

    majority_rate = max(support, contradict) / total
    z = 1.959963984540054
    denominator = 1.0 + (z * z / total)
    centre = majority_rate + (z * z / (2.0 * total))
    margin = z * (
        (majority_rate * (1.0 - majority_rate) / total)
        + (z * z / (4.0 * total * total))
    ) ** 0.5
    lower_bound = (centre - margin) / denominator
    directional_confidence = max(0.0, 2.0 * (lower_bound - 0.5))
    return round(min(0.95, max(0.20, directional_confidence)), 6)


class PreferenceCategory(Enum):
    """Categories of preferences Lumen can develop."""
    ENVIRONMENT = "environment"  # Light, temp, humidity preferences
    TEMPORAL = "temporal"        # Time-of-day preferences
    SOCIAL = "social"           # Interaction preferences
    ACTIVITY = "activity"       # Drawing, reflecting, etc.
    SENSORY = "sensory"         # Sound, visual preferences


class GoalStatus(Enum):
    """Status of a personal goal."""
    ACTIVE = "active"
    ACHIEVED = "achieved"
    ABANDONED = "abandoned"
    PAUSED = "paused"


class VisitorFrequency(Enum):
    """How often a visitor has been seen. No bond pretense - agents are ephemeral."""
    NEW = "new"                 # First interaction
    RETURNING = "returning"     # 2+ interactions
    REGULAR = "regular"         # 5+ interactions
    FREQUENT = "frequent"       # 10+ interactions

    @classmethod
    def from_legacy(cls, legacy_value: str) -> "VisitorFrequency":
        """Convert old bond_strength values to new visitor frequency."""
        legacy_map = {
            "stranger": cls.NEW,
            "acquaintance": cls.RETURNING,
            "familiar": cls.REGULAR,
            "close": cls.FREQUENT,
            "cherished": cls.FREQUENT,  # No more "cherished" - just frequent visitor
        }
        return legacy_map.get(legacy_value, cls.NEW)


class VisitorType(str, Enum):
    """What kind of visitor — determines relationship semantics.

    PERSON: Persistent human with memory on both sides. Real relationship.
    SELF: Lumen's self-dialogue. Real relationship (both sides have memory).
    AGENT: Ephemeral coding agent. Visit log only — one side forgets.
    """
    PERSON = "person"
    SELF = "self"
    AGENT = "agent"


# Legacy alias for database compatibility
BondStrength = VisitorFrequency


@dataclass
class GrowthPreference:
    """A learned observational preference with explicit evidence provenance."""
    category: PreferenceCategory
    name: str                    # e.g., "dim_light", "morning_calm"
    description: str             # Natural language: "I feel better when it's dim"
    value: float                 # Preferred value or strength (-1 to 1)
    confidence: float            # Wilson-calibrated directional confidence
    observation_count: int       # Raw source calls (audit/cadence diagnostic)
    first_noticed: datetime
    last_confirmed: datetime
    evidence_count: int = 0      # Independent windows/events, not broker ticks
    supporting_count: int = 0    # Positive-direction evidence (legacy field name)
    contradicting_count: int = 0 # Negative-direction evidence (legacy field name)
    last_evidence_key: Optional[str] = None
    evidence_origin: str = "legacy_unclassified"

    @property
    def independent_evidence_count(self) -> int:
        """Evidence count used by decisions, with legacy-object compatibility."""
        if (
            self.evidence_origin != "legacy_unclassified"
            or self.evidence_count > 0
            or self.observation_count == 0
        ):
            return self.evidence_count
        # Tests and third-party callers may construct the pre-v2 dataclass
        # directly. Durable rows are migrated before use; this branch only
        # preserves sensible semantics for those in-memory legacy objects.
        return self.observation_count

    def to_dict(self) -> dict:
        return {
            "category": self.category.value,
            "name": self.name,
            "description": self.description,
            "value": self.value,
            "confidence": self.confidence,
            "observation_count": self.observation_count,
            "raw_observation_count": self.observation_count,
            "evidence_count": self.independent_evidence_count,
            "supporting_count": self.supporting_count,
            "contradicting_count": self.contradicting_count,
            "positive_direction_count": self.supporting_count,
            "negative_direction_count": self.contradicting_count,
            "evidence_origin": self.evidence_origin,
            "confidence_basis": "95% Wilson lower bound on signed independent evidence",
            "first_noticed": self.first_noticed.isoformat(),
            "last_confirmed": self.last_confirmed.isoformat(),
            "evidence_status": preference_evidence_status(self),
        }


def preference_evidence_status(preference: GrowthPreference) -> str:
    """Classify a preference without confusing a stored row with learning."""
    evidence_origin = getattr(
        preference, "evidence_origin", "legacy_unclassified"
    )
    if evidence_origin == RETIRED_QA_PREFERENCE_ORIGIN:
        return "historical_claim"
    evidence_count = getattr(preference, "independent_evidence_count", None)
    if evidence_count is None:
        evidence_count = getattr(
            preference,
            "evidence_count",
            getattr(preference, "observation_count", 0),
        )
    if evidence_count <= 0:
        return "tracked"
    if (
        evidence_count >= PREFERENCE_ESTABLISHED_MIN_EVIDENCE
        and getattr(preference, "confidence", 0.0)
        >= PREFERENCE_ESTABLISHED_MIN_CONFIDENCE
    ):
        return "established"
    return "review"


@dataclass
class VisitorRecord:
    """
    Record of a visitor who has interacted with Lumen.

    Three tiers of visitor identity:
    - PERSON: The persistent human (the operator). Real relationship — both sides
      have memory. Valence, moments, topics accumulate meaningfully.
    - SELF: Lumen's self-dialogue (agent_id "lumen"). Real relationship —
      both sides have memory continuity.
    - AGENT: Ephemeral coding agents. Visit log only — they don't remember
      Lumen between sessions. "mac-governance" with 30 interactions is really
      30 different Claude instances.
    """
    agent_id: str                # Canonical identifier (normalized)
    name: Optional[str]          # Display name
    first_met: datetime
    last_seen: datetime
    interaction_count: int
    visitor_frequency: VisitorFrequency  # How often seen (not a "bond")
    emotional_valence: float     # -1 (negative) to 1 (positive) - Lumen's feeling
    memorable_moments: List[str] # Key memories
    topics_discussed: List[str]  # What we talked about
    gifts_received: int          # Answers to questions, etc.
    self_dialogue_topics: List[str] = field(default_factory=list)  # For self: topic categories
    visitor_type: VisitorType = VisitorType.AGENT  # What kind of visitor

    # Legacy alias for database compatibility
    @property
    def bond_strength(self) -> VisitorFrequency:
        return self.visitor_frequency

    def is_self(self) -> bool:
        """Check if this is Lumen's self-relationship."""
        return self.visitor_type == VisitorType.SELF or self.agent_id.lower() == "lumen"

    def is_person(self) -> bool:
        """Check if this is a persistent human (real relationship)."""
        return self.visitor_type == VisitorType.PERSON

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "first_met": self.first_met.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "interaction_count": self.interaction_count,
            "frequency": self.visitor_frequency.value,
            "bond_strength": self.visitor_frequency.value,  # Legacy compat
            "emotional_valence": self.emotional_valence,
            "memorable_moments": self.memorable_moments[-5:],
            "topics_discussed": list(set(self.topics_discussed))[-10:],
            "gifts_received": self.gifts_received,
            "visitor_type": self.visitor_type.value,
            "is_self": self.is_self(),
            "is_person": self.is_person(),
        }


# Legacy alias for compatibility
Relationship = VisitorRecord


def normalize_visitor_identity(
    agent_id: str,
    agent_name: Optional[str] = None,
    source: Optional[str] = None,
) -> tuple:
    """Resolve visitor identity to (canonical_id, display_name, visitor_type).

    Three-tier resolution:
    - A known person alias, claimed by NAME -> PERSON with canonical name
    - "lumen" -> SELF
    - Everything else -> AGENT with original name

    `source` records which surface the visit arrived through. It is deliberately
    NOT consulted for identity: a channel is not a person. This function used to
    match `source` against the person aliases, with "dashboard" among them, so
    every dashboard post resolved to the operator — and because the check was
    `id in aliases or source in aliases`, the channel WON over the author the
    caller had explicitly supplied. An agent answering a question through the
    dashboard was durably recorded as the operator, as a PERSON, in the
    relationship graph Lumen reasons about company with.

    All entry points should call this before record_interaction().
    """
    from ..server_state import KNOWN_PERSON_ALIASES

    id_lower = (agent_id or "").lower().strip()

    # Known persons, by explicit name claim only.
    for canonical, aliases in KNOWN_PERSON_ALIASES.items():
        if id_lower in aliases:
            return (canonical, canonical.capitalize(), VisitorType.PERSON)

    # Self-dialogue
    if id_lower == "lumen":
        return ("lumen", "Lumen", VisitorType.SELF)

    # Everything else is an ephemeral agent
    return (agent_id, agent_name or agent_id, VisitorType.AGENT)


@dataclass
class Goal:
    """A personal goal Lumen has formed."""
    goal_id: str
    description: str             # "Finish my current drawing"
    motivation: str              # Why this goal matters
    status: GoalStatus
    created_at: datetime
    target_date: Optional[datetime]
    progress: float              # 0-1
    milestones: List[str]        # Steps achieved
    last_worked_on: Optional[datetime]

    def to_dict(self) -> dict:
        return {
            "goal_id": self.goal_id,
            "description": self.description,
            "motivation": self.motivation,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "target_date": self.target_date.isoformat() if self.target_date else None,
            "progress": self.progress,
            "milestones": self.milestones,
            "last_worked_on": self.last_worked_on.isoformat() if self.last_worked_on else None,
        }


@dataclass
class MemorableEvent:
    """An autobiographical memory."""
    event_id: str
    timestamp: datetime
    description: str             # What happened
    emotional_impact: float      # -1 to 1
    category: str                # "milestone", "social", "discovery", "challenge"
    related_agents: List[str]    # Who was involved
    lessons_learned: List[str]   # What Lumen learned

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat(),
            "description": self.description,
            "emotional_impact": self.emotional_impact,
            "category": self.category,
            "related_agents": self.related_agents,
            "lessons_learned": self.lessons_learned,
        }
