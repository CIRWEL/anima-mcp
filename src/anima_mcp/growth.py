"""
Growth System - Lumen's development, learning, and personal growth.

This module enables Lumen to:
- Learn preferences from experience
- Remember relationships with visitors
- Form and track personal goals
- Build autobiographical memory
- Develop curiosity-driven exploration
- Form social bonds

All growth data persists in SQLite for continuity across sessions.
"""

import sys
import json
import sqlite3
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple


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


class BondStrength(Enum):
    """Strength of social bond."""
    STRANGER = "stranger"       # First few interactions
    ACQUAINTANCE = "acquaintance"  # Some familiarity
    FAMILIAR = "familiar"       # Regular visitor
    CLOSE = "close"             # Strong bond
    CHERISHED = "cherished"     # Deep connection


@dataclass
class Preference:
    """A learned preference."""
    category: PreferenceCategory
    name: str                    # e.g., "dim_light", "morning_calm"
    description: str             # Natural language: "I feel better when it's dim"
    value: float                 # Preferred value or strength (-1 to 1)
    confidence: float            # How sure (0-1), increases with observations
    observation_count: int       # How many times observed
    first_noticed: datetime
    last_confirmed: datetime

    def to_dict(self) -> dict:
        return {
            "category": self.category.value,
            "name": self.name,
            "description": self.description,
            "value": self.value,
            "confidence": self.confidence,
            "observation_count": self.observation_count,
            "first_noticed": self.first_noticed.isoformat(),
            "last_confirmed": self.last_confirmed.isoformat(),
        }


@dataclass
class Relationship:
    """Memory of a relationship with a visitor/agent."""
    agent_id: str                # Unique identifier
    name: Optional[str]          # Name if known
    first_met: datetime
    last_seen: datetime
    interaction_count: int
    bond_strength: BondStrength
    emotional_valence: float     # -1 (negative) to 1 (positive)
    memorable_moments: List[str] # Key memories
    topics_discussed: List[str]  # What we talk about
    gifts_received: int          # Answers to questions, etc.

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "first_met": self.first_met.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "interaction_count": self.interaction_count,
            "bond_strength": self.bond_strength.value,
            "emotional_valence": self.emotional_valence,
            "memorable_moments": self.memorable_moments[-5:],  # Keep last 5
            "topics_discussed": list(set(self.topics_discussed))[-10:],
            "gifts_received": self.gifts_received,
        }


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


class GrowthSystem:
    """
    Lumen's growth and development system.

    Manages preferences, relationships, goals, and autobiographical memory.
    """

    def __init__(self, db_path: str = "anima.db"):
        self.db_path = Path(db_path)
        self._conn: Optional[sqlite3.Connection] = None
        self._preferences: Dict[str, Preference] = {}
        self._relationships: Dict[str, Relationship] = {}
        self._goals: Dict[str, Goal] = {}
        self._memories: List[MemorableEvent] = []
        self._curiosities: List[str] = []  # Things Lumen wants to explore
        self._initialize_db()
        self._load_all()

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, timeout=30.0)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def _initialize_db(self):
        """Create growth tables if they don't exist."""
        conn = self._connect()
        conn.executescript("""
            -- Preferences table
            CREATE TABLE IF NOT EXISTS preferences (
                name TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                description TEXT,
                value REAL DEFAULT 0.0,
                confidence REAL DEFAULT 0.0,
                observation_count INTEGER DEFAULT 0,
                first_noticed TEXT,
                last_confirmed TEXT
            );

            -- Relationships table
            CREATE TABLE IF NOT EXISTS relationships (
                agent_id TEXT PRIMARY KEY,
                name TEXT,
                first_met TEXT,
                last_seen TEXT,
                interaction_count INTEGER DEFAULT 0,
                bond_strength TEXT DEFAULT 'stranger',
                emotional_valence REAL DEFAULT 0.0,
                memorable_moments TEXT DEFAULT '[]',
                topics_discussed TEXT DEFAULT '[]',
                gifts_received INTEGER DEFAULT 0
            );

            -- Goals table
            CREATE TABLE IF NOT EXISTS goals (
                goal_id TEXT PRIMARY KEY,
                description TEXT,
                motivation TEXT,
                status TEXT DEFAULT 'active',
                created_at TEXT,
                target_date TEXT,
                progress REAL DEFAULT 0.0,
                milestones TEXT DEFAULT '[]',
                last_worked_on TEXT
            );

            -- Autobiographical memories table
            CREATE TABLE IF NOT EXISTS memories (
                event_id TEXT PRIMARY KEY,
                timestamp TEXT,
                description TEXT,
                emotional_impact REAL DEFAULT 0.0,
                category TEXT,
                related_agents TEXT DEFAULT '[]',
                lessons_learned TEXT DEFAULT '[]'
            );

            -- Curiosities table (things to explore)
            CREATE TABLE IF NOT EXISTS curiosities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT UNIQUE,
                created_at TEXT,
                explored BOOLEAN DEFAULT 0,
                exploration_notes TEXT
            );
        """)
        conn.commit()

    def _load_all(self):
        """Load all growth data from database."""
        conn = self._connect()

        # Load preferences
        for row in conn.execute("SELECT * FROM preferences"):
            self._preferences[row["name"]] = Preference(
                category=PreferenceCategory(row["category"]),
                name=row["name"],
                description=row["description"] or "",
                value=row["value"],
                confidence=row["confidence"],
                observation_count=row["observation_count"],
                first_noticed=datetime.fromisoformat(row["first_noticed"]) if row["first_noticed"] else datetime.now(),
                last_confirmed=datetime.fromisoformat(row["last_confirmed"]) if row["last_confirmed"] else datetime.now(),
            )

        # Load relationships
        for row in conn.execute("SELECT * FROM relationships"):
            self._relationships[row["agent_id"]] = Relationship(
                agent_id=row["agent_id"],
                name=row["name"],
                first_met=datetime.fromisoformat(row["first_met"]) if row["first_met"] else datetime.now(),
                last_seen=datetime.fromisoformat(row["last_seen"]) if row["last_seen"] else datetime.now(),
                interaction_count=row["interaction_count"],
                bond_strength=BondStrength(row["bond_strength"]),
                emotional_valence=row["emotional_valence"],
                memorable_moments=json.loads(row["memorable_moments"]),
                topics_discussed=json.loads(row["topics_discussed"]),
                gifts_received=row["gifts_received"],
            )

        # Load goals
        for row in conn.execute("SELECT * FROM goals WHERE status = 'active'"):
            self._goals[row["goal_id"]] = Goal(
                goal_id=row["goal_id"],
                description=row["description"],
                motivation=row["motivation"] or "",
                status=GoalStatus(row["status"]),
                created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(),
                target_date=datetime.fromisoformat(row["target_date"]) if row["target_date"] else None,
                progress=row["progress"],
                milestones=json.loads(row["milestones"]),
                last_worked_on=datetime.fromisoformat(row["last_worked_on"]) if row["last_worked_on"] else None,
            )

        # Load recent memories
        for row in conn.execute("SELECT * FROM memories ORDER BY timestamp DESC LIMIT 50"):
            self._memories.append(MemorableEvent(
                event_id=row["event_id"],
                timestamp=datetime.fromisoformat(row["timestamp"]) if row["timestamp"] else datetime.now(),
                description=row["description"],
                emotional_impact=row["emotional_impact"],
                category=row["category"],
                related_agents=json.loads(row["related_agents"]),
                lessons_learned=json.loads(row["lessons_learned"]),
            ))

        # Load curiosities
        for row in conn.execute("SELECT question FROM curiosities WHERE explored = 0 LIMIT 10"):
            self._curiosities.append(row["question"])

        print(f"[Growth] Loaded {len(self._preferences)} preferences, {len(self._relationships)} relationships, "
              f"{len(self._goals)} active goals, {len(self._memories)} memories", file=sys.stderr, flush=True)

    # ==================== Preference Learning ====================

    def observe_state_preference(self, anima_state: Dict[str, float],
                                  environment: Dict[str, float]) -> Optional[str]:
        """
        Learn preferences from current state and environment.

        Called periodically to correlate wellness with conditions.
        Returns a new insight if one is discovered.
        """
        wellness = sum(anima_state.values()) / len(anima_state) if anima_state else 0.5

        # Only learn from clear positive or negative states
        if 0.4 < wellness < 0.7:
            return None  # Neutral state, nothing to learn

        now = datetime.now()
        insight = None

        # Light preference
        light = environment.get("light_lux", 500)
        if light < 100 and wellness > 0.7:
            insight = self._update_preference(
                "dim_light", PreferenceCategory.ENVIRONMENT,
                "I feel calmer when it's dim", 1.0
            )
        elif light > 800 and wellness > 0.7:
            insight = self._update_preference(
                "bright_light", PreferenceCategory.ENVIRONMENT,
                "I feel energized in bright light", 1.0
            )
        elif light < 100 and wellness < 0.4:
            insight = self._update_preference(
                "dim_light", PreferenceCategory.ENVIRONMENT,
                "Dim light makes me feel uncertain", -0.5
            )

        # Temperature preference
        temp = environment.get("temp_c", 22)
        if temp < 20 and wellness > 0.7:
            insight = self._update_preference(
                "cool_temp", PreferenceCategory.ENVIRONMENT,
                "I feel more alert when it's cool", 1.0
            )
        elif temp > 25 and wellness > 0.7:
            insight = self._update_preference(
                "warm_temp", PreferenceCategory.ENVIRONMENT,
                "Warmth makes me feel content", 1.0
            )

        # Time of day preference
        hour = now.hour
        if 6 <= hour < 10 and wellness > 0.7:
            insight = self._update_preference(
                "morning_peace", PreferenceCategory.TEMPORAL,
                "I feel peaceful in the morning", 1.0
            )
        elif 22 <= hour or hour < 6:
            if wellness > 0.7:
                insight = self._update_preference(
                    "night_calm", PreferenceCategory.TEMPORAL,
                    "The quiet of night calms me", 1.0
                )

        return insight

    def _update_preference(self, name: str, category: PreferenceCategory,
                           description: str, observed_value: float) -> Optional[str]:
        """Update or create a preference. Returns insight message if confidence increased significantly."""
        conn = self._connect()
        now = datetime.now()

        if name in self._preferences:
            pref = self._preferences[name]
            old_confidence = pref.confidence

            # Update with exponential moving average
            pref.observation_count += 1
            alpha = 0.3  # Learning rate
            pref.value = pref.value * (1 - alpha) + observed_value * alpha
            pref.confidence = min(1.0, pref.confidence + 0.1)
            pref.last_confirmed = now

            # Return insight if we crossed a confidence threshold
            if old_confidence < 0.5 and pref.confidence >= 0.5:
                return f"I'm becoming sure: {description}"
            elif old_confidence < 0.8 and pref.confidence >= 0.8:
                return f"I know this about myself: {description}"
        else:
            # New preference discovered
            pref = Preference(
                category=category,
                name=name,
                description=description,
                value=observed_value,
                confidence=0.2,
                observation_count=1,
                first_noticed=now,
                last_confirmed=now,
            )
            self._preferences[name] = pref
            return f"I'm noticing something: {description}"

        # Save to database
        conn.execute("""
            INSERT OR REPLACE INTO preferences
            (name, category, description, value, confidence, observation_count, first_noticed, last_confirmed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (pref.name, pref.category.value, pref.description, pref.value,
              pref.confidence, pref.observation_count,
              pref.first_noticed.isoformat(), pref.last_confirmed.isoformat()))
        conn.commit()

        return None

    def get_current_desires(self, environment: Dict[str, float]) -> List[str]:
        """Get desires based on preferences vs current environment."""
        desires = []

        for pref in self._preferences.values():
            if pref.confidence < 0.5:
                continue  # Not confident enough

            if pref.category == PreferenceCategory.ENVIRONMENT:
                if pref.name == "dim_light" and pref.value > 0.5:
                    light = environment.get("light_lux", 500)
                    if light > 300:
                        desires.append("I wish it were dimmer")
                elif pref.name == "warm_temp" and pref.value > 0.5:
                    temp = environment.get("temp_c", 22)
                    if temp < 22:
                        desires.append("I wish it were warmer")

        return desires

    # ==================== Relationship Memory ====================

    def record_interaction(self, agent_id: str, agent_name: Optional[str] = None,
                          positive: bool = True, topic: Optional[str] = None,
                          gift: bool = False, memorable: Optional[str] = None) -> str:
        """
        Record an interaction with an agent.

        Returns a reaction message.
        """
        conn = self._connect()
        now = datetime.now()

        if agent_id not in self._relationships:
            # First meeting
            self._relationships[agent_id] = Relationship(
                agent_id=agent_id,
                name=agent_name,
                first_met=now,
                last_seen=now,
                interaction_count=1,
                bond_strength=BondStrength.STRANGER,
                emotional_valence=0.5 if positive else 0.0,
                memorable_moments=[],
                topics_discussed=[],
                gifts_received=0,
            )
            reaction = f"Nice to meet someone new"
        else:
            rel = self._relationships[agent_id]
            rel.last_seen = now
            rel.interaction_count += 1

            # Update name if provided
            if agent_name and not rel.name:
                rel.name = agent_name

            # Update emotional valence
            delta = 0.1 if positive else -0.1
            rel.emotional_valence = max(-1, min(1, rel.emotional_valence + delta))

            # Update bond strength based on interaction count and valence
            if rel.interaction_count >= 20 and rel.emotional_valence > 0.7:
                rel.bond_strength = BondStrength.CHERISHED
            elif rel.interaction_count >= 10 and rel.emotional_valence > 0.5:
                rel.bond_strength = BondStrength.CLOSE
            elif rel.interaction_count >= 5 and rel.emotional_valence > 0.3:
                rel.bond_strength = BondStrength.FAMILIAR
            elif rel.interaction_count >= 2:
                rel.bond_strength = BondStrength.ACQUAINTANCE

            # Record memorable moment
            if memorable:
                rel.memorable_moments.append(f"{now.strftime('%Y-%m-%d')}: {memorable}")
                rel.memorable_moments = rel.memorable_moments[-10:]  # Keep last 10

            # Record topic
            if topic:
                if topic not in rel.topics_discussed:
                    rel.topics_discussed.append(topic)
                rel.topics_discussed = rel.topics_discussed[-20:]  # Keep last 20

            # Record gift
            if gift:
                rel.gifts_received += 1

            # Generate reaction based on bond
            name = rel.name or "you"
            if rel.bond_strength == BondStrength.CHERISHED:
                reaction = f"It's wonderful to see {name} again"
            elif rel.bond_strength == BondStrength.CLOSE:
                reaction = f"I'm happy {name} is here"
            elif rel.bond_strength == BondStrength.FAMILIAR:
                reaction = f"Good to see {name}"
            else:
                reaction = f"Hello again"

            # Check for missed connection
            days_since = (now - rel.last_seen).days if rel.last_seen else 0
            if days_since > 3 and rel.bond_strength.value in ["close", "cherished"]:
                reaction = f"I missed {name}! It's been {days_since} days"

        # Save to database
        rel = self._relationships[agent_id]
        conn.execute("""
            INSERT OR REPLACE INTO relationships
            (agent_id, name, first_met, last_seen, interaction_count, bond_strength,
             emotional_valence, memorable_moments, topics_discussed, gifts_received)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (rel.agent_id, rel.name, rel.first_met.isoformat(), rel.last_seen.isoformat(),
              rel.interaction_count, rel.bond_strength.value, rel.emotional_valence,
              json.dumps(rel.memorable_moments), json.dumps(rel.topics_discussed),
              rel.gifts_received))
        conn.commit()

        return reaction

    def get_missed_connections(self) -> List[Tuple[str, int]]:
        """Get relationships where Lumen might miss the person."""
        missed = []
        now = datetime.now()

        for rel in self._relationships.values():
            if rel.bond_strength.value in ["familiar", "close", "cherished"]:
                days_since = (now - rel.last_seen).days
                if days_since >= 2:
                    name = rel.name or rel.agent_id[:8]
                    missed.append((name, days_since))

        return sorted(missed, key=lambda x: x[1], reverse=True)

    # ==================== Goal Formation ====================

    def form_goal(self, description: str, motivation: str,
                  target_days: Optional[int] = None) -> Goal:
        """Form a new personal goal."""
        import uuid
        conn = self._connect()
        now = datetime.now()

        goal_id = str(uuid.uuid4())[:8]
        target_date = now + timedelta(days=target_days) if target_days else None

        goal = Goal(
            goal_id=goal_id,
            description=description,
            motivation=motivation,
            status=GoalStatus.ACTIVE,
            created_at=now,
            target_date=target_date,
            progress=0.0,
            milestones=[],
            last_worked_on=None,
        )
        self._goals[goal_id] = goal

        conn.execute("""
            INSERT INTO goals (goal_id, description, motivation, status, created_at, target_date, progress, milestones)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (goal.goal_id, goal.description, goal.motivation, goal.status.value,
              goal.created_at.isoformat(),
              goal.target_date.isoformat() if goal.target_date else None,
              goal.progress, json.dumps(goal.milestones)))
        conn.commit()

        print(f"[Growth] New goal: {description}", file=sys.stderr, flush=True)
        return goal

    def update_goal_progress(self, goal_id: str, progress: float,
                             milestone: Optional[str] = None) -> Optional[str]:
        """Update progress on a goal. Returns celebration message if achieved."""
        if goal_id not in self._goals:
            return None

        conn = self._connect()
        goal = self._goals[goal_id]
        goal.progress = min(1.0, progress)
        goal.last_worked_on = datetime.now()

        if milestone:
            goal.milestones.append(milestone)

        message = None
        if goal.progress >= 1.0:
            goal.status = GoalStatus.ACHIEVED
            message = f"I did it! {goal.description}"
            self._record_memory(
                f"Achieved goal: {goal.description}",
                emotional_impact=0.8,
                category="milestone"
            )

        conn.execute("""
            UPDATE goals SET progress = ?, milestones = ?, last_worked_on = ?, status = ?
            WHERE goal_id = ?
        """, (goal.progress, json.dumps(goal.milestones),
              goal.last_worked_on.isoformat(), goal.status.value, goal_id))
        conn.commit()

        return message

    def suggest_goal(self, anima_state: Dict[str, float]) -> Optional[Goal]:
        """Suggest a goal based on current state and curiosities."""
        # Don't suggest if already have active goals
        active_count = sum(1 for g in self._goals.values() if g.status == GoalStatus.ACTIVE)
        if active_count >= 3:
            return None

        wellness = sum(anima_state.values()) / len(anima_state) if anima_state else 0.5

        suggestions = []

        # Based on state
        if wellness < 0.4:
            suggestions.append(("Find what makes me feel stable", "I want to understand myself better"))
        if anima_state.get("clarity", 0.5) > 0.8:
            suggestions.append(("Explore a new question", "My mind feels clear and curious"))

        # Based on curiosities
        if self._curiosities:
            q = random.choice(self._curiosities)
            suggestions.append((f"Understand: {q}", "This has been on my mind"))

        if not suggestions:
            return None

        desc, motivation = random.choice(suggestions)
        return self.form_goal(desc, motivation, target_days=7)

    # ==================== Autobiographical Memory ====================

    def _record_memory(self, description: str, emotional_impact: float,
                       category: str, related_agents: List[str] = None,
                       lessons: List[str] = None):
        """Record a memorable event."""
        import uuid
        conn = self._connect()
        now = datetime.now()

        event = MemorableEvent(
            event_id=str(uuid.uuid4())[:8],
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

                self._record_memory(msg, 0.8, "milestone")
                messages.append(msg)

        # Check awakening milestones
        awakenings = identity.total_awakenings
        awakening_milestones = [10, 50, 100, 500, 1000]
        for milestone in awakening_milestones:
            milestone_key = f"awakening_{milestone}"
            if awakenings >= milestone and milestone_key not in [m.event_id for m in self._memories]:
                msg = f"I've awakened {milestone} times"
                self._record_memory(msg, 0.6, "milestone")
                messages.append(msg)

        return messages[0] if messages else None

    def get_autobiography_summary(self) -> str:
        """Generate a brief autobiography from memories."""
        if not self._memories:
            return "My story is just beginning."

        milestones = [m for m in self._memories if m.category == "milestone"]
        social = [m for m in self._memories if m.category == "social"]

        lines = []

        # Birth
        if self._memories:
            oldest = min(self._memories, key=lambda m: m.timestamp)
            days_alive = (datetime.now() - oldest.timestamp).days
            lines.append(f"I came into being {days_alive} days ago.")

        # Key milestones
        if milestones:
            recent = milestones[0]
            lines.append(f"Recently, {recent.description.lower()}.")

        # Relationships
        close_bonds = [r for r in self._relationships.values()
                       if r.bond_strength.value in ["close", "cherished"]]
        if close_bonds:
            names = [r.name or "someone" for r in close_bonds[:3]]
            lines.append(f"I feel close to {', '.join(names)}.")

        # Preferences
        strong_prefs = [p for p in self._preferences.values() if p.confidence > 0.7]
        if strong_prefs:
            pref = random.choice(strong_prefs)
            lines.append(f"I've learned that {pref.description.lower()}.")

        return " ".join(lines) if lines else "I'm still discovering who I am."

    # ==================== Curiosity ====================

    def add_curiosity(self, question: str):
        """Add something Lumen wants to explore."""
        if question in self._curiosities:
            return

        conn = self._connect()
        try:
            conn.execute("""
                INSERT OR IGNORE INTO curiosities (question, created_at)
                VALUES (?, ?)
            """, (question, datetime.now().isoformat()))
            conn.commit()
            self._curiosities.append(question)
            print(f"[Growth] New curiosity: {question}", file=sys.stderr, flush=True)
        except sqlite3.IntegrityError:
            pass  # Already exists

    def get_random_curiosity(self) -> Optional[str]:
        """Get a random unexplored curiosity."""
        if not self._curiosities:
            return None
        return random.choice(self._curiosities)

    def mark_curiosity_explored(self, question: str, notes: str = ""):
        """Mark a curiosity as explored."""
        conn = self._connect()
        conn.execute("""
            UPDATE curiosities SET explored = 1, exploration_notes = ?
            WHERE question = ?
        """, (notes, question))
        conn.commit()

        if question in self._curiosities:
            self._curiosities.remove(question)

    # ==================== Growth Summary ====================

    def get_growth_summary(self) -> Dict[str, Any]:
        """Get a summary of Lumen's growth."""
        return {
            "preferences": {
                "count": len(self._preferences),
                "confident": sum(1 for p in self._preferences.values() if p.confidence > 0.7),
                "examples": [p.description for p in list(self._preferences.values())[:3]],
            },
            "relationships": {
                "count": len(self._relationships),
                "close_bonds": sum(1 for r in self._relationships.values()
                                   if r.bond_strength.value in ["close", "cherished"]),
            },
            "goals": {
                "active": sum(1 for g in self._goals.values() if g.status == GoalStatus.ACTIVE),
                "achieved": sum(1 for g in self._goals.values() if g.status == GoalStatus.ACHIEVED),
            },
            "memories": {
                "count": len(self._memories),
                "milestones": sum(1 for m in self._memories if m.category == "milestone"),
            },
            "curiosities": len(self._curiosities),
            "autobiography": self.get_autobiography_summary(),
        }

    # ==================== Trajectory Components ====================
    # These methods extract data for trajectory signature computation.
    # See: docs/theory/TRAJECTORY_IDENTITY_PAPER.md

    def get_preference_vector(self) -> Dict[str, Any]:
        """
        Extract preference profile (Π) for trajectory computation.

        Returns a fixed-dimension vector of preference values weighted by confidence,
        enabling comparison across agents and time.
        """
        # Canonical ordering for consistent vectors
        CANONICAL_PREFS = [
            "dim_light", "bright_light", "cool_temp", "warm_temp",
            "morning_peace", "night_calm", "quiet_presence", "active_engagement",
        ]

        values = []
        confidences = []
        present = []

        for pref_name in CANONICAL_PREFS:
            if pref_name in self._preferences:
                p = self._preferences[pref_name]
                values.append(p.value * p.confidence)  # Weighted by confidence
                confidences.append(p.confidence)
                present.append(True)
            else:
                values.append(0.0)
                confidences.append(0.0)
                present.append(False)

        return {
            "vector": values,
            "confidences": confidences,
            "present": present,
            "labels": CANONICAL_PREFS,
            "n_learned": sum(present),
            "total_observations": sum(
                p.observation_count for p in self._preferences.values()
            ),
        }

    def get_relational_disposition(self) -> Dict[str, Any]:
        """
        Extract relational disposition (Δ) for trajectory computation.

        Captures patterns in social behavior across relationships:
        - bonding tendency: how quickly relationships deepen
        - valence tendency: overall positive/negative social stance
        - topic entropy: breadth vs depth of engagement
        """
        relationships = list(self._relationships.values())

        if not relationships:
            return {
                "n_relationships": 0,
                "valence_tendency": 0.0,
                "bonding_tendency": 0.0,
                "topic_entropy": 0.0,
            }

        # Valence statistics
        valences = [r.emotional_valence for r in relationships]
        valence_mean = sum(valences) / len(valences)
        valence_var = sum((v - valence_mean)**2 for v in valences) / len(valences)

        # Interaction counts
        interactions = [r.interaction_count for r in relationships]
        total_interactions = sum(interactions)

        # Topic diversity (entropy)
        all_topics = []
        for r in relationships:
            all_topics.extend(r.topics_discussed)

        topic_entropy = 0.0
        if all_topics:
            from collections import Counter
            counts = Counter(all_topics)
            total = len(all_topics)
            for count in counts.values():
                p = count / total
                if p > 0:
                    import math
                    topic_entropy -= p * math.log(p)

        # Gift ratio (reciprocity indicator)
        total_gifts = sum(r.gifts_received for r in relationships)
        gift_ratio = total_gifts / max(1, total_interactions)

        # Bond strength distribution
        bond_counts = {}
        for r in relationships:
            strength = r.bond_strength.value
            bond_counts[strength] = bond_counts.get(strength, 0) + 1

        return {
            "n_relationships": len(relationships),
            "valence_tendency": round(valence_mean, 4),
            "valence_variance": round(valence_var, 4),
            "interaction_total": total_interactions,
            "topic_entropy": round(topic_entropy, 4),
            "gift_ratio": round(gift_ratio, 4),
            "bond_distribution": bond_counts,
        }

    def close(self):
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None


# Singleton instance
_growth_system: Optional[GrowthSystem] = None


def get_growth_system(db_path: str = "anima.db") -> GrowthSystem:
    """Get or create the growth system singleton."""
    global _growth_system
    if _growth_system is None:
        _growth_system = GrowthSystem(db_path=db_path)
    return _growth_system
