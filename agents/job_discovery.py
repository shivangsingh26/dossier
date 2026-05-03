"""
agents/job_discovery.py — Finds, scores, and ranks jobs based on your profile.

Phase A: Synchronous, plain functions. File vault used for deduplication.

PIPELINE:
1. Load profile.json — target roles, skills, salary, experience, switch timeline
2. Compute experience band at switch time — used to match correct seniority level
3. Call JobSpy across LinkedIn + Indeed + Naukri + Google Jobs
4. Filter out hard_no companies (no LLM needed — rule-based)
5. Score each job vs profile using gpt-5-nano
6. Compute urgency from date_posted (Python, not LLM — deterministic)
7. Save raw JD + scorecard to data/artifacts/{job_id}/
8. Print ranked results table using rich

RUN VIA: python scripts/run_job_discovery.py
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from jobspy import scrape_jobs
from rich.console import Console
from rich.table import Table

from config import Config
from core.file_vault import job_vault_exists, save_jd, save_scorecard
from core.linkedin_scraper import scrape_linkedin_jobs
from core.llm_client import LLMClient
from core.logger import get_logger

logger = get_logger(__name__)
console = Console()


# ─── Experience Band Logic ────────────────────────────────────────────────────

def compute_experience_band(current_months: int, switch_timeline_months: int) -> dict:
    """
    Compute the candidate's experience level at the time they plan to switch.
    Returns a dict with band label, seniority target, and scoring guidance.

    This is profile-driven — works for any user based on their numbers.

    Examples:
        11 months now + 8 months timeline = 19 months at switch → "0-2 years" band
        36 months now + 12 months timeline = 48 months at switch → "2-5 years" band
    """
    months_at_switch = current_months + switch_timeline_months

    # First band extends to 36 months (3 years) — anything under 3 years is still
    # entry-to-junior level in practice. 24-month cutoff was too aggressive.
    if months_at_switch <= 36:
        return {
            "band": "0-3 years",
            "months_at_switch": months_at_switch,
            "target_seniority": "Entry to junior level",
            "ideal_titles": ["MLE-1", "AI Engineer", "Data Scientist", "Applied Scientist",
                             "Machine Learning Engineer", "Associate ML Engineer",
                             "DS-1", "DS-2", "MLE-2", "AI Engineer-1", "AI Engineer-2"],
            "penalise_titles": ["Senior", "Sr", "Staff", "Principal", "Lead", "Manager",
                                "Director", "Head", "VP", "Intern", "Internship", "Trainee",
                                "Fresher", "Apprentice", "Apprenticeship"],
            "max_years_required": 3,
            "scoring_note": (
                "Candidate will have ~{m} months ({y:.1f} years) of experience at switch time. "
                "Target entry-to-junior roles (0-3 years). "
                "HARD RULE: Cap score at 4 for ANY role with Senior/Sr./Staff/Principal/Lead/Manager in title, "
                "even at MAANG. These are too senior. "
                "Roles without a seniority prefix (Applied Scientist, ML Engineer, Data Scientist) are fine."
            ).format(m=months_at_switch, y=months_at_switch / 12),
        }
    elif months_at_switch <= 60:
        return {
            "band": "2-5 years",
            "months_at_switch": months_at_switch,
            "target_seniority": "Mid level",
            "ideal_titles": ["MLE-2", "AI Engineer", "Senior Data Scientist", "ML Engineer",
                             "Applied Scientist"],
            "penalise_titles": ["Staff", "Principal", "Director", "Manager", "Intern", "Junior"],
            "max_years_required": 5,
            "scoring_note": (
                "Candidate will have ~{m} months of experience at switch time. "
                "Target mid-level roles (2-5 years). "
                "Penalise roles requiring 6+ years or staff/principal titles."
            ).format(m=months_at_switch),
        }
    elif months_at_switch <= 96:
        return {
            "band": "5-8 years",
            "months_at_switch": months_at_switch,
            "target_seniority": "Senior level",
            "ideal_titles": ["Senior ML Engineer", "Senior AI Engineer", "Staff MLE",
                             "Senior Applied Scientist"],
            "penalise_titles": ["Principal", "Director", "VP", "Manager", "Junior", "Intern"],
            "max_years_required": 8,
            "scoring_note": (
                "Candidate will have ~{m} months of experience at switch time. "
                "Target senior-level roles (5-8 years)."
            ).format(m=months_at_switch),
        }
    else:
        return {
            "band": "8+ years",
            "months_at_switch": months_at_switch,
            "target_seniority": "Staff / Principal level",
            "ideal_titles": ["Staff ML Engineer", "Principal Engineer", "Distinguished Engineer"],
            "penalise_titles": ["Junior", "Intern", "Associate"],
            "max_years_required": 15,
            "scoring_note": (
                "Candidate will have ~{m} months of experience at switch time. "
                "Target staff/principal level roles."
            ).format(m=months_at_switch),
        }


# ─── Scoring Prompt ──────────────────────────────────────────────────────────

def build_scoring_system_prompt(exp_band: dict) -> str:
    """Build the scoring system prompt including experience-level guidance."""
    return f"""You are a job scoring agent for an AI/ML Engineer job search.

Score how well the job description matches the candidate profile.
Return ONLY valid JSON — no explanation, no markdown, nothing outside the JSON object.

MISSING INFO HANDLING:
If salary, experience requirement, or other key fields are not missing in the JD,
use reasonable inference from company type and industry norms. Do not penalise for missing info.

HARD RULE — CHECK THIS FIRST BEFORE ANY OTHER SCORING:
If the job title contains ANY of these words: "Senior", "Sr.", "Staff", "Principal", "Lead", "Manager",
"Director", "Head of", "VP", "President" → IMMEDIATELY return score=3, relevancy="low".
No exceptions. Not even for MAANG. The candidate is {exp_band['band']} experience level
({exp_band['months_at_switch']} months at switch) and these roles are too senior.
Roles WITHOUT a seniority prefix are fine: "Applied Scientist", "ML Engineer", "Data Scientist",
"AI Engineer", "Machine Learning Engineer" — these can be any level and should be scored normally.

SCORING (only if title passes the hard rule above):
1. Company + salary: 0-4 points
   IMPORTANT: If "Company tier" is provided in the pre-extracted facts below, use it directly — do not reclassify.
   - maang (MAANG India) + salary likely ≥ target: 4 pts
   - top_global_product or top_indian_product: 3 pts
   - top_ai_startup: 2 pts
   - unknown tier or not in watchlist → infer: good product company = 2 pts, service company = cap total at 2
2. ML/AI role relevance: 0-3 points
   - Core ML/AI role (MLE, AI Engineer, Applied Scientist, Data Scientist with ML work): 3 pts
   - Mostly SWE with some ML exposure: 1-2 pts
   - Pure SWE or non-technical: 0 pts
3. Skill overlap: 0-2 points
   - Strong (≥3 key skills match): 2 pts | Partial (1-2 match): 1 pt
   - Missing a REQUIRED skill: -1 pt | Missing a PREFERRED skill: -0.3 pts
4. Experience fit: 0-1 point
   - Role is entry/junior level ({exp_band['band']}): 1 pt
   - Requires slightly more experience but not senior-titled: 0.5 pt

Output schema (return exactly this, nothing else):
{{
  "score": integer between 1 and 10,
  "relevancy": "high" or "medium" or "low",
  "reason": "one sentence: mention seniority level, company quality, and top skill match or gap",
  "required_skills_missing": ["list of required skills candidate lacks"],
  "preferred_skills_missing": ["list of preferred skills candidate lacks"],
  "job_id": "company_roleSlug_relevancy"
}}

Relevancy bands: high = score 8-10, medium = score 5-7, low = score 1-4"""


# ─── Profile Loading ──────────────────────────────────────────────────────────

def load_profile() -> dict:
    """Load profile.json. Fails loudly if file is missing."""
    config = Config()
    if not config.profile_path.exists():
        raise FileNotFoundError(
            f"profile.json not found at {config.profile_path}. "
            "Run scripts/run_persona_builder.py first."
        )
    with open(config.profile_path, encoding="utf-8") as f:
        return json.load(f)


def build_candidate_summary(profile: dict, exp_band: dict) -> str:
    """Build a candidate summary string for the LLM scoring user prompt."""
    identity = profile.get("identity", {})
    target   = profile.get("target", {})
    skills   = profile.get("skills", [])

    skill_names   = [s["skill"] for s in skills]
    strong_skills = [s["skill"] for s in skills if s.get("depth") in ("can_architect", "can_teach")]
    market_aliases = []
    for s in skills:
        market_aliases.extend(s.get("market_aliases", []))

    return f"""
Name: {identity.get('name')}
Current Role: {identity.get('current_role')} at {identity.get('current_company')}
Total Experience: {identity.get('total_experience_months')} months
Experience at Switch: ~{exp_band['months_at_switch']} months ({exp_band['band']} band)
Target Seniority: {exp_band['target_seniority']}
Education: {identity.get('education')}
Location: {identity.get('location')}

Target Roles: {', '.join(target.get('roles', []))}
Min Salary: {target.get('min_salary_lpa')} LPA
Target Locations: {', '.join(target.get('locations', []))}
Hard Nos: {', '.join(target.get('hard_nos', []))}

Strong Skills (can architect/teach): {', '.join(strong_skills)}
All Skills: {', '.join(skill_names)}
JD Keyword Aliases: {', '.join(market_aliases[:30])}
Known Gaps: {', '.join(profile.get('known_gaps', [])[:3])}
""".strip()


# ─── Job ID Generation ────────────────────────────────────────────────────────

def slugify(text: str, max_len: int = 22) -> str:
    """Convert any string to a lowercase underscore slug."""
    slug = re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")
    return slug[:max_len]


def generate_job_id(company: str, title: str, relevancy: str) -> str:
    """
    Generate a unique job ID: company_roleSlug_relevancy
    Example: google_machine_learning_engineer_high
    """
    return f"{slugify(company)}_{slugify(title)}_{relevancy}"


# ─── Hard-No Filter ───────────────────────────────────────────────────────────

SERVICE_COMPANY_KEYWORDS = [
    "tcs", "tata consultancy", "infosys", "wipro", "accenture",
    "capgemini", "cognizant", "hcl", "tech mahindra", "mphasis",
    "hexaware", "ltimindtree", "birlasoft", "kpit", "cyient",
    "mindtree", "mastech", "niit technologies", "zensar", "ntt data",
    "happiest minds",
]

# Job aggregators and recruiter platforms — post on behalf of real employers.
# Filtered out because we can't verify the actual hiring company or salary.
JOB_AGGREGATOR_KEYWORDS = [
    "jobs ai", "hackajob", "tasc outsourcing", "tasc global",
    "unicotalent", "rupa career", "naukri resdex",
]

def is_hard_no(company_name: str, profile_hard_nos: list) -> bool:
    """Return True if this company should be skipped without scoring."""
    name_lower = company_name.lower()
    for keyword in SERVICE_COMPANY_KEYWORDS:
        if keyword in name_lower:
            return True
    for keyword in JOB_AGGREGATOR_KEYWORDS:
        if keyword in name_lower:
            return True
    for hard_no in profile_hard_nos:
        if hard_no.lower() in name_lower:
            return True
    return False


# ─── Company Tier Lookup ─────────────────────────────────────────────────────
# Load profile/target_companies.json once and cache it at module level.
# All 50 watchlist companies get a verified tier; everything else is "unknown".
# Passing tier as a stated fact to the LLM removes company-name guessing and
# prevents inconsistency across runs (same company scored 3 pts vs 4 pts).

_COMPANY_TIER_CACHE: dict | None = None


def _load_company_tier_cache() -> dict:
    """Load company → tier mapping from target_companies.json. Cached after first load."""
    global _COMPANY_TIER_CACHE
    if _COMPANY_TIER_CACHE is not None:
        return _COMPANY_TIER_CACHE

    companies_path = Path("profile/target_companies.json")
    if not companies_path.exists():
        _COMPANY_TIER_CACHE = {}
        return _COMPANY_TIER_CACHE

    with open(companies_path, encoding="utf-8") as f:
        data = json.load(f)

    cache: dict = {}
    for company in data.get("companies", []):
        name = company.get("name", "").lower().strip()
        tier = company.get("tier", "unknown")
        if name:
            cache[name] = tier

    _COMPANY_TIER_CACHE = cache
    return cache


def classify_company_tier(company_name: str) -> str:
    """
    Return the verified tier for a company using target_companies.json as ground truth.
    Falls back to 'unknown' for companies not in the 50-company watchlist.

    Tier values: maang | top_global_product | top_indian_product | top_ai_startup | unknown
    """
    cache = _load_company_tier_cache()
    name_lower = company_name.lower().strip()

    # Exact match first
    if name_lower in cache:
        return cache[name_lower]

    # Partial match: handles "Amazon Web Services (AWS)" → matches "amazon"
    for known_name, tier in cache.items():
        if known_name in name_lower or name_lower in known_name:
            return tier

    return "unknown"


# ─── Pre-LLM Title Filters ────────────────────────────────────────────────────

# Support/ops titles — never core ML work regardless of company or JD text.
# These are universal across all job seekers, so fine to hardcode as constants.
_SUPPORT_OPS_TITLE_KEYWORDS = [
    "support engineer", "site reliability", " sre ", "devops engineer",
    "platform engineer", "cloud engineer", "infrastructure engineer",
    "systems development engineer", "systems engineer",
]

# Pure SWE titles — may mention ML in JD but job function is software engineering.
# We pass this as a fact to the LLM rather than hard-capping, because some
# SWE roles at top companies do have meaningful ML work inside the description.
_PURE_SWE_TITLE_KEYWORDS = [
    "software development engineer", "full stack", "fullstack",
    "frontend engineer", "front-end engineer", "backend engineer",
    "back-end engineer", "java developer", "web developer",
]


def classify_job_function(title: str) -> str:
    """
    Classify the job function from the title alone — no LLM needed.
    Returns: 'support_ops' | 'pure_swe' | 'other'

    'support_ops' → hard cap at 3 before LLM (never core ML work)
    'pure_swe'    → pass as stated fact to LLM (may have ML inside JD, let LLM decide)
    'other'       → normal LLM scoring
    """
    title_lower = " " + title.lower() + " "   # pad so partial-word checks are reliable
    for kw in _SUPPORT_OPS_TITLE_KEYWORDS:
        if kw in title_lower:
            return "support_ops"
    for kw in _PURE_SWE_TITLE_KEYWORDS:
        if kw in title_lower:
            # A SWE title with an explicit AI/ML qualifier is ml_adjacent, not pure_swe
            if any(q in title_lower for q in [" ai ", " ml ", "machine learning", "llm", "nlp", "genai"]):
                return "other"
            return "pure_swe"
    return "other"


def is_seniority_mismatch(title: str, exp_band: dict) -> bool:
    """
    Return True if the job title contains a seniority level that doesn't fit
    this candidate's experience band.

    Uses exp_band["penalise_titles"] — computed from profile, not hardcoded.
    A 20-year engineer's band penalises "Junior/Intern"; a 0-3 year band
    penalises "Senior/Staff/Principal". The same function works for any user.

    Uses whole-word regex so 'intern' won't match 'internal' or 'internship'.
    """
    title_lower = title.lower()
    for keyword in exp_band.get("penalise_titles", []):
        pattern = r"(?<![a-z])" + re.escape(keyword.lower()) + r"(?![a-z])"
        if re.search(pattern, title_lower):
            return True
    return False


# ─── Urgency Calculation ─────────────────────────────────────────────────────

def compute_urgency(date_posted) -> str:
    """
    Compute urgency tier from job posting date.
    Research: applications within 24h get ~3x higher response rates.
    """
    if date_posted is None or (isinstance(date_posted, float) and pd.isna(date_posted)):
        return "UNKNOWN"

    try:
        if isinstance(date_posted, str):
            posted_dt = datetime.fromisoformat(date_posted).replace(tzinfo=timezone.utc)
        elif hasattr(date_posted, "tzinfo"):
            posted_dt = date_posted if date_posted.tzinfo else date_posted.replace(tzinfo=timezone.utc)
        else:
            posted_dt = datetime(date_posted.year, date_posted.month, date_posted.day, tzinfo=timezone.utc)

        days_old = (datetime.now(timezone.utc) - posted_dt).days

        if days_old < 1:   return "URGENT"   # Apply today
        elif days_old <= 3: return "HIGH"
        elif days_old <= 7: return "NORMAL"
        else:               return "LOW"
    except Exception:
        return "UNKNOWN"


# ─── Job Fetching ─────────────────────────────────────────────────────────────

def fetch_jobs_indeed(search_term: str, location: str, hours_old: int = 72) -> pd.DataFrame:
    """
    Fetch jobs from Indeed + Glassdoor via JobSpy.
    Google removed (403 broken since Sep 2025). Naukri removed (reCAPTCHA 406).
    LinkedIn handled separately via scrape_linkedin_jobs().
    """
    logger.info(f"JobSpy (Indeed+Glassdoor): '{search_term}' in '{location}' (last {hours_old}h)")
    try:
        df = scrape_jobs(
            site_name=["indeed", "glassdoor"],
            search_term=search_term,
            location=location,
            results_wanted=100,
            hours_old=hours_old,
            country_indeed="India",
            description_format="markdown",
            verbose=0,
        )
        logger.info(f"  Indeed/Glassdoor: {len(df)} results for '{search_term}'")
        return df
    except Exception as e:
        logger.error(f"JobSpy failed for '{search_term}': {e}")
        return pd.DataFrame()


def fetch_jobs_linkedin(search_term: str, location: str, hours_old: int = 72) -> list[dict]:
    """
    Fetch jobs from LinkedIn using the public guest API (no login required).
    Applies f_E=Entry+Associate filter at source to avoid senior roles.
    Returns list of dicts (not DataFrame — merged later).
    """
    logger.info(f"LinkedIn guest API: '{search_term}' in '{location}' (last {hours_old}h)")
    try:
        jobs = scrape_linkedin_jobs(
            search_term=search_term,
            location=location,
            hours_old=hours_old,
            results_wanted=50,
            experience_levels=["entry", "associate"],  # filters out Senior/Staff at source
            fetch_descriptions=True,
            sleep_between_pages=1.2,
        )
        logger.info(f"  LinkedIn: {len(jobs)} results for '{search_term}'")
        return jobs
    except Exception as e:
        logger.error(f"LinkedIn guest API failed for '{search_term}': {e}")
        return []


# ─── Job Scoring ──────────────────────────────────────────────────────────────

def score_job(
    company: str,
    title: str,
    description: str,
    candidate_summary: str,
    system_prompt: str,
    job_function: str = "other",
    shared_llm: "LLMClient | None" = None,
    company_tier: str = "unknown",
) -> dict:
    """
    Score a single job against the candidate profile using gpt-5-nano.
    job_function and company_tier are pre-extracted facts passed as ground truth
    so the LLM doesn't have to infer them — eliminates run-to-run inconsistency.
    shared_llm: pass a single LLMClient instance when scoring in parallel to
    avoid creating one HTTP client per thread.
    Returns parsed score dict. Returns a safe default on failure.
    """
    llm    = shared_llm if shared_llm is not None else LLMClient()
    config = Config()

    function_labels = {
        "support_ops": "Support / Operations (not core ML work)",
        "pure_swe":    "Pure Software Engineering (minimal ML involvement expected)",
        "other":       "ML / AI / Data role (score normally)",
    }
    function_note = function_labels.get(job_function, "Score normally")

    tier_labels = {
        "maang":              "maang — MAANG India (Google/Meta/Amazon/Apple/Microsoft/Netflix) → 4 pts for company quality",
        "top_global_product": "top_global_product — Top global product company (Uber, Walmart, Stripe, Adobe etc.) → 3 pts",
        "top_indian_product": "top_indian_product — Top Indian product company (Flipkart, Zepto, Swiggy, Razorpay etc.) → 3 pts",
        "top_ai_startup":     "top_ai_startup — Top AI-native startup (Sarvam, Krutrim, Uniphore etc.) → 2 pts",
        "unknown":            "unknown — not in verified watchlist, infer from JD and general knowledge",
    }
    tier_note = tier_labels.get(company_tier, tier_labels["unknown"])

    user_prompt = f"""
CANDIDATE PROFILE:
{candidate_summary}

PRE-EXTRACTED FACTS (treat these as ground truth — do not override):
- Detected job function from title: {function_note}
- Company tier from verified watchlist: {tier_note}

JOB TO SCORE:
Company: {company}
Role: {title}
Description:
{description[:2500]}
"""

    try:
        raw = llm.call(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=config.model_nano,
            max_tokens=512,
        )
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(cleaned)

    except json.JSONDecodeError as e:
        logger.warning(f"Score parse failed for {company}/{title}: {e}")
    except Exception as e:
        logger.error(f"Scoring error for {company}/{title}: {e}")

    return {
        "score": 0, "relevancy": "low",
        "reason": "Scoring failed",
        "required_skills_missing": [], "preferred_skills_missing": [],
        "job_id": generate_job_id(company, title, "low"),
    }


# ─── Results Display ──────────────────────────────────────────────────────────

URGENCY_STYLE  = {"URGENT": "bold red", "HIGH": "bold yellow", "NORMAL": "green", "LOW": "dim", "UNKNOWN": "dim"}
RELEVANCY_STYLE = {"high": "bold green", "medium": "yellow", "low": "dim red"}

# Maps substrings to a canonical parent company name for diversity cap purposes.
# Prevents "Amazon.com" and "Amazon Science" each getting their own 5-job allowance.
_PARENT_COMPANY_SUBSTRINGS = [
    "amazon", "google", "microsoft", "meta", "apple", "netflix",
    "uber", "flipkart", "swiggy", "zepto", "razorpay", "phonepe",
]


def canonical_company_name(company: str) -> str:
    """
    Normalize a company name to its parent for the diversity cap.
    'Amazon Science', 'Amazon.com', 'Amazon Web Services' all map to 'amazon'.
    Falls back to the lowercased name for unknown companies.
    """
    name_lower = company.lower().strip()
    for parent in _PARENT_COMPANY_SUBSTRINGS:
        if parent in name_lower:
            return parent
    return name_lower


def apply_company_diversity(scored_jobs: list, max_per_company: int = 3) -> list:
    """
    Limit results to max_per_company jobs from the same company.
    Keeps the highest-scored jobs per company and drops the rest.
    Prevents any one company (e.g. Amazon) from dominating the output.
    Uses canonical_company_name() so variants like 'Amazon Science' and
    'Amazon.com' count toward the same cap.
    """
    company_counts: dict = {}
    filtered = []
    for job in scored_jobs:
        company = canonical_company_name(job.get("company") or "unknown")
        count = company_counts.get(company, 0)
        if count < max_per_company:
            filtered.append(job)
            company_counts[company] = count + 1
    return filtered


def print_results(scored_jobs: list) -> None:
    """Print a ranked results table to the terminal."""
    if not scored_jobs:
        console.print("\n[yellow]No jobs matched your profile above the minimum score.[/yellow]")
        return

    table = Table(title="Dossier — Job Discovery Results", show_lines=True)
    table.add_column("#",        style="dim",   width=3)
    table.add_column("Score",    style="bold",  width=6)
    table.add_column("Urgency",                 width=8)
    table.add_column("Company",                 width=20)
    table.add_column("Role",                    width=30)
    table.add_column("Source",                  width=9)
    table.add_column("Reason",                  width=35)
    table.add_column("Link",                    width=45, no_wrap=False)

    for i, job in enumerate(scored_jobs, 1):
        urgency   = job.get("urgency", "UNKNOWN")
        relevancy = job.get("relevancy", "low")
        url       = job.get("url") or ""
        table.add_row(
            str(i),
            f"[{RELEVANCY_STYLE.get(relevancy, '')}]{job.get('score', 0)}/10[/]",
            f"[{URGENCY_STYLE.get(urgency, '')}]{urgency}[/]",
            (job.get("company") or "")[:20],
            (job.get("title") or "")[:30],
            (job.get("site") or ""),
            (job.get("reason") or "")[:35],
            url,
        )

    console.print()
    console.print(table)

    urgent_count = sum(1 for j in scored_jobs if j.get("urgency") == "URGENT")
    high_count   = sum(1 for j in scored_jobs if j.get("relevancy") == "high")
    console.print(
        f"\n  [bold]Total:[/bold] {len(scored_jobs)} jobs | "
        f"[bold green]High relevancy:[/bold green] {high_count} | "
        f"[bold red]URGENT (apply today):[/bold red] {urgent_count}\n"
    )


# ─── Main Entry Point ─────────────────────────────────────────────────────────

def run(hours_old: int = 72, min_score: int = 5) -> list:
    """
    Run the full job discovery pipeline.

    Args:
        hours_old: Only fetch jobs posted in last N hours (default 72 = 3 days)
        min_score: Skip jobs scoring below this (default 5 = medium+)

    Returns:
        List of scored job dicts sorted by score descending.
    """
    config = Config()
    config.artifacts_dir.mkdir(parents=True, exist_ok=True)

    # Step 1 — Load profile + compute experience band
    console.print("\n[bold]Step 1/4[/bold] — Loading profile...")
    profile = load_profile()

    current_months  = profile["identity"].get("total_experience_months", 0)
    switch_months   = profile["target"].get("switch_timeline_months", 12)
    exp_band        = compute_experience_band(current_months, switch_months)
    system_prompt   = build_scoring_system_prompt(exp_band)
    candidate_summary = build_candidate_summary(profile, exp_band)
    hard_nos        = profile["target"].get("hard_nos", [])
    locations       = profile["target"].get("locations", ["Bengaluru"])

    console.print(f"  Candidate: {profile['identity']['name']}")
    console.print(f"  Experience band at switch: {exp_band['band']} ({exp_band['months_at_switch']} months)")
    console.print(f"  Target seniority: {exp_band['target_seniority']}")
    console.print(f"  Location: {locations[0]}")

    # Step 2 — Fetch jobs from all sources
    console.print(f"\n[bold]Step 2/4[/bold] — Fetching jobs (last {hours_old}h)...")
    console.print(f"  Sources: Indeed + Glassdoor (JobSpy) + LinkedIn (guest API)")

    # Search terms come from profile["target"]["search_terms"] so any user can
    # customise them without touching code. Falls back to sensible defaults for
    # ML/AI roles if the field isn't present.
    default_search_terms = [
        "Machine Learning Engineer", "AI Engineer", "Applied Scientist",
        "Data Scientist", "Generative AI Engineer", "LLM Engineer",
        "NLP Engineer", "MLOps Engineer", "AI Research Engineer",
        "Computer Vision Engineer",
    ]
    search_terms = profile["target"].get("search_terms", default_search_terms)
    primary_location = locations[0]

    # Source A: Indeed + Glassdoor via JobSpy
    indeed_frames = []
    for term in search_terms:
        df = fetch_jobs_indeed(term, primary_location, hours_old=hours_old)
        if not df.empty:
            indeed_frames.append(df)

    indeed_combined = pd.concat(indeed_frames, ignore_index=True) if indeed_frames else pd.DataFrame()
    console.print(f"  Indeed/Glassdoor: {len(indeed_combined)} raw results")

    # Source B: LinkedIn via public guest API (runs after Indeed to space out requests)
    linkedin_rows = []
    for term in search_terms:
        jobs = fetch_jobs_linkedin(term, primary_location, hours_old=hours_old)
        linkedin_rows.extend(jobs)

    # Convert LinkedIn dicts to DataFrame rows compatible with Indeed format
    linkedin_df = pd.DataFrame(linkedin_rows) if linkedin_rows else pd.DataFrame()
    if not linkedin_df.empty and "linkedin_id" in linkedin_df.columns:
        linkedin_df = linkedin_df.drop(columns=["linkedin_id"], errors="ignore")
    console.print(f"  LinkedIn: {len(linkedin_df)} raw results")

    # Combine both sources, deduplicate by URL
    all_frames = [f for f in [indeed_combined, linkedin_df] if not f.empty]
    if not all_frames:
        console.print("[red]  No jobs fetched from any source. Check your internet connection.[/red]")
        return []

    combined = pd.concat(all_frames, ignore_index=True)
    # Primary dedup: exact URL match
    combined = combined.drop_duplicates(subset=["job_url"], keep="first")
    # Secondary dedup: same company + same title posted with different URLs (common on Indeed)
    combined["_dedup_key"] = (
        combined["company"].str.lower().str.strip() + "||" +
        combined["title"].str.lower().str.strip()
    )
    combined = combined.drop_duplicates(subset=["_dedup_key"], keep="first")
    combined = combined.drop(columns=["_dedup_key"])
    console.print(f"  [bold]{len(combined)} unique jobs[/bold] across all sources and search terms")

    # Step 3 — Filter and score
    console.print(f"\n[bold]Step 3/4[/bold] — Scoring each job (min score {min_score}/10)...")

    # ── Pass A: apply all rule-based pre-filters (no LLM cost) ───────────────
    # Collects jobs that survive into a list for parallel LLM scoring.
    # Pre-rejected jobs are captured with their reason for the audit file.
    jobs_for_llm: list[dict] = []
    rejected_jobs: list[dict] = []
    skipped_hard  = 0
    skipped_low   = 0
    skipped_seen  = 0

    for _, row in combined.iterrows():
        company     = str(row.get("company") or "Unknown")
        title       = str(row.get("title") or "Unknown")
        site        = str(row.get("site") or "")
        url         = str(row.get("job_url") or "")
        description = str(row.get("description") or "")
        date_posted = row.get("date_posted")

        if is_hard_no(company, hard_nos):
            skipped_hard += 1
            continue

        if len(description) < 100:
            continue

        temp_id = generate_job_id(company, title, "unknown")
        if job_vault_exists(temp_id):
            skipped_seen += 1
            continue

        if is_seniority_mismatch(title, exp_band):
            skipped_low += 1
            rejected_jobs.append({
                "company": company, "title": title, "site": site, "url": url,
                "score": 3, "relevancy": "low",
                "reason": "Seniority hard cap (pre-filter)",
                "required_skills_missing": [], "description_preview": description[:300],
            })
            continue

        job_function = classify_job_function(title)
        if job_function == "support_ops":
            skipped_low += 1
            rejected_jobs.append({
                "company": company, "title": title, "site": site, "url": url,
                "score": 3, "relevancy": "low",
                "reason": "Support/ops role (pre-filter)",
                "required_skills_missing": [], "description_preview": description[:300],
            })
            continue

        company_tier = classify_company_tier(company)

        jobs_for_llm.append({
            "company": company, "title": title, "site": site, "url": url,
            "description": description, "date_posted": date_posted,
            "job_function": job_function, "company_tier": company_tier,
        })

    # ── Pass B: score surviving jobs in parallel using ThreadPoolExecutor ─────
    # WHY THREADPOOLEXECUTOR: each LLM call waits 1-2s for the API response.
    # With 400+ jobs, serial scoring takes 10+ minutes. Threads let us run 8
    # concurrent API calls — near-linear speedup since the bottleneck is network
    # I/O, not CPU. No async rewrite needed; the existing sync score_job works as-is.
    scored_jobs: list[dict] = []
    llm_instance = LLMClient()   # one shared client for all threads (HTTP client is thread-safe)
    total = len(jobs_for_llm)
    console.print(f"  Pre-filtered {skipped_hard + skipped_low} jobs | Sending {total} to LLM (8 workers)...")

    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_job = {
            executor.submit(
                score_job,
                j["company"], j["title"], j["description"],
                candidate_summary, system_prompt, j["job_function"], llm_instance,
                j["company_tier"],
            ): j
            for j in jobs_for_llm
        }

        completed = 0
        for future in as_completed(future_to_job):
            job_data = future_to_job[future]
            completed += 1
            console.print(f"  Scored {completed}/{total}...", end="\r")

            result = future.result()

            if result["score"] < min_score:
                skipped_low += 1
                rejected_jobs.append({
                    "company":  job_data["company"],
                    "title":    job_data["title"],
                    "site":     job_data["site"],
                    "url":      job_data["url"],
                    "score":    result["score"],
                    "relevancy": result.get("relevancy", "low"),
                    "reason":   result.get("reason", ""),
                    "required_skills_missing": result.get("required_skills_missing", []),
                    "description_preview": job_data["description"][:300],
                })
                continue

            relevancy = result.get("relevancy", "low")
            urgency   = compute_urgency(job_data["date_posted"])
            job_id    = generate_job_id(job_data["company"], job_data["title"], relevancy)

            full_record = {
                **result,
                "job_id":   job_id,
                "company":  job_data["company"],
                "title":    job_data["title"],
                "site":     job_data["site"],
                "url":      job_data["url"],
                "urgency":  urgency,
                "found_at": datetime.now(timezone.utc).isoformat(),
                "experience_band": exp_band["band"],
            }
            save_jd(job_id, job_data["description"])
            save_scorecard(job_id, full_record)
            scored_jobs.append(full_record)

    # Step 4 — Sort and display
    console.print(" " * 80, end="\r")
    console.print(f"\n[bold]Step 4/4[/bold] — Results")
    console.print(f"  Hard-no skipped: {skipped_hard} | Low score skipped: {skipped_low} | Already seen: {skipped_seen}")

    scored_jobs.sort(key=lambda j: (j.get("score", 0)), reverse=True)

    # Apply company diversity cap — max 3 jobs per company in final output
    # Jobs are already sorted by score, so we keep the best ones per company
    diverse_jobs = apply_company_diversity(scored_jobs, max_per_company=5)
    dropped = len(scored_jobs) - len(diverse_jobs)
    if dropped:
        console.print(f"  Company diversity cap applied: {dropped} duplicate-company jobs removed (max 5 per company)")

    print_results(diverse_jobs)

    # Save full run summary
    summary_path = config.data_dir / "last_discovery_run.json"
    summary_path.write_text(json.dumps(scored_jobs, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"  Full results saved → {summary_path}")

    # Save rejected jobs for scoring audit
    rejected_jobs.sort(key=lambda j: j["score"], reverse=True)
    rejected_path = config.data_dir / "rejected_jobs.json"
    rejected_path.write_text(json.dumps(rejected_jobs, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"  Rejected jobs saved → {rejected_path} ({len(rejected_jobs)} jobs below score {min_score})\n")

    return scored_jobs
