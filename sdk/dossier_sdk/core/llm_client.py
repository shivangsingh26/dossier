"""
core/llm_client.py — Single entry point for ALL LLM calls in the Dossier project.

No agent imports openai or anthropic directly. They all call LLMClient().call().

WHY CENTRALISE LLM CALLS:
- If an SDK changes (openai v2 → v3), we fix it in ONE place, not across every agent
- Retry logic, cost logging, rate limiting can be added here once — all agents get it free
- Easy to mock in tests without hitting real APIs
- Model routing lives here: gpt-* → OpenAI client, claude-* → Anthropic client

ROUTING LOGIC:
- Model names starting with "gpt-" or "o" → OpenAI chat completions API
- Model names starting with "claude-" → Anthropic messages API

PHASE A NOTE:
All calls are synchronous. Phase C will add async versions when we need parallel calls.

OPENAI v2.x NOTE:
The v2.x SDK uses "developer" role (not "system") for system-level instructions.
This is the recommended pattern for gpt-5 family models. Both roles work, but
"developer" is what OpenAI's own examples show in their v2 SDK README.

WHY _openai AND _anthropic (WITH UNDERSCORE):
1. Avoids name collision: we already imported the 'openai' module at the top.
   self.openai would shadow that module name inside the class.
2. Single underscore = Python convention for "internal detail, don't access directly".
   Use LLMClient().call(...), not LLMClient()._openai.chat.completions.create(...)

THREAD SAFETY:
The singleton uses double-checked locking (threading.Lock) so two ThreadPoolExecutor
workers initialising simultaneously can't both call _init_clients(). After init, the
OpenAI and Anthropic SDK clients are stateless per request — safe to share across threads.

RETRY POLICY (SDK-native):
Both SDKs have built-in retry with exponential backoff via the max_retries parameter.
max_retries=3 means: 1 original attempt + up to 3 retries on 429 (rate limit) and
5xx errors. Auth errors (401) are never retried — they are permanent failures.
We do not write manual retry loops: the SDK's implementation is correct and battle-tested.

COST TRACKING:
Both SDKs return token usage natively in every response (response.usage). We read these
and accumulate per-model counters in self._usage. Call get_usage_summary() at the end of
a pipeline run to log total cost in last_orchestrator_run.json.
Pricing table matches CLAUDE.md (verified May 2026).
"""

import base64
import threading
from pathlib import Path

import openai
import anthropic

from dossier_sdk.config import Config
from dossier_sdk.core.logger import get_logger

logger = get_logger(__name__)

# Cost per million tokens — verified May 2026 (matches CLAUDE.md pricing table)
_COST_PER_M: dict[str, dict[str, float]] = {
    "gpt-5.4-mini":              {"input": 0.75,  "output": 4.50},
    "gpt-5":                     {"input": 1.25,  "output": 10.00},
    "claude-haiku-4-5-20251001": {"input": 1.00,  "output": 5.00},
    "claude-sonnet-4-6":         {"input": 3.00,  "output": 15.00},
}


class LLMClient:
    _instance = None
    _lock = threading.Lock()  # guards singleton initialisation under concurrent threads

    def __new__(cls):
        # Double-checked locking: cheap path (no lock) after first init.
        # Without this, two ThreadPoolExecutor workers could both see _instance is None
        # before either sets it, causing _init_clients() to run twice simultaneously.
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init_clients()
        return cls._instance

    def _init_clients(self) -> None:
        """Initialise both SDK clients with built-in retry. Called exactly once."""
        config = Config()

        # max_retries=3: the SDK retries automatically on 429 (rate limit) and 5xx errors
        # with exponential backoff. This is the official SDK pattern — no manual loops needed.
        self._openai = openai.OpenAI(
            api_key=config.openai_api_key,
            max_retries=3,
        )
        self._anthropic = anthropic.Anthropic(
            api_key=config.anthropic_api_key,
            max_retries=3,
        )

        # Per-model usage counters — populated from response.usage after every call.
        # Keyed by model name → {prompt_tokens, completion_tokens, calls}
        self._usage: dict[str, dict[str, int]] = {}

        logger.info("LLM clients initialised (OpenAI + Anthropic, max_retries=3)")

    def _track_usage(self, model: str, prompt_tokens: int, completion_tokens: int) -> None:
        """Accumulate token counts from response.usage into per-model counters."""
        if model not in self._usage:
            self._usage[model] = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
        self._usage[model]["prompt_tokens"] += prompt_tokens
        self._usage[model]["completion_tokens"] += completion_tokens
        self._usage[model]["calls"] += 1

    def get_usage_summary(self) -> dict:
        """
        Return accumulated token usage and estimated cost across all calls this run.
        Reads from response.usage counters collected during _call_openai / _call_anthropic.
        Call this at the end of a pipeline stage to include in last_orchestrator_run.json.
        """
        total_prompt = sum(v["prompt_tokens"] for v in self._usage.values())
        total_completion = sum(v["completion_tokens"] for v in self._usage.values())
        total_calls = sum(v["calls"] for v in self._usage.values())

        total_cost = 0.0
        per_model: dict = {}
        for model, counts in self._usage.items():
            # Fall back to gpt-5.4-mini rates for any unlisted model — conservative estimate
            rates = _COST_PER_M.get(model, {"input": 0.75, "output": 4.50})
            cost = (
                (counts["prompt_tokens"] / 1_000_000) * rates["input"]
                + (counts["completion_tokens"] / 1_000_000) * rates["output"]
            )
            total_cost += cost
            per_model[model] = {
                "calls": counts["calls"],
                "prompt_tokens": counts["prompt_tokens"],
                "completion_tokens": counts["completion_tokens"],
                "cost_usd": round(cost, 5),
            }

        return {
            "total_calls": total_calls,
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_tokens": total_prompt + total_completion,
            "estimated_cost_usd": round(total_cost, 5),
            "per_model": per_model,
        }

    def call(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int = 2048,
    ) -> str:
        """
        Make a single synchronous LLM call. Returns the response as a plain string.

        Args:
            system_prompt: The agent's identity, rules, and output schema (constant per agent)
            user_prompt:   The actual data for this specific call (changes every call)
            model:         Model name from Config — e.g. Config().model_nano
            max_tokens:    Maximum tokens in the response (default 2048)

        Returns:
            The model's response as a plain string.

        Raises:
            ValueError: If the model name is not recognised as OpenAI or Anthropic
            openai.APIError / anthropic.APIError: Propagated on API failure after SDK retries
        """
        logger.debug(f"LLM call | model={model} | system={system_prompt[:60]}...")

        if model.startswith("gpt-") or model.startswith("o"):
            result = self._call_openai(system_prompt, user_prompt, model, max_tokens)
        elif model.startswith("claude-"):
            result = self._call_anthropic(system_prompt, user_prompt, model, max_tokens)
        else:
            raise ValueError(
                f"[LLMClient] Unknown model '{model}'. "
                f"Model must start with 'gpt-', 'o', or 'claude-'."
            )

        logger.debug(f"LLM response | model={model} | length={len(result)} chars")
        return result

    def _call_openai(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
    ) -> str:
        """Call the OpenAI chat completions API. Returns response text.

        Retries are handled by the SDK (max_retries=3, set at client init).
        Token usage is read from response.usage — the official SDK response field.
        """
        try:
            response = self._openai.chat.completions.create(
                model=model,
                max_completion_tokens=max_tokens,  # GPT-5 family uses max_completion_tokens
                messages=[
                    # "developer" is the v2.x SDK recommended role for system-level instructions
                    {"role": "developer", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            # response.usage is the official SDK field — always present in non-streaming calls
            usage = response.usage
            if usage:
                self._track_usage(model, usage.prompt_tokens, usage.completion_tokens)
                logger.debug(
                    f"Tokens | {usage.prompt_tokens}p + {usage.completion_tokens}c "
                    f"= {usage.total_tokens}t | model={model}"
                )
            return response.choices[0].message.content or ""

        except openai.AuthenticationError as e:
            logger.error(f"OpenAI authentication failed — check OPENAI_API_KEY in .env: {e}")
            raise
        except openai.RateLimitError as e:
            # Raised only after all SDK retries exhausted
            logger.error(f"OpenAI rate limit — all retries exhausted: {e}")
            raise
        except openai.APIConnectionError as e:
            logger.error(f"OpenAI connection failed — check internet / API status: {e}")
            raise
        except openai.APIStatusError as e:
            logger.error(f"OpenAI API error {e.status_code}: {e.message}")
            raise

    def call_vision(self, image_path: Path, prompt: str, model: str = None) -> str:
        """
        Send an image + text prompt to Claude and return the response as a plain string.
        Used for extracting text from image-based resumes (PNG, JPG).

        Only works with Anthropic models — Claude has native vision support.

        Args:
            image_path: Path to the image file (PNG, JPG, WEBP, GIF)
            prompt:     What to ask about the image (e.g. "Extract all text from this resume")
            model:      Claude model to use (defaults to claude-haiku-4-5 for cost efficiency)
        """
        config = Config()
        model = model or config.model_cover  # claude-haiku-4-5 — vision + cheap

        suffix = image_path.suffix.lower()
        media_type_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }
        media_type = media_type_map.get(suffix, "image/png")

        image_data = base64.standard_b64encode(image_path.read_bytes()).decode("utf-8")

        logger.debug(f"Vision call | model={model} | image={image_path.name}")

        try:
            response = self._anthropic.messages.create(
                model=model,
                max_tokens=4096,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": image_data,
                                },
                            },
                            {
                                "type": "text",
                                "text": prompt,
                            },
                        ],
                    }
                ],
            )
            # Track vision call usage
            usage = response.usage
            if usage:
                self._track_usage(model, usage.input_tokens, usage.output_tokens)

            return response.content[0].text

        except anthropic.AuthenticationError as e:
            logger.error(f"Anthropic authentication failed: {e}")
            raise
        except anthropic.APIStatusError as e:
            logger.error(f"Anthropic vision API error {e.status_code}: {e.message}")
            raise

    def _call_anthropic(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
    ) -> str:
        """Call the Anthropic Messages API. Returns response text.

        Retries are handled by the SDK (max_retries=3, set at client init).
        Token usage is read from response.usage — the official SDK response field.
        Note: Anthropic uses input_tokens/output_tokens (not prompt/completion).
        """
        try:
            response = self._anthropic.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt},
                ],
            )
            # Anthropic SDK: response.usage.input_tokens / output_tokens
            usage = response.usage
            if usage:
                self._track_usage(model, usage.input_tokens, usage.output_tokens)
                logger.debug(
                    f"Tokens | {usage.input_tokens}p + {usage.output_tokens}c "
                    f"= {usage.input_tokens + usage.output_tokens}t | model={model}"
                )
            return response.content[0].text

        except anthropic.AuthenticationError as e:
            logger.error(f"Anthropic authentication failed — check ANTHROPIC_API_KEY in .env: {e}")
            raise
        except anthropic.RateLimitError as e:
            # Raised only after all SDK retries exhausted
            logger.error(f"Anthropic rate limit — all retries exhausted: {e}")
            raise
        except anthropic.APIConnectionError as e:
            logger.error(f"Anthropic connection failed — check internet / API status: {e}")
            raise
        except anthropic.APIStatusError as e:
            logger.error(f"Anthropic API error {e.status_code}: {e.message}")
            raise
