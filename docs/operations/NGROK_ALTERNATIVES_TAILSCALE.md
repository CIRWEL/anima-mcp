# Ngrok Alternatives: Tailscale (When at 100% Usage)

**Created:** February 11, 2026  
**Last Updated:** February 11, 2026  
**Purpose:** Use Tailscale when ngrok hits limits — no usage caps, free tier.

---

## Why Tailscale?

| | ngrok | Tailscale |
|--|-------|-----------|
| Usage limits | Free tier: 40 connections/min, monthly caps | **No limits** on free tier |
| Cost | Paid for higher limits | Free for personal use |
| Setup | Tunnels expose to internet | Mesh VPN, Pi gets 100.x.x.x |
| When ngrok is down | No alternative | **Activate via HTTP** without SSH |

---

## Quick Activate (Headless, via HTTP)

When ngrok is at 100% and you can't SSH:

1. **Get auth key:** https://login.tailscale.com/admin/settings/keys (reusable, 90 days)

2. **Run from Mac** (Pi HTTP must be reachable):
   ```bash
   TAILSCALE_AUTH_KEY=tskey-auth-xxx ./scripts/setup_tailscale_via_http.sh
   ```

3. **Update Cursor MCP** (`~/.cursor/mcp.json`):
   ```json
   {
     "mcpServers": {
       "anima": {
         "type": "http",
         "url": "http://100.x.x.x:8766/mcp/"
       }
     }
   }
   ```
   Use the `tailscale_ip` from the script output.

---

## With SSH Access

```bash
TAILSCALE_AUTH_KEY=tskey-auth-xxx ./scripts/setup_tailscale.sh
```

---

## MCP Tool (Call via HTTP)

If the script isn't handy, call the tool directly:

```bash
curl -s -X POST http://192.168.1.165:8766/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{"name":"setup_tailscale","arguments":{"auth_key":"tskey-auth-xxx"}}'
```

---

## Related

- **`scripts/setup_tailscale.sh`** — SSH-based setup
- **`scripts/setup_tailscale_via_http.sh`** — HTTP-based (headless)
- **`docs/operations/SSH_TIMEOUT_FIX.md`** — When SSH is blocked
- **`docs/operations/MULTIPLE_TUNNELS_SETUP.md`** — ngrok redundancy
