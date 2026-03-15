import inspect
import typing

import pytest


def _is_optional(t) -> bool:
    return typing.get_origin(t) is typing.Union and type(None) in typing.get_args(t)


def _optional_inner(t):
    args = [a for a in typing.get_args(t) if a is not type(None)]
    return args[0] if args else None


def test_tools_list_populated():
    import anima_mcp.tool_registry as tr

    assert len(tr.TOOLS) >= 19


def test_system_service_schema_includes_broker_service():
    import anima_mcp.tool_registry as tr

    tool = next(t for t in tr.TOOLS if t.name == "system_service")
    services = tool.inputSchema["properties"]["service"]["enum"]
    assert "anima-broker" in services


def test_transport_security_uses_defaults_without_env(monkeypatch):
    import anima_mcp.tool_registry as tr

    monkeypatch.delenv("ANIMA_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("ANIMA_ALLOWED_ORIGINS", raising=False)
    settings = tr._get_transport_security_settings()

    assert settings.enable_dns_rebinding_protection is True
    assert settings.allowed_hosts == tr._DEFAULT_ALLOWED_HOSTS
    assert settings.allowed_origins == tr._DEFAULT_ALLOWED_ORIGINS


def test_transport_security_uses_env_overrides(monkeypatch):
    import anima_mcp.tool_registry as tr

    monkeypatch.setenv("ANIMA_ALLOWED_HOSTS", "example.com, 10.0.0.1:* ,")
    monkeypatch.setenv("ANIMA_ALLOWED_ORIGINS", "https://example.com, null")
    settings = tr._get_transport_security_settings()

    assert settings.allowed_hosts == ["example.com", "10.0.0.1:*"]
    assert settings.allowed_origins == ["https://example.com", "null"]


def test_json_type_to_python_handles_null_union_and_unknown():
    import anima_mcp.tool_registry as tr

    assert tr._json_type_to_python("string") is str
    assert tr._json_type_to_python("integer") is int

    t = tr._json_type_to_python(["string", "null"])
    assert _is_optional(t)
    assert _optional_inner(t) is str

    # All-null list falls back to str
    assert tr._json_type_to_python(["null"]) is str
    # Unknown type falls back to str
    assert tr._json_type_to_python("mystery") is str


@pytest.mark.asyncio
async def test_create_tool_wrapper_builds_signature_filters_nones_and_parses_json():
    import anima_mcp.tool_registry as tr
    from mcp.types import Tool, TextContent

    captured = {}

    async def handler(args: dict):
        captured["args"] = args
        return [TextContent(type="text", text='{"ok": true, "x": 1}')]

    tool_def = Tool(
        name="dummy",
        description="dummy",
        inputSchema={
            "type": "object",
            "properties": {
                "required_int": {"type": "integer"},
                "optional_str": {"type": ["string", "null"]},
            },
            "required": ["required_int"],
        },
    )

    wrapper = tr._create_tool_wrapper(handler, "dummy", tool_def)

    sig = inspect.signature(wrapper)
    assert "required_int" in sig.parameters
    assert sig.parameters["required_int"].default is inspect._empty
    assert sig.parameters["required_int"].kind is inspect.Parameter.KEYWORD_ONLY

    assert "optional_str" in sig.parameters
    assert sig.parameters["optional_str"].default is None
    assert sig.parameters["optional_str"].kind is inspect.Parameter.KEYWORD_ONLY

    out = await wrapper(required_int=5, optional_str=None)
    assert out == {"ok": True, "x": 1}
    # None was filtered out before passing to handler
    assert captured["args"] == {"required_int": 5}


@pytest.mark.asyncio
async def test_create_tool_wrapper_returns_text_when_json_invalid(monkeypatch):
    import anima_mcp.tool_registry as tr
    from mcp.types import Tool, TextContent

    async def handler(args: dict):
        return [TextContent(type="text", text="not-json")]

    tool_def = Tool(
        name="dummy2",
        description="dummy2",
        inputSchema={"type": "object", "properties": {}},
    )

    wrapper = tr._create_tool_wrapper(handler, "dummy2", tool_def)
    out = await wrapper()
    assert out == {"text": "not-json"}


@pytest.mark.asyncio
async def test_create_tool_wrapper_catches_handler_exception():
    import anima_mcp.tool_registry as tr
    from mcp.types import Tool

    async def handler(args: dict):
        raise RuntimeError("boom")

    tool_def = Tool(
        name="dummy3",
        description="dummy3",
        inputSchema={"type": "object", "properties": {}},
    )

    wrapper = tr._create_tool_wrapper(handler, "dummy3", tool_def)
    out = await wrapper()
    assert "error" in out
    assert "boom" in out["error"]

