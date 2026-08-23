import base64
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def load_message_server():
    script = Path(__file__).parents[1] / "scripts" / "message_server.py"
    spec = importlib.util.spec_from_file_location("message_server_under_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ssh_state_fallback_relays_shadow_light_attribution(monkeypatch):
    module = load_message_server()
    module.LUMEN_HTTP_URL = ""
    captured = {}
    expected = {
        "schema": "anima.light_attribution.v1",
        "mode": "shadow",
        "status": "warming",
        "external_lux_residual": None,
        "used_by_clarity": False,
    }

    def fake_ssh_command(code, timeout=10):
        captured["code"] = code
        return True, json.dumps({"name": "Lumen", "light_attribution": expected})

    monkeypatch.setattr(module, "ssh_command", fake_ssh_command)
    handler = module.LumenControlHandler.__new__(module.LumenControlHandler)
    handler.send_json = lambda data, status=200: captured.update(
        {"response": data, "status": status}
    )

    handler.handle_get_state()

    assert '"light_attribution": shm_data.get("light_attribution")' in captured["code"]
    assert '"neural": neural' in captured["code"]
    assert '"body_eisv_projection": body_projection' in captured["code"]
    assert '"memory_percent": readings.memory_percent or 0' in captured["code"]
    assert '"disk_percent": readings.disk_percent or 0' in captured["code"]
    assert captured["response"]["light_attribution"] == expected
    assert captured["status"] == 200


def test_ssh_command_supplies_code_via_stdin_not_command_line(monkeypatch):
    module = load_message_server()
    captured = {}
    python_code = 'print("request-controlled content")'

    def fake_run(command, **kwargs):
        captured.update({"command": command, **kwargs})
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module.ssh_command(python_code) == (True, "ok")
    assert captured["command"][-1] == "cd anima-mcp && .venv/bin/python3 -"
    assert all(python_code not in part for part in captured["command"])
    assert captured["input"] == python_code
    assert captured["text"] is True
    assert captured["timeout"] == 10


@pytest.mark.parametrize(
    ("path", "handler_name"),
    [
        ("/messages?limit=20", "handle_get_messages"),
        ("/gallery?limit=12", "handle_get_gallery"),
        ("/self-knowledge?limit=50", "handle_get_upstream_json"),
        ("/growth", "handle_get_upstream_json"),
        ("/health/detailed", "handle_get_upstream_json"),
        ("/layers", "handle_get_upstream_json"),
        ("/schema-data", "handle_get_upstream_json"),
        ("/architecture", "handle_get_upstream_json"),
        ("/schema", "handle_get_upstream_json"),
        ("/gallery-page", "handle_get_upstream_json"),
        ("/static/shared.js", "handle_get_upstream_json"),
    ],
)
def test_get_routing_uses_path_without_dropping_query(path, handler_name):
    module = load_message_server()
    handler = module.LumenControlHandler.__new__(module.LumenControlHandler)
    handler.path = path
    called = []
    setattr(handler, handler_name, lambda: called.append(handler.path))

    handler.do_GET()

    assert called == [path]


def test_http_get_proxy_preserves_query_and_basic_auth(monkeypatch):
    module = load_message_server()
    module.LUMEN_HTTP_URL = "http://127.0.0.1:8769"
    module.LUMEN_HTTP_AUTH = "lumen:secret"
    captured = {}

    class FakeResponse:
        status = 200
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"messages": []}'

    def fake_urlopen(request, timeout):
        captured.update({"request": request, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    handler = module.LumenControlHandler.__new__(module.LumenControlHandler)
    handler.path = "/messages?limit=2"
    handler.headers = {}
    handler.send_bytes = lambda data, **kwargs: captured.update(
        {"body": data, **kwargs}
    )

    assert handler.proxy_http_get() is True

    request = captured["request"]
    assert request.full_url == "http://127.0.0.1:8769/messages?limit=2"
    assert request.get_method() == "GET"
    assert request.get_header("Authorization") == (
        "Basic " + base64.b64encode(b"lumen:secret").decode()
    )
    assert captured["timeout"] == 10
    assert captured["body"] == b'{"messages": []}'
    assert captured["status"] == 200
    assert captured["content_type"] == "application/json"


def test_http_post_proxy_preserves_body_and_content_type(monkeypatch):
    module = load_message_server()
    module.LUMEN_HTTP_URL = "http://127.0.0.1:8769"
    captured = {}

    class FakeResponse:
        status = 200
        headers = {"Content-Type": "application/json; charset=utf-8"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"success": true}'

    def fake_urlopen(request, timeout):
        captured.update({"request": request, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    handler = module.LumenControlHandler.__new__(module.LumenControlHandler)
    handler.path = "/message"
    handler.headers = {"Content-Type": "application/json; charset=utf-8"}
    handler.send_bytes = lambda data, **kwargs: captured.update(
        {"response_body": data, **kwargs}
    )
    body = b'{"text":"hello"}'

    assert handler.proxy_http_post(body) is True

    request = captured["request"]
    assert request.full_url == "http://127.0.0.1:8769/message"
    assert request.get_method() == "POST"
    assert request.data == body
    assert request.get_header("Content-type") == "application/json; charset=utf-8"
    assert captured["timeout"] == 15
    assert captured["response_body"] == b'{"success": true}'


def test_ssh_message_fallback_encodes_request_data_outside_python_source(monkeypatch):
    module = load_message_server()
    module.LUMEN_HTTP_URL = ""
    captured = {}
    malicious_text = '\"); __import__("os").system("touch /tmp/pwned") #'
    post_data = json.dumps(
        {"text": malicious_text, "author": "Visitor", "responds_to": "q1"}
    ).encode()

    def fake_ssh_command(code, timeout=10):
        captured.update({"code": code, "timeout": timeout})
        return True, '{"success": true}'

    monkeypatch.setattr(module, "ssh_command", fake_ssh_command)
    handler = module.LumenControlHandler.__new__(module.LumenControlHandler)
    handler.headers = {"Content-Length": str(len(post_data))}
    handler.rfile = io.BytesIO(post_data)
    handler.send_json = lambda data, status=200: captured.update(
        {"response": data, "status": status}
    )

    handler.handle_post_message()

    assert malicious_text not in captured["code"]
    encoded = captured["code"].split('base64.b64decode("', 1)[1].split('"', 1)[0]
    decoded = json.loads(base64.b64decode(encoded))
    assert decoded["message"] == malicious_text
    assert decoded["responds_to"] == "q1"
    assert "handle_post_message" in captured["code"]
    assert captured["timeout"] == 15
    assert captured["response"] == {"success": True}
    assert captured["status"] == 200


def test_configured_http_write_is_not_retried_after_ambiguous_failure(monkeypatch):
    module = load_message_server()
    module.LUMEN_HTTP_URL = "http://127.0.0.1:8769"
    captured = {}
    post_data = b'{"text":"hello"}'
    handler = module.LumenControlHandler.__new__(module.LumenControlHandler)
    handler.headers = {"Content-Length": str(len(post_data))}
    handler.rfile = io.BytesIO(post_data)
    handler.proxy_http_post = lambda *_args, **_kwargs: False
    handler.send_json = lambda data, status=200: captured.update(
        {"response": data, "status": status}
    )
    monkeypatch.setattr(
        module,
        "ssh_command",
        lambda *_args, **_kwargs: pytest.fail("ambiguous POST must not be retried"),
    )

    handler.handle_post_message()

    assert captured["status"] == 503
    assert "delivery status is unknown" in captured["response"]["error"]


def test_rest_only_card_reports_missing_http_bridge():
    module = load_message_server()
    module.LUMEN_HTTP_URL = ""
    captured = {}
    handler = module.LumenControlHandler.__new__(module.LumenControlHandler)
    handler.path = "/self-knowledge?limit=50"
    handler.send_json = lambda data, status=200: captured.update(
        {"response": data, "status": status}
    )

    handler.handle_get_upstream_json()

    assert captured["status"] == 503
    assert captured["response"] == {
        "error": "/self-knowledge requires the configured Lumen HTTP bridge"
    }


def test_control_center_labels_neural_bands_as_computational():
    dashboard = Path(__file__).parents[1] / "docs" / "control_center.html"

    assert "CPU-derived computational proprioception" in dashboard.read_text()
    assert "not physical EEG" in dashboard.read_text()
    assert "Computational Dynamics" in dashboard.read_text()
    assert "independently derived" in dashboard.read_text()


def test_architecture_page_uses_computational_sources_not_eeg_frequencies():
    architecture = Path(__file__).parents[1] / "docs" / "architecture.html"
    text = architecture.read_text()

    assert "Computational Dynamics" in text
    assert "not physical EEG" in text
    assert "raw light (room+LED)" in text
    assert r"0.5\u20134 Hz" not in text


def test_schema_page_visually_distinguishes_wiring_from_hypotheses():
    schema = Path(__file__).parents[1] / "docs" / "schema.html"
    text = schema.read_text()

    assert "live equation" in text
    assert "hypothesis / derived" in text
    assert "belief_about" in text
    assert "computational_influence" in text
    assert "derived_sensor" in text


def test_schema_trajectory_uses_canonical_profile_labels_and_confidences():
    schema = Path(__file__).parents[1] / "docs" / "schema.html"
    text = schema.read_text()

    assert "preferenceDetail.vector" in text
    assert "preferenceDetail.labels" in text
    assert "beliefDetail.values" in text
    assert "beliefDetail.labels" in text
    assert "beliefDetail.confidences" in text
    assert "canonical trajectory" in text
    assert "identity vector shows established only" in text
    assert "preferenceDetail.statuses" in text
    assert "tracked hypotheses" in text


def test_control_relay_root_redirects_to_dashboard():
    module = load_message_server()
    handler = module.LumenControlHandler.__new__(module.LumenControlHandler)
    handler.path = "/"
    handler.headers = {}
    captured = []
    handler.send_response = lambda status: captured.append(("status", status))
    handler.send_header = lambda name, value: captured.append((name, value))
    handler.end_headers = lambda: captured.append(("end", True))

    handler.do_GET()

    assert ("status", 302) in captured
    assert ("Location", "/dashboard") in captured


def test_control_relay_defaults_to_loopback_and_explicit_cors():
    module = load_message_server()
    assert module.BIND_HOST == "127.0.0.1"
    assert "*" not in module.ALLOWED_ORIGINS
    assert "null" in module.ALLOWED_ORIGINS

    handler = module.LumenControlHandler.__new__(module.LumenControlHandler)
    handler.headers = {"Origin": "null"}
    assert handler._allowed_cors_origin() == "null"
    handler.headers = {"Origin": "https://example.invalid"}
    assert handler._allowed_cors_origin() is None


def test_control_relay_rejects_untrusted_browser_write():
    module = load_message_server()
    handler = module.LumenControlHandler.__new__(module.LumenControlHandler)
    handler.path = "/message"
    handler.headers = {
        "Origin": "https://example.invalid",
        "Content-Type": "application/json",
    }
    captured = {}
    handler.send_json = lambda data, status=200: captured.update(
        {"response": data, "status": status}
    )
    handler.handle_post_message = lambda: pytest.fail("write must not dispatch")

    handler.do_POST()

    assert captured == {"response": {"error": "Origin not allowed"}, "status": 403}


def test_control_relay_rejects_simple_non_json_write():
    module = load_message_server()
    handler = module.LumenControlHandler.__new__(module.LumenControlHandler)
    handler.path = "/message"
    handler.headers = {"Origin": "null", "Content-Type": "text/plain"}
    captured = {}
    handler.send_json = lambda data, status=200: captured.update(
        {"response": data, "status": status}
    )
    handler.handle_post_message = lambda: pytest.fail("write must not dispatch")

    handler.do_POST()

    assert captured["status"] == 415
    assert "application/json" in captured["response"]["error"]
