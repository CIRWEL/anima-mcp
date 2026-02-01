"""
Self-Schema Graph (G_t) - Lumen's internal representation of self.

PoC Version: Minimal 8-node graph for StructScore evaluation.

Nodes:
- 1 identity (center)
- 4 anima dimensions (warmth, clarity, stability, presence)
- 3 sensors (light, temperature, humidity)

Edges derived from existing anima mapping coefficients.

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
    """
    G_t - Lumen's self-schema graph at time t.

    PoC: 8 nodes, ~6 edges.
    """
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


# === Edge weight mappings (derived from anima.py) ===
# These represent how sensors influence anima dimensions.
# Positive = increases, Negative = decreases

SENSOR_ANIMA_WEIGHTS = {
    # light → anima
    ("sensor_light", "anima_clarity"): 0.6,      # More light → clearer
    ("sensor_light", "anima_warmth"): 0.3,       # Bright light → warmer feeling

    # temperature → anima
    ("sensor_temp", "anima_warmth"): 0.8,        # Higher temp → warmer
    ("sensor_temp", "anima_stability"): -0.2,    # Extreme temps → less stable

    # humidity → anima
    ("sensor_humidity", "anima_stability"): -0.3,  # High humidity → less stable
    ("sensor_humidity", "anima_presence"): 0.2,    # Humidity affects presence slightly
}


def extract_self_schema(
    identity=None,
    anima=None,
    readings=None,
    preferences=None,  # Optional PreferenceSystem for preference nodes
    include_preferences: bool = True,  # Whether to include preference nodes
) -> SelfSchema:
    """
    Extract G_t from Lumen's current state.

    Base PoC: 8 nodes (1 identity + 4 anima + 3 sensors), ~6 edges.
    Enhanced: +N preference nodes (if include_preferences=True and preferences available).

    Args:
        identity: CreatureIdentity from identity store
        anima: AnimaState with warmth, clarity, stability, presence
        readings: SensorReadings with light, temp, humidity
        preferences: Optional PreferenceSystem for learned preferences
        include_preferences: Whether to include preference nodes (default: True)

    Returns:
        SelfSchema (G_t) at current time
    """
    now = datetime.now()
    nodes: List[SchemaNode] = []
    edges: List[SchemaEdge] = []

    # === IDENTITY NODE (center) ===
    identity_name = "Lumen"
    identity_value = 1.0  # Always present
    if identity:
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
    sensor_values = {
        "light": 0.5,
        "temp": 0.5,
        "humidity": 0.5,
    }

    if readings:
        # Normalize sensor values to 0-1 range
        light = getattr(readings, "light_lux", None)
        if light is not None:
            sensor_values["light"] = min(1.0, light / 1000.0)  # 0-1000 lux range

        temp = getattr(readings, "ambient_temp_c", None) or getattr(readings, "cpu_temp_c", None)
        if temp is not None:
            sensor_values["temp"] = min(1.0, max(0.0, (temp - 15) / 25))  # 15-40°C range

        humidity = getattr(readings, "humidity_pct", None)
        if humidity is not None:
            sensor_values["humidity"] = humidity / 100.0  # Already 0-100

    sensor_labels = {
        "light": "Light",
        "temp": "Temp",
        "humidity": "Humidity",
    }

    for sensor_id, value in sensor_values.items():
        nodes.append(SchemaNode(
            node_id=f"sensor_{sensor_id}",
            node_type="sensor",
            label=sensor_labels[sensor_id],
            value=value,
            raw_value=value,
        ))

    # === PREFERENCE NODES (ring 3, optional) ===
    if include_preferences and preferences:
        try:
            pref_summary = preferences.get_preference_summary()
            for dim, pref_data in pref_summary.items():
                # Only include confident preferences (confidence > 0.2)
                if pref_data["confidence"] > 0.2 and dim in ["warmth", "clarity", "stability", "presence"]:
                    # Use valence as node value (how much Lumen values this dimension)
                    nodes.append(SchemaNode(
                        node_id=f"pref_{dim}",
                        node_type="preference",
                        label=f"P{dim[0].upper()}",  # PW, PC, PS, PP
                        value=max(0.0, min(1.0, (pref_data["valence"] + 1.0) / 2.0)),  # Normalize -1..1 to 0..1
                        raw_value={
                            "valence": pref_data["valence"],
                            "optimal_range": pref_data["optimal_range"],
                            "confidence": pref_data["confidence"],
                        },
                    ))
        except Exception:
            # Non-fatal - preferences are optional enhancement
            pass

    # === EDGES (sensor → anima influences) ===
    for (source_id, target_id), weight in SENSOR_ANIMA_WEIGHTS.items():
        # Only add edge if both nodes exist
        if any(n.node_id == source_id for n in nodes) and any(n.node_id == target_id for n in nodes):
            edges.append(SchemaEdge(
                source_id=source_id,
                target_id=target_id,
                weight=weight,
            ))

    # === EDGES (preference → anima satisfaction) ===
    if include_preferences and preferences and anima:
        try:
            pref_summary = preferences.get_preference_summary()
            for dim in ["warmth", "clarity", "stability", "presence"]:
                if dim in pref_summary:
                    pref_data = pref_summary[dim]
                    if pref_data["confidence"] > 0.2:
                        # Edge weight = satisfaction level (how well current anima satisfies preference)
                        anima_value = getattr(anima, dim, 0.5)
                        satisfaction = preferences._preferences[dim].current_satisfaction(anima_value)
                        # Sign: positive if preference valence > 0 (Lumen values this), negative if < 0
                        sign = 1.0 if pref_data["valence"] > 0 else -1.0
                        edges.append(SchemaEdge(
                            source_id=f"pref_{dim}",
                            target_id=f"anima_{dim}",
                            weight=satisfaction * sign,
                        ))
        except Exception:
            # Non-fatal - preference edges are optional
            pass

    return SelfSchema(
        timestamp=now,
        nodes=nodes,
        edges=edges,
    )


# === Caching ===
_cached_schema: Optional[SelfSchema] = None
_cache_time: Optional[datetime] = None
_CACHE_TTL_SECONDS = 60.0  # 1 minute cache for slow-clock pattern


def get_current_schema(
    identity=None,
    anima=None,
    readings=None,
    preferences=None,
    include_preferences: bool = True,
    force_refresh: bool = False,
) -> SelfSchema:
    """
    Get current G_t with caching.

    Args:
        identity: CreatureIdentity (optional, will try to get from store)
        anima: AnimaState (optional)
        readings: SensorReadings (optional)
        preferences: PreferenceSystem (optional, for preference nodes)
        include_preferences: Whether to include preference nodes (default: True)
        force_refresh: Bypass cache

    Returns:
        Cached or freshly extracted SelfSchema
    """
    global _cached_schema, _cache_time

    now = datetime.now()

    # Return cache if fresh and not forcing refresh
    # Note: Cache doesn't account for preferences flag, so we skip cache if preferences are requested
    if not force_refresh and _cached_schema and _cache_time and not include_preferences:
        age = (now - _cache_time).total_seconds()
        if age < _CACHE_TTL_SECONDS:
            return _cached_schema

    # Extract fresh schema
    schema = extract_self_schema(
        identity=identity,
        anima=anima,
        readings=readings,
        preferences=preferences,
        include_preferences=include_preferences,
    )

    # Update cache (only if not including preferences, to keep cache simple)
    if not include_preferences:
        _cached_schema = schema
        _cache_time = now

    return schema


def clear_cache():
    """Clear the schema cache."""
    global _cached_schema, _cache_time
    _cached_schema = None
    _cache_time = None
