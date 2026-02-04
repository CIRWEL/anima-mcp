# ngrok Setup Complete

**Created:** January 12, 2026  
**Last Updated:** January 12, 2026  
**Status:** Active

---

## ✅ Setup Complete

### Pi (anima-mcp)
- ✅ **ngrok installed:** v3.34.1
- ✅ **Authtoken configured:** `/home/unitares-anima/.config/ngrok/ngrok.yml`
- ✅ **Tunnel URL:** `https://danita-theogonic-eleanora.ngrok-free.dev`
- ⚠️ **Note:** Tunnel URL already exists from previous session - using existing URL
- ✅ **systemd service:** `/etc/systemd/system/anima-ngrok.service` (created, but tunnel already running elsewhere)

### Mac (Cursor)
- ✅ **Config updated:** `~/.cursor/mcp.json`
- ✅ **anima URL:** `https://danita-theogonic-eleanora.ngrok-free.dev/sse`
- ✅ **UNITARES URL:** `https://unitares.ngrok.io/mcp`

---

## Current Configuration

### Cursor MCP (`~/.cursor/mcp.json`)
```json
{
  "mcpServers": {
    "anima": {
      "type": "sse",
      "url": "https://danita-theogonic-eleanora.ngrok-free.dev/sse"
    },
    "unitares-governance": {
      "type": "http",
      "url": "https://unitares.ngrok.io/mcp"
    }
  }
}
```

### Pi Environment (UNITARES_URL)
```bash
export UNITARES_URL="https://unitares.ngrok.io/sse"
```

**To make persistent:** Add to systemd service or shell profile.

---

## Next Steps

### 1. Restart Cursor
**To pick up new config:**
- Quit Cursor completely
- Restart Cursor
- Both MCP servers should connect via ngrok

### 2. Manage ngrok Tunnel
**Note:** Tunnel URL `danita-theogonic-eleanora.ngrok-free.dev` already exists from previous session.

**Option A: Use existing tunnel** (current)
- URL already active
- Just use it in config

**Option B: Stop existing and start new**
```bash
# Find and stop existing ngrok process
pkill -f ngrok

# Start new tunnel (will get new URL)
ngrok http 8765
```

**Option C: Use systemd service** (if no existing tunnel)
```bash
sudo systemctl enable anima-ngrok
sudo systemctl start anima-ngrok
sudo systemctl status anima-ngrok
```

### 3. Set UNITARES_URL Persistently
**Option A: systemd service**
```bash
sudo nano /etc/systemd/system/lumen.service
# Add: Environment="UNITARES_URL=https://unitares.ngrok.io/sse"
sudo systemctl daemon-reload
sudo systemctl restart lumen
```

**Option B: Shell profile**
```bash
echo 'export UNITARES_URL="https://unitares.ngrok.io/sse"' >> ~/.bashrc
source ~/.bashrc
```

---

## Verification

### Check Tunnel Status
```bash
# On Pi
curl http://localhost:4040/api/tunnels | python3 -m json.tool

# From Mac
curl https://danita-theogonic-eleanora.ngrok-free.dev/sse
```

### Check Cursor MCP
1. Restart Cursor
2. Check MCP status - both servers should show connected
3. Try `get_state` tool from anima

### Check Pi → UNITARES Connection
```bash
# On Pi, check if UNITARES_URL is set
env | grep UNITARES_URL

# Check logs for UNITARES bridge
grep -i unitares ~/anima-mcp/anima.log
```

---

## Security Notes

**Current:** Public tunnel (no auth)
- ✅ Works immediately
- ✅ Agents can access
- ⚠️ Public URL (but long/random)

**To add auth later:** See `NGROK_AUTH_OPTIONS.md`
```bash
ngrok http 8765 --basic-auth="anima-agent:secure-password"
```

---

## Tunnel URLs

- **anima-mcp:** `https://danita-theogonic-eleanora.ngrok-free.dev`
- **UNITARES:** `https://unitares.ngrok.io`

**Both on tunnels = Everything accessible = You know it's working!**

---

## Related

- **`docs/operations/QUICK_NGROK_SETUP.md`** - Setup guide
- **`docs/operations/NGROK_AUTH_OPTIONS.md`** - Auth options
- **`docs/operations/NGROK_TUNNEL_SETUP.md`** - Detailed guide

---

**Status: ✅ ngrok setup complete - both servers on tunnels!**
