# Cursor MCP Fix - Anima Blocking UNITARES

**Issue:** Adding anima-mcp caused both anima and unitares-governance to stop loading.

**Root Cause:** Cursor may fail to load all servers if one server fails to connect. Since anima's Pi isn't reachable, it blocks other servers.

**Fix Applied:** Temporarily removed anima from `~/.cursor/mcp.json` so UNITARES can load.

---

## Current Config

```json
{
  "mcpServers": {
    "GitHub": {...},
    "date-context": {...},
    "unitares-governance": {
      "type": "http",
      "url": "https://unitares.ngrok.io/mcp"
    }
  }
}
```

**Anima removed** until network connectivity is fixed.

---

## To Add Anima Back

When Pi is reachable:

1. **Test connection:**
   ```bash
   ping 192.168.1.165
   curl http://192.168.1.165:8765/sse
   ```

2. **Add to config:**
   ```json
   "anima": {
     "type": "http",
     "url": "http://192.168.1.165:8765/sse"
   }
   ```

3. **Restart Cursor**

---

## Alternative: Use ngrok

Set up ngrok on Pi (like UNITARES), then use ngrok URL instead of local IP.

---

**UNITARES should work now. Add anima back when network is available.**
