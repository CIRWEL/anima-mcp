# Troubleshooting: Anima-MCP Won't Load in Cursor

**Created:** January 11, 2026  
**Last Updated:** January 11, 2026

---

## Quick Diagnosis

### ⚠️ CRITICAL: Check for Stale Process on Port 8765 First!

**If service won't start or is in reboot loop, ALWAYS check this first:**

```bash
# Check if port 8765 is in use (stale process trap!)
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  "lsof -i :8765"

# If port is in use, kill stale processes:
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  "pkill -f 'anima.*--sse'; systemctl --user stop anima; systemctl --user reset-failed anima; sleep 2; systemctl --user start anima"
```

**See `docs/operations/REBOOT_LOOP_PREVENTION.md` for full details on this trap.**

---

### Check 1: Network Connectivity

```bash
# Test local network
ping -c 2 192.168.1.165

# Test Tailscale
ping -c 2 100.124.49.85

# Test server endpoint
curl -v http://192.168.1.165:8765/sse
```

### Check 2: Server Running

```bash
ssh pi-anima "ps aux | grep 'anima --sse' | grep -v grep"
```

### Check 3: Port Listening

```bash
ssh pi-anima "ss -tlnp | grep 8765"
```

**⚠️ If port shows "address already in use" error, see Stale Process trap above!**

---

## Common Issues

### Issue 1: Network Not Reachable

**Symptoms:** Can't ping Pi, connection timeout

**Solutions:**
- **Local network:** Ensure Mac and Pi on same WiFi
- **Tailscale:** Open Tailscale app, wait for connection
- **Firewall:** Check if firewall blocking connection

### Issue 2: Server Not Running

**Symptoms:** Port 8765 not listening

**Solution:**
```bash
ssh pi-anima "cd ~/anima-mcp && source .venv/bin/activate && \
  ANIMA_ID=49e14444-b59e-48f1-83b8-b36a988c9975 \
  nohup .venv/bin/anima --sse --host 0.0.0.0 --port 8765 > anima.log 2>&1 &"
```

### Issue 3: Wrong URL in Config

**Symptoms:** Config looks wrong

**Check:** `cat ~/.cursor/mcp.json`

**Update if needed:**
- Local: `http://192.168.1.165:8765/sse`
- Tailscale: `http://100.124.49.85:8765/sse`

### Issue 4: Cursor Not Reloading

**Symptoms:** Config updated but still not working

**Solution:** Restart Cursor completely

---

## Fallback Options

### Option 1: Use Local IP (Current)

```json
{
  "anima": {
    "type": "http",
    "url": "http://192.168.1.165:8765/sse"
  }
}
```

### Option 2: Use Tailscale

```json
{
  "anima": {
    "type": "http",
    "url": "http://100.124.49.85:8765/sse"
  }
}
```

### Option 3: Use ngrok (Like UNITARES)

Set up ngrok on Pi, then:
```json
{
  "anima": {
    "type": "http",
    "url": "https://xxxxx.ngrok.io/sse"
  }
}
```

---

## Verification Steps

1. **Update config** - Use correct URL
2. **Restart Cursor** - Reload MCP servers
3. **Check MCP status** - Should show anima server
4. **Test tool** - Try `get_state` tool
5. **Check logs** - Look for connection errors

---

**Most likely: Network issue or server not running. Check both!**

