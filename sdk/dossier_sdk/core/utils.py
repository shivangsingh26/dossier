"""
core/utils.py — Shared utility helpers for the Dossier project.

Small functions that multiple agents need but don't belong in any single core module.
Import from here rather than duplicating logic in each agent.
"""

import json
import re

from dossier_sdk.core.logger import get_logger

logger = get_logger(__name__)


def parse_json_response(raw: str, context: str = "") -> dict | list | None:
    """
    Safely parse a JSON string returned by an LLM call.

    Handles the most common LLM formatting failure modes:
      1. Response wrapped in ```json ... ``` or ``` ... ``` markdown fences
         — LLMs add these despite instructions saying not to
      2. Empty or whitespace-only response (e.g. gpt-5-nano was observed doing this)
      3. Trailing commas or other minor JSON syntax errors — logged, not swallowed

    Args:
        raw:     The raw string from llm_client.call()
        context: Caller label for error logs, e.g. "job scoring" or "skill extraction".
                 Makes it instant to find which agent produced bad JSON in the log file.

    Returns:
        Parsed dict or list on success. None on any failure.
        Callers must check for None before using the result.

    Usage:
        result = parse_json_response(llm.call(system, user, model), context="gap analysis")
        if result is None:
            logger.warning(f"Skipping job {job_id} — LLM returned unparseable JSON")
            return None
    """
    if not raw or not raw.strip():
        label = f"[{context}] " if context else ""
        logger.warning(f"Empty LLM response {label}— returning None")
        return None

    text = raw.strip()

    # Strip ```json ... ``` or ``` ... ``` code fences — LLMs add these despite instructions
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        label = f"[{context}] " if context else ""
        logger.error(
            f"JSON parse failed {label}— {e} | "
            f"raw preview (first 300 chars): {raw[:300]!r}"
        )
        return None
