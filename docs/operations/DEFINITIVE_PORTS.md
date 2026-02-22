# Definitive Ports

**Single source of truth for anima-mcp and related services.** When changing a port, update this file and all references below.

**Last Updated:** February 21, 2026

---

## Ports

| Service | Port | Where used |
|--------|------|------------|
| **anima-mcp** (Lumen MCP server) | **8766** | Pi systemd, Cursor `mcp.json`, scripts, README |
| **UNITARES governance** (Mac/local) | **8767** | `UNITARES_URL` in anima.service, broker, Cursor governance server |

---

## anima-mcp = 8766

- **systemd:** `systemd/anima.service` — `ExecStartPre` (fuser) and `ExecStart` (--port)
- **Code default:** `src/anima_mcp/server.py` — `--port` default 8766
- **Cursor:** `~/.cursor/mcp.json` — anima server URL `http://<Pi-IP>:8766/mcp/`
- **Scripts:** Any script that builds the Pi URL (e.g. `alert_check.sh`, `message_server.py`, `monitor_health_pi.sh`, `deploy_via_http.sh`, `call_git_pull_via_http.py`) — use 8766 or reference this doc

**Endpoints on 8766:**
- `/mcp/` — Streamable HTTP MCP transport (OAuth 2.1 required via ngrok; open on LAN/Tailscale)
- `/health`, `/health/detailed` — Health checks
- `/dashboard`, `/gallery-page`, `/architecture` — Web UI pages
- `/state`, `/qa`, `/answer`, `/message`, `/messages`, `/learning`, `/voice` — REST API
- `/gallery`, `/gallery/{file}` — Drawing gallery
- `/layers` — Proprioception stack
- `/v1/tools/call` — Direct MCP tool call

**OAuth 2.1 endpoints** (active when `ANIMA_OAUTH_ISSUER_URL` is set):
- `/.well-known/oauth-authorization-server` — Server metadata
- `/.well-known/oauth-protected-resource/mcp` — Protected resource metadata
- `/register` — Dynamic client registration
- `/authorize` — Authorization (PKCE, auto-approve)
- `/token` — Token exchange
- `/revoke` — Token revocation

OAuth only enforced when Host = `lumen-anima.ngrok.io`. All other hosts bypass auth.

---

## UNITARES = 8767

- **Pi → Mac:** `UNITARES_URL` in `systemd/anima.service` and `systemd/anima-broker.service` (e.g. `http://100.96.201.46:8767/mcp/`)
- **Cursor:** `~/.cursor/mcp.json` — unitares-governance URL `http://localhost:8767/mcp/`

---

## If you change a port

1. Edit this file.
2. Update `systemd/anima.service` (both fuser and ExecStart) for anima.
3. Update Cursor `mcp.json` if the URL changes.
4. Grep for the old port: `rg '8766|8767' --glob '!*.json' .` and fix any script/docs that still use the old value.
