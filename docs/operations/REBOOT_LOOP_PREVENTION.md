# Reboot Loop Prevention

**Created:** January 12, 2026  
**Last Updated:** January 13, 2026  
**Status:** Critical Fix

---

## Problem

After unplugging/replugging hardware (USB, power, sensors), the broker service can enter a reboot loop:
1. Hardware disconnection causes I2C initialization to fail
2. Broker crashes during startup
3. systemd restarts broker immediately
4. Loop continues until hardware stabilizes or systemd gives up

---

## Root Causes

1. **I2C Bus Stuck**: After hardware disconnect, I2C bus may be in bad state
2. **Rapid Restarts**: systemd restarts too quickly (5 seconds) without hardware stabilization time
3. **No Circuit Breaker**: No backoff when initialization fails repeatedly
4. **Missing Error Handling**: Initialization failures cause immediate crash

---

## Fixes Applied

### 1. Better Error Handling (`stable_creature.py`)

**Added graceful degradation:**
- Catch initialization failures
- Exit cleanly with error message instead of crashing
- Give hardware time to stabilize (30 second delay) before exit
- Allow degraded operation (CPU-only readings) if I2C unavailable

**Code:**
```python
try:
    sensors = get_sensors()
    if hasattr(sensors, '_i2c') and sensors._i2c is None:
        print("[StableCreature] WARNING: I2C initialization failed")
        print("[StableCreature] Continuing with degraded sensor access")
except Exception as e:
    print(f"[StableCreature] CRITICAL: Sensor initialization failed: {e}")
    print("[StableCreature] Wait 30 seconds, then check hardware connections.")
    time.sleep(30)  # Give hardware time to stabilize
    sys.exit(1)
```

### 2. Restart Policy (`anima-broker.service`)

**Increased delays:**
- `RestartSec=10` (was 5) - longer delay between restarts
- `StartLimitInterval=300` - 5 minute window
- `StartLimitBurst=3` - max 3 restarts in 5 minutes
- `TimeoutStartSec=30` - fail fast if initialization hangs

**Result:** After 3 failures, systemd waits 5 minutes before allowing restart.

### 3. Hardware Stabilization

**30-second delay on critical failure:**
- Gives I2C bus time to reset
- Allows hardware to stabilize after reconnect
- Prevents immediate retry of failed initialization

---

## Prevention Strategy

### If Hardware Disconnects:

1. **Broker detects failure** → exits cleanly with delay
2. **systemd waits 10 seconds** → then restarts
3. **If still failing** → after 3 attempts, waits 5 minutes
4. **Hardware stabilizes** → broker starts successfully

### Manual Recovery:

If stuck in loop:

```bash
# Stop broker
ssh -p 2222 unitares-anima@192.168.1.165 \
  "systemctl --user stop anima-broker"

# Wait 30 seconds for hardware to stabilize
sleep 30

# Check hardware
ssh -p 2222 unitares-anima@192.168.1.165 \
  "i2cdetect -y 1"

# Restart broker
ssh -p 2222 unitares-anima@192.168.1.165 \
  "systemctl --user start anima-broker"

# Monitor logs
ssh -p 2222 unitares-anima@192.168.1.165 \
  "journalctl --user -u anima-broker -f"
```

---

## Monitoring

**Check if broker is restarting too frequently:**

```bash
ssh -p 2222 unitares-anima@192.168.1.165 \
  "systemctl --user status anima-broker | grep -E 'Active|restart'"
```

**Check restart count:**

```bash
ssh -p 2222 unitares-anima@192.168.1.165 \
  "systemctl --user show anima-broker | grep -E 'NRestart|StartLimit'"
```

**Watch logs for initialization failures:**

```bash
ssh -p 2222 unitares-anima@192.168.1.165 \
  "journalctl --user -u anima-broker | grep -i 'CRITICAL\|initialization\|I2C'"
```

---

## Future Improvements

1. **Health Check Endpoint**: Broker exposes health status via shared memory
2. **Circuit Breaker**: Track consecutive failures, disable restarts after threshold
3. **Hardware Detection**: Check hardware availability before initialization
4. **Graceful Degradation**: Continue with available sensors, don't crash on missing hardware

---

---

## ⚠️ CRITICAL TRAP: Port 8765 Stale Process

**🚨 FOR FUTURE AGENTS: This is a common trap that causes reboot loops!**

### The Problem

When the `anima` service crashes or is killed improperly, a stale process can remain bound to port 8765. When systemd tries to restart the service:

1. **New process tries to bind to port 8765** → fails with `[Errno 98] address already in use`
2. **Service exits immediately** → systemd sees exit code 1
3. **systemd restarts service** → same failure repeats
4. **Reboot loop begins** → service can't start, keeps trying

### Symptoms

- Service shows `Active: activating (auto-restart)` or `failed (Result: exit-code)`
- Logs show: `ERROR: [Errno 98] error while attempting to bind on address ('0.0.0.0', 8765): address already in use`
- Service restarts repeatedly but never stays running

### Quick Fix

**ALWAYS check for stale processes before troubleshooting:**

```bash
# Check if port 8765 is in use
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  "lsof -i :8765"

# Kill any stale anima processes
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  "pkill -f 'anima.*--sse'; systemctl --user stop anima; systemctl --user reset-failed anima"

# Verify port is free
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  "lsof -i :8765 || echo 'Port 8765 is free'"

# Now restart service
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  "systemctl --user start anima"
```

### Prevention

The service now handles shutdown gracefully, but if you see a reboot loop:

1. **First check:** Is port 8765 in use? (`lsof -i :8765`)
2. **Kill stale processes** before restarting
3. **Reset failed state** (`systemctl --user reset-failed anima`)
4. **Then restart** the service

### Why This Happens

- Service crashes during startup/shutdown
- Process doesn't release port before exit
- systemd restarts before port is freed
- Creates a race condition where old and new processes conflict

**Remember: Port 8765 is a trap - always check for stale processes first!**

---

## Related

- **`docs/operations/BROKER_ARCHITECTURE.md`** - Broker architecture
- **`stable_creature.py`** - Broker implementation
- **`systemd/anima-broker.service`** - Service configuration
- **`docs/TROUBLESHOOTING_MCP.md`** - General troubleshooting guide
