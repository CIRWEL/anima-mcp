"""
SchemaHub - The living hub of Lumen's self-understanding.

Orchestrates all self-model systems (identity, growth, self-model, trajectory)
into a unified schema with semantic edges and trajectory feedback.

The schema IS the self-model. Other systems feed it; trajectory is computed
FROM schema history and feeds back as nodes.

See: docs/plans/2026-02-22-schema-hub-design.md
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, TYPE_CHECKING
import json

from .self_schema import SelfSchema, SchemaNode, SchemaEdge, extract_self_schema

if TYPE_CHECKING:
    from .identity.store import CreatureIdentity
    from .growth import GrowthSystem
    from .self_model import SelfModel
    from .anima_history import AnimaHistory
    from .trajectory import TrajectorySignature


@dataclass
class GapDelta:
    """Computed on wake from previous schema."""
    duration_seconds: float
    anima_delta: Dict[str, float]  # dimension -> change magnitude
    beliefs_decayed: List[str]  # belief IDs that lost confidence
    was_gap: bool = True  # False if this is first schema ever


class SchemaHub:
    """
    The living hub of Lumen's self-understanding.

    Orchestrates:
    - Schema composition from all source systems
    - Schema history for trajectory computation
    - Trajectory feedback as schema nodes
    - Schema persistence for gap handling
    - Gap delta computation on wake
    """

    def __init__(
        self,
        history_size: int = 100,
        persist_path: Optional[Path] = None,
    ):
        """
        Initialize SchemaHub.

        Args:
            history_size: Number of schemas to keep in rolling history
            persist_path: Path for schema persistence (default: ~/.anima/last_schema.json)
        """
        self.history_size = history_size
        self.schema_history: Deque[SelfSchema] = deque(maxlen=history_size)
        self.last_trajectory: Optional['TrajectorySignature'] = None
        self.persist_path = persist_path or Path.home() / ".anima" / "last_schema.json"
        self.last_gap_delta: Optional[GapDelta] = None
        self._trajectory_compute_interval = 20  # Recompute every N schemas
