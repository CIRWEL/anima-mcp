"""
Self-Schema Renderer R(G_t) - Renders self-schema to pixels.

Layout:
- Center: Identity node
- Ring 1 (radius ~50): 4 anima nodes at cardinal positions
- Ring 2 (radius ~80): 4 physical sensor nodes (light, temp, humidity, pressure)
- Ring 2b (radius ~100): 3 resource nodes (memory, cpu, disk)
- Ring 3 (radius ~110): Preference nodes (if present)

Colors:
- Identity: Gold
- Anima: Blue tones (varies by value)
- Sensors: Green tones (varies by value)
- Resources: Teal tones (varies by value)
- Edges: Green (positive) / Red (negative)

Can render to:
1. Dictionary of pixels (for canvas integration)
2. PNG file (for StructScore evaluation)
"""

from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
import math
import json
from pathlib import Path
from datetime import datetime

from .self_schema import SelfSchema, SchemaNode, SchemaEdge


# === Configuration ===

WIDTH = 240
HEIGHT = 240
CENTER = (WIDTH // 2, HEIGHT // 2)

# Ring radii
RING_1_RADIUS = 50   # Anima nodes
RING_2_RADIUS = 82   # Physical sensor nodes (tighter to fit more)
RING_2B_RADIUS = 102  # System resource nodes
RING_3_RADIUS = 112  # Preference nodes (outer ring)
RING_4_RADIUS = 118  # Belief nodes (outermost)

# Node sizes (radius)
IDENTITY_RADIUS = 14
ANIMA_RADIUS = 11
SENSOR_RADIUS = 9
RESOURCE_RADIUS = 8
PREFERENCE_RADIUS = 7
BELIEF_RADIUS = 6

# Colors (RGB)
COLORS = {
    "identity": (255, 200, 100),      # Gold
    "anima_high": (100, 150, 255),    # Bright blue (value > 0.6)
    "anima_mid": (80, 120, 200),      # Medium blue (0.4-0.6)
    "anima_low": (60, 90, 150),       # Dark blue (value < 0.4)
    "sensor": (100, 200, 100),        # Green
    "resource": (80, 180, 180),       # Teal for system resources
    "preference": (255, 150, 0),      # Orange for preferences
    "belief": (180, 180, 255),        # Lavender for beliefs
    "edge_positive": (100, 150, 100), # Green-gray for positive edges
    "edge_negative": (150, 100, 100), # Red-gray for negative edges
    "background": (20, 20, 30),       # Dark background
}

# VQA provider configurations (tried in order, free first)
_VQA_PROVIDERS = [
    {
        "name": "groq",
        "env_key": "GROQ_API_KEY",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "model": "meta-llama/llama-4-scout-17b-16e-instruct",
        "format": "openai",
    },
    {
        "name": "huggingface",
        "env_key": "HF_TOKEN",
        "url": "https://router.huggingface.co/hf-inference/models/meta-llama/Llama-3.2-11B-Vision-Instruct/v1/chat/completions",
        "model": "meta-llama/Llama-3.2-11B-Vision-Instruct",
        "format": "openai",
    },
    {
        "name": "together",
        "env_key": "TOGETHER_API_KEY",
        "url": "https://api.together.xyz/v1/chat/completions",
        "model": "Qwen/Qwen3-VL-8B-Instruct",
        "format": "openai",
    },
    {
        "name": "anthropic",
        "env_key": "ANTHROPIC_API_KEY",
        "url": "https://api.anthropic.com/v1/messages",
        "model": "claude-sonnet-4-20250514",
        "format": "anthropic",
    },
]


def _get_anima_color(value: float) -> Tuple[int, int, int]:
    """Get color for anima node based on value - brighter = higher value."""
    # Interpolate brightness based on value
    base_r, base_g, base_b = 60, 90, 150  # Base blue
    brightness = 0.4 + value * 0.6  # 0.4 to 1.0 range
    return (
        min(255, int(base_r + (255 - base_r) * value * 0.7)),
        min(255, int(base_g + (200 - base_g) * value * 0.8)),
        min(255, int(base_b + (255 - base_b) * value * 0.5)),
    )


def _get_sensor_color(value: float) -> Tuple[int, int, int]:
    """Get color for sensor node based on normalized value - brighter = higher."""
    # Floor: even at value=0, nodes should be visible (not black)
    v = max(0.25, value)
    base_r, base_g, base_b = 60, 150, 60  # Base green
    return (
        min(255, int(base_r + (180 - base_r) * v)),
        min(255, int(base_g + (255 - base_g) * v)),
        min(255, int(base_b + (180 - base_b) * v)),
    )


def _get_resource_color(value: float) -> Tuple[int, int, int]:
    """Get color for resource node based on usage value - teal tones."""
    # Floor: even at value=0, nodes should be visible (not black)
    v = max(0.25, value)
    base_r, base_g, base_b = 50, 130, 130  # Base teal
    return (
        min(255, int(base_r + (120 - base_r) * v)),
        min(255, int(base_g + (220 - base_g) * v)),
        min(255, int(base_b + (220 - base_b) * v)),
    )


def _draw_glow(
    pixels: Dict[Tuple[int, int], Tuple[int, int, int]],
    cx: int, cy: int, radius: int,
    color: Tuple[int, int, int],
    intensity: float,  # 0-1, how bright the glow
):
    """Draw a soft glow around a point for high-value nodes."""
    if intensity < 0.5:
        return  # No glow for low values

    glow_radius = radius + int(intensity * 4)  # Glow extends based on intensity
    for dy in range(-glow_radius, glow_radius + 1):
        for dx in range(-glow_radius, glow_radius + 1):
            dist_sq = dx * dx + dy * dy
            if dist_sq <= glow_radius * glow_radius and dist_sq > radius * radius:
                x, y = cx + dx, cy + dy
                if 0 <= x < WIDTH and 0 <= y < HEIGHT:
                    # Fade glow with distance
                    dist = math.sqrt(dist_sq)
                    fade = 1.0 - (dist - radius) / (glow_radius - radius)
                    glow_color = (
                        int(color[0] * fade * intensity * 0.5),
                        int(color[1] * fade * intensity * 0.5),
                        int(color[2] * fade * intensity * 0.5),
                    )
                    # Blend with existing
                    existing = pixels.get((x, y), COLORS["background"])
                    blended = (
                        min(255, existing[0] + glow_color[0]),
                        min(255, existing[1] + glow_color[1]),
                        min(255, existing[2] + glow_color[2]),
                    )
                    pixels[(x, y)] = blended


def _get_node_position(node: SchemaNode, index_in_ring: int, total_in_ring: int) -> Tuple[int, int]:
    """Calculate position for a node based on its type and ring."""
    cx, cy = CENTER

    if node.node_type == "identity":
        return cx, cy

    elif node.node_type == "anima":
        # Ring 1: anima at cardinal positions
        # Order: warmth (top), clarity (right), stability (bottom), presence (left)
        angles = [270, 0, 90, 180]  # degrees, 0 = right
        angle_rad = math.radians(angles[index_in_ring % 4])
        x = cx + int(RING_1_RADIUS * math.cos(angle_rad))
        y = cy + int(RING_1_RADIUS * math.sin(angle_rad))
        return x, y

    elif node.node_type == "sensor":
        # Ring 2: sensors positioned NEAR the anima node they primarily influence
        # Anima angles: warmth=270(top), clarity=0(right), stability=90(bottom), presence=180(left)
        # Temp→Warmth: near top         (250°)
        # Light→Clarity: near right      (340°)
        # Humidity→Stability: near bottom (70°)
        # Pressure→Stability: near bottom (110°)
        angles = [340, 250, 70, 110]  # Light, Temp, Humid, Press
        angle_rad = math.radians(angles[index_in_ring % len(angles)])
        x = cx + int(RING_2_RADIUS * math.cos(angle_rad))
        y = cy + int(RING_2_RADIUS * math.sin(angle_rad))
        return x, y

    elif node.node_type == "resource":
        # Ring 2b: resources positioned near Presence (left, 180°) and Stability (bottom, 90°)
        # Memory→Stability+Presence: between them (135°, bottom-left)
        # CPU→Presence: near left          (165°)
        # Disk→Presence: near left          (200°)
        angles = [135, 165, 200]  # Mem, CPU, Disk
        angle_rad = math.radians(angles[index_in_ring % len(angles)])
        x = cx + int(RING_2B_RADIUS * math.cos(angle_rad))
        y = cy + int(RING_2B_RADIUS * math.sin(angle_rad))
        return x, y

    elif node.node_type == "preference":
        # Ring 3: preferences evenly spaced around outer ring
        angle_step = 360.0 / total_in_ring if total_in_ring > 0 else 0
        angle = angle_step * index_in_ring
        angle_rad = math.radians(angle)
        x = cx + int(RING_3_RADIUS * math.cos(angle_rad))
        y = cy + int(RING_3_RADIUS * math.sin(angle_rad))
        return x, y

    elif node.node_type == "belief":
        # Ring 4: beliefs evenly spaced around outermost ring
        angle_step = 360.0 / total_in_ring if total_in_ring > 0 else 0
        angle = angle_step * index_in_ring
        angle_rad = math.radians(angle)
        x = cx + int(RING_4_RADIUS * math.cos(angle_rad))
        y = cy + int(RING_4_RADIUS * math.sin(angle_rad))
        return x, y

    return cx, cy


def _build_node_positions(schema: SelfSchema) -> Dict[str, Tuple[int, int]]:
    """Build position lookup for all nodes in the schema."""
    node_positions: Dict[str, Tuple[int, int]] = {}
    type_indices = {"anima": 0, "sensor": 0, "resource": 0, "preference": 0, "belief": 0}
    preference_count = sum(1 for n in schema.nodes if n.node_type == "preference")
    belief_count = sum(1 for n in schema.nodes if n.node_type == "belief")

    for node in schema.nodes:
        if node.node_type == "identity":
            pos = _get_node_position(node, 0, 1)
        elif node.node_type in type_indices:
            idx = type_indices[node.node_type]
            total = preference_count if node.node_type == "preference" else belief_count if node.node_type == "belief" else 0
            pos = _get_node_position(node, idx, total)
            type_indices[node.node_type] += 1
        else:
            pos = CENTER
        node_positions[node.node_id] = pos

    return node_positions


def _draw_filled_circle(
    pixels: Dict[Tuple[int, int], Tuple[int, int, int]],
    cx: int, cy: int, radius: int,
    color: Tuple[int, int, int],
):
    """Draw a filled circle."""
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx * dx + dy * dy <= radius * radius:
                x, y = cx + dx, cy + dy
                if 0 <= x < WIDTH and 0 <= y < HEIGHT:
                    pixels[(x, y)] = color


def _draw_line(
    pixels: Dict[Tuple[int, int], Tuple[int, int, int]],
    x0: int, y0: int, x1: int, y1: int,
    color: Tuple[int, int, int],
    thickness: int = 1,
):
    """
    Draw a line using Bresenham's algorithm with optional thickness.
    
    For thickness > 1, draws multiple parallel lines.
    """
    if thickness == 1:
        # Original single-pixel line
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy

        x, y = x0, y0

        while True:
            if 0 <= x < WIDTH and 0 <= y < HEIGHT:
                pixels[(x, y)] = color

            if x == x1 and y == y1:
                break

            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy
    else:
        # Thick line: draw multiple parallel lines
        # Calculate perpendicular direction
        dx = x1 - x0
        dy = y1 - y0
        length = math.sqrt(dx * dx + dy * dy)
        if length == 0:
            return
        
        # Perpendicular unit vector
        perp_x = -dy / length
        perp_y = dx / length
        
        # Draw multiple lines offset perpendicularly
        for offset in range(-thickness // 2, thickness // 2 + 1):
            offset_x = int(perp_x * offset)
            offset_y = int(perp_y * offset)
            _draw_line(pixels, x0 + offset_x, y0 + offset_y, x1 + offset_x, y1 + offset_y, color, thickness=1)


def render_schema_to_pixels(schema: SelfSchema) -> Dict[Tuple[int, int], Tuple[int, int, int]]:
    """
    Render G_t to pixel dictionary.

    This is the main rendering function R(G_t).

    Args:
        schema: The self-schema to render

    Returns:
        Dictionary mapping (x, y) -> (r, g, b)
    """
    pixels: Dict[Tuple[int, int], Tuple[int, int, int]] = {}

    if not schema.nodes:
        return pixels

    node_positions = _build_node_positions(schema)

    # Draw edges first (underneath nodes) - thicker and more visible
    for edge in schema.edges:
        if edge.source_id in node_positions and edge.target_id in node_positions:
            x0, y0 = node_positions[edge.source_id]
            x1, y1 = node_positions[edge.target_id]

            # Color based on weight - brighter for stronger connections
            weight_magnitude = abs(edge.weight)
            if edge.weight >= 0:
                # Positive: green, brighter with strength
                brightness = 0.5 + weight_magnitude * 0.5
                color = (
                    int(80 * brightness),
                    int(180 * brightness),
                    int(80 * brightness),
                )
            else:
                # Negative: red, brighter with strength
                brightness = 0.5 + weight_magnitude * 0.5
                color = (
                    int(180 * brightness),
                    int(80 * brightness),
                    int(80 * brightness),
                )

            # Thickness based on weight magnitude (2-4 pixels) - more visible
            thickness = max(2, min(4, int(weight_magnitude * 4) + 2))

            _draw_line(pixels, x0, y0, x1, y1, color, thickness=thickness)

    # Draw glows first (underneath nodes)
    for node in schema.nodes:
        if node.node_id not in node_positions:
            continue
        x, y = node_positions[node.node_id]

        if node.node_type == "identity":
            _draw_glow(pixels, x, y, IDENTITY_RADIUS, COLORS["identity"], 0.8)
        elif node.node_type == "anima":
            color = _get_anima_color(node.value)
            _draw_glow(pixels, x, y, ANIMA_RADIUS, color, node.value)
        elif node.node_type == "sensor":
            color = _get_sensor_color(node.value)
            _draw_glow(pixels, x, y, SENSOR_RADIUS, color, node.value)
        elif node.node_type == "resource":
            color = _get_resource_color(node.value)
            _draw_glow(pixels, x, y, RESOURCE_RADIUS, color, node.value)
        elif node.node_type == "preference":
            _draw_glow(pixels, x, y, PREFERENCE_RADIUS, COLORS["preference"], 0.6)
        elif node.node_type == "belief":
            _draw_glow(pixels, x, y, BELIEF_RADIUS, COLORS["belief"], 0.5)

    # Draw nodes
    for node in schema.nodes:
        if node.node_id not in node_positions:
            continue

        x, y = node_positions[node.node_id]

        if node.node_type == "identity":
            _draw_filled_circle(pixels, x, y, IDENTITY_RADIUS, COLORS["identity"])
        elif node.node_type == "anima":
            color = _get_anima_color(node.value)
            _draw_filled_circle(pixels, x, y, ANIMA_RADIUS, color)
        elif node.node_type == "sensor":
            color = _get_sensor_color(node.value)
            _draw_filled_circle(pixels, x, y, SENSOR_RADIUS, color)
        elif node.node_type == "resource":
            color = _get_resource_color(node.value)
            _draw_filled_circle(pixels, x, y, RESOURCE_RADIUS, color)
        elif node.node_type == "preference":
            _draw_filled_circle(pixels, x, y, PREFERENCE_RADIUS, COLORS["preference"])
        elif node.node_type == "belief":
            _draw_filled_circle(pixels, x, y, BELIEF_RADIUS, COLORS["belief"])

    return pixels


def render_to_canvas(schema: SelfSchema, canvas_state) -> int:
    """
    Render G_t directly to Lumen's canvas.

    Args:
        schema: The self-schema to render
        canvas_state: CanvasState instance from screens.py

    Returns:
        Number of pixels drawn
    """
    pixels = render_schema_to_pixels(schema)

    # Clear and draw
    canvas_state.clear()
    for (x, y), color in pixels.items():
        canvas_state.draw_pixel(x, y, color)

    # Mark as a structured render
    canvas_state.drawing_phase = "schema_render"

    return len(pixels)


def save_render_to_file(
    schema: SelfSchema,
    output_dir: Optional[Path] = None,
) -> Tuple[Path, Path]:
    """
    Save rendered schema as PNG and JSON for offline StructScore evaluation.

    Args:
        schema: The self-schema to render
        output_dir: Directory to save files (default: ~/.anima/schema_renders/)

    Returns:
        Tuple of (png_path, json_path)
    """
    if output_dir is None:
        output_dir = Path.home() / ".anima" / "schema_renders"

    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate timestamp-based filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    png_path = output_dir / f"schema_{timestamp}.png"
    json_path = output_dir / f"schema_{timestamp}.json"

    # Render to pixels
    pixels = render_schema_to_pixels(schema)

    # Try to save PNG (requires PIL)
    try:
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new("RGB", (WIDTH, HEIGHT), COLORS["background"])
        for (x, y), color in pixels.items():
            img.putpixel((x, y), color)

        # Add node labels for VQA readability
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
        except (OSError, IOError):
            font = ImageFont.load_default()

        node_positions = _build_node_positions(schema)
        for node in schema.nodes:
            x, y = node_positions[node.node_id]
            label = node.label
            bbox = draw.textbbox((0, 0), label, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            lx = max(1, min(WIDTH - tw - 1, x - tw // 2))
            ly = y + 10  # below node
            if ly + th > HEIGHT - 2:
                ly = y - th - 4  # above if at bottom
            draw.text((lx, ly), label, fill=(200, 200, 200), font=font)

        img.save(png_path)
    except ImportError:
        # PIL not available - save pixels as JSON instead
        png_path = output_dir / f"schema_{timestamp}_pixels.json"
        with open(png_path, "w") as f:
            # Convert tuple keys to strings for JSON
            pixel_data = {f"{x},{y}": list(color) for (x, y), color in pixels.items()}
            json.dump(pixel_data, f)

    # Save schema JSON with VQA ground truth
    schema_data = schema.to_dict()
    schema_data["vqa_ground_truth"] = schema.generate_vqa_ground_truth()
    schema_data["render_metadata"] = {
        "width": WIDTH,
        "height": HEIGHT,
        "node_count": len(schema.nodes),
        "edge_count": len(schema.edges),
        "pixel_count": len(pixels),
    }

    with open(json_path, "w") as f:
        json.dump(schema_data, f, indent=2)

    return png_path, json_path


# === StructScore Stub ===

def compute_visual_integrity_stub(
    rendered_pixels: Dict[Tuple[int, int], Tuple[int, int, int]],
    schema: SelfSchema,
) -> Dict[str, float]:
    """
    Stub for visual integrity computation V(t).

    In production, this would call a remote StructScore service.
    For PoC, we compute basic consistency metrics locally.

    Args:
        rendered_pixels: The rendered pixel dictionary
        schema: Ground truth schema

    Returns:
        Dictionary with v_f (factuality proxy), v_c (constraint proxy), V (combined)
    """
    if not schema.nodes or not rendered_pixels:
        return {"v_f": 0.0, "v_c": 0.0, "V": 0.0, "stub": True}

    # v_f proxy: Check that we rendered roughly the expected number of pixels
    # Each node contributes ~πr² pixels
    expected_pixels = 0
    for node in schema.nodes:
        if node.node_type == "identity":
            expected_pixels += int(math.pi * IDENTITY_RADIUS ** 2)
        elif node.node_type == "anima":
            expected_pixels += int(math.pi * ANIMA_RADIUS ** 2)
        elif node.node_type == "sensor":
            expected_pixels += int(math.pi * SENSOR_RADIUS ** 2)
        elif node.node_type == "resource":
            expected_pixels += int(math.pi * RESOURCE_RADIUS ** 2)
        elif node.node_type == "preference":
            expected_pixels += int(math.pi * PREFERENCE_RADIUS ** 2)

    # Add ~10% for edges
    expected_pixels = int(expected_pixels * 1.1)

    actual_pixels = len(rendered_pixels)
    v_f = min(1.0, min(actual_pixels, expected_pixels) / max(actual_pixels, expected_pixels, 1))

    # v_c proxy: Check color consistency (all pixels should be valid colors)
    valid_colors = set(COLORS.values())
    valid_count = 0
    for color in rendered_pixels.values():
        # Check if color is close to any valid color
        for valid in valid_colors:
            if all(abs(c1 - c2) < 50 for c1, c2 in zip(color, valid)):
                valid_count += 1
                break

    v_c = valid_count / max(len(rendered_pixels), 1)

    # Combined score (StructScore uses 0.9/0.1, we use 0.6/0.4 for generation)
    V = 0.6 * v_f + 0.4 * v_c

    return {
        "v_f": round(v_f, 3),
        "v_c": round(v_c, 3),
        "V": round(V, 3),
        "expected_pixels": expected_pixels,
        "actual_pixels": actual_pixels,
        "stub": True,  # Flag that this is not real StructScore
    }


# === Real VQA Evaluation ===

async def evaluate_vqa(
    png_path: Path,
    ground_truth: List[Dict[str, Any]],
    max_questions: int = 5,
) -> Dict[str, Any]:
    """
    Real VQA evaluation using vision-capable LLM.

    Provider priority (free first):
    1. Groq (GROQ_API_KEY) - llama-4-scout-17b (FREE)
    2. Together AI (TOGETHER_API_KEY) - Llama-Vision-Free (FREE)
    3. Anthropic (ANTHROPIC_API_KEY) - claude-sonnet (PAID, fallback)

    Args:
        png_path: Path to rendered schema PNG
        ground_truth: List of {"question": str, "answer": str, "type": str}
        max_questions: Maximum questions to evaluate (cost control)

    Returns:
        Dictionary with v_f (factuality), correct_count, total_count, details
    """
    import os
    import base64

    # Load and encode image
    try:
        with open(png_path, "rb") as f:
            image_data = base64.standard_b64encode(f.read()).decode("utf-8")
    except Exception as e:
        return {"v_f": None, "error": f"Failed to load image: {e}"}

    # Sample questions (prioritize counting and existence)
    questions = ground_truth[:max_questions]
    if len(ground_truth) > max_questions:
        counting = [q for q in ground_truth if q["type"] == "counting"]
        existence = [q for q in ground_truth if q["type"] == "existence"]
        attribute = [q for q in ground_truth if q["type"] == "attribute"]
        sampled = counting[:2] + existence[:2] + attribute[:1]
        if len(sampled) < max_questions:
            remaining = [q for q in ground_truth if q not in sampled]
            sampled += remaining[:max_questions - len(sampled)]
        questions = sampled[:max_questions]

    # Build prompt
    prompt = """Look at this graph visualization and answer the following questions.
Answer each question with ONLY the answer (a number, 'yes', 'no', or the value asked for).
Do not explain or add extra text.

Questions:
"""
    for i, q in enumerate(questions, 1):
        prompt += f"{i}. {q['question']}\n"
    prompt += "\nProvide answers in this format:\n1. [answer]\n2. [answer]\n..."

    # Build provider list from config (free first)
    providers = []
    for cfg in _VQA_PROVIDERS:
        key = os.environ.get(cfg["env_key"])
        if key:
            providers.append({**cfg, "api_key": key})

    if not providers:
        return {
            "v_f": None,
            "error": "No vision API key set (GROQ_API_KEY, TOGETHER_API_KEY, or HF_TOKEN). Get free key at groq.com",
            "stub_fallback": True,
        }

    # Try each provider
    last_error = None
    for config in providers:
        try:
            answer_text = await _call_vision_provider(config, image_data, prompt)
            if answer_text:
                return _parse_vqa_response(answer_text, questions, config["name"])
        except Exception as e:
            last_error = str(e)
            continue

    return {"v_f": None, "error": f"All providers failed: {last_error}"}


async def _call_vision_provider(
    config: Dict[str, str],
    image_data: str,
    prompt: str,
) -> Optional[str]:
    """Call a vision-capable LLM provider using config from _VQA_PROVIDERS."""
    import httpx

    async with httpx.AsyncClient(timeout=30.0) as client:
        if config["format"] == "openai":
            response = await client.post(
                config["url"],
                headers={
                    "Authorization": f"Bearer {config['api_key']}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": config["model"],
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/png;base64,{image_data}",
                                    },
                                },
                                {"type": "text", "text": prompt},
                            ],
                        }
                    ],
                    "max_tokens": 256,
                },
            )
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
            raise Exception(f"{config['name']} API error {response.status_code}: {response.text[:200]}")

        elif config["format"] == "anthropic":
            response = await client.post(
                config["url"],
                headers={
                    "x-api-key": config["api_key"],
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": config["model"],
                    "max_tokens": 256,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": image_data,
                                    },
                                },
                                {"type": "text", "text": prompt},
                            ],
                        }
                    ],
                },
            )
            if response.status_code == 200:
                return response.json()["content"][0]["text"]
            raise Exception(f"Anthropic API error {response.status_code}: {response.text[:200]}")

    return None


def _parse_vqa_response(
    answer_text: str,
    questions: List[Dict[str, Any]],
    model: str,
) -> Dict[str, Any]:
    """Parse VQA response and compute accuracy."""
    lines = answer_text.strip().split("\n")
    model_answers = []
    for line in lines:
        line = line.strip()
        if line and line[0].isdigit():
            parts = line.split(".", 1) if "." in line else line.split(")", 1)
            if len(parts) > 1:
                model_answers.append(parts[1].strip().lower())
            else:
                model_answers.append(line.lower())

    correct = 0
    details = []
    for i, q in enumerate(questions):
        expected = q["answer"].lower()
        got = model_answers[i] if i < len(model_answers) else ""

        is_correct = (
            got == expected or
            expected in got or
            (expected.isdigit() and got.startswith(expected))
        )

        if is_correct:
            correct += 1

        details.append({
            "question": q["question"],
            "expected": expected,
            "got": got,
            "correct": is_correct,
        })

    v_f = correct / len(questions) if questions else 0.0

    return {
        "v_f": round(v_f, 3),
        "correct_count": correct,
        "total_count": len(questions),
        "details": details,
        "model": model,
        "stub": False,
    }
