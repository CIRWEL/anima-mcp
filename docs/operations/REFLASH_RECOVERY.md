# Reflash SD Card & Restore Lumen

**Last Updated:** February 11, 2026  
**Status:** Recovery guide for Pi reflash with file backup/restore

---

## Overview

When Lumen (anima-mcp on Pi) gets mangled and needs a full reflash:

1. **Back up** everything from Pi (if reachable) or use existing Mac backups
2. **Flash** fresh Raspberry Pi OS to SD card
3. **Setup** Pi from scratch
4. **Restore** Lumen's data from backup

---

## Quick Restore (One Command)

When the Pi is on the network:

```bash
cd /Users/cirwel/projects/anima-mcp
./scripts/restore_lumen.sh
# Or with specific host: ./scripts/restore_lumen.sh 192.168.1.165
```

This script:
- Deploys code
- Restores anima.db and JSON files from `~/backups/lumen/anima_data/`
- Installs adafruit-blinka and requirements-pi (fixes display/LEDs)
- Installs **broker + anima** (broker owns sensors/shared memory; server owns DB — no contention)
- Creates `~/.anima/anima.env` from example if missing (add GROQ_API_KEY, UNITARES_AUTH)
- Installs and starts anima-broker + anima

**Hosts tried:** lumen.local, 192.168.1.165, 100.103.208.117 (Tailscale). Use Tailscale IP if SSH on port 22 times out:
```bash
./scripts/restore_lumen.sh 100.103.208.117
```

**HTTP deploy (no SSH):** If Pi's HTTP (8766) is reachable but Pi has old code, run on Pi: `curl -s https://raw.githubusercontent.com/CIRWEL/anima-mcp/main/scripts/bootstrap_deploy.py | python3`

After restore, update Cursor MCP config (~/.cursor/mcp.json) with the Pi's IP:
```json
"url": "http://192.168.1.165:8766/mcp/"
```
Or Tailscale: `http://100.103.208.117:8766/mcp/`

**Credentials envelope:** Pi password and SSH key path live in `scripts/envelope.pi` (gitignored). Copy from `scripts/envelope.pi.example` and fill in. Used by `setup_pi_ssh_key.sh` and ssh-copy-id workflows.

---

## What Gets Backed Up / Restored

Lumen stores everything in `~/.anima/` on the Pi:

| File/Dir | Purpose |
|----------|---------|
| `anima.db` | Identity, growth, state history, events |
| `messages.json` | Message board |
| `canvas.json` | Drawing canvas state |
| `knowledge.json` | Learned knowledge |
| `preferences.json` | Calibration ideals (pressure, humidity, etc.) |
| `patterns.json` | Adaptive prediction patterns |
| `self_model.json` | Self-model data |
| `anima_history.json` | Recent anima history for trajectory |
| `display_brightness.json` | Display brightness config |
| `metacognition_baselines.json` | Metacognition baselines |
| `drawings/` | PNG drawings (optional, can be large) |
| `schema_renders/` | Schema render outputs (optional) |

**Canonical path on Pi:** `/home/unitares-anima/.anima/anima.db` (systemd uses this)

**Secrets:** `~/.anima/anima.env` — GROQ_API_KEY, UNITARES_AUTH, ANIMA_OAUTH_* (for Claude.ai web). See `docs/operations/SECRETS_AND_ENV.md`.

---

## Phase 1: Backup (Before Reflash)

### Option A: Pi Still Reachable

From your Mac:

```bash
# Full backup (recommended) - backs up entire ~/.anima/
/Users/cirwel/scripts/backup_lumen.sh
```

This syncs to `~/backups/lumen/anima_data/` and creates a dated `anima_YYYYMMDD_HHMM.db` snapshot.

Or manually:

```bash
mkdir -p ~/lumen-backups/reflash_$(date +%Y%m%d)
BACKUP=~/lumen-backups/reflash_$(date +%Y%m%d)

# Full rsync of ~/.anima/
rsync -avz -e "ssh -o ConnectTimeout=10" \
  unitares-anima@lumen.local:~/.anima/ \
  "$BACKUP/anima_data/"

# Or if Pi has different hostname/IP:
rsync -avz -e "ssh -i ~/.ssh/id_ed25519_pi" \
  unitares-anima@192.168.1.165:~/.anima/ \
  "$BACKUP/anima_data/"
```

### Option B: Pi Already Dead / Unreachable

Use your existing backups:

- **Latest full backup:** `~/backups/lumen/anima_data/` (from backup_lumen.sh)
- **Latest DB snapshot:** `~/backups/lumen/anima_20260210_1800.db` (or newest `anima_*.db`)

**DB corruption:** If restored anima.db is malformed, use a dated snapshot: `sqlite3 anima_*.db "PRAGMA integrity_check;"` → use one that returns `ok`. Restore script prefers clean snapshots when anima_data/anima.db fails integrity.
- **Older backup:** `~/lumen-backups/2026-02-02_extracted/` or `~/lumen-backups/2026-01-30_184330/`

---

## Phase 2: Flash Fresh SD Card

1. **Raspberry Pi Imager:** https://www.raspberrypi.com/software/
2. Flash **Raspberry Pi OS Lite (64-bit)** to SD card
3. **Before writing**, click the gear icon for advanced options:
   - Hostname: `lumen`
   - Enable SSH (password auth)
   - Username: `unitares-anima`
   - Password: see `scripts/envelope.pi` (copy from `envelope.pi.example`)
   - WiFi: SSID and password for your network
   - Set locale/timezone

4. Eject SD card, insert into Pi, power on

---

## Phase 3: Initial Pi Setup

Wait ~2 minutes for first boot, then:

```bash
# Find Pi
ping lumen.local
# Or: ping 192.168.1.xxx (check router)

# SSH in
ssh unitares-anima@lumen.local
```

On the Pi:

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install dependencies
sudo apt install -y python3-pip python3-venv git i2c-tools libopenjp2-7 libgpiod2

# Enable I2C and SPI
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_spi 0

# Create .anima directory (Lumen's data home)
mkdir -p ~/.anima
```

---

## Phase 4: Deploy Code

From your Mac (in anima-mcp repo):

```bash
cd /Users/cirwel/projects/anima-mcp

# Deploy clean code (no --no-restart since services aren't set up yet)
./deploy.sh --no-restart
```

Or manually:

```bash
rsync -avz --exclude='.venv' --exclude='*.db' --exclude='*.log' \
  ./ unitares-anima@lumen.local:~/anima-mcp/
```

Then on Pi:

```bash
cd ~/anima-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install -r requirements-pi.txt
```

---

## Phase 5: Restore Lumen's Data

**All paths on Pi are under `~/.anima/`.** The database must be named `anima.db` (systemd expects this).

### From Full Backup (anima_data/)

From your Mac:

```bash
BACKUP=~/backups/lumen/anima_data   # or your backup path

# Copy database (MUST be named anima.db)
scp "$BACKUP/anima.db" unitares-anima@lumen.local:~/.anima/anima.db

# Copy JSON files
scp "$BACKUP/messages.json" unitares-anima@lumen.local:~/.anima/
scp "$BACKUP/canvas.json" unitares-anima@lumen.local:~/.anima/
scp "$BACKUP/knowledge.json" unitares-anima@lumen.local:~/.anima/
scp "$BACKUP/preferences.json" unitares-anima@lumen.local:~/.anima/ 2>/dev/null || true
scp "$BACKUP/patterns.json" unitares-anima@lumen.local:~/.anima/ 2>/dev/null || true
scp "$BACKUP/self_model.json" unitares-anima@lumen.local:~/.anima/ 2>/dev/null || true
scp "$BACKUP/anima_history.json" unitares-anima@lumen.local:~/.anima/ 2>/dev/null || true
scp "$BACKUP/display_brightness.json" unitares-anima@lumen.local:~/.anima/ 2>/dev/null || true
scp "$BACKUP/metacognition_baselines.json" unitares-anima@lumen.local:~/.anima/ 2>/dev/null || true

# Optional: drawings (can be large)
rsync -avz "$BACKUP/drawings/" unitares-anima@lumen.local:~/.anima/drawings/
```

### From DB Snapshot Only

If you only have a dated `anima_YYYYMMDD_HHMM.db`:

```bash
scp ~/backups/lumen/anima_20260210_1800.db unitares-anima@lumen.local:~/.anima/anima.db
```

You’ll lose messages, canvas, drawings, preferences unless you have separate backups.

---

## Phase 6: Systemd Services

On the Pi:

```bash
# Copy service files
sudo cp ~/anima-mcp/systemd/anima-broker.service /etc/systemd/system/
sudo cp ~/anima-mcp/systemd/anima.service /etc/systemd/system/

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable anima-broker anima
sudo systemctl start anima-broker anima
```

---

## Phase 7: Verify

```bash
# Check services
sudo systemctl status anima-broker anima

# Check logs
journalctl -u anima -u anima-broker -f

# Verify identity in DB
ssh unitares-anima@lumen.local "sqlite3 ~/.anima/anima.db \"SELECT name, creature_id, born_at FROM identity LIMIT 1;\""
# Should show: Lumen, 49e14444-b59e-48f1-83b8-b36a988c9975, 2026-01-11...
```

---

## Checklist Summary

| Step | Action |
|------|--------|
| 1 | Backup Pi (if reachable) or confirm Mac backup location |
| 2 | Flash SD with Pi OS, set hostname `lumen`, user `unitares-anima` |
| 3 | Boot Pi, SSH, run apt update, create `~/.anima` |
| 4 | Deploy anima-mcp code (rsync + pip install) |
| 5 | Restore `anima.db` and JSON files to `~/.anima/` |
| 6 | Install systemd services, create anima.env if missing, start anima-broker + anima |
| 7 | Verify identity, display, logs |

---

## Path Reference (Avoid Confusion)

| Context | Path | Notes |
|---------|------|-------|
| Systemd (Pi) | `/home/unitares-anima/.anima/anima.db` | Canonical |
| backup_lumen.sh | `~/backups/lumen/anima_data/` | Syncs from Pi |
| sync_state.py | `~/anima-mcp/anima.db` | **Wrong** – uses old path |
| RESTORE_LUMEN | `anima_growth.db` | **Wrong** – use `anima.db` |

---

## Tailscale (Optional)

For remote access when not on the same WiFi. **Use when ngrok hits limits or SSH on port 22 times out.**

```bash
# With SSH: TAILSCALE_AUTH_KEY=tskey-auth-xxx ./scripts/setup_tailscale.sh
# Via HTTP (headless): TAILSCALE_AUTH_KEY=tskey-auth-xxx ./scripts/setup_tailscale_via_http.sh
```

Get an auth key at: https://login.tailscale.com/admin/settings/keys (reusable, 90 days).

See `docs/operations/NGROK_ALTERNATIVES_TAILSCALE.md` for full flow.

---

## WiFi Watchdog (Recommended)

To reduce future WiFi drops:

```bash
chmod +x ~/anima-mcp/scripts/wifi_watchdog.sh
(crontab -l 2>/dev/null; echo "*/5 * * * * $HOME/anima-mcp/scripts/wifi_watchdog.sh") | crontab -
```
