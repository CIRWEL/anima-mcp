#!/usr/bin/env python3
"""
Anima Dashboard - Real-time Visualization of Anima State
"""
import sys
import time
import curses
import json
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.resolve()
sys.path.append(str(project_root))

from src.anima_mcp.shared_memory import SharedMemoryClient

def draw_bar(stdscr, y, x, label, value, max_val=1.0, width=20, color_pair=1):
    """Draw a progress bar."""
    stdscr.addstr(y, x, f"{label}: ", curses.color_pair(color_pair))
    
    # Calculate filled width
    filled = int((value / max_val) * width)
    filled = max(0, min(filled, width))
    
    # Draw bar
    bar = "█" * filled + "░" * (width - filled)
    stdscr.addstr(f"{bar} {value:.2f}")

def main(stdscr):
    # Setup
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    
    # Colors
    curses.init_pair(1, curses.COLOR_WHITE, -1)   # Normal
    curses.init_pair(2, curses.COLOR_GREEN, -1)   # Good
    curses.init_pair(3, curses.COLOR_YELLOW, -1)  # Warning
    curses.init_pair(4, curses.COLOR_RED, -1)     # Danger
    curses.init_pair(5, curses.COLOR_CYAN, -1)    # Info
    
    # Initialize Shared Memory Client in READ mode
    # Force file backend to match stable_creature.py configuration
    client = SharedMemoryClient(mode="read", backend="file")
    
    # Header logic
    title = " ANIMA SYSTEM DASHBOARD (SIMULATION) "
    
    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()
        
        # Draw Header
        stdscr.attron(curses.color_pair(5) | curses.A_BOLD)
        stdscr.addstr(0, max(0, (width - len(title)) // 2), title)
        stdscr.attroff(curses.color_pair(5) | curses.A_BOLD)
        stdscr.addstr(1, 0, "═" * width)
        
        # Read Data
        data = client.read()
        
        if not data:
            stdscr.addstr(3, 2, "WAITING FOR SHARED MEMORY...", curses.color_pair(3))
            stdscr.addstr(4, 2, "Confirm stable_creature.py is running.")
            stdscr.refresh()
            time.sleep(1)
            continue
            
        # Parse Data
        # Structure depends on what stable_creature puts in. 
        # Usually: {"anima": {...}, "readings": {...}, "eisv": {...}, "governance": {...}}
        
        anima = data.get("anima", {})
        eisv = data.get("eisv", {})
        readings = data.get("readings", {})
        gov = data.get("governance", {}) # Might be separate
        
        row = 3
        col1 = 2
        col2 = 40
        
        # --- LEFT COLUMN: ANIMA STATE ---
        stdscr.addstr(row, col1, "Anima State", curses.A_UNDERLINE | curses.A_BOLD)
        
        # Warmth (Energy)
        row += 2
        draw_bar(stdscr, row, col1, "Warmth   ", anima.get("warmth", 0), color_pair=2)
        
        # Clarity (Integrity)
        row += 1
        draw_bar(stdscr, row, col1, "Clarity  ", anima.get("clarity", 0), color_pair=5)
        
        # Stability (1-Entropy)
        row += 1
        draw_bar(stdscr, row, col1, "Stability", anima.get("stability", 0), color_pair=2)
        
        # Presence (1-Void)
        row += 1
        draw_bar(stdscr, row, col1, "Presence ", anima.get("presence", 0), color_pair=5)
        
        # Mood
        row += 2
        stdscr.addstr(row, col1, f"Mood: {anima.get('mood', 'N/A').upper()}", curses.A_BOLD)
        
        
        # --- RIGHT COLUMN: UNITARES METRICS ---
        r_row = 3
        stdscr.addstr(r_row, col2, "UNITARES (EISV)", curses.A_UNDERLINE | curses.A_BOLD)
        
        # Energy
        r_row += 2
        draw_bar(stdscr, r_row, col2, "Energy   ", eisv.get("E", 0), color_pair=4)
        
        # Integrity
        r_row += 1
        draw_bar(stdscr, r_row, col2, "Integrity", eisv.get("I", 0), color_pair=5)
        
        # Entropy
        r_row += 1
        s_val = eisv.get("S", 0)
        s_color = 4 if s_val > 0.5 else 2  # Red if high entropy
        draw_bar(stdscr, r_row, col2, "Entropy  ", s_val, color_pair=s_color)
        
        # Void
        r_row += 1
        v_val = eisv.get("V", 0)
        v_color = 4 if v_val > 0.5 else 2  # Red if high void
        draw_bar(stdscr, r_row, col2, "Void     ", v_val, color_pair=v_color)
        
        
        # --- ROW 3: SENSORS ---
        s_row = max(row, r_row) + 3
        stdscr.addstr(s_row, col1, "Raw Sensors (Simulated on Mac)", curses.A_UNDERLINE | curses.A_BOLD)
        s_row += 2
        
        temp = readings.get("cpu_temp_c") or readings.get("ambient_temp_c", 0)
        humidity = readings.get("humidity_pct", 0)
        light = readings.get("light_lux", 0)
        cpu = readings.get("cpu_percent", 0)
        
        stdscr.addstr(s_row, col1, f"Temp:     {temp:.1f}°C")
        stdscr.addstr(s_row, col1 + 25, f"Humidity: {humidity:.1f}%")
        s_row += 1
        stdscr.addstr(s_row, col1, f"Light:    {light:.1f} lux")
        stdscr.addstr(s_row, col1 + 25, f"CPU Load: {cpu:.1f}%")
        
        # Footer
        stdscr.addstr(height-2, 2, f"Last Update: {data.get('updated_at', 'Unknown')}", curses.A_DIM)
        stdscr.addstr(height-1, 2, "Press Ctrl+C to Exit", curses.A_DIM)
        
        stdscr.refresh()
        time.sleep(0.5)

if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        print("Dashboard Exited.")
