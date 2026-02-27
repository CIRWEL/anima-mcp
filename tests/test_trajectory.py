"""
Comprehensive tests for trajectory identity module.

Tests the core trajectory identity framework:
- TrajectorySignature computation and comparison
- Similarity calculations (fixed weights and adaptive)
- Anomaly detection (single-tier and two-tier)
- Component extraction and aggregation
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from anima_mcp.trajectory import (
    TrajectorySignature,
    compute_trajectory_signature,
    compare_signatures,
    save_genesis,
    load_genesis,
    save_trajectory,
    load_trajectory,
    GENESIS_MIN_OBSERVATIONS,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def empty_signature():
    """Signature with no data."""
    return TrajectorySignature()


@pytest.fixture
def minimal_signature():
    """Signature with minimal data."""
    return TrajectorySignature(
        preferences={"vector": [0.5, 0.5, 0.5, 0.5]},
        observation_count=10,
    )


@pytest.fixture
def full_signature():
    """Signature with all components populated."""
    return TrajectorySignature(
        preferences={
            "vector": [0.7, 0.3, 0.5, 0.8, 0.2, 0.6, 0.4, 0.9],
            "n_learned": 5,
        },
        beliefs={
            "values": [0.8, 0.6, 0.7, 0.5],
            "avg_confidence": 0.75,
        },
        attractor={
            "center": [0.6, 0.5, 0.7, 0.6],
            "variance": [0.01, 0.02, 0.01, 0.02],
        },
        recovery={
            "tau_estimate": 3.5,
            "confidence": 0.8,
            "n_episodes": 12,
        },
        relational={
            "valence_tendency": 0.3,
            "n_relationships": 4,
        },
        observation_count=100,
    )


@pytest.fixture
def similar_signature(full_signature):
    """Signature similar to full_signature."""
    return TrajectorySignature(
        preferences={
            "vector": [0.72, 0.28, 0.52, 0.78, 0.22, 0.58, 0.42, 0.88],
            "n_learned": 5,
        },
        beliefs={
            "values": [0.82, 0.58, 0.72, 0.48],
            "avg_confidence": 0.73,
        },
        attractor={
            "center": [0.58, 0.52, 0.68, 0.62],
            "variance": [0.01, 0.02, 0.01, 0.02],
        },
        recovery={
            "tau_estimate": 3.7,
            "confidence": 0.78,
            "n_episodes": 14,
        },
        relational={
            "valence_tendency": 0.35,
            "n_relationships": 5,
        },
        observation_count=110,
    )


@pytest.fixture
def different_signature():
    """Signature very different from full_signature."""
    return TrajectorySignature(
        preferences={
            "vector": [0.1, 0.9, 0.1, 0.1, 0.9, 0.1, 0.9, 0.1],
            "n_learned": 3,
        },
        beliefs={
            "values": [0.2, 0.9, 0.3, 0.8],
            "avg_confidence": 0.5,
        },
        attractor={
            "center": [0.2, 0.8, 0.3, 0.2],
            "variance": [0.05, 0.04, 0.05, 0.04],
        },
        recovery={
            "tau_estimate": 10.0,
            "confidence": 0.5,
            "n_episodes": 5,
        },
        relational={
            "valence_tendency": -0.5,
            "n_relationships": 1,
        },
        observation_count=30,
    )


# =============================================================================
# Test: Cosine Similarity
# =============================================================================

class TestCosineSimilarity:
    """Tests for _cosine_similarity helper method."""

    def test_identical_vectors(self, empty_signature):
        """Identical vectors should have similarity 1.0."""
        v = [1.0, 2.0, 3.0]
        result = empty_signature._cosine_similarity(v, v)
        assert result == pytest.approx(1.0)

    def test_orthogonal_vectors(self, empty_signature):
        """Orthogonal vectors should have similarity 0.0."""
        v1 = [1.0, 0.0]
        v2 = [0.0, 1.0]
        result = empty_signature._cosine_similarity(v1, v2)
        assert result == pytest.approx(0.0)

    def test_opposite_vectors(self, empty_signature):
        """Opposite vectors should have similarity -1.0."""
        v1 = [1.0, 2.0, 3.0]
        v2 = [-1.0, -2.0, -3.0]
        result = empty_signature._cosine_similarity(v1, v2)
        assert result == pytest.approx(-1.0)

    def test_different_lengths_returns_none(self, empty_signature):
        """Vectors of different lengths should return None."""
        v1 = [1.0, 2.0, 3.0]
        v2 = [1.0, 2.0]
        result = empty_signature._cosine_similarity(v1, v2)
        assert result is None

    def test_empty_vectors_returns_none(self, empty_signature):
        """Empty vectors should return None."""
        result = empty_signature._cosine_similarity([], [])
        assert result is None

    def test_zero_vector_returns_none(self, empty_signature):
        """Zero vectors should return None (division by zero)."""
        v1 = [0.0, 0.0, 0.0]
        v2 = [1.0, 2.0, 3.0]
        result = empty_signature._cosine_similarity(v1, v2)
        assert result is None

    def test_normalized_vectors(self, empty_signature):
        """Test with unit vectors."""
        import math
        v1 = [1/math.sqrt(2), 1/math.sqrt(2)]
        v2 = [1.0, 0.0]
        result = empty_signature._cosine_similarity(v1, v2)
        assert result == pytest.approx(1/math.sqrt(2))


# =============================================================================
# Test: Similarity Computation
# =============================================================================

class TestSimilarity:
    """Tests for similarity() method."""

    def test_identical_signatures(self, full_signature):
        """Identical signatures should have high similarity."""
        sim = full_signature.similarity(full_signature)
        assert sim == pytest.approx(1.0, abs=0.01)

    def test_similar_signatures(self, full_signature, similar_signature):
        """Similar signatures should have similarity > 0.8."""
        sim = full_signature.similarity(similar_signature)
        assert sim > 0.8

    def test_different_signatures(self, full_signature, different_signature):
        """Different signatures should have lower similarity."""
        sim = full_signature.similarity(different_signature)
        assert sim < 0.7

    def test_empty_signatures_return_default(self, empty_signature):
        """Empty signatures should return 0.5 (no data)."""
        other = TrajectorySignature()
        sim = empty_signature.similarity(other)
        assert sim == 0.5

    def test_partial_signature_uses_available_components(self, minimal_signature):
        """Partial signatures should use available components only."""
        other = TrajectorySignature(
            preferences={"vector": [0.5, 0.5, 0.5, 0.5]},
        )
        sim = minimal_signature.similarity(other)
        assert 0 <= sim <= 1

    def test_symmetry(self, full_signature, similar_signature):
        """Similarity should be symmetric."""
        sim1 = full_signature.similarity(similar_signature)
        sim2 = similar_signature.similarity(full_signature)
        assert sim1 == pytest.approx(sim2, abs=0.001)

    def test_range(self, full_signature, different_signature):
        """Similarity should always be in [0, 1]."""
        sim = full_signature.similarity(different_signature)
        assert 0 <= sim <= 1


# =============================================================================
# Test: Adaptive Similarity
# =============================================================================

class TestSimilarityAdaptive:
    """Tests for similarity_adaptive() method."""

    def test_returns_dict_with_similarity(self, full_signature, similar_signature):
        """Should return dict with similarity score."""
        result = full_signature.similarity_adaptive(similar_signature)
        assert "similarity" in result
        assert 0 <= result["similarity"] <= 1

    def test_returns_component_breakdown(self, full_signature, similar_signature):
        """Should return per-component scores."""
        result = full_signature.similarity_adaptive(similar_signature)
        assert "components" in result
        assert isinstance(result["components"], dict)

    def test_returns_weights(self, full_signature, similar_signature):
        """Should return weight values."""
        result = full_signature.similarity_adaptive(similar_signature)
        assert "weights" in result
        assert isinstance(result["weights"], dict)

    def test_updates_history(self, full_signature, similar_signature):
        """Should update component history when update_history=True."""
        full_signature.similarity_adaptive(similar_signature, update_history=True)
        assert len(full_signature.component_history) > 0

    def test_no_update_when_disabled(self, full_signature, similar_signature):
        """Should not update history when update_history=False."""
        original_history = dict(full_signature.component_history)
        full_signature.similarity_adaptive(similar_signature, update_history=False)
        assert full_signature.component_history == original_history

    def test_history_limit(self, full_signature, similar_signature):
        """History should be limited to 100 entries per component."""
        # Add many entries
        for _ in range(120):
            full_signature.similarity_adaptive(similar_signature, update_history=True)

        for component, history in full_signature.component_history.items():
            assert len(history) <= 100


# =============================================================================
# Test: Is Same Identity
# =============================================================================

class TestIsSameIdentity:
    """Tests for is_same_identity() method."""

    def test_identical_is_same(self, full_signature):
        """Identical signatures should be same identity."""
        assert full_signature.is_same_identity(full_signature)

    def test_similar_is_same(self, full_signature, similar_signature):
        """Similar signatures should be same identity."""
        assert full_signature.is_same_identity(similar_signature)

    def test_different_is_not_same(self, full_signature, different_signature):
        """Different signatures should not be same identity."""
        assert not full_signature.is_same_identity(different_signature)

    def test_custom_threshold(self, full_signature, similar_signature):
        """Should respect custom threshold."""
        # Very high threshold should fail even for similar
        assert not full_signature.is_same_identity(similar_signature, threshold=0.99)
        # Very low threshold should pass even for different
        assert full_signature.is_same_identity(similar_signature, threshold=0.5)


# =============================================================================
# Test: Anomaly Detection
# =============================================================================

class TestDetectAnomaly:
    """Tests for detect_anomaly() method."""

    def test_similar_not_anomaly(self, full_signature, similar_signature):
        """Similar signatures should not be anomalous."""
        result = full_signature.detect_anomaly(similar_signature)
        assert not result["is_anomaly"]

    def test_different_is_anomaly(self, full_signature, different_signature):
        """Different signatures should be anomalous."""
        result = full_signature.detect_anomaly(different_signature)
        assert result["is_anomaly"]

    def test_returns_similarity(self, full_signature, similar_signature):
        """Should return similarity score."""
        result = full_signature.detect_anomaly(similar_signature)
        assert "similarity" in result
        assert 0 <= result["similarity"] <= 1

    def test_returns_deviation(self, full_signature, similar_signature):
        """Should return deviation = 1 - similarity."""
        result = full_signature.detect_anomaly(similar_signature)
        assert "deviation" in result
        assert result["deviation"] == pytest.approx(1 - result["similarity"], abs=0.001)

    def test_custom_threshold(self, full_signature, similar_signature):
        """Should respect custom threshold."""
        result_low = full_signature.detect_anomaly(similar_signature, threshold=0.5)
        result_high = full_signature.detect_anomaly(similar_signature, threshold=0.99)
        assert not result_low["is_anomaly"]
        assert result_high["is_anomaly"]


# =============================================================================
# Test: Two-Tier Anomaly Detection
# =============================================================================

class TestDetectAnomalyTwoTier:
    """Tests for detect_anomaly_two_tier() method."""

    def test_both_tiers_pass(self, full_signature, similar_signature):
        """Both tiers passing should not be anomaly."""
        # Set genesis to similar signature
        full_signature.genesis_signature = similar_signature
        result = full_signature.detect_anomaly_two_tier(similar_signature)
        assert not result["is_anomaly"]
        assert result["coherence"]["passed"]
        assert result["lineage"]["passed"]

    def test_coherence_fails(self, full_signature, different_signature, similar_signature):
        """Coherence failure should trigger anomaly."""
        full_signature.genesis_signature = similar_signature
        result = full_signature.detect_anomaly_two_tier(different_signature)
        assert result["is_anomaly"]
        assert not result["coherence"]["passed"]

    def test_lineage_fails(self, full_signature, similar_signature, different_signature):
        """Lineage failure should trigger anomaly."""
        full_signature.genesis_signature = different_signature
        result = full_signature.detect_anomaly_two_tier(similar_signature)
        assert result["is_anomaly"]
        assert not result["lineage"]["passed"]

    def test_no_genesis_skips_lineage(self, full_signature, similar_signature):
        """No genesis should skip lineage check (pass by default)."""
        full_signature.genesis_signature = None
        result = full_signature.detect_anomaly_two_tier(similar_signature)
        assert not result["lineage"]["has_genesis"]
        assert result["lineage"]["passed"]

    def test_tier_failed_indicates_which(self, full_signature, different_signature):
        """tier_failed should indicate which tier failed."""
        result = full_signature.detect_anomaly_two_tier(different_signature)
        assert result["tier_failed"] in ["coherence", "lineage", None]


# =============================================================================
# Test: Lineage Similarity
# =============================================================================

class TestLineageSimilarity:
    """Tests for lineage_similarity() method."""

    def test_no_genesis_returns_none(self, full_signature):
        """No genesis signature should return None."""
        full_signature.genesis_signature = None
        result = full_signature.lineage_similarity()
        assert result is None

    def test_with_genesis_returns_similarity(self, full_signature, similar_signature):
        """With genesis, should return similarity score."""
        full_signature.genesis_signature = similar_signature
        result = full_signature.lineage_similarity()
        assert result is not None
        assert 0 <= result <= 1

    def test_identical_genesis_returns_one(self, full_signature):
        """Identical genesis should return ~1.0."""
        full_signature.genesis_signature = full_signature
        result = full_signature.lineage_similarity()
        assert result == pytest.approx(1.0, abs=0.01)


# =============================================================================
# Test: Identity Confidence
# =============================================================================

class TestIdentityConfidence:
    """Tests for identity_confidence property."""

    def test_cold_start_low_confidence(self):
        """Few observations should mean low confidence."""
        sig = TrajectorySignature(observation_count=5)
        assert sig.identity_confidence < 0.2

    def test_cold_start_saturates_at_50(self):
        """Cold start factor should saturate at 50 observations."""
        # Cold start factor = min(1.0, observation_count / 50)
        # At 50 obs: factor = 1.0
        # At 100 obs: factor = 1.0 (saturated)
        # But stability score continues to grow (saturates at 100)
        sig1 = TrajectorySignature(observation_count=50)
        sig2 = TrajectorySignature(observation_count=100)

        # Both have cold_start_factor = 1.0, but stability differs
        # sig1 stability: min(1.0, 50/100) = 0.5
        # sig2 stability: min(1.0, 100/100) = 1.0
        assert sig1.identity_confidence == pytest.approx(0.5, abs=0.01)
        assert sig2.identity_confidence == pytest.approx(1.0, abs=0.01)

    def test_confidence_in_range(self, full_signature):
        """Confidence should be in [0, 1]."""
        assert 0 <= full_signature.identity_confidence <= 1


# =============================================================================
# Test: Stability Score
# =============================================================================

class TestGetStabilityScore:
    """Tests for get_stability_score() method."""

    def test_empty_signature_returns_zero(self, empty_signature):
        """Empty signature should have stability 0."""
        assert empty_signature.get_stability_score() == 0.0

    def test_full_signature_higher_stability(self, full_signature):
        """Full signature should have higher stability."""
        assert full_signature.get_stability_score() > 0.5

    def test_observation_count_factors_in(self):
        """More observations should increase stability."""
        sig1 = TrajectorySignature(observation_count=10)
        sig2 = TrajectorySignature(observation_count=100)
        assert sig2.get_stability_score() > sig1.get_stability_score()

    def test_stability_in_range(self, full_signature):
        """Stability should be in [0, 1]."""
        assert 0 <= full_signature.get_stability_score() <= 1


# =============================================================================
# Test: Serialization
# =============================================================================

class TestToDict:
    """Tests for to_dict() method."""

    def test_contains_all_components(self, full_signature):
        """Should contain all signature components."""
        d = full_signature.to_dict()
        assert "preferences" in d
        assert "beliefs" in d
        assert "attractor" in d
        assert "recovery" in d
        assert "relational" in d

    def test_contains_metadata(self, full_signature):
        """Should contain metadata fields."""
        d = full_signature.to_dict()
        assert "computed_at" in d
        assert "observation_count" in d
        assert "stability_score" in d

    def test_computed_at_is_isoformat(self, full_signature):
        """computed_at should be ISO format string."""
        d = full_signature.to_dict()
        # Should be parseable as datetime
        datetime.fromisoformat(d["computed_at"])


class TestSummary:
    """Tests for summary() method."""

    def test_contains_key_metrics(self, full_signature):
        """Summary should contain key metrics."""
        s = full_signature.summary()
        assert "identity_confidence" in s
        assert "stability_score" in s
        assert "observation_count" in s
        assert "computed_at" in s

    def test_lineage_included_when_genesis(self, full_signature, similar_signature):
        """Should include lineage_similarity when genesis exists."""
        full_signature.genesis_signature = similar_signature
        s = full_signature.summary()
        assert s["lineage_similarity"] is not None
        assert s["has_genesis"] is True

    def test_lineage_none_without_genesis(self, full_signature):
        """lineage_similarity should be None without genesis."""
        full_signature.genesis_signature = None
        s = full_signature.summary()
        assert s["lineage_similarity"] is None
        assert s["has_genesis"] is False


# =============================================================================
# Test: Compute Trajectory Signature
# =============================================================================

class TestComputeTrajectorySignature:
    """Tests for compute_trajectory_signature() function."""

    def test_no_sources_returns_empty(self):
        """No data sources should return empty signature."""
        sig = compute_trajectory_signature()
        assert sig.preferences == {}
        assert sig.beliefs == {}
        assert sig.attractor is None
        assert sig.recovery == {}
        assert sig.relational == {}

    def test_extracts_preferences_from_growth_system(self):
        """Should extract preferences from GrowthSystem."""
        mock_growth = MagicMock()
        mock_growth.get_preference_vector.return_value = {
            "vector": [0.5, 0.5, 0.5, 0.5],
            "n_learned": 3,
        }

        sig = compute_trajectory_signature(growth_system=mock_growth)
        assert sig.preferences["vector"] == [0.5, 0.5, 0.5, 0.5]

    def test_extracts_beliefs_from_self_model(self):
        """Should extract beliefs from SelfModel."""
        mock_self = MagicMock()
        mock_self.get_belief_signature.return_value = {
            "values": [0.8, 0.6, 0.7],
            "avg_confidence": 0.7,
        }

        sig = compute_trajectory_signature(self_model=mock_self)
        assert sig.beliefs["values"] == [0.8, 0.6, 0.7]

    def test_extracts_attractor_from_anima_history(self):
        """Should extract attractor from AnimaHistory."""
        mock_history = MagicMock()
        mock_history.get_attractor_basin.return_value = {
            "center": [0.5, 0.5, 0.5, 0.5],
            "n_observations": 50,
        }

        sig = compute_trajectory_signature(anima_history=mock_history)
        assert sig.attractor["center"] == [0.5, 0.5, 0.5, 0.5]
        assert sig.observation_count == 50

    def test_extracts_recovery_from_self_model(self):
        """Should extract recovery from SelfModel."""
        mock_self = MagicMock()
        mock_self.get_belief_signature.return_value = {}
        mock_self.get_recovery_profile.return_value = {
            "tau_estimate": 3.5,
            "confidence": 0.8,
        }

        sig = compute_trajectory_signature(self_model=mock_self)
        assert sig.recovery["tau_estimate"] == 3.5

    def test_extracts_relational_from_growth_system(self):
        """Should extract relational from GrowthSystem."""
        mock_growth = MagicMock()
        mock_growth.get_preference_vector.return_value = {}
        mock_growth.get_relational_disposition.return_value = {
            "valence_tendency": 0.3,
            "n_relationships": 5,
        }

        sig = compute_trajectory_signature(growth_system=mock_growth)
        assert sig.relational["valence_tendency"] == 0.3

    def test_handles_extraction_errors_gracefully(self):
        """Should handle errors in component extraction."""
        mock_growth = MagicMock()
        mock_growth.get_preference_vector.side_effect = Exception("Test error")
        mock_growth.get_relational_disposition.return_value = {"valence_tendency": 0.5}

        # Should not raise, should continue with other components
        sig = compute_trajectory_signature(growth_system=mock_growth)
        assert sig.preferences == {}
        assert sig.relational["valence_tendency"] == 0.5


# =============================================================================
# Test: Compare Signatures
# =============================================================================

class TestCompareSignatures:
    """Tests for compare_signatures() function."""

    def test_returns_overall_similarity(self, full_signature, similar_signature):
        """Should return overall similarity score."""
        result = compare_signatures(full_signature, similar_signature)
        assert "overall_similarity" in result
        assert 0 <= result["overall_similarity"] <= 1

    def test_returns_component_breakdown(self, full_signature, similar_signature):
        """Should return per-component breakdown."""
        result = compare_signatures(full_signature, similar_signature)
        assert "components" in result
        assert isinstance(result["components"], dict)

    def test_returns_is_same_identity(self, full_signature, similar_signature):
        """Should return is_same_identity boolean."""
        result = compare_signatures(full_signature, similar_signature)
        assert "is_same_identity" in result
        assert isinstance(result["is_same_identity"], bool)

    def test_similar_signatures_same_identity(self, full_signature, similar_signature):
        """Similar signatures should be same identity."""
        result = compare_signatures(full_signature, similar_signature)
        assert result["is_same_identity"] is True

    def test_different_signatures_not_same_identity(self, full_signature, different_signature):
        """Different signatures should not be same identity."""
        result = compare_signatures(full_signature, different_signature)
        assert result["is_same_identity"] is False


# =============================================================================
# Test: Edge Cases
# =============================================================================

class TestEdgeCases:
    """Edge case and boundary condition tests."""

    def test_single_component_signature(self):
        """Signature with only one component should work."""
        sig1 = TrajectorySignature(
            preferences={"vector": [1.0, 0.0, 0.0, 0.0]},
        )
        sig2 = TrajectorySignature(
            preferences={"vector": [0.9, 0.1, 0.0, 0.0]},
        )
        sim = sig1.similarity(sig2)
        assert 0 < sim < 1

    def test_mismatched_vector_lengths(self):
        """Mismatched vector lengths should handle gracefully."""
        sig1 = TrajectorySignature(
            preferences={"vector": [1.0, 0.0]},
        )
        sig2 = TrajectorySignature(
            preferences={"vector": [1.0, 0.0, 0.0, 0.0]},
        )
        sim = sig1.similarity(sig2)
        # Should return 0.5 (no valid comparison)
        assert sim == 0.5

    def test_zero_tau_handled(self):
        """Zero tau_estimate should not cause division by zero."""
        sig1 = TrajectorySignature(recovery={"tau_estimate": 0.0})
        sig2 = TrajectorySignature(recovery={"tau_estimate": 3.0})
        sim = sig1.similarity(sig2)
        # Should not raise, should skip recovery component
        assert 0 <= sim <= 1

    def test_negative_tau_handled(self):
        """Negative tau_estimate should be handled."""
        sig1 = TrajectorySignature(recovery={"tau_estimate": -1.0})
        sig2 = TrajectorySignature(recovery={"tau_estimate": 3.0})
        sim = sig1.similarity(sig2)
        # Should not raise
        assert 0 <= sim <= 1

    def test_very_large_vectors(self):
        """Very large vectors should work."""
        large_vector = [0.5] * 1000
        sig1 = TrajectorySignature(preferences={"vector": large_vector})
        sig2 = TrajectorySignature(preferences={"vector": large_vector})
        sim = sig1.similarity(sig2)
        assert sim == pytest.approx(1.0, abs=0.01)

    def test_extreme_valence_values(self):
        """Extreme valence values (-1, 1) should work."""
        sig1 = TrajectorySignature(relational={"valence_tendency": -1.0})
        sig2 = TrajectorySignature(relational={"valence_tendency": 1.0})
        sim = sig1.similarity(sig2)
        # Maximum difference should give low similarity
        assert sim < 0.5

    def test_observation_count_zero(self):
        """Zero observation count should work."""
        sig = TrajectorySignature(observation_count=0)
        assert sig.identity_confidence == 0.0

    def test_observation_count_very_large(self):
        """Very large observation count should saturate properly."""
        sig = TrajectorySignature(observation_count=10000)
        # Cold start factor should be exactly 1.0
        assert sig.identity_confidence <= 1.0


# =============================================================================
# Test: Adaptive Weights
# =============================================================================

class TestAdaptiveWeights:
    """Tests for compute_adaptive_weights() method."""

    def test_no_history_returns_defaults(self, full_signature):
        """No history should return default weights."""
        full_signature.component_history = {}
        weights = full_signature.compute_adaptive_weights()
        assert "preferences" in weights
        assert "beliefs" in weights
        assert "attractor" in weights

    def test_insufficient_history_returns_defaults(self, full_signature):
        """Less than 5 observations should return defaults."""
        full_signature.component_history = {
            "preferences": [0.8, 0.9, 0.85],  # Only 3 entries
        }
        weights = full_signature.compute_adaptive_weights()
        # Should still use defaults for preferences
        assert weights["preferences"] == pytest.approx(0.15, abs=0.01)

    def test_low_variance_gets_higher_weight(self, full_signature):
        """Low variance component should get higher weight."""
        full_signature.component_history = {
            "preferences": [0.9, 0.9, 0.9, 0.9, 0.9],  # Low variance
            "beliefs": [0.3, 0.9, 0.5, 0.7, 0.2],      # High variance
        }
        weights = full_signature.compute_adaptive_weights()
        # Preferences should have higher weight (lower variance)
        if "preferences" in weights and "beliefs" in weights:
            assert weights["preferences"] > weights["beliefs"]


# =============================================================================
# Test: Serialization (from_dict / to_dict roundtrip)
# =============================================================================

class TestSerialization:
    """Tests for to_dict() / from_dict() roundtrip."""

    def test_empty_roundtrip(self, empty_signature):
        """Empty signature should roundtrip."""
        data = empty_signature.to_dict()
        restored = TrajectorySignature.from_dict(data)
        assert restored.preferences == {}
        assert restored.beliefs == {}
        assert restored.attractor is None
        assert restored.observation_count == 0

    def test_full_roundtrip(self, full_signature):
        """Full signature should roundtrip all fields."""
        data = full_signature.to_dict()
        restored = TrajectorySignature.from_dict(data)
        assert restored.preferences == full_signature.preferences
        assert restored.beliefs == full_signature.beliefs
        assert restored.attractor == full_signature.attractor
        assert restored.recovery == full_signature.recovery
        assert restored.relational == full_signature.relational
        assert restored.observation_count == full_signature.observation_count

    def test_genesis_included_in_dict(self, full_signature, similar_signature):
        """to_dict should include genesis when present."""
        full_signature.genesis_signature = similar_signature
        data = full_signature.to_dict()
        assert "genesis_signature" in data
        assert data["genesis_signature"]["observation_count"] == similar_signature.observation_count

    def test_genesis_not_in_dict_when_none(self, full_signature):
        """to_dict should omit genesis when None."""
        full_signature.genesis_signature = None
        data = full_signature.to_dict()
        assert "genesis_signature" not in data

    def test_from_dict_invalid_date(self):
        """Invalid date string should fall back to now."""
        data = {"computed_at": "not-a-date", "observation_count": 5}
        sig = TrajectorySignature.from_dict(data)
        assert isinstance(sig.computed_at, datetime)
        assert sig.observation_count == 5

    def test_similarity_preserved_after_roundtrip(self, full_signature, similar_signature):
        """Similarity should be same before and after serialization."""
        sim_before = full_signature.similarity(similar_signature)
        restored = TrajectorySignature.from_dict(full_signature.to_dict())
        sim_after = restored.similarity(similar_signature)
        assert sim_before == pytest.approx(sim_after, abs=0.001)


# =============================================================================
# Test: Genesis Persistence
# =============================================================================

class TestGenesisPersistence:
    """Tests for save_genesis() and load_genesis()."""

    def test_save_and_load_roundtrip(self, full_signature, tmp_path):
        """Genesis should roundtrip through file."""
        genesis_path = tmp_path / "genesis.json"
        assert save_genesis(full_signature, path=genesis_path) is True
        loaded = load_genesis(path=genesis_path)
        assert loaded is not None
        assert loaded.observation_count == full_signature.observation_count
        assert loaded.preferences == full_signature.preferences

    def test_save_is_write_once(self, full_signature, tmp_path):
        """Second save should return False (never overwrites)."""
        genesis_path = tmp_path / "genesis.json"
        assert save_genesis(full_signature, path=genesis_path) is True
        # Second save should fail
        sig2 = TrajectorySignature(observation_count=999)
        assert save_genesis(sig2, path=genesis_path) is False
        # Should still be the original
        import anima_mcp.trajectory as tmod
        tmod._cached_genesis = None  # Clear cache to force re-read
        loaded = load_genesis(path=genesis_path)
        assert loaded.observation_count == full_signature.observation_count

    def test_load_nonexistent_returns_none(self, tmp_path):
        """Loading from nonexistent path should return None."""
        import anima_mcp.trajectory as tmod
        tmod._cached_genesis = None
        assert load_genesis(path=tmp_path / "nonexistent.json") is None

    def test_load_caches(self, full_signature, tmp_path):
        """Second load should use cache."""
        import anima_mcp.trajectory as tmod
        genesis_path = tmp_path / "genesis.json"
        save_genesis(full_signature, path=genesis_path)
        # Clear cache, load, verify cached
        tmod._cached_genesis = None
        first = load_genesis(path=genesis_path)
        second = load_genesis(path=genesis_path)
        assert first is second  # Same object from cache

    def test_compute_creates_genesis_when_mature(self, tmp_path):
        """compute_trajectory_signature should auto-create genesis at threshold."""
        import anima_mcp.trajectory as tmod
        # Clear module-level cache
        tmod._cached_genesis = None

        mock_history = MagicMock()
        mock_history.get_attractor_basin.return_value = {
            "center": [0.5, 0.5, 0.5, 0.5],
            "n_observations": GENESIS_MIN_OBSERVATIONS,
        }

        with patch.object(tmod, '_GENESIS_PATH', tmp_path / "genesis.json"):
            sig = compute_trajectory_signature(anima_history=mock_history)
            # Should have created genesis and attached it
            assert sig.genesis_signature is not None
            assert sig.genesis_signature.observation_count == GENESIS_MIN_OBSERVATIONS
            # File should exist
            assert (tmp_path / "genesis.json").exists()

    def test_compute_skips_genesis_below_threshold(self, tmp_path):
        """compute_trajectory_signature should not create genesis below threshold."""
        import anima_mcp.trajectory as tmod
        tmod._cached_genesis = None

        mock_history = MagicMock()
        mock_history.get_attractor_basin.return_value = {
            "center": [0.5, 0.5, 0.5, 0.5],
            "n_observations": GENESIS_MIN_OBSERVATIONS - 1,
        }

        with patch.object(tmod, '_GENESIS_PATH', tmp_path / "genesis.json"):
            sig = compute_trajectory_signature(anima_history=mock_history)
            assert sig.genesis_signature is None
            assert not (tmp_path / "genesis.json").exists()


# =============================================================================
# Test: Last Trajectory Persistence (save_trajectory / load_trajectory)
# =============================================================================

class TestLastTrajectoryPersistence:
    """Tests for save_trajectory() and load_trajectory() - overwrite semantics."""

    def test_save_and_load_roundtrip(self, full_signature, tmp_path):
        """Last trajectory should roundtrip through file."""
        path = tmp_path / "last.json"
        assert save_trajectory(full_signature, path=path) is True
        loaded = load_trajectory(path=path)
        assert loaded is not None
        assert loaded.observation_count == full_signature.observation_count

    def test_save_overwrites(self, full_signature, tmp_path):
        """Second save should overwrite (unlike genesis)."""
        path = tmp_path / "last.json"
        assert save_trajectory(full_signature, path=path) is True
        sig2 = TrajectorySignature(observation_count=999)
        assert save_trajectory(sig2, path=path) is True
        loaded = load_trajectory(path=path)
        assert loaded.observation_count == 999

    def test_load_nonexistent_returns_none(self, tmp_path):
        """Loading from nonexistent path should return None."""
        assert load_trajectory(path=tmp_path / "nonexistent.json") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
