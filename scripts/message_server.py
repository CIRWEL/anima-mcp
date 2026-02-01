#!/usr/bin/env python3
"""
Lumen Control Server - Bridges the Control Center to Lumen on the Pi.

Endpoints:
  POST /message - Send a message to Lumen
  GET /state    - Get Lumen's current state (anima, identity, sensors)
  GET /qa       - Get questions and answers
  POST /answer  - Answer a question from Lumen
"""
import http.server
import socketserver
import json
import subprocess
import os
import base64

PORT = 8768
PI_USER = "unitares-anima"
PI_HOST = os.environ.get("LUMEN_HOST", "lumen")  # Use Tailscale hostname by default


def ssh_command(python_code: str, timeout: int = 10) -> tuple[bool, str]:
    """Run Python code on the Pi via SSH using base64 to avoid escaping issues."""
    encoded = base64.b64encode(python_code.encode()).decode()
    cmd = [
        "ssh", "-o", "ConnectTimeout=5", f"{PI_USER}@{PI_HOST}",
        f"cd anima-mcp && echo {encoded} | base64 -d | .venv/bin/python3"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            return True, result.stdout.strip()
        else:
            return False, result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "SSH timeout"
    except Exception as e:
        return False, str(e)


class LumenControlHandler(http.server.SimpleHTTPRequestHandler):

    def send_json(self, data: dict, status: int = 200):
        """Send JSON response with CORS headers."""
        self.send_response(status)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        if self.path == '/state':
            self.handle_get_state()
        elif self.path == '/qa':
            self.handle_get_qa()
        elif self.path == '/learning':
            self.handle_get_learning()
        elif self.path == '/voice':
            self.handle_get_voice()
        elif self.path == '/health':
            self.send_json({"status": "ok", "host": PI_HOST})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/message':
            self.handle_post_message()
        elif self.path == '/answer':
            self.handle_post_answer()
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def handle_get_state(self):
        """Get Lumen's current state from shared memory."""
        code = '''
import json
try:
    with open("/dev/shm/anima_state.json") as f:
        data = json.load(f).get("data", {})
    anima = data.get("anima", {})
    identity = data.get("identity", {})
    readings = data.get("readings", {})
    metacog = data.get("metacognition", {})
    print(json.dumps({
        "name": identity.get("name", "Lumen"),
        "mood": anima.get("feeling", {}).get("mood", "unknown"),
        "warmth": anima.get("warmth", 0),
        "clarity": anima.get("clarity", 0),
        "stability": anima.get("stability", 0),
        "presence": anima.get("presence", 0),
        "surprise": metacog.get("surprise", 0),
        "cpu_temp": readings.get("cpu_temp_c", 0),
        "ambient_temp": readings.get("ambient_temp_c", 0),
        "light": readings.get("light_lux", 0),
        "humidity": readings.get("humidity_pct", 0),
        "awakenings": identity.get("awakenings", 0),
        "timestamp": data.get("timestamp", "")
    }))
except Exception as e:
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
        """Get questions and answers from Lumen."""
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
print(json.dumps({"questions": qa_pairs[:10], "total": len(qa_pairs), "unanswered": sum(1 for q in qa_pairs if not q["answered"])}))
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
        """Get Lumen's learning stats from identity store."""
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
        """Get Lumen's voice/audio status."""
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

    def handle_post_message(self):
        """Send a message to Lumen."""
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)

        try:
            data = json.loads(post_data)
            text = data.get('text', '').replace("'", "\\'").replace('"', '\\"')

            if not text:
                self.send_json({"error": "No text provided"}, 400)
                return

            print(f"Sending message to Lumen: {text[:50]}...")
            code = f"from src.anima_mcp.messages import MessageBoard; b = MessageBoard(); b.add_user_message('{text}'); print('ok')"

            success, output = ssh_command(code)
            if success:
                self.send_json({"status": "sent"})
            else:
                self.send_json({"error": output}, 500)

        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def handle_post_answer(self):
        """Answer a question from Lumen."""
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)

        try:
            data = json.loads(post_data)
            question_id = data.get('question_id', '')
            answer_text = data.get('answer', '').replace("'", "\\'").replace('"', '\\"')

            if not answer_text:
                self.send_json({"error": "No answer provided"}, 400)
                return

            print(f"Answering question {question_id}: {answer_text[:50]}...")
            code = f'''
from src.anima_mcp.messages import MessageBoard
board = MessageBoard()
board._load()
# Find the question and mark as answered
for m in board._messages:
    if m.message_id == "{question_id}":
        m.answered = True
        m.answered_by = "user"
        break
# Add the answer
board.add_agent_message("{answer_text}", agent_name="you", responds_to="{question_id}")
print("ok")
'''
            success, output = ssh_command(code)
            if success:
                self.send_json({"status": "answered"})
            else:
                self.send_json({"error": output}, 500)

        except Exception as e:
            self.send_json({"error": str(e)}, 500)


def main():
    print(f"╭──────────────────────────────────────────╮")
    print(f"│  Lumen Control Server                    │")
    print(f"│  http://localhost:{PORT}                    │")
    print(f"│  Connecting to: {PI_HOST}                │")
    print(f"╰──────────────────────────────────────────╯")
    print()
    print("Endpoints:")
    print("  GET  /state   - Lumen's current state")
    print("  GET  /qa      - Questions & answers")
    print("  POST /message - Send message to Lumen")
    print("  POST /answer  - Answer Lumen's question")
    print()

    try:
        socketserver.TCPServer.allow_reuse_address = True
        with socketserver.TCPServer(("", PORT), LumenControlHandler) as httpd:
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()
