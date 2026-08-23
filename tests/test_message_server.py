import importlib.util
import json
from pathlib import Path


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
    assert captured["response"]["light_attribution"] == expected
    assert captured["status"] == 200
