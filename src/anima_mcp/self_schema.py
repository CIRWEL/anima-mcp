"""
Self-Schema Graph (G_t) - Lumen's internal representation of self.

Nodes:
- 1 identity (center)
- 4 anima dimensions (warmth, clarity, stability, presence)
- 7 sensors (light, temp, humidity, pressure, memory, cpu, disk)

Edges derived from NervousSystemCalibration weights.
Identity connects to all anima dimensions (structural "I am" edges).

This is the ground truth for visual integrity checking.
Any rendering R(G_t) should faithfully represent this structure.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime


@dataclass
class SchemaNode:
    """A node in Lumen's self-schema graph."""
    node_id: str
    node_type: str  # "identity", "anima", "sensor"
    label: str
    value: float  # Normalized 0-1 for display
    raw_value: Any = None  # Original value before normalization

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.node_id,
            "type": self.node_type,
            "label": self.label,
            "value": self.value,
            "raw_value": self.raw_value,
        }


@dataclass
class SchemaEdge:
    """An edge in Lumen's self-schema graph."""
    source_id: str
    target_id: str
    weight: float  # -1 to 1, strength and direction of influence

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source_id,
            "target": self.target_id,
            "weight": self.weight,
        }


@dataclass
class SelfSchema:
    """G_t - Lumen's self-schema graph at time t."""
    timestamp: datetime
    nodes: List[SchemaNode] = field(default_factory=list)
    edges: List[SchemaEdge] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
        }

    def generate_vqa_ground_truth(self) -> List[Dict[str, Any]]:
        """
        Generate VQA questions and ground-truth answers for StructScore.

        PoC: Simple counting and existence questions.
        """
        qa_pairs = []

        # Count by type
        type_counts = {}
        for node in self.nodes:
            type_counts[node.node_type] = type_counts.get(node.node_type, 0) + 1

        for node_type, count in type_counts.items():
            qa_pairs.append({
                "question": f"How many {node_type} nodes are shown?",
                "answer": str(count),
                "type": "counting",
            })

        # Total count
        qa_pairs.append({
            "question": "How many total nodes are in the graph?",
            "answer": str(len(self.nodes)),
            "type": "counting",
        })

        # Edge count
        qa_pairs.append({
            "question": "How many connections (edges) are shown?",
            "answer": str(len(self.edges)),
            "type": "counting",
        })

        # Existence questions for each node
        for node in self.nodes:
            qa_pairs.append({
                "question": f"Is there a node labeled '{node.label}'?",
                "answer": "yes",
                "type": "existence",
            })

        # Value questions for anima nodes
        for node in self.nodes:
            if node.node_type == "anima":
                level = "high" if node.value > 0.6 else "low" if node.value < 0.4 else "medium"
                qa_pairs.append({
                    "question": f"Is {node.label} {level}?",
                    "answer": "yes",
                    "type": "attribute",
                })

        return qa_pairs


def _get_sensor_anima_weights() -> Dict[Tuple[str, str], float]:
    """
    Derive sensor→anima edge weights from NervousSystemCalibration.

    Reads the actual nervous system wiring so the schema stays in sync
    with config changes.  Falls back to minimal defaults in tests.
    """
    try:
        from .config import get_calibration
        cal = get_calibration()
    except Exception:
        return {
            ("sensor_light", "anima_clarity"): 0.4,
            ("sensor_temp", "anima_warmth"): 0.3,
            ("sensor_humidity", "anima_stability"): -0.25,
            ("sensor_memory", "anima_stability"): -0.3,
            ("sensor_memory", "anima_presence"): -0.3,
            ("sensor_cpu", "anima_presence"): -0.25,
            ("sensor_disk", "anima_presence"): -0.25,
            ("sensor_pressure", "anima_stability"): -0.15,
        }

    weights: Dict[Tuple[str, str], float] = {}

    # --- Warmth ---
    # Warmth ← cpu_temp + ambient_temp (both map to sensor_temp node)
    temp_to_warmth = cal.warmth_weights.get("cpu_temp", 0) + cal.warmth_weights.get("ambient_temp", 0)
    if temp_to_warmth > 0:
        weights[("sensor_temp", "anima_warmth")] = temp_to_warmth

    # --- Clarity ---
    # Clarity ← light
    light_to_clarity = cal.clarity_weights.get("light", 0)
    if light_to_clarity > 0:
        weights[("sensor_light", "anima_clarity")] = light_to_clarity

    # --- Stability ---
    # Stability ← humidity deviation (inverse: deviation hurts stability)
    humidity_to_stability = cal.stability_weights.get("humidity_dev", 0)
    if humidity_to_stability > 0:
        weights[("sensor_humidity", "anima_stability")] = -humidity_to_stability

    # Stability ← memory pressure (inverse: high memory = less stable)
    memory_to_stability = cal.stability_weights.get("memory", 0)
    if memory_to_stability > 0:
        weights[("sensor_memory", "anima_stability")] = -memory_to_stability

    # Stability ← pressure deviation (inverse: deviation hurts stability)
    pressure_to_stability = cal.stability_weights.get("pressure_dev", 0)
    if pressure_to_stability > 0:
        weights[("sensor_pressure", "anima_stability")] = -pressure_to_stability

    # --- Presence (all inverse: resource usage = void, inverted to get presence) ---
    memory_to_presence = cal.presence_weights.get("memory", 0)
    if memory_to_presence > 0:
        weights[("sensor_memory", "anima_presence")] = -memory_to_presence

    cpu_to_presence = cal.presence_weights.get("cpu", 0)
    if cpu_to_presence > 0:
        weights[("sensor_cpu", "anima_presence")] = -cpu_to_presence

    disk_to_presence = cal.presence_weights.get("disk", 0)
    if disk_to_presence > 0:
        weights[("sensor_disk", "anima_presence")] = -disk_to_presence

    return weights


def _belief_label(belief_id: str) -> str:
    """Short label for a belief node in the schema graph."""
    labels = {
        "light_sensitive": "BLit",
        "temp_sensitive": "BTmp",
        "stability_recovery": "BRec",
        "warmth_recovery": "BWrc",
        "temp_clarity_correlation": "BTC",
        "light_warmth_correlation": "BLW",
        "interaction_clarity_boost": "BInt",
        "evening_warmth_increase": "BEve",
        "morning_clarity": "BMrn",
        "question_asking_tendency": "BQst",
    }
    return labels.get(belief_id, f"B{belief_id[:3]}")


def extract_self_schema(
    identity=None,
    anima=None,
    readings=None,
    growth_system=None,
    include_preferences: bool = True,
    self_model=None,
) -> SelfSchema:
    """
    Extract G_t from Lumen's current state.

    Base: 12 nodes (1 identity + 4 anima + 4 sensors + 3 resources), ~15 edges.
    Enhanced: +N preference nodes, +N belief nodes from self-model.

    Args:
        identity: CreatureIdentity from identity store
        anima: AnimaState with warmth, clarity, stability, presence
        readings: SensorReadings with light, temp, humidity
        growth_system: GrowthSystem for learned preferences
        include_preferences: Whether to include preference nodes (default: True)
        self_model: SelfModel for learned self-beliefs (optional)
    """
    now = datetime.now()
    nodes: List[SchemaNode] = []
    edges: List[SchemaEdge] = []

    # === IDENTITY NODE (center) ===
    identity_name = "Lumen"
    identity_value = 1.0  # Always present
    if identity and hasattr(identity, 'name'):
        identity_name = identity.name or "Lumen"

    nodes.append(SchemaNode(
        node_id="identity",
        node_type="identity",
        label=identity_name,
        value=identity_value,
        raw_value={"name": identity_name},
    ))

    # === ANIMA NODES (ring 1) ===
    anima_dims = ["warmth", "clarity", "stability", "presence"]
    anima_values = {
        "warmth": 0.5,
        "clarity": 0.5,
        "stability": 0.5,
        "presence": 0.5,
    }

    if anima:
        anima_values = {
            "warmth": getattr(anima, "warmth", 0.5),
            "clarity": getattr(anima, "clarity", 0.5),
            "stability": getattr(anima, "stability", 0.5),
            "presence": getattr(anima, "presence", 0.5),
        }

    for dim in anima_dims:
        nodes.append(SchemaNode(
            node_id=f"anima_{dim}",
            node_type="anima",
            label=dim.capitalize(),
            value=anima_values.get(dim, 0.5),
            raw_value=anima_values.get(dim, 0.5),
        ))

    # === SENSOR NODES (ring 2) ===
    # Physical sensors
    sensor_values = {
        "light": 0.5,
        "temp": 0.5,
        "humidity": 0.5,
        "pressure": 0.5,
    }
    # System resource sensors
    resource_values = {
        "memory": 0.5,
        "cpu": 0.5,
        "disk": 0.5,
    }

    if readings:
        # Normalize physical sensor values to 0-1 range
        light = getattr(readings, "light_lux", None)
        if light is not None:
            sensor_values["light"] = min(1.0, light / 1000.0)  # 0-1000 lux range

        temp = getattr(readings, "ambient_temp_c", None) or getattr(readings, "cpu_temp_c", None)
        if temp is not None:
            sensor_values["temp"] = min(1.0, max(0.0, (temp - 15) / 25))  # 15-40°C range

        humidity = getattr(readings, "humidity_pct", None)
        if humidity is not None:
            sensor_values["humidity"] = humidity / 100.0  # Already 0-100

        pressure = getattr(readings, "pressure_hpa", None)
        if pressure is not None:
            # Normalize relative to config's pressure_ideal (accounts for altitude)
            # ±50 hPa range around ideal → 0-1
            try:
                from .config import get_calibration
                p_ideal = get_calibration().pressure_ideal
            except Exception:
                p_ideal = 1013.25
            sensor_values["pressure"] = min(1.0, max(0.0, 1.0 - abs(pressure - p_ideal) / 50.0))

        # System resources (0-100% -> 0-1)
        cpu = getattr(readings, "cpu_percent", None)
        if cpu is not None:
            resource_values["cpu"] = cpu / 100.0

        memory = getattr(readings, "memory_percent", None)
        if memory is not None:
            resource_values["memory"] = memory / 100.0

        disk = getattr(readings, "disk_percent", None)
        if disk is not None:
            resource_values["disk"] = disk / 100.0

    sensor_labels = {
        "light": "Light",
        "temp": "Temp",
        "humidity": "Humid",
        "pressure": "Press",
    }
    resource_labels = {
        "memory": "Mem",
        "cpu": "CPU",
        "disk": "Disk",
    }

    for sensor_id, value in sensor_values.items():
        nodes.append(SchemaNode(
            node_id=f"sensor_{sensor_id}",
            node_type="sensor",
            label=sensor_labels[sensor_id],
            value=value,
            raw_value=value,
        ))

    for resource_id, value in resource_values.items():
        nodes.append(SchemaNode(
            node_id=f"sensor_{resource_id}",
            node_type="resource",
            label=resource_labels[resource_id],
            value=value,
            raw_value=value,
        ))

    # === PREFERENCE NODES (ring 3, optional) ===
    # Use GrowthSystem for learned preferences (456K+ observations in DB)
    pref_summary = None
    if include_preferences and growth_system:
        try:
            pref_summary = growth_system.get_dimension_preferences()
        except Exception:
            pass

    if pref_summary:
        for dim, pref_data in pref_summary.items():
            # Only include confident preferences (confidence > 0.2)
            if pref_data.get("confidence", 0) > 0.2 and dim in ["warmth", "clarity", "stability", "presence"]:
                # Use valence as node value (how much Lumen values this dimension)
                nodes.append(SchemaNode(
                    node_id=f"pref_{dim}",
                    node_type="preference",
                    label=f"P{dim[0].upper()}",  # PW, PC, PS, PP
                    value=max(0.0, min(1.0, (pref_data.get("valence", 0) + 1.0) / 2.0)),  # Normalize -1..1 to 0..1
                    raw_value={
                        "valence": pref_data.get("valence", 0),
                        "optimal_range": pref_data.get("optimal_range", (0.3, 0.7)),
                        "confidence": pref_data.get("confidence", 0),
                    },
                ))

    # === BELIEF NODES (ring 4, from SelfModel) ===
    # Beliefs Lumen has learned about itself — only included if confident enough.
    # Correlation beliefs also modulate sensor→anima edge weights below.
    belief_summary = None
    if self_model:
        try:
            belief_summary = self_model.get_belief_summary()
        except Exception:
            pass

    _correlation_beliefs = {}  # belief_id → value, for modulating edges below
    if belief_summary:
        for belief_id, bdata in belief_summary.items():
            confidence = bdata.get("confidence", 0)
            evidence = bdata.get("evidence", "0+ / 0-")
            # Only include beliefs that have been tested (have evidence) and are confident
            total_evidence = sum(int(x.strip().rstrip("+-")) for x in evidence.split("/") if x.strip().rstrip("+-").isdigit())
            if total_evidence < 1 or confidence < 0.3:
                continue  # Untested or not confident enough

            # Track correlation beliefs for edge modulation
            if belief_id in ("temp_clarity_correlation", "light_warmth_correlation"):
                _correlation_beliefs[belief_id] = bdata.get("value", 0.5)

            nodes.append(SchemaNode(
                node_id=f"belief_{belief_id}",
                node_type="belief",
                label=_belief_label(belief_id),
                value=bdata.get("value", 0.5),
                raw_value={
                    "description": bdata.get("description", ""),
                    "confidence": confidence,
                    "strength": bdata.get("strength", "uncertain"),
                    "evidence": bdata.get("evidence", "0+ / 0-"),
                },
            ))

    # === EDGES (identity → anima: "I am constituted by these") ===
    for dim in anima_dims:
        edges.append(SchemaEdge(
            source_id="identity",
            target_id=f"anima_{dim}",
            weight=anima_values.get(dim, 0.5),  # Weight = current dimension value
        ))

    # === EDGES (sensor → anima influences, derived from NervousSystemCalibration) ===
    # Correlation beliefs modulate these weights: learned knowledge overrides static config
    sensor_weights = _get_sensor_anima_weights()

    # Apply learned correlation beliefs to sensor→anima edges
    if _correlation_beliefs:
        # temp_clarity_correlation: value 0.5 = no effect, >0.5 = positive, <0.5 = negative
        if "temp_clarity_correlation" in _correlation_beliefs:
            learned = (_correlation_beliefs["temp_clarity_correlation"] - 0.5) * 2  # Map 0..1 → -1..1
            if ("sensor_temp", "anima_clarity") in sensor_weights:
                sensor_weights[("sensor_temp", "anima_clarity")] = learned * 0.4
            elif abs(learned) > 0.2:
                sensor_weights[("sensor_temp", "anima_clarity")] = learned * 0.4

        if "light_warmth_correlation" in _correlation_beliefs:
            learned = (_correlation_beliefs["light_warmth_correlation"] - 0.5) * 2
            if ("sensor_light", "anima_warmth") in sensor_weights:
                sensor_weights[("sensor_light", "anima_warmth")] = learned * 0.4
            elif abs(learned) > 0.2:
                sensor_weights[("sensor_light", "anima_warmth")] = learned * 0.4
    node_ids = {n.node_id for n in nodes}
    for (source_id, target_id), weight in sensor_weights.items():
        if source_id in node_ids and target_id in node_ids:
            edges.append(SchemaEdge(
                source_id=source_id,
                target_id=target_id,
                weight=weight,
            ))

    # === EDGES (preference → anima satisfaction) ===
    if include_preferences and pref_summary and anima:
        for dim in ["warmth", "clarity", "stability", "presence"]:
            if dim in pref_summary:
                pref_data = pref_summary[dim]
                if pref_data.get("confidence", 0) > 0.2:
                    try:
                        anima_value = getattr(anima, dim, 0.5)
                        # Calculate satisfaction: how well current anima matches preference
                        opt_range = pref_data.get("optimal_range", (0.3, 0.7))
                        if opt_range[0] <= anima_value <= opt_range[1]:
                            satisfaction = 1.0
                        elif anima_value < opt_range[0]:
                            satisfaction = max(0.0, 1.0 - (opt_range[0] - anima_value) * 2)
                        else:
                            satisfaction = max(0.0, 1.0 - (anima_value - opt_range[1]) * 2)
                        # Sign: positive if preference valence > 0 (Lumen values this), negative if < 0
                        sign = 1.0 if pref_data.get("valence", 0) > 0 else -1.0
                        edges.append(SchemaEdge(
                            source_id=f"pref_{dim}",
                            target_id=f"anima_{dim}",
                            weight=satisfaction * sign,
                        ))
                    except Exception:
                        pass  # Non-fatal

    # === EDGES (belief → anima: "I believe X affects Y") ===
    if belief_summary:
        # Map belief_id to which anima dimension it relates to
        _belief_anima_map = {
            "light_sensitive": "anima_clarity",
            "temp_sensitive": "anima_warmth",
            "stability_recovery": "anima_stability",
            "warmth_recovery": "anima_warmth",
            "temp_clarity_correlation": "anima_clarity",
            "light_warmth_correlation": "anima_warmth",
            "interaction_clarity_boost": "anima_clarity",
            "evening_warmth_increase": "anima_warmth",
            "morning_clarity": "anima_clarity",
        }
        node_ids = {n.node_id for n in nodes}
        for belief_id, bdata in belief_summary.items():
            source = f"belief_{belief_id}"
            target = _belief_anima_map.get(belief_id)
            if source in node_ids and target and target in node_ids:
                # Weight = confidence * direction (value > 0.5 = positive influence)
                confidence = bdata.get("confidence", 0)
                direction = (bdata.get("value", 0.5) - 0.5) * 2  # -1 to 1
                edges.append(SchemaEdge(
                    source_id=source,
                    target_id=target,
                    weight=confidence * direction,
                ))

    return SelfSchema(
        timestamp=now,
        nodes=nodes,
        edges=edges,
    )


def get_current_schema(
    identity=None,
    anima=None,
    readings=None,
    growth_system=None,
    include_preferences: bool = True,
    force_refresh: bool = False,
    preferences=None,  # Deprecated, ignored
    self_model=None,
) -> SelfSchema:
    """
    Get current G_t.

    Extraction is cheap (no I/O, just builds a small dataclass graph),
    so no caching is needed.

    Args:
        identity: CreatureIdentity (optional)
        anima: AnimaState (optional)
        readings: SensorReadings (optional)
        growth_system: GrowthSystem for learned preferences
        include_preferences: Whether to include preference nodes (default: True)
        force_refresh: Ignored (kept for API compat)
        preferences: Deprecated, ignored
        self_model: SelfModel for learned self-beliefs (optional)
    """
    return extract_self_schema(
        identity=identity,
        anima=anima,
        readings=readings,
        growth_system=growth_system,
        include_preferences=include_preferences,
        self_model=self_model,
    )
