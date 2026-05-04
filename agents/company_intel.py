"""
agents/company_intel.py — Gathers structured company intelligence for high-scoring jobs.

Phase A: Synchronous, plain functions. Volume is small (10-20 companies per run)
so no parallelism is needed — sequential is simpler and fully debuggable.

PURPOSE: The scoring agent tells you if you fit the job.
         This agent tells you if the job is worth applying to.

DATA SOURCES (all free at typical usage):
  1. Tavily API   — web search purpose-built for AI agents.
                    2 searches per company: funding/overview + recent news.
                    Works for early-stage startups via TechCrunch, YourStory, Inc42,
                    AngelList articles — where Wikipedia has nothing.
                    Free tier: 1,000 credits/month. We use 2 per company (~500/month).
                    Requires TAVILY_API_KEY in .env (free sign-up at app.tavily.com).
  2. Wikipedia    — free JSON API, no key. Provides first 3 sentences for large/known
                    companies. Fails silently for startups — Tavily covers those.

LLM: gpt-5.4-mini (model_mid). Structured extraction from scraped text. ~$0.001/company.

PIPELINE:
  1. Caller passes scored jobs (pre-filtered to min_score)
  2. Group by company — fetch intel once even if multiple jobs from same company
  3. For each company: 2 Tavily searches + Wikipedia fallback
  4. LLM synthesises raw snippets into structured JSON fields
  5. Save data/artifacts/{job_id}/intel.json for every qualifying job

RUN VIA: python scripts/run_company_intel.py [--min-score 7] [--source both]
"""

import json
import time
from datetime import datetime, timezone

import requests
from rich.console import Console
from rich.table import Table

from config import Config
from core.llm_client import LLMClient
from core.logger import get_logger

logger = get_logger(__name__)
console = Console()

_TAVILY_MAX_RESULTS = 4      # results per search call (1 Tavily credit each)
_TAVILY_TIMEOUT     = 10     # seconds per HTTP request
_SLEEP_BETWEEN      = 0.5    # seconds between companies — polite to free tier


# ─── LLM Prompts ─────────────────────────────────────────────────────────────

def build_intel_system_prompt() -> str:
    """System prompt for structured company intel extraction."""
    return """You are a company research analyst. Extract structured intelligence from web search results.

Return ONLY valid JSON — no explanation, no markdown, nothing outside the JSON object.

MISSING DATA: Use null for any field you cannot find. Do NOT fabricate or guess.

Output schema (return exactly this):
{
  "funding_stage": "Seed | Series A | Series B | Series C | Series D+ | IPO | Public | Bootstrapped | unknown",
  "funding_amount": "e.g. '$50M Series B' or '$1.2B total raised' or 'unknown'",
  "founded_year": integer or null,
  "headcount_estimate": "e.g. '100-500' or '5000+' or 'unknown'",
  "business_focus": "one sentence: what the company does and their core product",
  "ml_relevance": "one sentence: how ML/AI-intensive this company is and what ML problems they solve",
  "risk_flags": ["red flags only: layoffs, financial trouble, pivoting away from tech, regulatory issues — empty list if none found"],
  "data_quality": "good | partial | not_found"
}

data_quality: 'good' = funding_stage AND business_focus both populated. 'partial' = only some fields found. 'not_found' = no useful company data in results."""


def build_intel_user_prompt(
    company: str,
    overview_results: list[dict],
    news_results: list[dict],
) -> str:
    """Format Tavily + Wikipedia results into the LLM user prompt."""

    def fmt(results: list[dict], label: str) -> str:
        if not results:
            return f"[{label}]\nNo results returned."
        body = "\n\n".join(
            f"Title: {r.get('title', '')}\n"
            f"URL: {r.get('url', '')}\n"
            f"Snippet: {r.get('content', '')[:350]}"
            for r in results
        )
        return f"[{label}]\n{body}"

    return (
        f"COMPANY: {company}\n\n"
        f"{fmt(overview_results, 'COMPANY OVERVIEW & FUNDING')}\n\n"
        f"{fmt(news_results, 'RECENT NEWS')}\n\n"
        f"Extract structured company intelligence from the results above."
    )


# ─── Data Fetching ────────────────────────────────────────────────────────────

def fetch_tavily(query: str, api_key: str, topic: str = "general") -> list[dict]:
    """
    Single Tavily search. Uses 1 credit (basic depth).
    Returns list of {title, url, content} dicts. Empty list on any failure.
    """
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "search_depth": "basic",
                "topic": topic,
                "max_results": _TAVILY_MAX_RESULTS,
                "include_answer": False,
                "include_raw_content": False,
            },
            timeout=_TAVILY_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("results", [])
    except requests.exceptions.HTTPError as e:
        logger.warning(f"Tavily HTTP {e.response.status_code} for '{query}'")
    except requests.exceptions.RequestException as e:
        logger.warning(f"Tavily request failed for '{query}': {e}")
    except Exception as e:
        logger.error(f"Tavily unexpected error for '{query}': {e}")
    return []


def fetch_wikipedia_summary(company: str) -> str | None:
    """
    Fetch first 3 sentences from Wikipedia. Free, no key needed.
    Returns None for startups not on Wikipedia — expected and handled gracefully.
    """
    try:
        resp = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "titles": company,
                "prop": "extracts",
                "exintro": True,
                "explaintext": True,
                "exsentences": 3,
                "format": "json",
                "redirects": 1,
            },
            timeout=5,
        )
        resp.raise_for_status()
        pages = resp.json().get("query", {}).get("pages", {})
        for page_id, page in pages.items():
            if page_id != "-1":
                extract = page.get("extract", "").strip()
                return extract or None
        return None
    except Exception as e:
        logger.debug(f"Wikipedia lookup failed for '{company}': {e}")
        return None


def gather_raw_intel(company: str, config: Config) -> dict:
    """
    Fetch raw data for one company: 2 Tavily searches + Wikipedia.
    Returns dict with overview_results and news_results.
    Cost: 2 Tavily credits + Wikipedia (free).
    """
    tavily_key = config.tavily_api_key
    overview_results: list[dict] = []
    news_results: list[dict] = []

    if tavily_key:
        overview_results = fetch_tavily(
            query=f"{company} company funding investors valuation overview",
            api_key=tavily_key,
            topic="general",
        )
        news_results = fetch_tavily(
            query=f"{company} news 2025 2026",
            api_key=tavily_key,
            topic="news",
        )
    else:
        logger.warning(f"TAVILY_API_KEY not set — no web data for '{company}'")

    # Wikipedia prepended so LLM sees it first (reliable for established companies)
    wiki = fetch_wikipedia_summary(company)
    if wiki:
        overview_results = [{
            "title":   f"{company} — Wikipedia",
            "url":     f"https://en.wikipedia.org/wiki/{company.replace(' ', '_')}",
            "content": wiki,
        }] + overview_results

    return {"overview_results": overview_results, "news_results": news_results}


# ─── LLM Synthesis ────────────────────────────────────────────────────────────

_EMPTY_INTEL = {
    "funding_stage": None, "funding_amount": None, "founded_year": None,
    "headcount_estimate": None, "business_focus": None,
    "ml_relevance": None, "risk_flags": [], "data_quality": "not_found",
}

_FAILED_INTEL = {
    "funding_stage": "unknown", "funding_amount": "unknown", "founded_year": None,
    "headcount_estimate": "unknown", "business_focus": "LLM synthesis failed",
    "ml_relevance": "LLM synthesis failed", "risk_flags": [], "data_quality": "partial",
}


def synthesize_intel(company: str, raw: dict, llm: LLMClient) -> dict:
    """
    Use gpt-5.4-mini to extract structured intel from raw search results.
    Returns a clean intel dict. Falls back to _FAILED_INTEL on error.
    """
    config = Config()
    overview = raw.get("overview_results", [])
    news     = raw.get("news_results", [])

    if not overview and not news:
        return dict(_EMPTY_INTEL)

    try:
        raw_text = llm.call(
            system_prompt=build_intel_system_prompt(),
            user_prompt=build_intel_user_prompt(company, overview, news),
            model=config.model_mid,
            max_tokens=512,
        )
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.warning(f"Intel JSON parse failed for '{company}': {e}")
    except Exception as e:
        logger.error(f"Intel synthesis error for '{company}': {e}")

    return dict(_FAILED_INTEL)


# ─── Artifact Storage ─────────────────────────────────────────────────────────

def save_intel_to_vault(job_id: str, company: str, intel: dict, news_items: list[dict]) -> None:
    """Write intel.json to data/artifacts/{job_id}/."""
    config = Config()
    job_dir = config.artifacts_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    record = {
        "company":             company,
        "intel_generated_at":  datetime.now(timezone.utc).isoformat(),
        **intel,
        "recent_news": [
            {
                "title":   r.get("title", ""),
                "url":     r.get("url", ""),
                "snippet": r.get("content", "")[:200],
            }
            for r in news_items[:3]
        ],
        "sources_used": ["tavily", "wikipedia"] if intel.get("data_quality") != "not_found" else [],
    }

    (job_dir / "intel.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.debug(f"Intel saved → {job_dir / 'intel.json'}")


# ─── Results Display ──────────────────────────────────────────────────────────

_QUALITY_STYLE = {"good": "green", "partial": "yellow", "not_found": "red"}


def print_intel_summary(results: list[dict]) -> None:
    """Print a compact intel summary table to the terminal."""
    if not results:
        return

    table = Table(title="Company Intel Summary", show_lines=True)
    table.add_column("Company",  width=20)
    table.add_column("Stage",    width=12)
    table.add_column("Funding",  width=22)
    table.add_column("Size",     width=10)
    table.add_column("ML Focus", width=38)
    table.add_column("Quality",  width=8)
    table.add_column("Flags",    width=20)

    for r in results:
        intel   = r["intel"]
        quality = intel.get("data_quality", "?")
        flags   = ", ".join(intel.get("risk_flags") or []) or "—"
        table.add_row(
            r["company"][:20],
            (intel.get("funding_stage") or "unknown")[:12],
            (intel.get("funding_amount") or "unknown")[:22],
            (intel.get("headcount_estimate") or "?")[:10],
            (intel.get("ml_relevance") or "")[:38],
            f"[{_QUALITY_STYLE.get(quality, '')}]{quality}[/]",
            flags[:20],
        )

    console.print()
    console.print(table)


# ─── Main Entry Point ─────────────────────────────────────────────────────────

def run(jobs: list[dict], min_score: int = 7) -> list[dict]:
    """
    Run company intel for all jobs with score >= min_score.
    Groups by company — 2 Tavily credits per unique company, not per job.

    Args:
        jobs:      Scored job dicts from last_discovery_run.json / last_watchlist_run.json.
        min_score: Research only companies where at least one job hit this score.

    Returns:
        List of {company, jobs, intel} dicts — one per unique researched company.
    """
    config = Config()
    config.artifacts_dir.mkdir(parents=True, exist_ok=True)
    llm = LLMClient()

    high_score = [j for j in jobs if j.get("score", 0) >= min_score]
    if not high_score:
        console.print(f"[yellow]  No jobs found with score ≥ {min_score}[/yellow]")
        return []

    # One Tavily fetch per unique company regardless of how many jobs it has
    company_to_jobs: dict[str, list[dict]] = {}
    for job in high_score:
        company_to_jobs.setdefault(job.get("company", "Unknown"), []).append(job)

    n = len(company_to_jobs)
    console.print(f"  {len(high_score)} jobs (score ≥ {min_score}) across {n} companies")
    console.print(f"  Tavily credits this run: ~{n * 2} of 1,000 free/month\n")

    results: list[dict] = []

    for idx, (company, jobs_list) in enumerate(company_to_jobs.items(), 1):
        console.print(f"  [{idx}/{n}] {company}...", end=" ")

        raw   = gather_raw_intel(company, config)
        intel = synthesize_intel(company, raw, llm)

        quality = intel.get("data_quality", "?")
        stage   = intel.get("funding_stage") or "unknown"
        console.print(f"[{_QUALITY_STYLE.get(quality, '')}]{quality}[/] | {stage}")

        for job in jobs_list:
            save_intel_to_vault(job["job_id"], company, intel, raw.get("news_results", []))

        results.append({"company": company, "jobs": jobs_list, "intel": intel})

        if idx < n:
            time.sleep(_SLEEP_BETWEEN)

    return results
