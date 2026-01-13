# Quick ngrok Setup for anima-mcp

**Created:** January 12, 2026  
**Last Updated:** January 12, 2026  
**Status:** Active

---

## Goal

Get anima-mcp on ngrok tunnel (like UNITARES) for reliable, visible access.

---

## Step 1: Install ngrok on Pi

```bash
# SSH to Pi
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165

# Download ngrok (ARM64 for Raspberry Pi)
cd ~
wget https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-arm64.tgz
tar xvzf ngrok-v3-stable-linux-arm64.tgz
sudo mv ngrok /usr/local/bin/
ngrok version  # Verify: should show version
```

---

## Step 2: Configure ngrok

**Get authtoken from:** https://dashboard.ngrok.com/get-started/your-authtoken

**Option A: Use setup script (easiest)**
```bash
# From Mac, deploy script and run on Pi
scp -P 2222 -i ~/.ssh/id_ed25519_pi scripts/setup_ngrok.sh unitares-anima@192.168.1.165:~/anima-mcp/scripts/
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 "cd ~/anima-mcp && ./scripts/setup_ngrok.sh YOUR_AUTHTOKEN"
```

**Option B: Manual setup**
```bash
# Set authtoken
ngrok config add-authtoken YOUR_AUTHTOKEN
```

**For custom domain (if you have one):**
```bash
# Create domain in ngrok dashboard first, then use --url flag when starting tunnel
# No need to run 'ngrok domains create' - just use --url=anima.ngrok.io
```

---

## Step 3: Start Tunnel

**Note:** For now, starting public (no auth). See `NGROK_AUTH_OPTIONS.md` for adding auth later.

**Option A: Custom Domain (Recommended)**
```bash
ngrok http --url=anima.ngrok.io 8765
```

**Option B: Free Tier (Random URL)**
```bash
ngrok http 8765
# Note the URL from output: https://xxxxx.ngrok.io
```

**Get the URL:**
```bash
# In another terminal
curl http://localhost:4040/api/tunnels | python3 -m json.tool
# Look for "public_url"
```

---

## Step 4: Update Cursor Config

**Edit `~/.cursor/mcp.json`:**

**If custom domain:**
```json
{
  "mcpServers": {
    "anima": {
      "type": "sse",
      "url": "https://anima.ngrok.io/sse"
    },
    "unitares-governance": {
      "type": "http",
      "url": "https://unitares.ngrok.io/mcp"
    }
  }
}
```

**If random URL:**
```json
{
  "mcpServers": {
    "anima": {
      "type": "sse",
      "url": "https://xxxxx.ngrok.io/sse"
    },
    "unitares-governance": {
      "type": "http",
      "url": "https://unitares.ngrok.io/mcp"
    }
  }
}
```

**Restart Cursor** to pick up changes.

---

## Step 5: Set UNITARES_URL on Pi

**For anima to connect to UNITARES:**

```bash
# Temporary (current session)
export UNITARES_URL="https://unitares.ngrok.io/sse"

# Or add to systemd service (persistent)
sudo nano /etc/systemd/system/lumen.service
# Add line: Environment="UNITARES_URL=https://unitares.ngrok.io/sse"
sudo systemctl daemon-reload
sudo systemctl restart lumen
```

**Or for stable_creature.py:**
```bash
export UNITARES_URL="https://unitares.ngrok.io/sse"
python3 stable_creature.py
```

---

## Step 6: Make Tunnel Persistent (systemd)

**Create `/etc/systemd/system/anima-ngrok.service`:**

```ini
[Unit]
Description=ngrok tunnel for anima-mcp
After=network.target

[Service]
Type=simple
User=unitares-anima
ExecStart=/usr/local/bin/ngrok http --url=anima.ngrok.io 8765
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Enable and start:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable anima-ngrok
sudo systemctl start anima-ngrok
sudo systemctl status anima-ngrok
```

---

## Verification

### Check Tunnel is Running
```bash
# On Pi
ps aux | grep ngrok | grep -v grep
curl http://localhost:4040/api/tunnels | python3 -m json.tool
```

### Test from Mac
```bash
# Test anima tunnel
curl https://anima.ngrok.io/sse

# Test UNITARES tunnel
curl https://unitares.ngrok.io/mcp
```

### Check Cursor MCP
1. Restart Cursor
2. Check MCP status - both servers should connect
3. Try `get_state` tool from anima

### Check Pi → UNITARES Connection
```bash
# On Pi, check logs
grep -i unitares ~/anima-mcp/anima.log
# Should see: "[Server] UNITARES bridge active: https://unitares.ngrok.io/sse"
```

---

## Result

✅ **Both servers on ngrok tunnels**
- anima: `https://anima.ngrok.io/sse`
- UNITARES: `https://unitares.ngrok.io/mcp`

✅ **Everything accessible via HTTPS**
- Works anywhere
- Secure connections
- Visible in ngrok dashboard

✅ **Pi connects to UNITARES via ngrok**
- `UNITARES_URL=https://unitares.ngrok.io/sse`
- Reliable connection

---

## Troubleshooting

**Tunnel not starting:**
```bash
# Check if port 8765 is in use
lsof -i :8765

# Check ngrok logs
tail -f ~/.ngrok2/ngrok.log
```

**Can't connect from Mac:**
```bash
# Verify tunnel URL
curl http://localhost:4040/api/tunnels | python3 -m json.tool

# Test endpoint
curl https://anima.ngrok.io/sse
```

**UNITARES_URL not working:**
```bash
# Verify it's set
env | grep UNITARES_URL

# Test connection
curl https://unitares.ngrok.io/sse
```

---

## Security: Adding Auth Later

**Current:** Public tunnel (works immediately, agents can access)

**Soon:** Add basic auth (see `NGROK_AUTH_OPTIONS.md`):
```bash
ngrok http 8765 --basic-auth="anima-agent:secure-password"
```

**Benefits:**
- ✅ Blocks public access
- ✅ Agents can still use (add auth header)
- ✅ Simple to implement

**For now:** Public is fine - URLs are long/random, can monitor dashboard, add auth when ready.

---

## Next Steps (Optional)

**Add Tailscale later** if you want:
- Private mesh network
- Lower latency
- No public exposure

**Add auth** when ready:
- Basic auth (simple)
- IP restrictions (more secure)
- ngrok Edge (most flexible)

**For now:** ngrok gives you reliable, visible tunnels for everything!

---

**Quick setup = Everything on tunnels = You know it's working!**
