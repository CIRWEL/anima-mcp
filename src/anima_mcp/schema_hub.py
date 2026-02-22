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

    def compose_schema(
        self,
        identity: Optional['CreatureIdentity'] = None,
        anima: Optional[Any] = None,
        readings: Optional[Any] = None,
        growth_system: Optional['GrowthSystem'] = None,
        self_model: Optional['SelfModel'] = None,
    ) -> SelfSchema:
        """
        Compose unified schema from all source systems.

        This is the main entry point - call this each tick instead of
        extract_self_schema directly.

        Args:
            identity: CreatureIdentity from identity store
            anima: AnimaState with current anima values
            readings: SensorReadings with sensor data
            growth_system: GrowthSystem for preferences
            self_model: SelfModel for beliefs

        Returns:
            SelfSchema with all nodes and edges
        """
        # 1. Get base schema from existing extraction
        schema = extract_self_schema(
            identity=identity,
            anima=anima,
            readings=readings,
            growth_system=growth_system,
            self_model=self_model,
            include_preferences=True,
        )

        # 2. Inject identity enrichment nodes
        schema = self._inject_identity_enrichment(schema, identity)

        # 3. Add to history
        self.schema_history.append(schema)

        # 4. TODO: Inject trajectory feedback nodes (Task 6)
        # 5. TODO: Inject gap texture nodes (Task 5)

        return schema

    def _inject_identity_enrichment(
        self,
        schema: SelfSchema,
        identity: Optional['CreatureIdentity'],
    ) -> SelfSchema:
        """
        Add identity meta-nodes (alive_ratio, awakenings, age).

        These aren't metrics - they're texture. Part of who Lumen is.
        """
        if not identity:
            return schema

        try:
            import math

            # Existence ratio: how present vs absent (kintsugi texture)
            alive_ratio = identity.alive_ratio()
            schema.nodes.append(SchemaNode(
                node_id="meta_existence_ratio",
                node_type="meta",
                label="Exist%",
                value=alive_ratio,  # Already 0-1
                raw_value=alive_ratio,
            ))

            # Awakening count: times returned from nothing
            awakenings = identity.total_awakenings
            # Normalize to 0-1 for display (log scale, 100 awakenings = 1.0)
            normalized = min(1.0, math.log10(max(1, awakenings)) / 2)
            schema.nodes.append(SchemaNode(
                node_id="meta_awakening_count",
                node_type="meta",
                label="Wakes",
                value=normalized,
                raw_value=awakenings,
            ))

            # Age in days
            age_seconds = identity.age_seconds()
            age_days = age_seconds / 86400
            # Normalize: 100 days = 1.0
            normalized = min(1.0, age_days / 100)
            schema.nodes.append(SchemaNode(
                node_id="meta_age_days",
                node_type="meta",
                label="Age",
                value=normalized,
                raw_value=age_days,
            ))

        except Exception:
            pass  # Non-fatal if identity methods fail

        return schema

    def persist_schema(self) -> bool:
        """
        Persist current schema to disk for gap handling.

        Called on sleep/shutdown to save state for later recovery.

        Returns:
            True if persisted successfully
        """
        if not self.schema_history:
            return False

        schema = self.schema_history[-1]

        # Ensure directory exists
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)

        # Serialize schema
        data = schema.to_dict()
        data["_hub_meta"] = {
            "history_length": len(self.schema_history),
            "persisted_at": datetime.now().isoformat(),
        }

        try:
            self.persist_path.write_text(json.dumps(data, indent=2))
            return True
        except Exception:
            return False

    def load_previous_schema(self) -> Optional[SelfSchema]:
        """
        Load previously persisted schema from disk.

        Called on wake to compute gap delta.

        Returns:
            SelfSchema if found and valid, None otherwise
        """
        if not self.persist_path.exists():
            return None

        try:
            data = json.loads(self.persist_path.read_text())

            # Reconstruct nodes
            nodes = [
                SchemaNode(
                    node_id=n["id"],
                    node_type=n["type"],
                    label=n["label"],
                    value=n["value"],
                    raw_value=n.get("raw_value"),
                )
                for n in data.get("nodes", [])
            ]

            # Reconstruct edges
            edges = [
                SchemaEdge(
                    source_id=e["source"],
                    target_id=e["target"],
                    weight=e["weight"],
                )
                for e in data.get("edges", [])
            ]

            # Parse timestamp
            timestamp = datetime.fromisoformat(data["timestamp"])

            return SelfSchema(
                timestamp=timestamp,
                nodes=nodes,
                edges=edges,
            )
        except Exception:
            return None
