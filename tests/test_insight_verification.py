"""
Tests for Q&A insight verification against state_history.
"""

import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from anima_mcp.self_reflection import (
    SelfReflectionSystem, InsightCategory,
)


@pytest.fixture
def srs(tmp_path):
    """SelfReflectionSystem with state_history table and sample data."""
    system = SelfReflectionSystem(db_path=str(tmp_path / "verify.db"))
    conn = system._connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS state_history (
            timestamp TEXT, warmth REAL, clarity REAL,
            stability REAL, presence REAL, sensors TEXT
        )
    """)
    conn.commit()
    return system


def _insert_rows(srs, rows):
    """Insert state_history rows. Each row is (warmth, clarity, stability, presence, sensors_dict)."""
    conn = srs._connect()
    base = datetime.now() - timedelta(hours=48)
    for i, (w, c, s, p, sensors) in enumerate(rows):
        ts = (base + timedelta(minutes=i * 10)).isoformat()
        conn.execute(
            "INSERT INTO state_history VALUES (?, ?, ?, ?, ?, ?)",
            (ts, w, c, s, p, json.dumps(sensors)),
        )
    conn.commit()


def _make_light_rows(n=30):
    """Generate rows where high light → high clarity (correlation exists)."""
    rows = []
    for i in range(n):
        light = 10.0 + i * 20  # 10 to 590
        frac = i / (n - 1)     # 0.0 to 1.0
        # clarity tracks light strongly, warmth does not
        rows.append((
            0.5 + (frac * 0.02),   # warmth: nearly flat
            0.3 + (frac * 0.4),    # clarity: rises with light
            0.6,                    # stability: constant
            0.7,                    # presence: constant
            {"light_lux": light, "ambient_temp_c": 22.0},
        ))
    return rows


class TestVerifyQaInsight:
    """Unit tests for _verify_qa_insight()."""

    def test_verify_supported_positive_claim(self, srs):
        """'light affects clarity' against data where high light → high clarity → SUPPORTED."""
        _insert_rows(srs, _make_light_rows(30))
        result = srs._verify_qa_insight("light affects clarity", InsightCategory.ENVIRONMENT)
        assert result.verified is True
        assert result.correlation >= 0.1
        assert "SUPPORTED" in result.detail

    def test_verify_contradicted_positive_claim(self, srs):
        """'light affects warmth' against data where light has no warmth correlation → CONTRADICTED."""
        _insert_rows(srs, _make_light_rows(30))
        result = srs._verify_qa_insight("light affects warmth", InsightCategory.ENVIRONMENT)
        assert result.verified is False
        assert result.correlation < 0.1
        assert "CONTRADICTED" in result.detail

    def test_verify_negative_claim_supported(self, srs):
        """'light doesn't affect warmth' → correlation < 0.1 → SUPPORTED."""
        _insert_rows(srs, _make_light_rows(30))
        result = srs._verify_qa_insight(
            "light doesn't affect warmth", InsightCategory.ENVIRONMENT
        )
        assert result.verified is True
        assert result.correlation < 0.1
        assert "SUPPORTED" in result.detail

    def test_verify_negative_claim_contradicted(self, srs):
        """'light doesn't affect clarity' when data shows strong correlation → CONTRADICTED."""
        _insert_rows(srs, _make_light_rows(30))
        result = srs._verify_qa_insight(
            "light doesn't affect clarity", InsightCategory.ENVIRONMENT
        )
        assert result.verified is False
        assert result.correlation >= 0.1
        assert "CONTRADICTED" in result.detail

    def test_verify_unverifiable_claim(self, srs):
        """'contentment and curiosity can coexist' → no sensor/dimension match → None."""
        _insert_rows(srs, _make_light_rows(30))
        result = srs._verify_qa_insight(
            "contentment and curiosity can coexist", InsightCategory.WELLNESS
        )
        assert result.verified is None

    def test_verify_insufficient_data(self, srs):
        """Not enough rows → verified=None."""
        _insert_rows(srs, _make_light_rows(5))  # only 5 rows
        result = srs._verify_qa_insight("light affects clarity", InsightCategory.ENVIRONMENT)
        assert result.verified is None
        assert "insufficient" in result.detail.lower()

    def test_verify_no_direction_marker(self, srs):
        """Mention sensor+dimension but no direction word → verified=None."""
        _insert_rows(srs, _make_light_rows(30))
        result = srs._verify_qa_insight("light and clarity", InsightCategory.ENVIRONMENT)
        assert result.verified is None


class TestSyncAdjustsConfidence:
    """Integration: sync_from_qa_knowledge adjusts confidence based on verification."""

    def test_sync_contradicted_lowers_confidence(self, srs):
        """A contradicted claim gets confidence * 0.4 after sync."""
        _insert_rows(srs, _make_light_rows(30))

        # Create a mock Q&A insight claiming "light affects warmth" (false per data)
        mock_qa = MagicMock()
        mock_qa.confidence = 1.0
        mock_qa.insight_id = "test_contra"
        mock_qa.text = "light affects warmth"
        mock_qa.category = "sensations"
        mock_qa.references = 1

        mock_kb = MagicMock()
        mock_kb.get_all_insights.return_value = [mock_qa]

        with patch("anima_mcp.knowledge.get_knowledge", return_value=mock_kb):
            synced = srs.sync_from_qa_knowledge()

        assert synced == 1
        stored = srs._insights.get("qa_test_contra")
        assert stored is not None
        assert stored.confidence == pytest.approx(0.4, abs=0.01)
        assert stored.contradiction_count == 1
        assert stored.validation_count == 0

    def test_sync_supported_keeps_confidence(self, srs):
        """A supported claim keeps original confidence."""
        _insert_rows(srs, _make_light_rows(30))

        mock_qa = MagicMock()
        mock_qa.confidence = 1.0
        mock_qa.insight_id = "test_ok"
        mock_qa.text = "light doesn't affect warmth"
        mock_qa.category = "sensations"
        mock_qa.references = 1

        mock_kb = MagicMock()
        mock_kb.get_all_insights.return_value = [mock_qa]

        with patch("anima_mcp.knowledge.get_knowledge", return_value=mock_kb):
            synced = srs.sync_from_qa_knowledge()

        assert synced == 1
        stored = srs._insights.get("qa_test_ok")
        assert stored is not None
        assert stored.confidence == pytest.approx(1.0)
        assert stored.validation_count == 1
        assert stored.contradiction_count == 0
