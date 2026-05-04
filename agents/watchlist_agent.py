"""
agents/watchlist_agent.py — Fetches jobs from the target companies directly (currently 70).

Unlike job_discovery.py which searches by KEYWORD (and misses promoted listings),
this agent searches by COMPANY — fetching every ML/AI role our target companies
post, regardless of whether it surfaces in keyword results.

WHY THIS EXISTS:
  Companies like Google, AMD, Zepto, Sarvam post "sponsored" jobs on LinkedIn that
  only appear on their company page — not in keyword searches. The LinkedIn f_C=
  (company ID) filter fetches everything a company posts. Greenhouse/Lever companies
  get even cleaner data: a free structured JSON API with full descriptions.

THREE FETCH STRATEGIES (all free, no new API keys):
  1. Greenhouse API  — boards-api.greenhouse.io/v1/boards/{token}/jobs
                       Rippling, Stripe, Databricks, Airbnb, Coinbase
  2. Lever API       — api.lever.co/v0/postings/{handle}?mode=json
                       Browserstack
  3. LinkedIn f_C=   — existing guest scraper + company ID filter
                       All remaining 44 companies

PIPELINE: Same scoring logic as job_discovery.py (imported, not duplicated).
OUTPUT:   data/last_watchlist_run.json  +  terminal results table

Phase A: Synchronous plain functions, ThreadPoolExecutor for parallel scoring only.
"""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from rich.console import Console

from agents.job_discovery import (
    apply_company_diversity,
    build_candidate_summary,
    build_scoring_system_prompt,
    classify_company_tier,
    classify_job_function,
    compute_experience_band,
    compute_urgency,
    extract_degree_required,
    extract_years_required,
    generate_job_id,
    is_hard_no,
    is_seniority_mismatch,
    load_profile,
    print_results,
    score_job,
)
from config import Config
from core.db import get_seen_count, init_db, is_job_seen, mark_job_seen
from core.file_vault import save_jd, save_scorecard
from core.linkedin_scraper import scrape_linkedin_jobs
from core.llm_client import LLMClient
from core.logger import get_logger

logger = get_logger(__name__)
console = Console()


# ─── ML/AI Relevance Keywords ─────────────────────────────────────────────────
# Used to filter Greenhouse/Lever results which return ALL roles at a company.
# Intentionally broad — we'd rather score a borderline role than miss it.
# The LLM scorer handles final relevance judgement.

_ML_TITLE_KEYWORDS = [
    # Core ML/AI titles
    "machine learning", " ml ", "ai engineer", "artificial intelligence",
    "data scientist", "data science", "applied scientist",
    "nlp", "natural language", "computer vision",
    "llm", "large language", "generative", "gen ai",
    "deep learning", "reinforcement learning",
    "mlops", "ml platform", "research engineer", "research scientist",
    "recommendation", "ranking engineer", "speech recognition",
    "foundation model", "feature engineering",

    # Non-standard ML titles common at Indian product companies
    # (found from category_3 in exception_companies.json)
    "decision scientist",   # PhonePe, Flipkart — analytics/ML hybrid
    "analytics engineer",   # ML-adjacent pipeline/feature work
    "conversational ai",    # Uniphore, Haptik, Yellow.ai — voice/chat AI
    "speech engineer",      # Uniphore-style voice AI
    "speech scientist",     # Uniphore-style voice AI
    "language engineer",    # Sarvam AI — Indian language model work
    "operations research",  # Delhivery, logistics — quantitative optimisation
    "fraud",                # Fraud detection is always ML at our target companies
    "forecasting",          # Demand forecasting = time-series ML
    "personalization",      # Recommendation/personalisation engineering
    "visual search",        # Myntra, Lenskart — CV for fashion/eyewear
    "quantitative",         # Quant researcher/analyst at fintech targets
]

_INDIA_LOCATION_KEYWORDS = [
    "india", "bengaluru", "bangalore", "hyderabad", "mumbai",
    "delhi", "pune", "chennai", "remote", "anywhere", "worldwide",
    "global", "distributed",
]

# Path for persisting resolved LinkedIn company IDs across runs
_COMPANY_ID_CACHE_PATH = Path("data/linkedin_company_ids.json")


# ─── Location + Title Helpers ─────────────────────────────────────────────────

def is_india_relevant_location(location: str) -> bool:
    """Return True if location is India-relevant or unspecified (include by default)."""
    if not location or not location.strip():
        return True   # unspecified = assume it could be India, include
    loc_lower = location.lower()
    return any(kw in loc_lower for kw in _INDIA_LOCATION_KEYWORDS)


def is_ml_relevant_title(title: str) -> bool:
    """
    Return True if the job title indicates an ML/AI/Data Science role.
    Applied to Greenhouse/Lever results which include HR, Finance etc.
    Padded with spaces so 'ml' doesn't match 'html'.
    """
    padded = f" {title.lower()} "
    return any(kw in padded for kw in _ML_TITLE_KEYWORDS)


# ─── LinkedIn Company ID Resolution ──────────────────────────────────────────

def _load_id_cache() -> dict:
    """Load cached LinkedIn slug → numeric company ID mappings from disk."""
    if _COMPANY_ID_CACHE_PATH.exists():
        with open(_COMPANY_ID_CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_id_cache(cache: dict) -> None:
    """Persist LinkedIn company ID cache so future runs skip the resolution step."""
    _COMPANY_ID_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _COMPANY_ID_CACHE_PATH.write_text(
        json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8"
    )


_RESOLVE_PATTERNS = [
    r'organization[:/](\d{5,10})',          # most reliable across page versions (5+ for old companies like Zoho)
    r'"urn:li:fsd_company:(\d+)"',          # modern frontend
    r'"urn:li:company:(\d+)"',              # legacy format
    r'"companyId":(\d+)',                   # JS variable
    r'f_C=(\d+)',                           # "view all jobs" link param
    r'"entityUrn":"urn:li:company:(\d+)"',  # alternate quoted form
    r'"fs_normalized_company:(\d+)"',       # normalized entity format
    r'company/(\d+)/',                      # numeric ID in canonical URL
]

_RESOLVE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _try_extract_id(html: str) -> str | None:
    """Try all known patterns to extract a LinkedIn numeric company ID from HTML."""
    for pattern in _RESOLVE_PATTERNS:
        match = re.search(pattern, html)
        if match:
            return match.group(1)
    return None


def _resolve_id_from_page(slug: str) -> str | None:
    """
    Fetch LinkedIn company page(s) and extract the numeric company ID from HTML.
    Tries the main company page first, then /about/ as a fallback — different
    LinkedIn page versions embed the ID in different places.
    Returns None if extraction fails across all attempts.
    """
    urls_to_try = [
        f"https://www.linkedin.com/company/{slug}/",
        f"https://www.linkedin.com/company/{slug}/about/",
    ]
    for url in urls_to_try:
        try:
            resp = requests.get(url, headers=_RESOLVE_HEADERS, timeout=10)
            if resp.status_code == 200:
                company_id = _try_extract_id(resp.text)
                if company_id:
                    return company_id
            elif resp.status_code not in (404, 999):
                logger.debug(f"LinkedIn company page: {resp.status_code} for '{slug}' at {url}")
        except requests.RequestException as e:
            logger.debug(f"LinkedIn company page fetch failed for '{slug}': {e}")

    return None


def resolve_linkedin_company_id(slug: str, cache: dict) -> str | None:
    """
    Return the numeric LinkedIn company ID for a given slug.
    Checks in-memory cache first; resolves from the page if not cached.
    Updates the cache dict in-place — caller must call _save_id_cache() to persist.
    """
    if slug in cache:
        return cache[slug]

    logger.info(f"  Resolving LinkedIn ID for '{slug}'...")
    company_id = _resolve_id_from_page(slug)

    if company_id:
        logger.info(f"  Resolved: {slug} → {company_id}")
        cache[slug] = company_id
    else:
        logger.warning(f"  Could not resolve LinkedIn ID for '{slug}' — skipping this company")

    return company_id


# ─── Source Fetchers ──────────────────────────────────────────────────────────

def fetch_jobs_greenhouse(company_name: str, token: str) -> list[dict]:
    """
    Fetch all open ML/AI jobs from a Greenhouse ATS board.
    Greenhouse exposes a free public JSON API with full job descriptions.
    Returns jobs filtered for India-relevant locations and ML/AI titles.
    """
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            logger.warning(f"Greenhouse API: {resp.status_code} for {company_name} (token={token})")
            return []

        jobs = []
        for job in resp.json().get("jobs", []):
            title    = job.get("title", "")
            location = job.get("location", {}).get("name", "")

            if not is_ml_relevant_title(title):
                continue
            if not is_india_relevant_location(location):
                continue

            # Description is HTML from Greenhouse — strip to plain text
            raw_html    = job.get("content", "")
            description = (
                BeautifulSoup(raw_html, "html.parser").get_text("\n", strip=True)
                if raw_html else ""
            )

            jobs.append({
                "site":        "greenhouse",
                "title":       title,
                "company":     company_name,
                "location":    location,
                "job_url":     job.get("absolute_url", ""),
                "date_posted": job.get("updated_at"),
                "description": description,
            })

        logger.info(f"  Greenhouse [{company_name}]: {len(jobs)} ML/AI India jobs")
        return jobs

    except Exception as e:
        logger.error(f"Greenhouse fetch failed for {company_name}: {e}")
        return []


def fetch_jobs_lever(company_name: str, handle: str) -> list[dict]:
    """
    Fetch all open ML/AI jobs from a Lever ATS posting board.
    Lever exposes a free public JSON API — no auth required.
    Returns jobs filtered for India-relevant locations and ML/AI titles.
    """
    url = f"https://api.lever.co/v0/postings/{handle}?mode=json"
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            logger.warning(f"Lever API: {resp.status_code} for {company_name} (handle={handle})")
            return []

        jobs = []
        for posting in resp.json():
            title    = posting.get("text", "")
            location = posting.get("categories", {}).get("location", "")

            if not is_ml_relevant_title(title):
                continue
            if not is_india_relevant_location(location):
                continue

            # Prefer plain-text description; fall back to HTML-stripped
            description = posting.get("descriptionPlain", "")
            if not description:
                raw_html    = posting.get("description", "")
                description = (
                    BeautifulSoup(raw_html, "html.parser").get_text("\n", strip=True)
                    if raw_html else ""
                )

            # Lever timestamps are Unix milliseconds
            created_ms  = posting.get("createdAt", 0)
            date_posted = (
                datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc)
                if created_ms else None
            )

            jobs.append({
                "site":        "lever",
                "title":       title,
                "company":     company_name,
                "location":    location,
                "job_url":     posting.get("hostedUrl", ""),
                "date_posted": date_posted,
                "description": description,
            })

        logger.info(f"  Lever [{company_name}]: {len(jobs)} ML/AI India jobs")
        return jobs

    except Exception as e:
        logger.error(f"Lever fetch failed for {company_name}: {e}")
        return []


def fetch_jobs_linkedin_company(
    company_name: str,
    company_id: str,
    location: str,
) -> list[dict]:
    """
    Fetch LinkedIn jobs for a specific company using the f_C= company ID filter.
    Empty search_term means "all jobs at this company" — we filter by ML/AI title
    afterwards. This catches promoted/sponsored listings that keyword search misses.
    Rate: 25 results, 1 page, 0.5s between description fetches.
    """
    try:
        jobs = scrape_linkedin_jobs(
            search_term="",
            location=location,
            hours_old=720,          # 30 days — LinkedIn snaps to r2592000 anyway
            results_wanted=25,      # top 25 most recent per company
            experience_levels=[],   # no f_E filter — MAANG roles are "Mid-Senior" on LinkedIn
                                    # is_seniority_mismatch() in pre-filter handles this downstream
            fetch_descriptions=True,
            sleep_between_pages=0.5,
            company_id=company_id,
        )
        ml_jobs = [j for j in jobs if is_ml_relevant_title(j.get("title", ""))]
        logger.info(f"  LinkedIn [{company_name}]: {len(ml_jobs)} ML/AI jobs (of {len(jobs)} fetched)")
        return ml_jobs

    except Exception as e:
        logger.error(f"LinkedIn company fetch failed for {company_name}: {e}")
        return []


# ─── Company Data Loader ──────────────────────────────────────────────────────

def load_target_companies() -> list[dict]:
    """Load the 50-company watchlist from profile/target_companies.json."""
    path = Path("profile/target_companies.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("companies", [])


# ─── Main Entry Point ─────────────────────────────────────────────────────────

def run(min_score: int = 5, location: str = "India") -> list:
    """
    Run the watchlist job discovery pipeline.

    Fetches jobs from all target companies using the best available free
    source per company, then scores through the same pipeline as job_discovery.py.

    Args:
        min_score: Minimum LLM score to include in results (default 5)
        location:  Primary location for LinkedIn searches (default "India")

    Returns:
        List of scored job dicts sorted by score descending.
    """
    config = Config()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    init_db()

    # ── Step 1: Load profile ──────────────────────────────────────────────────
    console.print("\n[bold]Step 1/4[/bold] — Loading profile...")
    profile           = load_profile()
    current_months    = profile["identity"].get("total_experience_months", 0)
    switch_months     = profile["target"].get("switch_timeline_months", 12)
    exp_band          = compute_experience_band(current_months, switch_months)
    system_prompt     = build_scoring_system_prompt(exp_band)
    candidate_summary = build_candidate_summary(profile, exp_band)
    hard_nos          = profile["target"].get("hard_nos", [])

    console.print(f"  Candidate: {profile['identity']['name']} | Band: {exp_band['band']}")

    # ── Step 2: Fetch from all target companies ───────────────────────────────
    companies         = load_target_companies()
    n_companies       = len(companies)
    greenhouse_count  = sum(1 for c in companies if c.get("ats_type") == "greenhouse")
    console.print(f"\n[bold]Step 2/4[/bold] — Fetching from {n_companies} target companies...")
    console.print(f"  Greenhouse: {greenhouse_count} | LinkedIn f_C=: remaining")

    id_cache     = _load_id_cache()
    all_raw_jobs: list[dict] = []

    for company in companies:
        name      = company["name"]
        ats_type  = company.get("ats_type")
        ats_token = company.get("ats_token", "")
        slug      = company.get("linkedin_slug", "")

        if ats_type == "greenhouse" and ats_token:
            jobs = fetch_jobs_greenhouse(name, ats_token)

        elif ats_type == "lever" and ats_token:
            jobs = fetch_jobs_lever(name, ats_token)

        else:
            # LinkedIn company-ID search for all other companies
            # Resolves the numeric ID from slug (cached after first run)
            if not slug:
                logger.warning(f"  No LinkedIn slug for {name} — skipping")
                continue

            company_id = resolve_linkedin_company_id(slug, id_cache)
            if not company_id:
                continue

            jobs = fetch_jobs_linkedin_company(name, company_id, location)
            # Polite delay between LinkedIn company searches to avoid rate limiting
            time.sleep(1.0)

        all_raw_jobs.extend(jobs)

    # Persist any newly resolved company IDs
    _save_id_cache(id_cache)

    console.print(f"  Raw jobs fetched: [bold]{len(all_raw_jobs)}[/bold]")

    # ── Dedup by URL ──────────────────────────────────────────────────────────
    seen_urls: set = set()
    deduped: list[dict] = []
    for job in all_raw_jobs:
        url = job.get("job_url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            deduped.append(job)

    console.print(f"  After URL dedup: [bold]{len(deduped)}[/bold] unique jobs")

    # ── Step 3: Pre-filter and score ──────────────────────────────────────────
    console.print(f"\n[bold]Step 3/4[/bold] — Scoring (min {min_score}/10)...")

    jobs_for_llm: list[dict] = []
    rejected_jobs: list[dict] = []
    skipped = 0

    for job in deduped:
        company     = job["company"]
        title       = job["title"]
        description = job.get("description", "")
        url         = job.get("job_url", "")
        site        = job.get("site", "")

        # Same pre-filters as job_discovery.py — ensures consistent behaviour
        if is_hard_no(company, hard_nos):
            skipped += 1
            continue

        if len(description) < 100:
            skipped += 1
            continue

        if is_job_seen(url):
            skipped += 1
            continue

        if is_seniority_mismatch(title, exp_band):
            skipped += 1
            rejected_jobs.append({
                "company": company, "title": title, "site": site, "url": url,
                "score": 3, "reason": "Seniority hard cap (watchlist pre-filter)",
                "description_preview": description[:300],
            })
            continue

        job_function = classify_job_function(title)
        if job_function == "support_ops":
            skipped += 1
            rejected_jobs.append({
                "company": company, "title": title, "site": site, "url": url,
                "score": 3, "reason": "Support/ops role (watchlist pre-filter)",
                "description_preview": description[:300],
            })
            continue

        years_required = extract_years_required(description)
        if years_required is not None and years_required > exp_band["max_years_required"]:
            skipped += 1
            rejected_jobs.append({
                "company": company, "title": title, "site": site, "url": url,
                "score": 3, "reason": f"Experience too high: {years_required}+ yrs required (band: {exp_band['band']})",
                "description_preview": description[:300],
            })
            continue

        degree_required = extract_degree_required(description)
        if degree_required == "phd":
            skipped += 1
            rejected_jobs.append({
                "company": company, "title": title, "site": site, "url": url,
                "score": 3, "reason": "PhD required — candidate has bachelor's degree (watchlist pre-filter)",
                "description_preview": description[:300],
            })
            continue

        # All watchlist companies are known — tier will always be resolved correctly
        company_tier = classify_company_tier(company)

        jobs_for_llm.append({
            **job,
            "job_function": job_function,
            "company_tier": company_tier,
            "years_required": years_required,
            "degree_required": degree_required,
        })

    console.print(f"  Pre-filtered {skipped} | Sending [bold]{len(jobs_for_llm)}[/bold] to LLM (8 workers)...")

    # WHY THREADPOOLEXECUTOR: same reason as job_discovery — each LLM call waits
    # 1-2s for network. 8 parallel workers give near-linear speedup at no code cost.
    scored_jobs: list[dict] = []
    llm_instance = LLMClient()
    total = len(jobs_for_llm)

    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_job = {
            executor.submit(
                score_job,
                j["company"], j["title"], j.get("description", ""),
                candidate_summary, system_prompt,
                j["job_function"], llm_instance, j["company_tier"],
                j.get("years_required"), j.get("degree_required", "none"),
            ): j
            for j in jobs_for_llm
        }

        completed = 0
        for future in as_completed(future_to_job):
            job_data  = future_to_job[future]
            completed += 1
            console.print(f"  Scored {completed}/{total}...", end="\r")

            result = future.result()

            job_url = job_data.get("job_url", "")
            if result["score"] < min_score:
                low_job_id = generate_job_id(job_data["company"], job_data["title"], result.get("relevancy", "low"))
                mark_job_seen(
                    job_url, low_job_id, result["score"],
                    result.get("relevancy", "low"), job_data["company"], job_data["title"], job_data.get("site", ""),
                )
                rejected_jobs.append({
                    "company":              job_data["company"],
                    "title":               job_data["title"],
                    "site":                job_data.get("site", ""),
                    "url":                 job_url,
                    "score":               result["score"],
                    "reason":              result.get("reason", ""),
                    "description_preview": job_data.get("description", "")[:300],
                })
                continue

            relevancy = result.get("relevancy", "low")
            urgency   = compute_urgency(job_data.get("date_posted"))
            job_id    = generate_job_id(job_data["company"], job_data["title"], relevancy)

            full_record = {
                **result,
                "job_id":          job_id,
                "company":         job_data["company"],
                "title":           job_data["title"],
                "site":            job_data.get("site", ""),
                "url":             job_url,
                "urgency":         urgency,
                "found_at":        datetime.now(timezone.utc).isoformat(),
                "experience_band": exp_band["band"],
                "source":          "watchlist",
            }
            save_jd(job_id, job_data.get("description", ""))
            save_scorecard(job_id, full_record)
            mark_job_seen(
                job_url, job_id, result["score"], relevancy,
                job_data["company"], job_data["title"], job_data.get("site", ""),
            )
            scored_jobs.append(full_record)

    # ── Step 4: Sort and display ──────────────────────────────────────────────
    console.print(" " * 80, end="\r")
    console.print(f"\n[bold]Step 4/4[/bold] — Results")
    console.print(f"  Pre-filtered: {skipped} | Below score {min_score}: {len(rejected_jobs)} | DB total: {get_seen_count()}")

    scored_jobs.sort(key=lambda j: j.get("score", 0), reverse=True)
    diverse_jobs = apply_company_diversity(scored_jobs, max_per_company=3)
    dropped = len(scored_jobs) - len(diverse_jobs)
    if dropped:
        console.print(f"  Diversity cap: {dropped} duplicate-company jobs removed (max 3 per company)")

    print_results(diverse_jobs)

    summary_path = config.data_dir / "last_watchlist_run.json"
    summary_path.write_text(
        json.dumps(scored_jobs, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    console.print(f"  Watchlist results → {summary_path}\n")

    return scored_jobs
