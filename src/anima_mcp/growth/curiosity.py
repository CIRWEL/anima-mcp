"""
Growth System - Curiosity tracking mixin.

Handles adding, retrieving, and marking curiosities as explored.
"""

import sys
import sqlite3
from datetime import datetime
from typing import Optional, List
import random


class CuriosityMixin:
    """Mixin for curiosity-driven exploration."""

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
