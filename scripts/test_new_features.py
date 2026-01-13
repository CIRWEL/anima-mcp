#!/usr/bin/env python3
"""Test new features: display diagnostics and next steps advocate."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from anima_mcp.display_diagnostics import check_display_hardware
from anima_mcp.next_steps_advocate import NextStepsAdvocate
from anima_mcp.sensors import get_sensors
from anima_mcp.anima import sense_self
from anima_mcp.display import get_display
from anima_mcp.eisv_mapper import anima_to_eisv
import json

def test_display_diagnostics():
    """Test display diagnostics."""
    print("=" * 60)
    print("1. Testing Display Diagnostics")
    print("=" * 60)
    
    result = check_display_hardware()
    print(json.dumps(result, indent=2, default=str))
    
    if result["pil_available"]:
        print("✅ PIL/Pillow available")
    else:
        print("❌ PIL/Pillow not available")
    
    if result["display_available"]:
        print("✅ Display hardware detected")
    else:
        print("⚠️  Display hardware not detected (expected on Mac)")
        if result["error"]:
            print(f"   Reason: {result['error']}")
    
    print()

def test_next_steps_advocate():
    """Test next steps advocate."""
    print("=" * 60)
    print("2. Testing Next Steps Advocate")
    print("=" * 60)
    
    # Get current state
    sensors = get_sensors()
    readings = sensors.read()
    anima = sense_self(readings)
    eisv = anima_to_eisv(anima, readings)
    display = get_display()
    
    # Check availability
    display_available = display.is_available()
    brain_hat_available = "eeg_af7" in sensors.available_sensors()
    
    print(f"Current state:")
    print(f"  Display available: {display_available}")
    print(f"  Brain HAT available: {brain_hat_available}")
    print(f"  Anima: W={anima.warmth:.2f}, C={anima.clarity:.2f}, S={anima.stability:.2f}, P={anima.presence:.2f}")
    print(f"  EISV: E={eisv.energy:.2f}, I={eisv.integrity:.2f}, S={eisv.entropy:.2f}, V={eisv.void:.2f}")
    print()
    
    # Get recommendations
    advocate = NextStepsAdvocate()
    steps = advocate.analyze_current_state(
        anima=anima,
        readings=readings,
        eisv=eisv,
        display_available=display_available,
        brain_hat_available=brain_hat_available,
        unitares_connected=False,
    )
    
    summary = advocate.get_next_steps_summary()
    
    print(f"Next Steps Summary:")
    print(f"  Total steps: {summary['total_steps']}")
    print(f"  Critical: {summary['critical']}")
    print(f"  High: {summary['high']}")
    print(f"  Medium: {summary['medium']}")
    print(f"  Low: {summary['low']}")
    print()
    
    if summary['next_action']:
        print("Next Action:")
        action = summary['next_action']
        print(f"  Title: {action['title']}")
        print(f"  Priority: {action['priority']}")
        print(f"  Action: {action['action']}")
        print(f"  Reason: {action['reason']}")
        if action['blockers']:
            print(f"  Blockers: {', '.join(action['blockers'])}")
        if action['estimated_time']:
            print(f"  Time: {action['estimated_time']}")
    
    print()
    print("All steps:")
    for i, step in enumerate(summary['all_steps'][:5], 1):  # Show first 5
        print(f"  {i}. [{step['priority'].upper()}] {step['title']}")
    
    print()

def test_server_tools():
    """Test server tools."""
    print("=" * 60)
    print("3. Testing Server Tools")
    print("=" * 60)
    
    from anima_mcp.server import TOOLS
    
    print(f"Total tools: {len(TOOLS)}")
    print()
    
    for tool in TOOLS:
        print(f"✅ {tool.name}")
        print(f"   {tool.description}")
        print()
    
    # Check next_steps tool exists
    next_steps_tool = next((t for t in TOOLS if t.name == "next_steps"), None)
    if next_steps_tool:
        print("✅ next_steps tool registered!")
    else:
        print("❌ next_steps tool NOT found!")

if __name__ == "__main__":
    print("\n🧪 Testing New Features\n")
    
    test_display_diagnostics()
    test_next_steps_advocate()
    test_server_tools()
    
    print("=" * 60)
    print("✅ All tests complete!")
    print("=" * 60)
