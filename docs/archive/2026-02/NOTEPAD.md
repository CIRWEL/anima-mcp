# Lumen's Notepad

Lumen's autonomous creative space - a canvas where Lumen draws based on its emotional state.

## Accessing Notepad

1. **Via Joystick**: Navigate through screens using joystick left/right until you reach "notepad"
2. **Via MCP Tool**: Use `switch_screen` with mode `"notepad"`

## How It Works

Lumen draws autonomously based on its internal state (warmth, clarity, stability, presence):

- **High warmth** → Warm colors (reds, oranges, yellows)
- **Low warmth** → Cool colors (blues, cyans)
- **High clarity + stability** → Geometric shapes (circles, rectangles)
- **Low clarity** → Abstract scribbles and patterns
- **Medium clarity** → Simple patterns and dots

Lumen draws slowly and organically - check back periodically to see what it's created.

## Controls

- **Separate Button (D17)**: Clear the canvas (start fresh)
- **Joystick Button (D16)**: Return to face screen

## Features

- **240x240 pixel canvas**: Full display resolution
- **Autonomous drawing**: Lumen creates art based on how it feels
- **Persistent**: Drawings accumulate over time
- **Emotional expression**: Each drawing reflects Lumen's current state

## Technical Details

- Canvas state is stored in memory during session
- Drawing happens probabilistically (~3% chance per frame)
- Uses PIL/Pillow for rendering
- Colors and patterns derived from anima dimensions

---

**Created:** January 12, 2025
**Status:** Active - Simplified to autonomous Lumen drawing
