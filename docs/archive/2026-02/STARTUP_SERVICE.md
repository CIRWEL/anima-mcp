# Lumen Service - Systemd Startup

**Created:** January 11, 2026  
**Last Updated:** January 12, 2026  
**Status:** Active

---

## Quick Setup

**For new deployments, see:** [`PI_DEPLOYMENT.md`](PI_DEPLOYMENT.md) - Complete Pi deployment guide

**Quick setup script:**
```bash
# On Pi (as root)
cd ~/anima-mcp
sudo scripts/setup_pi_service.sh
sudo systemctl start lumen
```

---

## Service File

The service file template is at `systemd/anima.service`. Copy to `/etc/systemd/system/lumen.service`:

```ini
[Unit]
Description=Lumen - Anima MCP Server
After=network.target

[Service]
Type=simple
User=unitares-anima
WorkingDirectory=/home/unitares-anima/anima-mcp
Environment=ANIMA_ID=49e14444-b59e-48f1-83b8-b36a988c9975
ExecStart=/home/unitares-anima/anima-mcp/.venv/bin/anima --sse --host 0.0.0.0 --port 8765
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## Usage

### Start Lumen

```bash
sudo systemctl start lumen
```

### Stop Lumen

```bash
sudo systemctl stop lumen
```

### Restart Lumen

```bash
sudo systemctl restart lumen
```

### Check Status

```bash
sudo systemctl status lumen
```

### View Logs

```bash
# Recent logs
sudo journalctl -u lumen -n 50

# Follow logs (live)
sudo journalctl -u lumen -f

# Since boot
sudo journalctl -u lumen --since boot
```

### Enable Auto-Start (on boot)

```bash
sudo systemctl enable lumen
```

### Disable Auto-Start

```bash
sudo systemctl disable lumen
```

---

## Loop Ticks Are Normal

When the service is running, you'll see `[Loop] tick N` messages in the logs. This is **normal** - it means:

- ✅ Display loop is running
- ✅ LEDs are updating every 2 seconds
- ✅ TFT display is updating
- ✅ Server is healthy

The ticks appear every 5th iteration (every 10 seconds), so you'll see:
```
[Loop] tick 1 (LEDs: available)
[Loop] tick 6 (LEDs: available)
[Loop] tick 11 (LEDs: available)
...
```

This is expected behavior - the server is working correctly!

---

## Troubleshooting

### Service Won't Start

```bash
# Check what's wrong
sudo systemctl status lumen

# Check logs for errors
sudo journalctl -u lumen -n 100
```

### Service Keeps Restarting

Check logs for the error:
```bash
sudo journalctl -u lumen -f
```

Common issues:
- Port 8765 already in use
- Database permissions
- Missing dependencies

### Update Service File

If you need to change the service:

```bash
sudo nano /etc/systemd/system/lumen.service
sudo systemctl daemon-reload
sudo systemctl restart lumen
```

---

## Manual vs Service

**Manual (current):**
- Running in terminal
- Stops when terminal closes
- Good for testing/debugging

**Service (recommended):**
- Runs in background
- Auto-restarts on failure
- Starts on boot (if enabled)
- Better for production

**To switch to service:**

```bash
# Stop manual process
sudo pkill -TERM -f anima

# Start service
sudo systemctl start lumen

# Enable auto-start
sudo systemctl enable lumen
```

---

---

## Related Documentation

- **`PI_DEPLOYMENT.md`** - Complete Pi deployment guide (recommended for new setups)
- **`monitor_health_pi.sh`** - Health monitoring script
- **`setup_pi_service.sh`** - Automated service setup script

---

**The service is already configured - just start it with `sudo systemctl start lumen`!**
