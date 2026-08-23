"""
Anima History - Track anima state over time for trajectory computation.

This module enables computing attractor basins and other trajectory invariants
by maintaining a time-series of anima state observations.

Part of the Trajectory Identity framework.
See: trajectory-identity paper (cirwel/trajectory-identity-paper, separate repo)
"""

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from pathlib import Path
import json
import sys

from .atomic_write import atomic_json_write


DAY_SUMMARY_INTERVAL = timedelta(hours=24)
DAY_SUMMARY_LOOKBACK = timedelta(hours=24)
DAY_SUMMARY_RETRY_INTERVAL = timedelta(minutes=5)
DAY_SUMMARY_MIN_OBSERVATIONS = 100
DAY_SUMMARY_MAX_AGE_SECONDS = 36 * 60 * 60
DAY_SUMMARY_FUTURE_TOLERANCE_SECONDS = 5 * 60
DAY_SUMMARY_BOOTSTRAP_GRACE_SECONDS = 30 * 60


def _comparable_datetime(value: datetime) -> datetime:
    """Return a UTC-naive datetime so legacy/local stamps remain comparable."""
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _parse_summary_timestamp(value: Any, field: str) -> datetime:
    """Parse a persisted ISO timestamp or raise with its field provenance."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is missing or malformed")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} is malformed") from exc
    return _comparable_datetime(parsed)


# Numpy is optional - graceful fallback if not available
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


@dataclass
class DaySummary:
    """Consolidated summary of one active period."""
    date: str                              # ISO date string
    attractor_center: List[float]          # [warmth, clarity, stability, presence]
    attractor_variance: List[float]        # variance per dimension
    n_observations: int
    time_span_hours: float
    notable_perturbations: int             # count of perturbations detected
    dimension_trends: Dict[str, float]     # per-dim mean for this period

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "center": self.attractor_center,
            "variance": self.attractor_variance,
            "n_obs": self.n_observations,
            "hours": round(self.time_span_hours, 2),
            "perturbations": self.notable_perturbations,
            "trends": self.dimension_trends,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DaySummary':
        return cls(
            date=data["date"],
            attractor_center=data["center"],
            attractor_variance=data["variance"],
            n_observations=data["n_obs"],
            time_span_hours=data["hours"],
            notable_perturbations=data["perturbations"],
            dimension_trends=data["trends"],
        )


@dataclass
class AnimaSnapshot:
    """A single anima state observation."""
    timestamp: datetime
    warmth: float
    clarity: float
    stability: float
    presence: float

    def to_vector(self) -> List[float]:
        """Convert to list (or numpy array if available)."""
        return [self.warmth, self.clarity, self.stability, self.presence]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "t": self.timestamp.isoformat(),
            "w": round(self.warmth, 4),
            "c": round(self.clarity, 4),
            "s": round(self.stability, 4),
            "p": round(self.presence, 4),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AnimaSnapshot':
        """Deserialize from dictionary."""
        return cls(
            timestamp=datetime.fromisoformat(data["t"]),
            warmth=data["w"],
            clarity=data["c"],
            stability=data["s"],
            presence=data["p"],
        )


class AnimaHistory:
    """
    Track anima state history for trajectory computation.

    Implements a sliding window of observations with periodic persistence.
    This is the foundation for computing attractor basins and other
    trajectory invariants.

    Usage:
        history = get_anima_history()
        history.record(warmth=0.5, clarity=0.6, stability=0.7, presence=0.8)
        basin = history.get_attractor_basin(window=100)
    """

    def __init__(
        self,
        max_size: int = 2000,  # ~5.5h at the server's ~10s history cadence
        persistence_path: Optional[Path] = None,
        auto_save_interval: int = 100,  # Save every N records
    ):
        self.max_size = max_size
        self.persistence_path = persistence_path or Path.home() / ".anima" / "anima_history.json"
        self.auto_save_interval = auto_save_interval
        self._history: deque = deque(maxlen=max_size)
        self._records_since_save = 0
        self._next_day_summary_check_at: Optional[datetime] = None
        self._day_summary_last_attempt_at: Optional[datetime] = None
        self._day_summary_last_success_at: Optional[datetime] = None
        self._day_summary_last_error: Optional[str] = None
        self._day_summary_pending: Optional[DaySummary] = None
        self._day_summary_bootstrap_checked = False
        self._load()

    def record(
        self,
        warmth: float,
        clarity: float,
        stability: float,
        presence: float,
        timestamp: Optional[datetime] = None,
    ):
        """
        Record a new anima state observation.

        Args:
            warmth: Warmth dimension [0, 1]
            clarity: Clarity dimension [0, 1]
            stability: Stability dimension [0, 1]
            presence: Presence dimension [0, 1]
            timestamp: Optional timestamp (defaults to now)
        """
        self._history.append(AnimaSnapshot(
            timestamp=timestamp or datetime.now(),
            warmth=warmth,
            clarity=clarity,
            stability=stability,
            presence=presence,
        ))

        self._records_since_save += 1
        if self._records_since_save >= self.auto_save_interval:
            self._save()
            self._records_since_save = 0

    def record_from_anima(self, anima) -> None:
        """
        Record from an AnimaState object.

        Args:
            anima: AnimaState with warmth, clarity, stability, presence
        """
        self.record(
            warmth=getattr(anima, 'warmth', 0.5),
            clarity=getattr(anima, 'clarity', 0.5),
            stability=getattr(anima, 'stability', 0.5),
            presence=getattr(anima, 'presence', 0.5),
        )

    def get_attractor_basin(self, window: int = 100) -> Optional[Dict[str, Any]]:
        """
        Compute attractor basin from recent history.

        The attractor basin characterizes where the agent "lives" in state space:
        - center (μ): The equilibrium point the agent returns to
        - covariance (Σ): The shape of the region the agent occupies
        - eigenvalues: Principal axes of variability

        Args:
            window: Number of recent observations to use

        Returns:
            Dictionary with center, covariance, and metadata, or None if insufficient data
        """
        if len(self._history) < 10:
            return None

        recent = list(self._history)[-window:]

        if HAS_NUMPY:
            matrix = np.array([s.to_vector() for s in recent])
            center = np.mean(matrix, axis=0)
            covariance = np.cov(matrix.T)

            # Handle edge case of constant values
            if np.any(np.isnan(covariance)):
                covariance = np.eye(4) * 0.001

            # Regularization: add epsilon to diagonal to prevent singularity
            # This ensures det(covariance) > 0 for Bhattacharyya computation
            epsilon = 1e-6
            covariance = covariance + np.eye(4) * epsilon

            # Compute eigenvalues for principal component analysis
            try:
                eigenvalues = np.linalg.eigvalsh(covariance)
            except np.linalg.LinAlgError:
                eigenvalues = [0.001] * 4

            return {
                "center": center.tolist(),
                "covariance": covariance.tolist(),
                "eigenvalues": sorted(eigenvalues.tolist(), reverse=True),
                "n_observations": len(recent),
                "time_span_seconds": (recent[-1].timestamp - recent[0].timestamp).total_seconds(),
                "dimensions": ["warmth", "clarity", "stability", "presence"],
            }
        else:
            # Fallback without numpy - basic statistics only
            n = len(recent)
            center = [
                sum(s.warmth for s in recent) / n,
                sum(s.clarity for s in recent) / n,
                sum(s.stability for s in recent) / n,
                sum(s.presence for s in recent) / n,
            ]

            # Compute variance (diagonal of covariance) only
            # Add epsilon regularization for consistency with numpy path
            epsilon = 1e-6
            variance = [
                sum((s.warmth - center[0])**2 for s in recent) / n + epsilon,
                sum((s.clarity - center[1])**2 for s in recent) / n + epsilon,
                sum((s.stability - center[2])**2 for s in recent) / n + epsilon,
                sum((s.presence - center[3])**2 for s in recent) / n + epsilon,
            ]

            return {
                "center": center,
                "variance": variance,  # Only variance, not full covariance
                "n_observations": len(recent),
                "time_span_seconds": (recent[-1].timestamp - recent[0].timestamp).total_seconds(),
                "dimensions": ["warmth", "clarity", "stability", "presence"],
                "_note": "Full covariance requires numpy",
            }

    def get_recent_trajectory(self, n: int = 20) -> List[Dict[str, Any]]:
        """
        Get the most recent N observations as a trajectory.

        Useful for visualization and debugging.

        Args:
            n: Number of recent observations to return

        Returns:
            List of observation dictionaries
        """
        recent = list(self._history)[-n:]
        return [s.to_dict() for s in recent]

    def get_dimension_stats(self, dimension: str, window: int = 100) -> Optional[Dict[str, float]]:
        """
        Get statistics for a single dimension.

        Args:
            dimension: One of 'warmth', 'clarity', 'stability', 'presence'
            window: Number of recent observations to use

        Returns:
            Dictionary with mean, std, min, max, or None if insufficient data
        """
        if len(self._history) < 5:
            return None

        recent = list(self._history)[-window:]
        values = [getattr(s, dimension) for s in recent]

        mean_val = sum(values) / len(values)
        variance = sum((v - mean_val)**2 for v in values) / len(values)
        std_val = variance ** 0.5

        return {
            "mean": round(mean_val, 4),
            "std": round(std_val, 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
            "n": len(values),
        }

    def detect_perturbation(self, threshold: float = 0.15) -> Optional[Dict[str, Any]]:
        """
        Detect if a recent perturbation occurred.

        A perturbation is a sudden change in state that moves the agent
        away from its attractor center.

        Args:
            threshold: Minimum distance from center to count as perturbation

        Returns:
            Dictionary with perturbation info, or None if no perturbation detected
        """
        if len(self._history) < 20:
            return None

        basin = self.get_attractor_basin(window=50)
        if not basin:
            return None

        center = basin["center"]
        recent = list(self._history)[-5:]

        for snapshot in recent:
            current = snapshot.to_vector()
            # Euclidean distance from center
            distance = sum((c - v)**2 for c, v in zip(center, current)) ** 0.5

            if distance > threshold:
                return {
                    "detected": True,
                    "distance": round(distance, 4),
                    "timestamp": snapshot.timestamp.isoformat(),
                    "state": snapshot.to_dict(),
                    "center": center,
                }

        return {"detected": False, "distance": 0.0}

    def compute_void_integral(self, window: int = 100) -> Optional[Dict[str, Any]]:
        """
        Compute the historical Anima Void Integral V_anima(t).

        From paper Section 4.1:
        V_anima(t) = ∫ ||a(τ) - μ_a|| dτ

        This is a research diagnostic for cumulative deviation from the anima
        center. It is not EISV V (Valence), and the live governance path does
        not consume it as a trigger.

        Args:
            window: Number of recent observations to integrate over

        Returns:
            Dictionary with void integral value and metadata
        """
        if len(self._history) < 20:
            return None

        basin = self.get_attractor_basin(window=window)
        if not basin:
            return None

        center = basin["center"]
        recent = list(self._history)[-window:]

        # Compute integral as sum of distances (discrete approximation)
        total_deviation = 0.0
        deviations = []

        for i, snapshot in enumerate(recent):
            current = snapshot.to_vector()
            distance = sum((c - v)**2 for c, v in zip(center, current)) ** 0.5
            deviations.append(distance)
            total_deviation += distance

        # Time span for rate calculation
        if len(recent) >= 2:
            time_span = (recent[-1].timestamp - recent[0].timestamp).total_seconds()
            if time_span > 0:
                rate = total_deviation / time_span
            else:
                rate = 0.0
        else:
            time_span = 0.0
            rate = 0.0

        # Average deviation (normalized void)
        avg_deviation = total_deviation / len(recent) if recent else 0.0

        return {
            "void_integral": round(total_deviation, 4),
            "avg_deviation": round(avg_deviation, 4),
            "rate": round(rate, 6),  # Deviation per second
            "max_deviation": round(max(deviations), 4) if deviations else 0.0,
            "n_observations": len(recent),
            "time_span_seconds": round(time_span, 2),
            "center": [round(c, 4) for c in center],
        }

    # === Memory Consolidation ===

    def consolidate(
        self,
        observations: Optional[List[AnimaSnapshot]] = None,
        now: Optional[datetime] = None,
    ) -> Optional[DaySummary]:
        """
        Consolidate current buffer into a DaySummary.

        Compresses the rolling buffer into a single summary that captures
        the essential character of this active period. Requires ≥100
        observations to produce a meaningful summary.

        Returns:
            DaySummary if enough data, None otherwise
        """
        observations = list(self._history) if observations is None else list(observations)
        if len(observations) < DAY_SUMMARY_MIN_OBSERVATIONS:
            return None

        n = len(observations)

        # Compute center (mean per dimension)
        center = [
            sum(s.warmth for s in observations) / n,
            sum(s.clarity for s in observations) / n,
            sum(s.stability for s in observations) / n,
            sum(s.presence for s in observations) / n,
        ]

        # Compute variance per dimension
        variance = [
            sum((s.warmth - center[0])**2 for s in observations) / n,
            sum((s.clarity - center[1])**2 for s in observations) / n,
            sum((s.stability - center[2])**2 for s in observations) / n,
            sum((s.presence - center[3])**2 for s in observations) / n,
        ]

        # Time span
        time_span_hours = (
            observations[-1].timestamp - observations[0].timestamp
        ).total_seconds() / 3600.0

        # Count perturbations (distance from center > 0.15)
        perturbation_count = 0
        for s in observations:
            dist = sum((c - v)**2 for c, v in zip(
                center, s.to_vector()
            )) ** 0.5
            if dist > 0.15:
                perturbation_count += 1

        # Dimension trends (just the means, labeled)
        dim_names = ["warmth", "clarity", "stability", "presence"]
        trends = {name: round(center[i], 4) for i, name in enumerate(dim_names)}

        summary = DaySummary(
            # This is evidence time, not writer time. A restarted writer must
            # never make an old deque look current merely by attempting a save.
            date=observations[-1].timestamp.isoformat(),
            attractor_center=[round(c, 4) for c in center],
            attractor_variance=[round(v, 6) for v in variance],
            n_observations=n,
            time_span_hours=time_span_hours,
            notable_perturbations=perturbation_count,
            dimension_trends=trends,
        )

        attempted_at = _comparable_datetime(now or datetime.now())
        return self._commit_day_summary(summary, attempted_at)

    def _commit_day_summary(
        self,
        summary: DaySummary,
        attempted_at: datetime,
        *,
        deduplicate: bool = False,
    ) -> DaySummary:
        """Commit a summary and retain it for an idempotent uncertain retry."""
        self._day_summary_last_attempt_at = attempted_at
        self._day_summary_pending = summary
        try:
            self._save_day_summary(
                summary,
                written_at=attempted_at,
                deduplicate=deduplicate,
            )
        except Exception as exc:
            self._day_summary_last_error = f"{type(exc).__name__}: {exc}"
            self._next_day_summary_check_at = attempted_at + DAY_SUMMARY_RETRY_INTERVAL
            raise

        self._day_summary_last_success_at = attempted_at
        self._day_summary_last_error = None
        self._day_summary_pending = None
        self._next_day_summary_check_at = attempted_at + DAY_SUMMARY_INTERVAL

        return summary

    def _ensure_day_summary_bootstrap_marker(self, current: datetime) -> None:
        """Persist a bounded startup clock before enough evidence exists."""
        path = self._get_summaries_path()
        if (
            self._day_summary_bootstrap_checked
            and path.exists()
            and self._day_summary_last_error is None
        ):
            return

        self._day_summary_last_attempt_at = current
        try:
            if path.exists():
                document = self._read_day_summary_document()
                if document["summaries"]:
                    # The prior error was not an uncertain bootstrap write
                    # (for example, an operator repaired a malformed legacy
                    # document). A successful strict read is enough to clear
                    # that non-pending error; real summary writes retain their
                    # pending object and take the retry branch above.
                    self._day_summary_last_error = None
                    self._next_day_summary_check_at = None
                    self._day_summary_bootstrap_checked = True
                    return
                if "writer_started_at" not in document:
                    # Upgrade an empty pre-marker document in place. Mere file
                    # existence cannot prove the writer ever started.
                    document["writer_started_at"] = current.isoformat()
                else:
                    started_at = _parse_summary_timestamp(
                        document["writer_started_at"], "writer_started_at"
                    )
                    if started_at > current + timedelta(
                        seconds=DAY_SUMMARY_FUTURE_TOLERANCE_SECONDS
                    ):
                        raise ValueError("day summary writer_started_at is future-dated")

                    if self._day_summary_last_error is None:
                        self._day_summary_bootstrap_checked = True
                        return
                    # A prior marker write may have reached replace() and then
                    # failed directory fsync. Rewrite the observed document to
                    # confirm durability instead of treating existence as success.
            else:
                document = {
                    "summaries": [],
                    "writer_started_at": current.isoformat(),
                    "version": "1.0",
                }
            atomic_json_write(path, document)
        except Exception as exc:
            self._day_summary_last_error = f"{type(exc).__name__}: {exc}"
            self._next_day_summary_check_at = current + DAY_SUMMARY_RETRY_INTERVAL
            raise

        self._day_summary_last_error = None
        self._next_day_summary_check_at = None
        self._day_summary_bootstrap_checked = True

    def maybe_consolidate_daily(
        self, now: Optional[datetime] = None
    ) -> Optional[DaySummary]:
        """Write at most one real summary per 24 hours from this live deque.

        The server calls this on each history tick. In-memory scheduling keeps
        the common path free of disk reads, while persisted ``written_at``
        makes the cadence idempotent across restarts. Missing days are not
        backfilled: one write always represents one actual observation set.
        """
        current = _comparable_datetime(now or datetime.now())
        if (
            self._next_day_summary_check_at is not None
            and current < self._next_day_summary_check_at
        ):
            return None
        if self._day_summary_pending is not None:
            # atomic_json_write can raise after replace() if directory fsync
            # fails. Re-append idempotently so both "old file" and "new file"
            # outcomes converge on one confirmed summary and one heartbeat.
            return self._commit_day_summary(
                self._day_summary_pending,
                current,
                deduplicate=True,
            )
        # No subset can be eligible yet. Persist one bounded bootstrap clock,
        # then keep the ordinary warm-up path free of disk writes. Do not
        # schedule a future recheck: the 100th record must get an immediate
        # write opportunity on that same server tick.
        if len(self._history) < DAY_SUMMARY_MIN_OBSERVATIONS:
            self._ensure_day_summary_bootstrap_marker(current)
            return None

        try:
            document = self._read_day_summary_document()
            latest_evidence = self._latest_summary_evidence(document)
            written_at = self._summary_written_at(document, latest_evidence)
        except Exception as exc:
            self._day_summary_last_attempt_at = current
            self._day_summary_last_error = f"{type(exc).__name__}: {exc}"
            self._next_day_summary_check_at = current + DAY_SUMMARY_RETRY_INTERVAL
            raise

        future_limit = current + timedelta(
            seconds=DAY_SUMMARY_FUTURE_TOLERANCE_SECONDS
        )
        if latest_evidence is not None and latest_evidence > future_limit:
            future_error = ValueError("newest summary evidence is future-dated")
            self._day_summary_last_attempt_at = current
            self._day_summary_last_error = f"ValueError: {future_error}"
            self._next_day_summary_check_at = current + DAY_SUMMARY_RETRY_INTERVAL
            raise future_error
        if written_at is not None and written_at > future_limit:
            future_error = ValueError("day summary written_at is future-dated")
            self._day_summary_last_attempt_at = current
            self._day_summary_last_error = f"ValueError: {future_error}"
            self._next_day_summary_check_at = current + DAY_SUMMARY_RETRY_INTERVAL
            raise future_error

        # A strict read/validation retry repaired a prior non-write error.
        # A pending write takes the idempotent branch above and is cleared only
        # by a confirmed atomic commit.
        if self._day_summary_last_error is not None:
            self._day_summary_last_error = None

        writer_due = (
            written_at is None or current - written_at >= DAY_SUMMARY_INTERVAL
        )
        evidence_due = (
            latest_evidence is None
            or current - latest_evidence >= DAY_SUMMARY_INTERVAL
        )
        if not writer_due and not evidence_due:
            assert written_at is not None
            assert latest_evidence is not None
            self._next_day_summary_check_at = min(
                written_at + DAY_SUMMARY_INTERVAL,
                latest_evidence + DAY_SUMMARY_INTERVAL,
            )
            return None

        cutoff = current - DAY_SUMMARY_LOOKBACK
        if latest_evidence is not None:
            cutoff = max(cutoff, latest_evidence)
        candidates = [
            snapshot
            for snapshot in self._history
            if cutoff < _comparable_datetime(snapshot.timestamp) <= current
        ]
        if len(candidates) < DAY_SUMMARY_MIN_OBSERVATIONS:
            # The deque may contain old load-time rows. Re-evaluate on the next
            # live record so the moment 100 current rows exist is not hidden
            # behind a timer while the dead-man switch already sees eligibility.
            # A missing output still needs a durable, bounded startup marker;
            # total deque length alone cannot prove the live writer started.
            self._ensure_day_summary_bootstrap_marker(current)
            self._next_day_summary_check_at = None
            return None

        return self.consolidate(observations=candidates, now=current)

    def day_summary_health(
        self,
        now: Optional[datetime] = None,
        max_age_seconds: float = DAY_SUMMARY_MAX_AGE_SECONDS,
    ) -> Dict[str, Any]:
        """Return detailed freshness for health surfaces and operator probes."""
        current = _comparable_datetime(now or datetime.now())
        recent_cutoff = current - DAY_SUMMARY_LOOKBACK
        recent_count = sum(
            1
            for snapshot in self._history
            if recent_cutoff < _comparable_datetime(snapshot.timestamp) <= current
        )
        eligible = recent_count >= DAY_SUMMARY_MIN_OBSERVATIONS

        def stamp(value: Optional[datetime]) -> Optional[str]:
            return value.isoformat() if value is not None else None

        result: Dict[str, Any] = {
            "ok": False,
            "status": "unknown",
            "reason": None,
            "eligible": eligible,
            "recent_observations": recent_count,
            "max_age_seconds": max_age_seconds,
            "bootstrap": {
                "started_at": None,
                "age_seconds": None,
                "max_age_seconds": DAY_SUMMARY_BOOTSTRAP_GRACE_SECONDS,
            },
            "evidence": {"newest_at": None, "age_seconds": None},
            "writer": {
                "written_at": None,
                "age_seconds": None,
                "last_attempt_at": stamp(self._day_summary_last_attempt_at),
                "last_success_at": stamp(self._day_summary_last_success_at),
                "last_error": self._day_summary_last_error,
            },
        }

        if self._day_summary_last_error is not None:
            result.update(
                status="error",
                reason=f"last writer attempt failed: {self._day_summary_last_error}",
            )
            return result

        summaries_path = self._get_summaries_path()
        if not summaries_path.exists():
            result.update(
                status="missing",
                reason="day summary writer has no bootstrap marker",
            )
            return result

        try:
            document = self._read_day_summary_document()
            latest_evidence = self._latest_summary_evidence(document)
            if latest_evidence is None:
                started_at = _parse_summary_timestamp(
                    document.get("writer_started_at"),
                    "writer_started_at",
                )
                bootstrap_age = (current - started_at).total_seconds()
                result["bootstrap"] = {
                    "started_at": started_at.isoformat(),
                    "age_seconds": round(bootstrap_age, 1),
                    "max_age_seconds": DAY_SUMMARY_BOOTSTRAP_GRACE_SECONDS,
                }
                if bootstrap_age < -DAY_SUMMARY_FUTURE_TOLERANCE_SECONDS:
                    result.update(
                        status="future",
                        reason="day summary writer_started_at is future-dated",
                    )
                elif eligible:
                    result.update(
                        status="missing",
                        reason="eligible source has no day summary",
                    )
                elif bootstrap_age > DAY_SUMMARY_BOOTSTRAP_GRACE_SECONDS:
                    result.update(
                        status="bootstrap_timeout",
                        reason="day summary bootstrap grace expired",
                    )
                else:
                    result.update(
                        ok=True,
                        status="warming_up",
                        reason="source not yet eligible",
                    )
                return result
            written_at = self._summary_written_at(
                document,
                latest_evidence,
                legacy_mtime=True,
            )
            if written_at is None:
                raise ValueError("day summary writer timestamp is missing")
        except Exception as exc:
            result.update(
                status="malformed",
                reason=f"{type(exc).__name__}: {exc}",
            )
            return result

        evidence_age = (current - latest_evidence).total_seconds()
        writer_age = (current - written_at).total_seconds()
        result["evidence"] = {
            "newest_at": latest_evidence.isoformat(),
            "age_seconds": round(evidence_age, 1),
        }
        result["writer"].update(
            written_at=written_at.isoformat(),
            age_seconds=round(writer_age, 1),
        )

        tolerance = DAY_SUMMARY_FUTURE_TOLERANCE_SECONDS
        if evidence_age < -tolerance or writer_age < -tolerance:
            result.update(status="future", reason="day summary timestamp is future-dated")
            return result

        worst_age = max(evidence_age, writer_age)
        if worst_age > max_age_seconds:
            result.update(
                status="stale",
                reason=(
                    f"day summary stale: writer={writer_age:.0f}s "
                    f"evidence={evidence_age:.0f}s max={max_age_seconds:.0f}s"
                ),
            )
            return result

        result.update(ok=True, status="ok", reason=None)
        return result

    def get_day_summaries(self, limit: int = 30) -> List[DaySummary]:
        """
        Load persisted day summaries.

        Args:
            limit: Maximum number of summaries to return (most recent first)

        Returns:
            List of DaySummary objects, newest first
        """
        summaries_path = self._get_summaries_path()
        if not summaries_path.exists():
            return []

        try:
            with open(summaries_path, 'r') as f:
                data = json.load(f)
            summaries = [DaySummary.from_dict(d) for d in data.get("summaries", [])]
            # Return newest first, limited
            return list(reversed(summaries[-limit:]))
        except Exception as e:
            print(f"[AnimaHistory] Could not load day summaries: {e}", file=sys.stderr)
            return []

    def detect_long_term_trend(
        self, dimension: str, window_days: int = 7
    ) -> Optional[Dict[str, Any]]:
        """
        Detect long-term trend in a dimension across day summaries.

        Uses simple linear regression over day summary centers to find
        whether a dimension is trending up, down, or stable.

        Args:
            dimension: One of 'warmth', 'clarity', 'stability', 'presence'
            window_days: Number of recent summaries to analyze

        Returns:
            Dict with trend info, or None if insufficient data (<3 summaries)
        """
        summaries = self.get_day_summaries(limit=window_days)

        # Fail toward unknown, never stale-as-fresh. Audited 2026-08-21:
        # day_summaries.json had not been written since 2026-03-28, and this
        # function re-derived the same four March slopes every reflect cycle
        # for five months, each cycle re-validating trend insights whose
        # directions the current data contradicts (#188). Guards, in order:
        #   - a summary with an unparsable date is dropped, not fatal (one
        #     bad row must not disable the subsystem for every dimension);
        #   - EVERY summary in the regression must lie within the window —
        #     checking only the newest would let one fresh summary launder
        #     six months-old ones into a "recent" trend;
        #   - fewer than 3 in-window summaries is no trend data.
        cutoff = datetime.now() - timedelta(days=window_days)
        fresh: List[DaySummary] = []
        for s in summaries:
            try:
                if datetime.fromisoformat(s.date) >= cutoff:
                    fresh.append(s)
            except (ValueError, TypeError):
                continue
        if len(fresh) < 3:
            if summaries and not getattr(self, "_trend_stale_warned", False):
                self._trend_stale_warned = True
                print(f"[AnimaHistory] Trend detection has {len(fresh)} "
                      f"in-window summaries (of {len(summaries)} stored, "
                      f"window {window_days}d) — trends unavailable; if "
                      f"summaries should be arriving, the consolidation "
                      f"writer is broken (#188)", file=sys.stderr, flush=True)
            return None
        summaries = fresh
        newest = max(datetime.fromisoformat(s.date) for s in summaries)

        dim_idx = ["warmth", "clarity", "stability", "presence"].index(dimension)

        # Extract values (summaries are newest-first, reverse for chronological)
        values = [s.attractor_center[dim_idx] for s in reversed(summaries)]
        n = len(values)

        # Simple linear regression: y = mx + b
        x_mean = (n - 1) / 2.0
        y_mean = sum(values) / n

        numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
        denominator = sum((i - x_mean)**2 for i in range(n))

        if denominator == 0:
            slope = 0.0
        else:
            slope = numerator / denominator

        # Determine direction
        if abs(slope) < 0.005:
            direction = "stable"
        elif slope > 0:
            direction = "increasing"
        else:
            direction = "decreasing"

        return {
            "dimension": dimension,
            "trend": round(slope, 6),
            "direction": direction,
            "n_summaries": n,
            "recent_value": round(values[-1], 4),
            "oldest_value": round(values[0], 4),
            # When the newest contributing summary landed — consumers gate
            # re-validation on this, so a static summary set cannot keep
            # re-validating the same trend day after day.
            "newest_summary_at": newest.isoformat(),
        }

    def _get_summaries_path(self) -> Path:
        """Get path for day summaries persistence."""
        return self.persistence_path.parent / "day_summaries.json"

    def _read_day_summary_document(self) -> Dict[str, Any]:
        """Strictly read the mutation document; never convert damage to empty."""
        summaries_path = self._get_summaries_path()
        if not summaries_path.exists():
            return {"summaries": [], "version": "1.0"}

        with open(summaries_path, "r") as handle:
            document = json.load(handle)
        if not isinstance(document, dict):
            raise ValueError("day summary document must be an object")
        if "summaries" not in document or not isinstance(document["summaries"], list):
            raise ValueError("day summary document has no summaries list")
        return document

    def _latest_summary_evidence(
        self, document: Dict[str, Any]
    ) -> Optional[datetime]:
        """Return newest embedded evidence time, validating every stored row."""
        evidence: List[datetime] = []
        for index, row in enumerate(document["summaries"]):
            if not isinstance(row, dict):
                raise ValueError(f"day summary row {index} must be an object")
            evidence.append(
                _parse_summary_timestamp(row.get("date"), f"summary row {index} date")
            )
        return max(evidence) if evidence else None

    def _summary_written_at(
        self,
        document: Dict[str, Any],
        latest_evidence: Optional[datetime],
        *,
        legacy_mtime: bool = False,
    ) -> Optional[datetime]:
        """Resolve writer time, with explicit backward-compatible fallbacks."""
        if "written_at" in document:
            return _parse_summary_timestamp(document["written_at"], "written_at")
        if legacy_mtime and self._get_summaries_path().exists():
            return datetime.fromtimestamp(self._get_summaries_path().stat().st_mtime)
        # For cadence, a v1 row is the best durable record of the last write.
        return latest_evidence

    def _save_day_summary(
        self,
        summary: DaySummary,
        *,
        written_at: Optional[datetime] = None,
        deduplicate: bool = False,
    ) -> None:
        """Append atomically, preserving the old file on any read/write error."""
        summaries_path = self._get_summaries_path()
        document = self._read_day_summary_document()
        existing = list(document["summaries"])

        serialized = summary.to_dict()
        if not (deduplicate and existing and existing[-1] == serialized):
            existing.append(serialized)
        existing = existing[-30:]

        payload = dict(document)
        payload.update({
            "summaries": existing,
            "written_at": _comparable_datetime(
                written_at or datetime.now()
            ).isoformat(),
            "version": "1.0",
        })
        atomic_json_write(summaries_path, payload)

    def __len__(self) -> int:
        return len(self._history)

    def _save(self):
        """Persist history to disk."""
        try:
            # Only save last 500 for disk efficiency
            recent = list(self._history)[-500:]
            data = {
                "observations": [s.to_dict() for s in recent],
                "saved_at": datetime.now().isoformat(),
                "version": "1.0",
            }
            atomic_json_write(self.persistence_path, data)
        except Exception as e:
            print(f"[AnimaHistory] Could not save: {e}", file=sys.stderr)

    def _load(self):
        """Load history from disk."""
        if not self.persistence_path.exists():
            return

        try:
            with open(self.persistence_path, 'r') as f:
                data = json.load(f)

            for obs in data.get("observations", []):
                self._history.append(AnimaSnapshot.from_dict(obs))

            print(f"[AnimaHistory] Loaded {len(self._history)} observations", file=sys.stderr)
        except Exception as e:
            print(f"[AnimaHistory] Could not load: {e}", file=sys.stderr)

    def save(self):
        """Explicitly save the history."""
        self._save()

    def clear(self):
        """Clear all history (use with caution)."""
        self._history.clear()


# === Singleton Pattern ===

_history: Optional[AnimaHistory] = None


def get_anima_history() -> AnimaHistory:
    """Get or create the global AnimaHistory instance."""
    global _history
    if _history is None:
        _history = AnimaHistory()
    return _history


def reset_anima_history():
    """Reset the global AnimaHistory (mainly for testing)."""
    global _history
    _history = None
