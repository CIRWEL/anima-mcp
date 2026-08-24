from pathlib import Path

from anima_mcp.qa_provenance import (
    qa_answer_provenance,
    qa_ledger_provenance,
    qa_record_provenance,
)


def test_qa_records_have_no_current_state_authority():
    open_record = qa_record_provenance("How does quiet feel?", has_answer=False)
    answered_record = qa_record_provenance(
        "How does quiet feel?",
        has_answer=True,
    )

    assert open_record == {
        "record_role": "conversation_record",
        "epistemic_status": "open_question",
        "current_state_authority": "none",
        "context_scope": "state_when_asked",
        "premise_status": "not_assessed",
    }
    assert answered_record["epistemic_status"] == "answered_record"
    assert qa_answer_provenance()["record_role"] == "historical_utterance"
    assert qa_ledger_provenance()["current_state_authority"] == "none"


def test_retired_led_correlation_certainty_is_labeled_without_rejecting_hypothesis():
    record = qa_record_provenance(
        "Why is it that I am confident that my own LEDs affect my light "
        "sensor readings?",
        has_answer=False,
    )

    assert record["premise_status"] == "superseded_confidence_basis"
    assert record["current_interpretation"] == "defer_to_live_causal_test"
    assert record["superseded_by"] == "led_causal_evidence_reset_v6"
    assert "correlation evidence was retired" in record["premise_reason"]


def test_open_led_causal_question_is_not_mislabeled_as_superseded():
    record = qa_record_provenance(
        "Do my LEDs affect the lux measured by my light sensor?",
        has_answer=False,
    )

    assert record["premise_status"] == "not_assessed"


def test_control_center_exposes_qa_authority_and_premise_labels():
    dashboard = (Path(__file__).parents[1] / "docs" / "control_center.html").read_text()

    assert "Conversation record:" in dashboard
    assert "no current-state authority" in dashboard
    assert "confidence basis retired" in dashboard
    assert "The hypothesis itself remains open" in dashboard
