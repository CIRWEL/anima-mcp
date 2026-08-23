"""
Growth System database migrations.

Standalone functions that take a connection parameter.
"""

import sys
import json
import math
import sqlite3
from datetime import datetime
from typing import Dict

from .models import GrowthPreference, preference_evidence_confidence


# These preferences were historically sampled from the broker loop, nominally
# about once per minute. Their raw counts describe scheduler cadence, not
# independent experience. Drawing and Q&A preferences are event-triggered and
# therefore retain one evidence item per historical observation.
_CORRELATED_STATE_PREFERENCES = {
    "active_engagement",
    "bright_light",
    "cool_temp",
    "dim_light",
    "dry_air",
    "evening_calm",
    "humid_air",
    "morning_peace",
    "night_calm",
    "quiet_presence",
    "warm_temp",
}
_LEGACY_STATE_CALLS_PER_HOUR = 60


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
    """Legacy one-time marker for preferences learned from LED-dominated lux.

    Before the world-light correction (commits ad2195a..d410648), the light
    sensor read ~488 lux at typical LED brightness — all self-glow. Preferences
    like "bright_light" (69K observations) learned "my LEDs correlate with
    wellness," not "environmental light makes me feel good." The later v2
    evidence migration performs the durable cold start. This compatibility
    step now preserves the raw call count as audit data rather than erasing it.
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
                pref.confidence = 0.2
                pref.value = 0.0  # neutral on the documented [-1, 1] scale
                pref.last_confirmed = datetime.now()
                conn.execute("""
                    UPDATE preferences SET value=?, confidence=?,
                    last_confirmed=? WHERE name=?
                """, (pref.value, pref.confidence,
                      pref.last_confirmed.isoformat(), name))

    # Write sentinel so this never runs again
    conn.execute("""
        INSERT OR REPLACE INTO preferences
        (name, category, description, value, confidence, observation_count, last_confirmed)
        VALUES (?, 'system', 'raw-lux migration sentinel', 1.0, 1.0, 1, ?)
    """, (SENTINEL, datetime.now().isoformat()))
    conn.commit()


def migrate_preference_evidence_windows(
    conn: sqlite3.Connection,
    preferences: Dict[str, GrowthPreference],
):
    """One-time cadence correction for preference confidence and evidence.

    Historical state preferences were updated on every eligible broker pass.
    We cannot recover their exact independent episodes after the fact, so this
    migration stores a deliberately conservative reconstruction: at most one
    evidence item per nominal hour and never more than elapsed clock hours.
    The untouched raw count remains available for audit. Event-driven drawing
    and Q&A preferences retain their historical event counts.

    Historical polarity was not stored, so reconstructed items inherit the
    sign of the last learned value and are explicitly marked reconstructed.
    Native v2 observations subsequently record signed hourly windows.
    """
    sentinel = "_migration_preference_evidence_v1"
    row = conn.execute(
        "SELECT name FROM preferences WHERE name = ?", (sentinel,)
    ).fetchone()
    if row:
        return

    migrated = 0
    for pref in preferences.values():
        raw_count = max(0, int(pref.observation_count))
        if pref.name in _CORRELATED_STATE_PREFERENCES and raw_count:
            nominal_hours = max(
                1,
                math.ceil(raw_count / _LEGACY_STATE_CALLS_PER_HOUR),
            )
            elapsed_hours = max(
                1,
                math.ceil(
                    max(
                        0.0,
                        (pref.last_confirmed - pref.first_noticed).total_seconds(),
                    )
                    / 3600.0
                ),
            )
            evidence_count = min(raw_count, nominal_hours, elapsed_hours)
            origin = "legacy_hourly_reconstruction"
        else:
            evidence_count = raw_count
            origin = "legacy_event_count"

        pref.evidence_count = evidence_count
        pref.supporting_count = evidence_count if pref.value >= 0.0 else 0
        pref.contradicting_count = evidence_count if pref.value < 0.0 else 0
        pref.last_evidence_key = None
        pref.evidence_origin = origin
        if evidence_count:
            pref.confidence = preference_evidence_confidence(
                pref.supporting_count,
                pref.contradicting_count,
            )
        else:
            pref.confidence = min(pref.confidence, 0.2)

        conn.execute(
            """
            UPDATE preferences
               SET confidence=?, evidence_count=?, supporting_count=?,
                   contradicting_count=?, last_evidence_key=?, evidence_origin=?
             WHERE name=?
            """,
            (
                pref.confidence,
                pref.evidence_count,
                pref.supporting_count,
                pref.contradicting_count,
                pref.last_evidence_key,
                pref.evidence_origin,
                pref.name,
            ),
        )
        migrated += 1

    conn.execute(
        """
        INSERT OR REPLACE INTO preferences
            (name, category, description, value, confidence,
             observation_count, evidence_count, supporting_count,
             contradicting_count, evidence_origin, last_confirmed)
        VALUES (?, 'system', 'preference evidence migration sentinel',
                1.0, 1.0, 1, 1, 1, 0, 'system', ?)
        """,
        (sentinel, datetime.now().isoformat()),
    )
    conn.commit()
    print(
        f"[Growth] Preference evidence migration v1 complete ({migrated} rows).",
        file=sys.stderr,
        flush=True,
    )


def migrate_external_light_preferences_v2(
    conn: sqlite3.Connection,
    preferences: Dict[str, GrowthPreference],
):
    """Reset interpreted light evidence before the gated-residual era.

    The first raw-lux migration assumed a subtraction would remain in the
    caller. It was later removed because the fixed quadratic overcorrected, but
    raw VEML7700 lux then resumed feeding state and drawing preferences while
    their descriptions still claimed room light. Preserve raw call counts for
    audit, but cold-start the decision-bearing evidence fields. New light
    evidence is admitted only from a ready learned residual.
    """
    sentinel = "_migration_external_light_gate_v2"
    if conn.execute(
        "SELECT name FROM preferences WHERE name = ?", (sentinel,)
    ).fetchone():
        return

    now = datetime.now()
    for name in ("dim_light", "bright_light", "drawing_dim", "drawing_bright"):
        pref = preferences.get(name)
        if pref is None:
            continue
        pref.value = 0.0
        pref.confidence = 0.2
        pref.evidence_count = 0
        pref.supporting_count = 0
        pref.contradicting_count = 0
        pref.last_evidence_key = None
        pref.evidence_origin = "reset_external_light_gate_v2"
        pref.last_confirmed = now
        conn.execute(
            """
            UPDATE preferences
               SET value=?, confidence=?, evidence_count=0,
                   supporting_count=0, contradicting_count=0,
                   last_evidence_key=NULL, evidence_origin=?, last_confirmed=?
             WHERE name=?
            """,
            (
                pref.value,
                pref.confidence,
                pref.evidence_origin,
                pref.last_confirmed.isoformat(),
                name,
            ),
        )

    conn.execute(
        """
        INSERT OR REPLACE INTO preferences
            (name, category, description, value, confidence,
             observation_count, evidence_count, supporting_count,
             contradicting_count, evidence_origin, last_confirmed)
        VALUES (?, 'system', 'external-light gate migration sentinel',
                1.0, 1.0, 1, 1, 1, 0, 'system', ?)
        """,
        (sentinel, now.isoformat()),
    )
    conn.commit()
