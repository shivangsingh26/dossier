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
"""

import base64
from pathlib import Path

import openai
import anthropic

from config import Config
from core.logger import get_logger

logger = get_logger(__name__)


class LLMClient:
    _instance = None  # Singleton — one set of clients shared across all agents

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_clients()
        return cls._instance

    def _init_clients(self) -> None:
        """Initialise both OpenAI and Anthropic clients from config."""
        config = Config()

        # OpenAI client — used for gpt-* and o* models
        self._openai = openai.OpenAI(api_key=config.openai_api_key)

        # Anthropic client — used for claude-* models only
        self._anthropic = anthropic.Anthropic(api_key=config.anthropic_api_key)

        logger.info("LLM clients initialised (OpenAI + Anthropic)")

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
            openai.APIError / anthropic.APIError: Propagated on API failure
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
        """Call the OpenAI chat completions API. Returns response text."""
        try:
            response = self._openai.chat.completions.create(
                model=model,
                max_completion_tokens=max_tokens,  # GPT-5 family uses max_completion_tokens, not max_tokens
                messages=[
                    # "developer" is the v2.x SDK recommended role for system-level instructions
                    {"role": "developer", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            return response.choices[0].message.content

        except openai.AuthenticationError as e:
            logger.error(f"OpenAI authentication failed — check OPENAI_API_KEY in .env: {e}")
            raise
        except openai.RateLimitError as e:
            logger.warning(f"OpenAI rate limit hit — slow down or upgrade plan: {e}")
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
        """Call the Anthropic Messages API. Returns response text."""
        try:
            response = self._anthropic.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt},
                ],
            )
            return response.content[0].text

        except anthropic.AuthenticationError as e:
            logger.error(f"Anthropic authentication failed — check ANTHROPIC_API_KEY in .env: {e}")
            raise
        except anthropic.RateLimitError as e:
            logger.warning(f"Anthropic rate limit hit — slow down or upgrade plan: {e}")
            raise
        except anthropic.APIConnectionError as e:
            logger.error(f"Anthropic connection failed — check internet / API status: {e}")
            raise
        except anthropic.APIStatusError as e:
            logger.error(f"Anthropic API error {e.status_code}: {e.message}")
            raise
