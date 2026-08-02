"""Tests for visitor attribution and the human-presence signal.

Two coupled defects:

1. `normalize_visitor_identity` matched the *channel* against the operator's
   alias set — "dashboard" was an alias — and the match was
   `id in aliases OR source in aliases`, so the channel WON over the author the
   caller actually supplied. An agent answering through the dashboard was
   durably recorded as the operator, as a PERSON.

2. `interaction_level` scanned the message board for `msg_type == "user"`, a
   type nothing on the live system produces. It read exactly 0.0 for all 20,000
   sampled rows and had never once been non-zero.

They are tested together because the second now trusts the first: presence is
derived from PERSON visitor records, so PERSON has to mean something.
"""

from datetime import timedelta

import pytest

from anima_mcp.growth.base import GrowthSystem
from anima_mcp.growth.models import VisitorType, normalize_visitor_identity
from anima_mcp.server_state import ANONYMOUS_VISITOR_ID, OPERATOR_NAME


@pytest.fixture
def growth(tmp_path):
    return GrowthSystem(db_path=str(tmp_path / "anima.db"))


class TestChannelIsNotAnIdentity:
    def test_dashboard_source_does_not_make_someone_the_operator(self):
        _, _, v_type = normalize_visitor_identity("codex", source="dashboard")
        assert v_type is VisitorType.AGENT

    def test_dashboard_source_does_not_overwrite_an_explicit_author(self):
        """The exact reported failure: Codex answered, Kenny was recorded."""
        canonical, display, v_type = normalize_visitor_identity(
            "Codex", agent_name="Codex", source="dashboard"
        )
        assert v_type is VisitorType.AGENT
        assert canonical == "Codex"
        assert display == "Codex"
        assert OPERATOR_NAME not in canonical.lower()

    @pytest.mark.parametrize("source", ["dashboard", "web", "curl", "mcp", None, ""])
    def test_no_source_confers_personhood(self, source):
        _, _, v_type = normalize_visitor_identity("some-agent", source=source)
        assert v_type is VisitorType.AGENT

    def test_generic_role_words_are_not_the_operator(self):
        """"human" and "caretaker" were aliases — anyone could type them."""
        for claim in ("human", "caretaker", "dashboard"):
            _, _, v_type = normalize_visitor_identity(claim)
            assert v_type is VisitorType.AGENT, f"{claim!r} still resolves to a person"

    def test_anonymous_is_not_the_operator(self):
        _, _, v_type = normalize_visitor_identity(ANONYMOUS_VISITOR_ID, source="dashboard")
        assert v_type is VisitorType.AGENT

    def test_the_operators_own_name_still_resolves(self):
        """A deliberate name claim is still honoured — only inference is gone."""
        canonical, _, v_type = normalize_visitor_identity(OPERATOR_NAME)
        assert v_type is VisitorType.PERSON
        assert canonical == OPERATOR_NAME

    def test_operator_name_is_case_insensitive(self):
        _, _, v_type = normalize_visitor_identity(OPERATOR_NAME.upper())
        assert v_type is VisitorType.PERSON

    def test_lumen_is_still_self(self):
        canonical, _, v_type = normalize_visitor_identity("lumen", source="dashboard")
        assert v_type is VisitorType.SELF
        assert canonical == "lumen"


class TestInteractionLevel:
    def test_unknown_when_no_person_has_ever_visited(self, growth):
        assert growth.last_person_seen_at() is None
        assert growth.interaction_level() is None

    def test_agents_alone_do_not_count_as_company(self, growth):
        growth.record_interaction("Codex", agent_name="Codex", source="dashboard")
        growth.record_interaction("Claude Code", agent_name="Claude Code")
        assert growth.last_person_seen_at() is None
        assert growth.interaction_level() is None

    def test_full_when_a_person_just_visited(self, growth):
        growth.record_interaction(OPERATOR_NAME)
        assert growth.interaction_level() == pytest.approx(1.0, abs=0.01)

    def test_decays_over_the_window(self, growth):
        growth.record_interaction(OPERATOR_NAME)
        seen = growth.last_person_seen_at()
        assert seen is not None
        half = seen + timedelta(minutes=growth.INTERACTION_DECAY_MINUTES / 2)
        assert growth.interaction_level(now=half) == pytest.approx(0.5, abs=0.02)

    def test_zero_once_the_window_has_passed(self, growth):
        growth.record_interaction(OPERATOR_NAME)
        seen = growth.last_person_seen_at()
        later = seen + timedelta(minutes=growth.INTERACTION_DECAY_MINUTES * 3)
        # A measured zero: someone was here, and that was a while ago.
        assert growth.interaction_level(now=later) == 0.0

    def test_zero_and_none_are_different_claims(self, growth):
        """The distinction the old code could not make."""
        assert growth.interaction_level() is None
        growth.record_interaction(OPERATOR_NAME)
        seen = growth.last_person_seen_at()
        stale = seen + timedelta(hours=5)
        assert growth.interaction_level(now=stale) == 0.0

    def test_clock_skew_does_not_produce_a_negative_level(self, growth):
        growth.record_interaction(OPERATOR_NAME)
        seen = growth.last_person_seen_at()
        earlier = seen - timedelta(minutes=10)
        assert growth.interaction_level(now=earlier) == 1.0

    def test_an_agent_visit_does_not_refresh_a_persons_presence(self, growth):
        """A dashboard agent must not make it look like the human is back."""
        growth.record_interaction(OPERATOR_NAME)
        before = growth.last_person_seen_at()
        growth.record_interaction("Codex", agent_name="Codex", source="dashboard")
        assert growth.last_person_seen_at() == before
