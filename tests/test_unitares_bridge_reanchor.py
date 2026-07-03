"""Tests for the governance identity anchor / re-anchor loop (anima-mcp #97).

The 2026-06-30 incident: a server-side session-store wipe left the echo-only
bridge permanently identity-refused, and the typed refusal payload (no
success:false, no action) parsed as a silent default-"proceed". These tests pin
both fixes: refusal detection, and the harvest-while-healthy /
spend-during-recovery anchor loop.
"""

import json
import time
from unittest.mock import AsyncMock, patch

import pytest

from anima_mcp.unitares_bridge import IdentityRefusedError, UnitaresBridge
from tests.test_unitares_bridge import _mock_http_response, create_test_anima, create_test_readings

ANIMA_ID = "49e14444-b59e-48f1-83b8-b36a988c9975"
GOV_UUID = "69a1a4f7-a30f-4f4a-bcf9-2de8606fb819"


def make_bridge(tmp_path, with_anchor=False, anchor_age_s=0.0):
    anchor_path = tmp_path / "gov_identity.json"
    if with_anchor:
        anchor_path.write_text(json.dumps({
            "uuid": GOV_UUID,
            "continuity_token": "v1.token",
            "client_session_id": f"lumen-{ANIMA_ID}",
            "saved_at": time.time() - anchor_age_s,
        }))
    with patch.dict("os.environ", {"ANIMA_GOV_ANCHOR_PATH": str(anchor_path)}):
        bridge = UnitaresBridge(unitares_url="http://test:8767/mcp/", agent_id=ANIMA_ID)
    return bridge, anchor_path


def _mcp_body(payload: dict) -> str:
    """Wrap a tool payload the way the MCP server does (content[0].text)."""
    return json.dumps({
        "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}
    })


REFUSAL_PAYLOAD = {
    "status": "identity_required",
    "tool": "process_agent_update",
    "hint": "This tool works once you have a governance identity",
}


def _mock_session(bodies):
    """Session whose successive POSTs return the given JSON bodies."""
    session = AsyncMock()
    session.post = lambda *a, **k: _mock_http_response(body=bodies.pop(0))
    return session


# ---------------------------------------------------------------------------
# Refusal detection (the silent-"proceed" bug)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_typed_refusal_raises_not_proceed(tmp_path):
    """status=identity_required must raise, never parse as default proceed."""
    bridge, _ = make_bridge(tmp_path)
    session = _mock_session([_mcp_body(REFUSAL_PAYLOAD)])
    with patch.object(bridge, "_get_session", AsyncMock(return_value=session)):
        with pytest.raises(IdentityRefusedError):
            await bridge._call_unitares(create_test_anima(), create_test_readings(), _eisv())


def _eisv():
    from anima_mcp.eisv_mapper import anima_to_eisv
    return anima_to_eisv(create_test_anima(), create_test_readings(), 0.3, 0.7)


# ---------------------------------------------------------------------------
# check_in recovery flow
# ---------------------------------------------------------------------------

def _flow_bridge(tmp_path, **kw):
    bridge, anchor_path = make_bridge(tmp_path, **kw)
    bridge.check_availability = AsyncMock(return_value=True)
    return bridge, anchor_path


@pytest.mark.asyncio
async def test_refusal_without_anchor_falls_back_local(tmp_path):
    bridge, _ = _flow_bridge(tmp_path, with_anchor=False)
    with patch.object(bridge, "_call_unitares", AsyncMock(side_effect=IdentityRefusedError("refused"))):
        result = await bridge.check_in(create_test_anima(), create_test_readings())
    assert result["source"] == "local"


@pytest.mark.asyncio
async def test_refusal_with_anchor_reanchors_and_retries(tmp_path):
    bridge, _ = _flow_bridge(tmp_path, with_anchor=True)
    ok = {"action": "proceed", "margin": "comfortable", "reason": "ok",
          "eisv": {}, "source": "unitares", "unitares_agent_id": GOV_UUID, "raw_response": {}}
    call_unitares = AsyncMock(side_effect=[IdentityRefusedError("refused"), ok])
    reanchor_resp = {"uuid": GOV_UUID, "continuity_token": "v1.fresh"}
    with patch.object(bridge, "_call_unitares", call_unitares), \
         patch.object(bridge, "_call_identity_tool", AsyncMock(return_value=reanchor_resp)) as ident:
        result = await bridge.check_in(create_test_anima(), create_test_readings())
    assert result["source"] == "unitares"
    assert call_unitares.call_count == 2
    args = ident.call_args[0][0]
    assert args["agent_uuid"] == GOV_UUID
    assert args["resume"] is True
    assert args["client_session_id"] == f"lumen-{ANIMA_ID}"
    # fresh token persisted
    assert bridge._anchor["continuity_token"] == "v1.fresh"


@pytest.mark.asyncio
async def test_reanchor_uuid_mismatch_refused(tmp_path):
    """Resolving to a DIFFERENT uuid must not be accepted as recovery."""
    bridge, _ = _flow_bridge(tmp_path, with_anchor=True)
    with patch.object(bridge, "_call_unitares", AsyncMock(side_effect=IdentityRefusedError("refused"))), \
         patch.object(bridge, "_call_identity_tool", AsyncMock(return_value={"uuid": "someone-else"})):
        result = await bridge.check_in(create_test_anima(), create_test_readings())
    assert result["source"] == "local"


@pytest.mark.asyncio
async def test_reanchor_rate_limited(tmp_path):
    bridge, _ = _flow_bridge(tmp_path, with_anchor=True)
    ident = AsyncMock(return_value={"uuid": "someone-else"})  # always fails
    with patch.object(bridge, "_call_unitares", AsyncMock(side_effect=IdentityRefusedError("refused"))), \
         patch.object(bridge, "_call_identity_tool", ident):
        await bridge.check_in(create_test_anima(), create_test_readings())
        await bridge.check_in(create_test_anima(), create_test_readings())
    assert ident.call_count == 1  # second refusal inside cooldown: no new attempt


# ---------------------------------------------------------------------------
# Harvest while healthy
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_harvest_after_healthy_checkin_persists_anchor(tmp_path):
    bridge, anchor_path = _flow_bridge(tmp_path, with_anchor=False)
    ok = {"action": "proceed", "margin": "comfortable", "reason": "ok",
          "eisv": {}, "source": "unitares", "unitares_agent_id": GOV_UUID, "raw_response": {}}
    ident_resp = {"uuid": GOV_UUID, "continuity_token": "v1.harvested"}
    with patch.object(bridge, "_call_unitares", AsyncMock(return_value=ok)), \
         patch.object(bridge, "_call_identity_tool", AsyncMock(return_value=ident_resp)):
        result = await bridge.check_in(create_test_anima(), create_test_readings())
    assert result["source"] == "unitares"
    saved = json.loads(anchor_path.read_text())
    assert saved["uuid"] == GOV_UUID
    assert saved["continuity_token"] == "v1.harvested"


@pytest.mark.asyncio
async def test_fresh_anchor_not_reharvested(tmp_path):
    bridge, _ = _flow_bridge(tmp_path, with_anchor=True, anchor_age_s=60.0)
    ok = {"action": "proceed", "margin": "comfortable", "reason": "ok",
          "eisv": {}, "source": "unitares", "unitares_agent_id": GOV_UUID, "raw_response": {}}
    with patch.object(bridge, "_call_unitares", AsyncMock(return_value=ok)), \
         patch.object(bridge, "_call_identity_tool", AsyncMock()) as ident:
        await bridge.check_in(create_test_anima(), create_test_readings())
    ident.assert_not_called()


@pytest.mark.asyncio
async def test_stale_anchor_reharvested(tmp_path):
    bridge, _ = _flow_bridge(tmp_path, with_anchor=True, anchor_age_s=25 * 3600)
    ok = {"action": "proceed", "margin": "comfortable", "reason": "ok",
          "eisv": {}, "source": "unitares", "unitares_agent_id": GOV_UUID, "raw_response": {}}
    with patch.object(bridge, "_call_unitares", AsyncMock(return_value=ok)), \
         patch.object(bridge, "_call_identity_tool",
                      AsyncMock(return_value={"uuid": GOV_UUID, "continuity_token": "v1.rotated"})):
        await bridge.check_in(create_test_anima(), create_test_readings())
    assert bridge._anchor["continuity_token"] == "v1.rotated"


def test_anchor_roundtrip(tmp_path):
    bridge, anchor_path = make_bridge(tmp_path)
    bridge._save_anchor(GOV_UUID, "v1.tok")
    assert anchor_path.exists()
    with patch.dict("os.environ", {"ANIMA_GOV_ANCHOR_PATH": str(anchor_path)}):
        again = UnitaresBridge(unitares_url="http://test:8767/mcp/", agent_id=ANIMA_ID)
    assert again._anchor["uuid"] == GOV_UUID


def test_corrupt_anchor_ignored(tmp_path):
    anchor_path = tmp_path / "gov_identity.json"
    anchor_path.write_text("{not json")
    with patch.dict("os.environ", {"ANIMA_GOV_ANCHOR_PATH": str(anchor_path)}):
        bridge = UnitaresBridge(unitares_url="http://test:8767/mcp/", agent_id=ANIMA_ID)
    assert bridge._anchor is None
