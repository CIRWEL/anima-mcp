"""Centralized context reference for the anima-mcp server.

Single source of truth for the ServerContext pointer. All modules that need
_ctx import from here instead of doing late imports from server.py.

Set by lifecycle.py during wake()/sleep(). Read by accessors.py, input_handler.py,
loop_phases.py, and server.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .server_context import ServerContext

_ctx: ServerContext | None = None


def get_ctx() -> ServerContext | None:
    """Return the current server context, or None if not yet woken."""
    return _ctx


def set_ctx(ctx: ServerContext | None) -> None:
    """Set the server context. Called by lifecycle.wake() and lifecycle.sleep()."""
    global _ctx
    _ctx = ctx
