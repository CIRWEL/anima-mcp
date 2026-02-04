# Anima-MCP Tool Consolidation Design

## Overview
Reducing 27 tools → 18 tools (33% reduction) to improve cognitive load for LLM agents.

## High Priority Consolidations

### 1. `get_lumen_context` (NEW)
**Replaces:** `get_state`, `get_identity`, `read_sensors`

```json
{
  "name": "get_lumen_context",
  "description": "Get Lumen's complete current context: identity, anima state, and sensor readings in one call",
  "inputSchema": {
    "type": "object",
    "properties": {
      "include": {
        "type": "array",
        "items": {"enum": ["identity", "anima", "sensors", "mood"]},
        "description": "What to include. Default: all",
        "default": ["identity", "anima", "sensors", "mood"]
      }
    }
  }
}
```

**Response Structure:**
```json
{
  "identity": {"name": "Lumen", "birth": "...", "awakenings": 42},
  "anima": {"warmth": 0.7, "clarity": 0.8, "stability": 0.9, "presence": 0.85},
  "sensors": {"temperature": 22.5, "humidity": 45, "light": 800},
  "mood": {"current": "curious", "valence": 0.6}
}
```

---

### 2. `post_message` (NEW)
**Replaces:** `leave_message`, `leave_agent_note`

```json
{
  "name": "post_message",
  "description": "Post a message to Lumen's message board (from human or AI agent)",
  "inputSchema": {
    "type": "object",
    "properties": {
      "message": {"type": "string", "description": "The message content"},
      "source": {
        "enum": ["human", "agent"],
        "description": "Who is posting. Default: agent",
        "default": "agent"
      },
      "agent_name": {"type": "string", "description": "Name of AI agent (if source=agent)"},
      "responds_to": {"type": "string", "description": "Question ID this answers (for Q&A)"}
    },
    "required": ["message"]
  }
}
```

---

### 3. `query` (NEW)
**Replaces:** `query_knowledge`, `query_memory`, `search_knowledge_graph`, `cognitive_query`

```json
{
  "name": "query",
  "description": "Query Lumen's knowledge systems - learned facts, associative memory, or knowledge graph",
  "inputSchema": {
    "type": "object",
    "properties": {
      "text": {"type": "string", "description": "Search query or question"},
      "type": {
        "enum": ["learned", "memory", "graph", "cognitive"],
        "description": "Query type: learned (Q&A facts), memory (associative conditions), graph (semantic search), cognitive (RAG answer)",
        "default": "cognitive"
      },
      "category": {"type": "string", "description": "Filter by category (for type=learned)"},
      "conditions": {
        "type": "object",
        "properties": {
          "temperature": {"type": "number"},
          "light": {"type": "number"},
          "humidity": {"type": "number"}
        },
        "description": "Sensor conditions to query (for type=memory)"
      },
      "limit": {"type": "integer", "default": 10}
    },
    "required": ["text"]
  }
}
```

---

### 4. `cognitive_process` (NEW)
**Replaces:** `dialectic_synthesis`, `extract_knowledge`, `merge_insights`

```json
{
  "name": "cognitive_process",
  "description": "Perform cognitive operations: dialectic synthesis, knowledge extraction, or insight merging",
  "inputSchema": {
    "type": "object",
    "properties": {
      "operation": {
        "enum": ["synthesize", "extract", "merge"],
        "description": "Operation type"
      },
      "thesis": {"type": "string", "description": "Main proposition (for synthesize)"},
      "antithesis": {"type": "string", "description": "Counter-proposition (for synthesize)"},
      "text": {"type": "string", "description": "Text to extract from (for extract)"},
      "domain": {"type": "string", "description": "Knowledge domain (for extract)"},
      "insights": {"type": "array", "items": {"type": "string"}, "description": "Insights to merge (for merge)"},
      "context": {"type": "string", "description": "Additional context"}
    },
    "required": ["operation"]
  }
}
```

---

### 5. `configure_voice` (NEW)
**Replaces:** `voice_status`, `set_voice_mode`

```json
{
  "name": "configure_voice",
  "description": "Get or configure Lumen's voice system",
  "inputSchema": {
    "type": "object",
    "properties": {
      "action": {
        "enum": ["status", "configure"],
        "description": "Action: status (read-only) or configure (update settings)",
        "default": "status"
      },
      "always_listening": {"type": "boolean", "description": "Enable always-listening mode"},
      "chattiness": {"type": "number", "minimum": 0, "maximum": 1, "description": "How chatty (0-1)"},
      "wake_word": {"type": "string", "description": "Wake word to use"}
    }
  }
}
```

---

## Medium Priority Consolidations

### 6. `manage_display` (NEW)
**Replaces:** `switch_screen`, `show_face`

```json
{
  "name": "manage_display",
  "description": "Control Lumen's display: switch screens or show face",
  "inputSchema": {
    "type": "object",
    "properties": {
      "action": {
        "enum": ["switch", "face", "next", "previous"],
        "description": "Action to perform"
      },
      "screen": {
        "enum": ["face", "sensors", "identity", "diagnostics", "notepad", "learning", "messages", "qa", "self_graph"],
        "description": "Screen to switch to (for action=switch)"
      }
    },
    "required": ["action"]
  }
}
```

---

### 7. `manage_calibration` (NEW)
**Replaces:** `get_calibration`, `set_calibration`

```json
{
  "name": "manage_calibration",
  "description": "Get or update Lumen's nervous system calibration",
  "inputSchema": {
    "type": "object",
    "properties": {
      "action": {
        "enum": ["get", "set"],
        "description": "Action: get (read) or set (update)",
        "default": "get"
      },
      "updates": {
        "type": "object",
        "description": "Calibration values to update (for action=set)"
      },
      "source": {
        "enum": ["manual", "learning", "sensor_feedback"],
        "description": "Source of calibration update"
      }
    }
  }
}
```

---

## Tool Migration Matrix

| Old Tool | New Tool | Notes |
|----------|----------|-------|
| `get_state` | `get_lumen_context` | include=["anima", "mood"] |
| `get_identity` | `get_lumen_context` | include=["identity"] |
| `read_sensors` | `get_lumen_context` | include=["sensors"] |
| `leave_message` | `post_message` | source="human" |
| `leave_agent_note` | `post_message` | source="agent" |
| `query_knowledge` | `query` | type="learned" |
| `query_memory` | `query` | type="memory" |
| `search_knowledge_graph` | `query` | type="graph" |
| `cognitive_query` | `query` | type="cognitive" |
| `dialectic_synthesis` | `cognitive_process` | operation="synthesize" |
| `extract_knowledge` | `cognitive_process` | operation="extract" |
| `merge_insights` | `cognitive_process` | operation="merge" |
| `voice_status` | `configure_voice` | action="status" |
| `set_voice_mode` | `configure_voice` | action="configure" |
| `switch_screen` | `manage_display` | action="switch" |
| `show_face` | `manage_display` | action="face" |
| `get_calibration` | `manage_calibration` | action="get" |
| `set_calibration` | `manage_calibration` | action="set" |

## Kept As-Is (11 tools)
- `set_name` - Simple, focused
- `get_questions` - Specific query
- `test_leds` - Hardware test
- `learning_visualization` - Unique display
- `get_expression_mood` - Specific state
- `say` - Unique audio action
- `diagnostics` - System-wide status
- `next_steps` - Planning tool
- `unified_workflow` - Orchestration
- `show_face` - Could keep if display consolidation too complex

## Result
- **Before:** 27 tools
- **After:** 18 tools (7 new consolidated + 11 kept)
- **Reduction:** 33%
