# Fix Git Pull on Pi - Local Changes Blocking Pull

**Created:** February 3, 2026  
**Status:** Ready to execute when Pi is accessible

---

## Problem

The Pi has local uncommitted changes in these files blocking `git pull`:
- `screens.py`
- `messages.py`
- `next_steps_advocate.py`
- `server.py`

These changes need to be stashed before pulling the latest fixes from GitHub.

---

## Solution Options

### Option A: Via SSH (When SSH is working)

**Quick method:**
```bash
ssh unitares-anima@lumen.local "cd ~/anima-mcp && git stash push -m 'Local changes before sync' && git pull origin main && sudo systemctl restart anima.service"
```

**Or use the provided script:**
```bash
# Copy script to Pi first, then:
ssh unitares-anima@lumen.local 'bash -s' < scripts/fix_git_pull_on_pi.sh
```

**Or SSH in and run manually:**
```bash
ssh unitares-anima@lumen.local
cd ~/anima-mcp
git status
git diff --stat
git stash push -m "Local changes before sync"
git pull origin main
sudo systemctl restart anima.service
sudo systemctl restart anima-broker.service
```

---

### Option B: Via HTTP/MCP (When HTTP is accessible)

**Using the Python script:**
```bash
# From Mac, if Pi HTTP endpoint is accessible:
python3 scripts/call_git_pull_via_http.py --url http://192.168.1.165:8766/mcp/ --stash --restart
```

**Or via curl:**
```bash
curl -X POST http://192.168.1.165:8766/mcp/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "git_pull",
      "arguments": {
        "stash": true,
        "restart": true
      }
    },
    "id": 1
  }'
```

**Note:** The `git_pull` tool now supports `stash` and `force` parameters (schema updated). The implementation already supported these, but now they're properly exposed in the schema.

---

### Option C: Commit Changes to New Branch (If changes are valuable)

If the local changes are valuable and should be preserved:

```bash
ssh unitares-anima@lumen.local
cd ~/anima-mcp
git status
git diff  # Review changes
git checkout -b pi-local-changes-$(date +%Y%m%d)
git add .
git commit -m "Local Pi changes before sync"
git push origin pi-local-changes-$(date +%Y%m%d)
git checkout main
git pull origin main
sudo systemctl restart anima.service
```

---

## What Was Fixed

1. ✅ **Updated `git_pull` tool schema** to expose `stash` and `force` parameters
   - File: `src/anima_mcp/server.py`
   - The implementation already supported these, but they weren't in the schema

2. ✅ **Created helper scripts:**
   - `scripts/fix_git_pull_on_pi.sh` - Bash script for SSH execution
   - `scripts/call_git_pull_via_http.py` - Python script for HTTP/MCP calls

---

## After Pulling

Once the pull succeeds, the Pi will have:
- ✅ Streamable HTTP `json_response=True` fix
- ✅ `git_pull` stash option properly exposed
- ✅ Latest fixes from GitHub

The `mcp__anima__*` tools will then work properly with Claude Code.

---

## Troubleshooting

### SSH Not Working
- Check Pi is powered on and on network
- Try: `ping lumen.local` or `ping 192.168.1.165`
- Check SSH service: `ssh unitares-anima@lumen.local 'systemctl status ssh'`

### HTTP Not Working
- Check anima service is running: `ssh unitares-anima@lumen.local 'systemctl status anima'`
- Check port 8766 is open: `curl http://192.168.1.165:8766/mcp/`
- Check firewall: `ssh unitares-anima@lumen.local 'sudo ufw status'`

### Git Pull Fails
- Check git remote: `git remote -v`
- Check network connectivity: `ping github.com`
- Check credentials: `git config --list | grep credential`

---

## Next Steps

1. **When Pi becomes accessible** (SSH or HTTP):
   - Run Option A (SSH) or Option B (HTTP) above
   - Verify pull succeeded: `git log -1`
   - Verify services restarted: `systemctl status anima anima-broker`

2. **Verify fixes are applied:**
   - Check `git_pull` tool now shows `stash` parameter in schema
   - Test MCP tools work properly

3. **If local changes were valuable:**
   - Review stashed changes: `git stash list` and `git stash show -p stash@{0}`
   - Consider applying selectively: `git stash pop` or `git stash apply`

---

*Last updated: February 3, 2026*
