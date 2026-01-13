# Unified Workflow Orchestrator

**Created:** January 11, 2026  
**Last Updated:** January 11, 2026  
**Status:** Active

---

## Overview

The Unified Workflow Orchestrator coordinates both MCP servers:
- **anima-mcp** (Lumen's proprioceptive state)
- **unitares-governance** (Governance decisions)

Provides a single interface for agents to interact with both systems seamlessly.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│         Unified Workflow Orchestrator                    │
│  (Single interface for both MCP servers)                │
└──────────────┬──────────────────────────┬────────────────┘
               │                          │
               ▼                          ▼
    ┌──────────────────┐        ┌──────────────────┐
    │   anima-mcp      │        │ unitares-        │
    │   (Lumen)       │        │ governance       │
    │                  │        │                  │
    │ - get_state      │        │ - check_         │
    │ - read_sensors   │        │   governance     │
    │ - get_identity   │        │ - process_      │
    │                  │        │   agent_update   │
    └──────────────────┘        └──────────────────┘
```

---

## Features

### 1. Unified Interface

Single API to access both servers:

```python
from anima_mcp.workflow_orchestrator import get_orchestrator

orchestrator = get_orchestrator(
    unitares_url="http://192.168.1.164:8765/sse",
    anima_store=store,
    anima_sensors=sensors
)

# Get Lumen's state
state = await orchestrator.get_lumen_state()

# Check governance
governance = await orchestrator.check_governance()
```

### 2. Pre-built Workflows

Common workflows ready to use:

#### `check_state_and_governance`

Checks Lumen's state, then checks governance:

```python
result = await orchestrator.workflow_check_state_and_governance()

# Returns:
{
    "state": {
        "anima": {...},
        "eisv": {...},
        "sensors": {...},
        "identity": {...}
    },
    "governance": {
        "action": "proceed",
        "margin": "comfortable",
        "reason": "...",
        "source": "unitares"
    }
}
```

#### `monitor_and_govern`

Continuous monitoring with periodic governance checks:

```python
result = await orchestrator.workflow_monitor_and_govern(interval=60.0)
```

### 3. Custom Workflows

Build multi-step workflows:

```python
from anima_mcp.workflow_orchestrator import WorkflowStep, WorkflowStatus

steps = [
    WorkflowStep(
        name="get_state",
        server="anima",
        tool="get_state",
        arguments={}
    ),
    WorkflowStep(
        name="check_governance",
        server="unitares",
        tool="check_governance",
        arguments={},
        depends_on=["get_state"]  # Wait for state first
    )
]

result = await orchestrator.execute_workflow(steps)
```

---

## MCP Tool: `unified_workflow`

Access workflows via MCP:

```json
{
  "method": "tools/call",
  "params": {
    "name": "unified_workflow",
    "arguments": {
      "workflow": "check_state_and_governance"
    }
  }
}
```

### Available Workflows

1. **`check_state_and_governance`**
   - Gets Lumen's current state
   - Checks governance decision
   - Returns combined result

2. **`monitor_and_govern`**
   - Continuous monitoring
   - Periodic governance checks
   - Returns latest result

---

## Usage Examples

### Example 1: Check State and Governance

```python
# Via MCP tool
{
  "workflow": "check_state_and_governance"
}

# Via Python
orchestrator = get_orchestrator(...)
result = await orchestrator.workflow_check_state_and_governance()

if result["governance"]["action"] == "proceed":
    print("✅ Governance approved")
else:
    print(f"⚠️ Governance: {result['governance']['reason']}")
```

### Example 2: Custom Multi-Step Workflow

```python
steps = [
    WorkflowStep("read_sensors", "anima", "read_sensors", {}),
    WorkflowStep("get_identity", "anima", "get_identity", {}),
    WorkflowStep(
        "governance",
        "unitares",
        "check_governance",
        {},
        depends_on=["read_sensors"]
    )
]

result = await orchestrator.execute_workflow(steps, parallel=False)

if result.status == WorkflowStatus.SUCCESS:
    print("✅ All steps completed")
    print(f"Sensors: {result.steps['read_sensors']}")
    print(f"Governance: {result.steps['governance']}")
```

### Example 3: Parallel Execution

```python
# Independent steps can run in parallel
steps = [
    WorkflowStep("sensors", "anima", "read_sensors", {}),
    WorkflowStep("identity", "anima", "get_identity", {}),
    # No dependencies = can run in parallel
]

result = await orchestrator.execute_workflow(steps, parallel=True)
```

---

## Workflow Steps

### Anima-MCP Steps

- **`get_state`** - Get Lumen's full state (anima, sensors, identity)
- **`read_sensors`** - Read raw sensor values
- **`get_identity`** - Get identity information

### UNITARES Steps

- **`check_governance`** - Get governance decision
- **`process_agent_update`** - Send agent update to UNITARES

---

## Error Handling

Workflows handle errors gracefully:

```python
result = await orchestrator.execute_workflow(steps)

if result.status == WorkflowStatus.PARTIAL:
    print(f"⚠️ Some steps failed: {result.errors}")
elif result.status == WorkflowStatus.FAILED:
    print(f"❌ All steps failed: {result.errors}")
else:
    print("✅ All steps succeeded")
```

---

## Integration with Server

The orchestrator is initialized automatically in the server:

```python
# In server.py
orchestrator = get_orchestrator(
    unitares_url=os.environ.get("UNITARES_URL"),
    anima_store=_store,
    anima_sensors=_sensors
)
```

Access via MCP tool `unified_workflow`.

---

## Benefits

### 1. Unified Interface

- Single API for both servers
- No need to manage two separate connections
- Consistent error handling

### 2. Workflow Patterns

- Pre-built common workflows
- Custom multi-step workflows
- Dependency management

### 3. Agent-Friendly

- Simple MCP tool interface
- Clear workflow results
- Error handling built-in

---

## Future Enhancements

1. **More Workflows**
   - `analyze_trends` - Historical analysis
   - `adaptive_governance` - Dynamic threshold adjustment
   - `multi_agent_coordination` - Coordinate multiple Lumen instances

2. **Workflow Templates**
   - Save and reuse workflow patterns
   - Workflow library

3. **Workflow Scheduling**
   - Scheduled workflows
   - Event-triggered workflows

---

## Related

- **`workflow_orchestrator.py`** - Implementation
- **`unitares_bridge.py`** - UNITARES connection
- **`server.py`** - MCP server integration

---

**Unified workflows enable seamless coordination between Lumen and UNITARES governance.**
