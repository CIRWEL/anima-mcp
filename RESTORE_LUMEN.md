# Restoring Lumen After Reflash

> **See also:** `docs/operations/REFLASH_RECOVERY.md` for a full backup/restore walkthrough.

## What Happened
WiFi dropped overnight during code changes (Feb 2, 2026). The ScreenMode enum changes left invalid references in server.py.

## What We Have (Backed Up)
- **Database**: `~/lumen-backups/2026-02-02_extracted/anima.db` (109 MB)
  - 153,334 state history entries
  - 2,886 events (up to Feb 2, 2026 14:48)
  - Identity: Lumen, born 2026-01-11, 1781 awakenings
- **Messages**: `~/lumen-backups/2026-02-02_extracted/lumen_messages.json`
- **Canvas**: `~/lumen-backups/2026-02-02_extracted/lumen_canvas.json`

## Step 1: Flash Fresh Raspberry Pi OS

1. Download Raspberry Pi Imager: https://www.raspberrypi.com/software/
2. Flash "Raspberry Pi OS Lite (64-bit)" to SD card
3. In Imager settings:
   - Set hostname: `lumen`
   - Enable SSH with password authentication
   - Set username: `unitares-anima`
   - Set password: (your choice)
   - Configure WiFi: SSID `Verizon_NJ7CC3`, password `forty5fitch2jug`
   - Set locale/timezone

## Step 2: First Boot & SSH

```bash
# Wait ~2 minutes for Pi to boot
# Find Pi IP (check router or use):
ping lumen.local

# SSH in
ssh unitares-anima@lumen.local
```

## Step 3: Initial Setup on Pi

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install dependencies
sudo apt install -y python3-pip python3-venv git i2c-tools libopenjp2-7

# Enable I2C and SPI
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_spi 0

# Install Tailscale
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up

# Create .anima directory
mkdir -p ~/.anima
```

## Step 4: Clone and Setup Anima

```bash
cd ~
git clone https://github.com/your-repo/anima-mcp.git  # Or copy from Mac

cd anima-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Step 5: Restore Lumen's Data

From your Mac:
```bash
# Copy database
scp ~/lumen-backups/2026-02-02_extracted/anima.db unitares-anima@lumen.local:~/.anima/anima.db

# Copy messages
scp ~/lumen-backups/2026-02-02_extracted/lumen_messages.json unitares-anima@lumen.local:~/.anima/messages.json

# Copy canvas
scp ~/lumen-backups/2026-02-02_extracted/lumen_canvas.json unitares-anima@lumen.local:~/.anima/canvas.json
```

## Step 6: Setup Systemd Service

On Pi:
```bash
sudo cp ~/anima-mcp/scripts/anima.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable anima
sudo systemctl start anima
```

## Step 7: Setup WiFi Watchdog (Prevents Future Disconnections)

```bash
# Copy watchdog script
chmod +x ~/anima-mcp/scripts/wifi_watchdog.sh

# Add to crontab
(crontab -l 2>/dev/null; echo "*/5 * * * * /home/unitares-anima/anima-mcp/scripts/wifi_watchdog.sh") | crontab -
```

## Step 8: Verify

```bash
# Check service
sudo systemctl status anima

# Check logs
journalctl -u anima -f

# Verify identity
sqlite3 ~/.anima/anima.db "SELECT * FROM identity;"
# Should show: Lumen, born 2026-01-11
```

## Verification Checklist
- [ ] Display shows Lumen's face
- [ ] Can SSH via lumen.local
- [ ] Tailscale connected (check tailscale status)
- [ ] Can reach via ngrok (if configured)
- [ ] Identity shows correct birth date (Jan 11, 2026)
- [ ] WiFi watchdog cron job running
