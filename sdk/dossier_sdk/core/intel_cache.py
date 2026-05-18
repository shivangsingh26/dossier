"""
core/intel_cache.py — Company-level intel cache with TTL.

WHY THIS EXISTS:
  The company intel agent calls Tavily twice per company (2 credits each run).
  Without a cache, running the pipeline daily re-fetches Stripe, Databricks etc.
  every single time even though company facts don't change day-to-day.

  This module stores intel per company slug with a configurable TTL.
  A company's intel is re-fetched only when the cache is expired or missing.

  Expected impact: ~70% reduction in Tavily credits on daily runs after week 1,
  since most companies in your results will repeat across runs.

CACHE LOCATION: data/intel_cache/{slug}.json
TTL DEFAULT:    7 days (company funding/size rarely changes faster than this)
KEY:            company name → normalised slug → filename
"""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

_CACHE_DIR = Path("data/intel_cache")
_DEFAULT_TTL_DAYS = 7


def _to_slug(company: str) -> str:
    """Normalise company name to a safe filename slug.

    Examples:
        'Auric AI Labs'  → 'auric_ai_labs'
        'Amazon.com'     → 'amazon_com'
        'Stripe, Inc.'   → 'stripe_inc'
    """
    slug = company.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_")


def get_cached_intel(company: str, ttl_days: int = _DEFAULT_TTL_DAYS) -> dict | None:
    """Return cached intel for a company if it exists and is within TTL.

    Returns None when:
      - Cache file does not exist (first time seeing this company)
      - Cache is older than ttl_days (stale, should re-fetch)
      - Cache file is corrupted (treat as miss, re-fetch cleanly)

    Args:
        company:  Company name as it appears in the job data.
        ttl_days: How many days old the cache can be before it's considered stale.

    Returns:
        Intel dict (same shape as the JSON returned by synthesize_intel) or None.
    """
    path = _CACHE_DIR / f"{_to_slug(company)}.json"
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cached_at_str = data.get("cached_at")
        if not cached_at_str:
            return None

        cached_at = datetime.fromisoformat(cached_at_str)
        age = datetime.now(timezone.utc) - cached_at
        if age < timedelta(days=ttl_days):
            return data.get("intel")

        return None  # expired — caller should re-fetch
    except Exception:
        return None  # corrupted file → treat as miss, re-fetch cleanly


def save_intel_cache(company: str, intel: dict) -> None:
    """Persist fresh intel for a company so future runs skip the Tavily call.

    Called immediately after a successful Tavily fetch + LLM synthesis.
    Overwrites any existing entry for the same company.

    Args:
        company: Company name (used to derive the cache key/filename).
        intel:   The structured intel dict from synthesize_intel().
    """
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _CACHE_DIR / f"{_to_slug(company)}.json"
    record = {
        "company":   company,
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "intel":     intel,
    }
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")


def is_intel_fresh(company: str, ttl_days: int = _DEFAULT_TTL_DAYS) -> bool:
    """Quick boolean check: does unexpired cached intel exist for this company?

    Use this in log messages / summaries so you can report cache hit rate
    without loading the full intel dict.
    """
    return get_cached_intel(company, ttl_days) is not None
