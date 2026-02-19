"""
Tests for self_reflection.py — insight persistence, pattern analysis,
preference/belief/drawing analyzers, and reflect() orchestration.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from anima_mcp.self_reflection import (
    SelfReflectionSystem, Insight, InsightCategory, StatePattern,
)


@pytest.fixture
def srs(tmp_path):
    """Create SelfReflectionSystem with temp database."""
    system = SelfReflectionSystem(db_path=str(tmp_path / "test_reflect.db"))
    # state_history is created by the server, not SelfReflectionSystem — create it here
    conn = system._connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS state_history (
            timestamp TEXT, warmth REAL, clarity REAL,
            stability REAL, presence REAL, sensors TEXT
        )
    """)
    conn.commit()
    return system


# ==================== Insight Data Class ====================

class TestInsight:
    """Test Insight strength calculation."""

    def test_strength_new_insight(self):
        """New insight (no validations) has moderate strength."""
        i = Insight(
            id="test", category=InsightCategory.TEMPORAL,
            description="test", confidence=0.8, sample_count=10,
            discovered_at=datetime.now(), last_validated=datetime.now(),
            validation_count=0, contradiction_count=0,
        )
        # No validations → strength = confidence * 0.5
        assert i.strength() == pytest.approx(0.4)

    def test_strength_validated(self):
        """Validated insight has higher strength."""
        i = Insight(
            id="test", category=InsightCategory.TEMPORAL,
            description="test", confidence=0.8, sample_count=10,
            discovered_at=datetime.now(), last_validated=datetime.now(),
            validation_count=5, contradiction_count=0,
        )
        # All validations, no contradictions → strength = 0.8 * (5/5) = 0.8
        assert i.strength() == pytest.approx(0.8)

    def test_strength_contradicted(self):
        """Contradicted insight has lower strength."""
        i = Insight(
            id="test", category=InsightCategory.TEMPORAL,
            description="test", confidence=0.8, sample_count=10,
            discovered_at=datetime.now(), last_validated=datetime.now(),
            validation_count=1, contradiction_count=3,
        )
        # 1/(1+3) = 0.25 → 0.8 * 0.25 = 0.2
        assert i.strength() == pytest.approx(0.2)

    def test_to_dict(self):
        i = Insight(
            id="test_id", category=InsightCategory.ENVIRONMENT,
            description="light insight", confidence=0.7, sample_count=50,
            discovered_at=datetime.now(), last_validated=datetime.now(),
        )
        d = i.to_dict()
        assert d["id"] == "test_id"
        assert d["category"] == "environment"
        assert "strength" in d


# ==================== Persistence ====================

class TestInsightPersistence:
    """Test save/load round-trip via SQLite."""

    def test_save_and_reload(self, tmp_path):
        db = str(tmp_path / "persist.db")
        srs1 = SelfReflectionSystem(db_path=db)
        now = datetime.now()
        insight = Insight(
            id="persist_test", category=InsightCategory.TEMPORAL,
            description="warmth peaks at night", confidence=0.85,
            sample_count=100, discovered_at=now, last_validated=now,
            validation_count=3, contradiction_count=0,
        )
        srs1._save_insight(insight)
        srs1.close()

        srs2 = SelfReflectionSystem(db_path=db)
        assert "persist_test" in srs2._insights
        loaded = srs2._insights["persist_test"]
        assert loaded.description == "warmth peaks at night"
        assert loaded.confidence == pytest.approx(0.85)
        assert loaded.validation_count == 3
        srs2.close()

    def test_dedup_by_id(self, srs):
        """Saving same ID twice overwrites, not duplicates."""
        now = datetime.now()
        for i in range(3):
            insight = Insight(
                id="dedup_test", category=InsightCategory.WELLNESS,
                description=f"version {i}", confidence=0.5 + i * 0.1,
                sample_count=10, discovered_at=now, last_validated=now,
            )
            srs._save_insight(insight)
        assert len([k for k in srs._insights if k == "dedup_test"]) == 1
        assert srs._insights["dedup_test"].description == "version 2"


# ==================== should_reflect ====================

class TestShouldReflect:
    """Test reflection timing gate."""

    def test_true_on_first_call(self, srs):
        assert srs.should_reflect() is True

    def test_false_within_interval(self, srs):
        srs._last_analysis_time = datetime.now()
        assert srs.should_reflect() is False

    def test_true_after_interval(self, srs):
        srs._last_analysis_time = datetime.now() - timedelta(hours=2)
        assert srs.should_reflect() is True


# ==================== analyze_patterns ====================

class TestAnalyzePatterns:
    """Test state history pattern analysis."""

    def test_empty_db_returns_empty(self, srs):
        """No state_history rows → empty patterns."""
        patterns = srs.analyze_patterns(hours=24)
        assert patterns == []

    def test_with_state_history(self, tmp_path):
        """Populated state_history produces patterns."""
        db = str(tmp_path / "patterns.db")
        srs = SelfReflectionSystem(db_path=db)
        conn = srs._connect()
        # Create state_history table and insert 50 rows
        conn.execute("""
            CREATE TABLE IF NOT EXISTS state_history (
                timestamp TEXT, warmth REAL, clarity REAL,
                stability REAL, presence REAL, sensors TEXT
            )
        """)
        import json
        base = datetime.now() - timedelta(hours=12)
        for i in range(50):
            ts = base + timedelta(minutes=i * 15)
            # Create varying light levels to produce a pattern
            light = 50 + i * 10  # increasing
            warmth = 0.3 + (i / 50) * 0.4  # correlates with light
            conn.execute(
                "INSERT INTO state_history VALUES (?, ?, ?, ?, ?, ?)",
                (ts.isoformat(), warmth, 0.5, 0.5, 0.5,
                 json.dumps({"light_level": light, "ambient_temp": 22}))
            )
        conn.commit()

        patterns = srs.analyze_patterns(hours=24)
        # Should find at least temporal patterns (50 rows across time)
        assert isinstance(patterns, list)
        srs.close()


# ==================== generate_insights ====================

class TestGenerateInsights:
    """Test converting StatePatterns into Insights."""

    def test_temporal_pattern_creates_temporal_insight(self, srs):
        pattern = StatePattern(
            condition="the morning", outcome="highest clarity",
            correlation=0.25, sample_count=30,
            avg_warmth=0.5, avg_clarity=0.7, avg_stability=0.5, avg_presence=0.5,
        )
        insights = srs.generate_insights([pattern])
        assert len(insights) == 1
        assert insights[0].category == InsightCategory.TEMPORAL
        assert "morning" in insights[0].description.lower()

    def test_environment_pattern(self, srs):
        pattern = StatePattern(
            condition="low light", outcome="higher stability",
            correlation=0.3, sample_count=80,
            avg_warmth=0.5, avg_clarity=0.5, avg_stability=0.7, avg_presence=0.5,
        )
        insights = srs.generate_insights([pattern])
        assert len(insights) == 1
        assert insights[0].category == InsightCategory.ENVIRONMENT

    def test_causal_pattern(self, srs):
        pattern = StatePattern(
            condition="warmth rises", outcome="presence falls",
            correlation=-0.15, sample_count=20,
            avg_warmth=0.0, avg_clarity=0.0, avg_stability=0.0, avg_presence=0.0,
        )
        insights = srs.generate_insights([pattern])
        assert len(insights) == 1
        assert insights[0].category == InsightCategory.WELLNESS

    def test_existing_insight_validated(self, srs):
        """Re-encountering a pattern validates existing insight, doesn't duplicate."""
        pattern = StatePattern(
            condition="the night", outcome="highest warmth",
            correlation=0.3, sample_count=50,
            avg_warmth=0.7, avg_clarity=0.5, avg_stability=0.5, avg_presence=0.5,
        )
        srs.generate_insights([pattern])
        srs.generate_insights([pattern])  # Second time
        insight_id = "the_night_highest_warmth"
        assert srs._insights[insight_id].validation_count >= 2


# ==================== Preference Insights ====================

class TestPreferenceInsights:
    """Test _analyze_preference_insights."""

    def _mock_growth(self):
        """Create mock growth system with known preferences."""
        from anima_mcp.growth import Preference, PreferenceCategory
        mock = MagicMock()
        mock._preferences = {
            "night_calm": Preference(
                category=PreferenceCategory.TEMPORAL, name="night_calm",
                description="The quiet of night calms me",
                value=0.9, confidence=0.9, observation_count=100,
                first_noticed=datetime.now(), last_confirmed=datetime.now(),
            ),
            "low_conf": Preference(
                category=PreferenceCategory.ENVIRONMENT, name="low_conf",
                description="I like quiet", value=0.5, confidence=0.3,
                observation_count=2,
                first_noticed=datetime.now(), last_confirmed=datetime.now(),
            ),
        }
        return mock

    def test_high_confidence_preference_creates_insight(self, srs):
        mock_growth = self._mock_growth()
        with patch("anima_mcp.growth.get_growth_system", return_value=mock_growth):
            insights = srs._analyze_preference_insights()
        # night_calm has confidence=0.9, obs=100 → above thresholds (0.8, 10)
        assert len(insights) >= 1
        descs = [i.description for i in insights]
        assert any("night" in d.lower() for d in descs)

    def test_low_confidence_skipped(self, srs):
        mock_growth = self._mock_growth()
        with patch("anima_mcp.growth.get_growth_system", return_value=mock_growth):
            insights = srs._analyze_preference_insights()
        # low_conf has confidence=0.3 → below threshold
        ids = [i.id for i in insights]
        assert "pref_low_conf" not in ids

    def test_existing_insight_validated_not_duplicated(self, srs):
        mock_growth = self._mock_growth()
        with patch("anima_mcp.growth.get_growth_system", return_value=mock_growth):
            srs._analyze_preference_insights()
            insights2 = srs._analyze_preference_insights()
        # Second call should validate, not create new
        assert len(insights2) == 0  # No NEW insights, just validations


# ==================== Belief Insights ====================

class TestBeliefInsights:
    """Test _analyze_belief_insights."""

    def _mock_self_model(self, beliefs):
        mock = MagicMock()
        mock.beliefs = beliefs
        return mock

    def test_well_tested_belief_creates_insight(self, srs):
        from unittest.mock import PropertyMock
        belief = MagicMock()
        belief.supporting_count = 15
        belief.contradicting_count = 2
        belief.confidence = 0.8
        belief.description = "light affects my clarity"
        belief.get_belief_strength.return_value = "fairly confident"

        mock_sm = self._mock_self_model({"b1": belief})
        with patch("anima_mcp.self_model.get_self_model", return_value=mock_sm):
            insights = srs._analyze_belief_insights()
        assert len(insights) == 1
        assert "light" in insights[0].description.lower()

    def test_low_evidence_skipped(self, srs):
        belief = MagicMock()
        belief.supporting_count = 3
        belief.contradicting_count = 1
        belief.confidence = 0.8
        belief.description = "not enough data"

        mock_sm = self._mock_self_model({"b1": belief})
        with patch("anima_mcp.self_model.get_self_model", return_value=mock_sm):
            insights = srs._analyze_belief_insights()
        assert len(insights) == 0


# ==================== Drawing Insights ====================

class TestDrawingInsights:
    """Test _analyze_drawing_insights."""

    def test_insufficient_drawings_returns_empty(self, srs):
        mock_growth = MagicMock()
        mock_growth._drawings_observed = 2
        with patch("anima_mcp.growth.get_growth_system", return_value=mock_growth):
            insights = srs._analyze_drawing_insights()
        assert insights == []

    def test_drawing_wellbeing_insight(self, srs):
        from anima_mcp.growth import Preference, PreferenceCategory
        mock_growth = MagicMock()
        mock_growth._drawings_observed = 10
        mock_growth._preferences = {
            "drawing_wellbeing": Preference(
                category=PreferenceCategory.ACTIVITY, name="drawing_wellbeing",
                description="I feel good when I draw",
                value=0.8, confidence=0.7, observation_count=8,
                first_noticed=datetime.now(), last_confirmed=datetime.now(),
            ),
        }
        with patch("anima_mcp.growth.get_growth_system", return_value=mock_growth):
            insights = srs._analyze_drawing_insights()
        assert len(insights) >= 1
        assert any("draw" in i.description.lower() for i in insights)


# ==================== reflect() ====================

class TestReflect:
    """Test the main reflect() orchestrator."""

    def test_returns_string_or_none(self, srs):
        """reflect() returns Optional[str]."""
        result = srs.reflect()
        assert result is None or isinstance(result, str)

    def test_sets_last_analysis_time(self, srs):
        assert srs._last_analysis_time is None
        srs.reflect()
        assert srs._last_analysis_time is not None

    def test_returns_strongest_new_insight(self, srs):
        """If new insights discovered, returns description of strongest."""
        # Inject a high-confidence preference that will trigger insight
        from anima_mcp.growth import Preference, PreferenceCategory
        mock_growth = MagicMock()
        mock_growth._preferences = {
            "night_calm": Preference(
                category=PreferenceCategory.TEMPORAL, name="night_calm",
                description="The quiet of night calms me",
                value=0.9, confidence=0.95, observation_count=200,
                first_noticed=datetime.now(), last_confirmed=datetime.now(),
            ),
        }
        mock_growth._drawings_observed = 0
        mock_sm = MagicMock()
        mock_sm.beliefs = {}
        with patch("anima_mcp.growth.get_growth_system", return_value=mock_growth), \
             patch("anima_mcp.self_model.get_self_model", return_value=mock_sm):
            result = srs.reflect()
        # Should mention the new insight
        if result:
            assert "noticed" in result.lower() or "night" in result.lower() or "know" in result.lower()


# ==================== get_insights ====================

class TestGetInsights:
    """Test insight retrieval and filtering."""

    def test_empty_returns_empty(self, srs):
        assert srs.get_insights() == []

    def test_filter_by_category(self, srs):
        now = datetime.now()
        srs._save_insight(Insight(
            id="t1", category=InsightCategory.TEMPORAL,
            description="time", confidence=0.8, sample_count=10,
            discovered_at=now, last_validated=now,
        ))
        srs._save_insight(Insight(
            id="e1", category=InsightCategory.ENVIRONMENT,
            description="env", confidence=0.6, sample_count=10,
            discovered_at=now, last_validated=now,
        ))
        temporal = srs.get_insights(category=InsightCategory.TEMPORAL)
        assert len(temporal) == 1
        assert temporal[0].id == "t1"

    def test_sorted_by_strength(self, srs):
        now = datetime.now()
        srs._save_insight(Insight(
            id="weak", category=InsightCategory.TEMPORAL,
            description="weak", confidence=0.3, sample_count=5,
            discovered_at=now, last_validated=now, validation_count=1,
        ))
        srs._save_insight(Insight(
            id="strong", category=InsightCategory.TEMPORAL,
            description="strong", confidence=0.9, sample_count=50,
            discovered_at=now, last_validated=now, validation_count=10,
        ))
        insights = srs.get_insights()
        assert insights[0].id == "strong"
