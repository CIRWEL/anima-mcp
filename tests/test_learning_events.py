import json
import os

import pytest

from anima_mcp.learning_events import (
    LearningInboxFullError,
    drain_learning_events,
    enqueue_preference_weights,
    enqueue_self_belief_evidence,
    learning_inbox_status,
)
from anima_mcp.preferences import PreferenceSystem
from anima_mcp.self_model import SelfModel


def test_broker_applies_queued_self_belief_evidence(tmp_path):
    inbox = tmp_path / "inbox"
    model = SelfModel(persistence_path=tmp_path / "self_model.json")
    enqueue_self_belief_evidence(
        "question_asking_tendency",
        supports=True,
        strength=0.8,
        source="test",
        inbox=inbox,
    )

    result = drain_learning_events(self_model=model, inbox=inbox)

    assert result == {"processed": 1, "rejected": 0, "failed": 0}
    assert model.beliefs["question_asking_tendency"].supporting_count == 1
    assert not list(inbox.glob("*.json"))


def test_broker_applies_queued_preference_weights(tmp_path):
    inbox = tmp_path / "inbox"
    preferences = PreferenceSystem(persistence_path=tmp_path / "preferences.json")
    enqueue_preference_weights(
        {"warmth": 2.0, "clarity": 1.0, "stability": 0.5, "presence": 0.5},
        source="test",
        inbox=inbox,
    )

    result = drain_learning_events(preferences=preferences, inbox=inbox)

    assert result["processed"] == 1
    assert preferences._preferences["warmth"].influence_weight > 1.0
    persisted = json.loads(preferences.persistence_path.read_text())
    assert persisted["preferences"]["warmth"]["influence_weight"] > 1.0


def test_malformed_event_is_quarantined(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "bad.json").write_text("not-json")

    result = drain_learning_events(inbox=inbox)

    assert result["rejected"] == 1
    assert (inbox / "rejected" / "bad.json").exists()


def test_event_waits_when_writer_is_unavailable(tmp_path):
    inbox = tmp_path / "inbox"
    enqueue_self_belief_evidence(
        "light_sensitive",
        supports=True,
        strength=1.0,
        source="test",
        inbox=inbox,
    )
    reader = SelfModel(
        persistence_path=tmp_path / "self_model.json",
        read_only=True,
    )

    result = drain_learning_events(self_model=reader, inbox=inbox)

    assert result["failed"] == 1
    assert len(list(inbox.glob("*.json"))) == 1


def test_committed_event_receipt_prevents_replay(tmp_path):
    """A crash after snapshot save but before unlink cannot double evidence."""
    inbox = tmp_path / "inbox"
    model_path = tmp_path / "self_model.json"
    event_id = enqueue_self_belief_evidence(
        "light_sensitive",
        supports=True,
        strength=0.8,
        source="test",
        inbox=inbox,
    )
    event_path = inbox / f"{event_id}.json"

    model = SelfModel(persistence_path=model_path)
    model.apply_evidence("light_sensitive", supports=True, strength=0.8)
    model.mark_applied_event(event_id)
    assert model.save() is True

    restarted = SelfModel(persistence_path=model_path)
    assert restarted.beliefs["light_sensitive"].supporting_count == 1
    result = drain_learning_events(self_model=restarted, inbox=inbox)

    assert result["processed"] == 1
    assert restarted.beliefs["light_sensitive"].supporting_count == 1
    assert not event_path.exists()


def test_failed_snapshot_save_rolls_back_and_retains_event(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    model = SelfModel(persistence_path=tmp_path / "self_model.json")
    enqueue_self_belief_evidence(
        "light_sensitive",
        supports=True,
        strength=0.8,
        source="test",
        inbox=inbox,
    )
    monkeypatch.setattr(model, "save", lambda: False)

    result = drain_learning_events(self_model=model, inbox=inbox)

    assert result["failed"] == 1
    assert model.beliefs["light_sensitive"].supporting_count == 0
    assert model._applied_event_ids == []
    assert len(list(inbox.glob("*.json"))) == 1


def test_inbox_status_surfaces_queue_rejections_and_oldest_age(tmp_path):
    inbox = tmp_path / "inbox"
    event_id = enqueue_self_belief_evidence(
        "light_sensitive",
        supports=True,
        strength=0.8,
        source="test",
        inbox=inbox,
    )
    old = inbox / f"{event_id}.json"
    os.utime(old, (old.stat().st_atime, old.stat().st_mtime - 10))
    rejected = inbox / "rejected"
    rejected.mkdir()
    (rejected / "bad.json").write_text("bad")

    status = learning_inbox_status(inbox=inbox)

    assert status["queued"] == 1
    assert status["rejected"] == 1
    assert status["total_bytes"] > 0
    assert status["oldest_age_s"] >= 9
    assert status["over_capacity"] is False


def test_enqueue_fails_closed_at_configured_capacity(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    monkeypatch.setenv("ANIMA_LEARNING_INBOX_MAX_EVENTS", "1")
    enqueue_self_belief_evidence(
        "light_sensitive",
        supports=True,
        strength=0.8,
        source="first",
        inbox=inbox,
    )

    with pytest.raises(LearningInboxFullError):
        enqueue_self_belief_evidence(
            "light_sensitive",
            supports=True,
            strength=0.8,
            source="second",
            inbox=inbox,
        )

    assert len(list(inbox.glob("*.json"))) == 1
