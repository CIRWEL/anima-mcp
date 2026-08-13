"""Tests for destructive-handler admin gate.

The gate fails CLOSED when ANIMA_ADMIN_SECRET is unset: an unauthenticated
caller cannot reach a destructive handler just because the server forgot its
secret. `ANIMA_ADMIN_ALLOW_UNAUTH_IF_NO_SECRET=true` is the explicit opt-out.
When the secret is set, handlers like handle_git_pull and handle_system_power
must see it in the ContextVar populated from X-Anima-Admin.
"""
from __future__ import annotations

import pytest

from anima_mcp.admin_auth import require_admin, set_admin_header


@pytest.fixture(autouse=True)
def _reset_header(monkeypatch):
    # The opt-out must never leak in from the ambient environment, or a
    # developer machine that sets it would silently relax these tests.
    monkeypatch.delenv("ANIMA_ADMIN_ALLOW_UNAUTH_IF_NO_SECRET", raising=False)
    set_admin_header(None)
    yield
    set_admin_header(None)


class TestNoSecretConfigured:
    """Unset secret means the gate cannot authenticate anyone, so it denies."""

    def test_no_env_no_header_is_denied(self, monkeypatch):
        monkeypatch.delenv("ANIMA_ADMIN_SECRET", raising=False)
        result = require_admin()
        assert result is not None
        assert "ANIMA_ADMIN_SECRET is not set" in result[0].text

    def test_no_env_with_header_is_still_denied(self, monkeypatch):
        # A caller-supplied header cannot substitute for server config.
        monkeypatch.delenv("ANIMA_ADMIN_SECRET", raising=False)
        set_admin_header("anything")
        assert require_admin() is not None

    def test_empty_secret_is_treated_as_unset(self, monkeypatch):
        monkeypatch.setenv("ANIMA_ADMIN_SECRET", "")
        assert require_admin() is not None

    def test_error_names_the_explicit_opt_out(self, monkeypatch):
        monkeypatch.delenv("ANIMA_ADMIN_SECRET", raising=False)
        result = require_admin()
        assert "ANIMA_ADMIN_ALLOW_UNAUTH_IF_NO_SECRET" in result[0].text


class TestExplicitUnauthOptOut:
    """The escape hatch restores the old permissive behavior, loudly."""

    @pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes"])
    def test_opt_out_allows_when_no_secret(self, monkeypatch, value):
        monkeypatch.delenv("ANIMA_ADMIN_SECRET", raising=False)
        monkeypatch.setenv("ANIMA_ADMIN_ALLOW_UNAUTH_IF_NO_SECRET", value)
        assert require_admin() is None

    @pytest.mark.parametrize("value", ["false", "0", "no", ""])
    def test_non_affirmative_values_do_not_opt_out(self, monkeypatch, value):
        monkeypatch.delenv("ANIMA_ADMIN_SECRET", raising=False)
        monkeypatch.setenv("ANIMA_ADMIN_ALLOW_UNAUTH_IF_NO_SECRET", value)
        assert require_admin() is not None

    def test_opt_out_does_not_bypass_a_configured_secret(self, monkeypatch):
        # Opting out is about the *absence* of a secret. It must never let a
        # wrong header through when one is configured.
        monkeypatch.setenv("ANIMA_ADMIN_SECRET", "shh")
        monkeypatch.setenv("ANIMA_ADMIN_ALLOW_UNAUTH_IF_NO_SECRET", "true")
        set_admin_header("wrong")
        assert require_admin() is not None


class TestSecretConfigured:
    def test_missing_header_returns_error(self, monkeypatch):
        monkeypatch.setenv("ANIMA_ADMIN_SECRET", "shh")
        result = require_admin()
        assert result is not None
        assert "X-Anima-Admin" in result[0].text

    def test_wrong_header_returns_error(self, monkeypatch):
        monkeypatch.setenv("ANIMA_ADMIN_SECRET", "shh")
        set_admin_header("wrong")
        assert require_admin() is not None

    def test_matching_header_passes(self, monkeypatch):
        monkeypatch.setenv("ANIMA_ADMIN_SECRET", "shh")
        set_admin_header("shh")
        assert require_admin() is None

    def test_empty_header_does_not_satisfy_secret(self, monkeypatch):
        monkeypatch.setenv("ANIMA_ADMIN_SECRET", "shh")
        set_admin_header("")
        assert require_admin() is not None

    def test_header_that_is_a_prefix_of_the_secret_is_rejected(self, monkeypatch):
        # Guards the constant-time comparison against a length-only check.
        monkeypatch.setenv("ANIMA_ADMIN_SECRET", "correct-horse")
        set_admin_header("correct")
        assert require_admin() is not None

    def test_non_ascii_header_does_not_raise(self, monkeypatch):
        # hmac.compare_digest rejects non-ASCII str operands with TypeError;
        # a hostile header must be a clean denial, not a 500.
        monkeypatch.setenv("ANIMA_ADMIN_SECRET", "shh")
        set_admin_header("shhé")
        assert require_admin() is not None


class TestHandlerIntegration:
    async def test_system_power_blocked_without_header(self, monkeypatch):
        monkeypatch.setenv("ANIMA_ADMIN_SECRET", "shh")
        from anima_mcp.handlers.system_ops import handle_system_power
        result = await handle_system_power({"action": "status"})
        assert "X-Anima-Admin" in result[0].text

    async def test_system_power_allowed_with_matching_header(self, monkeypatch):
        monkeypatch.setenv("ANIMA_ADMIN_SECRET", "shh")
        set_admin_header("shh")
        from anima_mcp.handlers.system_ops import handle_system_power
        result = await handle_system_power({"action": "status"})
        assert "X-Anima-Admin" not in result[0].text

    async def test_system_power_blocked_when_secret_unset(self, monkeypatch):
        monkeypatch.delenv("ANIMA_ADMIN_SECRET", raising=False)
        monkeypatch.delenv("ANIMA_ADMIN_ALLOW_UNAUTH_IF_NO_SECRET", raising=False)
        from anima_mcp.handlers.system_ops import handle_system_power
        result = await handle_system_power({"action": "status"})
        assert "ANIMA_ADMIN_SECRET is not set" in result[0].text
