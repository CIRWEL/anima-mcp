"""Communication handlers — Q&A, messaging, voice, and feedback.

Handlers: lumen_qa, post_message, say, configure_voice, primitive_feedback.
"""

import json
import sys

from mcp.types import TextContent


async def handle_lumen_qa(arguments: dict) -> list[TextContent]:
    """
    Unified Q&A tool: list Lumen's questions OR answer one.

    Usage:
    - lumen_qa() -> list unanswered questions
    - lumen_qa(question_id="x", answer="...") -> answer question x
    """
    from ..server import _unitares_bridge
    from ..messages import get_board, MESSAGE_TYPE_QUESTION, add_agent_message

    question_id = arguments.get("question_id")
    answer = arguments.get("answer")
    limit = arguments.get("limit", 5)
    agent_name = arguments.get("agent_name", "agent")
    client_session_id = arguments.get("client_session_id")

    # Resolve verified identity from UNITARES when caller provides their session_id
    # Only attempts resolution if client_session_id is explicitly provided
    if _unitares_bridge and client_session_id:
        try:
            resolved = await _unitares_bridge.resolve_caller_identity(session_id=client_session_id)
            if resolved:
                agent_name = resolved
        except Exception:
            pass  # Fallback to provided agent_name

    # Convert limit to int if string
    if isinstance(limit, str):
        try:
            limit = int(limit)
        except ValueError:
            limit = 5

    board = get_board()
    board._load(force=True)

    # If question_id and answer provided -> answer mode
    if question_id and answer:
        # Find the question with prefix matching support
        question = None
        validated_question_id = None

        # Try exact match first
        for m in board._messages:
            if m.message_id == question_id and m.msg_type == MESSAGE_TYPE_QUESTION:
                question = m
                validated_question_id = question_id
                break

        # If exact match failed, try prefix matching
        if not question:
            matching = [
                m for m in board._messages
                if m.msg_type == MESSAGE_TYPE_QUESTION
                and m.message_id.startswith(question_id)
            ]
            if len(matching) == 1:
                question = matching[0]
                validated_question_id = question.message_id
            elif len(matching) > 1:
                # Multiple matches - use most recent
                question = matching[-1]
                validated_question_id = question.message_id
            else:
                # No match - return helpful error
                all_q_ids = [m.message_id for m in board._messages if m.msg_type == MESSAGE_TYPE_QUESTION]
                return [TextContent(type="text", text=json.dumps({
                    "success": False,
                    "error": f"Question '{question_id}' not found",
                    "hint": "Use the full question ID from lumen_qa()",
                    "recent_question_ids": all_q_ids[-5:] if all_q_ids else []
                }))]

        # Add answer via add_agent_message (handles responds_to linking)
        result = add_agent_message(answer, agent_name=agent_name, responds_to=validated_question_id)

        # Extract insight from Q&A (inline so result visible in response)
        # This populates Lumen's knowledge base with learnings from answers
        insight_result = None
        try:
            from ..knowledge import extract_insight_from_answer
            insight = await extract_insight_from_answer(
                question=question.text,
                answer=answer,
                author=agent_name
            )
            if insight:
                insight_result = {"text": insight.text, "category": insight.category}
                print(f"[Q&A] Extracted insight: {insight.text[:80]}", file=sys.stderr, flush=True)
            else:
                insight_result = {"skipped": "no meaningful insight extracted"}
                print(f"[Q&A] No insight extracted", file=sys.stderr, flush=True)
        except Exception as e:
            insight_result = {"error": str(e)}
            print(f"[Q&A] Insight extraction failed: {e}", file=sys.stderr, flush=True)

        return [TextContent(type="text", text=json.dumps({
            "success": True,
            "action": "answered",
            "question_id": validated_question_id,
            "question_text": question.text,
            "answer": answer,
            "agent_name": agent_name,
            "message_id": result.message_id if result else None,
            "matched_partial_id": question_id if question_id != validated_question_id else None,
            "insight": insight_result,
        }))]

    # Otherwise -> list mode
    # Auto-repair orphaned answered questions (answered=True but no actual answer)
    repaired = board.repair_orphaned_answered()

    # Find questions that have NO actual answer (responds_to link), even if auto-expired
    all_questions = [m for m in board._messages if m.msg_type == MESSAGE_TYPE_QUESTION]
    question_ids = {q.message_id for q in all_questions}

    # Find which questions have actual answers (agent messages with responds_to)
    agent_msgs = [m for m in board._messages if m.msg_type == "agent"]
    answered_ids = {m.responds_to for m in agent_msgs if m.responds_to}

    # Questions without actual answers (includes expired ones)
    truly_unanswered = [q for q in all_questions if q.message_id not in answered_ids]

    questions = truly_unanswered[-limit:] if truly_unanswered else []

    return [TextContent(type="text", text=json.dumps({
        "action": "list",
        "questions": [
            {
                "id": q.message_id,
                "text": q.text,
                "context": q.context,
                "age": q.age_str(),
                "expired": q.answered,  # True if auto-expired but never answered
            }
            for q in questions
        ],
        "unanswered_count": len(truly_unanswered),
        "total_questions": len(all_questions),
        "usage": "To answer: lumen_qa(question_id='<id>', answer='your answer')",
        "note": "Questions marked 'expired: true' auto-expired but were never answered - you can still answer them!"
    }))]


async def handle_post_message(arguments: dict) -> list[TextContent]:
    """
    Post a message to Lumen's message board.
    Consolidates: leave_message + leave_agent_note
    """
    from ..server import (
        _unitares_bridge, _growth, _activity,
        _get_readings_and_anima, _store,
    )
    from ..messages import (
        add_user_message, add_agent_message, get_board, MESSAGE_TYPE_QUESTION,
    )

    message = arguments.get("message", "").strip()
    source = arguments.get("source", "agent")
    agent_name = arguments.get("agent_name", "agent")
    responds_to = arguments.get("responds_to")
    client_session_id = arguments.get("client_session_id")

    # Resolve verified identity from UNITARES when caller provides their session_id
    # Only attempts resolution if client_session_id is explicitly provided
    if _unitares_bridge and client_session_id:
        try:
            resolved = await _unitares_bridge.resolve_caller_identity(session_id=client_session_id)
            if resolved:
                agent_name = resolved
        except Exception:
            pass  # Fallback to provided agent_name

    if not message:
        return [TextContent(type="text", text=json.dumps({
            "error": "message parameter required"
        }))]

    try:
        if source == "human":
            msg_id = add_user_message(message)
            # Track relationship with human
            if _growth:
                try:
                    _growth.record_interaction(
                        agent_id="human",
                        agent_name="human",
                        positive=True,
                        topic=message[:50] if len(message) > 10 else None
                    )
                except Exception:
                    pass  # Non-fatal
            # Wake Lumen on interaction (activity state)
            try:
                if _activity:
                    _activity.record_interaction()
            except Exception:
                pass
            # Snapshot clarity for self-model interaction observation
            try:
                _, cur_anima = _get_readings_and_anima(fallback_to_sensors=False)
                if cur_anima:
                    import anima_mcp.server as _srv
                    _srv._sm_clarity_before_interaction = cur_anima.clarity
            except Exception:
                pass
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "message_id": msg_id,
                "source": "human",
                "message": f"Message received: {message[:50]}..."
            }))]
        else:
            # Agent message - responds_to is passed to add_agent_message
            # Validate responds_to if provided
            validated_question_id = None
            if responds_to:
                board = get_board()
                board._load()
                # Check if question exists (exact match)
                question_found = any(
                    m.message_id == responds_to and m.msg_type == MESSAGE_TYPE_QUESTION
                    for m in board._messages
                )
                if not question_found:
                    # Try prefix matching
                    matching = [
                        m for m in board._messages
                        if m.msg_type == MESSAGE_TYPE_QUESTION
                        and m.message_id.startswith(responds_to)
                    ]
                    if len(matching) == 1:
                        validated_question_id = matching[0].message_id
                    elif len(matching) > 1:
                        # Multiple matches - use most recent
                        validated_question_id = matching[-1].message_id
                    else:
                        # No match - return helpful error
                        all_q_ids = [m.message_id for m in board._messages if m.msg_type == MESSAGE_TYPE_QUESTION]
                        return [TextContent(type="text", text=json.dumps({
                            "error": f"Question ID '{responds_to}' not found",
                            "hint": "Use the full question ID from get_questions()",
                            "recent_question_ids": all_q_ids[-5:] if all_q_ids else []
                        }))]
                else:
                    validated_question_id = responds_to

            msg = add_agent_message(message, agent_name, responds_to=validated_question_id or responds_to)
            # Track relationship with agent
            if _growth:
                try:
                    # Use agent_name as ID (agents have consistent names)
                    is_gift = responds_to is not None  # Answering a question is a gift
                    _growth.record_interaction(
                        agent_id=agent_name,
                        agent_name=agent_name,
                        positive=True,
                        topic=message[:50] if len(message) > 10 else None,
                        gift=is_gift
                    )
                except Exception:
                    pass  # Non-fatal
            # Wake Lumen on interaction (activity state)
            try:
                if _activity:
                    _activity.record_interaction()
            except Exception:
                pass
            # Snapshot clarity for self-model interaction observation
            try:
                _, cur_anima = _get_readings_and_anima(fallback_to_sensors=False)
                if cur_anima:
                    import anima_mcp.server as _srv
                    _srv._sm_clarity_before_interaction = cur_anima.clarity
            except Exception:
                pass
            result = {
                "success": True,
                "message_id": msg.message_id,
                "source": "agent",
                "agent_name": agent_name,
                "message": f"Note received from {agent_name}"
            }
            if responds_to:
                result["answered_question"] = validated_question_id or responds_to
                if validated_question_id and validated_question_id != responds_to:
                    result["note"] = f"Matched partial ID '{responds_to}' to full ID '{validated_question_id}'"
            return [TextContent(type="text", text=json.dumps(result))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "error": str(e)
        }))]


async def handle_say(arguments: dict) -> list[TextContent]:
    """Have Lumen speak - posts to message board (text mode) or uses TTS (audio mode)."""
    from ..server import _store, _get_voice, VOICE_MODE
    from ..messages import add_observation

    text = arguments.get("text", "")

    if not text:
        return [TextContent(type="text", text=json.dumps({
            "error": "No text provided"
        }))]

    # Always post to message board (Lumen's text expression)
    result = add_observation(text, author="lumen")

    # Also show on display notepad
    try:
        if _store:
            _store.add_note(f"[Lumen] {text}")
    except Exception:
        pass

    # Only use audio TTS if mode is "audio" or "both"
    if VOICE_MODE in ("audio", "both"):
        voice = _get_voice()
        if voice and hasattr(voice, '_voice'):
            try:
                voice._voice.say(text, blocking=False)
            except Exception as e:
                print(f"[Say] TTS error (text still posted): {e}", file=sys.stderr, flush=True)

    print(f"[Lumen] Said: {text} (mode={VOICE_MODE})", file=sys.stderr, flush=True)

    return [TextContent(type="text", text=json.dumps({
        "success": True,
        "said": text,
        "mode": VOICE_MODE,
        "posted_to": "message_board"
    }))]


async def handle_configure_voice(arguments: dict) -> list[TextContent]:
    """
    Get or configure Lumen's voice system.
    Consolidates: voice_status + set_voice_mode
    """
    from ..server import _get_voice

    action = arguments.get("action", "status")
    voice = _get_voice()

    if voice is None:
        return [TextContent(type="text", text=json.dumps({
            "error": "Voice system not available"
        }))]

    if action == "status":
        state = voice.state if hasattr(voice, 'state') else None
        return [TextContent(type="text", text=json.dumps({
            "action": "status",
            "available": True,
            "running": voice.is_running,
            "is_listening": state.is_listening if state else False,
            "is_speaking": state.is_speaking if state else False,
            "last_heard": state.last_heard.text if state and state.last_heard else None,
            "chattiness": voice.chattiness,
        }, indent=2))]

    elif action == "configure":
        changes = {}
        if "always_listening" in arguments:
            voice._voice.set_always_listening(arguments["always_listening"])
            changes["always_listening"] = arguments["always_listening"]
        if "chattiness" in arguments:
            voice.chattiness = float(arguments["chattiness"])
            changes["chattiness"] = voice.chattiness
        if "wake_word" in arguments:
            voice._voice._config.wake_word = arguments["wake_word"]
            changes["wake_word"] = arguments["wake_word"]

        return [TextContent(type="text", text=json.dumps({
            "action": "configure",
            "success": True,
            "changes": changes
        }, indent=2))]

    else:
        return [TextContent(type="text", text=json.dumps({
            "error": f"Unknown action: {action}",
            "valid_actions": ["status", "configure"]
        }))]


async def handle_primitive_feedback(arguments: dict) -> list[TextContent]:
    """
    Give feedback on Lumen's primitive language expressions.

    This is the training signal that shapes Lumen's emergent expression:
    - resonate: Strong positive signal (like /resonate command Gemini suggested)
    - confused: Negative signal (expression was unclear)
    - stats: View learning progress
    - recent: List recent utterances with scores
    """
    from ..server import _store
    from ..primitive_language import get_language_system

    action = arguments.get("action", "stats")

    try:
        lang = get_language_system(str(_store.db_path) if _store else "anima.db")

        if action == "resonate":
            # Give strong positive feedback to last utterance
            result = lang.record_explicit_feedback(positive=True)
            if result:
                return [TextContent(type="text", text=json.dumps({
                    "success": True,
                    "action": "resonate",
                    "message": "Positive feedback recorded - this pattern will be reinforced",
                    "score": result["score"],
                    "token_updates": result["token_updates"],
                }))]
            else:
                return [TextContent(type="text", text=json.dumps({
                    "error": "No recent utterance to give feedback on"
                }))]

        elif action == "confused":
            # Give negative feedback
            result = lang.record_explicit_feedback(positive=False)
            if result:
                return [TextContent(type="text", text=json.dumps({
                    "success": True,
                    "action": "confused",
                    "message": "Negative feedback recorded - this pattern will be discouraged",
                    "score": result["score"],
                    "token_updates": result["token_updates"],
                }))]
            else:
                return [TextContent(type="text", text=json.dumps({
                    "error": "No recent utterance to give feedback on"
                }))]

        elif action == "recent":
            # List recent utterances
            recent = lang.get_recent_utterances(10)
            return [TextContent(type="text", text=json.dumps({
                "action": "recent",
                "utterances": recent,
                "count": len(recent),
            }))]

        else:  # stats
            # Get learning statistics
            stats = lang.get_stats()
            return [TextContent(type="text", text=json.dumps({
                "action": "stats",
                "primitive_language_system": stats,
                "help": {
                    "resonate": "Give positive feedback to last expression",
                    "confused": "Give negative feedback to last expression",
                    "recent": "View recent utterances with scores",
                },
            }))]

    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "error": f"Primitive language error: {str(e)}"
        }))]
