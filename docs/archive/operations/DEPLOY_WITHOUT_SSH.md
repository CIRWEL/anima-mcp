# Deploy Without SSH

**Created:** February 3, 2026  
**Purpose:** Deploy code to Pi when SSH is not available

---

## Current Situation

✅ **Changes committed and pushed to git**  
✅ **Pi is reachable via HTTP** (MCP server running)  
❌ **SSH not working** (timeout on port 22)  
❌ **git_pull tool not available** (Pi running older server version)

---

## Deployment Options

### Option 1: Git Pull on Pi (Recommended if Pi has git access)

If the Pi can access the git repository, you can trigger a git pull:

**Via MCP (if git_pull tool becomes available after server update):**
```bash
curl -X POST http://192.168.1.165:8766/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"git_pull","arguments":{"restart":true}},"id":1}'
```

**Manual git pull (if you can access Pi another way):**
```bash
# On Pi
cd ~/anima-mcp
git pull origin main
sudo systemctl restart anima
sudo systemctl restart anima-broker
```

---

### Option 2: Wait for SSH Fix

Once SSH is working again, use standard deployment:
```bash
./deploy.sh
```

**To troubleshoot SSH:**
- Check Pi's SSH config: `/etc/ssh/sshd_config`
- Check firewall: `sudo ufw status`
- Check SSH logs: `sudo journalctl -u ssh -n 50`

---

### Option 3: Manual File Copy (If you have any Pi access)

If you can access the Pi through any method (direct access, VNC, etc.):

1. **Copy changed files manually:**
   ```bash
   # Key files that changed:
   - src/anima_mcp/server.py
   - src/anima_mcp/display/renderer.py
   - src/anima_mcp/display/screens.py
   - src/anima_mcp/growth.py
   - src/anima_mcp/identity/store.py
   - src/anima_mcp/llm_gateway.py
   - src/anima_mcp/messages.py
   - src/anima_mcp/metacognition.py
   - src/anima_mcp/self_schema.py
   - scripts/message_server.py
   - scripts/alert_check.sh
   ```

2. **Restart services:**
   ```bash
   sudo systemctl restart anima-broker
   sudo systemctl restart anima
   ```

---

## What Was Deployed

**Commit:** `53116b2` - "Claude's fixes: display improvements, growth system, identity updates"

**Changes:**
- Display improvements (renderer.py, screens.py)
- Growth system enhancements (growth.py)
- Identity store updates (identity/store.py)
- Message system improvements (messages.py)
- Self-schema updates (self_schema.py)
- LLM gateway updates (llm_gateway.py)
- Metacognition updates (metacognition.py)
- Server improvements (server.py)
- Script updates (message_server.py, alert_check.sh)

**Files changed:** 20 files, 1722 insertions(+), 522 deletions(-)

---

## Next Steps

1. **Try git pull on Pi** (if git access works)
2. **Fix SSH** (check SSH config, firewall, logs)
3. **Use standard deploy** once SSH works: `./deploy.sh`

---

## Status

✅ **Code ready** - Committed and pushed to git  
⏳ **Waiting for deployment** - Need SSH or git access on Pi  
📝 **Documented** - This guide tracks deployment status

---

**Last Updated:** February 3, 2026
