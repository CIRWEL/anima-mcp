# Raspberry Pi Deployment Guide

**Created:** January 12, 2026  
**Last Updated:** February 26, 2026
**Status:** Active

---

## Overview

This guide covers deploying Anima MCP server to a Raspberry Pi with:
- ✅ Systemd service for auto-start and reliability
- ✅ Health monitoring for proactive issue detection
- ✅ Network access via ngrok (optional)
- ✅ Hardware integration (display, LEDs, sensors)

---

## Prerequisites

### Hardware
- Raspberry Pi 4 (recommended) or Pi 3B+
- BrainCraft HAT (optional - for display/LEDs)
- BME280 sensor (temp/humidity/pressure)
- VEML7700 light sensor

### Software
- Raspberry Pi OS (Debian-based)
- Python 3.11+
- SSH access configured
- User account: `unitares-anima`

---

## Step 1: Initial Pi Setup

### 1.1 Create User Account

```bash
# On Pi
sudo adduser unitares-anima
sudo usermod -aG gpio,i2c,spi unitares-anima
```

### 1.2 Install Dependencies

```bash
# On Pi
sudo apt update
sudo apt install -y python3-pip python3-venv git

# Install hardware dependencies (if using BrainCraft HAT)
sudo apt install -y python3-rpi.gpio python3-pil python3-numpy
```

### 1.3 Clone Repository

```bash
# On Pi (as unitares-anima user)
cd ~
git clone <repository-url> anima-mcp
cd anima-mcp
```

---

## Step 2: Python Environment Setup

### 2.1 Create Virtual Environment

```bash
# On Pi
cd ~/anima-mcp
python3 -m venv .venv
source .venv/bin/activate
```

### 2.2 Install Dependencies

```bash
# Install base dependencies
pip install -e .

# Install Pi-specific dependencies
pip install -e ".[pi]"
```

### 2.3 Verify Installation

```bash
# Test that anima command works
.venv/bin/anima --help
```

---

## Step 3: Configure Systemd Service

### 3.1 Copy Service Files

```bash
# On Pi (as root or with sudo)
sudo cp ~/anima-mcp/systemd/anima.service /etc/systemd/system/anima.service
sudo cp ~/anima-mcp/systemd/anima-broker.service /etc/systemd/system/anima-broker.service
```

### 3.2 Edit Service Files (if needed)

```bash
sudo nano /etc/systemd/system/anima.service
```

**Key settings to verify:**
- `User=unitares-anima` - Correct user
- `WorkingDirectory` - Points to correct path
- `ExecStart` - Points to correct venv path
- `ANIMA_ID` - Your creature's UUID
- `UNITARES_URL` - UNITARES governance URL (if using)

### 3.3 Reload Systemd

```bash
sudo systemctl daemon-reload
```

### 3.4 Enable Services (auto-start on boot)

```bash
sudo systemctl enable anima-broker anima
```

### 3.5 Start Services

```bash
sudo systemctl start anima-broker anima
```

### 3.6 Check Status

```bash
sudo systemctl status anima-broker anima
```

**Expected output:**
```
● anima.service - Anima MCP Server - Lumen's Mind (MCP Interface)
   Loaded: loaded (/etc/systemd/system/anima.service; enabled)
   Active: active (running) since ...
```

---

## Step 4: Verify Deployment

### 4.1 Check Service Status

```bash
sudo systemctl status anima
```

### 4.2 Check Logs

```bash
# Recent logs
sudo journalctl -u anima -n 50

# Follow logs (live)
sudo journalctl -u anima -f

# Since boot
sudo journalctl -u anima --since boot
```

**Look for:**
- ✅ `[Loop] tick N` messages (normal - display loop running)
- ✅ `Server started on http://0.0.0.0:8766`
- ✅ No error messages

### 4.3 Test Health Endpoint

```bash
# From Pi
curl http://localhost:8766/health

# From Mac (if on same network)
curl http://pi.local:8766/health
```

### 4.4 Test MCP Connection

```bash
# From Mac, test Streamable HTTP connection
curl http://pi.local:8766/health
```

---

## Step 5: Set Up Health Monitoring

### 5.1 Copy Health Monitor Script

```bash
# On Pi
cp ~/anima-mcp/scripts/monitor_health_pi.sh ~/monitor_health.sh
chmod +x ~/monitor_health.sh
```

### 5.2 Test Health Monitor

```bash
# Single check
~/monitor_health.sh --once

# Continuous monitoring (Ctrl+C to stop)
~/monitor_health.sh
```

### 5.3 Set Up Cron Job (Optional)

```bash
# Edit crontab
crontab -e

# Add: Check health every 5 minutes
*/5 * * * * /home/unitares-anima/monitor_health.sh --once >> /tmp/anima_health.log 2>&1
```

### 5.4 Set Up Systemd Timer (Recommended)

Create `/etc/systemd/system/anima-health.timer`:

```ini
[Unit]
Description=Anima Health Check Timer
After=network.target

[Timer]
OnBootSec=5min
OnUnitActiveSec=5min
Unit=anima-health.service

[Install]
WantedBy=timers.target
```

Create `/etc/systemd/system/anima-health.service`:

```ini
[Unit]
Description=Anima Health Check
After=network.target

[Service]
Type=oneshot
User=unitares-anima
ExecStart=/home/unitares-anima/monitor_health.sh --once
StandardOutput=journal
StandardError=journal
```

Enable timer:

```bash
sudo systemctl daemon-reload
sudo systemctl enable anima-health.timer
sudo systemctl start anima-health.timer
sudo systemctl status anima-health.timer
```

---

## Step 6: Network Access (Optional)

### 6.1 Set Up Ngrok Tunnel

See `docs/operations/NGROK_SETUP_COMPLETE.md` for detailed instructions.

**Quick setup:**
```bash
# On Pi
ngrok http 8766 --url=your-custom-domain.ngrok.io
```

### 6.2 Configure Ngrok as Service

Create `/etc/systemd/system/anima-ngrok.service`:

```ini
[Unit]
Description=Anima Ngrok Tunnel
After=network.target anima.service
Requires=anima.service

[Service]
Type=simple
User=unitares-anima
ExecStart=/usr/local/bin/ngrok http 8766 --url=your-custom-domain.ngrok.io --log=stdout
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable anima-ngrok
sudo systemctl start anima-ngrok
sudo systemctl status anima-ngrok
```

---

## Step 7: Configure MCP Clients

### 7.1 Cursor / Claude Code Configuration

On Mac, edit `~/.cursor/mcp.json` or `~/.claude.json`:

```json
{
  "mcpServers": {
    "anima": {
      "type": "http",
      "url": "http://100.79.215.83:8766/mcp/"
    }
  }
}
```

Uses Tailscale (no auth required). LAN IP (`http://192.168.1.165:8766/mcp/`) also works.

### 7.2 Claude.ai Web (via ngrok + OAuth 2.1)

Claude.ai web connects via ngrok with automatic OAuth 2.1 authentication:
- URL: `https://lumen-anima.ngrok.io/mcp/`
- Auth: OAuth 2.1 (PKCE, auto-approve — no manual steps needed)
- Callback: `https://claude.ai/api/mcp/auth_callback`

**Required env vars** in `~/.anima/anima.env` or systemd service:
```bash
ANIMA_OAUTH_ISSUER_URL=https://lumen-anima.ngrok.io
ANIMA_OAUTH_AUTO_APPROVE=true
```

OAuth only protects `/mcp/` via ngrok. Dashboard and API endpoints remain open.

---

## Step 8: Post-Deployment Checklist

- [ ] Service starts automatically on boot
- [ ] Service restarts on failure
- [ ] Health endpoint responds correctly
- [ ] Logs show no errors
- [ ] Display/LEDs updating (if hardware present)
- [ ] Sensors reading correctly (if hardware present)
- [ ] MCP clients can connect
- [ ] Health monitoring is active
- [ ] Ngrok tunnel working (if configured)
- [ ] Database file created and accessible

---

## Troubleshooting

### Service Won't Start

```bash
# Check status
sudo systemctl status anima

# Check logs
sudo journalctl -u anima -n 100

# Common issues:
# - Port 8766 already in use
# - Database permissions
# - Missing dependencies
# - Wrong paths in service file
```

### Service Keeps Restarting

```bash
# Check logs for errors
sudo journalctl -u anima -f

# Check resource limits
systemctl show anima | grep -i limit

# Check disk space
df -h
```

### Health Check Fails

```bash
# Run health monitor manually
~/monitor_health.sh --once

# Check service status
sudo systemctl status anima

# Check network connectivity
curl http://localhost:8766/health
```

### Display/LEDs Not Working

```bash
# Check hardware connections
ls -la /dev/spi*

# Check permissions
groups unitares-anima  # Should include gpio, spi, i2c

# Test display manually
cd ~/anima-mcp
source .venv/bin/activate
python scripts/test_display_visual.py
```

### Database Issues

```bash
# Check database file
ls -la ~/anima-mcp/anima.db

# Check permissions
ls -la ~/anima-mcp/ | grep anima.db

# Fix permissions if needed
chmod 644 ~/anima-mcp/anima.db
```

---

## Maintenance

### View Logs

```bash
# Recent logs
sudo journalctl -u anima -n 50

# Follow logs
sudo journalctl -u anima -f

# Logs since boot
sudo journalctl -u anima --since boot

# Logs from specific time
sudo journalctl -u anima --since "2026-01-12 10:00:00"
```

### Restart Service

```bash
sudo systemctl restart anima-broker anima
```

### Update Code

**Recommended: Use deploy script (from Mac)**
```bash
# From Mac (in anima-mcp directory)
./deploy.sh

# Options:
#   ./deploy.sh --no-restart    # Deploy without restarting services
#   ./deploy.sh --logs           # Show logs after deploy
#   ./deploy.sh --host IP        # Override Pi hostname/IP
```

**Manual update (on Pi directly)**
```bash
# On Pi
cd ~/anima-mcp
git pull
source .venv/bin/activate
pip install -e ".[pi]"
sudo systemctl restart anima-broker anima
```

### Backup Database

```bash
# On Pi
cp ~/anima-mcp/anima.db ~/anima.db.backup.$(date +%Y%m%d)
```

---

## Security Considerations

### Firewall

```bash
# Allow SSH
sudo ufw allow 22/tcp

# Allow MCP port (local network only)
sudo ufw allow from 192.168.1.0/24 to any port 8766

# Enable firewall
sudo ufw enable
```

### Service User

- Service runs as `unitares-anima` (non-root)
- Limited file system access
- No sudo privileges

### Ngrok Security

- Use custom domain (not random URLs)
- OAuth 2.1 protects `/mcp/` endpoint (enabled via `ANIMA_OAUTH_ISSUER_URL`)
- Dashboard endpoints (`/dashboard`, `/gallery-page`, etc.) remain open via ngrok
- Tokens are in-memory — reset on service restart, clients re-authenticate automatically

---

## Quick Reference

### Service Management

```bash
sudo systemctl start anima-broker anima    # Start both
sudo systemctl stop anima anima-broker     # Stop both
sudo systemctl restart anima-broker anima  # Restart both
sudo systemctl status anima-broker anima   # Status
sudo systemctl enable anima-broker anima   # Enable auto-start
sudo systemctl disable anima-broker anima  # Disable auto-start
```

### Health Monitoring

```bash
~/monitor_health.sh --once      # Single check
~/monitor_health.sh             # Continuous
```

### Logs

```bash
sudo journalctl -u anima -f     # Follow logs
sudo journalctl -u anima -n 50  # Last 50 lines
```

### Testing

```bash
curl http://localhost:8766/health
curl http://pi.local:8766/state
```

---

## Related Documentation

- **`docs/operations/STARTUP_SERVICE.md`** - Systemd service details
- **`docs/operations/NGROK_SETUP_COMPLETE.md`** - Ngrok configuration
- **`docs/operations/TROUBLESHOOTING.md`** - Common issues
- **`README.md`** - Project overview

---

**Last Updated:** February 26, 2026
