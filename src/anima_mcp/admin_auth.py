"""Admin-secret gate for destructive MCP handlers.

Destructive handlers (git_pull, system_power, system_service, fix_ssh_port,
deploy_from_github, setup_tailscale) can reboot the Pi or modify system
state. A typo'd URL or misconfigured agent could trigger them by accident.

Gating: requests to destructive handlers must include an `X-Anima-Admin`
header matching `ANIMA_ADMIN_SECRET`.

**When the secret is unset the gate fails CLOSED** — destructive handlers
refuse rather than run ungated. This used to be a no-op for backward
compatibility, and that default was reachable by accident: `anima.env` is
deliberately excluded from backups (it holds secrets), `restore_lumen.sh`
recreates it from `config/anima.env.example` when missing, and the unit file
uses `EnvironmentFile=-` so a file with no secret in it still starts the
service. A reflash therefore brought Lumen back with the gate silently
disabled and nothing saying so — a fail-open on the recovery path, in a
codebase whose stated invariant is to fail toward *unknown*, never toward
healthy.

`ANIMA_ADMIN_ALLOW_UNAUTH_IF_NO_SECRET=true` restores the old permissive
behavior for local development or a deliberate legacy deployment. It is an
explicit, greppable opt-in — the same shape as `ANIMA_ALLOW_FRESH_START`.

The ASGI layer reads the header and stashes it in a ContextVar so handlers
can consult it without knowing about the request pipeline.
"""
from __future__ import annotations

import hmac
import os
from contextvars import ContextVar

from mcp.types import TextContent

_admin_header_value: ContextVar[str | None] = ContextVar(
    "anima_admin_header", default=None
)


def set_admin_header(value: str | None) -> None:
    """Called by the ASGI layer with the raw X-Anima-Admin header value."""
    _admin_header_value.set(value)


def _unauth_allowed_without_secret() -> bool:
    """True when an operator has explicitly opted out of the closed default."""
    return os.environ.get(
        "ANIMA_ADMIN_ALLOW_UNAUTH_IF_NO_SECRET", ""
    ).strip().lower() in ("true", "1", "yes")


def _error(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


def require_admin() -> list[TextContent] | None:
    """Return an error response if the admin gate does not pass.

    Returns None when the check passes (header matches the configured
    secret, or an operator explicitly allowed unauthenticated use while no
    secret is configured). Returns a TextContent list when the handler
    should abort.
    """
    secret = os.environ.get("ANIMA_ADMIN_SECRET")
    if not secret:
        if _unauth_allowed_without_secret():
            return None
        return _error(
            "error: this operation is disabled because ANIMA_ADMIN_SECRET is "
            "not set on the server, so the admin gate cannot authenticate the "
            "caller. Set ANIMA_ADMIN_SECRET in ~/.anima/anima.env and restart "
            "anima.service. To intentionally run destructive handlers ungated "
            "(local development only), set "
            "ANIMA_ADMIN_ALLOW_UNAUTH_IF_NO_SECRET=true."
        )
    got = _admin_header_value.get()
    # Constant-time: a plain == leaks the shared secret's matching prefix
    # length through response timing. Compare as bytes — compare_digest
    # raises TypeError on non-ASCII str operands, and a hostile header must
    # produce a clean denial rather than a 500.
    if got and hmac.compare_digest(got.encode("utf-8"), secret.encode("utf-8")):
        return None
    return _error(
        "error: this operation requires the X-Anima-Admin header. "
        "Set it to the value of ANIMA_ADMIN_SECRET on the server."
    )
