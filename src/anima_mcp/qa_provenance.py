"""Epistemic annotations for the Q&A conversation ledger.

Q&A preserves what Lumen and a visitor said at a particular time. It is not
live telemetry and an answer is not, by itself, evidence for the current
self-model. These helpers attach that distinction at every public Q&A view
without rewriting or deleting the underlying conversation.
"""

import re


def qa_ledger_provenance() -> dict[str, str]:
    """Describe the authority boundary shared by all Q&A records."""
    return {
        "record_role": "timestamped_conversation_ledger",
        "current_state_authority": "none",
        "current_state_source": "live telemetry and self-knowledge views",
    }


def qa_record_provenance(
    question_text: str,
    *,
    has_answer: bool,
) -> dict[str, str]:
    """Return non-destructive provenance for one question/answer pair.

    The LED classifier is deliberately narrow. It does not say that the
    LED-to-lux hypothesis is false. It says that certainty inherited from the
    retired closed-loop correlation is no longer admissible; clients must read
    the live causal test before treating that hypothesis as established.
    """
    normalized = re.sub(r"[^a-z0-9]+", " ", (question_text or "").casefold())
    normalized = " ".join(normalized.split())

    provenance = {
        "record_role": "conversation_record",
        "epistemic_status": ("answered_record" if has_answer else "open_question"),
        "current_state_authority": "none",
        "context_scope": "state_when_asked",
        "premise_status": "not_assessed",
    }

    mentions_own_leds = bool(
        re.search(r"\b(?:my|own)\s+(?:own\s+)?leds?\b", normalized)
        or "dotstar" in normalized
    )
    mentions_light_sensor = "light sensor" in normalized or "lux" in normalized
    claims_old_certainty = any(
        phrase in normalized
        for phrase in (
            "confident",
            "certain that",
            "i know that",
            "i learned that",
            "proven that",
            "definitely",
        )
    )

    if mentions_own_leds and mentions_light_sensor and claims_old_certainty:
        provenance.update(
            {
                "premise_status": "superseded_confidence_basis",
                "premise_reason": (
                    "Historical closed-loop LED/lux correlation evidence was "
                    "retired; consult the live breathing-pulse causal test before "
                    "treating this hypothesis as established."
                ),
                "current_interpretation": "defer_to_live_causal_test",
                "superseded_by": "led_causal_evidence_reset_v6",
            }
        )

    return provenance


def qa_answer_provenance() -> dict[str, str]:
    """Describe an answer as a preserved utterance, not current evidence."""
    return {
        "record_role": "historical_utterance",
        "current_state_authority": "none",
    }
