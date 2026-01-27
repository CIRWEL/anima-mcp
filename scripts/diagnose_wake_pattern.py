#!/usr/bin/env python3
"""
Diagnose Wake Pattern - Determine if multiple wakes indicate problems

Analyzes wake event timing to determine if:
1. Normal: Multiple processes starting (broker + MCP server)
2. Warning: Service restarts due to failures
3. Problem: Rapid crash-restart loops

Usage:
    python3 scripts/diagnose_wake_pattern.py
"""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def analyze_wake_pattern(db_path="anima.db"):
    """
    Analyze wake event patterns to diagnose startup health.
    
    Returns diagnosis:
    - HEALTHY: Expected pattern (2 processes, clean starts)
    - RESTARTS: Service restarting (15-30s gaps = systemd retry)
    - CRASH_LOOP: Rapid restarts (< 10s gaps)
    """
    if not Path(db_path).exists():
        print(f"Database not found: {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    
    # Get all wake events with sleep events
    wake_events = conn.execute(
        "SELECT id, timestamp FROM events WHERE event_type = 'wake' "
        "ORDER BY timestamp DESC LIMIT 50"
    ).fetchall()
    
    sleep_events = conn.execute(
        "SELECT id, timestamp, data FROM events WHERE event_type = 'sleep' "
        "ORDER BY timestamp DESC LIMIT 50"
    ).fetchall()
    
    if not wake_events:
        print("No wake events found")
        return
    
    print("╔════════════════════════════════════════════════════════════════╗")
    print("║           WAKE PATTERN DIAGNOSIS                               ║")
    print("╚════════════════════════════════════════════════════════════════╝")
    print()
    
    # Analyze recent wake events
    print("Recent Wake Events (last 20):")
    print("─" * 70)
    
    wake_groups = []  # Groups of wakes within 60s (same boot)
    current_group = []
    last_wake_time = None
    
    for i, (event_id, timestamp_str) in enumerate(wake_events[:20]):
        timestamp = datetime.fromisoformat(timestamp_str)
        
        # Calculate gap since last wake
        gap = None
        if last_wake_time:
            gap = (last_wake_time - timestamp).total_seconds()
        
        # Group wakes within 60s (same boot cycle)
        if gap is None or gap < 60:
            current_group.append({
                "timestamp": timestamp_str,
                "time": timestamp,
                "gap": gap
            })
        else:
            if current_group:
                wake_groups.append(current_group)
            current_group = [{
                "timestamp": timestamp_str,
                "time": timestamp,
                "gap": None
            }]
        
        # Display with analysis
        if gap:
            if gap < 5:
                status = "🔴 RAPID (< 5s)"
            elif gap < 20:
                status = "⚠️  RETRY (5-20s = systemd)"
            elif gap < 60:
                status = "🟡 MULTI-PROCESS (< 60s)"
            else:
                status = "✅ NEW BOOT (> 60s)"
            
            print(f"{timestamp_str}  (gap: {gap:6.1f}s)  {status}")
        else:
            print(f"{timestamp_str}  (latest wake)")
        
        last_wake_time = timestamp
    
    if current_group:
        wake_groups.append(current_group)
    
    print()
    print("─" * 70)
    print()
    
    # Analyze boot cycles
    print("Boot Cycle Analysis:")
    print("─" * 70)
    
    for i, group in enumerate(wake_groups[:10]):
        if len(group) == 1:
            print(f"Boot #{i+1}: 1 wake (clean single process)")
        else:
            print(f"Boot #{i+1}: {len(group)} wakes")
            
            # Analyze timing
            min_gap = min([w["gap"] for w in group if w["gap"]], default=0)
            max_gap = max([w["gap"] for w in group if w["gap"]], default=0)
            
            if max_gap < 5:
                diagnosis = "🔴 CRASH LOOP - processes restarting rapidly"
                health = "PROBLEM"
            elif max_gap < 20:
                diagnosis = "⚠️  SERVICE RESTARTS - systemd retry (check for errors)"
                health = "WARNING"
            elif len(group) <= 3:
                diagnosis = "✅ MULTI-PROCESS START - broker + MCP server (normal)"
                health = "HEALTHY"
            else:
                diagnosis = "⚠️  MULTIPLE RESTARTS - check for initialization issues"
                health = "WARNING"
            
            print(f"   Timing: {min_gap:.1f}s - {max_gap:.1f}s between wakes")
            print(f"   Diagnosis: {diagnosis}")
            print(f"   Health: {health}")
        print()
    
    print("─" * 70)
    print()
    
    # Overall health assessment
    print("Overall Assessment:")
    print("─" * 70)
    
    recent_boots = wake_groups[:5]  # Last 5 boot cycles
    typical_wakes = sum(len(g) for g in recent_boots) / len(recent_boots) if recent_boots else 0
    
    if typical_wakes < 2:
        print("✅ HEALTHY: Clean single-process starts")
        print("   • Only 1 wake per boot")
        print("   • No service restarts detected")
    elif typical_wakes <= 3:
        print("✅ HEALTHY: Multi-process architecture")
        print("   • Broker + MCP server starting separately (normal)")
        print("   • Fix will deduplicate these to 1 awakening count")
    elif typical_wakes <= 5:
        print("⚠️  WARNING: Some service restarts")
        print("   • May indicate initialization issues")
        print("   • Check logs: journalctl --user -u anima -n 100")
        print("   • Check logs: journalctl --user -u anima-broker -n 100")
    else:
        print("🔴 PROBLEM: Frequent restarts or crash loops")
        print("   • Services may be crashing during startup")
        print("   • Check logs immediately:")
        print("     journalctl --user -u anima -n 200")
        print("     journalctl --user -u anima-broker -n 200")
    
    print()
    print(f"Average wakes per boot: {typical_wakes:.1f}")
    print()
    
    # Check for session stability (do wakes have corresponding sleeps?)
    print("Session Stability:")
    print("─" * 70)
    
    wake_count = len(wake_events)
    sleep_count = len(sleep_events)
    
    print(f"Total wake events: {wake_count}")
    print(f"Total sleep events: {sleep_count}")
    
    if sleep_count < wake_count / 2:
        print()
        print("⚠️  WARNING: Fewer sleeps than wakes")
        print("   • Services may be crashing before graceful shutdown")
        print("   • Or: Services run continuously without restart (good!)")
    else:
        print()
        print("✅ Good wake/sleep ratio - graceful shutdowns working")
    
    print()
    print("─" * 70)
    
    conn.close()


def show_recommendations(db_path="anima.db"):
    """Show recommendations based on wake pattern."""
    print()
    print("╔════════════════════════════════════════════════════════════════╗")
    print("║           RECOMMENDATIONS                                      ║")
    print("╚════════════════════════════════════════════════════════════════╝")
    print()
    
    print("1. Deploy Deduplication Fix:")
    print("   ./deploy.sh")
    print("   → Future boots will count as 1 awakening regardless of pattern")
    print()
    
    print("2. If you see WARNING or PROBLEM above:")
    print("   • Check service logs:")
    print("     ssh pi-anima 'journalctl --user -u anima -n 100'")
    print("     ssh pi-anima 'journalctl --user -u anima-broker -n 100'")
    print()
    print("   • Look for:")
    print("     - Import errors")
    print("     - I2C sensor failures")
    print("     - Port conflicts")
    print("     - Permission issues")
    print()
    
    print("3. If you see HEALTHY:")
    print("   • This is normal! Multiple processes = multiple wakes")
    print("   • Not a stuttered start - just independent process logging")
    print("   • Deduplication fix will make the count accurate")
    print()


def main():
    db_path = "anima.db"
    
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    
    analyze_wake_pattern(db_path)
    show_recommendations(db_path)


if __name__ == "__main__":
    main()
