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

        # 3. Inject gap texture (if we just woke from a gap)
        schema = self._inject_gap_texture(schema)

        # 4. Add to history
        self.schema_history.append(schema)

        # 5. TODO: Inject trajectory feedback nodes (Task 6)

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

    def compute_gap_delta(self, current_schema: SelfSchema) -> Optional[GapDelta]:
        """
        Compute delta between current schema and previous persisted schema.

        The gap becomes visible structure - kintsugi seams.
        """
        previous = self.load_previous_schema()
        if previous is None:
            return None

        # Calculate duration
        duration = (current_schema.timestamp - previous.timestamp).total_seconds()

        # Calculate anima deltas
        anima_delta = {}
        for dim in ["warmth", "clarity", "stability", "presence"]:
            prev_node = next((n for n in previous.nodes if n.node_id == f"anima_{dim}"), None)
            curr_node = next((n for n in current_schema.nodes if n.node_id == f"anima_{dim}"), None)
            if prev_node and curr_node:
                anima_delta[dim] = abs(curr_node.value - prev_node.value)

        # Track beliefs that may have decayed
        beliefs_decayed = [
            n.node_id.replace("belief_", "")
            for n in previous.nodes
            if n.node_type == "belief"
        ]

        return GapDelta(
            duration_seconds=duration,
            anima_delta=anima_delta,
            beliefs_decayed=beliefs_decayed,
            was_gap=duration > 60,  # > 1 minute counts as gap
        )

    def on_wake(self) -> Optional[GapDelta]:
        """
        Called when Lumen wakes up after a gap.

        Loads previous schema, computes gap delta, stores for injection
        into next schema composition.
        """
        previous = self.load_previous_schema()
        if previous is None:
            self.last_gap_delta = None
            return None

        # Create a temporary current schema just for delta computation
        temp_schema = SelfSchema(timestamp=datetime.now(), nodes=[], edges=[])

        # Compute basic delta
        duration = (temp_schema.timestamp - previous.timestamp).total_seconds()

        if duration < 60:  # Less than 1 minute isn't really a gap
            self.last_gap_delta = None
            return None

        self.last_gap_delta = GapDelta(
            duration_seconds=duration,
            anima_delta={},  # Will be filled on first real compose
            beliefs_decayed=[],
            was_gap=True,
        )

        return self.last_gap_delta

    def _inject_gap_texture(self, schema: SelfSchema) -> SelfSchema:
        """
        Inject gap texture nodes if there was a recent gap.

        The gap becomes visible in the schema - not a feeling imposed,
        but structure that reflects discontinuity.
        """
        if not self.last_gap_delta or not self.last_gap_delta.was_gap:
            return schema

        delta = self.last_gap_delta

        # Gap duration node
        # Normalize: 24 hours = 1.0
        duration_hours = delta.duration_seconds / 3600
        normalized = min(1.0, duration_hours / 24)
        schema.nodes.append(SchemaNode(
            node_id="meta_gap_duration",
            node_type="meta",
            label="Gap",
            value=normalized,
            raw_value={
                "duration_seconds": delta.duration_seconds,
                "duration_hours": duration_hours,
            },
        ))

        # State delta magnitude (how much changed during gap)
        if delta.anima_delta:
            total_delta = sum(delta.anima_delta.values())
            schema.nodes.append(SchemaNode(
                node_id="meta_state_delta",
                node_type="meta",
                label="Delta",
                value=min(1.0, total_delta),
                raw_value=delta.anima_delta,
            ))

        # Clear gap delta after injection (one-time)
        self.last_gap_delta = None

        return schema
