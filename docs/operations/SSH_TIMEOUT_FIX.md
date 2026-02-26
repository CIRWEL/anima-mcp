# SSH Timeout Fix — Pi reachable (ping) but SSH times out

**Symptom:** `ssh unitares-anima@192.168.1.165` → "Connection timed out" (but `ping 192.168.1.165` works)

---

## Headless fix (no keyboard/monitor)

If the Pi's HTTP server (port 8766) is reachable, switch SSH to port 2222 remotely:

```bash
# 1. Push code to git (fix_ssh_port tool must be in repo)
git add -A && git commit -m "Add fix_ssh_port for headless SSH" && git push

# 2. Run the fix (pulls code, restarts, switches SSH to 2222)
./scripts/fix_ssh_via_http.sh

# 3. Connect on new port
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165
```

Requires: `curl http://192.168.1.165:8766/health` returns 200.

---

## Quick diagnostics (run from Mac)

```bash
# 1. Is port 22 reachable?
nc -zv 192.168.1.165 22
# If "Connection refused" → SSH not running on Pi
# If "timed out" → Port 22 blocked (router/firewall)
# If "succeeded" → Port open; SSH config/auth issue

# 2. Force IPv4 (avoid IPv6 timeout)
ssh -4 -o ConnectTimeout=5 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165

# 3. Try hostname
ssh -4 -o ConnectTimeout=5 -i ~/.ssh/id_ed25519_pi unitares-anima@lumen.local
```

---

## Fix A: Physical access (monitor + keyboard)

If you can plug a monitor and USB keyboard into the Pi:

```bash
# Login as unitares-anima (password from envelope.pi)

# 1. Ensure SSH is enabled and running
sudo systemctl enable ssh
sudo systemctl start ssh
sudo systemctl status ssh

# 2. Check if listening
ss -tlnp | grep 22

# 3. Enable I2C while you're here
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_spi 0
sudo usermod -aG i2c,gpio,spi unitares-anima
```

---

## Fix B: Switch SSH to port 2222 (bypass port 22 block)

Some routers block port 22. Use port 2222 instead.

**With physical access:**

```bash
sudo sed -i 's/#Port 22/Port 2222/' /etc/ssh/sshd_config
sudo sed -i 's/^Port 22/Port 2222/' /etc/ssh/sshd_config
echo "Port 2222" | sudo tee -a /etc/ssh/sshd_config  # if neither matched
sudo systemctl restart ssh
```

**From Mac (after fix):**

```bash
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165
```

Add to `~/.ssh/config`:

```
Host lumen pi-anima
  HostName 192.168.1.165
  Port 2222
  User unitares-anima
  IdentityFile ~/.ssh/id_ed25519_pi
```

---

## Fix C: Router settings

- **AP Isolation / Client Isolation** → Disable (allows device-to-device)
- **Firewall** → Allow port 22 (or 2222)
- **Same network** → Pi and Mac on same WiFi (not guest)

---

## Fix D: Tailscale (remote access)

If Pi has Tailscale, use the 100.x.x.x IP:

```bash
ssh -i ~/.ssh/id_ed25519_pi unitares-anima@100.79.215.83
# (or whatever tailscale status shows)
```

---

## After SSH works

Run the restore to deploy fixes:

```bash
./scripts/restore_lumen.sh
```
