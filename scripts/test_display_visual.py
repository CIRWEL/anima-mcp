#!/usr/bin/env python3
"""
Visual test of the minimal default display.
Creates an image file showing what the default screen looks like.
"""

from PIL import Image, ImageDraw

# Display dimensions (BrainCraft HAT)
WIDTH = 240
HEIGHT = 240
BLACK = (0, 0, 0)

def create_minimal_default():
    """Create the minimal default screen - same as renderer._show_waking_face()"""
    image = Image.new("RGB", (WIDTH, HEIGHT), BLACK)
    draw = ImageDraw.Draw(image)

    # Subtle border - dark enough to be minimal, visible enough to confirm it's not grey
    border_color = (25, 35, 45)  # Dark but visible
    border_width = 2
    
    # Draw a thin border around the edge
    # Top
    draw.rectangle([0, 0, WIDTH, border_width], fill=border_color)
    # Bottom
    draw.rectangle([0, HEIGHT - border_width, WIDTH, HEIGHT], fill=border_color)
    # Left
    draw.rectangle([0, 0, border_width, HEIGHT], fill=border_color)
    # Right
    draw.rectangle([WIDTH - border_width, 0, WIDTH, HEIGHT], fill=border_color)

    return image

if __name__ == "__main__":
    print("Creating visual test of minimal default display...")
    
    # Create the default screen
    img = create_minimal_default()
    
    # Save it
    output_path = "/tmp/anima_default_display.png"
    img.save(output_path)
    
    print(f"✅ Saved to: {output_path}")
    print(f"   Size: {WIDTH}x{HEIGHT}")
    print(f"   Border: 2px, color (25, 35, 45)")
    print(f"   Background: Black (0, 0, 0)")
    print("\nThis shows what the Pi display will look like instead of grey!")
    print("The border is subtle but visible - confirming the display works.")
