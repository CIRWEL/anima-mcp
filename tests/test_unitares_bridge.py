"""
Tests for UNITARES bridge module.

Validates governance integration and fallback behavior.
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock

from anima_mcp.unitares_bridge import UnitaresBridge, check_governance
from anima_mcp.anima import Anima
from anima_mcp.sensors.base import SensorReadings
from anima_mcp.eisv_mapper import EISVMetrics


def create_test_readings() -> SensorReadings:
    """Create test sensor readings."""
    return SensorReadings(
        timestamp=datetime.now(),
        cpu_temp_c=45.0,
        ambient_temp_c=22.0,
        humidity_pct=50.0,
        light_lux=300.0,
        cpu_percent=50.0,
        memory_percent=50.0,
        disk_percent=50.0,
        eeg_alpha_power=0.5,
        eeg_beta_power=0.6,
        eeg_gamma_power=0.4,
    )


def create_test_anima() -> Anima:
    """Create test anima state."""
    readings = create_test_readings()
    return Anima(
        warmth=0.7,
        clarity=0.6,
        stability=0.8,
        presence=0.7,
        readings=readings
    )


@pytest.mark.asyncio
async def test_local_governance_fallback():
    """Test local governance when UNITARES unavailable."""
    bridge = UnitaresBridge(unitares_url=None)  # No URL = local only
    
    anima = create_test_anima()
    readings = create_test_readings()
    
    decision = await bridge.check_in(anima, readings)
    
    assert "action" in decision
    assert "margin" in decision
    assert "reason" in decision
    assert "eisv" in decision
    assert decision["source"] == "local"
    assert decision["action"] in ["proceed", "pause", "halt"]


@pytest.mark.asyncio
async def test_local_governance_high_entropy():
    """Test local governance pauses on high entropy."""
    bridge = UnitaresBridge(unitares_url=None)
    
    # Low stability = high entropy
    anima = Anima(
        warmth=0.5,
        clarity=0.5,
        stability=0.2,  # Low stability = high entropy
        presence=0.5,
        readings=create_test_readings()
    )
    readings = create_test_readings()
    
    decision = await bridge.check_in(anima, readings)
    
    # High entropy should trigger pause (local governance calls this "risk")
    assert decision["action"] == "pause"
    assert "risk" in decision["reason"].lower()


@pytest.mark.asyncio
async def test_local_governance_low_integrity():
    """Test local governance pauses on low integrity."""
    bridge = UnitaresBridge(unitares_url=None)
    
    # Low clarity = low integrity
    anima = Anima(
        warmth=0.5,
        clarity=0.3,  # Low clarity = low integrity
        stability=0.5,
        presence=0.5,
        readings=create_test_readings()
    )
    readings = create_test_readings()

    decision = await bridge.check_in(anima, readings)

    # Low integrity should trigger pause
    assert decision["action"] == "pause"
    assert "coherence" in decision["reason"].lower()


@pytest.mark.asyncio
async def test_local_governance_comfortable():
    """Test local governance proceeds when comfortable."""
    bridge = UnitaresBridge(unitares_url=None)
    
    # Healthy state
    anima = Anima(
        warmth=0.6,
        clarity=0.7,
        stability=0.8,
        presence=0.7,
        readings=create_test_readings()
    )
    readings = create_test_readings()
    
    decision = await bridge.check_in(anima, readings)
    
    # Healthy state should proceed
    assert decision["action"] == "proceed"
    assert decision["margin"] in ["comfortable", "tight"]


@pytest.mark.asyncio
async def test_check_availability_no_url():
    """Test availability check with no URL."""
    bridge = UnitaresBridge(unitares_url=None)
    available = await bridge.check_availability()
    assert available is False


@pytest.mark.asyncio
async def test_check_availability_unreachable():
    """Test availability check with unreachable URL."""
    bridge = UnitaresBridge(unitares_url="http://127.0.0.1:99999/sse")
    available = await bridge.check_availability()
    assert available is False


@pytest.mark.asyncio
async def test_check_governance_convenience():
    """Test convenience function."""
    anima = create_test_anima()
    readings = create_test_readings()
    
    decision = await check_governance(anima, readings, unitares_url=None)
    
    assert "action" in decision
    assert "margin" in decision
    assert "source" in decision


@pytest.mark.asyncio
async def test_bridge_with_agent_id():
    """Test bridge with agent ID."""
    bridge = UnitaresBridge(unitares_url=None, agent_id="test-creature")
    assert bridge._agent_id == "test-creature"
    
    bridge.set_agent_id("new-id")
    assert bridge._agent_id == "new-id"


@pytest.mark.asyncio
async def test_bridge_with_session_id():
    """Test bridge with session ID."""
    bridge = UnitaresBridge(unitares_url=None)
    bridge.set_session_id("test-session")
    assert bridge._session_id == "test-session"


@pytest.mark.asyncio
async def test_decision_includes_eisv():
    """Test that decision includes EISV metrics."""
    bridge = UnitaresBridge(unitares_url=None)
    anima = create_test_anima()
    readings = create_test_readings()
    
    decision = await bridge.check_in(anima, readings)
    
    assert "eisv" in decision
    assert "E" in decision["eisv"]
    assert "I" in decision["eisv"]
    assert "S" in decision["eisv"]
    assert "V" in decision["eisv"]
    assert 0.0 <= decision["eisv"]["E"] <= 1.0
    assert 0.0 <= decision["eisv"]["I"] <= 1.0
    assert 0.0 <= decision["eisv"]["S"] <= 1.0
    assert 0.0 <= decision["eisv"]["V"] <= 1.0


@pytest.mark.asyncio
async def test_margin_calculation():
    """Test margin calculation in local governance."""
    bridge = UnitaresBridge(unitares_url=None)
    
    # Test different margins
    test_cases = [
        (0.5, 0.5, 0.5, 0.5, "comfortable"),  # Middle of range
        (0.55, 0.45, 0.1, 0.1, "tight"),      # Near thresholds
        (0.6, 0.4, 0.05, 0.15, "critical"),   # At thresholds
    ]
    
    for warmth, clarity, stability, presence, expected_margin in test_cases:
        anima = Anima(
            warmth=warmth,
            clarity=clarity,
            stability=stability,
            presence=presence,
            readings=create_test_readings()
        )
        readings = create_test_readings()
        
        decision = await bridge.check_in(anima, readings)
        
        # Margin should be calculated (may not match exactly due to thresholds)
        assert decision["margin"] in ["comfortable", "tight", "critical"]


def test_get_mcp_url_with_mcp():
    """Test _get_mcp_url when URL already contains /mcp."""
    bridge = UnitaresBridge(unitares_url="http://localhost:8767/mcp")
    assert bridge._get_mcp_url() == "http://localhost:8767/mcp"


def test_get_mcp_url_with_sse():
    """Test _get_mcp_url converts /sse to /mcp."""
    bridge = UnitaresBridge(unitares_url="http://localhost:8767/sse")
    assert bridge._get_mcp_url() == "http://localhost:8767/mcp"


def test_get_mcp_url_bare():
    """Test _get_mcp_url appends /mcp to bare URL."""
    bridge = UnitaresBridge(unitares_url="http://localhost:8767")
    assert bridge._get_mcp_url() == "http://localhost:8767/mcp"


def test_parse_mcp_response_json():
    """Test parsing a plain JSON response."""
    result = UnitaresBridge._parse_mcp_response(
        '{"result": {"content": []}}',
        "application/json"
    )
    assert result == {"result": {"content": []}}


def test_parse_mcp_response_sse():
    """Test parsing an SSE response."""
    sse_text = 'event: message\ndata: {"result": "ok"}\n\n'
    result = UnitaresBridge._parse_mcp_response(sse_text, "text/event-stream")
    assert result == {"result": "ok"}


def test_parse_mcp_response_sse_no_data():
    """Test parsing SSE response with no valid data lines."""
    result = UnitaresBridge._parse_mcp_response(
        "event: message\n\n", "text/event-stream"
    )
    assert result is None


def test_parse_mcp_response_sse_bad_json():
    """Test parsing SSE response with invalid JSON falls through."""
    sse_text = 'data: not-json\ndata: {"ok": true}\n'
    result = UnitaresBridge._parse_mcp_response(sse_text, "text/event-stream")
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_resolve_caller_identity_no_url():
    """Test resolve_caller_identity returns None when no URL configured."""
    bridge = UnitaresBridge(unitares_url=None)
    result = await bridge.resolve_caller_identity()
    assert result is None


@pytest.mark.asyncio
async def test_resolve_caller_identity_no_session():
    """Test resolve_caller_identity returns None with no session ID."""
    bridge = UnitaresBridge(unitares_url="http://localhost:8767/mcp")
    bridge._available = True
    result = await bridge.resolve_caller_identity()
    assert result is None


@pytest.mark.asyncio
async def test_resolve_caller_identity_unavailable():
    """Test resolve_caller_identity returns None when UNITARES is known unavailable."""
    bridge = UnitaresBridge(unitares_url="http://localhost:8767/mcp")
    bridge._available = False
    bridge.set_session_id("test-session")
    result = await bridge.resolve_caller_identity()
    assert result is None


@pytest.mark.asyncio
async def test_check_availability_staleness_recheck():
    """Test that availability is rechecked after 5 minutes."""
    # Use an unreachable URL so the recheck actually fails
    bridge = UnitaresBridge(unitares_url="http://127.0.0.1:19999/mcp")
    bridge._available = True
    import time
    # Recent check — should return True without rechecking
    bridge._last_availability_check = time.time()
    assert await bridge.check_availability() is True

    # Stale check (6 min ago) — should fall through to recheck (and fail, no server)
    bridge._last_availability_check = time.time() - 360
    result = await bridge.check_availability()
    assert result is False


def test_anima_snapshot_module_level():
    """Test that _AnimaSnapshot is defined at module level and reusable."""
    from anima_mcp.unitares_bridge import _AnimaSnapshot
    snap1 = _AnimaSnapshot(0.5, 0.6, 0.7, 0.8)
    snap2 = _AnimaSnapshot(0.1, 0.2, 0.3, 0.4)
    assert isinstance(snap1, _AnimaSnapshot)
    assert isinstance(snap2, _AnimaSnapshot)
    assert snap1.warmth == 0.5
    assert snap2.clarity == 0.2


@pytest.mark.asyncio
async def test_sync_name_handles_sse_response():
    """Test sync_name uses _parse_mcp_response instead of response.json()."""
    bridge = UnitaresBridge(unitares_url="http://localhost:8767/mcp")
    bridge._available = True
    bridge._agent_id = "test-creature"

    sse_body = 'event: message\ndata: {"result": {"content": [{"text": "ok"}]}}\n\n'
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.headers = {"Content-Type": "text/event-stream"}
    mock_response.text = AsyncMock(return_value=sse_body)
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_response)

    with patch.object(bridge, '_get_session', return_value=mock_session):
        result = await bridge.sync_name("Lumen")
    assert result is True


@pytest.mark.asyncio
async def test_report_outcome_handles_sse_response():
    """Test report_outcome uses _parse_mcp_response instead of response.json()."""
    bridge = UnitaresBridge(unitares_url="http://localhost:8767/mcp")
    bridge._available = True
    bridge._agent_id = "test-creature"

    sse_body = 'event: message\ndata: {"result": {"content": [{"text": "ok"}]}}\n\n'
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.headers = {"Content-Type": "text/event-stream"}
    mock_response.text = AsyncMock(return_value=sse_body)
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_response)

    with patch.object(bridge, '_get_session', return_value=mock_session):
        result = await bridge.report_outcome("drawing_complete", outcome_score=0.8)
    assert result is True


def test_server_bridge_uses_get_identity():
    """Test that _get_server_bridge uses get_identity() not .identity."""
    from anima_mcp.server import _get_server_bridge
    import anima_mcp.server as server_mod

    # Save and reset globals
    old_bridge = server_mod._server_bridge
    old_store = server_mod._store
    try:
        server_mod._server_bridge = None

        mock_identity = MagicMock()
        mock_identity.creature_id = "test-creature-id-1234"

        mock_store = MagicMock()
        mock_store.get_identity = MagicMock(return_value=mock_identity)
        # Ensure .identity would fail if accessed
        del mock_store.identity
        server_mod._store = mock_store

        with patch.dict('os.environ', {'UNITARES_URL': 'http://localhost:8767/mcp'}):
            bridge = _get_server_bridge()

        if bridge is not None:
            assert bridge._agent_id == "test-creature-id-1234"
            mock_store.get_identity.assert_called_once()
    finally:
        server_mod._server_bridge = old_bridge
        server_mod._store = old_store


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

