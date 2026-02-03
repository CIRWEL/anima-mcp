# Multiple ngrok Tunnels Setup for Connection Consistency

**Created:** February 3, 2026  
**Purpose:** Set up redundant ngrok tunnels with Streamable HTTP for connection consistency monitoring

---

## Overview

**Goal:** Multiple tunnels for redundancy + Streamable HTTP for connection consistency monitoring

**Benefits:**
- ✅ **Redundancy** - If one tunnel fails, backup is available
- ✅ **Connection monitoring** - Streamable HTTP allows consistency checks
- ✅ **High availability** - Multiple paths to the same server
- ✅ **Debugging** - Compare tunnel performance

---

## Setup Steps

### 1. SSH to Pi

```bash
ssh -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165
# or using hostname alias (port 22, standard SSH):
ssh lumen.local
```

### 2. Run Setup Script

```bash
cd ~/anima-mcp
./scripts/setup_multiple_ngrok_tunnels.sh YOUR_NGROK_AUTHTOKEN lumen-anima.ngrok.io anima-backup.ngrok.io
```

**Note:** Replace `YOUR_NGROK_AUTHTOKEN` with your actual ngrok authtoken from https://dashboard.ngrok.com/get-started/your-authtoken

**Domains:**
- `lumen-anima.ngrok.io` - Primary tunnel (custom domain)
- `anima-backup.ngrok.io` - Backup tunnel (custom domain)

**Or use free tier (random URLs):**
```bash
./scripts/setup_multiple_ngrok_tunnels.sh YOUR_NGROK_AUTHTOKEN
# Will use default domains or create random URLs
```

### 3. Install and Start Services

```bash
# Install services
sudo cp /tmp/anima-ngrok-primary.service /etc/systemd/system/
sudo cp /tmp/anima-ngrok-backup.service /etc/systemd/system/
sudo systemctl daemon-reload

# Enable and start
sudo systemctl enable anima-ngrok-primary
sudo systemctl enable anima-ngrok-backup
sudo systemctl start anima-ngrok-primary
sudo systemctl start anima-ngrok-backup

# Check status
sudo systemctl status anima-ngrok-primary
sudo systemctl status anima-ngrok-backup
```

### 4. Get Tunnel URLs

```bash
# Check primary tunnel
curl http://localhost:4040/api/tunnels | python3 -m json.tool | grep -A 5 "public_url"

# Or check ngrok dashboard
# Primary: http://localhost:4040 (if running on Pi)
# Backup: Check second tunnel's public_url
```

**Expected URLs:**
- Primary: `https://lumen-anima.ngrok.io/mcp/`
- Backup: `https://anima-backup.ngrok.io/mcp/` (or random URL)

---

## Update Cursor Config

Once tunnels are running, update `~/.cursor/mcp.json`:

**Option 1: Use Primary Tunnel**
```json
{
  "mcpServers": {
    "anima": {
      "type": "http",
      "url": "https://lumen-anima.ngrok.io/mcp/"
    }
  }
}
```

**Option 2: Use Backup Tunnel (if primary fails)**
```json
{
  "mcpServers": {
    "anima": {
      "type": "http",
      "url": "https://anima-backup.ngrok.io/mcp/"
    }
  }
}
```

**Note:** Cursor doesn't support automatic failover, so you'll need to manually switch URLs if one tunnel fails.

---

## Connection Consistency Monitoring

### Check Tunnel Status

Run the consistency checker script:

```bash
cd ~/anima-mcp
./scripts/check_tunnel_consistency.sh \
  https://lumen-anima.ngrok.io/mcp/ \
  https://anima-backup.ngrok.io/mcp/
```

**Output:**
```
🔍 Checking tunnel connection consistency...

Testing Primary: https://lumen-anima.ngrok.io/mcp/
   ✅ Primary: Connected (HTTP 200)

Testing Backup: https://anima-backup.ngrok.io/mcp/
   ✅ Backup: Connected (HTTP 200)

📊 Consistency Report:
   ✅ Both tunnels operational
   ✅ High availability - redundancy active
```

### Automated Monitoring

Add to crontab for periodic checks:

```bash
# Edit crontab
crontab -e

# Add line (check every 5 minutes)
*/5 * * * * /home/unitares-anima/anima-mcp/scripts/check_tunnel_consistency.sh https://lumen-anima.ngrok.io/mcp/ https://anima-backup.ngrok.io/mcp/ >> /tmp/tunnel_consistency.log 2>&1
```

### Manual Testing

**Test Streamable HTTP endpoint:**
```bash
# Primary tunnel
curl -H "Accept: text/event-stream" \
     -H "Content-Type: application/json" \
     https://lumen-anima.ngrok.io/mcp/

# Backup tunnel
curl -H "Accept: text/event-stream" \
     -H "Content-Type: application/json" \
     https://anima-backup.ngrok.io/mcp/
```

**Expected:** SSE event stream response (connection established)

---

## Why Streamable HTTP for Consistency?

**Streamable HTTP (`/mcp/`) advantages:**
- ✅ **Session-based** - Can track connection state
- ✅ **Resumable** - Sessions can resume after disconnect
- ✅ **Bidirectional** - Better for monitoring
- ✅ **MCP 1.24.0+ compliant** - Future-proof

**SSE (`/sse`) limitations:**
- ⚠️ One-way only (server → client)
- ⚠️ Harder to track connection state
- ⚠️ Legacy transport (marked for deprecation)

**For consistency monitoring:**
- Streamable HTTP allows checking if connection is truly active
- Can verify session state and resumability
- Better error reporting

---

## Troubleshooting

### Tunnel Not Starting

**Check ngrok authtoken:**
```bash
ngrok config check
```

**Check if port is in use:**
```bash
lsof -i :8766
```

**Check service logs:**
```bash
sudo journalctl -u anima-ngrok-primary -n 50
sudo journalctl -u anima-ngrok-backup -n 50
```

### Connection Consistency Issues

**Check if both tunnels are active:**
```bash
# Check primary
curl -I https://lumen-anima.ngrok.io/mcp/

# Check backup
curl -I https://anima-backup.ngrok.io/mcp/
```

**Check ngrok dashboard:**
- Primary: http://localhost:4040 (if accessible)
- Or: https://dashboard.ngrok.com/endpoints

**Verify server is running:**
```bash
sudo systemctl status anima
curl http://localhost:8766/health
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Pi (anima-mcp)                                        │
│  ┌───────────────────────────────────────────────────┐ │
│  │ anima --sse (localhost:8766)                      │ │
│  └───────────────┬───────────────────────────────────┘ │
│                  │                                      │
│        ┌─────────┴─────────┐                           │
│        │                   │                           │
│        ▼                   ▼                           │
│  ┌──────────┐       ┌──────────┐                       │
│  │ ngrok    │       │ ngrok    │                       │
│  │ Primary  │       │ Backup   │                       │
│  └────┬─────┘       └────┬─────┘                       │
└───────┼──────────────────┼─────────────────────────────┘
        │                  │
        │ HTTPS            │ HTTPS
        ▼                  ▼
┌──────────────┐    ┌──────────────┐
│ Primary URL  │    │ Backup URL   │
│ lumen-anima  │    │ anima-backup │
│ .ngrok.io    │    │ .ngrok.io    │
└──────┬───────┘    └──────┬───────┘
       │                   │
       └─────────┬─────────┘
                 │
                 ▼
         ┌───────────────┐
         │   Internet    │
         └───────┬───────┘
                 │
                 ▼
         ┌───────────────┐
         │  Cursor (Mac) │
         │  Uses Primary │
         │  (or Backup)  │
         └───────────────┘
```

---

## Benefits Summary

✅ **Redundancy** - Two tunnels = higher availability  
✅ **Consistency monitoring** - Streamable HTTP allows active connection checks  
✅ **Debugging** - Compare tunnel performance  
✅ **Future-proof** - Using Streamable HTTP (MCP 1.24.0+)  
✅ **Automated checks** - Cron job for periodic monitoring  

---

## Related

- **`scripts/setup_multiple_ngrok_tunnels.sh`** - Setup script
- **`scripts/check_tunnel_consistency.sh`** - Consistency checker
- **`docs/operations/NGROK_TUNNEL_SETUP.md`** - Single tunnel setup
- **`docs/operations/NETWORK_ACCESS_STRATEGY.md`** - Network strategy

---

**Status: Ready for setup - Run scripts when SSH access is available**
