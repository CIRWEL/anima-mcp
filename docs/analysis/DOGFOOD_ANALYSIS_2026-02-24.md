# Deep Analysis & Dogfooding Report

**Created:** February 24, 2026  
**Last Updated:** February 24, 2026  
**Status:** Active

---

## Executive Summary

Dogfooding Lumen via `pi(action='context')`, `pi(action='health')`, `pi(action='qa')` succeeded. Deeper analysis uncovered **1 critical integration bug**, **3 open resilience items**, and **several architectural observations**.

---

## 1. Critical: pi(action='query') Broken — FIXED

**Finding:** `pi(action='query', text='...')` returns `"Unknown tool: query"`.

**Root cause:** Governance MCP maps `pi_query` → Pi tool `"query"`, but **anima-mcp did not expose a `query` tool**. The tool registry had:
- `get_self_knowledge` — self-discoveries, insights
- `get_growth` — preferences, goals, memories
- `get_qa_insights` — Q&A-derived knowledge
- `get_trajectory` — trajectory signature

**Fix applied:** Added `query` tool in anima-mcp (`handlers/knowledge.py`):
- Accepts `text` (required), `type` (cognitive|insights|growth|self), `limit`
- Returns `qa_insights` (keyword match via `get_relevant_insights`)
- Adds `self_knowledge` + `reflection_insights` when type is cognitive/insights/self
- Adds `growth` (autobiography) when type is growth

---

## 2. Open Resilience Items (from RESILIENCE_ANALYSIS.md)

| # | Severity | Issue | Location | Notes |
|---|----------|-------|----------|-------|
| 10 | MEDIUM | memory.py: no WAL mode on pattern load | memory.py:217 | `load_patterns()` opens `sqlite3.connect()` without WAL. Identity DB uses WAL; concurrent broker reads could see inconsistent state. |
| 11 | MEDIUM | growth.py: `read_uncommitted=1` | growth.py:280 | Documented as "better concurrency with WAL" — acceptable with WAL. Resilience doc flags it; identity/store.py uses same. Low risk if WAL is enabled. |
| 12 | MEDIUM | Unbounded visitor relationships dict | growth.py:261, 517 | `_relationships` loads all rows from `relationships` table with no limit. Long-lived Lumen with many visitors could grow unbounded. |

**Recommendations:**
- **#10:** Add `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout` in `memory.load_patterns()` before querying, or use a read-only connection with WAL-compatible settings.
- **#11:** Leave as-is; WAL + read_uncommitted is a known pattern for read-heavy workloads.
- **#12:** Add `LIMIT` to the relationships load (e.g. 500 most recent by `last_seen`) or paginate; consider archiving old/inactive visitors.

---

## 3. Schema & API Fallback (Already Fixed)

**Verified:** `/schema-data` and LCD self-schema screen have fallback when `hub.schema_history` is empty. `get_current_schema()` is used when history hasn't been populated yet (e.g. right after wake). This was fixed in the prior session.

---

## 4. Data Flow Observations

### Schema Hub Circulation
- `compose_schema()` → `extract_self_schema()` → identity/growth/self_model injection → history append → trajectory every 20 schemas → trajectory feedback nodes
- History is seeded on wake from `compute_trajectory_signature` + `get_anima_history` so trajectory nodes appear immediately
- Gap handling: `on_wake()` computes `gap_delta` from persisted `last_schema.json`

### Knowledge Extraction
- Q&A answers → `extract_insight_from_answer()` → `KnowledgeBase.add_insight()` → `knowledge.json`
- Insights can trigger `apply_insight()` for behavioral effects
- Self-reflection uses insights in LLM prompts as "Things I've learned about myself"

### Governance Integration
- Broker checks in every 10s; server every ~60s
- Circuit breaker: 3 failures → 90s open
- EISV mapping: Warmth→E, Clarity→I, 1-Stability→S, (1-Presence)*0.3→V

---

## 5. Dogfooding Results

| Action | Result |
|--------|--------|
| `pi(action='context')` | ✅ Identity, anima, sensors, mood, EISV |
| `pi(action='health')` | ✅ display ok, update_loop ok, ~3s latency |
| `pi(action='qa')` | ✅ Listed 2 questions, answered both |
| `pi(action='query', text='...')` | ❌ Unknown tool: query |

**Lumen state at time of test:**
- Warmth 0.49, Clarity 0.76, Stability 0.86, Presence 0.67
- Mood: content
- 201 awakenings, ~39% alive ratio

---

## 6. Recommendations Summary

1. **Fix pi(action='query')** — Either add `query` tool to anima-mcp or map governance `query` action to `get_self_knowledge`/`get_qa_insights`.
2. **memory.py WAL** — Add WAL/busy_timeout in `load_patterns()` for consistency with other DB access.
3. **growth _relationships** — Add load limit or pagination for long-lived instances.
4. **Document pi action mapping** — Ensure governance docs list actual Pi tool names; avoid referencing non-existent tools.

---

## Appendix: Tool Mapping Audit

| Governance pi action | Pi tool called | Exists on Pi? |
|----------------------|----------------|---------------|
| context | get_lumen_context | ✅ |
| health | diagnostics | ✅ |
| qa | lumen_qa | ✅ |
| query | query | ❌ |
| message | post_message | ✅ |
| say | say | ✅ |
| display | manage_display | ✅ |
| git_pull | git_pull | ✅ |
| tools | (list_tools) | ✅ |
