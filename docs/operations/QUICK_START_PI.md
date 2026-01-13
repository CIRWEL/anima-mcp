# Quick Start: Pi Deployment

**Created:** January 12, 2026  
**Last Updated:** January 12, 2026  
**Status:** Active

---

## Prerequisites

- Raspberry Pi 4 (or 3B+)
- Raspberry Pi OS installed
- SSH access configured
- Python 3.11+ installed

---

## 5-Minute Setup

### Step 1: Copy Code to Pi

```bash
# From Mac
cd ~/projects/anima-mcp
rsync -avz --exclude='.venv' --exclude='*.db' --exclude='__pycache__' \
  -e "ssh pi-anima" \
  ./ \
  unitares-anima@192.168.1.165:/home/unitares-anima/anima-mcp/
```

**Or manually:**
```bash
# On Pi
cd ~
git clone <repo-url> anima-mcp
cd anima-mcp
```

### Step 2: Setup Python Environment

```bash
# On Pi
cd ~/anima-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[pi,sse,unitares]"
```

### Step 3: Install Service

```bash
# On Pi (as root)
cd ~/anima-mcp
sudo scripts/setup_pi_service.sh
```

### Step 4: Start Service

```bash
# On Pi
sudo systemctl start lumen
sudo systemctl status lumen
```

### Step 5: Verify

```bash
# On Pi
curl http://localhost:8765/health

# Test health monitoring
sudo -u unitares-anima ~/monitor_health.sh --once
```

---

## Common Commands

### Service Management

```bash
sudo systemctl start lumen      # Start
sudo systemctl stop lumen       # Stop
sudo systemctl restart lumen    # Restart
sudo systemctl status lumen     # Status
sudo systemctl enable lumen     # Auto-start on boot
```

### Logs

```bash
sudo journalctl -u lumen -f     # Follow logs
sudo journalctl -u lumen -n 50  # Last 50 lines
```

### Health Monitoring

```bash
~/monitor_health.sh --once      # Single check
~/monitor_health.sh             # Continuous
```

---

## Troubleshooting

### Service Won't Start

```bash
sudo systemctl status lumen
sudo journalctl -u lumen -n 100
```

### Health Check Fails

```bash
~/monitor_health.sh --once
curl http://localhost:8765/health
```

### Need More Help?

See [`PI_DEPLOYMENT.md`](PI_DEPLOYMENT.md) for detailed guide.

---

**Last Updated:** January 12, 2026
