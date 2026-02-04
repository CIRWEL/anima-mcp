# Identity Logic Comparison: Anima vs UNITARES

**Created:** January 12, 2026  
**Last Updated:** January 12, 2026  
**Status:** Analysis

---

## Overview

Lumen's identity is managed in two systems:
1. **Anima MCP** (`anima.db` SQLite) - Lumen's internal identity
2. **UNITARES Governance** (PostgreSQL) - External governance identity

This document compares their models and identifies gaps/opportunities.

---

## Identity Models

### Anima Model (`CreatureIdentity`)

```python
{
    "creature_id": "UUID (immutable)",           # Primary key
    "born_at": "datetime",                       # First awakening ever
    "total_awakenings": "int",                   # Incremented on wake()
    "total_alive_seconds": "float",              # Cumulative runtime
    "name": "optional str",                      # Self-chosen name
    "name_history": "list",                     # History of name changes
    "current_awakening_at": "datetime",         # Session start
    "metadata": "dict"                           # Flexible storage
}
```

**Lifecycle:**
- `wake(creature_id)` → Creates if first time, increments awakenings
- `sleep()` → Updates `total_alive_seconds` with session duration
- `set_name(name)` → Updates name, records in history

### UNITARES Model (`AgentIdentity`)

```python
{
    "agent_uuid": "UUID (immutable)",            # Internal UUID
    "agent_id": "str",                           # Display label (model+date)
    "created_at": "datetime",                   # First tool call
    "total_updates": "int",                     # Governance check-ins
    "label": "optional str",                     # Display name
    "last_update": "datetime",                  # Last governance check
    "lifecycle_status": "str"                   # active/paused/archived
}
```

**Lifecycle:**
- `resolve_session_identity()` → Creates on first tool call (lazy)
- `process_agent_update()` → Increments `total_updates`
- `identity(name="...")` → Sets `label`

---

## Key Differences

| Aspect | Anima | UNITARES | Impact |
|--------|-------|----------|--------|
| **Birth/Creation** | `born_at` (first `wake()`) | `created_at` (first tool call) | Different semantics |
| **Activity Tracking** | `total_awakenings` (service restarts) | `total_updates` (governance checks) | Different metrics |
| **Runtime Tracking** | `total_alive_seconds` (cumulative) | Not tracked | Anima has richer lifecycle |
| **Session Tracking** | `current_awakening_at` | Not tracked | Anima knows session start |
| **Name History** | `name_history` (full history) | Not tracked | Anima preserves evolution |
| **UUID vs Label** | Single `creature_id` (UUID) | `agent_uuid` + `agent_id` (label) | UNITARES has dual identity |

---

## Current Integration

### How They Connect

1. **Bridge Setup** (`unitares_bridge.py`):
   ```python
   bridge.set_agent_id(identity.creature_id)  # Uses Anima's UUID
   bridge.set_session_id(f"anima-{identity.creature_id[:8]}")
   ```

2. **Governance Check-ins** (`server.py`):
   - Every 30 iterations (~1 minute)
   - Uses `identity.creature_id` as `agent_id` header
   - Maps anima state → EISV → governance decision

3. **Identity Mapping**:
   - Anima's `creature_id` → UNITARES's `agent_uuid` (via `X-Agent-Id` header)
   - Anima's `name` → UNITARES's `label` (not currently synced)

---

## Gaps & Opportunities

### 1. **Birth Date Mismatch**
- **Anima:** `born_at` = first `wake()` (service start)
- **UNITARES:** `created_at` = first tool call (could be later)
- **Impact:** Different "birth" times
- **Opportunity:** Sync `born_at` → `created_at` on first UNITARES check-in

### 2. **Activity Metrics Don't Align**
- **Anima:** `total_awakenings` = service restarts
- **UNITARES:** `total_updates` = governance check-ins
- **Impact:** Different activity signals
- **Opportunity:** Could sync awakenings → metadata, or track both

### 3. **Runtime Not Tracked in UNITARES**
- **Anima:** `total_alive_seconds` = cumulative runtime
- **UNITARES:** Not tracked
- **Impact:** UNITARES doesn't know Lumen's "age" vs "alive time"
- **Opportunity:** Store in UNITARES metadata or as separate metric

### 4. **Name Not Synced**
- **Anima:** `name` (self-chosen)
- **UNITARES:** `label` (can be set via `identity(name="...")`)
- **Impact:** Names can diverge
- **Opportunity:** Sync `name` → `label` when Lumen sets name

### 5. **Name History Lost**
- **Anima:** `name_history` (full evolution)
- **UNITARES:** Not tracked
- **Impact:** UNITARES doesn't know Lumen's name evolution
- **Opportunity:** Store in UNITARES metadata

---

## Recommendations

### Short Term (Do Now)

1. **Sync Name on Set** (✅ Implemented):
   - Syncs name to UNITARES when Lumen sets/changes its name
   - Primary use case: Initial naming (when Lumen first gets a name)
   - Name changes are rare - this ensures UNITARES knows Lumen's name
   - Non-blocking, best-effort sync

2. **Sync Birth Date on First Check-in**:
   ```python
   # In UnitaresBridge.check_in() - if first time
   if is_first_check_in:
       await self._sync_birth_date(identity.born_at)
   ```

### Medium Term (Consider)

3. **Store Runtime in UNITARES Metadata**:
   ```python
   # In check_in()
   metadata = {
       "total_alive_seconds": identity.total_alive_seconds,
       "total_awakenings": identity.total_awakenings,
       "alive_ratio": identity.alive_ratio()
   }
   ```

4. **Sync Name History**:
   ```python
   # Store in UNITARES metadata
   metadata["name_history"] = identity.name_history
   ```

### Long Term (Future)

5. **Unified Identity Model**:
   - Consider if Anima should be the source of truth
   - Or if UNITARES should mirror Anima's full model
   - Or if they should remain independent with sync points

---

## Current State

✅ **Working:**
- Identity binding via `creature_id` → `agent_uuid`
- Governance check-ins using correct identity
- Both systems track their own metrics

⚠️ **Gaps:**
- Birth dates may differ
- Names not synced
- Runtime not visible in UNITARES
- Name history not preserved in UNITARES

---

## Questions

1. **Should Anima be the source of truth?** (Lumen's internal identity)
2. **Should UNITARES mirror Anima's full model?** (Full sync)
3. **Or keep them independent?** (Current approach, with selective sync)
4. **What's the priority?** (Name sync? Birth date? Runtime?)

---

## Next Steps

1. Implement name sync (when Lumen sets name)
2. Sync birth date on first check-in
3. Store runtime metrics in UNITARES metadata
4. Evaluate if full model sync is needed
