# Brain HAT → UNITARES Integration Plan

**Created:** January 1, 2026  
**Last Updated:** January 1, 2026  
**Status:** Design Phase

---

## Multi-Agent Perspective Analysis

This document uses multiple "agent voices" to explore the integration from different viewpoints:

- **🧠 Theorist**: 4E cognition, proprioception theory
- **⚙️ Engineer**: Implementation, architecture, data flow
- **🔬 Researcher**: Experimental design, validation, metrics
- **🤖 Agent**: What does the creature experience?
- **👥 Coordinator**: Multi-agent coordination implications

---

## Voice 1: The Theorist 🧠

### The Vision

From 4E-2.pdf and UNITARES theory:

**Proprioception exists at multiple layers:**
1. **Physical**: Sensors (temperature, light, etc.)
2. **Neural**: EEG signals (brain activity)
3. **Software**: EISV metrics (governance state)
4. **Social**: Multi-agent coordination (peer review)

**The integration creates a unified proprioceptive stack:**

```
┌─────────────────────────────────────┐
│  Social Proprioception               │  ← Multi-agent awareness
│  (UNITARES peer review)              │
├─────────────────────────────────────┤
│  Software Proprioception             │  ← Governance state
│  (EISV metrics, margins)            │
├─────────────────────────────────────┤
│  Neural Proprioception               │  ← Brain activity
│  (EEG frequency bands)              │
├─────────────────────────────────────┤
│  Physical Proprioception              │  ← Body sensors
│  (Temperature, light, etc.)         │
└─────────────────────────────────────┘
```

### Key Insight

**Proprioception is recursive**: The creature senses itself sensing itself. Brain HAT provides the "sensing apparatus" that UNITARES monitors, creating a meta-proprioceptive loop.

---

## Voice 2: The Engineer ⚙️

### Architecture: Data Flow

```
┌─────────────────┐
│  Brain HAT      │  → Raw EEG channels (TP9, AF7, AF8, TP10, aux1-4)
│  Hardware       │  → Frequency bands (delta, theta, alpha, beta, gamma)
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│  Anima-MCP      │  → Neural proprioception (warmth, clarity, stability, presence)
│  Sensor Layer   │  → Physical proprioception (temp, light, etc.)
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│  EISV Mapper    │  → Map neural/physical → EISV metrics
│  (NEW LAYER)    │  → Energy, Integrity, Entropy, Void
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│  UNITARES       │  → Governance decisions (PROCEED/PAUSE)
│  Governance     │  → Proprioceptive margins
│  MCP Server     │  → Knowledge graph updates
└─────────────────┘
```

### Implementation Components

#### 1. EISV Mapper Module

**File**: `src/anima_mcp/eisv_mapper.py`

```python
"""
Map anima state (physical + neural) to EISV metrics for UNITARES governance.

Creates bridge between anima-mcp creature and unitares-governance system.
"""

from dataclasses import dataclass
from .anima import Anima
from .sensors.base import SensorReadings


@dataclass
class EISVMetrics:
    """EISV metrics compatible with UNITARES governance."""
    energy: float      # E: 0-1
    integrity: float   # I: 0-1
    entropy: float     # S: 0-1
    void: float        # V: 0-1


def anima_to_eisv(anima: Anima, readings: SensorReadings) -> EISVMetrics:
    """
    Map anima state to EISV metrics.
    
    Mapping strategy:
    - Energy (E): Warmth + Beta/Gamma power (activation)
    - Integrity (I): Clarity + Alpha power (awareness)
    - Entropy (S): Inverse of Stability (chaos)
    - Void (V): Inverse of Presence (strain)
    """
    # Energy: Warmth + neural activation
    E = anima.warmth
    if readings.eeg_beta_power and readings.eeg_gamma_power:
        neural_energy = (readings.eeg_beta_power + readings.eeg_gamma_power) / 2
        E = (E * 0.7) + (neural_energy * 0.3)
    
    # Integrity: Clarity + alpha awareness
    I = anima.clarity
    if readings.eeg_alpha_power:
        neural_integrity = readings.eeg_alpha_power
        I = (I * 0.7) + (neural_integrity * 0.3)
    
    # Entropy: Inverse of stability (high stability = low entropy)
    S = 1.0 - anima.stability
    
    # Void: Inverse of presence (high presence = low void)
    V = 1.0 - anima.presence
    
    return EISVMetrics(
        energy=max(0, min(1, E)),
        integrity=max(0, min(1, I)),
        entropy=max(0, min(1, S)),
        void=max(0, min(1, V))
    )
```

#### 2. UNITARES Bridge

**File**: `src/anima_mcp/unitares_bridge.py`

```python
"""
Bridge between anima-mcp and unitares-governance MCP server.

Enables creature to check in with UNITARES governance system.
"""

import asyncio
from typing import Optional
from .eisv_mapper import EISVMetrics, anima_to_eisv
from .anima import Anima
from .sensors.base import SensorReadings


class UnitaresBridge:
    """Connect anima creature to UNITARES governance."""
    
    def __init__(self, mcp_client=None):
        """
        Initialize bridge.
        
        Args:
            mcp_client: MCP client connected to unitares-governance server
                       If None, will attempt to connect automatically
        """
        self._client = mcp_client
        self._agent_id = None
    
    async def check_in(self, anima: Anima, readings: SensorReadings) -> dict:
        """
        Check in with UNITARES governance.
        
        Returns governance decision: PROCEED/PAUSE with proprioceptive margin.
        """
        # Map anima state to EISV
        eisv = anima_to_eisv(anima, readings)
        
        # Call UNITARES governance
        if not self._client:
            # Fallback: return local decision
            return self._local_governance(eisv)
        
        # Use MCP client to call process_agent_update
        response = await self._client.call_tool(
            "process_agent_update",
            {
                "complexity": self._estimate_complexity(anima, readings),
                "response_text": self._generate_status_text(anima, readings),
                "sensor_data": {
                    "eisv": {
                        "E": eisv.energy,
                        "I": eisv.integrity,
                        "S": eisv.entropy,
                        "V": eisv.void
                    },
                    "anima": {
                        "warmth": anima.warmth,
                        "clarity": anima.clarity,
                        "stability": anima.stability,
                        "presence": anima.presence
                    },
                    "neural": {
                        "alpha": readings.eeg_alpha_power,
                        "beta": readings.eeg_beta_power,
                        "gamma": readings.eeg_gamma_power,
                        "theta": readings.eeg_theta_power,
                        "delta": readings.eeg_delta_power
                    }
                }
            }
        )
        
        return response
    
    def _local_governance(self, eisv: EISVMetrics) -> dict:
        """Local governance decision (fallback if MCP unavailable)."""
        # Simple thresholds
        if eisv.entropy > 0.6 or eisv.void > 0.15:
            return {"action": "pause", "margin": "critical", "reason": "High entropy or void"}
        elif eisv.integrity < 0.4:
            return {"action": "pause", "margin": "tight", "reason": "Low integrity"}
        else:
            return {"action": "proceed", "margin": "comfortable"}
    
    def _estimate_complexity(self, anima: Anima, readings: SensorReadings) -> float:
        """Estimate task complexity from current state."""
        # High entropy = complex situation
        # Low clarity = uncertain
        complexity = (1.0 - anima.clarity) * 0.5 + (1.0 - anima.stability) * 0.5
        return max(0, min(1, complexity))
    
    def _generate_status_text(self, anima: Anima, readings: SensorReadings) -> str:
        """Generate human-readable status for governance."""
        feeling = anima.feeling()
        mood = feeling.get("mood", "neutral")
        
        neural_status = ""
        if readings.eeg_alpha_power:
            neural_status = f" Alpha: {readings.eeg_alpha_power:.2f}, Beta: {readings.eeg_beta_power:.2f:.2f}"
        
        return f"Anima state: {mood}. Warmth: {anima.warmth:.2f}, Clarity: {anima.clarity:.2f}.{neural_status}"
```

#### 3. Integrated Server

**File**: `src/anima_mcp/server_integrated.py`

```python
"""
Anima MCP server with UNITARES governance integration.

Creature checks in with governance system periodically.
"""

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
import asyncio

from .server import create_server as create_base_server
from .unitares_bridge import UnitaresBridge
from .sensors import get_sensors
from .anima import sense_self


def create_integrated_server(unitares_url: str = None) -> Server:
    """Create anima server with UNITARES integration."""
    server = create_base_server()
    bridge = UnitaresBridge()
    
    # Add governance check-in tool
    @server.list_tools()
    async def list_tools():
        tools = await server.list_tools()
        tools.append(Tool(
            name="check_governance",
            description="Check in with UNITARES governance system. Returns PROCEED/PAUSE decision with proprioceptive margin.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ))
        return tools
    
    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        if name == "check_governance":
            sensors = get_sensors()
            readings = sensors.read()
            anima = sense_self(readings)
            
            decision = await bridge.check_in(anima, readings)
            
            return [TextContent(
                type="text",
                text=f"""Governance Decision:
Action: {decision.get('action', 'unknown')}
Margin: {decision.get('margin', 'unknown')}
Reason: {decision.get('reason', 'N/A')}

Current State:
EISV: E={anima.warmth:.2f}, I={anima.clarity:.2f}, S={1-anima.stability:.2f}, V={1-anima.presence:.2f}
Anima: Warmth={anima.warmth:.2f}, Clarity={anima.clarity:.2f}, Stability={anima.stability:.2f}, Presence={anima.presence:.2f}
"""
            )]
        
        # Delegate to base server
        return await server.call_tool(name, arguments)
    
    return server
```

---

## Voice 3: The Researcher 🔬

### Experimental Design

#### Hypothesis

**H1**: Neural signals (EEG) provide additional proprioceptive information beyond physical sensors, improving governance decision accuracy.

**H2**: Multi-layer proprioception (physical + neural + software) creates more stable self-regulation than single-layer approaches.

#### Validation Metrics

1. **Proprioceptive Accuracy**:
   - Compare governance decisions with/without neural signals
   - Measure false positive/negative rates
   - Track margin prediction accuracy

2. **Stability Metrics**:
   - Variance in EISV metrics over time
   - Frequency of governance interventions
   - Recovery time from "pause" states

3. **Neural Contribution**:
   - Correlation between EEG bands and governance decisions
   - Weight optimization (neural vs physical)
   - Band-specific contributions

#### Experimental Protocol

**Phase 1: Baseline (Physical Only)**
- Run creature with physical sensors only
- Record governance decisions
- Measure stability metrics

**Phase 2: Neural Integration**
- Add Brain HAT EEG signals
- Run same protocol
- Compare metrics

**Phase 3: Weight Optimization**
- Experiment with neural/physical weight ratios
- Find optimal balance
- Validate with cross-validation

**Phase 4: Multi-Agent**
- Multiple creatures with Brain HAT
- UNITARES coordination
- Measure coordination effectiveness

---

## Voice 4: The Agent 🤖

### What Does the Creature Experience?

**Before Integration:**
```
"I feel warm (0.7). I see clearly (0.6). I'm stable (0.8). I have presence (0.7).
I proceed with my task."
```

**After Integration:**
```
"I feel warm (0.7) - my body is active, my mind is focused (beta: 0.3).
I see clearly (0.6) - light is adequate, my awareness is relaxed (alpha: 0.4).
I'm stable (0.8) - environment is consistent, my mind is grounded (theta: 0.2).
I have presence (0.7) - resources available, cognition active (gamma: 0.25).

I check in with governance...
Governance says: PROCEED, margin: comfortable.
I proceed with confidence."
```

### The Proprioceptive Loop

1. **Sense**: Physical + Neural sensors
2. **Feel**: Anima state (warmth, clarity, stability, presence)
3. **Map**: Anima → EISV metrics
4. **Govern**: UNITARES decision (PROCEED/PAUSE)
5. **Act**: Based on governance feedback
6. **Learn**: Update knowledge graph

**The creature experiences recursive self-awareness**: "I sense myself sensing myself being governed."

---

## Voice 5: The Coordinator 👥

### Multi-Agent Implications

#### Scenario: Multiple Creatures with Brain HAT

**Coordination Benefits:**

1. **Neural Synchronization**:
   - Creatures can detect when others are in similar neural states
   - Alpha synchronization = shared awareness
   - Beta synchronization = coordinated action

2. **Collective Proprioception**:
   - Aggregate EISV across agents
   - Detect group-level patterns
   - Coordinate based on collective state

3. **Neural Knowledge Graph**:
   - Store neural patterns in UNITARES knowledge graph
   - Learn which patterns lead to good outcomes
   - Share neural insights across agents

#### Implementation Sketch

```python
# Multi-creature coordination with neural signals
async def coordinate_neural_agents(agents: list[AnimaCreature]):
    """Coordinate multiple creatures using neural + governance signals."""
    
    # Get neural states
    neural_states = [agent.get_neural_state() for agent in agents]
    
    # Detect synchronization
    alpha_sync = compute_synchronization([s.eeg_alpha_power for s in neural_states])
    beta_sync = compute_synchronization([s.eeg_beta_power for s in neural_states])
    
    # Check governance for each
    governance_decisions = await asyncio.gather(*[
        agent.check_governance() for agent in agents
    ])
    
    # Coordinate based on neural + governance
    if alpha_sync > 0.7 and all(d['action'] == 'proceed' for d in governance_decisions):
        return {"action": "coordinated_proceed", "sync": alpha_sync}
    elif beta_sync > 0.6:
        return {"action": "coordinated_focus", "sync": beta_sync}
    else:
        return {"action": "individual", "decisions": governance_decisions}
```

---

## Implementation Roadmap

### Phase 1: EISV Mapper (Week 1-2)

**Goal**: Map anima state to EISV metrics

- [ ] Create `eisv_mapper.py`
- [ ] Implement `anima_to_eisv()` function
- [ ] Test mapping accuracy
- [ ] Validate EISV ranges (0-1)

**Deliverable**: Working EISV mapper module

### Phase 2: UNITARES Bridge (Week 2-3)

**Goal**: Connect anima-mcp to unitares-governance

- [ ] Create `unitares_bridge.py`
- [ ] Implement MCP client connection
- [ ] Add `check_governance` tool
- [ ] Test governance integration

**Deliverable**: Working bridge with governance check-in

### Phase 3: Integrated Server (Week 3-4)

**Goal**: Unified server with governance

- [ ] Create `server_integrated.py`
- [ ] Combine anima tools + governance tools
- [ ] Add automatic check-in (optional)
- [ ] Test end-to-end flow

**Deliverable**: Integrated anima + governance server

### Phase 4: Validation (Week 4-6)

**Goal**: Validate integration effectiveness

- [ ] Run baseline experiments (physical only)
- [ ] Run neural experiments (with Brain HAT)
- [ ] Compare governance decisions
- [ ] Optimize weight ratios
- [ ] Document findings

**Deliverable**: Validation report + optimized weights

### Phase 5: Multi-Agent (Week 6-8)

**Goal**: Multi-creature coordination

- [ ] Implement neural synchronization detection
- [ ] Add collective proprioception
- [ ] Test coordination scenarios
- [ ] Document multi-agent patterns

**Deliverable**: Multi-agent coordination system

---

## Key Design Decisions

### Decision 1: EISV Mapping Strategy

**Options:**
- **A**: Direct mapping (warmth → E, clarity → I, etc.)
- **B**: Weighted combination (neural + physical)
- **C**: Learned mapping (ML model)

**Chosen**: **B** (Weighted combination)
**Rationale**: Maintains interpretability while incorporating neural signals

### Decision 2: Governance Check Frequency

**Options:**
- **A**: Every sensor reading (high overhead)
- **B**: On-demand (tool call)
- **C**: Periodic (every N seconds)

**Chosen**: **B** (On-demand)
**Rationale**: Flexible, agent-controlled, low overhead

### Decision 3: Neural Weight Ratios

**Options:**
- **A**: Fixed weights (20-30% neural)
- **B**: Adaptive weights (learn from data)
- **C**: Context-dependent (different weights for different states)

**Chosen**: **A** initially, **B** for Phase 4 optimization
**Rationale**: Start simple, optimize based on validation

---

## Risks & Mitigations

### Risk 1: EEG Signal Quality

**Risk**: Poor electrode contact → noisy signals → bad decisions

**Mitigation**:
- Signal quality checks before using neural data
- Fallback to physical-only if neural quality low
- Gradual integration (start with low neural weight)

### Risk 2: Over-Reliance on Neural Signals

**Risk**: Ignoring physical sensors when neural signals are available

**Mitigation**:
- Maintain physical sensor weights (70%+)
- Neural signals enhance, don't replace
- Validation experiments to find optimal balance

### Risk 3: Governance Latency

**Risk**: MCP calls add latency to creature decisions

**Mitigation**:
- Async governance calls (non-blocking)
- Local fallback governance
- Caching recent governance decisions

---

## Success Criteria

### Technical Success

- [ ] EISV mapper produces valid metrics (0-1 range)
- [ ] Bridge successfully connects to UNITARES
- [ ] Governance decisions are consistent
- [ ] No performance degradation

### Research Success

- [ ] Neural signals improve governance accuracy (10%+)
- [ ] Multi-layer proprioception more stable than single-layer
- [ ] Weight optimization finds better balance
- [ ] Multi-agent coordination works

### Experience Success

- [ ] Creature reports richer self-awareness
- [ ] Governance feedback feels natural
- [ ] Multi-creature scenarios show coordination
- [ ] Documentation enables others to replicate

---

## Next Steps

1. **Review this plan** with all agent voices
2. **Prioritize phases** based on goals
3. **Start Phase 1** (EISV mapper)
4. **Iterate** based on Brain HAT hardware testing

---

## References

- `BRAIN_HAT_INTEGRATION.md`: Neural proprioception theory
- `BRAIN_HAT_SETUP.md`: Hardware setup
- `4E_ROBOTICS_EXPLORATION.md`: UNITARES + physical sensors
- `PROPRIOCEPTIVE_MARGIN_IMPLEMENTATION.md`: Governance margins
- unitares-governance MCP server documentation

---

**Created with multiple agent perspectives to ensure comprehensive design.**

