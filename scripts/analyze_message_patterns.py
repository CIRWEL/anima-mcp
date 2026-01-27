#!/usr/bin/env python3
"""
Analyze Lumen's Message Posting Patterns

Examines message board history to understand:
1. Why messages are sometimes posted and sometimes not
2. Deduplication patterns
3. Posting frequency over time
4. Correlation with shutdowns/reboots

Usage:
    python3 scripts/analyze_message_patterns.py
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter
from typing import List, Dict, Any


def load_messages() -> List[Dict]:
    """Load messages from persistent storage."""
    messages_file = Path.home() / ".anima" / "messages.json"
    
    if not messages_file.exists():
        print(f"No messages found at {messages_file}")
        print("Lumen may not have posted any messages yet")
        return []
    
    try:
        data = json.load(messages_file.open())
        messages = data.get("messages", [])
        return messages
    except Exception as e:
        print(f"Error loading messages: {e}")
        return []


def analyze_posting_frequency(messages: List[Dict]):
    """Analyze how often Lumen posts messages."""
    if len(messages) < 2:
        print("Not enough messages to analyze frequency")
        return
    
    print("╔════════════════════════════════════════════════════════════════╗")
    print("║           MESSAGE POSTING FREQUENCY                            ║")
    print("╚════════════════════════════════════════════════════════════════╝")
    print()
    
    # Sort by timestamp
    sorted_msgs = sorted(messages, key=lambda m: m["timestamp"])
    
    # Calculate gaps between messages
    gaps = []
    for i in range(len(sorted_msgs) - 1):
        gap = sorted_msgs[i + 1]["timestamp"] - sorted_msgs[i]["timestamp"]
        gaps.append(gap)
    
    if not gaps:
        print("No gaps to analyze")
        return
    
    # Statistics
    avg_gap = sum(gaps) / len(gaps)
    min_gap = min(gaps)
    max_gap = max(gaps)
    
    print(f"Total messages: {len(messages)}")
    print(f"Time span: {(sorted_msgs[-1]['timestamp'] - sorted_msgs[0]['timestamp']) / 3600:.1f} hours")
    print()
    print("Gap Statistics:")
    print(f"  Average: {avg_gap / 60:.1f} minutes")
    print(f"  Minimum: {min_gap / 60:.1f} minutes")
    print(f"  Maximum: {max_gap / 60:.1f} minutes ({max_gap / 3600:.1f} hours)")
    print()
    
    # Categorize gaps
    gap_categories = {
        "< 3 min (rapid)": sum(1 for g in gaps if g < 180),
        "3-5 min (normal)": sum(1 for g in gaps if 180 <= g < 300),
        "5-15 min (occasional)": sum(1 for g in gaps if 300 <= g < 900),
        "15-60 min (rare)": sum(1 for g in gaps if 900 <= g < 3600),
        "> 1 hour (gap)": sum(1 for g in gaps if g >= 3600),
    }
    
    print("Gap Distribution:")
    for category, count in gap_categories.items():
        percentage = (count / len(gaps)) * 100 if gaps else 0
        print(f"  {category}: {count} ({percentage:.1f}%)")
    print()
    
    # Expected: 2 minutes (120 seconds) per message if posting regularly
    expected_gap = 120
    actual_avg = avg_gap
    
    if actual_avg < expected_gap * 1.5:
        print("✅ Posting regularly (close to expected 2-minute interval)")
    elif actual_avg < expected_gap * 3:
        print("⚠️  Posting less frequently than expected (some messages skipped)")
        print("   Likely due to: deduplication or state not crossing thresholds")
    else:
        print("⚠️  Long gaps between messages")
        print("   Likely due to: shutdowns, deduplication, or state remaining stable")


def analyze_deduplication(messages: List[Dict]):
    """Analyze deduplication patterns."""
    print()
    print("╔════════════════════════════════════════════════════════════════╗")
    print("║           DEDUPLICATION ANALYSIS                               ║")
    print("╚════════════════════════════════════════════════════════════════╝")
    print()
    
    # Count unique messages
    message_texts = [m["text"] for m in messages]
    unique_messages = set(message_texts)
    
    print(f"Total messages: {len(messages)}")
    print(f"Unique messages: {len(unique_messages)}")
    print(f"Repetition rate: {((len(messages) - len(unique_messages)) / len(messages) * 100):.1f}%")
    print()
    
    # Find most repeated messages
    text_counts = Counter(message_texts)
    most_common = text_counts.most_common(5)
    
    print("Most Repeated Messages:")
    for text, count in most_common:
        print(f"  [{count}x] {text[:60]}")
    print()
    
    # Estimate deduplication savings
    # Assumption: Without dedup, would post every 2 minutes
    sorted_msgs = sorted(messages, key=lambda m: m["timestamp"])
    time_span_hours = (sorted_msgs[-1]["timestamp"] - sorted_msgs[0]["timestamp"]) / 3600
    expected_posts = time_span_hours * 30  # 30 posts per hour if posting every 2 min
    actual_posts = len(messages)
    dedupe_saved = max(0, expected_posts - actual_posts)
    
    print(f"Time span: {time_span_hours:.1f} hours")
    print(f"Expected posts (no dedup): ~{expected_posts:.0f}")
    print(f"Actual posts: {actual_posts}")
    print(f"Deduplication saved: ~{dedupe_saved:.0f} messages")
    print()
    
    if dedupe_saved / expected_posts > 0.5:
        print("✅ Deduplication is working well (preventing spam)")
    else:
        print("⚠️  Low deduplication - messages are highly varied")


def correlate_with_shutdowns(messages: List[Dict]):
    """Try to correlate message patterns with shutdown/restart events."""
    print()
    print("╔════════════════════════════════════════════════════════════════╗")
    print("║           SHUTDOWN CORRELATION                                 ║")
    print("╚════════════════════════════════════════════════════════════════╝")
    print()
    
    sorted_msgs = sorted(messages, key=lambda m: m["timestamp"])
    
    # Identify potential shutdowns (gaps > 5 minutes)
    shutdown_gaps = []
    for i in range(len(sorted_msgs) - 1):
        gap = sorted_msgs[i + 1]["timestamp"] - sorted_msgs[i]["timestamp"]
        if gap > 300:  # 5 minutes
            shutdown_gaps.append({
                "before": sorted_msgs[i],
                "after": sorted_msgs[i + 1],
                "gap_minutes": gap / 60,
                "gap_hours": gap / 3600,
            })
    
    print(f"Potential shutdowns detected: {len(shutdown_gaps)}")
    print("(Gaps > 5 minutes between messages)")
    print()
    
    if not shutdown_gaps:
        print("No significant gaps detected")
        print("Either:")
        print("  • Lumen has been running continuously")
        print("  • Messages span short time period")
        return
    
    # Analyze gap patterns
    gap_durations = [g["gap_minutes"] for g in shutdown_gaps]
    avg_gap = sum(gap_durations) / len(gap_durations)
    
    print(f"Average gap: {avg_gap:.1f} minutes")
    print()
    print("Recent gaps:")
    for i, gap_info in enumerate(shutdown_gaps[:10]):  # Show first 10
        before_time = datetime.fromtimestamp(gap_info["before"]["timestamp"])
        after_time = datetime.fromtimestamp(gap_info["after"]["timestamp"])
        
        print(f"  Gap #{i + 1}:")
        print(f"    Before: {before_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"    After:  {after_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"    Duration: {gap_info['gap_minutes']:.1f} min ({gap_info['gap_hours']:.2f} hours)")
        
        # Analyze message content before/after
        before_text = gap_info["before"]["text"][:40]
        after_text = gap_info["after"]["text"][:40]
        
        if before_text == after_text:
            print(f"    Same feeling before/after ← State persisted")
        else:
            print(f"    Different feeling after ← State changed")
        print()
    
    # Check if message content changes after shutdowns
    same_count = sum(1 for g in shutdown_gaps 
                     if g["before"]["text"] == g["after"]["text"])
    
    print(f"Messages with same feeling before/after shutdown: {same_count}/{len(shutdown_gaps)}")
    
    if same_count / len(shutdown_gaps) > 0.5:
        print("  → Lumen's state tends to persist across shutdowns")
        print("  → Environmental conditions stable")
    else:
        print("  → Lumen's state often changes after shutdowns")
        print("  → Environmental or system changes on restart")


def analyze_message_content(messages: List[Dict]):
    """Analyze what Lumen talks about."""
    print()
    print("╔════════════════════════════════════════════════════════════════╗")
    print("║           MESSAGE CONTENT ANALYSIS                             ║")
    print("╚════════════════════════════════════════════════════════════════╝")
    print()
    
    # Extract feelings and desires
    feelings = []
    desires = []
    
    for msg in messages:
        text = msg["text"]
        
        # Try to parse "I feel X - I want Y" format
        if " - " in text:
            parts = text.split(" - ", 1)
            feelings.append(parts[0])
            if len(parts) > 1:
                desires.append(parts[1])
    
    # Count feeling types
    feeling_words = []
    for feeling in feelings:
        # Extract key feeling words
        if "uncertain" in feeling.lower():
            feeling_words.append("uncertain")
        elif "chaotic" in feeling.lower():
            feeling_words.append("chaotic")
        elif "cold" in feeling.lower():
            feeling_words.append("cold")
        elif "constrained" in feeling.lower():
            feeling_words.append("constrained")
        elif "clear" in feeling.lower() and "capable" in feeling.lower():
            feeling_words.append("capable")
        elif "content" in feeling.lower() or "good" in feeling.lower():
            feeling_words.append("content")
    
    feeling_counts = Counter(feeling_words)
    
    print("Lumen's Emotional Patterns:")
    for feeling, count in feeling_counts.most_common():
        percentage = (count / len(messages)) * 100
        print(f"  {feeling.title()}: {count} times ({percentage:.1f}%)")
    print()
    
    # Analyze desire types
    desire_words = []
    for desire in desires:
        if "clarity" in desire.lower() or "clearly" in desire.lower():
            desire_words.append("clarity")
        elif "peace" in desire.lower():
            desire_words.append("peace")
        elif "comfortable" in desire.lower():
            desire_words.append("comfort")
        elif "freedom" in desire.lower():
            desire_words.append("freedom")
        elif "explore" in desire.lower() or "experience" in desire.lower():
            desire_words.append("exploration")
        elif "express" in desire.lower():
            desire_words.append("expression")
    
    desire_counts = Counter(desire_words)
    
    print("Lumen's Desires:")
    for desire, count in desire_counts.most_common():
        percentage = (count / len(messages)) * 100
        print(f"  Wants {desire}: {count} times ({percentage:.1f}%)")
    print()


def main():
    messages = load_messages()
    
    if not messages:
        print()
        print("No messages to analyze")
        print()
        print("Possible reasons:")
        print("  • Lumen hasn't run long enough (need ~2 minutes)")
        print("  • State hasn't crossed any thresholds (everything OK)")
        print("  • Message board file doesn't exist yet")
        return
    
    print()
    print(f"Loaded {len(messages)} messages")
    print()
    
    analyze_posting_frequency(messages)
    analyze_deduplication(messages)
    analyze_message_content(messages)
    correlate_with_shutdowns(messages)
    
    print()
    print("╔════════════════════════════════════════════════════════════════╗")
    print("║           CONCLUSIONS                                          ║")
    print("╚════════════════════════════════════════════════════════════════╝")
    print()
    print("Based on this analysis:")
    print()
    print("1. Message posting is CONDITIONAL:")
    print("   • Posts when state crosses thresholds")
    print("   • Skips if same message was recent (deduplication)")
    print("   • Stays quiet when state is stable/comfortable")
    print()
    print("2. This is INTENTIONAL DESIGN:")
    print("   • Not random or broken")
    print("   • Prevents spam")
    print("   • Lumen speaks when it has something new to say")
    print()
    print("3. Lumen does NOT (yet) learn:")
    print("   • Message effectiveness (user engagement)")
    print("   • Shutdown patterns (CI/CD cycles)")
    print("   • Behavioral adaptation (meta-cognition)")
    print()
    print("4. Current learning is ENVIRONMENTAL only:")
    print("   • Temperature calibration")
    print("   • Pressure baselines")
    print("   • Humidity ranges")
    print()
    print("See MESSAGE_BEHAVIOR_ANALYSIS.md for full explanation")
    print()


if __name__ == "__main__":
    main()
