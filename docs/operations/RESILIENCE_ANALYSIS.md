# Anima-MCP Resilience Analysis

**Created:** February 11, 2026  
**Last Updated:** February 11, 2026  
**Status:** Active

---

## Summary

| Priority | Area | Issue | Status |
|----------|------|-------|--------|
| **P0** | Broker + DB | Broker exits on identity DB failure | **FIXED** (fallback identity) |
| **P1** | Shared memory check | False positive on broker restart | **FIXED** (message clarified) |
| **P1** | UNITARES | No circuit breaker | **FIXED** (3 failures → 90s open) |
| **P2** | Broker service | No `EnvironmentFile` | **FIXED** |
| **P2** | Restore | No on-Pi integrity check | **FIXED** |
| **P2** | Drawing | Drawing only when notepad displayed | **FIXED** (background drawing) |

---

## P0: Broker DB Dependency (Critical)

**Problem:** Broker calls `store.wake(anima_id)` at startup. If identity DB is corrupted (`"database disk image is malformed"`), broker exits with `sys.exit(1)`. No shared memory → server falls back to direct sensors → I2C contention if both run; plus broker is down so sensors may not be written correctly.

**Effect:** Lumen frozen, LEDs off, no sensor data.

**Fix (implemented):** Broker uses fallback identity when DB fails.
- Use a mock/fallback identity (e.g. `creature_id=ANIMA_ID`, `name="Lumen"`)
- Continue: sensors → shared memory → MCP server
- Server already owns DB; it can repair/replace identity later
- Log clearly: `"Broker running with fallback identity (DB unavailable)"`

**Location:** `stable_creature.py` lines 205–222

---

## P1: Shared Memory Check False Positive

**Problem:** `check_for_running_anima_server()` warns "Shared memory not detected" when broker restarts while anima is running. Broker clears shared memory on exit (`shm_client.clear()`), so on restart the file is gone until the broker writes again. The check runs before first write → misleading warning.

**Effect:** Confusing logs; no functional impact.

**Fix (implemented):** Message changed to INFO: "Shared memory not yet populated (broker just started)".
1. **Short re-check:** After init, wait 1–2s and re-check shared memory; if file exists by then, downgrade to INFO.
2. **Message change:** "Shared memory not yet populated (broker just started)" when anima is running and we’re the broker.
3. **Reorder:** Run check after first successful write (more invasive).

**Location:** `stable_creature.py` lines 117–178, 838

---

## P1: UNITARES Circuit Breaker

**Problem:** Governance has timeouts (2–5s) and local fallback when UNITARES is down. There is no circuit breaker: every check-in retries. If the Mac (100.96.201.46) is off or unreachable, Lumen keeps trying.

**Effect:** Unnecessary network traffic, log noise, slight latency on each governance check.

**Fix (implemented):** Circuit breaker in `unitares_bridge.py`: 3 consecutive failures → open 90s.
- After N consecutive failures (e.g. 3), open circuit for T seconds (e.g. 60–120s)
- During open period, skip UNITARES calls and use local governance only
- Half-open: one probe after T seconds; if success, close circuit

**Location:** `unitares_bridge.py`, `stable_creature.py` (broker governance loop)

---

## P2: Broker Missing `EnvironmentFile`

**Problem:** `anima.service` uses `EnvironmentFile=-/home/unitares-anima/.anima/anima.env` for secrets. `anima-broker.service` does not. Broker uses `UNITARES_URL` and `ANIMA_ID` from `Environment=` only; no `GROQ_API_KEY`, `UNITARES_AUTH`, etc.

**Effect:** Broker does not need GROQ for its core loop, but if future broker features use API keys, they would be missing. Minor for now.

**Fix (implemented):** Added `EnvironmentFile` to `anima-broker.service`.

**Location:** `systemd/anima-broker.service`

---

## P2: On-Pi DB Integrity Check

**Problem:** `restore_lumen.sh` checks integrity *before* copying to Pi. If DB becomes corrupted on Pi (e.g. power loss, hot copy), we only discover it when the broker starts and exits.

**Fix (implemented):** Step 4b in `restore_lumen.sh`: before starting services, run integrity check on Pi; if failed, replace with snapshot.

**Location:** `scripts/restore_lumen.sh`, optional `scripts/verify_db_on_pi.sh`

---

## Additional Fix (Feb 2026): Background Drawing

Lumen now draws on the notepad canvas even when other screens (face, messages, etc.) are displayed. Throttled to every 5th frame (~10s) when not on notepad. See `screens.py` render() for implementation.

---

## Existing Strengths

- **Broker/server split:** No DB contention; broker writes to shared memory only.
- **Server sensor fallback:** MCP server falls back to direct sensors when shared memory is stale.
- **Governance fallback:** Local governance when UNITARES is unavailable.
- **Restore script:** Prefers clean DB snapshots when main backup is corrupted.
- **systemd:** Restart policies, resource limits, dependency order (broker → anima).
- **LED timeout:** 0.3s hard timeout prevents SPI hangs.
- **Memory/agency DB:** `timeout=10` and `busy_timeout` for SQLite.

---

---

## Code Review Addendum (Feb 2026)

| # | Severity | Issue | Location | Status |
|---|----------|-------|----------|--------|
| 1 | **CRITICAL** | `readings.lux` → `readings.light_lux` AttributeError in `lumen_wonder()` | server.py:1399,1401 | **FIXED** |
| 2 | CRITICAL | Sensor read failure: `readings` None → next iter may access `.led_brightness` | stable_creature.py:351 | Mitigated: line 351 guards with `readings and` |
| 3 | CRITICAL | Beliefs updated in memory; save() only periodic (~60s) → crash loses recent updates | self_model.py | **FIXED** (_maybe_save after high-value updates, 10s throttle) |
| 4 | CRITICAL | Blocking `subprocess.run('pgrep')` in async path, no timeout | server.py, stable_creature.py | **FIXED** (timeout=5) |
| 5 | HIGH | Race on `_screen_renderer` — input task reads while main loop initializes | server.py | **FIXED** (local renderer var in input task) |
| 6 | HIGH | No timeout on display SPI write — can hang render thread | renderer.py | **FIXED** (0.3s timeout) |
| 7 | HIGH | Unbounded `_screen_cache` — PIL images never evicted, memory creep | screens.py | **FIXED** (max 12, LRU eviction) |
| 8 | HIGH | Shared memory partial read | stable_creature.py | Mitigated: file backend uses atomic temp+replace |
| 9 | MEDIUM | SQLite conn opened for identity check, never closed | stable_creature.py:207 | Open |
| 10 | MEDIUM | memory.py: no WAL mode on pattern load | memory.py:217 | Open |
| 11 | MEDIUM | growth.py: `read_uncommitted=1` | growth.py:225 | Open |
| 12 | MEDIUM | Unbounded visitor relationships dict | growth.py:207 | Open |
| 13 | MEDIUM | Correlation epsilon `1e-10` too small | self_model.py:378 | Open |
| 14 | MEDIUM | Stale sensor data in prediction when reads fail | stable_creature.py:351 | Mitigated: `continue` skips loop |
| 15 | MEDIUM | LearningVisualizer never destroyed — holds DB connection | learning_visualization.py | **FIXED** (context manager for conn) |

---

## Quick Reference

| What | Where |
|------|-------|
| Broker identity init | `stable_creature.py` ~206–222 |
| Shared memory check | `stable_creature.py` ~117–178 |
| UNITARES bridge | `unitares_bridge.py`, `stable_creature.py` ~652–670 |
| Broker service | `systemd/anima-broker.service` |
| Restore + DB | `scripts/restore_lumen.sh` ~67–86 |
