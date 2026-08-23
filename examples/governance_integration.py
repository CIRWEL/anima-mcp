#!/usr/bin/env python3
"""
Example: Anima creature with UNITARES governance integration.

Demonstrates how to use the integrated server to check in with governance.
"""

import asyncio
import os
from anima_mcp.sensors import get_sensors
from anima_mcp.anima import sense_self
from anima_mcp.unitares_bridge import check_governance
from anima_mcp.eisv_mapper import anima_to_body_eisv_projection


async def main():
    """Example: Check governance with anima creature."""
    
    # Get sensors (auto-detects Pi vs Mac)
    sensors = get_sensors()
    print(f"Available sensors: {sensors.available_sensors()}")
    
    # Read sensors
    readings = sensors.read()
    print("\nSensor readings:")
    print(f"  CPU temp: {readings.cpu_temp_c}°C" if readings.cpu_temp_c else "  CPU temp: N/A")
    print(f"  Light: {readings.light_lux} lux" if readings.light_lux else "  Light: N/A")
    
    # Check for neural signals
    if readings.eeg_alpha_power is not None:
        print("\nNeural signals:")
        print(f"  Alpha: {readings.eeg_alpha_power:.2f}")
        print(f"  Beta: {readings.eeg_beta_power:.2f}")
        print(f"  Gamma: {readings.eeg_gamma_power:.2f}")
    
    # Sense self (anima state)
    anima = sense_self(readings)
    print("\nAnima state:")
    print(f"  Warmth: {anima.warmth:.2f}")
    print(f"  Clarity: {anima.clarity:.2f}")
    print(f"  Stability: {anima.stability:.2f}")
    print(f"  Presence: {anima.presence:.2f}")
    print(f"  Mood: {anima.feeling()['mood']}")
    
    # Project the body into EISV-shaped telemetry. This is input evidence, not
    # UNITARES's own inferred state.
    body_projection = anima_to_body_eisv_projection(anima, readings)
    print("\nBody EISV projection:")
    print(f"  Energy proxy (E): {body_projection.energy:.2f}")
    print(f"  Integrity proxy (I): {body_projection.integrity:.2f}")
    print(f"  Entropy proxy (S): {body_projection.entropy:.2f}")
    print(f"  Valence (V): {body_projection.valence:+.2f}")
    
    # Check governance
    print("\nChecking governance...")
    unitares_url = os.environ.get("UNITARES_URL", "http://127.0.0.1:8767/mcp/")
    decision = await check_governance(anima, readings, unitares_url=unitares_url)
    
    print("\nGovernance Decision:")
    print(f"  Action: {decision['action'].upper()}")
    print(f"  Margin: {decision['margin']}")
    print(f"  Reason: {decision['reason']}")
    print(f"  Source: {decision['source']}")
    if decision.get("governance_eisv"):
        print(
            "  UNITARES EISV: "
            f"{decision['governance_eisv']} "
            f"({decision['governance_eisv_source']})"
        )
    else:
        print("  UNITARES EISV: not returned by this check-in mode")
    
    if decision['action'] == 'proceed':
        print(f"\n✅ Proceeding with task (margin: {decision['margin']})")
    else:
        print(f"\n⏸️  Pausing (margin: {decision['margin']}): {decision['reason']}")


if __name__ == "__main__":
    asyncio.run(main())
