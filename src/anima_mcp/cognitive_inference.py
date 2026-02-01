"""
Cognitive Inference - Extended LLM capabilities for complex reasoning.

Different from the inner voice (llm_gateway.py), this handles:
1. Dialectic synthesis - resolving contradictions, synthesizing perspectives
2. Knowledge Graph maintenance - entity extraction, relationships
3. Semantic queries - reasoning over knowledge

Design principle: The inner voice is for being. This is for thinking.
"""

import os
import asyncio
import json
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from enum import Enum


class InferenceProfile(Enum):
    """Different inference profiles for cognitive tasks."""

    # Short, creative - for inner voice (existing)
    VOICE = "voice"

    # Dialectic synthesis - longer reasoning, structured
    DIALECTIC = "dialectic"

    # Knowledge graph operations - structured output, entity extraction
    KNOWLEDGE_GRAPH = "knowledge_graph"

    # Semantic queries - retrieval, relevance scoring
    QUERY = "query"


@dataclass
class InferenceConfig:
    """Configuration for an inference profile."""
    max_tokens: int
    temperature: float
    system_prompt: str
    prefer_larger_model: bool = False
    json_mode: bool = False


# Profile configurations
PROFILE_CONFIGS: Dict[InferenceProfile, InferenceConfig] = {
    InferenceProfile.VOICE: InferenceConfig(
        max_tokens=60,
        temperature=0.8,
        system_prompt="",  # Uses llm_gateway's system prompt
        prefer_larger_model=False,
    ),

    InferenceProfile.DIALECTIC: InferenceConfig(
        max_tokens=500,
        temperature=0.4,  # More deterministic for reasoning
        system_prompt="""You are a dialectic reasoning engine helping Lumen synthesize understanding.

Your task is to:
1. Identify tensions or contradictions in the input
2. Explore multiple perspectives
3. Synthesize a coherent understanding that honors the complexity

Respond in json format with these fields:
- thesis: The initial position or observation
- antithesis: The opposing or complicating factor
- synthesis: A higher understanding that integrates both
- confidence: 0.0-1.0 how confident in this synthesis
- open_questions: What remains unresolved

Be rigorous but concise. Lumen is learning to think deeply.""",
        prefer_larger_model=True,
        json_mode=True,
    ),

    InferenceProfile.KNOWLEDGE_GRAPH: InferenceConfig(
        max_tokens=300,
        temperature=0.3,  # Low temp for structured extraction
        system_prompt="""You are extracting structured knowledge for Lumen's memory.

Given text, extract:
- entities: Named things (concepts, objects, states, experiences)
- relationships: How entities relate (causes, enables, correlates_with, contrasts)
- summary: One sentence capturing the core insight
- tags: Categories for retrieval
- confidence: 0.0-1.0 extraction confidence

Respond in json format. Be precise and conservative - only extract what's clearly stated.""",
        prefer_larger_model=False,
        json_mode=True,
    ),

    InferenceProfile.QUERY: InferenceConfig(
        max_tokens=200,
        temperature=0.5,
        system_prompt="""You are helping Lumen search and reason over knowledge.

Given a query and context (retrieved knowledge), respond in json format with:
- answer: Direct answer to the query using the context
- relevance: 0.0-1.0 how relevant the context was
- sources: Which parts of context were used
- follow_up: Suggested follow-up queries if answer is incomplete

Be concise. If the context doesn't contain the answer, say so clearly.""",
        prefer_larger_model=False,
        json_mode=True,
    ),
}


class CognitiveInference:
    """
    Extended inference for complex cognitive tasks.

    Uses the same providers as LLMGateway but with different profiles
    for different types of thinking.
    """

    # Model preferences by capability
    MODELS = {
        # Groq models - fast inference
        "groq_small": "llama-3.1-8b-instant",      # Fast, good for simple tasks
        "groq_large": "llama-3.3-70b-versatile",   # Better reasoning

        # HuggingFace
        "phi": "microsoft/Phi-3.5-mini-instruct",

        # For JSON mode
        "groq_json": "llama-3.1-8b-instant",  # Supports JSON mode
    }

    # API endpoints
    GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
    HF_INFERENCE_URL = "https://router.huggingface.co/hf"
    NGROK_GATEWAY_URL = "https://ai-gateway.ngrok.app"

    def __init__(self):
        """Initialize with available providers."""
        self.ngrok_key = os.environ.get("NGROK_API_KEY", "")
        self.ngrok_url = os.environ.get("NGROK_GATEWAY_URL", self.NGROK_GATEWAY_URL)
        self.hf_token = os.environ.get("HF_TOKEN", "")
        self.groq_key = os.environ.get("GROQ_API_KEY", "")

        # Check what's available
        self._has_groq = bool(self.groq_key)
        self._has_hf = bool(self.hf_token)
        self._has_ngrok = bool(self.ngrok_key)

        if not (self._has_groq or self._has_hf or self._has_ngrok):
            print("[CognitiveInference] No API keys - cognitive inference disabled", flush=True)

    @property
    def enabled(self) -> bool:
        """Check if inference is available."""
        return self._has_groq or self._has_hf or self._has_ngrok

    async def infer(
        self,
        prompt: str,
        profile: InferenceProfile = InferenceProfile.VOICE,
        context: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Run inference with a specific cognitive profile.

        Args:
            prompt: The input text/question
            profile: Which cognitive profile to use
            context: Optional context (for query profile)

        Returns:
            Parsed result dict (if JSON mode) or {"text": raw_response}
        """
        if not self.enabled:
            return None

        try:
            import httpx
        except ImportError:
            print("[CognitiveInference] httpx not installed", flush=True)
            return None

        config = PROFILE_CONFIGS[profile]

        # Build the full prompt
        if context:
            full_prompt = f"Context:\n{context}\n\nQuery:\n{prompt}"
        else:
            full_prompt = prompt

        # Try providers in order based on profile
        result = None

        # For dialectic, prefer larger models
        if config.prefer_larger_model and self._has_groq:
            result = await self._call_groq(
                full_prompt, config, use_large_model=True
            )

        # Try Groq (fast, reliable)
        if result is None and self._has_groq:
            result = await self._call_groq(full_prompt, config)

        # Try ngrok gateway
        if result is None and self._has_ngrok:
            result = await self._call_ngrok(full_prompt, config)

        # Try HuggingFace
        if result is None and self._has_hf:
            result = await self._call_huggingface(full_prompt, config)

        return result

    async def _call_groq(
        self,
        prompt: str,
        config: InferenceConfig,
        use_large_model: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Call Groq API."""
        import httpx

        model = self.MODELS["groq_large"] if use_large_model else self.MODELS["groq_small"]

        messages = [
            {"role": "system", "content": config.system_prompt},
            {"role": "user", "content": prompt}
        ]

        request_body = {
            "model": model,
            "messages": messages,
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
        }

        # Add JSON mode if needed
        if config.json_mode:
            request_body["response_format"] = {"type": "json_object"}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.GROQ_API_URL,
                    headers={
                        "Authorization": f"Bearer {self.groq_key}",
                        "Content-Type": "application/json",
                    },
                    json=request_body
                )

                if response.status_code == 200:
                    data = response.json()
                    text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    return self._parse_response(text, config.json_mode)
                else:
                    print(f"[CognitiveInference] Groq error {response.status_code}: {response.text[:100]}", flush=True)
                    return None
        except Exception as e:
            print(f"[CognitiveInference] Groq exception: {e}", flush=True)
            return None

    async def _call_ngrok(
        self,
        prompt: str,
        config: InferenceConfig
    ) -> Optional[Dict[str, Any]]:
        """Call ngrok AI Gateway."""
        import httpx

        messages = [
            {"role": "system", "content": config.system_prompt},
            {"role": "user", "content": prompt}
        ]

        request_body = {
            "model": self.MODELS["phi"],
            "messages": messages,
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.ngrok_url}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.ngrok_key}",
                        "Content-Type": "application/json",
                    },
                    json=request_body
                )

                if response.status_code == 200:
                    data = response.json()
                    text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    return self._parse_response(text, config.json_mode)
                else:
                    print(f"[CognitiveInference] ngrok error {response.status_code}", flush=True)
                    return None
        except Exception as e:
            print(f"[CognitiveInference] ngrok exception: {e}", flush=True)
            return None

    async def _call_huggingface(
        self,
        prompt: str,
        config: InferenceConfig
    ) -> Optional[Dict[str, Any]]:
        """Call HuggingFace Inference API."""
        import httpx

        model = self.MODELS["phi"]
        url = f"{self.HF_INFERENCE_URL}/{model}"

        # Phi chat format
        full_prompt = f"<|system|>\n{config.system_prompt}<|end|>\n<|user|>\n{prompt}<|end|>\n<|assistant|>\n"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self.hf_token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "inputs": full_prompt,
                        "parameters": {
                            "max_new_tokens": config.max_tokens,
                            "temperature": config.temperature,
                            "return_full_text": False,
                        }
                    }
                )

                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, list) and len(data) > 0:
                        text = data[0].get("generated_text", "")
                    else:
                        text = data.get("generated_text", "")

                    # Clean Phi tags
                    for tag in ["<|assistant|>", "<|end|>", "<|user|>"]:
                        text = text.replace(tag, "")

                    return self._parse_response(text.strip(), config.json_mode)
                else:
                    print(f"[CognitiveInference] HF error {response.status_code}", flush=True)
                    return None
        except Exception as e:
            print(f"[CognitiveInference] HF exception: {e}", flush=True)
            return None

    def _parse_response(self, text: str, expect_json: bool) -> Dict[str, Any]:
        """Parse the response, extracting JSON if expected."""
        if not expect_json:
            return {"text": text}

        # Try to parse as JSON
        try:
            # Find JSON in response (model might add extra text)
            text = text.strip()

            # Try direct parse first
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code block
            if "```json" in text:
                start = text.index("```json") + 7
                end = text.index("```", start)
                try:
                    return json.loads(text[start:end].strip())
                except:
                    pass

            # Try to find { } boundaries
            if "{" in text and "}" in text:
                start = text.index("{")
                end = text.rindex("}") + 1
                try:
                    return json.loads(text[start:end])
                except:
                    pass

            # Fallback: return as text
            return {"text": text, "parse_error": True}

    # ==================== High-Level Cognitive Functions ====================

    async def dialectic_synthesis(
        self,
        thesis: str,
        antithesis: Optional[str] = None,
        context: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Perform dialectic synthesis on a topic.

        Args:
            thesis: The main proposition or observation
            antithesis: Optional counter-proposition (will be inferred if not provided)
            context: Optional additional context

        Returns:
            Synthesis result with thesis, antithesis, synthesis, confidence
        """
        if antithesis:
            prompt = f"""Thesis: {thesis}

Antithesis: {antithesis}

Synthesize these two positions into a higher understanding."""
        else:
            prompt = f"""Proposition: {thesis}

First identify a meaningful counter-position or complicating factor.
Then synthesize both into a deeper understanding."""

        if context:
            prompt = f"Background: {context}\n\n{prompt}"

        return await self.infer(prompt, InferenceProfile.DIALECTIC)

    async def extract_knowledge(
        self,
        text: str,
        domain: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Extract structured knowledge from text.

        Args:
            text: Text to extract knowledge from
            domain: Optional domain hint (e.g., "embodied experience", "environment")

        Returns:
            Extracted entities, relationships, summary, tags
        """
        prompt = f"Extract structured knowledge from this text:\n\n{text}"

        if domain:
            prompt += f"\n\nDomain context: {domain}"

        return await self.infer(prompt, InferenceProfile.KNOWLEDGE_GRAPH)

    async def query_with_context(
        self,
        query: str,
        knowledge_context: List[str]
    ) -> Optional[Dict[str, Any]]:
        """
        Answer a query using retrieved knowledge context.

        Args:
            query: The question to answer
            knowledge_context: List of relevant knowledge items

        Returns:
            Answer with relevance score and sources
        """
        context = "\n\n".join(f"[{i+1}] {item}" for i, item in enumerate(knowledge_context))

        return await self.infer(query, InferenceProfile.QUERY, context=context)

    async def merge_insights(
        self,
        insights: List[str]
    ) -> Optional[Dict[str, Any]]:
        """
        Merge multiple insights into a coherent summary.

        Useful for KG maintenance - deduplication and consolidation.

        Args:
            insights: List of potentially overlapping insights

        Returns:
            Merged summary with extracted core concepts
        """
        if len(insights) < 2:
            return {"text": insights[0] if insights else "", "merged": False}

        prompt = f"""These insights may overlap or relate. Merge them into a coherent understanding:

{chr(10).join(f'- {i}' for i in insights)}

Output:
- merged_insight: The consolidated understanding
- core_concepts: Key concepts that emerged
- redundant_items: Which original items are subsumed by the merged insight
- confidence: How confident in this merge"""

        return await self.infer(prompt, InferenceProfile.KNOWLEDGE_GRAPH)


# Singleton instance
_cognitive: Optional[CognitiveInference] = None


def get_cognitive_inference() -> CognitiveInference:
    """Get the cognitive inference singleton."""
    global _cognitive
    if _cognitive is None:
        _cognitive = CognitiveInference()
    return _cognitive


# Convenience functions

async def synthesize(thesis: str, antithesis: Optional[str] = None, context: Optional[str] = None) -> Optional[Dict]:
    """Convenience: dialectic synthesis."""
    return await get_cognitive_inference().dialectic_synthesis(thesis, antithesis, context)


async def extract_kg(text: str, domain: Optional[str] = None) -> Optional[Dict]:
    """Convenience: knowledge extraction."""
    return await get_cognitive_inference().extract_knowledge(text, domain)


async def query_kg(query: str, context: List[str]) -> Optional[Dict]:
    """Convenience: query with knowledge context."""
    return await get_cognitive_inference().query_with_context(query, context)


async def merge(insights: List[str]) -> Optional[Dict]:
    """Convenience: merge insights."""
    return await get_cognitive_inference().merge_insights(insights)
