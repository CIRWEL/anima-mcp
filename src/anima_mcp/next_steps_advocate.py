"""
Next Steps Advocate - Reports Lumen's actual state and drives.

No canned phrases. Feelings come from anima dimensions, desires come from
inner_life drives (which accumulate when temperament drops below comfort
thresholds). Diagnostic checks remain for hardware/connectivity issues.
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum

from .anima import Anima
from .sensors.base import SensorReadings
from .eisv_mapper import EISVMetrics


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
    blockers: List[str] = None
    estimated_time: Optional[str] = None
    related_files: List[str] = None

    def __post_init__(self):
        if self.blockers is None:
            self.blockers = []
        if self.related_files is None:
            self.related_files = []

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

        Returns:
            List of findings, prioritized
        """
        steps = []

        # === Diagnostic checks (factual) ===

        if not display_available:
            steps.append(NextStep(
                feeling="display unavailable",
                desire="expression",
                action="Run display diagnostics",
                priority=Priority.HIGH,
                category=StepCategory.HARDWARE,
                reason="Cannot show state without display",
            ))

        if not unitares_connected:
            steps.append(NextStep(
                feeling="no governance connection",
                desire="connection",
                action="Check UNITARES_URL configuration",
                priority=Priority.MEDIUM,
                category=StepCategory.INTEGRATION,
                reason="Self-monitoring requires governance",
            ))

        if anima and readings:
            if anima.clarity < 0.3:
                steps.append(NextStep(
                    feeling=f"clarity={anima.clarity:.2f}",
                    desire="wanting to see clearly",
                    action="Check sensor connections",
                    priority=Priority.HIGH,
                    category=StepCategory.HARDWARE,
                    reason="Sensor signal quality degraded",
                ))

            if eisv and eisv.entropy > 0.6:
                steps.append(NextStep(
                    feeling=f"entropy={eisv.entropy:.2f}",
                    desire="wanting calm",
                    action="Check for resource pressure",
                    priority=Priority.CRITICAL,
                    category=StepCategory.OPTIMIZATION,
                    reason="System state unstable",
                ))

            if anima.stability < 0.4:
                steps.append(NextStep(
                    feeling=f"stability={anima.stability:.2f}",
                    desire="wanting stability",
                    action="Check environment consistency",
                    priority=Priority.HIGH,
                    category=StepCategory.OPTIMIZATION,
                    reason="Environmental instability",
                ))

            if anima.warmth < 0.3:
                steps.append(NextStep(
                    feeling=f"warmth={anima.warmth:.2f}",
                    desire="wanting warmth",
                    action="Check temperature, CPU activity",
                    priority=Priority.MEDIUM,
                    category=StepCategory.HARDWARE,
                    reason="Low thermal/activity state",
                ))

            if anima.presence < 0.4:
                steps.append(NextStep(
                    feeling=f"presence={anima.presence:.2f}",
                    desire="wanting to feel whole",
                    action="Check CPU, memory, disk usage",
                    priority=Priority.HIGH,
                    category=StepCategory.OPTIMIZATION,
                    reason="Resource constraints",
                ))

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

            steps.append(NextStep(
                feeling=f"drive: {strongest_drive}={drive_val:.2f}",
                desire=desire,
                action="observe",
                priority=Priority.LOW,
                category=StepCategory.TESTING,
                reason=f"temperament below comfort for {strongest_drive}",
            ))

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
            "last_analyzed": self._last_analysis.isoformat() if self._last_analysis else None,
            "total_steps": len(self._cached_steps),
            "critical": len([s for s in self._cached_steps if s.priority == Priority.CRITICAL]),
            "high": len([s for s in self._cached_steps if s.priority == Priority.HIGH]),
            "medium": len([s for s in self._cached_steps if s.priority == Priority.MEDIUM]),
            "low": len([s for s in self._cached_steps if s.priority == Priority.LOW]),
            "next_action": self._cached_steps[0].to_dict() if self._cached_steps else None,
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
