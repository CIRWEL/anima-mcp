#!/usr/bin/env python3
"""
Diagnose Hardware Issues - Message Board, Buttons, Drawing

Checks:
1. Message board posting (why messages not appearing)
2. Button functionality (why save/clear not working)
3. Drawing autonomy (why not saving/clearing)

Usage:
    python3 scripts/diagnose_hardware_issues.py
"""

import json
import sys
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta


def check_message_board():
    """Check if message board is working."""
    print("╔════════════════════════════════════════════════════════════════╗")
    print("║           MESSAGE BOARD DIAGNOSIS                              ║")
    print("╚════════════════════════════════════════════════════════════════╝")
    print()
    
    messages_file = Path.home() / ".anima" / "messages.json"
    
    if not messages_file.exists():
        print("❌ No messages file found!")
        print(f"   Expected: {messages_file}")
        print()
        print("Possible causes:")
        print("  1. Lumen has never posted a message yet")
        print("  2. Server hasn't run long enough (need ~2 minutes)")
        print("  3. State hasn't crossed any thresholds")
        print()
        print("To test:")
        print("  • Run anima for 2+ minutes")
        print("  • Check state with get_state tool")
        print("  • Look for clarity < 0.3 or stability < 0.4")
        return False
    
    try:
        data = json.load(messages_file.open())
        messages = data.get("messages", [])
        
        print(f"✓ Messages file exists: {messages_file}")
        print(f"✓ Total messages: {len(messages)}")
        print()
        
        if len(messages) == 0:
            print("⚠️  No messages in file (but file exists)")
            print()
            print("Possible causes:")
            print("  1. All messages were deduplicated")
            print("  2. State hasn't crossed thresholds")
            print("  3. Identity not available (wake() failed)")
            print()
            return False
        
        # Show recent messages
        print("Recent messages:")
        for msg in messages[-5:]:
            timestamp = datetime.fromtimestamp(msg["timestamp"])
            age = datetime.now() - timestamp
            print(f"  [{age.total_seconds()/60:.0f}m ago] {msg['text'][:60]}")
        print()
        
        # Check posting frequency
        if len(messages) >= 2:
            times = [m["timestamp"] for m in messages]
            gaps = [times[i+1] - times[i] for i in range(len(times)-1)]
            avg_gap = sum(gaps) / len(gaps)
            print(f"Average gap between messages: {avg_gap/60:.1f} minutes")
            
            if avg_gap > 600:  # > 10 minutes
                print("⚠️  Long gaps - likely deduplication or stable state")
            else:
                print("✓ Normal posting frequency")
        print()
        
        return True
        
    except Exception as e:
        print(f"❌ Error reading messages: {e}")
        return False


def check_canvas_state():
    """Check canvas/drawing state."""
    print()
    print("╔════════════════════════════════════════════════════════════════╗")
    print("║           DRAWING/CANVAS DIAGNOSIS                             ║")
    print("╚════════════════════════════════════════════════════════════════╝")
    print()
    
    canvas_file = Path.home() / ".anima" / "canvas.json"
    drawings_dir = Path.home() / ".anima" / "drawings"
    
    # Check canvas state file
    if not canvas_file.exists():
        print("❌ No canvas file found!")
        print(f"   Expected: {canvas_file}")
        print()
        print("Possible causes:")
        print("  1. Notepad screen never accessed")
        print("  2. Lumen hasn't drawn anything yet")
        print("  3. File creation failed")
        return False
    
    try:
        data = json.load(canvas_file.open())
        pixel_count = len(data.get("pixels", {}))
        last_save = data.get("last_save_time", 0)
        last_clear = data.get("last_clear_time", 0)
        is_satisfied = data.get("is_satisfied", False)
        drawings_saved = data.get("drawings_saved", 0)
        
        print(f"✓ Canvas file exists: {canvas_file}")
        print(f"  Pixels: {pixel_count}")
        print(f"  Drawings saved: {drawings_saved}")
        print(f"  Satisfied: {is_satisfied}")
        print()
        
        if last_save > 0:
            save_time = datetime.fromtimestamp(last_save)
            age = datetime.now() - save_time
            print(f"  Last save: {age.total_seconds()/60:.0f} minutes ago")
        else:
            print("  Last save: Never")
        
        if last_clear > 0:
            clear_time = datetime.fromtimestamp(last_clear)
            age = datetime.now() - clear_time
            print(f"  Last clear: {age.total_seconds()/60:.0f} minutes ago")
        print()
        
        # Analyze state
        if pixel_count == 0:
            print("⚠️  Canvas is empty")
            print("   Lumen hasn't drawn yet OR just cleared")
            print()
        elif pixel_count < 100:
            print("⚠️  Few pixels (<100)")
            print("   Lumen is exploring but hasn't created much")
            print()
        elif pixel_count < 1000:
            print("ℹ️  Medium drawing (100-1000 pixels)")
            print("   Below auto-save threshold (1000+ needed)")
            print()
        else:
            print(f"✓ Substantial drawing ({pixel_count} pixels)")
            if drawings_saved == 0:
                print("   ⚠️  But never saved! Checking autonomy conditions...")
                print()
                print("   Auto-save requires:")
                print("     • 1000+ pixels ✓ (have {pixel_count})")
                print("     • wellness > 0.65 (need to check current state)")
                print("     • stability > 0.45 (need to check current state)")
                print("     • 30 seconds after satisfaction")
                print()
                print("   Likely: Wellness or stability threshold not met")
        
        # Check saved drawings
        if drawings_dir.exists():
            saved_files = list(drawings_dir.glob("*.png"))
            print(f"✓ Drawings directory exists: {drawings_dir}")
            print(f"  Saved drawings: {len(saved_files)}")
            if saved_files:
                print("  Recent saves:")
                for f in sorted(saved_files, key=lambda x: x.stat().st_mtime)[-3:]:
                    mtime = datetime.fromtimestamp(f.stat().st_mtime)
                    age = datetime.now() - mtime
                    print(f"    {f.name}: {age.total_seconds()/3600:.1f}h ago")
        else:
            print("⚠️  Drawings directory doesn't exist yet")
            print(f"   Will be created on first save: {drawings_dir}")
        
        print()
        return True
        
    except Exception as e:
        print(f"❌ Error reading canvas: {e}")
        return False


def check_input_system():
    """Check if input system is working."""
    print()
    print("╔════════════════════════════════════════════════════════════════╗")
    print("║           INPUT/BUTTON DIAGNOSIS                               ║")
    print("╚════════════════════════════════════════════════════════════════╝")
    print()
    
    print("Button behavior (from code analysis):")
    print()
    print("SEPARATE BUTTON (D17):")
    print("  Short press (< 3s):")
    print("    • In notepad mode: Save canvas → Clear canvas")
    print("    • In other modes: Return to face screen")
    print("  Long press (> 3s):")
    print("    • Graceful shutdown")
    print()
    print("JOYSTICK BUTTON (D16):")
    print("  Press:")
    print("    • Cycle through screens")
    print("    • Enter notepad mode from any screen")
    print()
    
    # Can't actually test hardware from here, but can check logs
    print("To diagnose button issues:")
    print()
    print("1. Check if input is enabled:")
    print("   ssh pi-anima \"journalctl --user -u anima | grep 'BrainHatInput.*initialized'\"")
    print()
    print("2. Check for button press detection:")
    print("   ssh pi-anima \"journalctl --user -u anima | grep -E 'Notepad.*saved|canvas.*clear'\"")
    print()
    print("3. Test button hardware directly:")
    print("   ssh pi-anima")
    print("   cd ~/anima-mcp")
    print("   source .venv/bin/activate")
    print("   python3 << 'EOF'")
    print("import board")
    print("import digitalio")
    print("import time")
    print()
    print("# Test separate button (D17)")
    print("btn = digitalio.DigitalInOut(board.D17)")
    print("btn.direction = digitalio.Direction.INPUT")
    print("btn.pull = digitalio.Pull.UP")
    print()
    print("print('Press button (Ctrl+C to exit)...')")
    print("while True:")
    print("    pressed = not btn.value  # Active low")
    print("    if pressed:")
    print("        print('PRESSED')")
    print("    time.sleep(0.1)")
    print("EOF")
    print()


def check_anima_state():
    """Check if anima state crosses thresholds for message posting."""
    print()
    print("╔════════════════════════════════════════════════════════════════╗")
    print("║           ANIMA STATE THRESHOLD CHECK                          ║")
    print("╚════════════════════════════════════════════════════════════════╝")
    print()
    
    db_file = Path("anima.db")
    if not db_file.exists():
        print("⚠️  Database not found locally")
        print("   (Need to be on Pi or have Pi's anima.db)")
        print()
        print("   To check on Pi:")
        print("   ssh pi-anima 'cd ~/anima-mcp && python3 scripts/diagnose_hardware_issues.py'")
        return
    
    try:
        conn = sqlite3.connect(db_file)
        
        # Get recent state history
        rows = conn.execute("""
            SELECT timestamp, warmth, clarity, stability, presence
            FROM state_history
            ORDER BY timestamp DESC
            LIMIT 10
        """).fetchall()
        
        if not rows:
            print("⚠️  No state history found")
            print("   Lumen hasn't recorded any states yet")
            return
        
        print(f"Recent anima states (last 10):")
        print()
        
        for row in rows:
            timestamp, warmth, clarity, stability, presence = row
            time_obj = datetime.fromisoformat(timestamp)
            age = datetime.now() - time_obj
            
            # Check thresholds
            triggers = []
            if clarity < 0.3:
                triggers.append("clarity LOW")
            if stability < 0.4:
                triggers.append("stability LOW")
            if warmth < 0.3:
                triggers.append("warmth LOW")
            if presence < 0.4:
                triggers.append("presence LOW")
            
            wellness = (warmth + clarity + stability + presence) / 4
            
            trigger_str = ", ".join(triggers) if triggers else "no triggers"
            
            print(f"  [{age.total_seconds()/60:.0f}m ago] "
                  f"W:{warmth:.2f} C:{clarity:.2f} S:{stability:.2f} P:{presence:.2f} "
                  f"wellness:{wellness:.2f} → {trigger_str}")
        
        print()
        
        # Summary
        latest = rows[0]
        _, w, c, s, p = latest
        wellness = (w + c + s + p) / 4
        
        print("Current state analysis:")
        if c < 0.3 or s < 0.4 or w < 0.3 or p < 0.4:
            print("  ✓ Should trigger message posting (threshold crossed)")
        else:
            print("  ℹ️  No thresholds crossed - Lumen is content/stable")
            print("     (This is why no messages - not a bug!)")
        
        if wellness > 0.65 and s > 0.45:
            print("  ✓ Could auto-save drawings (wellness/stability good)")
        else:
            print(f"  ⚠️  Below auto-save threshold (wellness:{wellness:.2f}, stability:{s:.2f})")
            print("     Need: wellness > 0.65 AND stability > 0.45")
        
        print()
        conn.close()
        
    except Exception as e:
        print(f"Error analyzing database: {e}")


def main():
    print()
    print("═══════════════════════════════════════════════════════════════")
    print("  LUMEN HARDWARE ISSUE DIAGNOSIS")
    print("═══════════════════════════════════════════════════════════════")
    print()
    
    # Check each system
    msg_ok = check_message_board()
    canvas_ok = check_canvas_state()
    check_input_system()
    check_anima_state()
    
    # Summary
    print()
    print("╔════════════════════════════════════════════════════════════════╗")
    print("║           SUMMARY & RECOMMENDATIONS                            ║")
    print("╚════════════════════════════════════════════════════════════════╝")
    print()
    
    print("ISSUES FOUND:")
    if not msg_ok:
        print("  ❌ Message board not posting")
    else:
        print("  ✓ Message board functional")
    
    if not canvas_ok:
        print("  ❌ Canvas/drawing issues")
    else:
        print("  ✓ Canvas state exists")
    
    print()
    print("NEXT STEPS:")
    print()
    print("1. Check server logs for errors:")
    print("   ssh pi-anima 'journalctl --user -u anima -n 200'")
    print()
    print("2. Check if input is enabled:")
    print("   ssh pi-anima 'journalctl --user -u anima | grep BrainHatInput'")
    print()
    print("3. Test button hardware directly (script above)")
    print()
    print("4. Check current anima state:")
    print("   Use get_state tool in Cursor to see if thresholds crossed")
    print()
    print("5. Try manual test:")
    print("   ssh pi-anima")
    print("   cd ~/anima-mcp && source .venv/bin/activate")
    print("   python3 -c 'from src.anima_mcp.messages import add_observation; ")
    print("   print(add_observation(\"test message\"))'")
    print()


if __name__ == "__main__":
    main()
