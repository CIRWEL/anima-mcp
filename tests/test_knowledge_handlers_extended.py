from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from conftest import parse_result


@pytest.mark.asyncio
class TestGetSelfKnowledgeExtended:
    async def test_returns_summary_and_insights(self):
        from anima_mcp.handlers.knowledge import handle_get_self_knowledge

        insight = SimpleNamespace(to_dict=lambda: {"text": "I feel calmer in dim light"})
        reflection = SimpleNamespace(
            _insights=[insight],
            get_insights=lambda category=None: [insight],
            get_self_knowledge_summary=lambda: "dim light helps calm",
        )
        store = SimpleNamespace(db_path=":memory:")

        with patch("anima_mcp.accessors._get_store", return_value=store), \
             patch("anima_mcp.self_reflection.get_reflection_system", return_value=reflection):
            data = parse_result(await handle_get_self_knowledge({"limit": 5}))

        assert data["total_insights"] == 1
        assert data["summary"] == "dim light helps calm"
        assert data["insights"][0]["text"] == "I feel calmer in dim light"

    async def test_belief_view_uses_live_cold_started_evidence(self):
        from anima_mcp.handlers.knowledge import handle_get_self_knowledge

        insight = SimpleNamespace(
            id="belief_light_warmth_correlation",
            to_dict=lambda: {
                "id": "belief_light_warmth_correlation",
                "description": "Light level affects my warmth",
                "confidence": 0.99,
                "sample_count": 500,
                "validation_count": 20,
                "contradiction_count": 0,
            },
        )
        reflection = SimpleNamespace(
            get_insights=lambda category=None: [insight],
            get_self_knowledge_summary=lambda: "historical summary",
        )
        belief = SimpleNamespace(
            confidence=0.5,
            value=0.5,
            supporting_count=0,
            contradicting_count=0,
        )
        self_model = SimpleNamespace(
            beliefs={"light_warmth_correlation": belief}
        )
        store = SimpleNamespace(db_path=":memory:")

        with patch("anima_mcp.accessors._get_store", return_value=store), \
             patch("anima_mcp.accessors._get_growth", return_value=None), \
             patch(
                 "anima_mcp.self_reflection.get_reflection_system",
                 return_value=reflection,
             ), \
             patch("anima_mcp.self_model.get_self_model", return_value=self_model):
            data = parse_result(await handle_get_self_knowledge({"limit": 5}))

        view = data["insights"][0]
        assert view["confidence"] == 0.5
        assert view["sample_count"] == 0
        assert view["actionability"] == "review"
        assert "cold-started" in view["interpretation"]

    async def test_summary_uses_live_views_and_ranks_review_claims_last(self):
        from anima_mcp.handlers.knowledge import handle_get_self_knowledge
        from anima_mcp.self_reflection import InsightCategory

        stale_light = SimpleNamespace(
            id="pref_dim_light",
            category=InsightCategory.ENVIRONMENT,
            to_dict=lambda: {
                "id": "pref_dim_light",
                "description": "i know this about myself: dim light calms me",
                "confidence": 1.0,
                "sample_count": 100_000,
                "validation_count": 600,
                "contradiction_count": 0,
            },
        )
        established = SimpleNamespace(
            id="qa_rederived",
            category=InsightCategory.BEHAVIORAL,
            to_dict=lambda: {
                "id": "qa_rederived",
                "description": "Repeated checks support this claim",
                "confidence": 1.0,
                "sample_count": 3,
                "validation_count": 3,
                "contradiction_count": 0,
            },
        )
        reflection = SimpleNamespace(
            get_insights=lambda category=None: [stale_light, established],
            get_self_knowledge_summary=lambda: {
                "total_insights": 2,
                "strongest": [stale_light.to_dict()],
                "by_category": {
                    "environment": [stale_light.to_dict()["description"]]
                },
                "reflection_summary": {},
            },
        )
        preference = SimpleNamespace(
            confidence=0.2,
            observation_count=100_000,
            independent_evidence_count=0,
            supporting_count=0,
            contradicting_count=0,
            evidence_origin="reset_external_light_gate_v2",
        )
        growth = SimpleNamespace(_preferences={"dim_light": preference})
        store = SimpleNamespace(db_path=":memory:")

        with patch("anima_mcp.accessors._get_store", return_value=store), \
             patch("anima_mcp.accessors._get_growth", return_value=growth), \
             patch(
                 "anima_mcp.self_reflection.get_reflection_system",
                 return_value=reflection,
             ), \
             patch("anima_mcp.self_model.get_self_model", return_value=None):
            data = parse_result(await handle_get_self_knowledge({"limit": 5}))

        strongest = data["summary"]["strongest"]
        assert strongest[0]["id"] == "qa_rederived"
        assert strongest[1]["id"] == "pref_dim_light"
        assert strongest[1]["confidence"] == 0.2
        assert strongest[1]["actionability"] == "review"
        assert data["summary"]["by_category"]["environment"] == [
            "observational pattern: dim light calms me"
        ]

    async def test_negative_preference_direction_is_not_called_contradiction(self):
        from anima_mcp.handlers.knowledge import _insight_view

        insight = SimpleNamespace(
            id="pref_dim_light",
            to_dict=lambda: {
                "id": "pref_dim_light",
                "description": "Dim light makes me feel uncertain",
                "confidence": 0.99,
                "sample_count": 500,
                "validation_count": 30,
                "contradiction_count": 0,
            },
        )
        preference = SimpleNamespace(
            confidence=0.85,
            observation_count=500,
            independent_evidence_count=40,
            supporting_count=0,
            contradicting_count=40,
            evidence_origin="native_hourly_windows",
        )
        growth = SimpleNamespace(_preferences={"dim_light": preference})

        view = _insight_view(insight, growth)

        assert view["actionability"] == "established"
        assert view["evidence_support_label"] == "positive direction"
        assert view["evidence_contradiction_label"] == "negative direction"

    async def test_high_confidence_single_claim_is_not_established(self):
        from anima_mcp.handlers.knowledge import _insight_view

        insight = SimpleNamespace(
            id="qa_single_claim",
            to_dict=lambda: {
                "id": "qa_single_claim",
                "description": "A single answer asserted this",
                "confidence": 1.0,
                "sample_count": 1,
                "validation_count": 1,
                "contradiction_count": 0,
            },
        )

        view = _insight_view(insight)

        assert view["actionability"] == "review"
        assert view["actionability_evidence_count"] == 1
        assert view["minimum_established_evidence"] == 3
        assert "only 1 source evidence" in view["review_reason"]


@pytest.mark.asyncio
class TestGetGrowthExtended:
    async def test_include_all_returns_expected_sections(self):
        from anima_mcp.handlers.knowledge import handle_get_growth

        pref_good = SimpleNamespace(
            name="dim",
            description="likes dim light",
            confidence=0.9,
            observation_count=6,
        )
        pref_low = SimpleNamespace(
            name="noise",
            description="uncertain",
            confidence=0.1,
            observation_count=2,
        )
        rel_self = SimpleNamespace(
            is_self=lambda: True,
            interaction_count=3,
            self_dialogue_topics=["light", "light", "rest"],
        )
        rel_visitor = SimpleNamespace(
            is_self=lambda: False,
            name="Cursor",
            agent_id="agent-123",
            visitor_frequency=SimpleNamespace(value="regular"),
            interaction_count=4,
            first_met=datetime(2026, 1, 1),
            last_seen=datetime(2026, 3, 1),
        )
        goal_active = SimpleNamespace(
            status=SimpleNamespace(value="active"),
            description="understand calm",
            progress=0.4,
            milestones=["m1", "m2"],
        )
        memory = SimpleNamespace(
            description="A meaningful exchange",
            category="social",
            timestamp=datetime(2026, 3, 1),
        )
        growth = SimpleNamespace(
            get_autobiography_summary=lambda: {"chapters": 2},
            _preferences={"p1": pref_good, "p2": pref_low},
            _relationships={"self": rel_self, "v1": rel_visitor},
            # _goals is active-only under load_state(); the achieved counter
            # comes from count_goals_by_status hitting the DB.
            _goals={"g1": goal_active},
            _memories=[memory],
            _curiosities=["why light?"],
            get_inactive_visitors=lambda: [("OldAgent", 9)],
            count_goals_by_status=lambda status: 1 if status.value == "achieved" else 0,
        )

        with patch("anima_mcp.accessors._get_growth", return_value=growth):
            data = parse_result(await handle_get_growth({"include": ["all"]}))

        assert "autobiography" in data
        assert data["preferences"]["count"] == 2
        assert len(data["preferences"]["learned"]) == 1  # low-confidence pref filtered out
        assert data["visitors"]["unique_names"] == 1
        assert data["goals"]["active"] == 1
        assert data["goals"]["achieved"] == 1
        assert data["memories"]["count"] == 1
        assert data["curiosities"]["count"] == 1
        assert data["visitors"]["inactive"][0]["name"] == "OldAgent"


@pytest.mark.asyncio
class TestQaInsightsExtended:
    async def test_empty_insights_adds_note(self):
        from anima_mcp.handlers.knowledge import handle_get_qa_insights

        kb = SimpleNamespace(_insights=[])
        with patch("anima_mcp.knowledge.get_knowledge", return_value=kb), \
             patch("anima_mcp.knowledge.get_insights", return_value=[]):
            data = parse_result(await handle_get_qa_insights({"limit": 3}))

        assert data["total_insights"] == 0
        assert "note" in data


@pytest.mark.asyncio
class TestTrajectoryExtended:
    async def test_summary_marks_identity_stable(self):
        from anima_mcp.handlers.knowledge import handle_get_trajectory

        sig = SimpleNamespace(
            summary=lambda: {"observation_count": 70},
            to_dict=lambda: {"raw": True},
            get_stability_score=lambda: 0.8,
        )
        with patch("anima_mcp.trajectory.compute_trajectory_signature", return_value=sig), \
             patch("anima_mcp.anima_history.get_anima_history", return_value=SimpleNamespace()), \
             patch("anima_mcp.self_model.get_self_model", return_value=SimpleNamespace()):
            data = parse_result(await handle_get_trajectory({}))

        assert data["identity_status"] == "stable"
        assert "note" in data

    async def test_compare_to_historical_without_genesis_reports_unavailable(self):
        from anima_mcp.handlers.knowledge import handle_get_trajectory

        sig = SimpleNamespace(
            summary=lambda: {},
            to_dict=lambda: {"raw": True},
            get_stability_score=lambda: 0.2,
            genesis_signature=None,
            observation_count=5,
        )
        with patch("anima_mcp.trajectory.compute_trajectory_signature", return_value=sig), \
             patch("anima_mcp.anima_history.get_anima_history", return_value=SimpleNamespace()), \
             patch("anima_mcp.self_model.get_self_model", return_value=SimpleNamespace()), \
             patch("anima_mcp.trajectory.load_trajectory", return_value=None), \
             patch("anima_mcp.trajectory.GENESIS_MIN_OBSERVATIONS", 20):
            data = parse_result(await handle_get_trajectory({"compare_to_historical": True}))

        assert data["identity_status"] == "forming"
        assert data["anomaly_detection"]["available"] is False


@pytest.mark.asyncio
class TestQueryExtended:
    async def test_invalid_type_rejected(self):
        from anima_mcp.handlers.knowledge import handle_query

        data = parse_result(await handle_query({"text": "hello", "type": "bad"}))
        assert "error" in data
        assert "valid_types" in data

    async def test_growth_query_returns_growth_summary(self):
        from anima_mcp.handlers.knowledge import handle_query

        growth = SimpleNamespace(get_autobiography_summary=lambda: {"highlights": 3})
        with patch("anima_mcp.knowledge.get_relevant_insights", return_value=[]), \
             patch("anima_mcp.accessors._get_growth", return_value=growth):
            data = parse_result(await handle_query({"text": "growth status", "type": "growth"}))

        assert data["type"] == "growth"
        assert data["growth"]["highlights"] == 3

    async def test_cognitive_query_includes_reflection_context(self):
        from anima_mcp.handlers.knowledge import handle_query

        qa = SimpleNamespace(
            text="Light matters",
            category="environment",
            source_question="How does light affect you?",
        )
        refl_insight = SimpleNamespace(to_dict=lambda: {"text": "dim helps"})
        reflection = SimpleNamespace(
            get_self_knowledge_summary=lambda: "dim helps",
            get_insights=lambda: [refl_insight],
        )
        store = SimpleNamespace(db_path=":memory:")

        with patch("anima_mcp.knowledge.get_relevant_insights", return_value=[qa]), \
             patch("anima_mcp.accessors._get_store", return_value=store), \
             patch("anima_mcp.self_reflection.get_reflection_system", return_value=reflection):
            data = parse_result(await handle_query({"text": "light", "type": "cognitive"}))

        assert len(data["qa_insights"]) == 1
        assert data["self_knowledge"] == "dim helps"
        assert len(data["reflection_insights"]) == 1


@pytest.mark.asyncio
class TestEisvTrajectoryStateExtended:
    async def test_returns_state(self):
        from anima_mcp.handlers.knowledge import handle_get_eisv_trajectory_state

        traj = SimpleNamespace(get_state=lambda: {"coherence": 0.5})
        with patch("anima_mcp.handlers.knowledge.get_trajectory_awareness", return_value=traj):
            data = parse_result(await handle_get_eisv_trajectory_state({}))
        assert data["coherence"] == 0.5
