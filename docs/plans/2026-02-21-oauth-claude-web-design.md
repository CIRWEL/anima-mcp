# OAuth 2.1 for Claude.ai Custom MCP Connector

**Date:** 2026-02-21
**Status:** Approved
**Applies to:** anima-mcp (primary), governance-mcp (follow-up)

## Problem

Claude.ai's "Integrations" (custom MCP connectors) require remote servers to implement OAuth 2.1. Both anima-mcp (`lumen-anima.ngrok.io`) and governance-mcp (`unitares.ngrok.io`) currently lack OAuth, so Claude.ai cannot connect to them.

## Constraints

- Dashboard, gallery, REST endpoints must remain publicly accessible (no auth)
- Single-user personal server — simplicity over enterprise features
- Must work behind ngrok tunnel
- Stdio transport unaffected (local, no auth needed)
- Existing `UNITARES_AUTH` basic auth for ngrok remains as outer layer

## Design

### Architecture

```
Claude.ai
  │
  ├─ GET /.well-known/oauth-protected-resource
  │   → { resource: "https://lumen-anima.ngrok.io/mcp",
  │        authorization_servers: ["https://lumen-anima.ngrok.io"] }
  │
  ├─ GET /.well-known/oauth-authorization-server
  │   → { issuer, authorization_endpoint, token_endpoint,
  │        registration_endpoint, code_challenge_methods_supported }
  │
  ├─ POST /register  (Dynamic Client Registration)
  │   → { client_id, client_secret }
  │
  ├─ GET /authorize  (auto-approves when ANIMA_OAUTH_AUTO_APPROVE=true)
  │   → 302 redirect to callback with ?code=...
  │
  ├─ POST /token  (exchange code for access_token)
  │   → { access_token, refresh_token, expires_in }
  │
  └─ POST /mcp  (existing endpoint, now validates Bearer token)
      Authorization: Bearer <access_token>

Dashboard, /health, /state, /qa, /gallery, etc. → UNPROTECTED (no change)
```

### New File: `src/anima_mcp/oauth_provider.py`

Implements the MCP SDK's `OAuthAuthorizationServerProvider` protocol:

- `get_client()` / `register_client()` — dynamic client registration
- `authorize()` — auto-approve or HTML consent page
- `exchange_authorization_code()` — code → access + refresh tokens
- `exchange_refresh_token()` — refresh flow
- `load_access_token()` / `load_authorization_code()` / `load_refresh_token()` — lookups
- `revoke_token()` — revocation

**Storage:** In-memory Python dicts. Tokens reset on server restart (Claude.ai re-authenticates automatically — ~2 second delay).

**Token signing:** `ANIMA_OAUTH_SECRET` env var. Falls back to random secret on startup.

**Token lifetimes:**
- Authorization codes: 5 minutes
- Access tokens: 1 hour
- Refresh tokens: 7 days

### Changes to `tool_registry.py`

Pass `auth_server_provider` and `AuthSettings` to FastMCP constructor:

```python
from mcp.server.auth.provider import OAuthAuthorizationServerProvider
from mcp.server.auth.settings import AuthSettings
from .oauth_provider import AnimaOAuthProvider

oauth_provider = AnimaOAuthProvider()

_fastmcp = FastMCP(
    name="anima-mcp",
    host="0.0.0.0",
    auth_server_provider=oauth_provider,
    auth=AuthSettings(
        issuer_url=OAUTH_ISSUER_URL,
        resource_server_url=OAUTH_ISSUER_URL,
    ),
    transport_security=TransportSecuritySettings(...),  # existing
)
```

### Changes to `server.py`

In the manually-built Starlette app (~line 3250):

1. **Import auth routes** from `mcp.server.auth.routes.create_auth_routes()`
2. **Import auth middleware** (`BearerAuthBackend`, `RequireAuthMiddleware`, `AuthContextMiddleware`)
3. **Wrap `/mcp` mount** with `RequireAuthMiddleware` (only when OAuth is configured)
4. **Add auth routes** (`/.well-known/*`, `/authorize`, `/token`, `/register`) to the Starlette routes list
5. **Add `AuthenticationMiddleware`** with `BearerAuthBackend` to the middleware stack
6. **Conditional:** Only enable OAuth when `ANIMA_OAUTH_ISSUER_URL` is set (graceful fallback for local dev)

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `ANIMA_OAUTH_SECRET` | random on startup | Token signing key |
| `ANIMA_OAUTH_ISSUER_URL` | (unset = OAuth disabled) | OAuth issuer URL, e.g. `https://lumen-anima.ngrok.io` |
| `ANIMA_OAUTH_AUTO_APPROVE` | `true` | Skip consent page for /authorize |

### Connection Flow

```
1. Claude.ai discovers OAuth metadata
   GET /.well-known/oauth-protected-resource
   GET /.well-known/oauth-authorization-server

2. Claude.ai registers itself
   POST /register → { client_id, client_secret }

3. Claude.ai initiates auth (PKCE)
   GET /authorize?client_id=...&redirect_uri=...&code_challenge=...&state=...
   ← 302 redirect with ?code=...&state=... (auto-approved)

4. Claude.ai exchanges code for token
   POST /token { grant_type: "authorization_code", code, code_verifier, ... }
   ← { access_token, refresh_token, token_type: "bearer", expires_in: 3600 }

5. Claude.ai uses MCP normally
   POST /mcp (Authorization: Bearer <token>)
   ← MCP tools work as before

6. Token refresh (automatic, every ~1 hour)
   POST /token { grant_type: "refresh_token", refresh_token }
   ← { new access_token, new refresh_token }
```

### What Stays the Same

- All dashboard/REST endpoints — open, no auth required
- Existing ngrok basic auth (`UNITARES_AUTH`) — still works as outer layer
- Existing `client_session_id` identity resolution — still works
- Stdio transport — unaffected
- Tool behavior — no changes to any tool handlers

### Follow-up

Apply the same pattern to governance-mcp. The `oauth_provider.py` module is portable — copy or extract to a shared package.
