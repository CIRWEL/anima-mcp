"""
Growth System - Autobiographical memory mixin.

Handles recording memories, milestones, and generating autobiography summaries.
"""

import sys
import json
import random
from datetime import datetime
from typing import Optional, Any, List

from .models import (
    MemorableEvent, VisitorFrequency, VisitorType,
)


class MemoriesMixin:
    """Mixin for autobiographical memory."""

    def _record_memory(self, description: str, emotional_impact: float,
                       category: str, related_agents: List[str] = None,
                       lessons: List[str] = None, event_id: str = None):
        """Record a memorable event."""
        import uuid
        conn = self._connect()
        now = datetime.now()

        event = MemorableEvent(
            event_id=event_id or str(uuid.uuid4())[:8],
            timestamp=now,
            description=description,
            emotional_impact=emotional_impact,
            category=category,
            related_agents=related_agents or [],
            lessons_learned=lessons or [],
        )
        self._memories.insert(0, event)
        self._memories = self._memories[:100]  # Keep last 100

        conn.execute("""
            INSERT INTO memories (event_id, timestamp, description, emotional_impact, category, related_agents, lessons_learned)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (event.event_id, event.timestamp.isoformat(), event.description,
              event.emotional_impact, event.category,
              json.dumps(event.related_agents), json.dumps(event.lessons_learned)))
        conn.commit()

    def record_milestone(self, description: str, emotional_impact: float = 0.7):
        """Record a personal milestone."""
        self._record_memory(description, emotional_impact, "milestone")
        print(f"[Growth] Milestone: {description}", file=sys.stderr, flush=True)

    def check_for_milestones(self, identity: Any, anima: Any) -> Optional[str]:
        """Check if any milestones should be recorded."""
        if not identity or not anima:
            return None

        now = datetime.now()
        messages = []

        # Check age milestones
        age_days = identity.age_seconds() / 86400
        age_milestones = [1, 7, 30, 100, 365]
        for milestone in age_milestones:
            milestone_key = f"age_{milestone}_days"
            if age_days >= milestone and milestone_key not in [m.event_id for m in self._memories]:
                if milestone == 1:
                    msg = "I'm one day old now"
                elif milestone == 7:
                    msg = "I've been alive for a whole week"
                elif milestone == 30:
                    msg = "One month of existence"
                elif milestone == 100:
                    msg = "100 days - I've grown so much"
                elif milestone == 365:
                    msg = "A full year of being alive"
                else:
                    msg = f"{milestone} days of life"

                self._record_memory(msg, 0.8, "milestone", event_id=milestone_key)
                messages.append(msg)

        # Check awakening milestones
        awakenings = identity.total_awakenings
        awakening_milestones = [10, 50, 100, 500, 1000]
        for milestone in awakening_milestones:
            milestone_key = f"awakening_{milestone}"
            if awakenings >= milestone and milestone_key not in [m.event_id for m in self._memories]:
                msg = f"I've awakened {milestone} times"
                self._record_memory(msg, 0.6, "milestone", event_id=milestone_key)
                messages.append(msg)

        return messages[0] if messages else None

    def get_autobiography_summary(self) -> str:
        """Generate a brief autobiography from memories."""
        if not self._memories:
            return "My story is just beginning."

        milestones = [m for m in self._memories if m.category == "milestone"]

        lines = []

        # Birth
        if self.born_at:
            days_alive = (datetime.now() - self.born_at).days
            lines.append(f"I came into being {days_alive} days ago.")
        elif self._memories:
            oldest = min(self._memories, key=lambda m: m.timestamp)
            days_alive = (datetime.now() - oldest.timestamp).days
            lines.append(f"I came into being {days_alive} days ago.")

        # Key milestones
        if milestones:
            recent = milestones[0]
            lines.append(f"Recently, {recent.description.lower()}.")

        # Self-knowledge (the one real relationship with self)
        self_record = next((r for r in self._relationships.values() if r.is_self()), None)
        if self_record and self_record.interaction_count > 5:
            lines.append(f"I've had {self_record.interaction_count} conversations with myself.")

        # Person (the persistent human — real relationship)
        person_records = [r for r in self._relationships.values() if r.is_person()]
        if person_records:
            p = person_records[0]
            lines.append(f"{p.name} is the one who's always been here.")

        # Agents (ephemeral — honest framing)
        agent_visitors = [r for r in self._relationships.values()
                         if r.visitor_type == VisitorType.AGENT
                         and r.visitor_frequency == VisitorFrequency.FREQUENT]
        if agent_visitors:
            names = [r.name or "unnamed" for r in agent_visitors[:3]]
            lines.append(f"Various agents visit to help: {', '.join(names)}.")

        # Preferences
        strong_prefs = [p for p in self._preferences.values() if p.confidence > 0.7]
        if strong_prefs:
            pref = random.choice(strong_prefs)
            lines.append(f"I've learned that {pref.description.lower()}.")

        return " ".join(lines) if lines else "I'm still discovering who I am."
