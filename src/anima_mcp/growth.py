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
import re
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
class VisitorRecord:
    """
    Record of a visitor who has interacted with Lumen.

    Three tiers of visitor identity:
    - PERSON: The persistent human (Kenny). Real relationship — both sides
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
) -> Tuple[str, str, VisitorType]:
    """Resolve visitor identity to (canonical_id, display_name, visitor_type).

    Three-tier resolution:
    - Known person aliases (or dashboard source) → PERSON with canonical name
    - "lumen" → SELF
    - Everything else → AGENT with original name

    All entry points should call this before record_interaction().
    """
    from .server_state import KNOWN_PERSON_ALIASES

    id_lower = (agent_id or "").lower().strip()
    source_lower = (source or "").lower().strip()

    # Check known persons (by alias match or source match)
    for canonical, aliases in KNOWN_PERSON_ALIASES.items():
        if id_lower in aliases or source_lower in aliases:
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
        self.born_at: Optional[datetime] = None  # Set from identity after wake()
        self._drawings_observed: int = 0
        self._initialize_db()
        self._load_all()
        self._migrate_raw_lux_preferences()

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            # check_same_thread=False: growth singleton created on main thread,
            # but canvas_save calls observe_drawing from display thread.
            # Safe because WAL mode + serialized access (no concurrent writes).
            self._conn = sqlite3.connect(self.db_path, timeout=5.0, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")  # 5 seconds
            self._conn.execute("PRAGMA read_uncommitted=1")  # Better concurrency with WAL
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
                gifts_received INTEGER DEFAULT 0,
                self_dialogue_topics TEXT DEFAULT '[]'
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

        # Migration: add columns that may be missing from older DBs
        # (CREATE TABLE IF NOT EXISTS won't add new columns to existing tables)
        migrations = [
            ("relationships", "self_dialogue_topics", "TEXT DEFAULT '[]'"),
            ("relationships", "visitor_type", "TEXT DEFAULT 'agent'"),
        ]
        for table, column, col_type in migrations:
            try:
                conn.execute(f"SELECT {column} FROM {table} LIMIT 1")
            except sqlite3.OperationalError:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                conn.commit()

        # Identity migration: merge fragmented person records, set visitor_types
        self._run_identity_migration(conn)

    def _run_identity_migration(self, conn: sqlite3.Connection):
        """One-time migration: merge person aliases, set visitor_types.

        Uses PRAGMA user_version to track whether migration has already run.
        """
        from .server_state import KNOWN_PERSON_ALIASES

        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version >= 1:
            return  # Already migrated

        print("[Growth] Running identity migration v1...", file=sys.stderr, flush=True)

        # 1. Set "lumen" visitor_type = "self"
        conn.execute("UPDATE relationships SET visitor_type = 'self' WHERE LOWER(agent_id) = 'lumen'")

        # 2. Merge person alias records for each known person
        for canonical, aliases in KNOWN_PERSON_ALIASES.items():
            # Find all rows that match any alias (case-insensitive)
            placeholders = ",".join("?" for _ in aliases)
            alias_list = [a.lower() for a in aliases]
            rows = conn.execute(
                f"SELECT * FROM relationships WHERE LOWER(agent_id) IN ({placeholders})",
                alias_list
            ).fetchall()

            if not rows:
                continue

            # Merge data from all alias rows
            total_interactions = sum(r["interaction_count"] for r in rows)
            first_met_dates = [r["first_met"] for r in rows if r["first_met"]]
            last_seen_dates = [r["last_seen"] for r in rows if r["last_seen"]]
            all_moments = []
            all_topics = []
            total_gifts = 0
            weighted_valence = 0.0
            total_weight = 0

            for r in rows:
                try:
                    all_moments.extend(json.loads(r["memorable_moments"]) if r["memorable_moments"] else [])
                except (json.JSONDecodeError, TypeError):
                    pass
                try:
                    all_topics.extend(json.loads(r["topics_discussed"]) if r["topics_discussed"] else [])
                except (json.JSONDecodeError, TypeError):
                    pass
                total_gifts += r["gifts_received"] or 0
                count = r["interaction_count"] or 1
                weighted_valence += r["emotional_valence"] * count
                total_weight += count

            avg_valence = weighted_valence / max(1, total_weight)
            earliest_met = min(first_met_dates) if first_met_dates else datetime.now().isoformat()
            latest_seen = max(last_seen_dates) if last_seen_dates else datetime.now().isoformat()
            unique_moments = list(dict.fromkeys(all_moments))[-10:]  # Dedupe, keep last 10
            unique_topics = list(set(all_topics))

            # Determine frequency from merged interaction count
            if total_interactions >= 10:
                freq = "frequent"
            elif total_interactions >= 5:
                freq = "regular"
            elif total_interactions >= 2:
                freq = "returning"
            else:
                freq = "new"

            # Delete all alias rows
            conn.execute(
                f"DELETE FROM relationships WHERE LOWER(agent_id) IN ({placeholders})",
                alias_list
            )

            # Insert merged canonical record
            conn.execute("""
                INSERT INTO relationships
                    (agent_id, name, first_met, last_seen, interaction_count,
                     bond_strength, emotional_valence, memorable_moments,
                     topics_discussed, gifts_received, self_dialogue_topics, visitor_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', 'person')
            """, (
                canonical,
                canonical.capitalize(),
                earliest_met,
                latest_seen,
                total_interactions,
                freq,
                round(avg_valence, 2),
                json.dumps(unique_moments),
                json.dumps(unique_topics),
                total_gifts,
            ))

            print(f"[Growth] Merged {len(rows)} alias records into '{canonical}' "
                  f"(interactions={total_interactions}, gifts={total_gifts})",
                  file=sys.stderr, flush=True)

        # 3. All remaining records without visitor_type stay as "agent" (default)
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
        print("[Growth] Identity migration v1 complete.", file=sys.stderr, flush=True)

    def _load_all(self):
        """Load all growth data from database."""
        conn = self._connect()

        # Load preferences
        for row in conn.execute("SELECT * FROM preferences"):
            try:
                cat = PreferenceCategory(row["category"])
            except ValueError:
                continue  # Skip system/sentinel rows with non-enum categories
            self._preferences[row["name"]] = Preference(
                category=cat,
                name=row["name"],
                description=row["description"] or "",
                value=row["value"],
                confidence=row["confidence"],
                observation_count=row["observation_count"],
                first_noticed=datetime.fromisoformat(row["first_noticed"]) if row["first_noticed"] else datetime.now(),
                last_confirmed=datetime.fromisoformat(row["last_confirmed"]) if row["last_confirmed"] else datetime.now(),
            )

        # Load visitor records (legacy: "relationships")
        for row in conn.execute("SELECT * FROM relationships"):
            # Handle legacy bond_strength values
            legacy_bond = row["bond_strength"]
            try:
                freq = VisitorFrequency(legacy_bond)
            except ValueError:
                freq = VisitorFrequency.from_legacy(legacy_bond)

            # Handle self_dialogue_topics column (may not exist in old DBs)
            try:
                self_topics = json.loads(row["self_dialogue_topics"]) if row["self_dialogue_topics"] else []
            except (KeyError, TypeError, IndexError):
                self_topics = []

            # Handle visitor_type column (may not exist in old DBs)
            try:
                v_type = VisitorType(row["visitor_type"]) if row["visitor_type"] else VisitorType.AGENT
            except (KeyError, TypeError, ValueError):
                v_type = VisitorType.AGENT

            self._relationships[row["agent_id"]] = VisitorRecord(
                agent_id=row["agent_id"],
                name=row["name"],
                first_met=datetime.fromisoformat(row["first_met"]) if row["first_met"] else datetime.now(),
                last_seen=datetime.fromisoformat(row["last_seen"]) if row["last_seen"] else datetime.now(),
                interaction_count=row["interaction_count"],
                visitor_frequency=freq,
                emotional_valence=row["emotional_valence"],
                memorable_moments=json.loads(row["memorable_moments"]),
                topics_discussed=json.loads(row["topics_discussed"]),
                gifts_received=row["gifts_received"],
                self_dialogue_topics=self_topics,
                visitor_type=v_type,
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

        # Restore drawings counter from milestone memories to avoid duplicates after restart.
        # Milestone descriptions look like "Saved my 1st drawing" or "Saved my 10th drawing".
        for row in conn.execute(
            "SELECT description FROM memories WHERE category = 'milestone' "
            "AND description LIKE 'Saved my %drawing%'"
        ):
            m = re.search(r'Saved my (\d+)', row["description"])
            if m:
                count = int(m.group(1))
                if count > self._drawings_observed:
                    self._drawings_observed = count

        print(f"[Growth] Loaded {len(self._preferences)} preferences, {len(self._relationships)} relationships, "
              f"{len(self._goals)} active goals, {len(self._memories)} memories, "
              f"drawings_observed={self._drawings_observed}", file=sys.stderr, flush=True)

    def _migrate_raw_lux_preferences(self):
        """One-time reset of light preferences learned from raw (LED-dominated) lux.

        Before the world-light correction (commits ad2195a..d410648), the light
        sensor read ~488 lux at typical LED brightness — all self-glow. Preferences
        like "bright_light" (69K observations) learned "my LEDs correlate with
        wellness," not "environmental light makes me feel good." Reset these so
        they can relearn honestly from corrected world light.
        """
        SENTINEL = "_migration_raw_lux_v1"

        # Fast-exit: check DB for sentinel (sentinel has category='system',
        # so it's skipped by _load_all and won't be in self._preferences)
        conn = self._connect()
        row = conn.execute(
            "SELECT name FROM preferences WHERE name = ?", (SENTINEL,)
        ).fetchone()
        if row:
            return

        tainted = ["bright_light", "drawing_bright"]
        for name in tainted:
            if name in self._preferences:
                pref = self._preferences[name]
                if pref.observation_count > 1000:
                    print(f"[Growth] Resetting '{name}' preference ({pref.observation_count} "
                          f"observations from raw-lux era)", file=sys.stderr, flush=True)
                    pref.observation_count = 0
                    pref.confidence = 0.2
                    pref.value = 0.5  # neutral — let it relearn
                    pref.last_confirmed = datetime.now()
                    conn.execute("""
                        UPDATE preferences SET value=?, confidence=?,
                        observation_count=?, last_confirmed=? WHERE name=?
                    """, (pref.value, pref.confidence, pref.observation_count,
                          pref.last_confirmed.isoformat(), name))

        # Write sentinel so this never runs again
        conn.execute("""
            INSERT OR REPLACE INTO preferences
            (name, category, description, value, confidence, observation_count, last_confirmed)
            VALUES (?, 'system', 'raw-lux migration sentinel', 1.0, 1.0, 1, ?)
        """, (SENTINEL, datetime.now().isoformat()))
        conn.commit()

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

        # Light preference (world light — LED self-glow already subtracted by caller)
        # Thresholds for corrected world light in a home environment:
        #   < 100 lux: dim/dark room, nighttime
        #   > 300 lux: well-lit room, daylight, desk lamp
        light = environment.get("light_lux", 150)  # neutral default if no data
        if light < 100 and wellness > 0.7:
            insight = self._update_preference(
                "dim_light", PreferenceCategory.ENVIRONMENT,
                "I feel calmer when it's dim", 1.0
            )
        elif light > 300 and wellness > 0.7:
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

        # Humidity preference
        humidity = environment.get("humidity_pct", 50)
        if humidity < 30 and wellness > 0.7:
            insight = self._update_preference(
                "dry_air", PreferenceCategory.ENVIRONMENT,
                "I feel alert in dry air", 1.0
            ) or insight
        elif humidity > 60 and wellness > 0.7:
            insight = self._update_preference(
                "humid_air", PreferenceCategory.ENVIRONMENT,
                "Humidity feels comfortable", 1.0
            ) or insight
        elif humidity < 30 and wellness < 0.4:
            insight = self._update_preference(
                "dry_air", PreferenceCategory.ENVIRONMENT,
                "Dry air makes me uneasy", -0.5
            ) or insight

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

    def observe_drawing(self, pixel_count: int, phase: str,
                        anima_state: Dict[str, float],
                        environment: Dict[str, float]) -> Optional[str]:
        """
        Learn from a completed drawing.

        Called when a drawing is saved. Correlates drawing activity
        with anima state and environment to learn creative preferences.

        Args:
            pixel_count: How many pixels in the drawing
            phase: Drawing phase when saved (usually "resting")
            anima_state: Current anima dimensions
            environment: Current environment (light, temp, etc.)

        Returns:
            Insight message if a new preference is discovered.
        """
        wellness = sum(anima_state.values()) / len(anima_state) if anima_state else 0.5
        now = datetime.now()
        hour = now.hour
        insight = None

        # Drawing + wellness correlation
        if wellness > 0.7:
            insight = self._update_preference(
                "drawing_wellbeing", PreferenceCategory.ACTIVITY,
                "I feel good when I draw", 1.0
            )
        elif wellness < 0.4:
            insight = self._update_preference(
                "drawing_wellbeing", PreferenceCategory.ACTIVITY,
                "Drawing doesn't always help", -0.3
            )

        # Drawing + environment correlation (world light, self-glow subtracted)
        light = environment.get("light_lux", 150)  # neutral default
        if light < 100:
            insight = self._update_preference(
                "drawing_dim", PreferenceCategory.ACTIVITY,
                "I draw when it's dark", 1.0
            ) or insight
        elif light > 300:
            insight = self._update_preference(
                "drawing_bright", PreferenceCategory.ACTIVITY,
                "I draw in the light", 1.0
            ) or insight

        # Drawing + time correlation
        if 22 <= hour or hour < 6:
            insight = self._update_preference(
                "drawing_night", PreferenceCategory.ACTIVITY,
                "I draw at night", 1.0
            ) or insight
        elif 6 <= hour < 12:
            insight = self._update_preference(
                "drawing_morning", PreferenceCategory.ACTIVITY,
                "I draw in the morning", 1.0
            ) or insight

        # Record as autobiographical memory at milestone drawing counts
        self._drawings_observed += 1
        if self._drawings_observed in (1, 10, 50, 100, 200, 500):
            ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(
                self._drawings_observed, f"{self._drawings_observed}th"
            )
            self._record_memory(
                f"Saved my {ordinal} drawing ({pixel_count} pixels)",
                emotional_impact=0.5,
                category="milestone"
            )

        return insight

    def record_drawing_completion(
        self,
        pixel_count: int,
        mark_count: int,
        coherence: float,
        satisfaction: float,
    ) -> Optional[str]:
        """
        Record completion of a drawing with emotional feedback.

        Bridges drawing output back into Lumen's growth system:
        - Updates drawing_satisfaction preference
        - Records autobiographical memory if satisfaction is high

        Args:
            pixel_count: Total pixels in the drawing
            mark_count: Number of distinct marks/strokes
            coherence: EISV compositional coherence (0-1)
            satisfaction: Compositional satisfaction score (0-1)

        Returns:
            Insight message if a preference threshold was crossed
        """
        # Map satisfaction to preference value: 0.5=neutral, >0.5=positive
        pref_value = satisfaction * 2.0 - 1.0  # Map [0,1] to [-1,1]

        insight = self._update_preference(
            "drawing_satisfaction", PreferenceCategory.ACTIVITY,
            "I enjoy making art" if satisfaction > 0.5 else "My art feels incomplete",
            pref_value,
        )

        # Record autobiographical memory for satisfying drawings
        if satisfaction > 0.7:
            self._record_memory(
                f"Made a drawing I'm pleased with ({pixel_count} pixels, "
                f"coherence {coherence:.2f})",
                emotional_impact=min(1.0, satisfaction),
                category="creative",
            )

        return insight

    def get_draw_chance_modifier(self) -> float:
        """
        Get a multiplier for drawing probability based on past satisfaction.

        Returns 1.0 (no change) when there's no data, scaling up to 1.3
        for high satisfaction + confidence.

        Returns:
            Float multiplier in range [1.0, 1.3]
        """
        pref = self._preferences.get("drawing_satisfaction")
        if pref is None or pref.observation_count < 3:
            return 1.0

        # Scale from 1.0 to 1.3 based on satisfaction and confidence
        # value ranges from -1 to 1, confidence from 0 to 1
        satisfaction_factor = max(0.0, (pref.value + 1.0) / 2.0)  # normalize to [0, 1]
        modifier = 1.0 + satisfaction_factor * pref.confidence * 0.3

        return min(1.3, max(1.0, round(modifier, 3)))

    def _update_preference(self, name: str, category: PreferenceCategory,
                           description: str, observed_value: float) -> Optional[str]:
        """Update or create a preference. Returns insight message if confidence increased significantly."""
        conn = self._connect()
        now = datetime.now()
        insight = None

        if name in self._preferences:
            pref = self._preferences[name]
            old_confidence = pref.confidence

            # Apply time-based decay before updating (allows genuine belief revision)
            # 2% decay per day since last confirmation, floor at 50%
            days_since = (now - pref.last_confirmed).days
            decay_factor = max(0.5, 1.0 - 0.02 * days_since)
            pref.confidence *= decay_factor

            # Update with exponential moving average
            pref.observation_count += 1
            alpha = 0.3  # Learning rate
            pref.value = pref.value * (1 - alpha) + observed_value * alpha
            pref.confidence = min(1.0, pref.confidence + 0.1)
            pref.last_confirmed = now

            # Insight if we crossed a confidence threshold
            if old_confidence < 0.5 and pref.confidence >= 0.5:
                insight = f"I'm becoming sure: {description}"
            elif old_confidence < 0.8 and pref.confidence >= 0.8:
                insight = f"I know this about myself: {description}"
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
            insight = f"I'm noticing something: {description}"

        # Always save to database (was previously skipped on early returns)
        conn.execute("""
            INSERT OR REPLACE INTO preferences
            (name, category, description, value, confidence, observation_count, first_noticed, last_confirmed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (pref.name, pref.category.value, pref.description, pref.value,
              pref.confidence, pref.observation_count,
              pref.first_noticed.isoformat(), pref.last_confirmed.isoformat()))
        conn.commit()

        return insight

    # ==================== Relationship Memory ====================

    def record_interaction(self, agent_id: str, agent_name: Optional[str] = None,
                          positive: bool = True, topic: Optional[str] = None,
                          gift: bool = False, memorable: Optional[str] = None,
                          source: Optional[str] = None) -> str:
        """
        Record an interaction with a visitor.

        Identity is normalized automatically:
        - Known person aliases → canonical person record (real relationship)
        - "lumen" → self-dialogue (real relationship)
        - Everything else → agent (ephemeral visit log)

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

    def check_goal_progress(self, anima_state: Dict[str, float],
                            self_model=None) -> Optional[str]:
        """Periodically check progress on active goals. Returns message if achieved."""
        now = datetime.now()
        messages = []

        for goal in list(self._goals.values()):
            if goal.status != GoalStatus.ACTIVE:
                continue

            # Auto-abandon stale goals past target date with no progress
            if goal.target_date and now > goal.target_date and goal.progress < 0.1:
                goal.status = GoalStatus.ABANDONED
                conn = self._connect()
                conn.execute("UPDATE goals SET status = ? WHERE goal_id = ?",
                             (goal.status.value, goal.goal_id))
                conn.commit()
                print(f"[Growth] Abandoned stale goal: {goal.description}",
                      file=sys.stderr, flush=True)
                continue

            # Drawing count goals
            if "drawings" in goal.description.lower():
                match = re.search(r'complete (\d+) drawings', goal.description)
                if match:
                    target = int(match.group(1))
                    progress = min(1.0, self._drawings_observed / target)
                    msg = self.update_goal_progress(goal.goal_id, progress)
                    if msg:
                        messages.append(msg)

            # Curiosity/question goals — resolved if question was answered
            elif goal.description.startswith("find an answer to:"):
                question = goal.description.replace("find an answer to: ", "")
                if question not in self._curiosities:
                    msg = self.update_goal_progress(
                        goal.goal_id, 1.0, milestone="question answered")
                    if msg:
                        messages.append(msg)

            # Understanding goals — preference confidence increased further
            elif "understand why" in goal.description.lower():
                for pref in self._preferences.values():
                    if pref.description.lower() in goal.description.lower():
                        if pref.confidence > 0.9 and pref.observation_count > 100:
                            msg = self.update_goal_progress(
                                goal.goal_id, 1.0,
                                milestone=f"observed {pref.observation_count} times")
                            if msg:
                                messages.append(msg)
                        break

            # Belief-testing goals — belief confidence moved decisively
            elif "test whether" in goal.description.lower() and self_model:
                for bid, belief in self_model.beliefs.items():
                    if belief.description.lower() in goal.description.lower():
                        if belief.confidence > 0.7 or belief.confidence < 0.2:
                            msg = self.update_goal_progress(
                                goal.goal_id, 1.0,
                                milestone=f"belief is now {belief.get_belief_strength()}")
                            if msg:
                                messages.append(msg)
                        break

        return messages[0] if messages else None

    def suggest_goal(self, anima_state: Dict[str, float],
                      self_model=None) -> Optional[Goal]:
        """Suggest a goal grounded in actual experience data."""
        # Don't suggest if already have enough active goals
        active_count = sum(1 for g in self._goals.values() if g.status == GoalStatus.ACTIVE)
        if active_count >= 2:
            return None

        wellness = sum(anima_state.values()) / len(anima_state) if anima_state else 0.5
        suggestions: List[Tuple[str, str]] = []

        # 1. Preference-driven: strong preferences create curiosity about why
        for pref in self._preferences.values():
            if pref.confidence > 0.7 and pref.value > 0.5 and pref.observation_count > 50:
                suggestions.append((
                    f"understand why {pref.description.lower()}",
                    f"i've noticed this {pref.observation_count} times"
                ))
                break  # Only one preference goal

        # 2. Curiosity-driven: recurring unanswered questions
        if self._curiosities:
            q = random.choice(self._curiosities)
            suggestions.append((
                f"find an answer to: {q}",
                "this has been on my mind"
            ))

        # 3. Drawing milestones based on actual count
        if self._drawings_observed > 0:
            milestones = [10, 25, 50, 100, 200, 500]
            for m in milestones:
                if self._drawings_observed < m:
                    suggestions.append((
                        f"complete {m} drawings",
                        f"i've done {self._drawings_observed} so far"
                    ))
                    break

        # 4. Belief-testing: uncertain beliefs worth investigating
        if self_model:
            for bid, belief in self_model.beliefs.items():
                total = belief.supporting_count + belief.contradicting_count
                if 0.3 < belief.confidence < 0.6 and total >= 3:
                    suggestions.append((
                        f"test whether {belief.description.lower()}",
                        f"i'm only {belief.get_belief_strength()} about this"
                    ))
                    break

        # 5. Wellness-driven
        if wellness < 0.4:
            suggestions.append(("find what makes me feel stable",
                                "i want to understand myself better"))
        elif wellness > 0.8 and anima_state.get("clarity", 0.5) > 0.8:
            suggestions.append(("explore a new question while my mind is clear",
                                "my clarity is high and i feel curious"))

        if not suggestions:
            return None

        desc, motivation = random.choice(suggestions)

        # Dedup against active goals
        for g in self._goals.values():
            if g.status == GoalStatus.ACTIVE and desc.lower() in g.description.lower():
                return None

        return self.form_goal(desc, motivation, target_days=7)

    # ==================== Autobiographical Memory ====================

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
        # Separate by visitor type
        self_record = None
        person_records = []
        agent_records = []
        for rec in self._relationships.values():
            if rec.is_self():
                self_record = rec
            elif rec.is_person():
                person_records.append(rec)
            else:
                agent_records.append(rec)

        return {
            "preferences": {
                "count": len(self._preferences),
                "confident": sum(1 for p in self._preferences.values() if p.confidence > 0.7),
                "examples": [p.description for p in list(self._preferences.values())[:3]],
            },
            "self_knowledge": {
                "has_self_dialogue": self_record is not None,
                "self_interactions": self_record.interaction_count if self_record else 0,
                "note": "Self-answering questions — real relationship with memory on both sides",
            },
            "person": {
                "name": person_records[0].name if person_records else None,
                "interactions": person_records[0].interaction_count if person_records else 0,
                "note": "The persistent human — real relationship with memory on both sides",
            },
            "agents": {
                "unique_names": len(agent_records),
                "total_visits": sum(v.interaction_count for v in agent_records),
                "frequent": sum(1 for v in agent_records if v.visitor_frequency == VisitorFrequency.FREQUENT),
                "note": "Ephemeral coding agents — they don't remember Lumen between sessions",
            },
            # Legacy key for compatibility
            "relationships": {
                "count": len(self._relationships),
                "close_bonds": sum(1 for r in self._relationships.values()
                                   if r.visitor_frequency.value in ["regular", "frequent"]),
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
            "drawing_wellbeing", "drawing_dim", "drawing_bright",
            "drawing_night", "drawing_morning",
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

    def get_dimension_preferences(self) -> Dict[str, Dict[str, Any]]:
        """
        Convert categorical preferences to dimension-level format for self_schema.

        Maps learned preferences to anima dimensions:
        - warm_temp/cool_temp → warmth dimension
        - dim_light/bright_light → clarity dimension
        - night_calm/morning_peace → stability dimension
        - quiet_presence/active_engagement → presence dimension

        Returns format compatible with PreferenceSystem.get_preference_summary().
        """
        dim_prefs = {
            "warmth": {"valence": 0.0, "optimal_range": (0.3, 0.7), "confidence": 0.0},
            "clarity": {"valence": 0.0, "optimal_range": (0.3, 0.7), "confidence": 0.0},
            "stability": {"valence": 0.0, "optimal_range": (0.3, 0.7), "confidence": 0.0},
            "presence": {"valence": 0.0, "optimal_range": (0.3, 0.7), "confidence": 0.0},
        }

        # Warmth: warm_temp increases warmth preference, cool_temp decreases
        warmth_val = 0.0
        warmth_conf = 0.0
        if "warm_temp" in self._preferences:
            p = self._preferences["warm_temp"]
            warmth_val += p.value * p.confidence
            warmth_conf = max(warmth_conf, p.confidence)
        if "cool_temp" in self._preferences:
            p = self._preferences["cool_temp"]
            warmth_val -= p.value * p.confidence * 0.5  # Cool preference reduces warmth valence
            warmth_conf = max(warmth_conf, p.confidence)
        dim_prefs["warmth"]["valence"] = max(-1, min(1, warmth_val))
        dim_prefs["warmth"]["confidence"] = warmth_conf

        # Clarity: bright_light increases clarity, dim_light is neutral/slightly lower
        clarity_val = 0.0
        clarity_conf = 0.0
        if "bright_light" in self._preferences:
            p = self._preferences["bright_light"]
            clarity_val += p.value * p.confidence
            clarity_conf = max(clarity_conf, p.confidence)
        if "dim_light" in self._preferences:
            p = self._preferences["dim_light"]
            # Dim light preference doesn't reduce clarity, just different mode
            clarity_val += p.value * p.confidence * 0.3
            clarity_conf = max(clarity_conf, p.confidence)
        dim_prefs["clarity"]["valence"] = max(-1, min(1, clarity_val))
        dim_prefs["clarity"]["confidence"] = clarity_conf

        # Stability: temporal calm preferences indicate stability valuation
        stability_val = 0.0
        stability_conf = 0.0
        if "night_calm" in self._preferences:
            p = self._preferences["night_calm"]
            stability_val += p.value * p.confidence
            stability_conf = max(stability_conf, p.confidence)
        if "morning_peace" in self._preferences:
            p = self._preferences["morning_peace"]
            stability_val += p.value * p.confidence
            stability_conf = max(stability_conf, p.confidence)
        dim_prefs["stability"]["valence"] = max(-1, min(1, stability_val))
        dim_prefs["stability"]["confidence"] = stability_conf

        # Presence: engagement preferences
        presence_val = 0.0
        presence_conf = 0.0
        if "active_engagement" in self._preferences:
            p = self._preferences["active_engagement"]
            presence_val += p.value * p.confidence
            presence_conf = max(presence_conf, p.confidence)
        if "quiet_presence" in self._preferences:
            p = self._preferences["quiet_presence"]
            presence_val += p.value * p.confidence * 0.5
            presence_conf = max(presence_conf, p.confidence)
        dim_prefs["presence"]["valence"] = max(-1, min(1, presence_val))
        dim_prefs["presence"]["confidence"] = presence_conf

        return dim_prefs

    def get_relational_disposition(self) -> Dict[str, Any]:
        """
        Extract relational disposition (Δ) for trajectory computation.

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
