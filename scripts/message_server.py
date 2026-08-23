#!/usr/bin/env python3
"""
Lumen Control Server - Bridges the Control Center to Lumen on the Pi.

Endpoints:
  POST /message - Send a message to Lumen
  GET /state    - Get Lumen's current state (anima, identity, sensors)
  GET /qa       - Get questions and answers
  POST /answer  - Answer a question from Lumen

Connection methods (in order of preference):
  1. HTTP to Pi's anima-mcp server (via LUMEN_HTTP_URL env var or Cloudflare tunnel)
  2. SSH fallback (via LUMEN_HOST env var)
"""
import http.server
import socketserver
import json
import subprocess
import os
import base64
import hmac
import urllib.request
import urllib.error
from urllib.parse import unquote, urlsplit

# 8771, not 8768: the UNITARES gateway (`com.unitares.gateway-mcp`) is allocated
# 8768 and binds 127.0.0.1 there. The relay now also defaults to loopback; the
# distinct port prevents loopback dials resolving to the gateway — which broke the Control
# Center whenever control_center.html was opened as a file:// URL (shared.js
# falls back to http://localhost:<PORT> in that case). See DEFINITIVE_PORTS.md.
PORT = 8771
BIND_HOST = (os.environ.get("LUMEN_BIND_HOST") or "127.0.0.1").strip()
CONTROL_TOKEN = os.environ.get("LUMEN_CONTROL_TOKEN", "")
_DEFAULT_ALLOWED_ORIGINS = f"null,http://localhost:{PORT},http://127.0.0.1:{PORT}"
ALLOWED_ORIGINS = frozenset(
    origin.strip()
    for origin in os.environ.get(
        "LUMEN_ALLOWED_ORIGINS", _DEFAULT_ALLOWED_ORIGINS
    ).split(",")
    if origin.strip()
)
PI_USER = "unitares-anima"
PI_HOST = os.environ.get("LUMEN_HOST", "lumen-local")  # SSH config alias (local network)

# HTTP URL for Pi's anima-mcp server (preferred over SSH).
# No default — Tailscale IPs are operator-specific and change after Pi reinstalls.
# Set LUMEN_HTTP_URL via env (verify with `tailscale status`).
# DEFINITIVE: anima-mcp runs on port 8766 - see docs/operations/DEFINITIVE_PORTS.md
LUMEN_HTTP_URL = os.environ.get("LUMEN_HTTP_URL", "")
LUMEN_HTTP_AUTH = os.environ.get("LUMEN_HTTP_AUTH", "")  # "user:pass" for basic auth

# Canonical operator name is deployment-specific (see server_state.KNOWN_PERSON_ALIASES).
# Generic default; a deployment sets ANIMA_OPERATOR_NAME to its caretaker's name.
OPERATOR_NAME = (os.environ.get("ANIMA_OPERATOR_NAME") or "operator").strip()
OPERATOR_DISPLAY = OPERATOR_NAME.capitalize()


def http_call_tool(tool_name: str, arguments: dict = None, timeout: int = 10) -> tuple[bool, str]:
    """Call an MCP tool on Pi's anima-mcp server via HTTP."""
    if not LUMEN_HTTP_URL:
        return False, "LUMEN_HTTP_URL not configured"

    url = f"{LUMEN_HTTP_URL.rstrip('/')}/v1/tools/call"
    data = json.dumps({"name": tool_name, "arguments": arguments or {}}).encode()

    headers = {"Content-Type": "application/json"}
    if LUMEN_HTTP_AUTH:
        import base64 as b64
        auth = b64.b64encode(LUMEN_HTTP_AUTH.encode()).decode()
        headers["Authorization"] = f"Basic {auth}"

    req = urllib.request.Request(url, data=data, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode())
            if not result.get("success"):
                return False, result.get("error", "Tool call failed")
            # The REST envelope's `success` only reports transport/dispatch.
            # A tool that fails *internally* returns a nested
            # {"success": false, "error": ...} payload (see anima handlers),
            # so an outer-only check would report success on a tool error.
            inner = result.get("result", result)
            if isinstance(inner, dict) and inner.get("success") is False:
                return False, inner.get("error", "Tool reported failure")
            return True, json.dumps(inner)
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return False, f"Connection failed: {e.reason}"
    except Exception as e:
        return False, str(e)


def ssh_command(python_code: str, timeout: int = 10) -> tuple[bool, str]:
    """Run Python code on the Pi via SSH, supplying it only through stdin."""
    cmd = [
        "ssh", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes", f"{PI_USER}@{PI_HOST}",
        "cd anima-mcp && .venv/bin/python3 -"
    ]
    try:
        result = subprocess.run(
            cmd,
            input=python_code,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        else:
            return False, result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "SSH timeout"
    except Exception as e:
        return False, str(e)


class LumenControlHandler(http.server.SimpleHTTPRequestHandler):

    def _allowed_cors_origin(self) -> str | None:
        """Echo only an explicitly trusted browser origin."""
        headers = getattr(self, "headers", None)
        origin = headers.get("Origin") if headers else None
        return origin if origin in ALLOWED_ORIGINS else None

    def _send_cors_headers(self) -> None:
        origin = self._allowed_cors_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def _require_control_auth(self) -> bool:
        """Require bearer auth when a token is configured."""
        if not CONTROL_TOKEN:
            return True
        headers = getattr(self, "headers", None)
        supplied = headers.get("Authorization", "") if headers else ""
        expected = f"Bearer {CONTROL_TOKEN}"
        if hmac.compare_digest(supplied, expected):
            return True
        self.send_json({"error": "Control relay authentication required"}, 401)
        return False

    def send_json(self, data: dict, status: int = 200):
        """Send JSON response with CORS headers."""
        self.send_response(status)
        self.send_header('Content-type', 'application/json')
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def send_bytes(
        self,
        data: bytes,
        *,
        status: int = 200,
        content_type: str = "application/octet-stream",
        cache_control: str | None = None,
    ):
        """Relay an upstream response with the Control Center's CORS contract."""
        self.send_response(status)
        self.send_header("Content-type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self._send_cors_headers()
        if cache_control:
            self.send_header("Cache-Control", cache_control)
        self.end_headers()
        self.wfile.write(data)

    def proxy_http_request(
        self,
        *,
        method: str = "GET",
        body: bytes | None = None,
        timeout: int = 10,
        cache_control: str | None = None,
    ) -> bool:
        """Proxy this exact request path, including its query, to Lumen."""
        if not LUMEN_HTTP_URL:
            return False

        headers = {}
        if LUMEN_HTTP_AUTH:
            auth = base64.b64encode(LUMEN_HTTP_AUTH.encode()).decode()
            headers["Authorization"] = f"Basic {auth}"
        if body is not None:
            headers["Content-Type"] = self.headers.get(
                "Content-Type", "application/json"
            )
        request = urllib.request.Request(
            f"{LUMEN_HTTP_URL.rstrip('/')}{self.path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                response_body = response.read()
                response_status = response.status
                response_type = response.headers.get(
                    "Content-Type", "application/octet-stream"
                )
        except urllib.error.HTTPError as error:
            # An upstream application error is authoritative. Forward it
            # instead of masking it with a different SSH fallback result.
            response_body = error.read()
            response_status = error.code
            response_type = error.headers.get(
                "Content-Type", "application/json"
            )
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

        # Once the upstream answered, a client disconnect is not a reason to
        # attempt a second, semantically different SSH response.
        self.send_bytes(
            response_body,
            status=response_status,
            content_type=response_type,
            cache_control=cache_control,
        )
        return True

    def proxy_http_get(
        self, *, timeout: int = 10, cache_control: str | None = None
    ) -> bool:
        return self.proxy_http_request(
            timeout=timeout, cache_control=cache_control
        )

    def proxy_http_post(self, body: bytes, *, timeout: int = 15) -> bool:
        return self.proxy_http_request(method="POST", body=body, timeout=timeout)

    def do_GET(self):
        if not self._require_control_auth():
            return
        route = urlsplit(self.path).path
        if route == '/state':
            self.handle_get_state()
        elif route == '/qa':
            self.handle_get_qa()
        elif route == '/messages':
            self.handle_get_messages()
        elif route == '/learning':
            self.handle_get_learning()
        elif route == '/voice':
            self.handle_get_voice()
        elif route == '/gallery':
            self.handle_get_gallery()
        elif route.startswith('/gallery/'):
            self.handle_get_gallery_image(route)
        elif (
            route in {
                '/health/detailed', '/self-knowledge', '/growth',
                '/dashboard', '/architecture', '/layers', '/schema',
                '/schema-data', '/gallery-page',
            }
            or route.startswith('/static/')
        ):
            self.handle_get_upstream_json()
        elif route == '/':
            self.send_response(302)
            self.send_header('Location', '/dashboard')
            self._send_cors_headers()
            self.end_headers()
        elif route == '/health':
            self.send_json({
                "status": "ok",
                "http_url": LUMEN_HTTP_URL or None,
                "ssh_host": PI_HOST,
                "mode": "http" if LUMEN_HTTP_URL else "ssh",
                "bind_host": BIND_HOST,
                "auth_required": bool(CONTROL_TOKEN),
            })
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if not self._require_control_auth():
            return
        origin = self.headers.get("Origin")
        if origin and origin not in ALLOWED_ORIGINS:
            self.send_json({"error": "Origin not allowed"}, 403)
            return
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].lower()
        if content_type != "application/json":
            self.send_json({"error": "Content-Type must be application/json"}, 415)
            return
        route = urlsplit(self.path).path
        if route == '/message':
            self.handle_post_message()
        elif route == '/answer':
            self.handle_post_answer()
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        origin = self.headers.get("Origin")
        if not origin or origin not in ALLOWED_ORIGINS:
            self.send_json({"error": "Origin not allowed"}, 403)
            return
        self.send_response(200)
        self._send_cors_headers()
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()

    def handle_get_state(self):
        """Get Lumen's current state via REST endpoint."""
        if self.proxy_http_get():
            return

        # SSH fallback - use the SAME get_state logic as the MCP server
        # This reads from shared memory and uses anima.feeling() for mood
        code = '''
import json
import sys, io

# Suppress init messages
old_stdout, old_stderr = sys.stdout, sys.stderr
sys.stdout = sys.stderr = io.StringIO()

try:
    from src.anima_mcp.shared_memory import SharedMemoryClient
    from src.anima_mcp.anima import Anima, SensorReadings
    from src.anima_mcp.computational_neural import computational_neural_provenance
    from src.anima_mcp.identity import IdentityStore

    # Read from shared memory (same source as Pi display)
    shm = SharedMemoryClient()
    shm_data = shm.read()

    sys.stdout, sys.stderr = old_stdout, old_stderr

    if not shm_data or "anima" not in shm_data:
        print(json.dumps({"error": "No shared memory data - is broker running?"}))
    else:
        # Reconstruct anima from shared memory
        a = shm_data["anima"]
        r = shm_data.get("readings", {})

        readings = SensorReadings(
            timestamp=r.get("timestamp", ""),
            cpu_temp_c=r.get("cpu_temp_c"),
            ambient_temp_c=r.get("ambient_temp_c"),
            humidity_pct=r.get("humidity_pct"),
            light_lux=r.get("light_lux"),
            pressure_hpa=r.get("pressure_hpa"),
            cpu_percent=r.get("cpu_percent"),
            memory_percent=r.get("memory_percent"),
            disk_percent=r.get("disk_percent"),
        )

        anima = Anima(
            warmth=a.get("warmth", 0.5),
            clarity=a.get("clarity", 0.5),
            stability=a.get("stability", 0.5),
            presence=a.get("presence", 0.5),
            readings=readings,
        )

        # Use anima.feeling() for consistent mood calculation
        feeling = anima.feeling()

        # Get identity
        store = IdentityStore()
        creature = store.get_identity()

        neural = {
            "delta": r.get("eeg_delta_power"),
            "theta": r.get("eeg_theta_power"),
            "alpha": r.get("eeg_alpha_power"),
            "beta": r.get("eeg_beta_power"),
            "gamma": r.get("eeg_gamma_power"),
        }
        if not any(value is not None for value in neural.values()):
            neural = {}

        body_projection = shm_data.get("body_eisv_projection") or shm_data.get("eisv")

        print(json.dumps({
            "name": (creature.name or "Lumen") if creature else "Lumen",
            "mood": feeling["mood"],
            "warmth": anima.warmth,
            "clarity": anima.clarity,
            "stability": anima.stability,
            "presence": anima.presence,
            "feeling": feeling,
            "cpu_temp": readings.cpu_temp_c or 0,
            "ambient_temp": readings.ambient_temp_c or 0,
            "light": readings.light_lux or 0,
            # Preserve the broker's provenance-rich decomposition. This is a
            # telemetry slice only: the Control Center labels it as shadow and
            # raw lux remains the behavioral input on the Pi.
            "light_attribution": shm_data.get("light_attribution"),
            "humidity": readings.humidity_pct or 0,
            "pressure": readings.pressure_hpa,
            "cpu_percent": readings.cpu_percent or 0,
            "memory_percent": readings.memory_percent or 0,
            "disk_percent": readings.disk_percent or 0,
            "neural": neural,
            "neural_provenance": computational_neural_provenance(),
            "body_anima": shm_data.get("body_anima") or a,
            "body_eisv_projection": body_projection,
            "eisv": body_projection,
            "api_security": {
                "mode": "ssh-fallback",
                "token_configured": False,
                "trusted_proxy_networks_configured": False,
            },
            "awakenings": creature.total_awakenings if creature else 0,
            "alive_hours": round(creature.total_alive_seconds / 3600, 1) if creature else 0,
            "alive_ratio": round(creature.alive_ratio(), 2) if creature else 0,
            "activity": shm_data.get("activity"),
            "timestamp": readings.timestamp,
            "source": "shared_memory"
        }))
except Exception as e:
    sys.stdout, sys.stderr = old_stdout, old_stderr
    print(json.dumps({"error": str(e)}))
'''
        success, output = ssh_command(code)
        if success:
            try:
                self.send_json(json.loads(output))
            except json.JSONDecodeError:
                self.send_json({"error": "Invalid JSON from Pi", "raw": output}, 500)
        else:
            self.send_json({"error": output, "offline": True}, 503)

    def handle_get_qa(self):
        """Get questions and answers from Lumen via REST endpoint."""
        if self.proxy_http_get():
            return

        # SSH fallback
        code = '''
import json
from src.anima_mcp.messages import get_board, MESSAGE_TYPE_QUESTION, MESSAGE_TYPE_AGENT
board = get_board()
board._load()
questions = [m for m in board._messages if m.msg_type == MESSAGE_TYPE_QUESTION]
qa_pairs = []
for q in questions:
    answer = None
    for m in board._messages:
        if getattr(m, "responds_to", None) == q.message_id:
            answer = {"text": m.text, "author": m.author, "timestamp": m.timestamp}
            break
    qa_pairs.append({
        "id": q.message_id,
        "question": q.text,
        "answered": q.answered,
        "timestamp": q.timestamp,
        "answer": answer
    })
qa_pairs.reverse()
print(json.dumps({"questions": qa_pairs[:10], "total": len(qa_pairs), "unanswered": sum(1 for q in qa_pairs if q["answer"] is None)}))
'''
        success, output = ssh_command(code)
        if success:
            try:
                self.send_json(json.loads(output))
            except json.JSONDecodeError:
                self.send_json({"error": "Invalid JSON", "raw": output}, 500)
        else:
            self.send_json({"error": output}, 503)

    def handle_get_messages(self):
        """Get recent messages from Lumen's message board via REST endpoint."""
        if self.proxy_http_get():
            return

        # SSH fallback
        code = '''
import json
from src.anima_mcp.messages import get_recent_messages
messages = get_recent_messages(20)
result = [{"id": m.message_id, "text": m.text, "type": m.msg_type, "author": m.author, "timestamp": m.timestamp, "responds_to": m.responds_to} for m in messages]
print(json.dumps({"messages": result, "total": len(result)}))
'''
        success, output = ssh_command(code)
        if success:
            try:
                self.send_json(json.loads(output))
            except json.JSONDecodeError:
                self.send_json({"error": "Invalid JSON", "raw": output}, 500)
        else:
            self.send_json({"error": output}, 503)

    def handle_get_learning(self):
        """Get Lumen's learning stats via REST endpoint."""
        if self.proxy_http_get(timeout=15):
            return

        # SSH fallback
        code = '''
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

# Check multiple possible database locations
db_path = None
for p in [Path.home() / "anima-mcp" / "anima.db", Path.home() / ".anima" / "anima.db"]:
    if p.exists():
        db_path = p
        break

if not db_path:
    print(json.dumps({"error": "No identity database"}))
else:
    conn = sqlite3.connect(str(db_path))

    # Get identity stats
    identity = conn.execute("SELECT name, total_awakenings, total_alive_seconds FROM identity LIMIT 1").fetchone()

    # Get recent state history for learning trends
    one_day_ago = (datetime.now() - timedelta(hours=24)).isoformat()
    recent_states = conn.execute(
        "SELECT warmth, clarity, stability, presence, timestamp FROM state_history WHERE timestamp > ? ORDER BY timestamp DESC LIMIT 100",
        (one_day_ago,)
    ).fetchall()

    # Calculate averages and trends
    if recent_states:
        avg_warmth = sum(s[0] for s in recent_states) / len(recent_states)
        avg_clarity = sum(s[1] for s in recent_states) / len(recent_states)
        avg_stability = sum(s[2] for s in recent_states) / len(recent_states)
        avg_presence = sum(s[3] for s in recent_states) / len(recent_states)

        # Trend: compare first half to second half
        mid = len(recent_states) // 2
        if mid > 0:
            first_half = recent_states[mid:]
            second_half = recent_states[:mid]
            stability_trend = sum(s[2] for s in second_half) / len(second_half) - sum(s[2] for s in first_half) / len(first_half)
        else:
            stability_trend = 0
    else:
        avg_warmth = avg_clarity = avg_stability = avg_presence = 0
        stability_trend = 0

    # Get recent events
    events = conn.execute(
        "SELECT event_type, timestamp FROM events ORDER BY timestamp DESC LIMIT 10"
    ).fetchall()

    alive_hours = identity[2] / 3600 if identity else 0

    print(json.dumps({
        "name": identity[0] if identity else "Unknown",
        "awakenings": identity[1] if identity else 0,
        "alive_hours": round(alive_hours, 1),
        "samples_24h": len(recent_states),
        "avg_warmth": round(avg_warmth, 3),
        "avg_clarity": round(avg_clarity, 3),
        "avg_stability": round(avg_stability, 3),
        "avg_presence": round(avg_presence, 3),
        "stability_trend": round(stability_trend, 3),
        "recent_events": [{"type": e[0], "time": e[1]} for e in events[:5]]
    }))
    conn.close()
'''
        success, output = ssh_command(code, timeout=15)
        if success:
            try:
                self.send_json(json.loads(output))
            except json.JSONDecodeError:
                self.send_json({"error": "Invalid JSON", "raw": output}, 500)
        else:
            self.send_json({"error": output}, 503)

    def handle_get_voice(self):
        """Get Lumen's voice/audio status via REST endpoint."""
        if self.proxy_http_get():
            return

        # SSH fallback
        code = '''
import json
try:
    with open("/dev/shm/anima_voice.json") as f:
        data = json.load(f)
    print(json.dumps(data))
except FileNotFoundError:
    print(json.dumps({"active": False, "status": "no voice data"}))
except Exception as e:
    print(json.dumps({"error": str(e)}))
'''
        success, output = ssh_command(code)
        if success:
            try:
                self.send_json(json.loads(output))
            except json.JSONDecodeError:
                self.send_json({"error": "Invalid JSON", "raw": output}, 500)
        else:
            self.send_json({"error": output}, 503)

    def handle_get_gallery(self):
        """Get list of Lumen's drawings via REST endpoint."""
        if self.proxy_http_get():
            return

        # SSH fallback
        code = '''
import json
import re
from pathlib import Path
from datetime import datetime

drawings_dir = Path.home() / ".anima" / "drawings"

if not drawings_dir.exists():
    print(json.dumps({"drawings": [], "total": 0}))
else:
    files = list(drawings_dir.glob("lumen_drawing*.png"))

    def parse_ts(f):
        m = re.search(r"(\\d{8})_(\\d{6})", f.name)
        if m:
            try:
                return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").timestamp()
            except Exception:
                pass
        return f.stat().st_mtime

    files = sorted(files, key=parse_ts, reverse=True)

    drawings = []
    for f in files[:30]:
        drawings.append({
            "filename": f.name,
            "timestamp": parse_ts(f),
            "size": f.stat().st_size
        })
    print(json.dumps({"drawings": drawings, "total": len(files)}))
'''
        success, output = ssh_command(code)
        if success:
            try:
                self.send_json(json.loads(output))
            except json.JSONDecodeError:
                self.send_json({"error": "Invalid JSON", "raw": output}, 500)
        else:
            self.send_json({"error": output}, 503)

    def handle_get_gallery_image(self, route: str | None = None):
        """Serve a drawing image from the Pi via REST endpoint."""
        gallery_route = route or urlsplit(self.path).path
        filename = unquote(gallery_route.split('/gallery/')[-1])
        # Sanitize filename
        if '/' in filename or '..' in filename:
            self.send_response(400)
            self.end_headers()
            return

        if self.proxy_http_get(timeout=15, cache_control="max-age=3600"):
            return

        # SSH fallback
        code = f'''
import base64
from pathlib import Path

img_path = Path.home() / ".anima" / "drawings" / "{filename}"
if img_path.exists():
    with open(img_path, "rb") as f:
        print(base64.b64encode(f.read()).decode())
else:
    print("NOT_FOUND")
'''
        success, output = ssh_command(code, timeout=15)
        if success and output != "NOT_FOUND":
            try:
                img_data = base64.b64decode(output)
                self.send_response(200)
                self.send_header('Content-type', 'image/png')
                self._send_cors_headers()
                self.send_header('Cache-Control', 'max-age=3600')
                self.end_headers()
                self.wfile.write(img_data)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
        else:
            self.send_response(404)
            self.end_headers()

    def handle_get_upstream_json(self):
        """Relay canonical REST-only Control Center cards."""
        if self.proxy_http_get(timeout=15):
            return
        self.send_json(
            {
                "error": (
                    f"{urlsplit(self.path).path} requires the configured "
                    "Lumen HTTP bridge"
                )
            },
            503,
        )

    def handle_post_message(self):
        """Send a message to Lumen, optionally responding to a question."""
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)

        if LUMEN_HTTP_URL:
            if self.proxy_http_post(post_data):
                return
            self.send_json(
                {
                    "error": (
                        "Lumen HTTP bridge unavailable; message was not retried "
                        "over SSH because delivery status is unknown"
                    )
                },
                503,
            )
            return

        try:
            data = json.loads(post_data)
            text = data.get('text', '')
            author = data.get('author') or 'user'
            responds_to = data.get('responds_to') or None

            if not isinstance(text, str) or not text.strip():
                self.send_json({"error": "No text provided"}, 400)
                return
            if not isinstance(author, str):
                self.send_json({"error": "Author must be text"}, 400)
                return
            if responds_to is not None and not isinstance(responds_to, str):
                self.send_json({"error": "responds_to must be text"}, 400)
                return

            # Normalize role aliases → canonical operator name (also done server-side)
            if author.lower() in ('caretaker', OPERATOR_NAME.lower()):
                author = OPERATOR_DISPLAY

            payload = {
                "message": text,
                "source": "dashboard",
                "author": author,
            }
            if responds_to:
                payload["responds_to"] = responds_to
            encoded_payload = base64.b64encode(
                json.dumps(payload).encode()
            ).decode()
            code = '''
import asyncio
import base64
import json

from src.anima_mcp.growth import normalize_visitor_identity
from src.anima_mcp.handlers.communication import handle_post_message

payload = json.loads(base64.b64decode("__PAYLOAD__").decode())
author = payload.pop("author")
_, display_name, _ = normalize_visitor_identity(author, source="dashboard")
payload["agent_name"] = display_name
result = asyncio.run(handle_post_message(payload))
print(result[0].text if result else json.dumps({"success": True}))
'''.replace("__PAYLOAD__", encoded_payload)

            success, output = ssh_command(code, timeout=15)
            if success:
                try:
                    self.send_json(json.loads(output))
                except json.JSONDecodeError:
                    self.send_json({"error": "Invalid JSON", "raw": output}, 500)
            else:
                self.send_json({"error": output}, 500)

        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self.send_json({"error": f"Invalid JSON: {e}"}, 400)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def handle_post_answer(self):
        """Answer a question from Lumen."""
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)

        if LUMEN_HTTP_URL:
            if self.proxy_http_post(post_data, timeout=45):
                return
            self.send_json(
                {
                    "error": (
                        "Lumen HTTP bridge unavailable; answer was not retried "
                        "over SSH because delivery status is unknown"
                    )
                },
                503,
            )
            return

        try:
            data = json.loads(post_data)
            question_id = data.get('question_id') or data.get('id', '')
            answer_text = data.get('answer', '')
            author = data.get('author') or OPERATOR_DISPLAY

            if not isinstance(question_id, (str, int)) or not str(question_id):
                self.send_json({"error": "No question ID provided"}, 400)
                return
            if not isinstance(answer_text, str) or not answer_text.strip():
                self.send_json({"error": "No answer provided"}, 400)
                return
            if not isinstance(author, str):
                self.send_json({"error": "Author must be text"}, 400)
                return

            # Normalize role aliases → canonical operator name (also done server-side)
            if author.lower() in ('caretaker', OPERATOR_NAME.lower()):
                author = OPERATOR_DISPLAY

            payload = {
                "question_id": str(question_id),
                "answer": answer_text,
                "author": author,
            }
            encoded_payload = base64.b64encode(
                json.dumps(payload).encode()
            ).decode()
            code = '''
import asyncio
import base64
import json

from src.anima_mcp.growth import normalize_visitor_identity
from src.anima_mcp.handlers.communication import handle_lumen_qa

payload = json.loads(base64.b64decode("__PAYLOAD__").decode())
author = payload.pop("author")
_, display_name, _ = normalize_visitor_identity(author, source="dashboard")
payload["agent_name"] = display_name
result = asyncio.run(handle_lumen_qa(payload))
print(result[0].text if result else json.dumps({"success": True}))
'''.replace("__PAYLOAD__", encoded_payload)
            success, output = ssh_command(code, timeout=45)
            if success:
                try:
                    self.send_json(json.loads(output))
                except json.JSONDecodeError:
                    self.send_json({"error": "Invalid JSON", "raw": output}, 500)
            else:
                self.send_json({"error": output}, 500)

        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self.send_json({"error": f"Invalid JSON: {e}"}, 400)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)


def main():
    if BIND_HOST not in {"127.0.0.1", "::1", "localhost"} and not CONTROL_TOKEN:
        raise SystemExit(
            "Refusing a non-loopback control relay without LUMEN_CONTROL_TOKEN"
        )
    print("╭──────────────────────────────────────────╮")
    print("│  Lumen Control Server                    │")
    print(f"│  http://{BIND_HOST}:{PORT}                    │")
    print("╰──────────────────────────────────────────╯")
    print()
    if LUMEN_HTTP_URL:
        print("  Mode: HTTP (preferred)")
        print(f"  URL:  {LUMEN_HTTP_URL}")
    else:
        print("  Mode: SSH (fallback)")
    print(f"  SSH:  {PI_USER}@{PI_HOST}")
    print()
    print("Endpoints:")
    print("  GET  /state       - Lumen's current state")
    print("  GET  /qa          - Questions & answers")
    print("  GET  /gallery     - List Lumen's drawings")
    print("  GET  /gallery/<f> - Get drawing image")
    print("  GET  /health      - Connection status")
    print("  POST /message     - Send message to Lumen")
    print("  POST /answer      - Answer Lumen's question")
    print()

    try:
        # Use ThreadingTCPServer to handle concurrent requests
        # (prevents blocking when SSH commands are slow)
        class ThreadedServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
            allow_reuse_address = True
            daemon_threads = True

        with ThreadedServer((BIND_HOST, PORT), LumenControlHandler) as httpd:
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()
