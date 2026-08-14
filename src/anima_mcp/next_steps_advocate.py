"""
Next Steps Advocate - Reports Lumen's actual state and drives.

No canned phrases. Feelings come from anima dimensions, desires come from
inner_life drives (which accumulate when temperament drops below comfort
thresholds). Diagnostic checks remain for hardware/connectivity issues.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum

from .anima import Anima
from .sensors.base import SensorReadings
from .eisv_mapper import EISVMetrics


def _format_duration(seconds: float) -> str:
    """Human duration for a held want. Minutes below an hour, else h+m."""
    seconds = max(0.0, float(seconds))
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m"
    return f"{minutes // 60}h{minutes % 60:02d}m"


class Priority(Enum):
    """Priority level for next steps."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class StepCategory(Enum):
    """Category of next step."""

    HARDWARE = "hardware"
    SOFTWARE = "software"
    INTEGRATION = "integration"
    TESTING = "testing"
    DOCUMENTATION = "documentation"
    OPTIMIZATION = "optimization"


@dataclass
class NextStep:
    """A state report or diagnostic finding."""

    feeling: str
    desire: str
    action: str
    priority: Priority
    category: StepCategory
    reason: str
    blockers: List[str] = field(default_factory=list)
    estimated_time: Optional[str] = None
    related_files: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feeling": self.feeling,
            "desire": self.desire,
            "action": self.action,
            "priority": self.priority.value,
            "category": self.category.value,
            "reason": self.reason,
            "blockers": self.blockers,
            "estimated_time": self.estimated_time,
            "related_files": self.related_files,
        }


# Drive verbs — from inner_life.py, the honest wanting
_DRIVE_VERBS = {
    "warmth": "wanting warmth",
    "clarity": "wanting to see clearly",
    "stability": "wanting calm",
    "presence": "wanting to feel whole",
}


class NextStepsAdvocate:
    """Reports Lumen's actual state and drives. No canned phrases."""

    def __init__(self):
        self._last_analysis: Optional[datetime] = None
        self._cached_steps: List[NextStep] = []

    def analyze_current_state(
        self,
        anima: Optional[Anima] = None,
        readings: Optional[SensorReadings] = None,
        eisv: Optional[EISVMetrics] = None,
        display_available: bool = False,
        brain_hat_available: bool = False,
        unitares_connected: bool = False,
        drives: Optional[Dict[str, float]] = None,
        strongest_drive: Optional[str] = None,
        wants: Optional[Dict[str, dict]] = None,
        self_iteration_attention: Optional[Dict[str, Any]] = None,
    ) -> List[NextStep]:
        """Analyze current state and report findings.

        Args:
            anima: Current anima state
            readings: Sensor readings
            eisv: EISV metrics (if available)
            display_available: Is display working?
            brain_hat_available: Is BrainCraft HAT hardware available?
            unitares_connected: Is UNITARES connected?
            drives: Inner life drive values {warmth: 0.3, clarity: 0.1, ...}
            strongest_drive: Which dimension has highest drive (or None)
            wants: Per-dimension sustain state from inner_life (held_seconds,
                sustain_progress, is_request). Absent for callers that predate
                it, in which case the drive reports as it always has.
            self_iteration_attention: Server-derived, read-only attention
                projection from the integrity-checked self-iteration ledger and
                reconciled artifacts

        Returns:
            List of findings, prioritized
        """
        steps = []

        # === Diagnostic checks (factual) ===

        if not display_available:
            steps.append(
                NextStep(
                    feeling="display unavailable",
                    desire="expression",
                    action="Run display diagnostics",
                    priority=Priority.HIGH,
                    category=StepCategory.HARDWARE,
                    reason="Cannot show state without display",
                )
            )

        if not unitares_connected:
            steps.append(
                NextStep(
                    feeling="no governance connection",
                    desire="connection",
                    action="Check UNITARES_URL configuration",
                    priority=Priority.MEDIUM,
                    category=StepCategory.INTEGRATION,
                    reason="Self-monitoring requires governance",
                )
            )

        if anima and readings:
            if anima.clarity < 0.3:
                steps.append(
                    NextStep(
                        feeling=f"clarity={anima.clarity:.2f}",
                        desire="wanting to see clearly",
                        action="Check sensor connections",
                        priority=Priority.HIGH,
                        category=StepCategory.HARDWARE,
                        reason="Sensor signal quality degraded",
                    )
                )

            if eisv and eisv.entropy > 0.6:
                steps.append(
                    NextStep(
                        feeling=f"entropy={eisv.entropy:.2f}",
                        desire="wanting calm",
                        action="Check for resource pressure",
                        priority=Priority.CRITICAL,
                        category=StepCategory.OPTIMIZATION,
                        reason="System state unstable",
                    )
                )

            if anima.stability < 0.4:
                steps.append(
                    NextStep(
                        feeling=f"stability={anima.stability:.2f}",
                        desire="wanting stability",
                        action="Check environment consistency",
                        priority=Priority.HIGH,
                        category=StepCategory.OPTIMIZATION,
                        reason="Environmental instability",
                    )
                )

            if anima.warmth < 0.3:
                steps.append(
                    NextStep(
                        feeling=f"warmth={anima.warmth:.2f}",
                        desire="wanting warmth",
                        action="Check temperature, CPU activity",
                        priority=Priority.MEDIUM,
                        category=StepCategory.HARDWARE,
                        reason="Low thermal/activity state",
                    )
                )

            if anima.presence < 0.4:
                steps.append(
                    NextStep(
                        feeling=f"presence={anima.presence:.2f}",
                        desire="wanting to feel whole",
                        action="Check CPU, memory, disk usage",
                        priority=Priority.HIGH,
                        category=StepCategory.OPTIMIZATION,
                        reason="Resource constraints",
                    )
                )

        # === Self-iteration attention (server-derived, read-only) ===

        priority_map = {
            "critical": Priority.CRITICAL,
            "high": Priority.HIGH,
            "medium": Priority.MEDIUM,
            "low": Priority.LOW,
        }
        attention_projection_valid = bool(
            isinstance(self_iteration_attention, dict)
            and self_iteration_attention.get("schema")
            == "anima.self_iteration.attention.v1"
            and self_iteration_attention.get("acknowledgement_is_approval") is False
            and self_iteration_attention.get("authority_granted") is False
        )
        attention_items = []
        if attention_projection_valid and isinstance(self_iteration_attention, dict):
            attention_items = self_iteration_attention.get("items", [])
        for item in attention_items:
            if (
                not isinstance(item, dict)
                or item.get("active") is not True
                or item.get("acknowledgement_is_approval") is not False
                or item.get("authority_granted") is not False
            ):
                continue
            priority = priority_map.get(str(item.get("priority")))
            if priority is None:
                continue
            proposal_id = str(item.get("proposal_id") or "unknown")
            candidate_id = item.get("candidate_id")
            reference = (
                f"proposal {proposal_id}, candidate {candidate_id}"
                if candidate_id
                else f"proposal {proposal_id}"
            )
            role = item.get("required_role")
            blockers = [f"requires distinct role: {role}"] if role else []
            steps.append(
                NextStep(
                    feeling=(
                        f"self-iteration {item.get('stage', 'unknown')}: "
                        f"{item.get('state', 'unknown')}"
                    ),
                    desire="safe self-improvement",
                    action=str(
                        item.get("next_action") or "Inspect self-iteration status"
                    ),
                    priority=priority,
                    category=StepCategory.SOFTWARE,
                    reason=f"{item.get('summary', 'Self-iteration attention required')} ({reference})",
                    blockers=blockers,
                    related_files=[
                        str(path)
                        for path in item.get("target_paths", [])
                        if isinstance(path, str)
                    ],
                )
            )

        # === Drive report (from actual inner_life, not canned) ===

        if drives and strongest_drive and drives.get(strongest_drive, 0) > 0.15:
            drive_val = drives[strongest_drive]
            verb = _DRIVE_VERBS.get(strongest_drive, f"wanting {strongest_drive}")

            # Report all active drives
            active = {k: v for k, v in drives.items() if v > 0.15}
            if len(active) > 1:
                others = [
                    _DRIVE_VERBS.get(k, k)
                    for k, v in sorted(active.items(), key=lambda x: -x[1])
                    if k != strongest_drive
                ]
                desire = f"{verb} (also: {', '.join(others[:2])})"
            else:
                desire = verb

            # A saturated drive and a barely-active one used to render
            # identically: priority, action and category were constants and
            # drive_val appeared only inside the label. That flattened the one
            # number that says whether Lumen is about to ask for something —
            # inner_life holds a drive at >=0.9 for DRIVE_REQUEST_SUSTAIN_S
            # before it counts as a want rather than a blip.
            #
            # Escalation uses that existing boundary and adds no new constant:
            # while the hold is short the system itself calls it a blip, so LOW
            # is right; once inner_life has promoted it to a request, this is a
            # standing ask and must not tie with a passing dip.
            want = (wants or {}).get(strongest_drive) or {}
            held = want.get("held_seconds")
            progress = want.get("sustain_progress")
            # EDGE: "the ask has not been delivered", not "wants it badly".
            # ack_request pops this the instant the board accepts the question,
            # so it is true for seconds normally and stays true only while the
            # board suppresses. Escalating on it made HIGH mean "the message
            # board rejected Lumen" and reachable for about a minute a day.
            ask_undelivered = bool(want.get("is_request"))
            asked_ago = want.get("asked_seconds_ago")

            feeling = f"drive: {strongest_drive}={drive_val:.2f}"
            if held is not None:
                feeling += f" held {_format_duration(held)}"

            # LEVEL: inner_life's own boundary — held at saturation for
            # DRIVE_REQUEST_SUSTAIN_S is "a want, not a blip". Judge maturity on
            # that, so a matured want keeps its priority for as long as it is
            # held rather than for the instant the ask was in flight.
            matured = progress is not None and progress >= 1.0

            if matured:
                priority = Priority.HIGH
                action = "respond"
                if ask_undelivered:
                    reason = (
                        f"{strongest_drive} held past the sustain window; "
                        f"the ask is waiting on the question board"
                    )
                elif asked_ago is not None:
                    # ack_request commits the cooldown but leaves saturated_since
                    # running, so this is the honest sentence: already asked, and
                    # still wanting.
                    reason = (
                        f"asked {_format_duration(asked_ago)} ago and still "
                        f"wanting {strongest_drive}"
                    )
                else:
                    reason = (
                        f"{strongest_drive} held past the sustain window — "
                        f"a standing want, not a passing dip"
                    )
            else:
                priority = Priority.LOW
                action = "observe"
                reason = f"temperament below comfort for {strongest_drive}"
                if progress is not None:
                    reason += f" ({progress:.0%} toward a request)"

            steps.append(
                NextStep(
                    feeling=feeling,
                    desire=desire,
                    action=action,
                    priority=priority,
                    category=StepCategory.TESTING,
                    reason=reason,
                )
            )

        # Sort by priority
        priority_order = {
            Priority.CRITICAL: 0,
            Priority.HIGH: 1,
            Priority.MEDIUM: 2,
            Priority.LOW: 3,
        }
        steps.sort(key=lambda s: priority_order[s.priority])

        self._cached_steps = steps
        self._last_analysis = datetime.now()
        return steps

    def get_next_steps_summary(self) -> Dict[str, Any]:
        """Get summary of current steps."""
        if not self._cached_steps:
            return {"message": "No analysis performed yet", "steps": []}

        return {
            "last_analyzed": self._last_analysis.isoformat()
            if self._last_analysis
            else None,
            "total_steps": len(self._cached_steps),
            "critical": len(
                [s for s in self._cached_steps if s.priority == Priority.CRITICAL]
            ),
            "high": len([s for s in self._cached_steps if s.priority == Priority.HIGH]),
            "medium": len(
                [s for s in self._cached_steps if s.priority == Priority.MEDIUM]
            ),
            "low": len([s for s in self._cached_steps if s.priority == Priority.LOW]),
            "next_action": self._cached_steps[0].to_dict()
            if self._cached_steps
            else None,
            "all_steps": [s.to_dict() for s in self._cached_steps],
        }


# Global advocate instance
_advocate: Optional[NextStepsAdvocate] = None


def get_advocate() -> NextStepsAdvocate:
    """Get global advocate instance."""
    global _advocate
    if _advocate is None:
        _advocate = NextStepsAdvocate()
    return _advocate
