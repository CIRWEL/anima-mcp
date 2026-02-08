"""
Geometric Phase - Art Movement Capsule
=======================================

Lumen's first art period: Jan 13 - Feb 7, 2026
637 drawings. 16 shape templates. Complete forms stamped whole.

Character:
  - Circles dominant (~25% of output)
  - Each template places 50-3400 pixels in one call
  - Forms appear complete, not built up
  - Spirals, arcs, layered compositions, organic blobs
  - 3-10 minutes per piece, ~300 drawings/day

Preserved for future art movement integration.
These were instance methods on ScreenRenderer, placing pixels
via self._canvas.draw_pixel(x, y, color) on a 240x240 canvas.

Source: git show ed0067d^:src/anima_mcp/display/screens.py
"""

# Style weights from the old _lumen_draw dispatch:
#
# styles = [
#   "circle", "gradient_circle", "spiral", "line", "curve",
#   "pattern", "organic", "layered", "rectangle", "triangle",
#   "wave", "rings", "arc", "starburst", "drip", "scatter"
# ]
#
# Weights influenced by clarity (more complex shapes),
# stability (more structured shapes), and expression mood.


def _draw_circle(cx: int, cy: int, radius: int, color: Tuple[int, int, int]):
    """Draw a filled circle."""
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            if dx*dx + dy*dy <= radius*radius:
                px, py = cx + dx, cy + dy
                if 0 <= px < 240 and 0 <= py < 240:
                    canvas.draw_pixel(px, py, color)


def _draw_circle_gradient(cx: int, cy: int, radius: int, base_color: Tuple[int, int, int], clarity: float):
    """Draw a circle with gradient fill - more vibrant at center."""
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            dist_sq = dx*dx + dy*dy
            if dist_sq <= radius*radius:
                # Gradient: brighter at center, dimmer at edges
                dist = math.sqrt(dist_sq)
                if radius > 0:
                    gradient = 1.0 - (dist / radius) * 0.4  # 60-100% brightness
                else:
                    gradient = 1.0
                # Apply clarity to gradient intensity
                gradient = gradient * (0.7 + clarity * 0.3)
                color = tuple(int(c * gradient) for c in base_color)
                px, py = cx + dx, cy + dy
                if 0 <= px < 240 and 0 <= py < 240:
                    canvas.draw_pixel(px, py, color)


def _draw_spiral(cx: int, cy: int, max_radius: int, color: Tuple[int, int, int], tightness: float):
    """Draw a spiral."""
    import math
    turns = 2 + int(tightness * 3)
    steps = turns * 20
    for i in range(steps):
        angle = i * 2 * math.pi / 20
        radius = (i / steps) * max_radius
        x = int(cx + radius * math.cos(angle))
        y = int(cy + radius * math.sin(angle))
        if 0 <= x < 240 and 0 <= y < 240:
            canvas.draw_pixel(x, y, color)


def _draw_line(x1: int, y1: int, x2: int, y2: int, color: Tuple[int, int, int]):
    """Draw a line using Bresenham's algorithm."""
    dx = abs(x2 - x1)
    dy = abs(y2 - y1)
    sx = 1 if x1 < x2 else -1
    sy = 1 if y1 < y2 else -1
    err = dx - dy
    
    x, y = x1, y1
    while True:
        if 0 <= x < 240 and 0 <= y < 240:
            canvas.draw_pixel(x, y, color)
        if x == x2 and y == y2:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x += sx
        if e2 < dx:
            err += dx
            y += sy


def _draw_curve(x1: int, y1: int, x2: int, y2: int, color: Tuple[int, int, int], width: int):
    """Draw a curved line (bezier-like)."""
    import random
    # Control point for curve
    mid_x = (x1 + x2) // 2 + random.randint(-30, 30)
    mid_y = (y1 + y2) // 2 + random.randint(-30, 30)
    
    # Draw curve as series of line segments
    steps = 20
    for i in range(steps + 1):
        t = i / steps
        # Quadratic bezier
        x = int((1-t)*(1-t)*x1 + 2*(1-t)*t*mid_x + t*t*x2)
        y = int((1-t)*(1-t)*y1 + 2*(1-t)*t*mid_y + t*t*y2)
        if 0 <= x < 240 and 0 <= y < 240:
            # Draw with width
            for wx in range(-width//2, width//2 + 1):
                for wy in range(-width//2, width//2 + 1):
                    px, py = x + wx, y + wy
                    if 0 <= px < 240 and 0 <= py < 240:
                        canvas.draw_pixel(px, py, color)


def _draw_arc(cx: int, cy: int, radius: int, start_angle: float,
              arc_length: float, color: Tuple[int, int, int]):
    """Draw an arc (partial circle)."""
    import math
    steps = int(arc_length * radius / 2)  # More steps for larger arcs
    for i in range(max(1, steps)):
        angle = start_angle + (i / max(1, steps)) * arc_length
        x = int(cx + radius * math.cos(angle))
        y = int(cy + radius * math.sin(angle))
        if 0 <= x < 240 and 0 <= y < 240:
            canvas.draw_pixel(x, y, color)


def _draw_wave(start_x: int, y_center: int, amplitude: int,
               wavelength: int, color: Tuple[int, int, int]):
    """Draw a horizontal sine wave."""
    import math
    for x in range(max(0, start_x), min(240, start_x + 100)):
        y = int(y_center + amplitude * math.sin((x - start_x) * 2 * math.pi / wavelength))
        if 0 <= y < 240:
            canvas.draw_pixel(x, y, color)
            # Make wave thicker
            if 0 <= y + 1 < 240:
                canvas.draw_pixel(x, y + 1, color)


def _draw_rings(cx: int, cy: int, num_rings: int, max_radius: int,
                color: Tuple[int, int, int]):
    """Draw concentric rings."""
    import math
    for ring in range(1, num_rings + 1):
        radius = int(ring * max_radius / num_rings)
        # Draw circle outline
        for angle in range(0, 360, 3):  # Every 3 degrees
            rad = math.radians(angle)
            x = int(cx + radius * math.cos(rad))
            y = int(cy + radius * math.sin(rad))
            if 0 <= x < 240 and 0 <= y < 240:
                canvas.draw_pixel(x, y, color)


def _draw_starburst(cx: int, cy: int, num_rays: int, ray_length: int,
                    color: Tuple[int, int, int]):
    """Draw a starburst pattern - rays emanating from center."""
    import math
    for i in range(num_rays):
        angle = (i / num_rays) * 2 * math.pi
        for r in range(1, ray_length + 1):
            x = int(cx + r * math.cos(angle))
            y = int(cy + r * math.sin(angle))
            if 0 <= x < 240 and 0 <= y < 240:
                canvas.draw_pixel(x, y, color)
    # Center dot
    if 0 <= cx < 240 and 0 <= cy < 240:
        canvas.draw_pixel(cx, cy, color)


def _draw_pattern(cx: int, cy: int, size: int, color: Tuple[int, int, int]):
    """Draw a simple pattern (cross, star, etc.)."""
    import random
    import math
    pattern_type = random.choice(['cross', 'star', 'grid'])
    
    if pattern_type == 'cross':
        # Cross pattern
        for i in range(-size, size + 1):
            if 0 <= cx + i < 240 and 0 <= cy < 240:
                canvas.draw_pixel(cx + i, cy, color)
            if 0 <= cx < 240 and 0 <= cy + i < 240:
                canvas.draw_pixel(cx, cy + i, color)
    elif pattern_type == 'star':
        # Star pattern (4 directions)
        for angle in [0, math.pi/2, math.pi, 3*math.pi/2]:
            for r in range(1, size + 1):
                x = int(cx + r * math.cos(angle))
                y = int(cy + r * math.sin(angle))
                if 0 <= x < 240 and 0 <= y < 240:
                    canvas.draw_pixel(x, y, color)
    else:  # grid
        # Small grid
        for i in range(-size, size + 1, 2):
            for j in range(-size, size + 1, 2):
                x, y = cx + i, cy + j
                if 0 <= x < 240 and 0 <= y < 240:
                    canvas.draw_pixel(x, y, color)


def _draw_rectangle(cx: int, cy: int, width: int, height: int,
                    color: Tuple[int, int, int], filled: bool = True):
    """Draw a rectangle (filled or outline)."""
    x1, y1 = cx - width // 2, cy - height // 2
    x2, y2 = cx + width // 2, cy + height // 2

    if filled:
        for x in range(max(0, x1), min(240, x2 + 1)):
            for y in range(max(0, y1), min(240, y2 + 1)):
                canvas.draw_pixel(x, y, color)
    else:
        # Draw outline only
        for x in range(max(0, x1), min(240, x2 + 1)):
            if 0 <= y1 < 240:
                canvas.draw_pixel(x, y1, color)
            if 0 <= y2 < 240:
                canvas.draw_pixel(x, y2, color)
        for y in range(max(0, y1), min(240, y2 + 1)):
            if 0 <= x1 < 240:
                canvas.draw_pixel(x1, y, color)
            if 0 <= x2 < 240:
                canvas.draw_pixel(x2, y, color)


def _draw_triangle(cx: int, cy: int, size: int, color: Tuple[int, int, int]):
    """Draw a filled triangle pointing up."""
    import math
    # Three vertices of equilateral triangle
    for y_offset in range(size):
        # Width at this height
        width_at_y = int((y_offset / size) * size)
        y = cy + y_offset - size // 2
        for x_offset in range(-width_at_y // 2, width_at_y // 2 + 1):
            x = cx + x_offset
            if 0 <= x < 240 and 0 <= y < 240:
                canvas.draw_pixel(x, y, color)


def _draw_organic_shape(cx: int, cy: int, color: Tuple[int, int, int], clarity: float, stability: float):
    """Draw organic, flowing shapes - like clouds or blobs."""
    import random
    import math
    
    # Create irregular blob shape
    num_points = int(6 + clarity * 4)
    points = []
    base_radius = int(8 + stability * 15)
    
    for i in range(num_points):
        angle = (i / num_points) * 2 * math.pi
        radius_variation = random.uniform(0.7, 1.3)
        radius = base_radius * radius_variation
        x = int(cx + radius * math.cos(angle))
        y = int(cy + radius * math.sin(angle))
        points.append((x, y))
    
    # Fill the shape
    for dx in range(-base_radius * 2, base_radius * 2 + 1):
        for dy in range(-base_radius * 2, base_radius * 2 + 1):
            px, py = cx + dx, cy + dy
            if 0 <= px < 240 and 0 <= py < 240:
                # Check if point is inside the blob (simple distance check)
                dist = math.sqrt(dx*dx + dy*dy)
                if dist < base_radius * 1.2:
                    # Add some randomness for organic feel
                    if random.random() < 0.85:
                        canvas.draw_pixel(px, py, color)


def _draw_layered_composition(cx: int, cy: int, base_color: Tuple[int, int, int], clarity: float, stability: float):
    """Draw layered composition - multiple elements working together."""
    import random
    
    # Create 2-3 related elements
    num_elements = random.randint(2, 3)
    for i in range(num_elements):
        # Vary color slightly for each layer
        color_variation = random.uniform(0.8, 1.0)
        layer_color = tuple(int(c * color_variation) for c in base_color)
        
        # Offset position
        offset_x = random.randint(-30, 30)
        offset_y = random.randint(-30, 30)
        x = cx + offset_x
        y = cy + offset_y
        
        # Different shapes for each layer
        if i == 0:
            # Base layer - larger circle
            size = int(6 + stability * 12)
            self._draw_circle(x, y, size, layer_color)
        elif i == 1:
            # Middle layer - smaller circle or pattern
            if random.random() < 0.5:
                size = int(3 + stability * 6)
                self._draw_circle(x, y, size, layer_color)
            else:
                self._draw_pattern(x, y, int(2 + clarity * 3), layer_color)
        else:
            # Top layer - accent dots or small shapes
            for _ in range(random.randint(2, 4)):
                dot_x = x + random.randint(-10, 10)
                dot_y = y + random.randint(-10, 10)
                if 0 <= dot_x < 240 and 0 <= dot_y < 240:
                    canvas.draw_pixel(dot_x, dot_y, layer_color)

# === NEW SHAPE DRAWING METHODS ===


def _draw_scatter(cx: int, cy: int, num_particles: int,
                  spread: int, color: Tuple[int, int, int]):
    """Draw scattered particles in a cluster."""
    import random
    for _ in range(num_particles):
        # Gaussian-ish distribution - more dense at center
        dx = int(random.gauss(0, spread / 3))
        dy = int(random.gauss(0, spread / 3))
        x = cx + dx
        y = cy + dy
        if 0 <= x < 240 and 0 <= y < 240:
            canvas.draw_pixel(x, y, color)


def _draw_drip(x: int, start_y: int, length: int,
               color: Tuple[int, int, int], stability: float):
    """Draw a drip/random walk flowing downward."""
    import random
    current_x = x
    wobble = int(3 + (1.0 - stability) * 8)  # Less stable = more wobble

    for y in range(start_y, min(240, start_y + length)):
        if 0 <= current_x < 240:
            canvas.draw_pixel(current_x, y, color)
        # Random walk sideways
        current_x += random.randint(-wobble, wobble)
        current_x = max(0, min(239, current_x))


