"""Tests for growth.migrations — identity merge and raw-lux preference reset."""

import json
import sqlite3

import pytest

from anima_mcp.growth.migrations import (
    migrate_external_light_preferences_v2,
    migrate_preference_evidence_windows,
    migrate_qa_claim_preferences,
    migrate_raw_lux_preferences,
    run_identity_migration,
)
from anima_mcp.growth.models import (
    GrowthPreference,
    PreferenceCategory,
    RETIRED_QA_PREFERENCE_ORIGIN,
    preference_evidence_status,
)


def _schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE preferences (
            name TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            description TEXT,
            value REAL DEFAULT 0.0,
            confidence REAL DEFAULT 0.0,
            observation_count INTEGER DEFAULT 0,
            first_noticed TEXT,
            last_confirmed TEXT,
            evidence_count INTEGER DEFAULT 0,
            supporting_count INTEGER DEFAULT 0,
            contradicting_count INTEGER DEFAULT 0,
            last_evidence_key TEXT,
            evidence_origin TEXT DEFAULT 'legacy_unclassified'
        );
        CREATE TABLE relationships (
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
            self_dialogue_topics TEXT DEFAULT '[]',
            visitor_type TEXT DEFAULT 'agent'
        );
        """
    )


def _insert_relationship(conn: sqlite3.Connection, agent_id: str, **kwargs) -> None:
    defaults = {
        "name": agent_id,
        "first_met": "2020-01-01T00:00:00",
        "last_seen": "2025-06-01T12:00:00",
        "interaction_count": 1,
        "bond_strength": "stranger",
        "emotional_valence": 0.5,
        "memorable_moments": "[]",
        "topics_discussed": "[]",
        "gifts_received": 0,
        "visitor_type": "agent",
    }
    defaults.update(kwargs)
    conn.execute(
        """
        INSERT INTO relationships (
            agent_id, name, first_met, last_seen, interaction_count,
            bond_strength, emotional_valence, memorable_moments,
            topics_discussed, gifts_received, self_dialogue_topics, visitor_type
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?)
        """,
        (
            agent_id,
            defaults["name"],
            defaults["first_met"],
            defaults["last_seen"],
            defaults["interaction_count"],
            defaults["bond_strength"],
            defaults["emotional_valence"],
            defaults["memorable_moments"],
            defaults["topics_discussed"],
            defaults["gifts_received"],
            defaults["visitor_type"],
        ),
    )


class TestRunIdentityMigration:
    @pytest.fixture(autouse=True)
    def _operator_is_kenny(self, monkeypatch):
        # The canonical operator name is env-driven (ANIMA_OPERATOR_NAME); these
        # tests exercise a deployment whose caretaker is "kenny". Pin the alias
        # map so the merge target is stable regardless of the host's env.
        from anima_mcp import server_state
        monkeypatch.setattr(
            server_state,
            "KNOWN_PERSON_ALIASES",
            {"kenny": {"kenny", "caretaker", "dashboard", "human"}},
        )

    def test_skips_when_user_version_ge_one(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        _schema(conn)
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
        run_identity_migration(conn)
        assert conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0] == 0

    def test_sets_lumen_visitor_type_self(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        _schema(conn)
        _insert_relationship(conn, "lumen", visitor_type="agent")
        conn.commit()
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0

        run_identity_migration(conn)

        row = conn.execute(
            "SELECT visitor_type FROM relationships WHERE agent_id = 'lumen'"
        ).fetchone()
        assert row["visitor_type"] == "self"
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1

    def test_merges_kenny_aliases(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        _schema(conn)
        _insert_relationship(
            conn,
            "kenny",
            interaction_count=3,
            emotional_valence=0.4,
            memorable_moments=json.dumps(["a"]),
            topics_discussed=json.dumps(["t1"]),
            gifts_received=1,
        )
        _insert_relationship(
            conn,
            "caretaker",
            interaction_count=7,
            emotional_valence=0.6,
            memorable_moments=json.dumps(["b"]),
            topics_discussed=json.dumps(["t2"]),
            gifts_received=2,
        )
        conn.commit()

        run_identity_migration(conn)

        n = conn.execute(
            "SELECT COUNT(*) FROM relationships WHERE LOWER(agent_id) IN ('kenny','caretaker')"
        ).fetchone()[0]
        assert n == 1
        merged = conn.execute(
            "SELECT agent_id, interaction_count, bond_strength, gifts_received, visitor_type "
            "FROM relationships WHERE agent_id = 'kenny'"
        ).fetchone()
        assert merged["interaction_count"] == 10
        assert merged["bond_strength"] == "frequent"
        assert merged["gifts_received"] == 3
        assert merged["visitor_type"] == "person"

    def test_merges_alias_rows_with_invalid_json_moments(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        _schema(conn)
        _insert_relationship(
            conn,
            "kenny",
            memorable_moments="not-json",
            topics_discussed="also-bad",
            interaction_count=2,
        )
        _insert_relationship(conn, "human", interaction_count=1)
        conn.commit()

        run_identity_migration(conn)

        row = conn.execute(
            "SELECT interaction_count, visitor_type FROM relationships WHERE agent_id = 'kenny'"
        ).fetchone()
        assert row["interaction_count"] == 3
        assert row["visitor_type"] == "person"

    def test_idempotent_second_run_noop(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        _schema(conn)
        _insert_relationship(conn, "lumen")
        conn.commit()
        run_identity_migration(conn)
        v1 = conn.execute("PRAGMA user_version").fetchone()[0]
        n1 = conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
        run_identity_migration(conn)
        v2 = conn.execute("PRAGMA user_version").fetchone()[0]
        n2 = conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
        assert v1 == v2 == 1
        assert n1 == n2


class TestMigrateRawLuxPreferences:
    def _pref(self, name: str, obs: int) -> GrowthPreference:
        now = __import__("datetime").datetime.now()
        return GrowthPreference(
            category=PreferenceCategory.ENVIRONMENT,
            name=name,
            description="test",
            value=0.9,
            confidence=0.9,
            observation_count=obs,
            first_noticed=now,
            last_confirmed=now,
        )

    def test_skips_when_sentinel_exists(self):
        conn = sqlite3.connect(":memory:")
        _schema(conn)
        conn.execute(
            """
            INSERT INTO preferences (name, category, description, value, confidence,
                observation_count, last_confirmed)
            VALUES ('_migration_raw_lux_v1', 'system', 'sentinel', 1.0, 1.0, 1, '2020-01-01')
            """
        )
        conn.commit()
        prefs = {"bright_light": self._pref("bright_light", 5000)}
        migrate_raw_lux_preferences(conn, prefs)
        assert prefs["bright_light"].observation_count == 5000

    def test_marks_high_count_tainted_preferences_without_erasing_audit(self):
        conn = sqlite3.connect(":memory:")
        _schema(conn)
        conn.commit()
        prefs = {
            "bright_light": self._pref("bright_light", 2000),
            "drawing_bright": self._pref("drawing_bright", 1500),
        }
        migrate_raw_lux_preferences(conn, prefs)

        assert prefs["bright_light"].observation_count == 2000
        assert prefs["bright_light"].confidence == pytest.approx(0.2)
        assert prefs["bright_light"].value == pytest.approx(0.0)
        assert prefs["drawing_bright"].observation_count == 1500

        row = conn.execute(
            "SELECT name FROM preferences WHERE name = '_migration_raw_lux_v1'"
        ).fetchone()
        assert row is not None

    def test_inserts_sentinel_when_no_tainted_prefs(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        _schema(conn)
        conn.commit()
        migrate_raw_lux_preferences(conn, {})
        row = conn.execute(
            "SELECT category FROM preferences WHERE name = '_migration_raw_lux_v1'"
        ).fetchone()
        assert row["category"] == "system"

    def test_does_not_reset_low_observation_tainted(self):
        conn = sqlite3.connect(":memory:")
        _schema(conn)
        conn.commit()
        prefs = {"bright_light": self._pref("bright_light", 100)}
        migrate_raw_lux_preferences(conn, prefs)
        assert prefs["bright_light"].observation_count == 100
        row = conn.execute(
            "SELECT name FROM preferences WHERE name = '_migration_raw_lux_v1'"
        ).fetchone()
        assert row is not None


class TestMigratePreferenceEvidenceWindows:
    def test_correlated_ticks_are_reconstructed_as_hourly_evidence(self):
        from datetime import datetime, timedelta

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        _schema(conn)
        first = datetime(2026, 1, 1)
        last = first + timedelta(hours=120)
        pref = GrowthPreference(
            category=PreferenceCategory.ENVIRONMENT,
            name="warm_temp",
            description="Warmth makes me feel content",
            value=0.8,
            confidence=1.0,
            observation_count=6000,
            first_noticed=first,
            last_confirmed=last,
        )
        conn.execute(
            """
            INSERT INTO preferences
                (name, category, description, value, confidence,
                 observation_count, first_noticed, last_confirmed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pref.name,
                pref.category.value,
                pref.description,
                pref.value,
                pref.confidence,
                pref.observation_count,
                first.isoformat(),
                last.isoformat(),
            ),
        )
        conn.commit()

        migrate_preference_evidence_windows(conn, {pref.name: pref})

        assert pref.observation_count == 6000
        assert pref.evidence_count == 100
        assert pref.evidence_origin == "legacy_hourly_reconstruction"
        assert 0.9 < pref.confidence < 0.95
        row = conn.execute(
            "SELECT observation_count, evidence_count, evidence_origin "
            "FROM preferences WHERE name='warm_temp'"
        ).fetchone()
        assert row["observation_count"] == 6000
        assert row["evidence_count"] == 100
        assert row["evidence_origin"] == "legacy_hourly_reconstruction"

        migrate_preference_evidence_windows(conn, {pref.name: pref})
        assert pref.evidence_count == 100


class TestMigrateExternalLightPreferencesV2:
    def test_decision_evidence_resets_but_raw_audit_count_survives(self):
        from datetime import datetime

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        _schema(conn)
        now = datetime.now()
        pref = GrowthPreference(
            category=PreferenceCategory.ENVIRONMENT,
            name="dim_light",
            description="I feel calmer when it's dim",
            value=0.8,
            confidence=0.95,
            observation_count=120000,
            first_noticed=now,
            last_confirmed=now,
            evidence_count=2000,
            supporting_count=2000,
            evidence_origin="legacy_hourly_reconstruction",
        )
        conn.execute(
            """
            INSERT INTO preferences
                (name, category, description, value, confidence,
                 observation_count, first_noticed, last_confirmed,
                 evidence_count, supporting_count, contradicting_count,
                 evidence_origin)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pref.name, pref.category.value, pref.description, pref.value,
                pref.confidence, pref.observation_count,
                pref.first_noticed.isoformat(), pref.last_confirmed.isoformat(),
                pref.evidence_count, pref.supporting_count,
                pref.contradicting_count, pref.evidence_origin,
            ),
        )
        conn.commit()

        migrate_external_light_preferences_v2(conn, {pref.name: pref})

        assert pref.observation_count == 120000
        assert pref.independent_evidence_count == 0
        assert pref.confidence == pytest.approx(0.2)
        assert pref.evidence_origin == "reset_external_light_gate_v2"
        row = conn.execute(
            "SELECT observation_count, evidence_count FROM preferences "
            "WHERE name='dim_light'"
        ).fetchone()
        assert tuple(row) == (120000, 0)

    def test_drawing_light_evidence_is_cold_started_too(self):
        from datetime import datetime

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        _schema(conn)
        now = datetime.now()
        pref = GrowthPreference(
            category=PreferenceCategory.ACTIVITY,
            name="drawing_bright",
            description="I draw in the light",
            value=1.0,
            confidence=0.9,
            observation_count=1500,
            first_noticed=now,
            last_confirmed=now,
            evidence_count=1500,
            supporting_count=1500,
            evidence_origin="legacy_event_count",
        )
        conn.execute(
            """
            INSERT INTO preferences
                (name, category, description, value, confidence,
                 observation_count, first_noticed, last_confirmed,
                 evidence_count, supporting_count, contradicting_count,
                 evidence_origin)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pref.name, pref.category.value, pref.description, pref.value,
                pref.confidence, pref.observation_count,
                pref.first_noticed.isoformat(), pref.last_confirmed.isoformat(),
                pref.evidence_count, pref.supporting_count,
                pref.contradicting_count, pref.evidence_origin,
            ),
        )
        conn.commit()

        migrate_external_light_preferences_v2(conn, {pref.name: pref})

        assert pref.observation_count == 1500
        assert pref.independent_evidence_count == 0
        assert pref.evidence_origin == "reset_external_light_gate_v2"


class TestMigrateQaClaimPreferences:
    def test_retires_behavioral_evidence_but_preserves_audit_record(self):
        from datetime import datetime

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        _schema(conn)
        now = datetime.now()
        pref = GrowthPreference(
            category=PreferenceCategory.ENVIRONMENT,
            name="insight_light",
            description="From Q&A: a textual claim about brightness",
            value=-0.5,
            confidence=0.95,
            observation_count=330,
            first_noticed=now,
            last_confirmed=now,
            evidence_count=330,
            supporting_count=0,
            contradicting_count=330,
            evidence_origin="legacy_event_count",
        )
        conn.execute(
            """
            INSERT INTO preferences
                (name, category, description, value, confidence,
                 observation_count, first_noticed, last_confirmed,
                 evidence_count, supporting_count, contradicting_count,
                 evidence_origin)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pref.name,
                pref.category.value,
                pref.description,
                pref.value,
                pref.confidence,
                pref.observation_count,
                pref.first_noticed.isoformat(),
                pref.last_confirmed.isoformat(),
                pref.evidence_count,
                pref.supporting_count,
                pref.contradicting_count,
                pref.evidence_origin,
            ),
        )
        conn.commit()

        migrate_qa_claim_preferences(conn, {pref.name: pref})

        assert pref.observation_count == 330
        assert pref.value == 0.0
        assert pref.confidence == 0.0
        assert pref.independent_evidence_count == 0
        assert pref.evidence_origin == RETIRED_QA_PREFERENCE_ORIGIN
        assert preference_evidence_status(pref) == "historical_claim"
        row = conn.execute(
            "SELECT value, confidence, observation_count, evidence_count, "
            "evidence_origin FROM preferences WHERE name='insight_light'"
        ).fetchone()
        assert tuple(row) == (
            0.0,
            0.0,
            330,
            0,
            RETIRED_QA_PREFERENCE_ORIGIN,
        )

        sentinel = conn.execute(
            "SELECT description FROM preferences "
            "WHERE name='_migration_retire_qa_preference_bridge_v1'"
        ).fetchone()
        audit = json.loads(sentinel["description"])
        assert audit["rows"][0]["contradicting_count"] == 330

        # The sentinel makes the migration idempotent.
        migrate_qa_claim_preferences(conn, {pref.name: pref})
        assert pref.evidence_origin == RETIRED_QA_PREFERENCE_ORIGIN
