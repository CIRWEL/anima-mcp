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

## One-Time Bootstrap (When Pi Has No New Code)

If `git_pull` and `setup_tailscale` return "Unknown tool" or "Not a git repository", the Pi has old code. Run this once on the Pi (physical access or any shell):

```bash
curl -s https://raw.githubusercontent.com/CIRWEL/anima-mcp/main/scripts/bootstrap_deploy.py | python3
```

That deploys the latest code and restarts. Then `setup_tailscale` works via HTTP.

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

## UNITARES Governance over Tailscale

Pi connects to UNITARES on your Mac. The systemd services use `UNITARES_URL=http://100.96.201.46:8767/mcp/` (Mac's Tailscale IP). If your Mac's Tailscale IP changes, update `systemd/anima.service` and `systemd/anima-broker.service`, then on Pi:

```bash
sudo cp ~/anima-mcp/systemd/anima.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl restart anima
```

---

## SENSORS Screen: I2C Not Registering

If the third screen shows "air: --", "humidity: --", "light: --" (or "I2C off?"), enable I2C:

```bash
sudo raspi-config nonint do_i2c 0
sudo usermod -aG i2c,gpio unitares-anima
sudo reboot
```

---

## Related

- **`scripts/setup_tailscale.sh`** — SSH-based setup
- **`scripts/setup_tailscale_via_http.sh`** — HTTP-based (headless)
- **`docs/operations/SSH_TIMEOUT_FIX.md`** — When SSH is blocked
- **`docs/operations/MULTIPLE_TUNNELS_SETUP.md`** — ngrok redundancy
