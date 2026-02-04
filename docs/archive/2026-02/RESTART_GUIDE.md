# Server Restart Guide

**Created:** January 12, 2026
**Last Updated:** January 13, 2026
**Status:** Active

---

## ⚡ Quick Restart (TL;DR)

**Most cases - just restart the MCP server (mind):**
```bash
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  "systemctl --user restart anima"
```

**If display frozen or server won't respond, that one command usually fixes it.**

---

## When to Restart

Restart the Anima server after:
- ✅ Code changes (like joystick integration)
- ✅ Configuration changes
- ✅ After deploying updates
- ✅ If server becomes unresponsive or display freezes

---

## Restart Methods

### 1. **Pi (systemd user service)** 🍓

The services run as user services (not system), so use `--user`:

```bash
# Restart MCP server only (most common)
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  "systemctl --user restart anima"

# Check status
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  "systemctl --user status anima"

# View logs
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  "journalctl --user -u anima -f"
```

**Auto-restart:** The service is configured with `Restart=on-failure`, so it will automatically restart if it crashes.

---

### 2. **Local Development (Mac/Linux)** 💻

**If running directly:**
```bash
# Find the process
ps aux | grep anima

# Kill the process (replace PID)
kill <PID>

# Or if running in terminal, just Ctrl+C

# Restart
cd /path/to/anima-mcp
python3 -m anima_mcp.server --sse --host 0.0.0.0 --port 8765
```

**If running via script:**
```bash
# Stop
./scripts/stop_anima.sh  # If you have one

# Start
./scripts/start_anima.sh  # If you have one
```

---

### 3. **Via MCP Client (Cursor/Claude)** 🔧

The server restarts automatically when:
- MCP client reconnects (if using SSE)
- Code changes are detected (if using hot-reload)

**Manual restart:**
- Stop the MCP server process
- Restart Cursor/Claude (will reconnect)

---

## Verification

After restart, verify joystick integration:

```bash
# Check logs for joystick initialization
grep -i joystick /path/to/logs

# Or via MCP tool
# Call diagnostics tool to see joystick status
```

**Expected output:**
```
[Joystick] Initialized successfully
# OR
[Joystick] Hardware library not available (expected on Mac)
```

---

## Quick Restart Commands

### Pi (via SSH)
```bash
# One-liner: restart and check status
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  "systemctl --user restart anima && systemctl --user status anima"
```

### Local
```bash
pkill -f "anima.*server" && python3 -m anima_mcp.server --sse
```

---

## Troubleshooting

### Server won't start
```bash
# Check for errors (on Pi via SSH)
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  "journalctl --user -u anima -n 50"

# Check for stale processes on port 8765
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  "lsof -i :8765"

# Kill stale processes and reset
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  "pkill -f 'anima.*--sse'; systemctl --user reset-failed anima"
```

**See also:** `docs/operations/REBOOT_LOOP_PREVENTION.md` for port 8765 trap details.

### Joystick not detected
- Verify hardware connection
- Check I2C is enabled: `sudo raspi-config`
- Check permissions: `groups` (should include `i2c`)
- Test I2C: `sudo i2cdetect -y 1`

---

**Status:** Restart required after code changes. Use systemctl on Pi, kill/restart locally.
