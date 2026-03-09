"""
Growth System database migrations.

Standalone functions that take a connection parameter.
"""

import sys
import json
import sqlite3
from datetime import datetime
from typing import Dict

from .models import GrowthPreference


def run_identity_migration(conn: sqlite3.Connection):
    """One-time migration: merge person aliases, set visitor_types.

    Uses PRAGMA user_version to track whether migration has already run.
    """
    from ..server_state import KNOWN_PERSON_ALIASES

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


def migrate_raw_lux_preferences(
    conn: sqlite3.Connection,
    preferences: Dict[str, GrowthPreference],
):
    """One-time reset of light preferences learned from raw (LED-dominated) lux.

    Before the world-light correction (commits ad2195a..d410648), the light
    sensor read ~488 lux at typical LED brightness — all self-glow. Preferences
    like "bright_light" (69K observations) learned "my LEDs correlate with
    wellness," not "environmental light makes me feel good." Reset these so
    they can relearn honestly from corrected world light.
    """
    SENTINEL = "_migration_raw_lux_v1"

    # Fast-exit: check DB for sentinel (sentinel has category='system',
    # so it's skipped by _load_all and won't be in preferences)
    row = conn.execute(
        "SELECT name FROM preferences WHERE name = ?", (SENTINEL,)
    ).fetchone()
    if row:
        return

    tainted = ["bright_light", "drawing_bright"]
    for name in tainted:
        if name in preferences:
            pref = preferences[name]
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
