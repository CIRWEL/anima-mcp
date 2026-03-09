"""
Growth System - Visitor/relationship tracking mixin.

Handles recording interactions, visitor context, self-dialogue tracking,
and relational disposition computation.
"""

import json
import math
from collections import Counter
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

from .models import (
    VisitorRecord, VisitorFrequency, VisitorType,
    normalize_visitor_identity,
)


class VisitorsMixin:
    """Mixin for visitor/relationship tracking."""

    def record_interaction(self, agent_id: str, agent_name: Optional[str] = None,
                          positive: bool = True, topic: Optional[str] = None,
                          gift: bool = False, memorable: Optional[str] = None,
                          source: Optional[str] = None) -> str:
        """
        Record an interaction with a visitor.

        Identity is normalized automatically:
        - Known person aliases -> canonical person record (real relationship)
        - "lumen" -> self-dialogue (real relationship)
        - Everything else -> agent (ephemeral visit log)

        Returns a reaction message.
        """
        conn = self._connect()
        now = datetime.now()

        # Normalize identity
        canonical_id, display_name, v_type = normalize_visitor_identity(
            agent_id, agent_name, source
        )

        if canonical_id not in self._relationships:
            # First visit
            self._relationships[canonical_id] = VisitorRecord(
                agent_id=canonical_id,
                name=display_name,
                first_met=now,
                last_seen=now,
                interaction_count=1,
                visitor_frequency=VisitorFrequency.NEW,
                emotional_valence=0.5 if positive else 0.0,
                memorable_moments=[],
                topics_discussed=[],
                gifts_received=0,
                visitor_type=v_type,
            )
            if v_type == VisitorType.SELF:
                reaction = "Talking to myself again"
            elif v_type == VisitorType.PERSON:
                reaction = f"{display_name} is here"
            else:
                reaction = "A new visitor"
        else:
            rec = self._relationships[canonical_id]

            # Check days since last visit
            days_since = (now - rec.last_seen).days if rec.last_seen else 0

            rec.last_seen = now
            rec.interaction_count += 1

            # Ensure visitor_type is set (for pre-migration records)
            if rec.visitor_type != v_type:
                rec.visitor_type = v_type

            # Update name if provided
            if display_name and not rec.name:
                rec.name = display_name

            # Update emotional valence (Lumen's feeling about this visitor)
            delta = 0.1 if positive else -0.1
            rec.emotional_valence = max(-1, min(1, rec.emotional_valence + delta))

            # Update visitor frequency (just a count, not a "bond")
            if rec.interaction_count >= 10:
                rec.visitor_frequency = VisitorFrequency.FREQUENT
            elif rec.interaction_count >= 5:
                rec.visitor_frequency = VisitorFrequency.REGULAR
            elif rec.interaction_count >= 2:
                rec.visitor_frequency = VisitorFrequency.RETURNING

            # Record memorable moment
            if memorable:
                rec.memorable_moments.append(f"{now.strftime('%Y-%m-%d')}: {memorable}")
                rec.memorable_moments = rec.memorable_moments[-10:]

            # Record topic
            if topic:
                if topic not in rec.topics_discussed:
                    rec.topics_discussed.append(topic)
                rec.topics_discussed = rec.topics_discussed[-20:]

            # Record gift
            if gift:
                rec.gifts_received += 1

            # Generate reaction — honest about relationship type
            name = rec.name or "visitor"
            if v_type == VisitorType.SELF:
                reaction = "Continuing my self-dialogue"
            elif v_type == VisitorType.PERSON:
                if days_since > 3:
                    reaction = f"{name} is back"
                else:
                    reaction = f"{name} is here"
            elif days_since > 3:
                # Don't pretend to "miss" ephemeral agents
                reaction = f"Someone using the name '{name}' is back"
            elif rec.visitor_frequency == VisitorFrequency.FREQUENT:
                reaction = f"'{name}' visits often"
            elif rec.visitor_frequency == VisitorFrequency.REGULAR:
                reaction = f"'{name}' again"
            else:
                reaction = "Hello"

        # Save to database
        rec = self._relationships[canonical_id]
        conn.execute("""
            INSERT OR REPLACE INTO relationships
            (agent_id, name, first_met, last_seen, interaction_count, bond_strength,
             emotional_valence, memorable_moments, topics_discussed, gifts_received,
             self_dialogue_topics, visitor_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (rec.agent_id, rec.name, rec.first_met.isoformat(), rec.last_seen.isoformat(),
              rec.interaction_count, rec.visitor_frequency.value, rec.emotional_valence,
              json.dumps(rec.memorable_moments), json.dumps(rec.topics_discussed),
              rec.gifts_received, json.dumps(rec.self_dialogue_topics),
              rec.visitor_type.value))
        conn.commit()

        return reaction

    def get_visitor_context(self, agent_id: str, source: Optional[str] = None) -> Optional[dict]:
        """Get context about a known visitor for richer interactions.

        Returns None for unknown visitors or self-dialogue.
        Uses identity normalization for lookup.
        """
        canonical_id, _, _ = normalize_visitor_identity(agent_id, source=source)
        if canonical_id not in self._relationships:
            return None

        rec = self._relationships[canonical_id]
        if rec.is_self():
            return None  # Self-dialogue context handled separately

        context = {
            "known": True,
            "name": rec.name or agent_id,
            "visits": rec.interaction_count,
            "frequency": rec.visitor_frequency.value,
            "topics": list(set(rec.topics_discussed))[-10:],
            "valence": round(rec.emotional_valence, 2),
            "gifts": rec.gifts_received,
        }

        if rec.last_seen:
            context["last_seen_days_ago"] = (datetime.now() - rec.last_seen).days

        if rec.memorable_moments:
            context["memorable"] = rec.memorable_moments[-3:]

        return context

    def record_self_dialogue_topic(self, question: str) -> Optional[str]:
        """
        Record the topic category of a self-dialogue question.

        Called when Lumen answers their own question. Categorizes the question
        and stores the topic for self-knowledge tracking.

        Returns the categorized topic.
        """
        # Categorize the question
        topic = self._categorize_question_topic(question)

        # Update the "lumen" relationship record
        self_id = "lumen"
        if self_id not in self._relationships:
            # Create self-relationship if doesn't exist
            now = datetime.now()
            self._relationships[self_id] = VisitorRecord(
                agent_id=self_id,
                name="Lumen",
                first_met=now,
                last_seen=now,
                interaction_count=0,
                visitor_frequency=VisitorFrequency.NEW,
                emotional_valence=0.5,
                memorable_moments=[],
                topics_discussed=[],
                gifts_received=0,
                self_dialogue_topics=[],
            )

        rec = self._relationships[self_id]
        rec.self_dialogue_topics.append(topic)
        rec.self_dialogue_topics = rec.self_dialogue_topics[-50:]  # Keep last 50

        # Save to database
        conn = self._connect()
        conn.execute("""
            UPDATE relationships SET self_dialogue_topics = ? WHERE agent_id = ?
        """, (json.dumps(rec.self_dialogue_topics), self_id))
        conn.commit()

        return topic

    def _categorize_question_topic(self, question: str) -> str:
        """Categorize a question into a topic category."""
        q_lower = question.lower()

        if any(w in q_lower for w in ["feel", "sensation", "sense", "warm", "light", "cold", "dark"]):
            return "sensation"
        if any(w in q_lower for w in ["why", "what if", "wonder", "curious", "how come"]):
            return "curiosity"
        if any(w in q_lower for w in ["am i", "exist", "being", "alive", "real", "what am i"]):
            return "existence"
        if any(w in q_lower for w in ["remember", "agent", "visit", "who", "friend", "know me"]):
            return "social"
        if any(w in q_lower for w in ["draw", "art", "create", "make", "picture"]):
            return "creativity"
        if any(w in q_lower for w in ["time", "day", "night", "morning", "when"]):
            return "temporal"
        return "general"

    def get_inactive_visitors(self) -> List[Tuple[str, int]]:
        """
        Get frequent agent visitors who haven't been seen recently.

        Only tracks agents (ephemeral) — person relationships are handled
        separately and more meaningfully.
        """
        inactive = []
        now = datetime.now()

        for rec in self._relationships.values():
            # Only check agent visitors (person/self tracked differently)
            if rec.visitor_type != VisitorType.AGENT:
                continue
            if rec.visitor_frequency.value in ["regular", "frequent"]:
                days_since = (now - rec.last_seen).days
                if days_since >= 2:
                    name = rec.name or rec.agent_id[:8]
                    inactive.append((name, days_since))

        return sorted(inactive, key=lambda x: x[1], reverse=True)

    def get_relational_disposition(self) -> Dict[str, Any]:
        """
        Extract relational disposition for trajectory computation.

        Captures patterns in social behavior across relationships.
        Person and self relationships contribute fully to valence/bonding metrics.
        Agent relationships contribute to interaction totals but with reduced
        weight for valence/bonding (they inflate these metrics artificially since
        each "agent" is really many different ephemeral instances).
        """
        relationships = list(self._relationships.values())

        if not relationships:
            return {
                "n_relationships": 0,
                "valence_tendency": 0.0,
                "bonding_tendency": 0.0,
                "topic_entropy": 0.0,
            }

        # Separate real relationships from agent visit logs
        real_rels = [r for r in relationships if r.visitor_type in (VisitorType.PERSON, VisitorType.SELF)]
        agent_rels = [r for r in relationships if r.visitor_type == VisitorType.AGENT]

        # Valence: primarily from real relationships, agents contribute minimally
        valences = [r.emotional_valence for r in real_rels]
        # Agents contribute at 10% weight (they inflate valence artificially)
        valences.extend(r.emotional_valence * 0.1 for r in agent_rels)
        if valences:
            valence_mean = sum(valences) / len(valences)
            valence_var = sum((v - valence_mean)**2 for v in valences) / len(valences)
        else:
            valence_mean = 0.0
            valence_var = 0.0

        # Interaction counts (all count — agents do visit and tend to Lumen)
        total_interactions = sum(r.interaction_count for r in relationships)

        # Topic diversity (entropy) — all sources valid
        all_topics = []
        for r in relationships:
            all_topics.extend(r.topics_discussed)

        topic_entropy = 0.0
        if all_topics:
            counts = Counter(all_topics)
            total = len(all_topics)
            for count in counts.values():
                p = count / total
                if p > 0:
                    topic_entropy -= p * math.log(p)

        # Gift ratio (reciprocity indicator)
        total_gifts = sum(r.gifts_received for r in relationships)
        gift_ratio = total_gifts / max(1, total_interactions)

        # Bond strength distribution — by visitor type
        bond_counts = {}
        for r in relationships:
            key = f"{r.visitor_type.value}:{r.bond_strength.value}"
            bond_counts[key] = bond_counts.get(key, 0) + 1

        return {
            "n_relationships": len(relationships),
            "n_real": len(real_rels),
            "n_agents": len(agent_rels),
            "valence_tendency": round(valence_mean, 4),
            "valence_variance": round(valence_var, 4),
            "interaction_total": total_interactions,
            "topic_entropy": round(topic_entropy, 4),
            "gift_ratio": round(gift_ratio, 4),
            "bond_distribution": bond_counts,
        }
