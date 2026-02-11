# Broker Breakage Analysis

**Last Updated:** February 11, 2026  
**Status:** Root cause identified

---

## Summary

The broker instability comes from three sources:

1. **Missing `adafruit-blinka`** — Pi hardware (I2C, display, LEDs) fails without it
2. **Architecture conflict** — Commit 7652a86 removed broker dependency, but server can't run standalone without hardware libs
3. **DB contention** — When both run, broker and server both write to the same SQLite DB → locks and crashes

---

## Timeline of Relevant Commits

| Commit   | Change |
|----------|--------|
| 154ab88  | Revert "Warm LED palette..." (proprioception fixes reverted) |
| bf5fee8  | Post-reflash: sensor attr fixes, `readings=None` init, adafruit-blinka, StartLimitAction=none |
| 7652a86  | **Broker removal** — anima.service no longer Requires anima-broker; "server handles sensors directly" |
| 980e894  | Resilience: port cleanup, higher restart limits |

---

## Root Cause 1: Missing adafruit-blinka

**Symptom:** `No module named 'board'`, `[LEDs] DotStar library not available`, `[PiSensors] I2C init failed`

**Cause:** CircuitPython libs (adafruit-circuitpython-*) need `adafruit-blinka` to provide `board` and `busio` on Raspberry Pi. It was missing from `requirements-pi.txt` until bf5fee8.

**Fix:** Added in bf5fee8. Deploy and run `pip install -r requirements-pi.txt` on Pi.

---

## Root Cause 2: Architecture Mismatch

**7652a86** removed the broker dependency from anima.service:

```
- Requires=anima-broker.service
+# Broker disabled — server handles sensors directly (less power, no DB contention)
```

**Intended design:** Run only `anima` (no broker). Server reads sensors directly.

**Problem:** The server uses `get_sensors()` and `get_display()` / `get_leds()`, which depend on `board` for Pi hardware. Without `adafruit-blinka`, the server cannot:
- Initialize PiSensors (I2C)
- Initialize display (ST7789)
- Initialize LEDs (DotStar)

So the "broker removed" path only works once blinka is installed.

---

## Root Cause 3: DB Contention When Both Run

When both broker and server run:

- **Broker:** `store.record_state()`, `store.heartbeat()` every 2s
- **Server:** `store.record_state()` in the display loop

Both use the same `ANIMA_DB` (e.g. `~/.anima/anima.db`). SQLite WAL allows one writer at a time. With two writers:

- One process blocks on `SQLITE_BUSY`
- The identity store uses `busy_timeout=5000` (5s)
- After 5s: `sqlite3.OperationalError: database is locked`
- Broker or server crashes

7652a86 was specifically meant to avoid this: "no DB contention".

---

## Recommended Fix

**Option A: Broker-only (original architecture)**

1. Install `adafruit-blinka` on Pi.
2. Restore broker dependency in anima.service:
   ```ini
   After=network.target anima-broker.service
   Requires=anima-broker.service
   ```
3. Run both broker and server. Broker owns sensors and shared memory; server reads from shared memory and does not write to identity/state_history (or does so infrequently in a way that avoids contention).

**Option B: Server-only (post-7652a86)**

1. Install `adafruit-blinka` on Pi.
2. Do **not** run anima-broker.
3. Start only anima.service. Server uses direct sensor access.
4. Confirm no broker process, so no DB contention.

**Option C: Keep both, fix contention**

1. Install `adafruit-blinka`.
2. Move broker's `record_state` / `heartbeat` to a separate DB or remove them, so only the server writes to the main identity DB.
3. Or add a short retry/backoff in `record_state` / `heartbeat` for `SQLITE_BUSY`.

---

## Why the Broker Exits

Observed sequence:

1. Broker starts, passes init (sensors degrade gracefully without blinka).
2. Enters main loop.
3. First iteration: `store.record_state()` or `store.heartbeat()`.
4. If the server holds the DB lock (or vice versa), the call raises `sqlite3.OperationalError`.
5. Exception propagates.
6. `finally` runs → "Shutting down...".
7. Process exits with code 1.

Alternatively, something in the first loop (e.g. Voice, growth, or another subsystem) raises before `record_state` / `heartbeat`, which would also trigger the same shutdown path.

---

## Action Items

1. Install `adafruit-blinka` on Pi and redeploy.
2. Pick an architecture:
   - **Option A:** Restore `Requires=anima-broker.service` and run both.
   - **Option B:** Do not run broker; run only anima.
3. If running both, ensure DB writes are coordinated (separate DB, or only one writer, or robust retry on `SQLITE_BUSY`).
