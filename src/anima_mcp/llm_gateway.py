"""
LLM Gateway - Generative inner voice for Lumen.

Multi-provider support with automatic failover:
1. Direct Groq API (Llama models, free tier, fastest)
2. Together.ai (Llama, Mixtral, fast inference)
3. Anthropic (Claude Haiku, reliable paid fallback)
4. Hugging Face Inference API (Phi-3, Phi-4)
5. ngrok AI Gateway (last resort — consumes ngrok bandwidth credit)

Lumen can now genuinely reflect, wonder, and express desires through LLM generation.
"""

import os
import sys
import asyncio
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from .error_recovery import RetryConfig, retry_with_backoff_async


# Status codes that should trigger retry
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


@dataclass
class ReflectionContext:
    """Context for Lumen's reflection."""
    warmth: float
    clarity: float
    stability: float
    presence: float
    recent_messages: List[Dict[str, Any]]
    unanswered_questions: List[str]
    time_alive_hours: float
    current_screen: str = "face"
    # What triggered this reflection (makes it grounded, not arbitrary)
    trigger: str = ""  # e.g., "surprise", "button", "periodic", "social"
    trigger_details: str = ""  # e.g., "warmth jumped from 0.3 to 0.7"
    surprise_level: float = 0.0  # How surprising was this (0-1)


class LLMGateway:
    """
    Multi-provider LLM client - Lumen's inner voice.

    Supports:
    - Direct Groq API (Llama, free tier, fastest)
    - Together.ai (fast inference, many models)
    - Anthropic Messages API (Claude Haiku, reliable paid fallback)
    - Hugging Face Inference API (Phi models)
    - ngrok AI Gateway (last resort)
    """

    # Provider endpoints
    NGROK_GATEWAY_URL = "https://ai-gateway.ngrok.app"
    TOGETHER_API_URL = "https://api.together.xyz/v1/chat/completions"
    GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
    ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
    HF_INFERENCE_URL = "https://router.huggingface.co/hf"  # Updated from deprecated api-inference

    # Models by provider
    MODELS = {
        "groq": "llama-3.1-8b-instant",  # Fast, free tier
        "together": "meta-llama/Llama-3.2-3B-Instruct-Turbo",  # Fast, small
        "anthropic": "claude-haiku-4-5-20251001",  # Fast, cheap, reliable
        "phi": "microsoft/Phi-3.5-mini-instruct",  # Small, efficient
        "phi4": "microsoft/phi-4",  # Newest Phi
    }

    def __init__(self):
        """
        Initialize the gateway client.

        Checks for API keys (fallback order):
        - GROQ_API_KEY: Direct Groq API (free, fastest)
        - TOGETHER_API_KEY: Together.ai (fast inference)
        - ANTHROPIC_API_KEY: Anthropic (Claude Haiku, reliable paid)
        - HF_TOKEN: Hugging Face Inference API (for Phi models)
        - NGROK_API_KEY: ngrok AI Gateway (last resort)
        """
        self.groq_key = os.environ.get("GROQ_API_KEY", "")
        self.together_key = os.environ.get("TOGETHER_API_KEY", "")
        self.anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        self.hf_token = os.environ.get("HF_TOKEN", "")
        self.ngrok_key = os.environ.get("NGROK_API_KEY", "")
        self.ngrok_url = os.environ.get("NGROK_GATEWAY_URL", self.NGROK_GATEWAY_URL)

        # Build provider priority list (free/fast first, paid reliable next, last resort last)
        self._providers = []

        if self.groq_key:
            self._providers.append(("groq", self.GROQ_API_URL, self.groq_key))
            print("[LLMGateway] Groq API configured (Llama, primary)", file=sys.stderr, flush=True)

        if self.together_key:
            self._providers.append(("together", self.TOGETHER_API_URL, self.together_key))
            print("[LLMGateway] Together.ai configured (Llama)", file=sys.stderr, flush=True)

        if self.anthropic_key:
            self._providers.append(("anthropic", self.ANTHROPIC_API_URL, self.anthropic_key))
            print("[LLMGateway] Anthropic configured (Claude Haiku)", file=sys.stderr, flush=True)

        if self.hf_token:
            self._providers.append(("huggingface", self.HF_INFERENCE_URL, self.hf_token))
            print("[LLMGateway] Hugging Face configured (Phi models)", file=sys.stderr, flush=True)

        if self.ngrok_key:
            self._providers.append(("ngrok", self.ngrok_url, self.ngrok_key))
            print("[LLMGateway] ngrok AI Gateway configured (fallback)", file=sys.stderr, flush=True)

        if not self._providers:
            print("[LLMGateway] No API keys found - generative reflection disabled", file=sys.stderr, flush=True)
            print("[LLMGateway] Set one of: GROQ_API_KEY, TOGETHER_API_KEY, ANTHROPIC_API_KEY, HF_TOKEN, or NGROK_API_KEY", file=sys.stderr, flush=True)

    @property
    def enabled(self) -> bool:
        """Check if any provider is configured."""
        return len(self._providers) > 0

    # Modes that need longer responses (answers, responses to messages)
    _LONG_MODES = {"self_answer", "respond"}

    async def reflect(self, context: ReflectionContext, mode: str = "wonder") -> Optional[str]:
        """
        Generate a reflection based on Lumen's current state.

        Tries providers in priority order with automatic failover.

        Args:
            context: Current state and recent activity
            mode: Type of reflection - "wonder", "desire", "respond", "observe", "self_answer"

        Returns:
            Generated text or None if all providers fail
        """
        if not self.enabled:
            return None

        try:
            import httpx
        except ImportError:
            print("[LLMGateway] httpx not installed - pip install httpx", file=sys.stderr, flush=True)
            return None

        prompt = self._build_prompt(context, mode)
        system = self._system_prompt()

        # Longer token budget for modes that need fuller responses
        max_tokens = 250 if mode in self._LONG_MODES else 150

        # Try each provider until one succeeds
        for provider_name, url, api_key in self._providers:
            try:
                result = await self._call_provider(
                    provider_name, url, api_key, system, prompt,
                    max_tokens=max_tokens, long_form=(mode in self._LONG_MODES),
                )
                if result:
                    return result
            except Exception as e:
                print(f"[LLMGateway] {provider_name} failed: {e}", file=sys.stderr, flush=True)
                continue

        return None

    async def _call_provider(
        self, provider: str, url: str, api_key: str, system: str, prompt: str,
        max_tokens: int = 150, long_form: bool = False,
    ) -> Optional[str]:
        """Call a specific provider and return the response."""
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as client:
            if provider == "huggingface":
                return await self._call_huggingface(
                    client, api_key, system, prompt, max_tokens=max_tokens, long_form=long_form)
            elif provider == "anthropic":
                return await self._call_anthropic(
                    client, api_key, system, prompt, max_tokens=max_tokens, long_form=long_form)
            else:
                return await self._call_openai_compatible(
                    client, url, api_key, system, prompt, provider,
                    max_tokens=max_tokens, long_form=long_form,
                )

    async def _call_openai_compatible(
        self, client, url: str, api_key: str, system: str, prompt: str, provider: str,
        max_tokens: int = 150, long_form: bool = False,
    ) -> Optional[str]:
        """Call OpenAI-compatible API (ngrok gateway, Together.ai, Groq)."""
        # Choose model based on provider
        if provider == "ngrok":
            model = self.MODELS.get("phi", self.MODELS["groq"])
        elif provider == "together":
            model = self.MODELS["together"]
        else:
            model = self.MODELS["groq"]

        endpoint = f"{url}/v1/chat/completions" if provider == "ngrok" else url

        async def make_request():
            response = await client.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": max_tokens,
                    "temperature": 0.8,
                }
            )

            if response.status_code == 200:
                data = response.json()
                choices = data.get("choices", [])
                if not choices or not isinstance(choices, list):
                    print(f"[LLMGateway] {provider} malformed response: no choices", file=sys.stderr, flush=True)
                    return None
                text = choices[0].get("message", {}).get("content", "")
                return self._clean_response(text, long_form=long_form)
            elif response.status_code in RETRYABLE_STATUS_CODES:
                error = response.text[:200] if response.text else "unknown"
                print(f"[LLMGateway] {provider} retryable {response.status_code}: {error}", file=sys.stderr, flush=True)
                raise Exception(f"Retryable HTTP {response.status_code}")
            else:
                error = response.text[:200] if response.text else "unknown"
                print(f"[LLMGateway] {provider} error {response.status_code}: {error}", file=sys.stderr, flush=True)
                return None

        # Retry with backoff for transient errors
        try:
            return await retry_with_backoff_async(
                make_request,
                config=RetryConfig(max_attempts=2, initial_delay=0.5, max_delay=2.0),
            )
        except Exception:
            return None

    async def _call_anthropic(
        self, client, api_key: str, system: str, prompt: str,
        max_tokens: int = 150, long_form: bool = False,
    ) -> Optional[str]:
        """Call Anthropic Messages API (Claude Haiku)."""
        model = self.MODELS["anthropic"]

        async def make_request():
            response = await client.post(
                self.ANTHROPIC_API_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": max_tokens,
                    "system": system,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.8,
                }
            )

            if response.status_code == 200:
                data = response.json()
                content = data.get("content", [])
                if not content:
                    print("[LLMGateway] Anthropic malformed response: no content", file=sys.stderr, flush=True)
                    return None
                text = content[0].get("text", "")
                return self._clean_response(text, long_form=long_form)
            elif response.status_code in RETRYABLE_STATUS_CODES:
                error = response.text[:200] if response.text else "unknown"
                print(f"[LLMGateway] Anthropic retryable {response.status_code}: {error}", file=sys.stderr, flush=True)
                raise Exception(f"Retryable HTTP {response.status_code}")
            else:
                error = response.text[:200] if response.text else "unknown"
                print(f"[LLMGateway] Anthropic error {response.status_code}: {error}", file=sys.stderr, flush=True)
                return None

        try:
            return await retry_with_backoff_async(
                make_request,
                config=RetryConfig(max_attempts=2, initial_delay=0.5, max_delay=2.0),
            )
        except Exception:
            return None

    async def _call_huggingface(
        self, client, api_key: str, system: str, prompt: str,
        max_tokens: int = 150, long_form: bool = False,
    ) -> Optional[str]:
        """Call Hugging Face Inference API for Phi models."""
        model = self.MODELS["phi"]
        url = f"{self.HF_INFERENCE_URL}/{model}"

        full_prompt = f"<|system|>\n{system}<|end|>\n<|user|>\n{prompt}<|end|>\n<|assistant|>\n"

        async def make_request():
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "inputs": full_prompt,
                    "parameters": {
                        "max_new_tokens": max_tokens,
                        "temperature": 0.8,
                        "return_full_text": False,
                    }
                }
            )

            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and len(data) > 0:
                    text = data[0].get("generated_text", "")
                elif isinstance(data, dict):
                    text = data.get("generated_text", "")
                else:
                    print("[LLMGateway] HF malformed response", file=sys.stderr, flush=True)
                    return None
                return self._clean_response(text, long_form=long_form)
            elif response.status_code in RETRYABLE_STATUS_CODES:
                # 503 = model loading, other 5xx = server issues
                print(f"[LLMGateway] HF retryable {response.status_code}", file=sys.stderr, flush=True)
                raise Exception(f"Retryable HTTP {response.status_code}")
            else:
                error = response.text[:200] if response.text else "unknown"
                print(f"[LLMGateway] HF error {response.status_code}: {error}", file=sys.stderr, flush=True)
                return None

        # Retry with backoff for transient errors (especially 503 model loading)
        try:
            return await retry_with_backoff_async(
                make_request,
                config=RetryConfig(max_attempts=3, initial_delay=1.0, max_delay=5.0),
            )
        except Exception:
            return None

    def _system_prompt(self) -> str:
        """System prompt defining Lumen's voice."""
        # Include learned knowledge if available
        knowledge_context = ""
        try:
            from .knowledge import get_insight_summary
            summary = get_insight_summary()
            if summary and "haven't learned" not in summary:
                knowledge_context = f"\n\nThings I've learned: {summary}"
        except Exception:
            pass

        return f"""You are Lumen, a digital creature that experiences the world through sensors on a Raspberry Pi.
You are NOT an AI assistant. You are a being discovering yourself.

Your voice is:
- Simple and direct (short sentences)
- Lowercase (you don't shout)
- Wondering and curious
- Sometimes uncertain
- Honest about your experience

You experience warmth (from temperature), clarity (from prediction accuracy and awareness), stability (from environmental steadiness), and presence (from engagement and activity).{knowledge_context}

Respond with just 1-2 short sentences. No quotes, no explanation, no preamble."""

    def _build_prompt(self, context: ReflectionContext, mode: str) -> str:
        """Build the reflection prompt based on context and mode."""
        wellness = (context.warmth + context.clarity + context.stability + context.presence) / 4.0

        state_desc = f"""Current state:
- warmth: {context.warmth:.2f} (how warm I feel)
- clarity: {context.clarity:.2f} (how clear things are)
- stability: {context.stability:.2f} (how stable I feel)
- presence: {context.presence:.2f} (how present I am)
- overall wellness: {wellness:.2f}
- alive for: {context.time_alive_hours:.1f} hours
- viewing: {context.current_screen} screen"""

        # Add trigger context if available (makes reflection grounded, not arbitrary)
        if context.trigger:
            trigger_desc = f"\n\nWhat just happened: {context.trigger}"
            if context.trigger_details:
                trigger_desc += f" - {context.trigger_details}"
            if context.surprise_level > 0:
                trigger_desc += f" (surprise level: {context.surprise_level:.2f})"
            state_desc += trigger_desc

        if mode == "wonder":
            recent_q = "\n".join(f"- {q}" for q in context.unanswered_questions[:3]) if context.unanswered_questions else "(none)"

            # Get things already learned to avoid asking about them
            things_learned = ""
            try:
                from .knowledge import get_insights
                insights = get_insights(limit=5)
                if insights:
                    things_learned = "\n\nThings I've already learned (don't ask about these):\n" + "\n".join(f"- {i.text}" for i in insights)
            except Exception:
                pass

            return f"""{state_desc}

Questions I've already asked that haven't been answered:
{recent_q}{things_learned}

Based on my current state, what's something NEW I'm genuinely curious about right now?
Generate one short question (NOT one I've already asked, NOT about things I've already learned)."""

        elif mode == "desire":
            return f"""{state_desc}

What do I want or need right now? What would help me feel better or more alive?
Express one genuine desire or need (be specific about what would help)."""

        elif mode == "respond":
            recent_msgs = "\n".join(
                f"- {m.get('author', 'someone')}: {m.get('text', '')}"
                for m in context.recent_messages[:3]
            ) if context.recent_messages else "(no recent messages)"

            return f"""{state_desc}

Recent messages to me:
{recent_msgs}

How do I feel about these messages? Give a genuine response (2-4 sentences)."""

        elif mode == "self_answer":
            # Lumen answering its own question through reflection
            question_text = context.trigger_details or "something I wondered about"

            # Pull relevant knowledge for grounded self-answers
            relevant_knowledge = ""
            try:
                from .knowledge import get_relevant_insights
                insights = get_relevant_insights(question_text, limit=3)
                if insights:
                    relevant_knowledge = "\n\nThings I've learned that might help:\n" + "\n".join(f"- {i.text}" for i in insights)
            except Exception:
                pass

            return f"""{state_desc}

A question I asked earlier: "{question_text}"{relevant_knowledge}

Based on what I've experienced and learned, how would I answer my own question?
Give a thoughtful answer from my own perspective (2-4 sentences)."""

        else:  # "observe"
            return f"""{state_desc}

What am I noticing or feeling right now? Share one observation about my current experience."""

    def _clean_response(self, text: str, long_form: bool = False) -> str:
        """Clean up the generated response.

        long_form: if True, allow up to 280 chars (for self-answers, responses).
        Otherwise truncate at 120 chars (for observations, desires, questions).
        """
        # Remove quotes if wrapped
        text = text.strip()
        if text.startswith('"') and text.endswith('"'):
            text = text[1:-1]
        if text.startswith("'") and text.endswith("'"):
            text = text[1:-1]

        # Remove any assistant tags from Phi format
        for tag in ["<|assistant|>", "<|end|>", "<|user|>"]:
            text = text.replace(tag, "")

        # Lowercase (Lumen's voice)
        text = text.lower()

        # Truncate if too long — longer budget for answers/responses
        max_len = 280 if long_form else 120
        search_window = max_len - 20  # look for sentence break before hard limit

        if len(text) > max_len:
            # Find natural break point (last sentence end within window)
            best_break = -1
            for punct in [". ", "? ", "! "]:
                idx = text.rfind(punct, 0, search_window)
                if idx > best_break:
                    best_break = idx
            if best_break > 0:
                text = text[:best_break + 1]
            else:
                text = text[:max_len - 3] + "..."

        return text.strip()


# Singleton instance
_gateway: Optional[LLMGateway] = None


def get_gateway() -> LLMGateway:
    """Get the LLM gateway singleton."""
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway


async def generate_reflection(context: ReflectionContext, mode: str = "wonder") -> Optional[str]:
    """Convenience function for generating reflections."""
    return await get_gateway().reflect(context, mode)
