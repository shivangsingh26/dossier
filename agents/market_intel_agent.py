"""
agents/market_intel_agent.py — Discovers new AI/ML startups from Indian funding news.

Phase A: Synchronous plain functions. Volume is small (5–15 new companies per run)
so no parallelism is needed — sequential is simpler and fully debuggable.

PURPOSE: Monitors YourStory, Inc42, TechCrunch for Series A/B AI/ML startups in
         India that are not yet in our target_companies.json watchlist. For each:
         - Quick probe: does this company have public ML job openings?
         - YES → pipeline_stage="watchlist", auto-added to target_companies.json
         - NO  → pipeline_stage="cold_outreach", alert printed to console

         Reaching a company via cold outreach within 48h of a funding announcement
         beats every applicant who waits for a public job posting. This is what
         "reach earlier" means in the Dossier product positioning.

DATA SOURCES (Tavily only):
  Discovery phase — 3 searches, 3 credits, queries built from profile.json:
    Query 1: India AI/ML startup funding news (broad anchor)
    Query 2: Profile skill keywords (LLM, NLP, CV, RAG…) + India startup funding
    Query 3: Profile search terms (MLE, AI Engineer…) + India startup hiring

  Opening probe — 1 search per new company:
    "[company] machine learning data scientist jobs openings apply 2026"
    Heuristic check on result URLs (greenhouse.io, lever.co, linkedin.com/jobs)
    and snippet keywords ("we're hiring", "open positions", etc.).
    No extra LLM call — URL/keyword pattern is sufficient for a binary yes/no.

SCHEMA MIGRATION (first run only):
  Existing 70 companies in target_companies.json lack the 7 new fields added here.
  load_target_companies() detects missing fields, backfills defaults, and writes the
  file back. All subsequent runs skip this step (fields already present).

LLM: gpt-5.4-mini (model_mid). One call per run to extract companies from snippets.
     ~$0.001 per run.

PIPELINE:
  1. Build discovery queries from profile.json (profile-driven, not hardcoded)
  2. Load target_companies.json → backfill schema (one-time) → known company names
  3. Load data/market_intel_queue.json (or create empty queue)
  4. 3 Tavily discovery searches → aggregate raw funding news snippets
  5. LLM extracts: [{name, funding_stage, funding_amount, ml_relevance_reason, source_url}]
  6. Filter: skip companies already in target_companies.json or the queue
  7. For each new company: 1 Tavily probe → has_openings True/False
  8. Route:
       has_openings=True  → pipeline_stage="watchlist"  → target_companies.json + queue
       has_openings=False → pipeline_stage="cold_outreach" → queue only + console alert
  9. Print Rich summary table + cold outreach alerts

RUN VIA: python scripts/run_market_intel.py
"""

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from rich.console import Console
from rich.table import Table

from config import Config
from core.llm_client import LLMClient
from core.logger import get_logger

logger = get_logger(__name__)
console = Console()


# ─── Paths ────────────────────────────────────────────────────────────────────

_TARGET_COMPANIES_PATH = Path("profile/target_companies.json")
_QUEUE_PATH            = Path("data/market_intel_queue.json")


# ─── Tavily Settings ──────────────────────────────────────────────────────────

_TAVILY_TIMEOUT     = 10   # seconds per request
_TAVILY_MAX_RESULTS = 5    # results per search call (1 Tavily credit per call)
_SLEEP_BETWEEN      = 0.5  # seconds between calls — polite to the free tier

# URL patterns that confirm a result is a job listing page (ATS domains)
_OPENING_URL_PATTERNS = [
    "greenhouse.io",
    "lever.co",
    "jobs.lever.co",
    "linkedin.com/jobs",
    "ashbyhq.com",
    "breezy.hr",
    "workday.com",
]

# Snippet keywords that signal active hiring intent
_OPENING_SNIPPET_KEYWORDS = [
    "we're hiring",
    "we are hiring",
    "apply now",
    "apply here",
    "open positions",
    "job opening",
    "join our team",
    "open roles",
    "current openings",
    "now hiring",
]

# Maps verbose profile skill names to short Tavily-friendly search keywords.
# Profile skills like "LLM Pipeline Engineering" are too long for good search queries.
# Anything not in this map falls back to the first word of the skill name.
_SKILL_KEYWORD_MAP: dict[str, str] = {
    "llm pipeline engineering":      "LLM",
    "production ml engineering":     "MLOps",
    "computer vision":               "computer vision",
    "llm evaluation":                "LLM evaluation",
    "rag systems":                   "RAG",
    "nlp":                           "NLP",
    "natural language":              "NLP",
    "generative":                    "generative AI",
    "speech":                        "speech AI",
    "recommendation":                "recommendation systems",
    "reinforcement learning":        "reinforcement learning",
    "mlops":                         "MLOps",
    "deep learning":                 "deep learning",
}

# Skills excluded from query generation — too generic, add noise not signal
_GENERIC_SKILLS = {
    "python", "fastapi", "microservices", "distributed systems",
    "infrastructure", "sql", "git", "docker", "linux",
    "fastapi + microservices", "distributed systems & infrastructure",
}


# ─── Schema Migration ─────────────────────────────────────────────────────────
# 7 new fields added in this agent. Existing 70 companies don't have them yet.
# Defaults are applied once (lazy migration) on first run of this agent.

_SCHEMA_DEFAULTS: dict = {
    "pipeline_stage":      "watchlist",
    "funding_stage":       None,
    "funding_amount":      None,
    "discovered_via":      "manual",
    "discovered_at":       "2026-05-04",
    "has_public_openings": None,
    "ml_relevance_reason": None,
}


# ─── Profile-Driven Query Builder ─────────────────────────────────────────────

def _skill_to_keyword(skill_name: str) -> str:
    """
    Map a verbose profile skill name to a short search-friendly keyword.
    e.g. "LLM Pipeline Engineering" → "LLM", "RAG Systems" → "RAG".
    Falls back to the first word of the skill name if no map entry exists.
    """
    lower = skill_name.lower()
    for fragment, keyword in _SKILL_KEYWORD_MAP.items():
        if fragment in lower:
            return keyword
    # Fallback: first word is usually the most meaningful part of the skill name
    return skill_name.split()[0]


def build_discovery_queries(profile: dict) -> list[str]:
    """
    Generate 5 Tavily discovery queries tailored to the user's target skills and roles.
    Profile-driven so the agent adapts when profile.json changes.

    5 queries cover different angles:
      1. Broad India AI/ML funding anchor
      2. User's specific ML skill keywords (LLM, RAG, NLP — short tokens, not verbose phrases)
      3. Named sources in query text (YourStory, Inc42) — Tavily weights these results higher
      4. Indian city anchors (Bengaluru, Hyderabad) — forces geographic specificity
      5. Role-based signal (MLE, AI Engineer) — surfaces companies building those teams
    """
    # Convert verbose skill names → short keywords, drop generic ones
    all_skills = [s["skill"] for s in profile.get("skills", [])]
    ml_keywords = [
        _skill_to_keyword(s)
        for s in all_skills
        if s.lower() not in _GENERIC_SKILLS
    ]
    # Deduplicate while preserving order, take top 3
    seen: set[str] = set()
    unique_keywords: list[str] = []
    for kw in ml_keywords:
        if kw not in seen:
            seen.add(kw)
            unique_keywords.append(kw)
        if len(unique_keywords) == 3:
            break
    skill_snippet = " ".join(unique_keywords)  # e.g. "LLM MLOps computer vision"

    # Role terms — already short enough (e.g. "Machine Learning Engineer")
    role_terms = profile.get("target", {}).get("search_terms", [])
    role_snippet = " ".join(role_terms[:2])  # e.g. "Machine Learning Engineer AI Engineer"

    # Primary location for India-specificity
    cities = "Bengaluru Hyderabad Mumbai"

    return [
        # 1. Broad anchor — catches the main India startup funding news cycle
        "India AI ML startup raised Series A Series B 2026 funding announcement",
        # 2. Skill-specific — short keywords, not verbose phrases (fixed from v1)
        f"India {skill_snippet} startup funding investment 2026",
        # 3. Named sources — Tavily weights results from YourStory/Inc42 higher when named
        "YourStory Inc42 India AI startup funding raised 2026",
        # 4. City anchors — locks results to actual Indian companies, not "mentions India"
        f"{cities} AI ML generative startup raised funded 2026",
        # 5. Role signal — surfaces companies actively building the teams the user targets
        f"India {role_snippet} startup hiring raised investment 2026",
    ]


# ─── target_companies.json Helpers ───────────────────────────────────────────

def load_target_companies() -> dict:
    """
    Load target_companies.json and backfill any missing schema fields (one-time migration).
    Writes the file back only if at least one field was added — idempotent after first run.
    """
    with open(_TARGET_COMPANIES_PATH, encoding="utf-8") as f:
        data = json.load(f)

    changed = False
    for company in data.get("companies", []):
        for field, default in _SCHEMA_DEFAULTS.items():
            if field not in company:
                company[field] = default
                changed = True

    if changed:
        _write_target_companies(data)
        logger.info("target_companies.json: schema backfill complete (first-run migration)")

    return data


def _write_target_companies(data: dict) -> None:
    """Write target_companies.json back to disk with 2-space indent."""
    with open(_TARGET_COMPANIES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.debug("target_companies.json written")


def get_known_company_names(data: dict) -> set[str]:
    """Return a lowercase set of all company names in target_companies.json."""
    return {c["name"].lower() for c in data.get("companies", [])}


def add_to_target_companies(
    data: dict,
    company_info: dict,
    has_openings: bool,
    discovered_via: str,
) -> None:
    """
    Append a newly discovered company to the companies list.
    pipeline_stage is set from the opening probe result.
    linkedin_slug is a best-guess — watchlist_agent will verify or correct it.
    """
    stage = "watchlist" if has_openings else "cold_outreach"
    entry: dict = {
        "name":                company_info.get("name"),
        "tier":                "top_ai_startup",
        "linkedin_slug":       _make_slug(company_info.get("name", "")),
        "careers_url":         None,
        "scrape_method":       "linkedin",
        "why":                 company_info.get(
            "ml_relevance_reason", "Discovered by market intel agent"
        ),
        # New schema fields
        "pipeline_stage":      stage,
        "funding_stage":       company_info.get("funding_stage"),
        "funding_amount":      company_info.get("funding_amount"),
        "discovered_via":      discovered_via,
        "discovered_at":       datetime.now(timezone.utc).date().isoformat(),
        "has_public_openings": has_openings,
        "ml_relevance_reason": company_info.get("ml_relevance_reason"),
    }
    data["companies"].append(entry)


# ─── Queue Helpers ────────────────────────────────────────────────────────────

def load_queue() -> dict:
    """
    Load market_intel_queue.json, or create an empty queue if the file doesn't exist.
    The queue is an append-only audit trail of every company the agent has discovered.
    """
    if _QUEUE_PATH.exists():
        with open(_QUEUE_PATH, encoding="utf-8") as f:
            return json.load(f)

    return {
        "_note": (
            "Audit trail of companies discovered by market_intel_agent.py. "
            "pipeline_stage=watchlist  → also added to target_companies.json for scraping. "
            "pipeline_stage=cold_outreach → flagged for outreach before they post publicly. "
            "processed=true → referral_finder has already acted on this entry."
        ),
        "queue": [],
    }


def _write_queue(queue_data: dict) -> None:
    """Write market_intel_queue.json to disk. Creates data/ directory if needed."""
    _QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_QUEUE_PATH, "w", encoding="utf-8") as f:
        json.dump(queue_data, f, indent=2, ensure_ascii=False)


def _in_queue(name: str, queue_data: dict) -> bool:
    """Return True if a company with this name is already in the queue (case-insensitive)."""
    name_lower = name.lower()
    return any(e["name"].lower() == name_lower for e in queue_data.get("queue", []))


# ─── Tavily Fetch ─────────────────────────────────────────────────────────────

def fetch_tavily(query: str, api_key: str, topic: str = "news") -> list[dict]:
    """
    Single Tavily search. Costs 1 credit. Returns list of {title, url, content} dicts.
    Falls back to empty list on any failure — never crashes the pipeline.
    """
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key":             api_key,
                "query":               query,
                "search_depth":        "basic",
                "topic":               topic,
                "max_results":         _TAVILY_MAX_RESULTS,
                "include_answer":      False,
                "include_raw_content": False,
            },
            timeout=_TAVILY_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("results", [])
    except requests.exceptions.HTTPError as e:
        logger.warning(f"Tavily HTTP {e.response.status_code} | query: '{query[:60]}'")
    except requests.exceptions.RequestException as e:
        logger.warning(f"Tavily request failed: {e}")
    except Exception as e:
        logger.error(f"Tavily unexpected error: {e}")
    return []


# ─── LLM Extraction ───────────────────────────────────────────────────────────

def _build_system_prompt() -> str:
    """System prompt for extracting AI/ML company list from funding news snippets."""
    return """You are a startup analyst focused on the Indian AI/ML ecosystem.

Extract a list of AI/ML companies from the provided funding news snippets.

Return ONLY valid JSON — an array of objects. No explanation, no markdown, nothing outside the array.

Each object must have exactly these keys:
{
  "name": "Company name exactly as it appears in the article",
  "funding_stage": "Seed | Series A | Series B | Series C | Series D+ | IPO | unknown",
  "funding_amount": "e.g. '$25M' or 'INR 200 Cr' or 'unknown'",
  "ml_relevance_reason": "One sentence: what AI/ML problem they build or solve",
  "source_url": "The URL of the article where this company was found"
}

Rules:
- Include ONLY companies that BUILD AI/ML products or have a core ML-intensive product
  (search, recommendation, NLP, computer vision, LLM, speech AI, fraud detection, forecasting)
- Do NOT include companies that merely USE AI as a minor feature (generic SaaS + AI chat widget)
- GEOGRAPHY (strict): ONLY include companies that are (a) headquartered in India, OR
  (b) founded by Indians with primary engineering in India, OR (c) have a major India
  engineering hub (100+ engineers). "Mentions India" is NOT enough — reject it.
- REJECT any company that sounds like a US/European company with no India presence
- SOURCE TRUST: each snippet is labelled [TRUSTED: India startup news] or [UNKNOWN SOURCE].
  For [TRUSTED] sources: extract companies if they meet the criteria above.
  For [UNKNOWN SOURCE]: apply the strictest possible India geography filter — reject unless
  the snippet explicitly names India headquarters or Indian founders.
- If the same company appears in multiple snippets, include it ONCE (most informative source)
- Return [] if no qualifying companies are found
- Do NOT fabricate — extract only from the text provided"""


# Domains known to publish credible Indian startup funding news.
# Snippets from these sources get a [TRUSTED] label so the LLM can weight them higher.
_TRUSTED_INDIA_DOMAINS = {
    "yourstory.com", "inc42.com", "entrackr.com", "thetechportal.com",
    "techcrunch.com", "business-standard.com", "livemint.com",
    "economictimes.indiatimes.com", "financialexpress.com",
    "startupstorymedia.com", "vccircle.com", "dealstreetasia.com",
}


def _source_label(url: str) -> str:
    """Return [TRUSTED: India startup news] or [UNKNOWN SOURCE] for a result URL."""
    domain = url.lower().split("//")[-1].split("/")[0].lstrip("www.")
    if any(trusted in domain for trusted in _TRUSTED_INDIA_DOMAINS):
        return "[TRUSTED: India startup news]"
    return "[UNKNOWN SOURCE — apply strict India geography filter]"


def _build_user_prompt(all_results: list[dict]) -> str:
    """Format aggregated Tavily results into a single user prompt for LLM extraction."""
    if not all_results:
        return "No search results provided."

    snippets = [
        f"Source:  {_source_label(r.get('url', ''))}\n"
        f"Title:   {r.get('title', '')}\n"
        f"URL:     {r.get('url', '')}\n"
        f"Snippet: {r.get('content', '')[:400]}"
        for r in all_results
    ]
    body = "\n\n---\n\n".join(snippets)
    return (
        f"FUNDING NEWS SNIPPETS ({len(all_results)} results):\n\n"
        f"{body}\n\n"
        "Extract the list of qualifying AI/ML companies from the snippets above."
    )


def extract_companies(results: list[dict], llm: LLMClient) -> list[dict]:
    """
    Run gpt-5.4-mini over aggregated Tavily snippets and return a structured company list.
    One LLM call per agent run. Returns empty list on any failure.
    """
    config = Config()
    if not results:
        return []

    try:
        raw = llm.call(
            system_prompt=_build_system_prompt(),
            user_prompt=_build_user_prompt(results),
            model=config.model_mid,
            max_tokens=1024,
        )
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            # Strip markdown code fences if the model wrapped the JSON
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return parsed
        logger.warning(f"LLM returned {type(parsed).__name__}, expected list — skipping")
    except json.JSONDecodeError as e:
        logger.warning(f"Company extraction JSON parse failed: {e}")
    except Exception as e:
        logger.error(f"Company extraction error: {e}")

    return []


# ─── Opening Probe ────────────────────────────────────────────────────────────

def probe_for_openings(company_name: str, api_key: str) -> bool:
    """
    Check if a company has public ML/AI job openings using 1 Tavily search.
    Heuristic: ATS URL match (strong signal) or hiring-intent keyword in snippet (weaker).
    No LLM call — binary yes/no doesn't need one.
    """
    query = (
        f"{company_name} machine learning data scientist engineer "
        "jobs openings apply 2026"
    )
    results = fetch_tavily(query, api_key, topic="general")

    for r in results:
        url     = (r.get("url")     or "").lower()
        snippet = (r.get("content") or "").lower()

        if any(pat in url for pat in _OPENING_URL_PATTERNS):
            logger.debug(f"Probe '{company_name}': True  (ATS URL: {url[:80]})")
            return True

        if any(kw in snippet for kw in _OPENING_SNIPPET_KEYWORDS):
            logger.debug(f"Probe '{company_name}': True  (hiring keyword in snippet)")
            return True

    logger.debug(f"Probe '{company_name}': False (no signals found in {len(results)} results)")
    return False


# ─── Utility Helpers ──────────────────────────────────────────────────────────

def _make_slug(name: str) -> str:
    """
    Best-guess LinkedIn slug from a company name. e.g. "Sarvam AI" → "sarvam-ai".
    Not guaranteed correct — watchlist_agent will verify/correct it on first use.
    """
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)  # drop punctuation
    slug = re.sub(r"\s+",          "-", slug)  # spaces → hyphens
    slug = re.sub(r"-+",           "-", slug)  # collapse repeated hyphens
    return slug.strip("-")


def _classify_source(source_url: str) -> str:
    """Map a source URL to a short canonical label for the queue (yourstory, inc42, etc.)."""
    url = (source_url or "").lower()
    if "yourstory.com" in url:
        return "yourstory"
    if "inc42.com" in url:
        return "inc42"
    if "techcrunch.com" in url:
        return "techcrunch"
    if "crunchbase.com" in url:
        return "crunchbase"
    return "other"


def _load_profile() -> dict:
    """Load profile.json from the path configured in Config."""
    config = Config()
    with open(config.profile_path, encoding="utf-8") as f:
        return json.load(f)


# ─── Results Display ──────────────────────────────────────────────────────────

def _print_report(discovered: list[dict]) -> None:
    """Print a Rich summary table and cold outreach alert block."""
    if not discovered:
        console.print("\n  [yellow]No new AI/ML companies discovered this run.[/yellow]\n")
        return

    table = Table(title="Market Intel — New Companies Discovered", show_lines=True)
    table.add_column("Company",    width=22)
    table.add_column("Stage",      width=10)
    table.add_column("Funding",    width=18)
    table.add_column("ML Focus",   width=40)
    table.add_column("Openings?",  width=10)
    table.add_column("Action",     width=20)

    for c in discovered:
        has_open = c.get("has_public_openings", False)
        table.add_row(
            (c.get("name")                or "")[:22],
            (c.get("funding_stage")       or "unknown")[:10],
            (c.get("funding_amount")      or "unknown")[:18],
            (c.get("ml_relevance_reason") or "")[:40],
            "[green]Yes[/green]" if has_open else "[dim]No[/dim]",
            "[green]→ Watchlist[/green]" if has_open else "[yellow]→ Cold outreach[/yellow]",
        )

    console.print()
    console.print(table)

    cold = [c for c in discovered if not c.get("has_public_openings")]
    if not cold:
        return

    console.print("\n[bold yellow]  ⚡ Cold Outreach Targets — Act Now[/bold yellow]")
    console.print(
        "  These companies have NO public openings. Reaching out within 48h of\n"
        "  their funding announcement puts you ahead of every public applicant.\n"
    )
    for c in cold:
        console.print(
            f"  • [bold]{c['name']}[/bold]  "
            f"({c.get('funding_stage', '?')} · {c.get('funding_amount', '?')})\n"
            f"    {c.get('ml_relevance_reason', '')}\n"
            f"    Source: {c.get('source_url', '—')}\n"
        )


# ─── Main Entry Point ─────────────────────────────────────────────────────────

def run() -> list[dict]:
    """
    Run the full market intel pipeline. Returns list of newly discovered company dicts.

    Steps:
      1. Build discovery queries from profile.json (not hardcoded)
      2. Load + backfill target_companies.json schema (one-time lazy migration)
      3. Load or create market_intel_queue.json
      4. 3 Tavily discovery searches (3 credits)
      5. LLM extracts structured company list (1 LLM call)
      6. Filter: skip companies already known or in the queue
      7. Probe each new company for public openings (1 Tavily credit per company)
      8. Route: watchlist or cold_outreach — write both files
      9. Print summary + cold outreach alerts
    """
    config = Config()
    llm    = LLMClient()

    if not config.tavily_api_key:
        logger.error(
            "TAVILY_API_KEY not set — market intel requires Tavily. "
            "Sign up free at app.tavily.com and add TAVILY_API_KEY to .env."
        )
        return []

    console.print("\n[bold]═══ Market Intel Agent ═══[/bold]")

    # Step 1: profile-driven queries
    profile = _load_profile()
    queries = build_discovery_queries(profile)
    console.print(f"  Discovery queries built from profile.json ({len(queries)} searches · profile-driven)")

    # Step 2: load target companies + backfill schema
    console.print("  Loading target_companies.json...")
    target_data = load_target_companies()
    known_names = get_known_company_names(target_data)
    console.print(f"  {len(target_data['companies'])} companies currently tracked")

    # Step 3: load (or create) the discovery queue
    queue_data = load_queue()
    console.print(f"  {len(queue_data['queue'])} companies already in discovery queue")

    # Step 4: discovery searches (3 Tavily credits)
    console.print(f"\n  Running {len(queries)} Tavily discovery searches...")
    all_snippets: list[dict] = []
    for i, query in enumerate(queries, 1):
        console.print(f"  [{i}/{len(queries)}] {query[:72]}...")
        results = fetch_tavily(query, config.tavily_api_key, topic="news")
        all_snippets.extend(results)
        if i < len(queries):
            time.sleep(_SLEEP_BETWEEN)
    console.print(f"  {len(all_snippets)} raw snippets collected")

    if not all_snippets:
        console.print("  [yellow]No snippets returned — check TAVILY_API_KEY or try again later.[/yellow]")
        return []

    # Step 5: LLM extracts structured company list (1 LLM call for the whole batch)
    console.print("\n  Extracting companies with LLM (gpt-5.4-mini, 1 call)...")
    extracted: list[dict] = extract_companies(all_snippets, llm)
    console.print(f"  {len(extracted)} AI/ML companies extracted")

    if not extracted:
        console.print("  [dim]No qualifying companies found — try again tomorrow for fresh news.[/dim]")
        return []

    # Step 6: filter to genuinely new companies
    new_vs_file  = [c for c in extracted if c.get("name") and c["name"].lower() not in known_names]
    new_vs_queue = [c for c in new_vs_file  if not _in_queue(c["name"], queue_data)]

    if len(extracted) - len(new_vs_file):
        console.print(f"  [dim]{len(extracted) - len(new_vs_file)} already in watchlist — skipped[/dim]")
    if len(new_vs_file) - len(new_vs_queue):
        console.print(f"  [dim]{len(new_vs_file) - len(new_vs_queue)} already in discovery queue — skipped[/dim]")
    if not new_vs_queue:
        console.print("  [dim]No genuinely new companies this run.[/dim]")
        _print_report([])
        return []

    # Step 7: probe each new company for public openings
    probe_credits = len(new_vs_queue)
    console.print(
        f"\n  [green]{len(new_vs_queue)} new companies to probe[/green] "
        f"(Tavily credits: {len(queries)} discovery + {probe_credits} probes "
        f"= {len(queries) + probe_credits} total this run)"
    )

    discovered: list[dict] = []

    for idx, company_info in enumerate(new_vs_queue, 1):
        name = company_info.get("name", "Unknown")
        console.print(f"  [{idx}/{len(new_vs_queue)}] {name}...", end=" ")

        has_openings = probe_for_openings(name, config.tavily_api_key)
        source       = _classify_source(company_info.get("source_url", ""))

        company_info["has_public_openings"] = has_openings
        company_info["discovered_via"]      = source

        if has_openings:
            console.print("[green]has openings → watchlist[/green]")
        else:
            console.print("[yellow]no openings → cold outreach[/yellow]")

        # Add to target_companies.json (in memory — written once after loop)
        add_to_target_companies(target_data, company_info, has_openings, source)
        known_names.add(name.lower())  # prevent intra-run duplicates if LLM returned dupes

        # Build queue entry (same shape for both paths)
        queue_entry: dict = {
            "name":                name,
            "linkedin_slug":       _make_slug(name),
            "tier":                "top_ai_startup",
            "pipeline_stage":      "watchlist" if has_openings else "cold_outreach",
            "funding_stage":       company_info.get("funding_stage"),
            "funding_amount":      company_info.get("funding_amount"),
            "discovered_via":      source,
            "discovered_at":       datetime.now(timezone.utc).date().isoformat(),
            "has_public_openings": has_openings,
            "ml_relevance_reason": company_info.get("ml_relevance_reason"),
            "source_url":          company_info.get("source_url"),
            "processed":           False,
        }
        queue_data["queue"].append(queue_entry)
        discovered.append(queue_entry)

        if idx < len(new_vs_queue):
            time.sleep(_SLEEP_BETWEEN)

    # Step 8: persist both files
    _write_target_companies(target_data)
    _write_queue(queue_data)
    console.print(
        f"\n  [green]Saved {len(discovered)} companies[/green]"
        f" → target_companies.json + market_intel_queue.json"
    )

    # Step 9: display report + cold outreach alerts
    _print_report(discovered)

    return discovered
