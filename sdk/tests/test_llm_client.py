"""
tests/test_llm_client.py — Tests for the LLM client.

Tests all configured models to verify:
  1. API connection works
  2. Model returns non-empty content
  3. Model can produce valid JSON output

Run with: python -m pytest tests/test_llm_client.py -v
Or for quick diagnostics: python tests/test_llm_client.py
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dossier_sdk.config import Config
from dossier_sdk.core.llm_client import LLMClient

config = Config()
llm    = LLMClient()

SIMPLE_SYSTEM = "You are a helpful assistant. Answer in plain text."
JSON_SYSTEM   = 'You are a JSON API. Return ONLY valid JSON. No markdown, no explanation.'
SIMPLE_USER   = "Say exactly: hello world"
JSON_USER     = 'Return this JSON exactly: {"status": "ok", "value": 42}'


# ─── Helper ───────────────────────────────────────────────────────────────────

def check_model(model: str, system: str, user: str, expect_json: bool = False) -> dict:
    """
    Call a model and return a result dict with pass/fail and diagnostics.
    Does NOT raise — returns failure info instead so we can report all models.
    """
    result = {"model": model, "passed": False, "response": None, "error": None}
    try:
        response = llm.call(system_prompt=system, user_prompt=user, model=model, max_tokens=128)
        result["response"] = repr(response[:200]) if response else repr(response)

        if not response:
            result["error"] = f"Empty or None response (got: {repr(response)})"
            return result

        if expect_json:
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            parsed = json.loads(cleaned)
            result["parsed_json"] = parsed

        result["passed"] = True
    except json.JSONDecodeError as e:
        result["error"] = f"JSON parse failed: {e} | raw={repr(response[:200])}"
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
    return result


# ─── Individual model tests (pytest discovers these) ──────────────────────────

def test_openai_nano_plain_text():
    """gpt-5-nano should return non-empty plain text."""
    r = check_model(config.model_nano, SIMPLE_SYSTEM, SIMPLE_USER)
    assert r["passed"], f"gpt-5-nano plain text FAILED: {r['error']}"
    print(f"\n  gpt-5-nano response: {r['response']}")


def test_openai_nano_json_output():
    """gpt-5-nano should return valid JSON when asked."""
    r = check_model(config.model_nano, JSON_SYSTEM, JSON_USER, expect_json=True)
    assert r["passed"], f"gpt-5-nano JSON FAILED: {r['error']}"
    print(f"\n  gpt-5-nano JSON: {r.get('parsed_json')}")


def test_openai_mid_plain_text():
    """gpt-5.4-mini should return non-empty plain text."""
    r = check_model(config.model_mid, SIMPLE_SYSTEM, SIMPLE_USER)
    assert r["passed"], f"gpt-5.4-mini plain text FAILED: {r['error']}"
    print(f"\n  gpt-5.4-mini response: {r['response']}")


def test_openai_mid_json_output():
    """gpt-5.4-mini should return valid JSON when asked."""
    r = check_model(config.model_mid, JSON_SYSTEM, JSON_USER, expect_json=True)
    assert r["passed"], f"gpt-5.4-mini JSON FAILED: {r['error']}"
    print(f"\n  gpt-5.4-mini JSON: {r.get('parsed_json')}")


def test_openai_quality_plain_text():
    """gpt-5 should return non-empty plain text."""
    r = check_model(config.model_quality, SIMPLE_SYSTEM, SIMPLE_USER)
    assert r["passed"], f"gpt-5 plain text FAILED: {r['error']}"
    print(f"\n  gpt-5 response: {r['response']}")


def test_openai_quality_json_output():
    """gpt-5 should return valid JSON when asked."""
    r = check_model(config.model_quality, JSON_SYSTEM, JSON_USER, expect_json=True)
    assert r["passed"], f"gpt-5 JSON FAILED: {r['error']}"
    print(f"\n  gpt-5 JSON: {r.get('parsed_json')}")


def test_anthropic_haiku_plain_text():
    """claude-haiku-4-5 should return non-empty plain text."""
    r = check_model(config.model_cover, SIMPLE_SYSTEM, SIMPLE_USER)
    assert r["passed"], f"claude-haiku plain text FAILED: {r['error']}"
    print(f"\n  claude-haiku response: {r['response']}")


def test_anthropic_haiku_json_output():
    """claude-haiku-4-5 should return valid JSON when asked."""
    r = check_model(config.model_cover, JSON_SYSTEM, JSON_USER, expect_json=True)
    assert r["passed"], f"claude-haiku JSON FAILED: {r['error']}"
    print(f"\n  claude-haiku JSON: {r.get('parsed_json')}")


def test_anthropic_sonnet_plain_text():
    """claude-sonnet-4-6 should return non-empty plain text."""
    r = check_model(config.model_resume, SIMPLE_SYSTEM, SIMPLE_USER)
    assert r["passed"], f"claude-sonnet plain text FAILED: {r['error']}"
    print(f"\n  claude-sonnet response: {r['response']}")


# ─── Standalone diagnostic runner ────────────────────────────────────────────

if __name__ == "__main__":
    """Run this directly for a quick diagnostic table: python tests/test_llm_client.py"""
    models_to_test = [
        ("nano",    config.model_nano,    "OpenAI"),
        ("mid",     config.model_mid,     "OpenAI"),
        ("quality", config.model_quality, "OpenAI"),
        ("cover",   config.model_cover,   "Anthropic"),
        ("resume",  config.model_resume,  "Anthropic"),
    ]

    print("\n" + "=" * 70)
    print("  LLM Model Diagnostic")
    print("=" * 70)
    print(f"  {'Tier':<10} {'Model':<35} {'Plain':<8} {'JSON':<8} Notes")
    print("  " + "-" * 68)

    for tier, model, provider in models_to_test:
        plain = check_model(model, SIMPLE_SYSTEM, SIMPLE_USER)
        jsn   = check_model(model, JSON_SYSTEM, JSON_USER, expect_json=True)

        plain_mark = "PASS" if plain["passed"] else "FAIL"
        json_mark  = "PASS" if jsn["passed"]   else "FAIL"

        error_note = ""
        if not plain["passed"]:
            error_note = plain["error"][:40]
        elif not jsn["passed"]:
            error_note = jsn["error"][:40]

        print(f"  {tier:<10} {model:<35} {plain_mark:<8} {json_mark:<8} {error_note}")

    print("=" * 70 + "\n")
