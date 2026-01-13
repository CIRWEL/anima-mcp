# ngrok Tunnel Setup for MCP Connections

**Created:** January 12, 2026  
**Last Updated:** January 12, 2026  
**Status:** Active

---

## Current State

### Mac (UNITARES)
- ✅ **ngrok installed:** `/opt/homebrew/bin/ngrok` (v3.34.1)
- ✅ **ngrok running:** `ngrok http --url=unitares.ngrok.io 8765`
- ✅ **Tunnel active:** `https://unitares.ngrok.io` → `localhost:8765`
- ✅ **UNITARES MCP:** Accessible via ngrok tunnel

### Pi (anima-mcp)
- ❌ **ngrok not installed**
- ❌ **No tunnel running**
- ⚠️ **UNITARES_URL not set** - anima not connecting to UNITARES
- ✅ **Local access:** `http://192.168.1.165:8765/sse` (works on local network)

---

## Why ngrok for MCP?

**Benefits:**
- ✅ **Reliable connectivity** - Works across networks, firewalls, NAT
- ✅ **HTTPS** - Secure connections
- ✅ **Consistent URLs** - Custom domains don't change
- ✅ **Verification** - If tunnel works, connection works
- ✅ **Debugging** - ngrok dashboard shows all requests

**Your philosophy:** "Get everyone on tunnel so I know it's working"

---

## Setup: UNITARES (Mac) - Already Running

**Current command:**
```bash
ngrok http --url=unitares.ngrok.io 8765
```

**Status:** ✅ Running (PID 732)

**Access:**
- **MCP endpoint:** `https://unitares.ngrok.io/mcp`
- **Dashboard:** `http://localhost:4040` (if web interface enabled)

**For Cursor MCP:**
```json
{
  "unitares-governance": {
    "type": "http",
    "url": "https://unitares.ngrok.io/mcp"
  }
}
```

**Note:** Currently using `localhost:8765/mcp` in Cursor config, but ngrok tunnel is available.

---

## Setup: anima-mcp (Pi) - Needs Setup

### Step 1: Install ngrok on Pi

```bash
# SSH to Pi
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165

# Download ngrok (ARM64 for Pi)
cd ~
wget https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-arm64.tgz
tar xvzf ngrok-v3-stable-linux-arm64.tgz
sudo mv ngrok /usr/local/bin/
ngrok version  # Verify installation
```

### Step 2: Configure ngrok (Custom Domain)

**Option A: Use existing ngrok account (if you have custom domain)**

```bash
# Set authtoken (get from ngrok dashboard)
ngrok config add-authtoken YOUR_AUTHTOKEN

# Set up custom domain (if available)
ngrok domains create anima.ngrok.io  # Or your preferred name
```

**Option B: Use free ngrok (random URL)**

```bash
# Set authtoken
ngrok config add-authtoken YOUR_AUTHTOKEN

# No custom domain needed - will get random URL
```

### Step 3: Start ngrok Tunnel

**For custom domain:**
```bash
ngrok http --url=anima.ngrok.io 8765
```

**For free tier (random URL):**
```bash
ngrok http 8765
```

**Get the URL:**
```bash
curl http://localhost:4040/api/tunnels | python3 -m json.tool
# Look for "public_url": "https://xxxxx.ngrok.io"
```

### Step 4: Update Cursor Config

**If custom domain:**
```json
{
  "anima": {
    "type": "sse",
    "url": "https://anima.ngrok.io/sse"
  }
}
```

**If random URL:**
```json
{
  "anima": {
    "type": "sse",
    "url": "https://xxxxx.ngrok.io/sse"
  }
}
```

### Step 5: Set UNITARES_URL on Pi

**For anima to connect to UNITARES:**

```bash
# Set environment variable (temporary)
export UNITARES_URL="https://unitares.ngrok.io/sse"

# Or add to systemd service (persistent)
# Edit /etc/systemd/system/lumen.service
# Add: Environment="UNITARES_URL=https://unitares.ngrok.io/sse"
```

**Or update stable_creature.py startup:**
```bash
export UNITARES_URL="https://unitares.ngrok.io/sse"
python3 stable_creature.py
```

---

## Complete Tunnel Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Mac (UNITARES)                                            │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ UNITARES Server (localhost:8765)                      │ │
│  └───────────────┬───────────────────────────────────────┘ │
│                  │                                          │
│                  ▼                                          │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ ngrok tunnel: unitares.ngrok.io → localhost:8765      │ │
│  └───────────────────────────────────────────────────────┘ │
│                  │                                          │
└──────────────────┼──────────────────────────────────────────┘
                    │ HTTPS
                    ▼
┌─────────────────────────────────────────────────────────────┐
│  Internet                                                    │
│  https://unitares.ngrok.io/mcp                              │
└──────────────────┬──────────────────────────────────────────┘
                   │ HTTPS
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  Pi (anima-mcp)                                             │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ anima --sse (localhost:8765)                         │ │
│  └───────────────┬───────────────────────────────────────┘ │
│                  │                                          │
│                  ▼                                          │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ ngrok tunnel: anima.ngrok.io → localhost:8765         │ │
│  └───────────────────────────────────────────────────────┘ │
│                  │                                          │
│                  │ UNITARES_URL=https://unitares.ngrok.io  │
│                  ▼                                          │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ UnitaresBridge connects to UNITARES                   │ │
│  └───────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

## Verification

### Check UNITARES Tunnel (Mac)
```bash
# Check if running
ps aux | grep ngrok | grep unitares

# Check tunnel status
curl http://localhost:4040/api/tunnels | python3 -m json.tool

# Test endpoint
curl https://unitares.ngrok.io/mcp
```

### Check anima Tunnel (Pi)
```bash
# After setting up ngrok on Pi
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165

# Check if running
ps aux | grep ngrok

# Check tunnel status
curl http://localhost:4040/api/tunnels | python3 -m json.tool

# Test endpoint
curl https://anima.ngrok.io/sse  # Or your ngrok URL
```

### Check anima → UNITARES Connection
```bash
# On Pi, check if UNITARES_URL is set
env | grep UNITARES_URL

# Check logs for UNITARES bridge activity
# Should see: "[StableCreature] UNITARES bridge active: https://unitares.ngrok.io/sse"
```

---

## Persistent Setup (systemd)

### UNITARES (Mac) - Already Running

**Current:** Running manually or via launchd

**For persistence:** Create `~/Library/LaunchAgents/com.unitares.ngrok.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.unitares.ngrok</string>
    <key>ProgramArguments</key>
    <array>
        <string>/opt/homebrew/bin/ngrok</string>
        <string>http</string>
        <string>--url=unitares.ngrok.io</string>
        <string>8765</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
```

### anima-mcp (Pi) - systemd Service

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

## Troubleshooting

### ngrok Tunnel Not Working

**Check 1: Is ngrok running?**
```bash
ps aux | grep ngrok | grep -v grep
```

**Check 2: Is local server running?**
```bash
# Mac (UNITARES)
lsof -i :8765 | grep LISTEN

# Pi (anima)
ssh pi "lsof -i :8765 | grep LISTEN"
```

**Check 3: Check ngrok logs**
```bash
# Mac
tail -f ~/.ngrok2/ngrok.log  # Or check stdout if running in terminal

# Pi
tail -f ~/.ngrok2/ngrok.log
```

**Check 4: Verify tunnel URL**
```bash
curl http://localhost:4040/api/tunnels | python3 -m json.tool
```

### UNITARES_URL Not Working

**Check 1: Is URL correct?**
```bash
# Should be HTTPS, not HTTP
export UNITARES_URL="https://unitares.ngrok.io/sse"  # ✅ Correct
export UNITARES_URL="http://unitares.ngrok.io/sse"   # ❌ Wrong (HTTP)
```

**Check 2: Is ngrok tunnel active?**
```bash
curl https://unitares.ngrok.io/mcp  # Should return something
```

**Check 3: Check anima logs**
```bash
# Should see UNITARES bridge messages
grep -i unitares ~/anima-mcp/anima.log
```

---

## Benefits of Full Tunnel Setup

✅ **Everything on tunnels** - Consistent, reliable access  
✅ **HTTPS everywhere** - Secure connections  
✅ **Works across networks** - No local IP dependencies  
✅ **Easy debugging** - ngrok dashboard shows all traffic  
✅ **Verification** - If tunnel works, connection works  

---

## Related

- **`docs/CURSOR_MCP_SETUP.md`** - Cursor MCP configuration
- **`docs/operations/HOLY_GRAIL_STARTUP.md`** - Startup sequence
- **`docs/features/UNIFIED_WORKFLOWS.md`** - UNITARES integration

---

**Goal: Get everyone on tunnels so you know it's working!**
