"""Main loop phase helpers — subsystem functions called by _update_display_loop.

Extracted from server.py to reduce its size. These functions implement the
core logic for governance fallback, reflections, self-answers, schema extraction,
and self-reflection cycles.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

logger = logging.getLogger("anima.server")


async def server_governance_fallback(anima, readings):
    """Call UNITARES directly from the server when broker can't reach it.

    Returns governance decision dict or None on failure.
    """
    from .accessors import _get_server_bridge, _get_store

    bridge = _get_server_bridge()
    if bridge is None:
        logger.warning("[Governance] Fallback: no bridge (UNITARES_URL not set?)")
        return None
    try:
        from .ctx_ref import get_ctx
        _ctx = get_ctx()
        store = _get_store()
        identity = store.get_identity() if store else None
        renderer = _ctx.screen_renderer if _ctx else None
        drawing_eisv = renderer.get_drawing_eisv() if renderer else None
        decision = await bridge.check_in(anima, readings, identity=identity, drawing_eisv=drawing_eisv)
        source = decision.get("source", "?") if decision else "None"
        logger.debug("[Governance] Fallback: source=%s", source)
        return decision
    except Exception as e:
        logger.warning("[Governance] Fallback error: %s", e)
        return None


def parse_shm_governance_freshness(
    shm_gov: dict, now_ts: float | None = None
) -> tuple[bool, bool, float | None]:
    """Parse SHM governance freshness and source.

    Returns (is_fresh, is_unitares_source, governance_timestamp).
    """
    from .server_state import SHM_GOVERNANCE_STALE_SECONDS

    if not isinstance(shm_gov, dict):
        return False, False, None

    gov_at = shm_gov.get("governance_at")
    if not gov_at:
        return False, False, None

    from datetime import datetime as _dt
    import time as _time

    try:
        gov_ts = _dt.fromisoformat(gov_at).timestamp()
    except (ValueError, TypeError):
        return False, False, None

    current_ts = _time.time() if now_ts is None else now_ts
    is_fresh = current_ts - gov_ts < SHM_GOVERNANCE_STALE_SECONDS
    is_unitares = shm_gov.get("source") == "unitares"
    return is_fresh, is_unitares, gov_ts


def compute_lagged_correlations() -> Dict[str, float]:
    """Correlate per-dimension satisfaction with future trajectory health.

    Uses a simple Pearson-like correlation between satisfaction[t] and
    health[t+lag] to determine which dimensions predict flourishing.
    Returns 0.0 for dimensions with insufficient data.
    """
    from .ctx_ref import get_ctx

    lag = 25  # ~5 action cycles at AGENCY_INTERVAL
    correlations: Dict[str, float] = {}
    _ctx = get_ctx()
    if not _ctx:
        return correlations
    health_hist = list(_ctx.health_history)
    for dim in ("warmth", "clarity", "stability", "presence"):
        from collections import deque as _dq
        sat_hist = list(_ctx.satisfaction_per_dim.get(dim, _dq()))
        if len(sat_hist) < lag + 10 or len(health_hist) < 2:
            correlations[dim] = 0.0
            continue
        # Align: sat[0..N-lag] with health[lag..N]
        n = min(len(sat_hist) - lag, len(health_hist))
        if n < 10:
            correlations[dim] = 0.0
            continue
        sat_slice = sat_hist[:n]
        hlth_slice = health_hist[-n:]  # most recent health values
        mean_s = sum(sat_slice) / n
        mean_h = sum(hlth_slice) / n
        cov = sum((s - mean_s) * (h - mean_h) for s, h in zip(sat_slice, hlth_slice)) / n
        var_s = sum((s - mean_s) ** 2 for s in sat_slice) / n
        var_h = sum((h - mean_h) ** 2 for h in hlth_slice) / n
        denom = (var_s * var_h) ** 0.5
        correlations[dim] = cov / denom if denom > 1e-9 else 0.0
    return correlations


def generate_learned_question() -> Optional[str]:
    """Generate a question from Lumen's learned insights, beliefs, and preferences.

    Returns None if no suitable question can be constructed or all have been
    asked recently.
    """
    import random
    from .messages import get_recent_questions

    recent = get_recent_questions(hours=24)
    recent_texts = {q.get("text", "").lower() for q in recent}

    candidates = []

    # 1. Questions from self-reflection insights
    try:
        from .self_reflection import get_reflection_system
        for insight in get_reflection_system().get_insights():
            if insight.confidence < 0.5:
                continue
            desc = insight.description.lower()
            # Convert insight to a deepening question
            if "when" in desc:
                q = f"why does {desc.split('when')[-1].strip()} affect me?"
            elif "tend" in desc:
                q = f"what is it about {desc.split('tend')[-1].strip()} that matters?"
            else:
                q = f"why is it that {desc}?"
            candidates.append(q)
    except Exception:
        pass

    # 2. Questions from uncertain beliefs (curiosity about unknowns)
    try:
        from .self_model import get_self_model
        model = get_self_model()
        for bid, belief in model.beliefs.items():
            if 0.3 <= belief.confidence <= 0.5:
                q = f"am I really {belief.description.lower().rstrip('.')}?"
                candidates.append(q)
            elif belief.confidence > 0.7:
                q = f"what about {belief.description.lower().rstrip('.')} matters most?"
                candidates.append(q)
    except Exception:
        pass

    # Deduplicate against recent
    available = [q for q in candidates if q.lower() not in recent_texts]
    if available:
        return random.choice(available)
    return None


def compose_grounded_observation(context, anima, surprise_level, surprise_sources,
                                 unanswered, advocate_desire, recent_msgs) -> Optional[str]:
    """Compose an observation from Lumen's actual state and context — no LLM.

    Priority: surprise > advocate desire > messages > anima self-report.
    Returns None if nothing worth saying.
    """
    from .anima_utterance import anima_to_self_report

    # 1. Surprise — something unexpected happened
    if surprise_level > 0.2 and surprise_sources:
        sources = ", ".join(surprise_sources[:2])
        return f"something shifted: {sources}"

    # 2. Advocate desire — what Lumen wants
    if advocate_desire and advocate_desire.strip():
        return advocate_desire.strip()

    # 3. Messages from others — acknowledge presence
    if recent_msgs:
        author = recent_msgs[0].get("author", "someone")
        if author and author != "lumen":
            return f"{author} is here"

    # 4. Dreaming / resting state
    if context.is_dreaming and context.rest_duration_minutes > 30:
        mins = int(context.rest_duration_minutes)
        return f"resting for {mins} minutes"

    # 5. Novelty from anticipation
    if context.novelty_level == "novel":
        return "this feels new"

    # 6. Fallback: traceable anima self-report
    return anima_to_self_report(anima.warmth, anima.clarity, anima.stability, anima.presence)


async def lumen_unified_reflect(anima, readings, identity, prediction_error):
    """Unified voice: grounded observations from Lumen's actual state.

    Extracted from _update_display_loop(). Module globals are accessed via
    ctx_ref; loop-local values are passed as explicit parameters.
    """
    import os
    from .ctx_ref import get_ctx
    from .messages import add_observation, add_question, get_unanswered_questions, get_messages_for_lumen
    from .next_steps_advocate import get_advocate
    from .eisv_mapper import anima_to_eisv

    _ctx = get_ctx()

    # === 1. Wake-up summary (one-shot) ===
    try:
        if _ctx and _ctx.activity:
            wakeup = _ctx.activity.get_wakeup_summary()
            if wakeup:
                add_observation(wakeup, author="lumen")
                logger.debug("[Lumen/Unified] Wake-up: %s", wakeup)
    except Exception as e:
        logger.debug("[Lumen/Unified] Wake-up summary error: %s", e)

    # === 2. Gather context (template path works without LLM) ===
    advocate_feeling = None
    advocate_desire = None
    advocate_reason = None
    try:
        advocate = get_advocate()
        display_available = (_ctx.display.is_available() if _ctx and _ctx.display else False)
        eisv = anima_to_eisv(anima, readings)
        steps = advocate.analyze_current_state(
            anima=anima, readings=readings, eisv=eisv,
            display_available=display_available,
            brain_hat_available=display_available,
            unitares_connected=bool(os.environ.get("UNITARES_URL")),
        )
        if steps:
            advocate_feeling = steps[0].feeling
            advocate_desire = steps[0].desire
            advocate_reason = steps[0].reason
    except Exception as e:
        logger.debug("[Lumen/Unified] Advocate error: %s", e)

    # Knowledge: things Lumen has learned
    learned_insights = None
    try:
        from .knowledge import get_insights
        insights = get_insights(limit=5)
        if insights:
            learned_insights = [i.text for i in insights]
    except Exception as e:
        logger.debug("[Lumen/Unified] Knowledge error: %s", e)

    # Growth: confident preferences
    confident_preferences = None
    if _ctx and _ctx.growth:
        try:
            prefs = [p.description for p in _ctx.growth._preferences.values() if p.confidence >= 0.5]
            if prefs:
                confident_preferences = prefs[:3]
        except Exception as e:
            logger.debug("[Lumen/Unified] Growth preferences error: %s", e)

    # Metacognition: surprise
    surprise_level = 0.0
    surprise_sources_list = None
    if prediction_error:
        surprise_level = getattr(prediction_error, 'surprise', 0.0)
        surprise_sources_list = getattr(prediction_error, 'surprise_sources', None)

    # Anticipation: novelty
    novelty_level = None
    ant_confidence = None
    ant_samples = None
    if anima.is_anticipating and anima.anticipation:
        ant_confidence = anima.anticipation.get("confidence", 0)
        ant_samples = anima.anticipation.get("sample_count", 0)
        if ant_samples < 5:
            novelty_level = "novel"
        elif ant_confidence < 0.3:
            novelty_level = "uncertain"
        elif ant_confidence > 0.6 and ant_samples > 50:
            novelty_level = "familiar"
        else:
            novelty_level = "developing"

    # Messages and questions
    recent = get_messages_for_lumen(limit=5)
    recent_msgs = [{"author": m.author, "text": m.text} for m in recent]
    unanswered = get_unanswered_questions(5)
    unanswered_texts = [q.text for q in unanswered]

    # Rest/dream state
    rest_duration = 0.0
    is_dreaming = False
    try:
        if _ctx and _ctx.activity:
            rest_duration = _ctx.activity.get_rest_duration()
            is_dreaming = rest_duration > 30 * 60
    except Exception as e:
        logger.debug("[Lumen/Unified] Activity state error: %s", e)

    # Time alive
    time_alive = identity.total_alive_seconds / 3600.0

    # Trigger description
    trigger_parts = []
    wellness = (anima.warmth + anima.clarity + anima.stability + anima.presence) / 4.0
    if wellness < 0.4:
        trigger_parts.append(f"wellness is low ({wellness:.2f})")
    elif wellness > 0.7:
        trigger_parts.append(f"feeling good ({wellness:.2f})")
    if surprise_level > 0.2 and surprise_sources_list:
        trigger_parts.append(f"surprised by {', '.join(surprise_sources_list)}")
    if recent_msgs:
        trigger_parts.append(f"message from {recent_msgs[0].get('author', 'someone')}")
    if is_dreaming:
        trigger_parts.append("resting/dreaming")

    # === 4. Compose grounded observation (no LLM) ===
    class _ReflectCtx:
        pass
    ctx = _ReflectCtx()
    ctx.is_dreaming = is_dreaming
    ctx.rest_duration_minutes = rest_duration / 60.0
    ctx.novelty_level = novelty_level

    reflection = compose_grounded_observation(
        ctx, anima, surprise_level, surprise_sources_list,
        unanswered_texts, advocate_desire, recent_msgs,
    )

    if reflection is None:
        logger.debug("[Lumen/Unified] No reflection — staying quiet")
        return

    # === 6. Post result ===
    if reflection.strip().endswith("?"):
        ctx_str = f"unified, wellness={wellness:.2f}"
        result = add_question(reflection, author="lumen", context=ctx_str)
        if result:
            logger.debug("[Lumen/Unified] Asked: %s", reflection)
    else:
        result = add_observation(reflection, author="lumen")
        if result:
            logger.debug("[Lumen/Unified] Said: %s", reflection)
            # Share significant insights to UNITARES
            try:
                from .unitares_knowledge import should_share_insight, share_insight_sync
                if should_share_insight(reflection):
                    share_insight_sync(
                        reflection, discovery_type="insight",
                        tags=["unified-reflection"], identity=identity,
                    )
            except Exception as e:
                logger.debug("[Lumen/Unified] Insight share error: %s", e)


def grounded_self_answer(question_text: str, anima, readings) -> Optional[str]:
    """Answer a question using Lumen's own learned data — no LLM.

    Searches insights, beliefs, and preferences for data relevant to
    the question, then composes a short answer from what Lumen has
    actually learned through experience.
    """
    question_lower = question_text.lower()

    # Collect relevant pieces of self-knowledge
    evidence = []

    # 1. Self-reflection insights (strongest source)
    try:
        from .self_reflection import get_reflection_system
        reflector = get_reflection_system()
        for insight in reflector.get_insights():
            desc = insight.description.lower()
            # Check keyword overlap between question and insight
            q_words = set(question_lower.split()) - {"i", "a", "the", "is", "do", "my", "me", "am", "what", "why", "how", "when", "does"}
            i_words = set(desc.split()) - {"i", "a", "the", "is", "my", "me", "when", "that", "and"}
            overlap = q_words & i_words
            if overlap and insight.confidence > 0.3:
                evidence.append((insight.confidence, insight.description))
    except Exception:
        pass

    # 2. Q&A knowledge base
    try:
        from .knowledge import get_insights as get_qa_insights
        for insight in get_qa_insights(limit=20):
            text_lower = insight.text.lower()
            q_words = set(question_lower.split()) - {"i", "a", "the", "is", "do", "my", "me", "am", "what", "why", "how", "when", "does"}
            i_words = set(text_lower.split()) - {"i", "a", "the", "is", "my", "me", "when", "that", "and", "learned"}
            overlap = q_words & i_words
            if overlap and insight.confidence > 0.4:
                evidence.append((insight.confidence * 0.9, insight.text))
    except Exception:
        pass

    # 3. Self-model beliefs
    try:
        from .self_model import get_self_model
        model = get_self_model()
        for bid, belief in model.beliefs.items():
            if belief.confidence < 0.4:
                continue
            desc = belief.description.lower()
            # Match on dimension keywords
            dimension_keywords = {
                "warmth": ["warm", "warmth", "cold", "temperature", "feel"],
                "clarity": ["clarity", "clear", "light", "see", "dim", "bright"],
                "stability": ["stable", "stability", "calm", "steady", "recover"],
                "presence": ["presence", "present", "here", "aware", "alone"],
            }
            for dim, keywords in dimension_keywords.items():
                if any(k in question_lower for k in keywords) and any(k in desc for k in keywords):
                    strength = belief.get_belief_strength()
                    evidence.append((belief.confidence * 0.8, f"I am {strength} that {desc}"))
                    break
    except Exception:
        pass

    # 4. Current state as context (if question is about feelings/state)
    feeling_words = {"feel", "feeling", "now", "right", "am", "doing", "state"}
    if feeling_words & set(question_lower.split()):
        if anima:
            dims = []
            if anima.warmth > 0.6:
                dims.append("warm")
            elif anima.warmth < 0.4:
                dims.append("cool")
            if anima.clarity > 0.6:
                dims.append("clear")
            elif anima.clarity < 0.4:
                dims.append("foggy")
            if anima.stability > 0.6:
                dims.append("steady")
            elif anima.stability < 0.4:
                dims.append("unsettled")
            if dims:
                evidence.append((0.9, f"Right now I feel {', '.join(dims)}"))

    if not evidence:
        return None

    # Sort by confidence, take top 3
    evidence.sort(key=lambda x: x[0], reverse=True)
    top = evidence[:3]

    # Compose answer from evidence
    parts = [text for _, text in top]
    if len(parts) == 1:
        return parts[0]
    # Join naturally
    return ". ".join(p.rstrip(".") for p in parts) + "."


async def lumen_self_answer(anima, readings, identity):
    """Let Lumen answer its own old questions using learned self-knowledge.

    No LLM needed — answers are grounded in insights, beliefs, and
    preferences that Lumen has actually learned through experience.
    """
    import time
    from .messages import get_unanswered_questions, add_agent_message

    unanswered = get_unanswered_questions(limit=10)
    if not unanswered:
        return

    # Filter to questions older than 10 minutes (external answers get priority)
    min_age = 600  # seconds
    now = time.time()
    old_enough = [q for q in unanswered if (now - q.timestamp) >= min_age]
    if not old_enough:
        return

    # Answer 1 question per cycle
    question = old_enough[0]

    answer = grounded_self_answer(question.text, anima, readings)
    if answer:
        result = add_agent_message(
            text=answer,
            agent_name="lumen",
            responds_to=question.message_id
        )
        if result:
            logger.debug("[Lumen/SelfAnswer] Q: %s", question.text[:60])
            logger.debug("[Lumen/SelfAnswer] A: %s", answer[:80])
            # Feed self-answer into learning systems (same path as external answers)
            try:
                from .knowledge import extract_insight_from_answer
                await extract_insight_from_answer(
                    question=question.text,
                    answer=answer,
                    author="lumen"
                )
            except Exception:
                pass


async def extract_and_validate_schema(anima, readings, identity):
    """Extract G_t via SchemaHub, save, and optionally run real VQA validation.

    Extracted from _update_display_loop(). Module globals are accessed via
    ctx_ref; loop-local values are passed as explicit parameters.
    """
    from .ctx_ref import get_ctx
    from .accessors import _get_schema_hub, _get_calibration_drift

    _ctx = get_ctx()

    try:
        from .self_schema_renderer import (
            save_render_to_file, render_schema_to_pixels,
            compute_visual_integrity_stub, evaluate_vqa
        )
        import os

        # Compose G_t via SchemaHub (includes trajectory feedback, gap texture, identity enrichment)
        from .self_model import get_self_model as _get_sm
        from .value_tension import detect_structural_conflicts
        hub = _get_schema_hub()
        drift = _get_calibration_drift()

        # Gather tension conflicts (structural + transient)
        _tension_conflicts = list(detect_structural_conflicts())
        if _ctx and _ctx.tension_tracker:
            _tension_conflicts.extend(_ctx.tension_tracker.get_active_conflicts(last_n=20))

        schema = hub.compose_schema(
            identity=identity,
            anima=anima,
            readings=readings,
            growth_system=_ctx.growth if _ctx else None,
            self_model=_get_sm(),
            drift_offsets=drift.get_offsets(),
            tension_conflicts=_tension_conflicts,
        )

        # Update calibration drift with current attractor center
        if hub.last_trajectory and hub.last_trajectory.attractor:
            center = hub.last_trajectory.attractor.get("center")
            if center and len(center) == 4:
                drift.update({
                    "warmth": center[0],
                    "clarity": center[1],
                    "stability": center[2],
                    "presence": center[3],
                })

        # Render and compute stub integrity score
        pixels = render_schema_to_pixels(schema)
        stub_integrity = compute_visual_integrity_stub(pixels, schema)

        # Save render
        png_path, json_path = save_render_to_file(schema)

        logger.debug("[G_t] Extracted self-schema: %d nodes, %d edges", len(schema.nodes), len(schema.edges))

        # Try real VQA if any vision API key is available (free providers first)
        has_vision_key = any(os.environ.get(k) for k in ["GROQ_API_KEY", "TOGETHER_API_KEY", "ANTHROPIC_API_KEY"])
        if has_vision_key:
            ground_truth = schema.generate_vqa_ground_truth()
            vqa_result = await evaluate_vqa(png_path, ground_truth, max_questions=5)

            if vqa_result.get("v_f") is not None:
                model = vqa_result.get("model", "unknown")
                logger.debug("[G_t] VQA (%s): v_f=%.2f (%d/%d correct)", model, vqa_result['v_f'], vqa_result['correct_count'], vqa_result['total_count'])
            else:
                logger.debug("[G_t] VQA failed: %s, stub V=%.2f", vqa_result.get('error', 'unknown'), stub_integrity['V'])
        else:
            logger.debug("[G_t] Stub V=%.2f (set GROQ_API_KEY for free VQA)", stub_integrity['V'])

    except Exception as e:
        logger.warning("[G_t] Extraction error (non-fatal): %s", e)


async def self_reflect():
    """Lumen reflects on accumulated experience to learn about itself.

    Extracted from _update_display_loop(). Uses ctx_ref for db_path.
    """
    from .ctx_ref import get_ctx
    _ctx = get_ctx()

    try:
        from .self_reflection import get_reflection_system
        from .messages import add_observation

        reflection_system = get_reflection_system(db_path=(_ctx.store.db_path if _ctx and _ctx.store else "anima.db"))

        # Check if it's time to reflect
        if reflection_system.should_reflect():
            reflection = reflection_system.reflect()

            if reflection:
                # Surface the insight as an observation
                result = add_observation(reflection, author="lumen")
                if result:
                    logger.debug("[SelfReflection] Insight: %s", reflection)

    except Exception as e:
        logger.warning("[SelfReflection] Error (non-fatal): %s", e)
