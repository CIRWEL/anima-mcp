# Quick Start: Pi Deployment

**Created:** January 12, 2026
**Last Updated:** February 26, 2026
**Status:** Active

---

## Prerequisites

- Raspberry Pi 4 (or 3B+)
- Raspberry Pi OS installed
- SSH access configured (user `unitares-anima`, key `~/.ssh/id_ed25519_pi`)
- Python 3.11+ installed

---

## 5-Minute Setup

### Step 1: Copy Code to Pi

```bash
# From Mac
cd ~/projects/anima-mcp
rsync -avz --exclude='.venv' --exclude='*.db' --exclude='__pycache__' --exclude='.git' \
  -e "ssh -i ~/.ssh/id_ed25519_pi" \
  ./ \
  unitares-anima@100.79.215.83:/home/unitares-anima/anima-mcp/
```

**Or via git:**
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
pip install -e ".[pi]"
```

### Step 3: Install Services

```bash
# Copy both service files
sudo cp systemd/anima.service /etc/systemd/system/
sudo cp systemd/anima-broker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable anima-broker anima
```

### Step 4: Start Services

```bash
# On Pi — broker must start first
sudo systemctl start anima-broker
sudo systemctl start anima
sudo systemctl status anima-broker anima
```

### Step 5: Verify

```bash
# On Pi
curl http://localhost:8766/health
```

---

## Common Commands

### Service Management

```bash
sudo systemctl start anima-broker anima    # Start both
sudo systemctl stop anima anima-broker     # Stop both
sudo systemctl restart anima-broker anima  # Restart both
sudo systemctl restart anima               # Restart MCP server only (safe)
sudo systemctl status anima-broker anima   # Status
```

### Logs

```bash
sudo journalctl -u anima -f               # Follow MCP server logs
sudo journalctl -u anima-broker -f         # Follow broker logs
sudo journalctl -u anima -n 50            # Last 50 lines
```

---

## Troubleshooting

### Service Won't Start

```bash
sudo systemctl status anima
sudo journalctl -u anima -n 100
```

### Health Check Fails

```bash
curl http://localhost:8766/health
```

### Need More Help?

See [`PI_DEPLOYMENT.md`](PI_DEPLOYMENT.md) for detailed guide.

---

**Last Updated:** February 26, 2026
