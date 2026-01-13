# Cursor MCP Setup - Anima-MCP

**Created:** January 11, 2026  
**Last Updated:** January 11, 2026  
**Status:** Active

---

## Current Configuration

Anima-MCP is configured in `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "anima": {
      "type": "http",
      "url": "http://100.124.49.85:8765/sse"
    }
  }
}
```

**Issue:** Requires Tailscale to be running on Mac.

---

## Connection Options

### Option 1: Tailscale (Recommended)

**Requires:** Tailscale app running on Mac

1. **Open Tailscale app** on Mac
2. **Verify connection:** `ping 100.124.49.85`
3. **Restart Cursor** to reload MCP config

**Pi Tailscale IP:** `100.124.49.85`

### Option 2: Local Network

**Requires:** Mac and Pi on same network

1. **Find Pi IP:** Check router or use `arp -a`
2. **Update config:** Change URL to `http://192.168.1.165:8765/sse`
3. **Restart Cursor**

### Option 3: ngrok (Like UNITARES)

**Requires:** ngrok setup on Pi

1. **Set up ngrok** on Pi (similar to UNITARES)
2. **Update config:** Use ngrok URL
3. **Restart Cursor**

---

## Troubleshooting

### "Anima won't load"

**Check 1: Network connectivity**
```bash
# Test Tailscale
ping 100.124.49.85

# Test local network
ping 192.168.1.165

# Test server
curl http://100.124.49.85:8765/sse
```

**Check 2: Server running**
```bash
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  'systemctl --user status anima'
```

**Check 3: MCP config**
```bash
cat ~/.cursor/mcp.json | python3 -m json.tool
```

**Check 4: Cursor logs**
- Check Cursor's MCP connection logs
- Look for connection errors

---

## Quick Fixes

### If Tailscale Not Running

1. **Open Tailscale app** on Mac
2. **Wait for connection** (green indicator)
3. **Restart Cursor**

### If Server Not Running

```bash
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  'cd ~/anima-mcp && source .venv/bin/activate && \
   ANIMA_ID=49e14444-b59e-48f1-83b8-b36a988c9975 \
   nohup .venv/bin/anima --sse --host 0.0.0.0 --port 8765 > anima.log 2>&1 &'
```

### If Config Wrong

Update `~/.cursor/mcp.json` with correct URL:
- Tailscale: `http://100.124.49.85:8765/sse`
- Local: `http://192.168.1.165:8765/sse`
- ngrok: `https://xxxxx.ngrok.io/sse`

---

## Verification

After setup, verify anima-mcp loads:

1. **Restart Cursor**
2. **Check MCP status** - Should show anima server
3. **Try a tool** - `get_state` should work
4. **Check logs** - No connection errors

---

## Related

- **`CURSOR_HANDOFF.md`** - Full handoff guide
- **`operations/PI_ACCESS.md`** - SSH access details

---

**Most common issue: Tailscale not running on Mac. Open the app and restart Cursor.**

