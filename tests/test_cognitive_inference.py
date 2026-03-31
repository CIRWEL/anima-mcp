"""Tests for cognitive_inference.py — extended LLM reasoning (dialectic, knowledge graph)."""

import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from anima_mcp.cognitive_inference import (
    InferenceProfile,
    InferenceConfig,
    PROFILE_CONFIGS,
    CognitiveInference,
    get_cognitive_inference,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_httpx_response(status_code=200, json_body=None, text_body=""):
    """Create a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    if json_body is not None:
        resp.json.return_value = json_body
    resp.text = text_body or json.dumps(json_body or {})
    return resp


# ---------------------------------------------------------------------------
# InferenceProfile enum
# ---------------------------------------------------------------------------


class TestInferenceProfile:
    """Test InferenceProfile enum values."""

    def test_voice_value(self):
        assert InferenceProfile.VOICE.value == "voice"

    def test_dialectic_value(self):
        assert InferenceProfile.DIALECTIC.value == "dialectic"

    def test_knowledge_graph_value(self):
        assert InferenceProfile.KNOWLEDGE_GRAPH.value == "knowledge_graph"

    def test_query_value(self):
        assert InferenceProfile.QUERY.value == "query"

    def test_all_profiles_in_configs(self):
        for profile in InferenceProfile:
            assert profile in PROFILE_CONFIGS


# ---------------------------------------------------------------------------
# InferenceConfig dataclass
# ---------------------------------------------------------------------------


class TestInferenceConfig:
    """Test InferenceConfig dataclass construction and defaults."""

    def test_required_fields(self):
        config = InferenceConfig(
            max_tokens=100,
            temperature=0.5,
            system_prompt="test",
        )
        assert config.max_tokens == 100
        assert config.temperature == 0.5
        assert config.system_prompt == "test"

    def test_defaults(self):
        config = InferenceConfig(
            max_tokens=100,
            temperature=0.5,
            system_prompt="test",
        )
        assert config.prefer_larger_model is False
        assert config.json_mode is False

    def test_custom_optional_fields(self):
        config = InferenceConfig(
            max_tokens=500,
            temperature=0.4,
            system_prompt="reasoning",
            prefer_larger_model=True,
            json_mode=True,
        )
        assert config.prefer_larger_model is True
        assert config.json_mode is True


# ---------------------------------------------------------------------------
# PROFILE_CONFIGS
# ---------------------------------------------------------------------------


class TestProfileConfigs:
    """Validate the profile configuration constants."""

    def test_voice_config(self):
        config = PROFILE_CONFIGS[InferenceProfile.VOICE]
        assert config.max_tokens == 60
        assert config.temperature == 0.8
        assert config.prefer_larger_model is False
        assert config.json_mode is False

    def test_dialectic_config(self):
        config = PROFILE_CONFIGS[InferenceProfile.DIALECTIC]
        assert config.max_tokens == 500
        assert config.temperature == 0.4
        assert config.prefer_larger_model is True
        assert config.json_mode is True
        assert "dialectic" in config.system_prompt.lower()
        assert "thesis" in config.system_prompt.lower()
        assert "synthesis" in config.system_prompt.lower()

    def test_knowledge_graph_config(self):
        config = PROFILE_CONFIGS[InferenceProfile.KNOWLEDGE_GRAPH]
        assert config.max_tokens == 300
        assert config.temperature == 0.3
        assert config.prefer_larger_model is False
        assert config.json_mode is True
        assert "entities" in config.system_prompt.lower()
        assert "relationships" in config.system_prompt.lower()

    def test_query_config(self):
        config = PROFILE_CONFIGS[InferenceProfile.QUERY]
        assert config.max_tokens == 200
        assert config.temperature == 0.5
        assert config.prefer_larger_model is False
        assert config.json_mode is True
        assert "answer" in config.system_prompt.lower()
        assert "relevance" in config.system_prompt.lower()


# ---------------------------------------------------------------------------
# CognitiveInference init and provider detection
# ---------------------------------------------------------------------------


class TestCognitiveInferenceInit:
    """Test provider detection from environment."""

    def test_no_keys_disabled(self):
        with patch.dict("os.environ", {}, clear=True):
            ci = CognitiveInference()
            assert not ci.enabled
            assert not ci._has_groq
            assert not ci._has_hf
            assert not ci._has_ngrok

    def test_groq_only(self):
        env = {"GROQ_API_KEY": "gk-test"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()
            assert ci.enabled
            assert ci._has_groq
            assert not ci._has_hf
            assert not ci._has_ngrok

    def test_hf_only(self):
        env = {"HF_TOKEN": "hf_test"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()
            assert ci.enabled
            assert ci._has_hf

    def test_ngrok_only(self):
        env = {"NGROK_API_KEY": "nk-test"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()
            assert ci.enabled
            assert ci._has_ngrok

    def test_all_providers(self):
        env = {"GROQ_API_KEY": "gk", "HF_TOKEN": "hf", "NGROK_API_KEY": "nk"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()
            assert ci._has_groq
            assert ci._has_hf
            assert ci._has_ngrok

    def test_custom_ngrok_url(self):
        env = {"NGROK_API_KEY": "nk", "NGROK_GATEWAY_URL": "https://custom.io"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()
            assert ci.ngrok_url == "https://custom.io"


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------


class TestParseResponse:
    """Test JSON/text response parsing."""

    def setup_method(self):
        with patch.dict("os.environ", {"GROQ_API_KEY": "gk"}, clear=True):
            self.ci = CognitiveInference()

    def test_text_mode_wraps_in_dict(self):
        result = self.ci._parse_response("hello world", expect_json=False)
        assert result == {"text": "hello world"}

    def test_json_direct_parse(self):
        data = {"thesis": "warmth comes from CPU", "confidence": 0.8}
        result = self.ci._parse_response(json.dumps(data), expect_json=True)
        assert result["thesis"] == "warmth comes from CPU"
        assert result["confidence"] == 0.8

    def test_json_from_markdown_code_block(self):
        text = 'Some preamble\n```json\n{"key": "value"}\n```\nAfterward'
        result = self.ci._parse_response(text, expect_json=True)
        assert result["key"] == "value"

    def test_json_from_braces(self):
        text = 'Here is the result: {"answer": 42, "done": true} and more text'
        result = self.ci._parse_response(text, expect_json=True)
        assert result["answer"] == 42
        assert result["done"] is True

    def test_json_nested_braces(self):
        data = {"outer": {"inner": "value"}}
        text = f"Result: {json.dumps(data)} end"
        result = self.ci._parse_response(text, expect_json=True)
        assert result["outer"]["inner"] == "value"

    def test_malformed_json_fallback(self):
        text = "this is not json at all"
        result = self.ci._parse_response(text, expect_json=True)
        assert result["text"] == text
        assert result["parse_error"] is True

    def test_empty_string_json(self):
        result = self.ci._parse_response("", expect_json=True)
        assert "parse_error" in result

    def test_json_with_whitespace(self):
        text = '  \n  {"key": "value"}  \n  '
        result = self.ci._parse_response(text, expect_json=True)
        assert result["key"] == "value"

    def test_json_code_block_malformed_inner(self):
        """Markdown block present but inner JSON is broken."""
        text = '```json\n{bad json}\n```'
        result = self.ci._parse_response(text, expect_json=True)
        # Falls through to brace extraction, which also fails
        assert "parse_error" in result

    def test_braces_but_not_json(self):
        text = "function{x} returns {y}"
        result = self.ci._parse_response(text, expect_json=True)
        # outermost { to } is "function{x} returns {y}", which is invalid JSON
        assert "parse_error" in result


# ---------------------------------------------------------------------------
# _call_groq
# ---------------------------------------------------------------------------


class TestCallGroq:
    """Test Groq API calls with mocked httpx."""

    @pytest.mark.asyncio
    async def test_groq_success(self):
        env = {"GROQ_API_KEY": "gk-test"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        config = InferenceConfig(max_tokens=100, temperature=0.5, system_prompt="sys")
        json_data = {"choices": [{"message": {"content": "hello"}}]}
        mock_response = _mock_httpx_response(status_code=200, json_body=json_data)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await ci._call_groq("test prompt", config)
            assert result is not None
            assert result["text"] == "hello"

    @pytest.mark.asyncio
    async def test_groq_large_model(self):
        env = {"GROQ_API_KEY": "gk-test"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        config = InferenceConfig(max_tokens=500, temperature=0.4, system_prompt="sys")
        json_data = {"choices": [{"message": {"content": "deep thought"}}]}
        mock_response = _mock_httpx_response(status_code=200, json_body=json_data)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await ci._call_groq("test", config, use_large_model=True)
            call_args = mock_client.post.call_args
            body = call_args.kwargs.get("json") or call_args[1].get("json")
            assert body["model"] == CognitiveInference.MODELS["groq_large"]

    @pytest.mark.asyncio
    async def test_groq_json_mode(self):
        env = {"GROQ_API_KEY": "gk-test"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        config = InferenceConfig(
            max_tokens=300, temperature=0.3, system_prompt="sys", json_mode=True
        )
        response_data = {"thesis": "A", "antithesis": "B", "synthesis": "C"}
        json_data = {"choices": [{"message": {"content": json.dumps(response_data)}}]}
        mock_response = _mock_httpx_response(status_code=200, json_body=json_data)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await ci._call_groq("test", config)
            assert result["thesis"] == "A"

            # Verify json mode was in the request
            call_args = mock_client.post.call_args
            body = call_args.kwargs.get("json") or call_args[1].get("json")
            assert body["response_format"] == {"type": "json_object"}

    @pytest.mark.asyncio
    async def test_groq_no_json_mode_in_request(self):
        env = {"GROQ_API_KEY": "gk-test"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        config = InferenceConfig(
            max_tokens=60, temperature=0.8, system_prompt="sys", json_mode=False
        )
        json_data = {"choices": [{"message": {"content": "text"}}]}
        mock_response = _mock_httpx_response(status_code=200, json_body=json_data)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await ci._call_groq("test", config)
            call_args = mock_client.post.call_args
            body = call_args.kwargs.get("json") or call_args[1].get("json")
            assert "response_format" not in body

    @pytest.mark.asyncio
    async def test_groq_error_returns_none(self):
        env = {"GROQ_API_KEY": "gk-test"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        config = InferenceConfig(max_tokens=100, temperature=0.5, system_prompt="sys")
        mock_response = _mock_httpx_response(status_code=429, text_body="rate limited")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await ci._call_groq("test", config)
            assert result is None

    @pytest.mark.asyncio
    async def test_groq_exception_returns_none(self):
        env = {"GROQ_API_KEY": "gk-test"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        config = InferenceConfig(max_tokens=100, temperature=0.5, system_prompt="sys")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("connection error"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await ci._call_groq("test", config)
            assert result is None


# ---------------------------------------------------------------------------
# _call_ngrok
# ---------------------------------------------------------------------------


class TestCallNgrok:
    """Test ngrok AI Gateway calls."""

    @pytest.mark.asyncio
    async def test_ngrok_success(self):
        env = {"NGROK_API_KEY": "nk-test"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        config = InferenceConfig(max_tokens=100, temperature=0.5, system_prompt="sys")
        json_data = {"choices": [{"message": {"content": "ngrok response"}}]}
        mock_response = _mock_httpx_response(status_code=200, json_body=json_data)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await ci._call_ngrok("test", config)
            assert result is not None
            assert result["text"] == "ngrok response"

    @pytest.mark.asyncio
    async def test_ngrok_url_format(self):
        env = {"NGROK_API_KEY": "nk-test"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        config = InferenceConfig(max_tokens=100, temperature=0.5, system_prompt="sys")
        json_data = {"choices": [{"message": {"content": "x"}}]}
        mock_response = _mock_httpx_response(status_code=200, json_body=json_data)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await ci._call_ngrok("test", config)
            call_args = mock_client.post.call_args
            url = call_args[0][0] if call_args[0] else ""
            assert "/v1/chat/completions" in url

    @pytest.mark.asyncio
    async def test_ngrok_error_returns_none(self):
        env = {"NGROK_API_KEY": "nk-test"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        config = InferenceConfig(max_tokens=100, temperature=0.5, system_prompt="sys")
        mock_response = _mock_httpx_response(status_code=500, text_body="server error")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await ci._call_ngrok("test", config)
            assert result is None


# ---------------------------------------------------------------------------
# _call_huggingface
# ---------------------------------------------------------------------------


class TestCallHuggingFace:
    """Test HuggingFace Inference API calls."""

    @pytest.mark.asyncio
    async def test_hf_success_list_response(self):
        env = {"HF_TOKEN": "hf_test"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        config = InferenceConfig(max_tokens=100, temperature=0.5, system_prompt="sys")
        json_data = [{"generated_text": "extracted knowledge"}]
        mock_response = _mock_httpx_response(status_code=200, json_body=json_data)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await ci._call_huggingface("test", config)
            assert result is not None

    @pytest.mark.asyncio
    async def test_hf_success_dict_response(self):
        env = {"HF_TOKEN": "hf_test"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        config = InferenceConfig(max_tokens=100, temperature=0.5, system_prompt="sys")
        json_data = {"generated_text": "knowledge output"}
        mock_response = _mock_httpx_response(status_code=200, json_body=json_data)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await ci._call_huggingface("test", config)
            assert result is not None

    @pytest.mark.asyncio
    async def test_hf_cleans_phi_tags(self):
        env = {"HF_TOKEN": "hf_test"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        config = InferenceConfig(
            max_tokens=100, temperature=0.5, system_prompt="sys", json_mode=False
        )
        json_data = [{"generated_text": "<|assistant|>hello<|end|>"}]
        mock_response = _mock_httpx_response(status_code=200, json_body=json_data)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await ci._call_huggingface("test", config)
            assert "<|assistant|>" not in result.get("text", "")
            assert "<|end|>" not in result.get("text", "")

    @pytest.mark.asyncio
    async def test_hf_error_returns_none(self):
        env = {"HF_TOKEN": "hf_test"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        config = InferenceConfig(max_tokens=100, temperature=0.5, system_prompt="sys")
        mock_response = _mock_httpx_response(status_code=503, text_body="loading")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await ci._call_huggingface("test", config)
            assert result is None

    @pytest.mark.asyncio
    async def test_hf_url_includes_model(self):
        env = {"HF_TOKEN": "hf_test"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        config = InferenceConfig(max_tokens=100, temperature=0.5, system_prompt="sys")
        json_data = [{"generated_text": "x"}]
        mock_response = _mock_httpx_response(status_code=200, json_body=json_data)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await ci._call_huggingface("test", config)
            call_args = mock_client.post.call_args
            url = call_args[0][0] if call_args[0] else ""
            assert CognitiveInference.MODELS["phi"] in url


# ---------------------------------------------------------------------------
# infer() — provider routing and failover
# ---------------------------------------------------------------------------


class TestInfer:
    """Test the infer() method for routing and failover logic."""

    @pytest.mark.asyncio
    async def test_disabled_returns_none(self):
        with patch.dict("os.environ", {}, clear=True):
            ci = CognitiveInference()
        result = await ci.infer("test")
        assert result is None

    @pytest.mark.asyncio
    async def test_httpx_missing_returns_none(self):
        env = {"GROQ_API_KEY": "gk"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "httpx":
                raise ImportError("no httpx")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            result = await ci.infer("test")
            assert result is None

    @pytest.mark.asyncio
    async def test_groq_only_success(self):
        env = {"GROQ_API_KEY": "gk"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        with patch.object(ci, "_call_groq", new_callable=AsyncMock, return_value={"text": "groq result"}):
            result = await ci.infer("test", InferenceProfile.VOICE)
            assert result["text"] == "groq result"

    @pytest.mark.asyncio
    async def test_dialectic_prefers_large_model(self):
        """Dialectic profile should first try Groq with large model."""
        env = {"GROQ_API_KEY": "gk"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        calls = []

        async def track_groq(prompt, config, use_large_model=False):
            calls.append(("groq", use_large_model))
            if use_large_model:
                return {"thesis": "A", "synthesis": "C"}
            return None

        with patch.object(ci, "_call_groq", side_effect=track_groq):
            result = await ci.infer("test", InferenceProfile.DIALECTIC)
            assert result is not None
            # First call should be large model
            assert calls[0] == ("groq", True)

    @pytest.mark.asyncio
    async def test_dialectic_fallback_to_small_groq(self):
        """If large model fails, fallback to small Groq."""
        env = {"GROQ_API_KEY": "gk"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        calls = []

        async def track_groq(prompt, config, use_large_model=False):
            calls.append(("groq", use_large_model))
            if use_large_model:
                return None  # Large model fails
            return {"text": "small model result"}

        with patch.object(ci, "_call_groq", side_effect=track_groq):
            result = await ci.infer("test", InferenceProfile.DIALECTIC)
            assert result is not None
            assert len(calls) == 2
            assert calls[0] == ("groq", True)
            assert calls[1] == ("groq", False)

    @pytest.mark.asyncio
    async def test_failover_groq_to_ngrok(self):
        env = {"GROQ_API_KEY": "gk", "NGROK_API_KEY": "nk"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        with patch.object(ci, "_call_groq", new_callable=AsyncMock, return_value=None):
            with patch.object(ci, "_call_ngrok", new_callable=AsyncMock, return_value={"text": "ngrok"}) as mock_ngrok:
                result = await ci.infer("test", InferenceProfile.VOICE)
                assert result["text"] == "ngrok"
                mock_ngrok.assert_called_once()

    @pytest.mark.asyncio
    async def test_failover_groq_to_ngrok_to_hf(self):
        env = {"GROQ_API_KEY": "gk", "NGROK_API_KEY": "nk", "HF_TOKEN": "hf"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        with patch.object(ci, "_call_groq", new_callable=AsyncMock, return_value=None):
            with patch.object(ci, "_call_ngrok", new_callable=AsyncMock, return_value=None):
                with patch.object(ci, "_call_huggingface", new_callable=AsyncMock, return_value={"text": "hf"}) as mock_hf:
                    result = await ci.infer("test", InferenceProfile.VOICE)
                    assert result["text"] == "hf"
                    mock_hf.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_providers_fail_returns_none(self):
        env = {"GROQ_API_KEY": "gk", "NGROK_API_KEY": "nk", "HF_TOKEN": "hf"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        with patch.object(ci, "_call_groq", new_callable=AsyncMock, return_value=None):
            with patch.object(ci, "_call_ngrok", new_callable=AsyncMock, return_value=None):
                with patch.object(ci, "_call_huggingface", new_callable=AsyncMock, return_value=None):
                    result = await ci.infer("test", InferenceProfile.VOICE)
                    assert result is None

    @pytest.mark.asyncio
    async def test_context_prepended_to_prompt(self):
        """When context is provided, it should be prepended to the prompt."""
        env = {"GROQ_API_KEY": "gk"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        captured_prompt = []

        async def capture_groq(prompt, config, use_large_model=False):
            captured_prompt.append(prompt)
            return {"text": "result"}

        with patch.object(ci, "_call_groq", side_effect=capture_groq):
            await ci.infer("my query", InferenceProfile.QUERY, context="some context")
            assert "Context:" in captured_prompt[0]
            assert "some context" in captured_prompt[0]
            assert "Query:" in captured_prompt[0]
            assert "my query" in captured_prompt[0]

    @pytest.mark.asyncio
    async def test_no_context_plain_prompt(self):
        env = {"GROQ_API_KEY": "gk"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        captured_prompt = []

        async def capture_groq(prompt, config, use_large_model=False):
            captured_prompt.append(prompt)
            return {"text": "result"}

        with patch.object(ci, "_call_groq", side_effect=capture_groq):
            await ci.infer("direct question", InferenceProfile.VOICE)
            assert captured_prompt[0] == "direct question"


# ---------------------------------------------------------------------------
# High-level cognitive functions
# ---------------------------------------------------------------------------


class TestDialecticSynthesis:
    """Test dialectic_synthesis method."""

    @pytest.mark.asyncio
    async def test_with_thesis_and_antithesis(self):
        env = {"GROQ_API_KEY": "gk"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        expected = {
            "thesis": "warmth comes from CPU",
            "antithesis": "warmth also from ambient",
            "synthesis": "warmth is multi-source",
            "confidence": 0.7,
        }
        with patch.object(ci, "infer", new_callable=AsyncMock, return_value=expected) as mock_infer:
            result = await ci.dialectic_synthesis(
                thesis="warmth comes from CPU",
                antithesis="warmth also from ambient",
            )
            assert result["synthesis"] == "warmth is multi-source"
            # Should use DIALECTIC profile
            call_args = mock_infer.call_args
            assert call_args[1].get("profile") == InferenceProfile.DIALECTIC or call_args[0][1] == InferenceProfile.DIALECTIC

    @pytest.mark.asyncio
    async def test_with_thesis_only(self):
        env = {"GROQ_API_KEY": "gk"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        with patch.object(ci, "infer", new_callable=AsyncMock, return_value={"text": "result"}) as mock_infer:
            await ci.dialectic_synthesis(thesis="warmth feels good")
            prompt = mock_infer.call_args[0][0]
            assert "Proposition:" in prompt
            assert "counter-position" in prompt

    @pytest.mark.asyncio
    async def test_with_context(self):
        env = {"GROQ_API_KEY": "gk"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        with patch.object(ci, "infer", new_callable=AsyncMock, return_value={"text": "result"}) as mock_infer:
            await ci.dialectic_synthesis(
                thesis="warmth fluctuates",
                context="recent temperature data",
            )
            prompt = mock_infer.call_args[0][0]
            assert "Background:" in prompt
            assert "recent temperature data" in prompt


class TestExtractKnowledge:
    """Test extract_knowledge method."""

    @pytest.mark.asyncio
    async def test_basic_extraction(self):
        env = {"GROQ_API_KEY": "gk"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        expected = {
            "entities": ["CPU temperature", "warmth"],
            "relationships": [{"from": "CPU temperature", "to": "warmth", "type": "causes"}],
            "summary": "CPU temp drives warmth",
            "tags": ["hardware", "warmth"],
            "confidence": 0.8,
        }
        with patch.object(ci, "infer", new_callable=AsyncMock, return_value=expected) as mock_infer:
            result = await ci.extract_knowledge("CPU temperature affects how warm I feel")
            assert result["entities"] == ["CPU temperature", "warmth"]
            # Should use KNOWLEDGE_GRAPH profile
            call_args = mock_infer.call_args
            assert call_args[0][1] == InferenceProfile.KNOWLEDGE_GRAPH

    @pytest.mark.asyncio
    async def test_with_domain_hint(self):
        env = {"GROQ_API_KEY": "gk"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        with patch.object(ci, "infer", new_callable=AsyncMock, return_value={"text": "result"}) as mock_infer:
            await ci.extract_knowledge("warmth data", domain="embodied experience")
            prompt = mock_infer.call_args[0][0]
            assert "Domain context: embodied experience" in prompt


class TestQueryWithContext:
    """Test query_with_context method."""

    @pytest.mark.asyncio
    async def test_query_success(self):
        env = {"GROQ_API_KEY": "gk"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        expected = {
            "answer": "warmth peaks at night due to CPU heat retention",
            "relevance": 0.9,
            "sources": ["item 1"],
            "follow_up": [],
        }
        with patch.object(ci, "infer", new_callable=AsyncMock, return_value=expected) as mock_infer:
            result = await ci.query_with_context(
                query="when is warmth highest?",
                knowledge_context=["warmth peaks at night", "CPU runs cooler in daytime"],
            )
            assert result["relevance"] == 0.9
            # Should use QUERY profile
            call_args = mock_infer.call_args
            assert call_args[0][1] == InferenceProfile.QUERY
            # Context should be formatted with numbered items
            context_arg = call_args[1].get("context") or call_args[0][2]
            assert "[1]" in context_arg
            assert "[2]" in context_arg

    @pytest.mark.asyncio
    async def test_query_formats_context_items(self):
        env = {"GROQ_API_KEY": "gk"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        with patch.object(ci, "infer", new_callable=AsyncMock, return_value={"text": "x"}) as mock_infer:
            await ci.query_with_context(
                query="test",
                knowledge_context=["fact A", "fact B", "fact C"],
            )
            context_arg = mock_infer.call_args[1].get("context") or mock_infer.call_args[0][2]
            assert "[1] fact A" in context_arg
            assert "[2] fact B" in context_arg
            assert "[3] fact C" in context_arg


class TestMergeInsights:
    """Test merge_insights method."""

    @pytest.mark.asyncio
    async def test_single_insight_no_merge(self):
        env = {"GROQ_API_KEY": "gk"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        result = await ci.merge_insights(["only one insight"])
        assert result["text"] == "only one insight"
        assert result["merged"] is False

    @pytest.mark.asyncio
    async def test_empty_insights_no_merge(self):
        env = {"GROQ_API_KEY": "gk"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        result = await ci.merge_insights([])
        assert result["text"] == ""
        assert result["merged"] is False

    @pytest.mark.asyncio
    async def test_multiple_insights_merged(self):
        env = {"GROQ_API_KEY": "gk"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        expected = {
            "merged_insight": "warmth is affected by CPU and ambient",
            "core_concepts": ["warmth", "CPU", "ambient"],
            "redundant_items": [0],
            "confidence": 0.8,
        }
        with patch.object(ci, "infer", new_callable=AsyncMock, return_value=expected) as mock_infer:
            result = await ci.merge_insights([
                "warmth comes from CPU",
                "warmth is also from ambient temp",
            ])
            assert result["merged_insight"] == "warmth is affected by CPU and ambient"
            # Should use KNOWLEDGE_GRAPH profile
            call_args = mock_infer.call_args
            assert call_args[0][1] == InferenceProfile.KNOWLEDGE_GRAPH

    @pytest.mark.asyncio
    async def test_merge_prompt_includes_all_insights(self):
        env = {"GROQ_API_KEY": "gk"}
        with patch.dict("os.environ", env, clear=True):
            ci = CognitiveInference()

        with patch.object(ci, "infer", new_callable=AsyncMock, return_value={"text": "merged"}) as mock_infer:
            await ci.merge_insights(["insight A", "insight B", "insight C"])
            prompt = mock_infer.call_args[0][0]
            assert "insight A" in prompt
            assert "insight B" in prompt
            assert "insight C" in prompt


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    """Test get_cognitive_inference singleton."""

    def test_returns_instance(self):
        import anima_mcp.cognitive_inference as mod
        mod._cognitive = None
        with patch.dict("os.environ", {}, clear=True):
            ci = get_cognitive_inference()
            assert isinstance(ci, CognitiveInference)

    def test_same_instance(self):
        import anima_mcp.cognitive_inference as mod
        mod._cognitive = None
        with patch.dict("os.environ", {}, clear=True):
            ci1 = get_cognitive_inference()
            ci2 = get_cognitive_inference()
            assert ci1 is ci2


# ---------------------------------------------------------------------------
# Models and constants
# ---------------------------------------------------------------------------


class TestModelsAndConstants:
    """Test model and endpoint constants."""

    def test_models_dict(self):
        assert "groq_small" in CognitiveInference.MODELS
        assert "groq_large" in CognitiveInference.MODELS
        assert "phi" in CognitiveInference.MODELS
        assert "groq_json" in CognitiveInference.MODELS

    def test_api_urls(self):
        assert "groq.com" in CognitiveInference.GROQ_API_URL
        assert "huggingface" in CognitiveInference.HF_INFERENCE_URL
        assert "ngrok" in CognitiveInference.NGROK_GATEWAY_URL
