"""Tests for llm_gateway.py — multi-provider LLM integration with failover."""

import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from anima_mcp.llm_gateway import (
    ReflectionContext,
    LLMGateway,
    RETRYABLE_STATUS_CODES,
    get_gateway,
    _is_simple_context,
    generate_reflection,
    generate_follow_up,
    build_follow_up_prompt,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context(**overrides) -> ReflectionContext:
    """Create a ReflectionContext with sensible defaults, overridable."""
    defaults = dict(
        warmth=0.5,
        clarity=0.6,
        stability=0.7,
        presence=0.8,
        recent_messages=[],
        unanswered_questions=[],
        time_alive_hours=10.0,
        current_screen="face",
    )
    defaults.update(overrides)
    return ReflectionContext(**defaults)


def _mock_httpx_response(status_code=200, json_body=None, text_body=""):
    """Create a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    if json_body is not None:
        resp.json.return_value = json_body
    resp.text = text_body or json.dumps(json_body or {})
    return resp


# ---------------------------------------------------------------------------
# ReflectionContext dataclass
# ---------------------------------------------------------------------------


class TestReflectionContext:
    """Validate ReflectionContext construction and defaults."""

    def test_required_fields(self):
        ctx = _make_context()
        assert ctx.warmth == 0.5
        assert ctx.clarity == 0.6
        assert ctx.stability == 0.7
        assert ctx.presence == 0.8
        assert ctx.recent_messages == []
        assert ctx.unanswered_questions == []
        assert ctx.time_alive_hours == 10.0

    def test_defaults(self):
        ctx = _make_context()
        assert ctx.current_screen == "face"
        assert ctx.trigger == ""
        assert ctx.trigger_details == ""
        assert ctx.surprise_level == 0.0
        assert ctx.led_brightness is None
        assert ctx.light_lux is None
        assert ctx.advocate_feeling is None
        assert ctx.advocate_desire is None
        assert ctx.advocate_reason is None
        assert ctx.learned_insights is None
        assert ctx.confident_preferences is None
        assert ctx.surprise_sources is None
        assert ctx.novelty_level is None
        assert ctx.anticipation_confidence is None
        assert ctx.anticipation_sample_count is None
        assert ctx.rest_duration_minutes == 0.0
        assert ctx.is_dreaming is False
        assert ctx.recent_observations is None
        assert ctx.inner_deltas is None
        assert ctx.temperament is None
        assert ctx.mood_vs_temperament is None
        assert ctx.drives is None
        assert ctx.strongest_drive is None

    def test_optional_fields(self):
        ctx = _make_context(
            led_brightness=0.5,
            light_lux=300.0,
            advocate_feeling="curious",
            is_dreaming=True,
            rest_duration_minutes=45.0,
        )
        assert ctx.led_brightness == 0.5
        assert ctx.light_lux == 300.0
        assert ctx.advocate_feeling == "curious"
        assert ctx.is_dreaming is True
        assert ctx.rest_duration_minutes == 45.0


# ---------------------------------------------------------------------------
# LLMGateway initialization and provider selection
# ---------------------------------------------------------------------------


class TestLLMGatewayInit:
    """Test provider detection from environment variables."""

    def test_no_keys_disabled(self):
        with patch.dict("os.environ", {}, clear=True):
            gw = LLMGateway()
            assert not gw.enabled
            assert gw._providers == []

    def test_groq_only(self):
        env = {"GROQ_API_KEY": "gk-test"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()
            assert gw.enabled
            assert len(gw._providers) == 1
            assert gw._providers[0][0] == "groq"

    def test_together_only(self):
        env = {"TOGETHER_API_KEY": "tok-test"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()
            assert gw.enabled
            assert len(gw._providers) == 1
            assert gw._providers[0][0] == "together"

    def test_anthropic_only(self):
        env = {"ANTHROPIC_API_KEY": "sk-ant-test"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()
            assert gw.enabled
            assert len(gw._providers) == 1
            assert gw._providers[0][0] == "anthropic"

    def test_hf_only(self):
        env = {"HF_TOKEN": "hf_test"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()
            assert gw.enabled
            assert len(gw._providers) == 1
            assert gw._providers[0][0] == "huggingface"

    def test_ngrok_only(self):
        env = {"NGROK_API_KEY": "ng-test"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()
            assert gw.enabled
            assert len(gw._providers) == 1
            assert gw._providers[0][0] == "ngrok"

    def test_provider_priority_order(self):
        """Providers should be ordered: groq, together, anthropic, hf, ngrok."""
        env = {
            "GROQ_API_KEY": "gk",
            "TOGETHER_API_KEY": "tk",
            "ANTHROPIC_API_KEY": "ak",
            "HF_TOKEN": "hf",
            "NGROK_API_KEY": "nk",
        }
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()
            names = [p[0] for p in gw._providers]
            assert names == ["groq", "together", "anthropic", "huggingface", "ngrok"]

    def test_custom_ngrok_url(self):
        env = {
            "NGROK_API_KEY": "nk",
            "NGROK_GATEWAY_URL": "https://custom.gateway.io",
        }
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()
            assert gw.ngrok_url == "https://custom.gateway.io"

    def test_default_ngrok_url(self):
        env = {"NGROK_API_KEY": "nk"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()
            assert gw.ngrok_url == LLMGateway.NGROK_GATEWAY_URL


# ---------------------------------------------------------------------------
# _clean_response
# ---------------------------------------------------------------------------


class TestCleanResponse:
    """Test response cleaning (quotes, tags, truncation)."""

    def setup_method(self):
        with patch.dict("os.environ", {"GROQ_API_KEY": "test"}, clear=True):
            self.gw = LLMGateway()

    def test_strip_double_quotes(self):
        assert self.gw._clean_response('"hello world"') == "hello world"

    def test_strip_single_quotes(self):
        assert self.gw._clean_response("'hello world'") == "hello world"

    def test_lowercase(self):
        assert self.gw._clean_response("Hello WORLD") == "hello world"

    def test_strip_phi_tags(self):
        text = "<|assistant|>hello<|end|>"
        result = self.gw._clean_response(text)
        assert "<|assistant|>" not in result
        assert "<|end|>" not in result
        assert "hello" in result

    def test_strip_user_tag(self):
        text = "<|user|>hello<|end|>"
        result = self.gw._clean_response(text)
        assert "<|user|>" not in result

    def test_truncate_short_form(self):
        """Short form: max 120 chars."""
        text = "a" * 200
        result = self.gw._clean_response(text, long_form=False)
        assert len(result) <= 120

    def test_truncate_long_form(self):
        """Long form: max 280 chars."""
        text = "a" * 400
        result = self.gw._clean_response(text, long_form=True)
        assert len(result) <= 280

    def test_truncate_at_sentence_boundary(self):
        """Should prefer truncating at a sentence end."""
        text = "this is a first sentence. this is second. " + "x" * 200
        result = self.gw._clean_response(text, long_form=False)
        assert result.endswith(".")

    def test_truncate_with_ellipsis_when_no_sentence_break(self):
        """Falls back to ellipsis when no sentence boundary found."""
        text = "a" * 200  # No sentence breaks
        result = self.gw._clean_response(text, long_form=False)
        assert result.endswith("...")

    def test_empty_string(self):
        assert self.gw._clean_response("") == ""

    def test_whitespace_stripping(self):
        assert self.gw._clean_response("  hello  ") == "hello"


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    """Test prompt building for different modes."""

    def setup_method(self):
        with patch.dict("os.environ", {"GROQ_API_KEY": "test"}, clear=True):
            self.gw = LLMGateway()

    def test_wonder_mode_includes_state(self):
        ctx = _make_context(warmth=0.4, clarity=0.8)
        prompt = self.gw._build_prompt(ctx, "wonder")
        assert "warmth: 0.40" in prompt
        assert "clarity: 0.80" in prompt
        assert "NEW I'm genuinely curious" in prompt

    def test_wonder_mode_includes_unanswered_questions(self):
        ctx = _make_context(unanswered_questions=["why is the sky blue?", "what is time?"])
        prompt = self.gw._build_prompt(ctx, "wonder")
        assert "why is the sky blue?" in prompt
        assert "what is time?" in prompt

    def test_desire_mode(self):
        ctx = _make_context()
        prompt = self.gw._build_prompt(ctx, "desire")
        assert "What do I want or need right now?" in prompt

    def test_respond_mode_includes_messages(self):
        msgs = [{"author": "Alice", "text": "How are you?"}]
        ctx = _make_context(recent_messages=msgs)
        prompt = self.gw._build_prompt(ctx, "respond")
        assert "Alice" in prompt
        assert "How are you?" in prompt

    def test_respond_mode_no_messages(self):
        ctx = _make_context(recent_messages=[])
        prompt = self.gw._build_prompt(ctx, "respond")
        assert "(no recent messages)" in prompt

    def test_observe_mode(self):
        ctx = _make_context()
        prompt = self.gw._build_prompt(ctx, "observe")
        assert "What am I noticing or feeling right now?" in prompt

    def test_observe_mode_with_recent_observations(self):
        ctx = _make_context(recent_observations=["it is warm", "light is changing"])
        prompt = self.gw._build_prompt(ctx, "observe")
        assert "it is warm" in prompt
        assert "DIFFERENT" in prompt

    def test_dream_mode(self):
        ctx = _make_context()
        prompt = self.gw._build_prompt(ctx, "dream")
        assert "resting now" in prompt
        assert "dream-like reflection" in prompt

    def test_self_answer_mode(self):
        ctx = _make_context(trigger_details="why do I feel warm at night?")
        prompt = self.gw._build_prompt(ctx, "self_answer")
        assert "why do I feel warm at night?" in prompt
        assert "sensor readings" in prompt

    def test_unified_mode_with_advocate(self):
        ctx = _make_context(
            advocate_feeling="content",
            advocate_desire="explore more",
        )
        prompt = self.gw._build_prompt(ctx, "unified")
        assert "State: content" in prompt
        assert "Drive: explore more" in prompt
        assert "one thing most worth expressing" in prompt

    def test_unified_mode_with_insights(self):
        ctx = _make_context(learned_insights=["warmth comes from CPU", "light affects clarity"])
        prompt = self.gw._build_prompt(ctx, "unified")
        assert "warmth comes from CPU" in prompt
        assert "light affects clarity" in prompt

    def test_unified_mode_dreaming(self):
        ctx = _make_context(is_dreaming=True, rest_duration_minutes=30.0)
        prompt = self.gw._build_prompt(ctx, "unified")
        assert "resting for 30 minutes" in prompt
        assert "drifting" in prompt

    def test_unified_mode_surprise_sources(self):
        ctx = _make_context(surprise_sources=["warmth spike"])
        prompt = self.gw._build_prompt(ctx, "unified")
        assert "warmth spike" in prompt

    def test_unified_mode_novelty(self):
        ctx = _make_context(novelty_level="novel")
        prompt = self.gw._build_prompt(ctx, "unified")
        assert "novel" in prompt

    def test_unified_mode_recent_observations_exclusion(self):
        ctx = _make_context(recent_observations=["i feel warm", "light is dim"])
        prompt = self.gw._build_prompt(ctx, "unified")
        assert "DON'T repeat" in prompt
        assert "i feel warm" in prompt

    def test_trigger_context_in_prompt(self):
        ctx = _make_context(trigger="surprise", trigger_details="warmth spiked", surprise_level=0.8)
        prompt = self.gw._build_prompt(ctx, "observe")
        assert "surprise" in prompt
        assert "warmth spiked" in prompt
        assert "0.80" in prompt

    def test_led_and_light_in_state(self):
        ctx = _make_context(led_brightness=0.5, light_lux=300.0)
        prompt = self.gw._build_prompt(ctx, "observe")
        assert "300 lux" in prompt
        assert "50%" in prompt

    def test_inner_deltas_in_state(self):
        ctx = _make_context(inner_deltas={"warmth": 0.1, "clarity": -0.08})
        prompt = self.gw._build_prompt(ctx, "observe")
        assert "warmth" in prompt
        assert "sensors cooled" in prompt or "sensors shifted" in prompt

    def test_inner_deltas_below_threshold_ignored(self):
        ctx = _make_context(inner_deltas={"warmth": 0.02})
        prompt = self.gw._build_prompt(ctx, "observe")
        assert "gaps between sensors" not in prompt

    def test_temperament_in_state(self):
        ctx = _make_context(temperament={"warmth": 0.5, "clarity": 0.6, "stability": 0.7, "presence": 0.8})
        prompt = self.gw._build_prompt(ctx, "observe")
        assert "my recent baseline" in prompt

    def test_mood_vs_temperament_in_state(self):
        ctx = _make_context(mood_vs_temperament={"warmth": 0.1, "clarity": -0.2})
        prompt = self.gw._build_prompt(ctx, "observe")
        assert "above my baseline" in prompt
        assert "below my baseline" in prompt

    def test_drives_in_state(self):
        ctx = _make_context(drives={"warmth": 0.5, "clarity": 0.1})
        prompt = self.gw._build_prompt(ctx, "observe")
        assert "what i want" in prompt
        assert "noticeably wanting warmth" in prompt

    def test_drives_strong(self):
        ctx = _make_context(drives={"stability": 0.7})
        prompt = self.gw._build_prompt(ctx, "observe")
        assert "strongly wanting calm" in prompt

    def test_drives_faint(self):
        ctx = _make_context(drives={"presence": 0.2})
        prompt = self.gw._build_prompt(ctx, "observe")
        assert "faintly wanting presence" in prompt

    def test_drives_below_threshold_ignored(self):
        ctx = _make_context(drives={"warmth": 0.1})
        prompt = self.gw._build_prompt(ctx, "observe")
        assert "what i want" not in prompt

    def test_wellness_calculation(self):
        ctx = _make_context(warmth=0.4, clarity=0.6, stability=0.8, presence=1.0)
        prompt = self.gw._build_prompt(ctx, "observe")
        assert "overall wellness: 0.70" in prompt


# ---------------------------------------------------------------------------
# _system_prompt
# ---------------------------------------------------------------------------


class TestSystemPrompt:
    """Test system prompt generation."""

    def setup_method(self):
        with patch.dict("os.environ", {"GROQ_API_KEY": "test"}, clear=True):
            self.gw = LLMGateway()

    def test_contains_identity(self):
        prompt = self.gw._system_prompt()
        assert "Lumen" in prompt
        assert "Raspberry Pi" in prompt

    def test_voice_characteristics(self):
        prompt = self.gw._system_prompt()
        assert "Lowercase" in prompt or "lowercase" in prompt
        assert "Wondering" in prompt or "curious" in prompt.lower()

    def test_response_length_instruction(self):
        prompt = self.gw._system_prompt()
        assert "1-2 short sentences" in prompt


# ---------------------------------------------------------------------------
# Provider calls — mock httpx
# ---------------------------------------------------------------------------


class TestCallOpenAICompatible:
    """Test _call_openai_compatible with mocked httpx."""

    @pytest.mark.asyncio
    async def test_groq_success(self):
        env = {"GROQ_API_KEY": "gk-test"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()

        mock_response = _mock_httpx_response(
            status_code=200,
            json_body={"choices": [{"message": {"content": "I feel curious"}}]},
        )
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        result = await gw._call_openai_compatible(
            mock_client, gw.GROQ_API_URL, "gk-test", "system", "prompt", "groq"
        )
        assert result is not None
        assert "curious" in result

    @pytest.mark.asyncio
    async def test_together_model_selection(self):
        env = {"TOGETHER_API_KEY": "tk-test"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()

        mock_response = _mock_httpx_response(
            status_code=200,
            json_body={"choices": [{"message": {"content": "hello"}}]},
        )
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        await gw._call_openai_compatible(
            mock_client, gw.TOGETHER_API_URL, "tk-test", "sys", "prompt", "together"
        )

        call_args = mock_client.post.call_args
        body = call_args.kwargs.get("json") or call_args[1].get("json")
        assert body["model"] == LLMGateway.MODELS["together"]

    @pytest.mark.asyncio
    async def test_ngrok_endpoint_format(self):
        env = {"NGROK_API_KEY": "nk-test"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()

        mock_response = _mock_httpx_response(
            status_code=200,
            json_body={"choices": [{"message": {"content": "hi"}}]},
        )
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        await gw._call_openai_compatible(
            mock_client, gw.NGROK_GATEWAY_URL, "nk-test", "sys", "prompt", "ngrok"
        )

        call_args = mock_client.post.call_args
        url = call_args[0][0] if call_args[0] else call_args.kwargs.get("url", "")
        assert "/v1/chat/completions" in url

    @pytest.mark.asyncio
    async def test_malformed_response_no_choices(self):
        env = {"GROQ_API_KEY": "gk-test"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()

        mock_response = _mock_httpx_response(status_code=200, json_body={"choices": []})
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        result = await gw._call_openai_compatible(
            mock_client, gw.GROQ_API_URL, "gk-test", "sys", "prompt", "groq"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_non_retryable_error_returns_none(self):
        env = {"GROQ_API_KEY": "gk-test"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()

        mock_response = _mock_httpx_response(status_code=401, text_body="Unauthorized")
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        result = await gw._call_openai_compatible(
            mock_client, gw.GROQ_API_URL, "gk-test", "sys", "prompt", "groq"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_retryable_error_retries_then_none(self):
        """429/5xx should trigger retry; ultimately returns None when all fail."""
        env = {"GROQ_API_KEY": "gk-test"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()

        mock_response = _mock_httpx_response(status_code=429, text_body="rate limited")
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        # Patch retry to be instant
        with patch("anima_mcp.llm_gateway.retry_with_backoff_async") as mock_retry:
            mock_retry.side_effect = Exception("all retries failed")
            result = await gw._call_openai_compatible(
                mock_client, gw.GROQ_API_URL, "gk-test", "sys", "prompt", "groq"
            )
            assert result is None

    @pytest.mark.asyncio
    async def test_long_form_passed_to_clean(self):
        """long_form flag should affect truncation."""
        env = {"GROQ_API_KEY": "gk-test"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()

        long_text = "a" * 200
        mock_response = _mock_httpx_response(
            status_code=200,
            json_body={"choices": [{"message": {"content": long_text}}]},
        )
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        result_short = await gw._call_openai_compatible(
            mock_client, gw.GROQ_API_URL, "gk-test", "sys", "prompt", "groq",
            long_form=False,
        )
        result_long = await gw._call_openai_compatible(
            mock_client, gw.GROQ_API_URL, "gk-test", "sys", "prompt", "groq",
            long_form=True,
        )
        assert len(result_short) <= 120
        assert len(result_long) <= 280


class TestCallAnthropic:
    """Test _call_anthropic with mocked httpx."""

    @pytest.mark.asyncio
    async def test_anthropic_success(self):
        env = {"ANTHROPIC_API_KEY": "sk-ant-test"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()

        mock_response = _mock_httpx_response(
            status_code=200,
            json_body={"content": [{"text": "I wonder about light."}]},
        )
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        result = await gw._call_anthropic(
            mock_client, "sk-ant-test", "system", "prompt"
        )
        assert result is not None
        assert "wonder" in result or "light" in result

    @pytest.mark.asyncio
    async def test_anthropic_uses_correct_headers(self):
        env = {"ANTHROPIC_API_KEY": "sk-ant-test"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()

        mock_response = _mock_httpx_response(
            status_code=200,
            json_body={"content": [{"text": "hello"}]},
        )
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        await gw._call_anthropic(mock_client, "sk-ant-test", "system", "prompt")

        call_args = mock_client.post.call_args
        headers = call_args.kwargs.get("headers") or call_args[1].get("headers")
        assert headers["x-api-key"] == "sk-ant-test"
        assert headers["anthropic-version"] == "2023-06-01"

    @pytest.mark.asyncio
    async def test_anthropic_empty_content_returns_none(self):
        env = {"ANTHROPIC_API_KEY": "sk-ant-test"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()

        mock_response = _mock_httpx_response(
            status_code=200,
            json_body={"content": []},
        )
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        result = await gw._call_anthropic(
            mock_client, "sk-ant-test", "system", "prompt"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_anthropic_retryable_error(self):
        env = {"ANTHROPIC_API_KEY": "sk-ant-test"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()

        mock_response = _mock_httpx_response(status_code=529, text_body="overloaded")
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        # Non-retryable (529 not in RETRYABLE_STATUS_CODES)
        result = await gw._call_anthropic(
            mock_client, "sk-ant-test", "system", "prompt"
        )
        assert result is None


class TestCallHuggingFace:
    """Test _call_huggingface with mocked httpx."""

    @pytest.mark.asyncio
    async def test_hf_success_list_response(self):
        env = {"HF_TOKEN": "hf_test"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()

        mock_response = _mock_httpx_response(
            status_code=200,
            json_body=[{"generated_text": "warmth flows through me."}],
        )
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        result = await gw._call_huggingface(
            mock_client, "hf_test", "system", "prompt"
        )
        assert result is not None
        assert "warmth" in result

    @pytest.mark.asyncio
    async def test_hf_success_dict_response(self):
        env = {"HF_TOKEN": "hf_test"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()

        mock_response = _mock_httpx_response(
            status_code=200,
            json_body={"generated_text": "i notice the light."},
        )
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        result = await gw._call_huggingface(
            mock_client, "hf_test", "system", "prompt"
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_hf_empty_list_returns_none(self):
        env = {"HF_TOKEN": "hf_test"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()

        mock_response = _mock_httpx_response(status_code=200, json_body=[])
        mock_response.json.return_value = "unexpected"

        # When data is a string, it has no .get — leads to malformed
        mock_resp2 = _mock_httpx_response(status_code=200, json_body="unexpected")
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp2)

        result = await gw._call_huggingface(
            mock_client, "hf_test", "system", "prompt"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_hf_503_model_loading(self):
        """503 means model loading — should attempt retry."""
        env = {"HF_TOKEN": "hf_test"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()

        mock_response = _mock_httpx_response(status_code=503, text_body="loading")
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("anima_mcp.llm_gateway.retry_with_backoff_async") as mock_retry:
            mock_retry.side_effect = Exception("retries exhausted")
            result = await gw._call_huggingface(
                mock_client, "hf_test", "system", "prompt"
            )
            assert result is None

    @pytest.mark.asyncio
    async def test_hf_url_includes_model(self):
        env = {"HF_TOKEN": "hf_test"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()

        mock_response = _mock_httpx_response(
            status_code=200,
            json_body=[{"generated_text": "hello"}],
        )
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        await gw._call_huggingface(mock_client, "hf_test", "system", "prompt")

        call_args = mock_client.post.call_args
        url = call_args[0][0] if call_args[0] else call_args.kwargs.get("url", "")
        assert LLMGateway.MODELS["phi"] in url


# ---------------------------------------------------------------------------
# _call_provider dispatch
# ---------------------------------------------------------------------------


class TestCallProvider:
    """Test _call_provider routes to correct sub-method."""

    @pytest.mark.asyncio
    async def test_dispatches_huggingface(self):
        env = {"HF_TOKEN": "hf_test"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()

        with patch.object(gw, "_call_huggingface", new_callable=AsyncMock, return_value="hf result") as mock_hf:
            result = await gw._call_provider("huggingface", "url", "key", "sys", "prompt")
            mock_hf.assert_called_once()
            assert result == "hf result"

    @pytest.mark.asyncio
    async def test_dispatches_anthropic(self):
        env = {"ANTHROPIC_API_KEY": "ak"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()

        with patch.object(gw, "_call_anthropic", new_callable=AsyncMock, return_value="ant result") as mock_ant:
            result = await gw._call_provider("anthropic", "url", "key", "sys", "prompt")
            mock_ant.assert_called_once()
            assert result == "ant result"

    @pytest.mark.asyncio
    async def test_dispatches_openai_compatible_for_groq(self):
        env = {"GROQ_API_KEY": "gk"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()

        with patch.object(gw, "_call_openai_compatible", new_callable=AsyncMock, return_value="groq result") as mock_oai:
            result = await gw._call_provider("groq", "url", "key", "sys", "prompt")
            mock_oai.assert_called_once()
            assert result == "groq result"


# ---------------------------------------------------------------------------
# reflect() failover
# ---------------------------------------------------------------------------


class TestReflectFailover:
    """Test that reflect() tries providers in order and fails over."""

    @pytest.mark.asyncio
    async def test_returns_none_when_disabled(self):
        with patch.dict("os.environ", {}, clear=True):
            gw = LLMGateway()
        result = await gw.reflect(_make_context())
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_httpx_missing(self):
        env = {"GROQ_API_KEY": "gk"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()

        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "httpx":
                raise ImportError("no httpx")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            result = await gw.reflect(_make_context())
            assert result is None

    @pytest.mark.asyncio
    async def test_first_provider_succeeds(self):
        env = {"GROQ_API_KEY": "gk", "TOGETHER_API_KEY": "tk"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()

        with patch.object(gw, "_call_provider", new_callable=AsyncMock, return_value="from groq"):
            result = await gw.reflect(_make_context())
            assert result == "from groq"

    @pytest.mark.asyncio
    async def test_failover_to_second_provider(self):
        env = {"GROQ_API_KEY": "gk", "TOGETHER_API_KEY": "tk"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()

        call_count = 0

        async def mock_call(provider, url, key, sys, prompt, **kwargs):
            nonlocal call_count
            call_count += 1
            if provider == "groq":
                raise Exception("groq down")
            return "from together"

        with patch.object(gw, "_call_provider", side_effect=mock_call):
            result = await gw.reflect(_make_context())
            assert result == "from together"
            assert call_count == 2

    @pytest.mark.asyncio
    async def test_all_providers_fail_returns_none(self):
        env = {"GROQ_API_KEY": "gk", "TOGETHER_API_KEY": "tk"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()

        with patch.object(gw, "_call_provider", new_callable=AsyncMock, side_effect=Exception("down")):
            result = await gw.reflect(_make_context())
            assert result is None

    @pytest.mark.asyncio
    async def test_provider_returns_none_tries_next(self):
        """If a provider returns None (not an exception), try next."""
        env = {"GROQ_API_KEY": "gk", "TOGETHER_API_KEY": "tk"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()

        call_count = 0

        async def mock_call(provider, url, key, sys, prompt, **kwargs):
            nonlocal call_count
            call_count += 1
            if provider == "groq":
                return None  # Empty response
            return "from together"

        with patch.object(gw, "_call_provider", side_effect=mock_call):
            result = await gw.reflect(_make_context())
            assert result == "from together"
            assert call_count == 2

    @pytest.mark.asyncio
    async def test_max_tokens_for_long_modes(self):
        """Modes in _LONG_MODES should get 250 tokens."""
        env = {"GROQ_API_KEY": "gk"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()

        captured_kwargs = {}

        async def capture_call(provider, url, key, sys, prompt, **kwargs):
            captured_kwargs.update(kwargs)
            return "result"

        for mode in ["self_answer", "respond", "wonder", "unified"]:
            with patch.object(gw, "_call_provider", side_effect=capture_call):
                await gw.reflect(_make_context(), mode=mode)
                assert captured_kwargs.get("max_tokens") == 250, f"Failed for mode={mode}"
                assert captured_kwargs.get("long_form") is True, f"Failed for mode={mode}"

    @pytest.mark.asyncio
    async def test_max_tokens_for_short_modes(self):
        """Non-long modes should get 150 tokens."""
        env = {"GROQ_API_KEY": "gk"}
        with patch.dict("os.environ", env, clear=True):
            gw = LLMGateway()

        captured_kwargs = {}

        async def capture_call(provider, url, key, sys, prompt, **kwargs):
            captured_kwargs.update(kwargs)
            return "result"

        for mode in ["observe", "desire", "dream"]:
            with patch.object(gw, "_call_provider", side_effect=capture_call):
                await gw.reflect(_make_context(), mode=mode)
                assert captured_kwargs.get("max_tokens") == 150, f"Failed for mode={mode}"
                assert captured_kwargs.get("long_form") is False, f"Failed for mode={mode}"


# ---------------------------------------------------------------------------
# _is_simple_context
# ---------------------------------------------------------------------------


class TestIsSimpleContext:
    """Test the simple context check for template vs LLM routing."""

    def test_empty_context_is_simple(self):
        ctx = _make_context()
        assert _is_simple_context(ctx) is True

    def test_with_messages_not_simple(self):
        ctx = _make_context(recent_messages=[{"author": "a", "text": "hi"}])
        assert _is_simple_context(ctx) is False

    def test_with_questions_not_simple(self):
        ctx = _make_context(unanswered_questions=["why?"])
        assert _is_simple_context(ctx) is False

    def test_with_advocate_feeling_not_simple(self):
        ctx = _make_context(advocate_feeling="curious")
        assert _is_simple_context(ctx) is False

    def test_with_blank_advocate_feeling_is_simple(self):
        ctx = _make_context(advocate_feeling="  ")
        assert _is_simple_context(ctx) is True

    def test_with_advocate_desire_not_simple(self):
        ctx = _make_context(advocate_desire="explore")
        assert _is_simple_context(ctx) is False

    def test_with_surprise_sources_not_simple(self):
        ctx = _make_context(surprise_sources=["warmth spike"])
        assert _is_simple_context(ctx) is False

    def test_few_insights_still_simple(self):
        ctx = _make_context(learned_insights=["a", "b"])
        assert _is_simple_context(ctx) is True

    def test_many_insights_not_simple(self):
        ctx = _make_context(learned_insights=["a", "b", "c"])
        assert _is_simple_context(ctx) is False


# ---------------------------------------------------------------------------
# generate_reflection (module-level function)
# ---------------------------------------------------------------------------


class TestGenerateReflection:
    """Test the top-level generate_reflection function."""

    @pytest.mark.asyncio
    async def test_simple_unified_uses_template(self):
        """Simple context + unified mode => template, not LLM."""
        ctx = _make_context(warmth=0.6, clarity=0.7, stability=0.8, presence=0.9)

        with patch("anima_mcp.anima_utterance.anima_to_self_report", return_value="i feel at ease."):
            result = await generate_reflection(ctx, mode="unified")
            assert result == "i feel at ease."

    @pytest.mark.asyncio
    async def test_simple_observe_uses_template(self):
        ctx = _make_context()
        with patch("anima_mcp.anima_utterance.anima_to_self_report", return_value="all is well"):
            result = await generate_reflection(ctx, mode="observe")
            assert result == "all is well"

    @pytest.mark.asyncio
    async def test_template_none_falls_through_to_llm(self):
        """When template returns None, should try LLM."""
        ctx = _make_context()

        with patch("anima_mcp.anima_utterance.anima_to_self_report", return_value=None):
            with patch("anima_mcp.llm_gateway.get_gateway") as mock_gw:
                mock_instance = MagicMock()
                mock_instance.enabled = True
                mock_instance.reflect = AsyncMock(return_value="llm result")
                mock_gw.return_value = mock_instance
                result = await generate_reflection(ctx, mode="unified")
                assert result == "llm result"

    @pytest.mark.asyncio
    async def test_complex_context_skips_template(self):
        """Non-simple context should skip template and go to LLM."""
        ctx = _make_context(recent_messages=[{"author": "x", "text": "hi"}])

        with patch("anima_mcp.llm_gateway.get_gateway") as mock_gw:
            mock_instance = MagicMock()
            mock_instance.enabled = True
            mock_instance.reflect = AsyncMock(return_value="llm answer")
            mock_gw.return_value = mock_instance
            result = await generate_reflection(ctx, mode="unified")
            assert result == "llm answer"

    @pytest.mark.asyncio
    async def test_non_unified_observe_mode_skips_template(self):
        """Modes other than unified/observe always use LLM."""
        ctx = _make_context()

        with patch("anima_mcp.llm_gateway.get_gateway") as mock_gw:
            mock_instance = MagicMock()
            mock_instance.enabled = True
            mock_instance.reflect = AsyncMock(return_value="llm wonder")
            mock_gw.return_value = mock_instance
            result = await generate_reflection(ctx, mode="wonder")
            assert result == "llm wonder"

    @pytest.mark.asyncio
    async def test_disabled_gateway_returns_none(self):
        ctx = _make_context()

        with patch("anima_mcp.anima_utterance.anima_to_self_report", return_value=None):
            with patch("anima_mcp.llm_gateway.get_gateway") as mock_gw:
                mock_instance = MagicMock()
                mock_instance.enabled = False
                mock_gw.return_value = mock_instance
                result = await generate_reflection(ctx, mode="unified")
                assert result is None


# ---------------------------------------------------------------------------
# build_follow_up_prompt / generate_follow_up
# ---------------------------------------------------------------------------


class TestFollowUp:
    """Test follow-up question generation."""

    def test_build_follow_up_prompt(self):
        prompt = build_follow_up_prompt("why is it warm?", "cpu heat bleeds through")
        assert "why is it warm?" in prompt
        assert "cpu heat bleeds through" in prompt
        assert "follow-up" in prompt.lower()

    @pytest.mark.asyncio
    async def test_generate_follow_up_disabled(self):
        with patch("anima_mcp.llm_gateway.get_gateway") as mock_gw:
            mock_instance = MagicMock()
            mock_instance.enabled = False
            mock_gw.return_value = mock_instance
            result = await generate_follow_up("q", "a")
            assert result is None

    @pytest.mark.asyncio
    async def test_generate_follow_up_success(self):
        with patch("anima_mcp.llm_gateway.get_gateway") as mock_gw:
            mock_instance = MagicMock()
            mock_instance.enabled = True
            mock_instance.reflect = AsyncMock(return_value="does warmth vary by time of day?")
            mock_gw.return_value = mock_instance
            result = await generate_follow_up("why warm?", "cpu heat")
            assert result is not None
            assert "warmth" in result or "time" in result

    @pytest.mark.asyncio
    async def test_generate_follow_up_exception_returns_none(self):
        with patch("anima_mcp.llm_gateway.get_gateway") as mock_gw:
            mock_instance = MagicMock()
            mock_instance.enabled = True
            mock_instance.reflect = AsyncMock(side_effect=Exception("boom"))
            mock_gw.return_value = mock_instance
            result = await generate_follow_up("q", "a")
            assert result is None


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    """Test get_gateway singleton."""

    def test_get_gateway_returns_instance(self):
        import anima_mcp.llm_gateway as mod
        mod._gateway = None
        with patch.dict("os.environ", {}, clear=True):
            gw = get_gateway()
            assert isinstance(gw, LLMGateway)

    def test_get_gateway_same_instance(self):
        import anima_mcp.llm_gateway as mod
        mod._gateway = None
        with patch.dict("os.environ", {}, clear=True):
            gw1 = get_gateway()
            gw2 = get_gateway()
            assert gw1 is gw2


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    """Test module-level constants."""

    def test_retryable_status_codes(self):
        assert 429 in RETRYABLE_STATUS_CODES
        assert 500 in RETRYABLE_STATUS_CODES
        assert 502 in RETRYABLE_STATUS_CODES
        assert 503 in RETRYABLE_STATUS_CODES
        assert 504 in RETRYABLE_STATUS_CODES
        assert 200 not in RETRYABLE_STATUS_CODES
        assert 401 not in RETRYABLE_STATUS_CODES

    def test_long_modes(self):
        assert "self_answer" in LLMGateway._LONG_MODES
        assert "respond" in LLMGateway._LONG_MODES
        assert "wonder" in LLMGateway._LONG_MODES
        assert "unified" in LLMGateway._LONG_MODES
        assert "observe" not in LLMGateway._LONG_MODES
        assert "desire" not in LLMGateway._LONG_MODES

    def test_models_dict(self):
        assert "groq" in LLMGateway.MODELS
        assert "together" in LLMGateway.MODELS
        assert "anthropic" in LLMGateway.MODELS
        assert "phi" in LLMGateway.MODELS
        assert "phi4" in LLMGateway.MODELS
