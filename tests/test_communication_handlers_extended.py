import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _parse(result):
    assert isinstance(result, list)
    assert len(result) == 1
    return json.loads(result[0].text)


class TestCallerNameResolution:
    def test_parse_caller_name_from_ua_variants(self):
        from anima_mcp.handlers.communication import _parse_caller_name_from_ua

        assert _parse_caller_name_from_ua("claude-code/2.1.56 (claude-vscode)") == "Claude Code (VSCode)"
        assert _parse_caller_name_from_ua("claude-code/2.1.56") == "Claude Code"
        assert _parse_caller_name_from_ua("cursor/0.50.1") == "Cursor"
        assert _parse_caller_name_from_ua("windsurf/0.1") == "Windsurf"
        assert _parse_caller_name_from_ua("custom-client/1.0") == "custom-client"
        assert _parse_caller_name_from_ua("") is None

    def test_resolve_caller_name_prefers_explicit_agent_name(self):
        from anima_mcp.handlers.communication import _resolve_caller_name

        assert _resolve_caller_name({"agent_name": "Kenny"}) == "Kenny"

    def test_resolve_caller_name_uses_user_agent_fallback(self):
        from anima_mcp.handlers.communication import _resolve_caller_name

        with patch("anima_mcp.handlers.communication._get_request_headers", return_value={"user-agent": "cursor/1.2.3"}):
            assert _resolve_caller_name({"agent_name": "agent"}) == "Cursor"


@pytest.mark.asyncio
class TestConfigureVoice:
    async def test_status_returns_voice_state(self):
        from anima_mcp.handlers.communication import handle_configure_voice

        state = SimpleNamespace(
            is_listening=True,
            is_speaking=False,
            last_heard=SimpleNamespace(text="hello"),
        )
        voice = SimpleNamespace(is_running=True, chattiness=0.4, state=state)

        with patch("anima_mcp.server._get_voice", return_value=voice):
            data = _parse(await handle_configure_voice({"action": "status"}))

        assert data["action"] == "status"
        assert data["available"] is True
        assert data["running"] is True
        assert data["is_listening"] is True
        assert data["last_heard"] == "hello"

    async def test_configure_updates_voice_settings(self):
        from anima_mcp.handlers.communication import handle_configure_voice

        low_voice = MagicMock()
        low_voice._config = SimpleNamespace(wake_word="lumen")
        voice = SimpleNamespace(
            is_running=True,
            chattiness=0.2,
            state=None,
            _voice=low_voice,
        )

        with patch("anima_mcp.server._get_voice", return_value=voice):
            data = _parse(await handle_configure_voice({
                "action": "configure",
                "always_listening": True,
                "chattiness": 0.9,
                "wake_word": "anima",
            }))

        low_voice.set_always_listening.assert_called_once_with(True)
        assert data["success"] is True
        assert data["changes"]["always_listening"] is True
        assert data["changes"]["chattiness"] == 0.9
        assert data["changes"]["wake_word"] == "anima"

    async def test_unknown_action_returns_error(self):
        from anima_mcp.handlers.communication import handle_configure_voice

        voice = SimpleNamespace(is_running=True, chattiness=0.2, state=None)
        with patch("anima_mcp.server._get_voice", return_value=voice):
            data = _parse(await handle_configure_voice({"action": "bad"}))

        assert "error" in data
        assert "valid_actions" in data


@pytest.mark.asyncio
class TestPrimitiveFeedback:
    async def test_resonate_success_returns_score(self):
        from anima_mcp.handlers.communication import handle_primitive_feedback

        lang = MagicMock()
        lang.record_explicit_feedback.return_value = {"score": 0.7, "token_updates": {"warm": 1}}
        with patch("anima_mcp.server._store", SimpleNamespace(db_path=":memory:")), \
             patch("anima_mcp.primitive_language.get_language_system", return_value=lang):
            data = _parse(await handle_primitive_feedback({"action": "resonate"}))

        assert data["success"] is True
        assert data["action"] == "resonate"
        assert data["score"] == 0.7

    async def test_recent_returns_utterances_list(self):
        from anima_mcp.handlers.communication import handle_primitive_feedback

        lang = MagicMock()
        lang.get_recent_utterances.return_value = [{"text": "pulse", "score": 0.2}]
        with patch("anima_mcp.server._store", SimpleNamespace(db_path=":memory:")), \
             patch("anima_mcp.primitive_language.get_language_system", return_value=lang):
            data = _parse(await handle_primitive_feedback({"action": "recent"}))

        assert data["action"] == "recent"
        assert data["count"] == 1

    async def test_stats_is_default_action(self):
        from anima_mcp.handlers.communication import handle_primitive_feedback

        lang = MagicMock()
        lang.get_stats.return_value = {"utterances": 42}
        with patch("anima_mcp.server._store", SimpleNamespace(db_path=":memory:")), \
             patch("anima_mcp.primitive_language.get_language_system", return_value=lang):
            data = _parse(await handle_primitive_feedback({}))

        assert data["action"] == "stats"
        assert data["primitive_language_system"]["utterances"] == 42


@pytest.mark.asyncio
class TestPostMessageRespondsToMatching:
    async def test_agent_message_matches_partial_question_id(self):
        from anima_mcp.handlers.communication import handle_post_message

        question = SimpleNamespace(message_id="q_abcdef1234", msg_type="question")
        board = SimpleNamespace(_messages=[question], _load=MagicMock())
        msg = SimpleNamespace(message_id="msg_1")
        growth = MagicMock()
        growth.get_visitor_context.return_value = {"relationship": "trusted"}

        with patch("anima_mcp.server._growth", growth), \
             patch("anima_mcp.server._activity", None), \
             patch("anima_mcp.server._store", None), \
             patch("anima_mcp.server._get_readings_and_anima", return_value=(None, None)), \
             patch("anima_mcp.messages.get_board", return_value=board), \
             patch("anima_mcp.messages.add_agent_message", return_value=msg):
            data = _parse(await handle_post_message({
                "message": "Here is my answer",
                "source": "agent",
                "responds_to": "q_abc",
                "agent_name": "Cursor",
            }))

        assert data["success"] is True
        assert data["answered_question"] == "q_abcdef1234"
        assert "Matched partial ID" in data["note"]
        assert data["visitor_context"]["relationship"] == "trusted"

    async def test_agent_message_returns_error_for_unknown_question(self):
        from anima_mcp.handlers.communication import handle_post_message

        board = SimpleNamespace(_messages=[], _load=MagicMock())
        with patch("anima_mcp.server._growth", None), \
             patch("anima_mcp.server._activity", None), \
             patch("anima_mcp.server._store", None), \
             patch("anima_mcp.server._get_readings_and_anima", return_value=(None, None)), \
             patch("anima_mcp.messages.get_board", return_value=board):
            data = _parse(await handle_post_message({
                "message": "answer",
                "source": "agent",
                "responds_to": "missing",
            }))

        assert "error" in data
        assert "not found" in data["error"]
