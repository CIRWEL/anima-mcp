import base64
import importlib.util
import json
from pathlib import Path

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


@pytest.mark.parametrize(
    ("path", "handler_name"),
    [
        ("/messages?limit=20", "handle_get_messages"),
        ("/gallery?limit=12", "handle_get_gallery"),
        ("/self-knowledge?limit=50", "handle_get_upstream_json"),
        ("/growth", "handle_get_upstream_json"),
        ("/health/detailed", "handle_get_upstream_json"),
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
