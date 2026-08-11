"""Durable cross-process handoff for learned-state mutations.

The hardware broker is the sole writer for embodied learned state.  Server
events that legitimately affect that state (a question being asked, or a
meta-learning weight update) are written as one-file messages and consumed by
the broker.  One file per event keeps multiple producers safe without turning
the learned JSON snapshots themselves into multi-writer stores.
"""

from __future__ import annotations

import json
import math
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from .atomic_write import atomic_json_write


EVENT_VERSION = 1


def _default_inbox() -> Path:
    """Resolve HOME at call time so tests and alternate runtimes stay isolated."""
    return Path.home() / ".anima" / "learning_inbox"


def enqueue_learning_event(
    kind: str,
    payload: dict[str, Any],
    *,
    inbox: Optional[Path] = None,
) -> str:
    """Append a durable event and return its id."""
    event_id = f"{time.time_ns()}-{os.getpid()}-{uuid.uuid4().hex[:10]}"
    root = Path(inbox) if inbox is not None else _default_inbox()
    event = {
        "version": EVENT_VERSION,
        "event_id": event_id,
        "kind": kind,
        "created_at": time.time(),
        "payload": payload,
    }
    atomic_json_write(root / f"{event_id}.json", event)
    return event_id


def enqueue_self_belief_evidence(
    belief_id: str,
    *,
    supports: bool,
    strength: float,
    source: str,
    inbox: Optional[Path] = None,
) -> str:
    """Queue one semantic evidence episode for the broker-owned self-model."""
    normalized_strength = float(strength)
    if not math.isfinite(normalized_strength) or normalized_strength <= 0.0:
        raise ValueError("self-belief evidence strength must be finite and positive")
    return enqueue_learning_event(
        "self_belief_evidence",
        {
            "belief_id": belief_id,
            "supports": bool(supports),
            "strength": min(1.0, normalized_strength),
            "source": source,
        },
        inbox=inbox,
    )


def enqueue_preference_weights(
    weights: dict[str, float],
    *,
    source: str,
    inbox: Optional[Path] = None,
) -> str:
    """Queue a complete influence-weight update for broker application."""
    normalized = {str(k): float(v) for k, v in weights.items()}
    if not normalized or any(
        not math.isfinite(value) or value < 0.0 for value in normalized.values()
    ):
        raise ValueError("preference weights must be finite and non-negative")
    return enqueue_learning_event(
        "preference_weights",
        {"weights": normalized, "source": source},
        inbox=inbox,
    )


def _reject(path: Path, root: Path) -> None:
    rejected = root / "rejected"
    rejected.mkdir(parents=True, exist_ok=True)
    path.replace(rejected / path.name)


def drain_learning_events(
    *,
    self_model=None,
    preferences=None,
    inbox: Optional[Path] = None,
    limit: int = 100,
) -> dict[str, int]:
    """Apply queued events in creation order from the broker process.

    Malformed events are quarantined so one bad file cannot poison the inbox.
    Transient application failures remain queued for the next pass.
    """
    root = Path(inbox) if inbox is not None else _default_inbox()
    result = {"processed": 0, "rejected": 0, "failed": 0}
    if not root.exists():
        return result

    for path in sorted(root.glob("*.json"))[: max(0, limit)]:
        try:
            event = json.loads(path.read_text())
            if event.get("version") != EVENT_VERSION:
                raise ValueError("unsupported learning-event version")
            event_id = event.get("event_id")
            if not isinstance(event_id, str) or not event_id:
                raise ValueError("learning-event id must be a non-empty string")
            payload = event.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("learning-event payload must be an object")

            kind = event.get("kind")
            if kind == "self_belief_evidence":
                if self_model is None or not getattr(self_model, "is_writable", False):
                    raise RuntimeError("writable self-model unavailable")
                belief_id = payload.get("belief_id")
                supports = payload.get("supports")
                strength = payload.get("strength")
                if not isinstance(belief_id, str) or not isinstance(supports, bool):
                    raise ValueError("invalid self-belief event")
                if isinstance(strength, bool) or not isinstance(strength, (int, float)):
                    raise ValueError("invalid self-belief strength")
                strength = float(strength)
                if not math.isfinite(strength) or strength <= 0.0:
                    raise ValueError("invalid self-belief strength")
                if not self_model.has_applied_event(event_id):
                    belief = self_model.beliefs.get(belief_id)
                    if belief is None:
                        raise ValueError(f"unknown self-belief: {belief_id}")
                    belief_before = (
                        belief.confidence,
                        belief.value,
                        belief.supporting_count,
                        belief.contradicting_count,
                        belief.last_tested,
                    )
                    self_model.apply_evidence(
                        belief_id,
                        supports=supports,
                        strength=min(1.0, strength),
                    )
                    self_model.mark_applied_event(event_id)
                    if not self_model.save():
                        (
                            belief.confidence,
                            belief.value,
                            belief.supporting_count,
                            belief.contradicting_count,
                            belief.last_tested,
                        ) = belief_before
                        self_model.forget_applied_event(event_id)
                        raise RuntimeError("self-model snapshot save failed")
            elif kind == "preference_weights":
                if preferences is None or not getattr(preferences, "is_writable", False):
                    raise RuntimeError("writable preference system unavailable")
                weights = payload.get("weights")
                if not isinstance(weights, dict) or not weights:
                    raise ValueError("invalid preference-weight event")
                converted: dict[str, float] = {}
                for dim, weight in weights.items():
                    if dim not in preferences._preferences:
                        raise ValueError(f"unknown preference dimension: {dim}")
                    value = float(weight)
                    if not math.isfinite(value) or value < 0.0:
                        raise ValueError("invalid preference weight")
                    converted[dim] = value
                if not preferences.has_applied_event(event_id):
                    weight_before = {
                        dim: pref.influence_weight
                        for dim, pref in preferences._preferences.items()
                    }
                    for dim, weight in converted.items():
                        preferences._preferences[dim].influence_weight = weight
                    preferences.enforce_weight_conservation()
                    preferences.mark_applied_event(event_id)
                    if not preferences._save():
                        for dim, weight in weight_before.items():
                            preferences._preferences[dim].influence_weight = weight
                        preferences.forget_applied_event(event_id)
                        raise RuntimeError("preference snapshot save failed")
            else:
                raise ValueError(f"unknown learning-event kind: {kind}")
        except (ValueError, TypeError, json.JSONDecodeError):
            _reject(path, root)
            result["rejected"] += 1
            continue
        except Exception:
            result["failed"] += 1
            continue

        path.unlink(missing_ok=True)
        result["processed"] += 1

    return result
