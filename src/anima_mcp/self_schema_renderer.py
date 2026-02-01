"""
Self-Schema Renderer R(G_t) - Renders self-schema to pixels.

PoC Version: Simple concentric layout for 8 nodes.

Layout:
- Center: Identity node
- Ring 1 (radius ~50): 4 anima nodes at cardinal positions
- Ring 2 (radius ~90): 3 sensor nodes

Colors:
- Identity: Gold (255, 200, 100)
- Anima: Blue tones (varies by value)
- Sensors: Green (100, 200, 100)
- Edges: Gray lines

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
RING_1_RADIUS = 50  # Anima nodes
RING_2_RADIUS = 90  # Sensor nodes
RING_3_RADIUS = 110  # Preference nodes (outer ring)

# Node sizes (radius)
IDENTITY_RADIUS = 15
ANIMA_RADIUS = 12
SENSOR_RADIUS = 10
PREFERENCE_RADIUS = 8  # Smaller for outer ring

# Colors (RGB)
COLORS = {
    "identity": (255, 200, 100),      # Gold
    "anima_high": (100, 150, 255),    # Bright blue (value > 0.6)
    "anima_mid": (80, 120, 200),      # Medium blue (0.4-0.6)
    "anima_low": (60, 90, 150),       # Dark blue (value < 0.4)
    "sensor": (100, 200, 100),        # Green
    "preference": (255, 150, 0),      # Orange for preferences
    "edge_positive": (100, 150, 100), # Green-gray for positive edges
    "edge_negative": (150, 100, 100), # Red-gray for negative edges
    "background": (20, 20, 30),       # Dark background
}


def _get_anima_color(value: float) -> Tuple[int, int, int]:
    """Get color for anima node based on value."""
    if value > 0.6:
        return COLORS["anima_high"]
    elif value < 0.4:
        return COLORS["anima_low"]
    else:
        return COLORS["anima_mid"]


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
        # Ring 2: sensors at 45, 135, 225 degrees (between anima nodes)
        angles = [315, 45, 135]  # Light at top-right, temp at bottom-right, humidity at bottom-left
        angle_rad = math.radians(angles[index_in_ring % 3])
        x = cx + int(RING_2_RADIUS * math.cos(angle_rad))
        y = cy + int(RING_2_RADIUS * math.sin(angle_rad))
        return x, y

    elif node.node_type == "preference":
        # Ring 3: preferences evenly spaced around outer ring
        angle_step = 360.0 / total_in_ring if total_in_ring > 0 else 0
        angle = angle_step * index_in_ring
        angle_rad = math.radians(angle)
        x = cx + int(RING_3_RADIUS * math.cos(angle_rad))
        y = cy + int(RING_3_RADIUS * math.sin(angle_rad))
        return x, y

    return cx, cy


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

    # Build node positions
    node_positions: Dict[str, Tuple[int, int]] = {}

    # Count nodes by type for positioning
    anima_index = 0
    sensor_index = 0
    preference_index = 0
    preference_count = sum(1 for n in schema.nodes if n.node_type == "preference")

    for node in schema.nodes:
        if node.node_type == "identity":
            pos = _get_node_position(node, 0, 1)
        elif node.node_type == "anima":
            pos = _get_node_position(node, anima_index, 4)
            anima_index += 1
        elif node.node_type == "sensor":
            pos = _get_node_position(node, sensor_index, 3)
            sensor_index += 1
        elif node.node_type == "preference":
            pos = _get_node_position(node, preference_index, preference_count)
            preference_index += 1
        else:
            pos = CENTER

        node_positions[node.node_id] = pos

    # Draw edges first (underneath nodes)
    for edge in schema.edges:
        if edge.source_id in node_positions and edge.target_id in node_positions:
            x0, y0 = node_positions[edge.source_id]
            x1, y1 = node_positions[edge.target_id]

            # Color based on weight sign
            if edge.weight >= 0:
                color = COLORS["edge_positive"]
            else:
                color = COLORS["edge_negative"]

            # Thickness based on weight magnitude (1-3 pixels)
            weight_magnitude = abs(edge.weight)
            thickness = max(1, min(3, int(weight_magnitude * 3) + 1))

            _draw_line(pixels, x0, y0, x1, y1, color, thickness=thickness)

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
            _draw_filled_circle(pixels, x, y, SENSOR_RADIUS, COLORS["sensor"])
        elif node.node_type == "preference":
            _draw_filled_circle(pixels, x, y, PREFERENCE_RADIUS, COLORS["preference"])

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
        from PIL import Image

        img = Image.new("RGB", (WIDTH, HEIGHT), COLORS["background"])
        for (x, y), color in pixels.items():
            img.putpixel((x, y), color)

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
    1. Groq (GROQ_API_KEY) - llama-3.2-11b-vision-preview (FREE)
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

    # Try providers in order (free first)
    providers = []

    # 1. Hugging Face Inference API (FREE) - Llama 3.2 Vision or LLaVA
    if os.environ.get("HF_TOKEN"):
        providers.append(("huggingface", os.environ["HF_TOKEN"]))

    # 2. Together AI (FREE tier) - Llama Vision Free
    if os.environ.get("TOGETHER_API_KEY"):
        providers.append(("together", os.environ["TOGETHER_API_KEY"]))

    # 3. Anthropic (PAID fallback)
    if os.environ.get("ANTHROPIC_API_KEY"):
        providers.append(("anthropic", os.environ["ANTHROPIC_API_KEY"]))

    if not providers:
        return {
            "v_f": None,
            "error": "No vision API key set (TOGETHER_API_KEY or ANTHROPIC_API_KEY). Get free key at together.ai",
            "stub_fallback": True,
        }

    # Try each provider
    import httpx
    last_error = None

    for provider_name, api_key in providers:
        try:
            answer_text = await _call_vision_provider(
                provider_name, api_key, image_data, prompt
            )
            if answer_text:
                # Parse and score
                return _parse_vqa_response(answer_text, questions, provider_name)
        except Exception as e:
            last_error = str(e)
            continue

    return {"v_f": None, "error": f"All providers failed: {last_error}"}


async def _call_vision_provider(
    provider: str,
    api_key: str,
    image_data: str,
    prompt: str,
) -> Optional[str]:
    """Call a vision-capable LLM provider."""
    import httpx

    async with httpx.AsyncClient(timeout=30.0) as client:
        if provider == "huggingface":
            # Hugging Face Inference API - Llama 3.2 Vision
            # Uses the new router endpoint for serverless inference
            model = "meta-llama/Llama-3.2-11B-Vision-Instruct"
            response = await client.post(
                f"https://router.huggingface.co/hf-inference/models/{model}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
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
            elif response.status_code == 503:
                # Model loading - try fallback
                raise Exception("HF model loading, trying fallback...")
            else:
                raise Exception(f"HF API error {response.status_code}: {response.text[:200]}")

        elif provider == "together":
            # Together AI with Qwen3-VL-8B (serverless, pay-per-use)
            response = await client.post(
                "https://api.together.xyz/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "Qwen/Qwen3-VL-8B-Instruct",
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
            else:
                raise Exception(f"Together API error {response.status_code}: {response.text[:200]}")

        elif provider == "anthropic":
            # Anthropic Claude (PAID)
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
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
            else:
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
