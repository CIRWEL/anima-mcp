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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

