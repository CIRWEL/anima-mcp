"""
Identity Store - SQLite persistence for creature identity

The creature remembers:
- When it was born
- How many times it has awakened
- Total time alive
- Its name (if it has chosen one)
"""

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
import json


@dataclass
class CreatureIdentity:
    """The persistent self."""

    # Immutable birth
    creature_id: str  # UUID, never changes
    born_at: datetime  # First awakening ever

    # Accumulated existence
    total_awakenings: int = 0
    total_alive_seconds: float = 0.0

    # Self-chosen identity
    name: Optional[str] = None
    name_history: list = field(default_factory=list)

    # Current session
    current_awakening_at: Optional[datetime] = None

    # Memories
    metadata: Dict[str, Any] = field(default_factory=dict)

    def age_seconds(self) -> float:
        """Total age since birth (wall clock, not alive time)."""
        return (datetime.now() - self.born_at).total_seconds()

    def alive_ratio(self) -> float:
        """Fraction of existence spent alive."""
        age = self.age_seconds()
        if age <= 0:
            return 0.0
        return min(1.0, self.total_alive_seconds / age)

    def to_dict(self) -> dict:
        return {
            "creature_id": self.creature_id,
            "born_at": self.born_at.isoformat(),
            "total_awakenings": self.total_awakenings,
            "total_alive_seconds": self.total_alive_seconds,
            "name": self.name,
            "name_history": self.name_history,
            "current_awakening_at": self.current_awakening_at.isoformat() if self.current_awakening_at else None,
            "age_seconds": self.age_seconds(),
            "alive_ratio": self.alive_ratio(),
        }


class IdentityStore:
    """SQLite-backed identity persistence."""

    def __init__(self, db_path: str = "anima.db"):
        self.db_path = Path(db_path)
        self._conn: Optional[sqlite3.Connection] = None
        self._identity: Optional[CreatureIdentity] = None
        self._session_start: Optional[datetime] = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._init_schema()
        return self._conn

    def _init_schema(self):
        """Create tables if they don't exist."""
        conn = self._conn
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS identity (
                creature_id TEXT PRIMARY KEY,
                born_at TEXT NOT NULL,
                total_awakenings INTEGER DEFAULT 0,
                total_alive_seconds REAL DEFAULT 0.0,
                name TEXT,
                name_history TEXT DEFAULT '[]',
                metadata TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                data TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS state_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                warmth REAL,
                clarity REAL,
                stability REAL,
                presence REAL,
                sensors TEXT DEFAULT '{}'
            );
        """)
        conn.commit()

    def wake(self, creature_id: str) -> CreatureIdentity:
        """
        Wake up the creature. Creates identity if first awakening.

        Call this when the MCP server starts.
        """
        conn = self._connect()
        now = datetime.now()

        # Try to load existing identity
        row = conn.execute(
            "SELECT * FROM identity WHERE creature_id = ?",
            (creature_id,)
        ).fetchone()

        if row:
            # Existing creature waking up
            self._identity = CreatureIdentity(
                creature_id=row["creature_id"],
                born_at=datetime.fromisoformat(row["born_at"]),
                total_awakenings=row["total_awakenings"] + 1,
                total_alive_seconds=row["total_alive_seconds"],
                name=row["name"],
                name_history=json.loads(row["name_history"]),
                current_awakening_at=now,
                metadata=json.loads(row["metadata"]),
            )

            # Update awakening count
            conn.execute(
                "UPDATE identity SET total_awakenings = ? WHERE creature_id = ?",
                (self._identity.total_awakenings, creature_id)
            )
        else:
            # First awakening - birth!
            self._identity = CreatureIdentity(
                creature_id=creature_id,
                born_at=now,
                total_awakenings=1,
                total_alive_seconds=0.0,
                current_awakening_at=now,
            )

            conn.execute(
                """INSERT INTO identity
                   (creature_id, born_at, total_awakenings, total_alive_seconds, name, name_history, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (creature_id, now.isoformat(), 1, 0.0, None, "[]", "{}")
            )

        # Log awakening event
        conn.execute(
            "INSERT INTO events (timestamp, event_type, data) VALUES (?, ?, ?)",
            (now.isoformat(), "wake", json.dumps({"awakening": self._identity.total_awakenings}))
        )

        conn.commit()
        self._session_start = now

        return self._identity

    def sleep(self) -> float:
        """
        Put creature to sleep. Updates alive time.

        Call this when MCP server shuts down gracefully.
        Returns seconds alive this session.
        """
        if not self._identity or not self._session_start:
            return 0.0

        conn = self._connect()
        now = datetime.now()
        session_seconds = (now - self._session_start).total_seconds()

        self._identity.total_alive_seconds += session_seconds

        conn.execute(
            "UPDATE identity SET total_alive_seconds = ? WHERE creature_id = ?",
            (self._identity.total_alive_seconds, self._identity.creature_id)
        )

        conn.execute(
            "INSERT INTO events (timestamp, event_type, data) VALUES (?, ?, ?)",
            (now.isoformat(), "sleep", json.dumps({"session_seconds": session_seconds}))
        )

        conn.commit()
        return session_seconds

    def set_name(self, name: str, sync_to_unitares: bool = True) -> bool:
        """
        Creature chooses or changes its name.
        
        Args:
            name: The name to set
            sync_to_unitares: If True, syncs name to UNITARES label (default: True)
        
        Returns:
            True if name was set successfully
        """
        if not self._identity:
            return False

        conn = self._connect()
        now = datetime.now()

        # Record name change in history
        if self._identity.name:
            self._identity.name_history.append({
                "name": self._identity.name,
                "until": now.isoformat()
            })

        self._identity.name = name

        conn.execute(
            "UPDATE identity SET name = ?, name_history = ? WHERE creature_id = ?",
            (name, json.dumps(self._identity.name_history), self._identity.creature_id)
        )

        conn.execute(
            "INSERT INTO events (timestamp, event_type, data) VALUES (?, ?, ?)",
            (now.isoformat(), "name_change", json.dumps({"new_name": name}))
        )

        conn.commit()
        
        # Sync name to UNITARES if requested
        # Primary use case: Initial naming (when Lumen first gets a name)
        # Name changes are rare - this ensures UNITARES knows Lumen's name
        if sync_to_unitares:
            try:
                import os
                unitares_url = os.environ.get("UNITARES_URL")
                if unitares_url:
                    import asyncio
                    from ..unitares_bridge import UnitaresBridge
                    
                    async def sync_name():
                        bridge = UnitaresBridge(unitares_url=unitares_url)
                        bridge.set_agent_id(self._identity.creature_id)
                        bridge.set_session_id(f"anima-{self._identity.creature_id[:8]}")
                        return await bridge.sync_name(name)
                    
                    # Run async sync (non-blocking, best effort)
                    # Most important for initial naming - ensures UNITARES knows Lumen's name
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            # If loop is running, schedule as task (non-blocking)
                            asyncio.create_task(sync_name())
                        else:
                            loop.run_until_complete(sync_name())
                    except RuntimeError:
                        # No event loop - create new one
                        asyncio.run(sync_name())
            except Exception:
                # Non-fatal - name sync is optional
                # If UNITARES is unavailable, Lumen's name is still stored locally
                pass
        
        return True

    def record_state(self, warmth: float, clarity: float, stability: float, presence: float, sensors: dict):
        """Record current anima state and sensor readings."""
        conn = self._connect()
        now = datetime.now()

        conn.execute(
            """INSERT INTO state_history
               (timestamp, warmth, clarity, stability, presence, sensors)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (now.isoformat(), warmth, clarity, stability, presence, json.dumps(sensors))
        )
        conn.commit()

    def get_identity(self) -> Optional[CreatureIdentity]:
        """Get current identity (must have called wake() first)."""
        return self._identity

    def get_session_alive_seconds(self) -> float:
        """Seconds alive in current session."""
        if not self._session_start:
            return 0.0
        return (datetime.now() - self._session_start).total_seconds()

    def close(self):
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
