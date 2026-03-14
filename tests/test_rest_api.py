"""Targeted tests for REST endpoint helpers and gallery endpoints."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from anima_mcp import rest_api


def _make_request(
    method: str = "GET",
    path: str = "/",
    *,
    headers: dict[str, str] | None = None,
    query: str = "",
    body: dict | None = None,
    client_host: str = "8.8.8.8",
    path_params: dict[str, str] | None = None,
) -> Request:
    """Create a Starlette request object for direct endpoint calls."""
    raw_headers = [(k.lower().encode("utf-8"), v.encode("utf-8")) for k, v in (headers or {}).items()]
    body_bytes = b""
    if body is not None:
        body_bytes = json.dumps(body).encode("utf-8")
        raw_headers.append((b"content-type", b"application/json"))

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "path": path,
        "headers": raw_headers,
        "query_string": query.encode("utf-8"),
        "client": (client_host, 12345),
        "path_params": path_params or {},
    }

    sent = {"done": False}

    async def receive():
        if sent["done"]:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent["done"] = True
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    return Request(scope, receive)


class TestRestAuthHelpers:
    def test_is_trusted_network_uses_x_forwarded_for(self):
        request = _make_request(headers={"x-forwarded-for": "100.88.1.8"})
        assert rest_api._is_trusted_network(request) is True

    def test_is_trusted_network_rejects_invalid_ip(self):
        request = _make_request(headers={"x-forwarded-for": "not-an-ip"})
        assert rest_api._is_trusted_network(request) is False

    def test_check_rest_auth_accepts_same_origin_with_token(self, monkeypatch):
        monkeypatch.setattr(rest_api, "_ANIMA_HTTP_API_TOKEN", "secret")
        request = _make_request(headers={"sec-fetch-site": "same-origin"})
        assert rest_api._check_rest_auth(request) is True

    def test_check_rest_auth_requires_valid_bearer(self, monkeypatch):
        monkeypatch.setattr(rest_api, "_ANIMA_HTTP_API_TOKEN", "secret")
        request = _make_request(headers={"authorization": "Bearer wrong"})
        assert rest_api._check_rest_auth(request) is False

        request_ok = _make_request(headers={"authorization": "Bearer secret"})
        assert rest_api._check_rest_auth(request_ok) is True


@pytest.mark.asyncio
class TestRestToolCall:
    async def test_missing_name_returns_400(self):
        request = _make_request(method="POST", path="/v1/tools/call", body={"arguments": {}})
        response = await rest_api.rest_tool_call(request)
        assert response.status_code == 400
        assert json.loads(response.body)["error"] == "Missing 'name' field"

    async def test_unknown_tool_returns_404(self):
        request = _make_request(method="POST", path="/v1/tools/call", body={"name": "not-a-tool"})
        response = await rest_api.rest_tool_call(request)
        assert response.status_code == 404
        assert "Unknown tool" in json.loads(response.body)["error"]

    async def test_returns_parsed_json_result(self, monkeypatch):
        async def fake_handler(_args):
            return [SimpleNamespace(text='{"ok": true, "n": 3}')]

        monkeypatch.setattr(rest_api, "HANDLERS", {"demo": fake_handler})
        request = _make_request(method="POST", path="/v1/tools/call", body={"name": "demo", "arguments": {"x": 1}})

        response = await rest_api.rest_tool_call(request)
        data = json.loads(response.body)
        assert response.status_code == 200
        assert data["success"] is True
        assert data["result"] == {"ok": True, "n": 3}


@pytest.mark.asyncio
class TestRestGalleryImage:
    async def test_unauthorized_request_rejected(self, monkeypatch):
        monkeypatch.setattr(rest_api, "_check_rest_auth", lambda _req: False)
        request = _make_request(path="/gallery/foo.png")
        response = await rest_api.rest_gallery_image(request)
        assert response.status_code == 401

    async def test_rejects_path_traversal_filename(self, monkeypatch):
        monkeypatch.setattr(rest_api, "_check_rest_auth", lambda _req: True)
        request = _make_request(path="/gallery/../secret.txt", path_params={"filename": "../secret.txt"})
        response = await rest_api.rest_gallery_image(request)
        assert response.status_code == 400

    async def test_returns_404_for_missing_image(self, monkeypatch, tmp_path):
        monkeypatch.setattr(rest_api, "_check_rest_auth", lambda _req: True)
        monkeypatch.setenv("HOME", str(tmp_path))
        request = _make_request(path="/gallery/missing.png", path_params={"filename": "missing.png"})
        response = await rest_api.rest_gallery_image(request)
        assert response.status_code == 404

    async def test_serves_png_with_cache_header(self, monkeypatch, tmp_path):
        monkeypatch.setattr(rest_api, "_check_rest_auth", lambda _req: True)
        monkeypatch.setenv("HOME", str(tmp_path))
        drawings = Path(tmp_path) / ".anima" / "drawings"
        drawings.mkdir(parents=True)
        image = drawings / "lumen_drawing_20260207_190001_gestural.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\nfake")

        request = _make_request(path=f"/gallery/{image.name}", path_params={"filename": image.name})
        response = await rest_api.rest_gallery_image(request)

        assert response.status_code == 200
        assert response.media_type == "image/png"
        assert response.headers["Cache-Control"] == "max-age=3600"
        assert response.body.startswith(b"\x89PNG")
