"""
agents/referral_finder.py

Given a job_id, finds people at the target company who could refer the user for that role.

Three-tier strategy:
  Tier 1 (warm):    User's existing LinkedIn connections at the company.
                    Loaded from profile/linkedin_connections.csv (official LinkedIn export).
                    Skipped gracefully if the file doesn't exist or skip_csv=True is passed.

  Tier 2 (cold):    Tavily search — purpose-built for AI agents, better LinkedIn coverage
                    than DDG (DDG has inconsistent LinkedIn indexing across runs).
                    Queries built from profile["target"]["search_terms"] — not hardcoded.
                    Only accepts results where LinkedIn title explicitly confirms employment
                    at the target company ("at Grab" / "@ Grab" in title).
                    Uses ~5 Tavily credits per job run.

                    Future (Dossier Max / long-term): SerpAPI gives Google-quality LinkedIn
                    search with 100 free queries/month. Better coverage, more stable results.
                    Switch when Tavily credits become a bottleneck or for higher-volume use.
                    Needs SERPAPI_KEY in .env — see https://serpapi.com

  Tier 3 (message): gpt-5 writes a personalised LinkedIn cold message per contact,
                    using tone.md, intel.json (company context), and gap.json (skills match).

Output: data/artifacts/{job_id}/referrals.json
Schema: [{name, title, company, linkedin_url, tier, connection_type,
          outreach_hook, confidence, status}]
"""

import csv
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

import requests

from config import Config
from core.llm_client import LLMClient

logger = logging.getLogger(__name__)

# ML/DS/AI title keywords used to rank contacts by relevance
# Space-prefixed " ml" and " ai" catch "Head of ML", "VP of AI", "Data and AI" etc.
_ML_TITLE_KEYWORDS = [
    "machine learning", "data scientist", "data science", "ml engineer",
    "ai engineer", "applied scientist", "nlp", "computer vision", "deep learning",
    "llm", "generative ai", "genai", "mlops", "research scientist", "analytics engineer",
    " ml", " ai",
]

# Seniority/hiring keywords — only contribute relevance when ML/data signal is also present.
# Prevents pure "Senior Engineering Manager" from passing while allowing
# "Head of ML", "VP of Data Science", "Director of AI" through.
_HIRING_TITLE_KEYWORDS = [
    "hiring manager", "head of", "director", "lead",
    "principal", "staff", "vp ", "vice president",
]


# ─── Profile context helpers ─────────────────────────────────────────────────


def _parse_college(education_str: str) -> str:
    """Extract college name from the education string in profile.json identity."""
    # education_str format: "B.Tech Computer Science, IIIT SriCity (CGPA: 8.1, 2025)"
    parts = education_str.split(",")
    if len(parts) >= 2:
        # Take the second part, strip everything from "(" onward
        return parts[1].split("(")[0].strip()
    return ""


def _load_tone(tone_path: Path) -> str:
    """Load tone.md content for use in message generation prompt."""
    if tone_path.exists():
        return tone_path.read_text(encoding="utf-8")
    logger.warning("tone.md not found at %s — using generic tone instructions", tone_path)
    return "Be casual, direct, and concise. 3-5 lines max. No emojis."


def _build_career_summary(profile: dict) -> str:
    """Build a 1-line career summary from the first project entry in profile.json.

    Used in cold messages to give the recipient a concrete sense of what the sender builds.
    Format: "Name — short description using Tech1, Tech2, Tech3."
    """
    projects = profile.get("projects", [])
    if not projects:
        return ""
    p = projects[0]
    name = p.get("name", "")
    desc = p.get("description", "")
    # Truncate description to ~90 chars so the sentence stays tight
    if len(desc) > 90:
        desc = desc[:90].rsplit(" ", 1)[0]
    tech = p.get("tech", [])[:3]
    tech_str = ", ".join(tech) if tech else ""
    parts = [f"{name} — {desc}"]
    if tech_str:
        parts.append(f"using {tech_str}")
    return " ".join(parts) + "."


def _load_profile_context(config: Config) -> dict:
    """Load sender context needed for cold message generation."""
    profile = json.loads(config.profile_path.read_text(encoding="utf-8"))
    identity = profile.get("identity", {})
    target = profile.get("target", {})

    college = _parse_college(identity.get("education", ""))

    github_username = identity.get("github", "")
    github_url = f"https://github.com/{github_username}" if github_username else ""

    linkedin_handle = identity.get("linkedin", "")
    linkedin_url = f"https://linkedin.com/{linkedin_handle}" if linkedin_handle else ""

    # short_title: informal role label for cold messages ("AI Engineer" not the full official title)
    short_title = identity.get("short_title") or identity.get("current_role", "")

    return {
        "name": identity.get("name", ""),
        "current_role": identity.get("current_role", ""),
        "short_title": short_title,
        "current_company": identity.get("current_company", ""),
        "college": college,
        "target_roles": target.get("roles", []),
        "search_terms": target.get("search_terms", []),
        "career_summary": _build_career_summary(profile),
        "github_url": github_url,
        "linkedin_url": linkedin_url,
        "resume_url": identity.get("resume_url", ""),
        "portfolio_url": identity.get("portfolio_url", ""),
    }


# ─── Artifact loaders ────────────────────────────────────────────────────────


def _load_intel(job_id: str, config: Config) -> dict:
    """Load company intel for the job from intel.json."""
    intel_path = config.artifacts_dir / job_id / "intel.json"
    if not intel_path.exists():
        logger.warning("No intel.json found for job %s — company context will be thin", job_id)
        return {}
    return json.loads(intel_path.read_text(encoding="utf-8"))


def _load_gap(job_id: str, config: Config) -> dict:
    """Load skills gap data for the job from gap.json."""
    gap_path = config.artifacts_dir / job_id / "gap.json"
    if not gap_path.exists():
        logger.warning("No gap.json found for job %s — skills context unavailable", job_id)
        return {}
    return json.loads(gap_path.read_text(encoding="utf-8"))


def _load_jd_info(job_id: str, config: Config) -> tuple[str, str]:
    """Load job title and posting URL from score_card.json. Returns (title, url)."""
    score_path = config.artifacts_dir / job_id / "score_card.json"
    if score_path.exists():
        score_data = json.loads(score_path.read_text(encoding="utf-8"))
        return score_data.get("title", ""), score_data.get("url", "")
    return "", ""


# ─── Tier 1 — LinkedIn connections CSV ───────────────────────────────────────


def _fuzzy_company_match(csv_company: str, target_company: str) -> bool:
    """Return True if csv_company is a reasonable match for target_company.

    Handles cases like "Flipkart Internet Pvt Ltd" matching "Flipkart".
    """
    csv_lower = csv_company.lower().strip()
    target_lower = target_company.lower().strip()

    # Direct substring match in either direction
    if target_lower in csv_lower or csv_lower in target_lower:
        return True

    # Strip common legal suffixes and try again
    for suffix in [" pvt ltd", " private limited", " ltd", " inc", " llc", " corp", " india"]:
        csv_lower = csv_lower.replace(suffix, "")
    if target_lower in csv_lower or csv_lower in target_lower:
        return True

    return False


def _score_title_relevance(title: str) -> int:
    """Score a job title by ML/DS relevance. Higher = more relevant.

    Hiring/seniority keywords only count when an ML or data signal is also present.
    This prevents "Senior Engineering Manager" (no ML signal) from passing while
    "Head of ML" or "VP of Data Science" (ML signal present) still pass.
    """
    title_lower = title.lower()
    ml_score = sum(2 for kw in _ML_TITLE_KEYWORDS if kw in title_lower)
    has_data_signal = ml_score > 0 or "data" in title_lower
    hiring_score = (
        sum(1 for kw in _HIRING_TITLE_KEYWORDS if kw in title_lower)
        if has_data_signal else 0
    )
    return ml_score + hiring_score


# Words that indicate a string is a job title, not a company name.
# Used to distinguish "Senior Data Scientist" (title) from "Grab" (company) in DDG results.
_JOB_TITLE_WORDS = [
    "engineer", "scientist", "analyst", "developer", "manager", "lead", "head",
    "director", "intern", "associate", "researcher", "consultant", "architect",
    "specialist", "officer", "founder", "co-founder", "president",
]


def _extract_title_company(title: str) -> str:
    """Extract the current company from a LinkedIn result title if present.

    Handles three LinkedIn title formats:
      "Name - Role at Company | LinkedIn"  → extracts "Company"
      "Name - Role @ Company | LinkedIn"   → extracts "Company"
      "Name - CompanyName | LinkedIn"      → extracts "CompanyName" if it looks like a
                                             company (no job-title keywords in the string)
    Returns empty string when the remainder looks like a job title (can't determine company).
    """
    if " - " not in title:
        return ""
    role_part = title.split(" - ", 1)[1]
    role_part = re.sub(r"\s*\|\s*LinkedIn.*$", "", role_part).strip()

    # "Role at Company" format
    if " at " in role_part:
        return role_part.split(" at ")[-1].strip()

    # "Role @ Company" format
    if "@" in role_part:
        return role_part.split("@")[-1].strip()

    # "CompanyName" format — the remainder is either a company or a bare job title.
    # If it contains job-title words ("engineer", "scientist", etc.) treat it as a title
    # and return "" (can't extract company). Otherwise treat it as the company name.
    role_lower = role_part.lower()
    for keyword in _JOB_TITLE_WORDS:
        if keyword in role_lower:
            return ""
    return role_part


def find_tier1_connections(company_name: str, csv_path: Path) -> list[dict]:
    """Find user's existing LinkedIn connections at the target company from CSV export.

    The CSV is the official LinkedIn connections export from:
    Settings → Data Privacy → Get a copy of your data → Connections
    Columns: First Name, Last Name, Email Address, Company, Position, Connected On
    """
    if not csv_path.exists():
        logger.info("Connections CSV not found at %s — skipping Tier 1", csv_path)
        return []

    matches = []
    try:
        with csv_path.open(encoding="utf-8", newline="") as f:
            # LinkedIn CSVs have a 3-line header before the actual CSV data
            content = f.read()
            # Find the actual CSV start (header row with "First Name")
            csv_start = content.find("First Name")
            if csv_start == -1:
                logger.warning("Could not find CSV header in connections file")
                return []
            reader = csv.DictReader(content[csv_start:].splitlines())
            for row in reader:
                csv_company = row.get("Company", "").strip()
                if not csv_company:
                    continue
                if not _fuzzy_company_match(csv_company, company_name):
                    continue

                first = row.get("First Name", "").strip()
                last = row.get("Last Name", "").strip()
                name = f"{first} {last}".strip()
                position = row.get("Position", "").strip()

                matches.append({
                    "name": name,
                    "title": position,
                    "company": company_name,
                    "linkedin_url": "",  # Official export does not include URLs
                    "tier": 1,
                    "connection_type": "warm_connection",
                    "confidence": "high",
                    "relevance_score": _score_title_relevance(position),
                })
    except Exception as e:
        logger.error("Failed to read connections CSV: %s", e)
        return []

    # Sort by ML/DS title relevance descending
    matches.sort(key=lambda x: x["relevance_score"], reverse=True)

    logger.info("Tier 1: found %d connections at %s", len(matches), company_name)
    return matches[:5]  # Return top 5 warm connections


# ─── Tier 2 — Tavily cold search ─────────────────────────────────────────────

_TAVILY_URL = "https://api.tavily.com/search"
_TAVILY_TIMEOUT = 15


def _tavily_search(query: str, api_key: str, max_results: int = 5) -> list[dict]:
    """Run a Tavily search and return results as [{title, url, content}].

    Uses 1 credit per call (basic depth). Returns empty list on any failure.
    Tavily has better LinkedIn coverage than DDG and handles site: queries properly.
    """
    try:
        resp = requests.post(
            _TAVILY_URL,
            json={
                "api_key": api_key,
                "query": query,
                "search_depth": "basic",
                "topic": "general",
                "max_results": max_results,
                "include_answer": False,
                "include_raw_content": False,
            },
            timeout=_TAVILY_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("results", [])
    except requests.exceptions.HTTPError as e:
        logger.warning("Tavily HTTP %s for query '%s'", e.response.status_code, query)
    except requests.exceptions.RequestException as e:
        logger.warning("Tavily request failed for '%s': %s", query, e)
    except Exception as e:
        logger.error("Tavily unexpected error for '%s': %s", query, e)
    return []


def _parse_linkedin_result(result: dict, connection_type: str, company_name: str) -> Optional[dict]:
    """Parse a Tavily search result into a contact dict.

    LinkedIn result titles follow: "Name - Role at Company | LinkedIn"
    or simpler variants like "Name | LinkedIn".

    Company validation: require the title to explicitly confirm employment at the target
    company. "Trust the query" is not safe — search engines match keywords anywhere on the
    profile page, not just as current employer. We accept only results where
    result title or the result body snippet to filter out false positives.
    """
    title = result.get("title", "")
    # Tavily uses "url" key; DDG used "href" — handle both for safety
    href = result.get("url", result.get("href", ""))

    # Must resolve to a LinkedIn profile URL (not company pages or posts)
    if "linkedin.com/in/" not in href:
        return None

    # Company validation: REQUIRE the title to explicitly name the target company.
    # "Trust the query" is not safe — DDG matches "Grab" anywhere on the profile page
    # (projects, bio, interests) not just as current employer. We need precision over recall:
    # false positives (messaging someone who doesn't work at Grab) are worse than missing
    # a few genuine contacts.
    # Accepted formats: "Name - Role at Grab | LinkedIn" or "Name - Role @ Grab | LinkedIn"
    title_company = _extract_title_company(title)
    if not title_company:
        logger.debug("Skipping: no company found in title (can't confirm employment) — %s", title)
        return None
    if not _fuzzy_company_match(title_company, company_name):
        logger.debug(
            "Skipping: title company '%s' doesn't match target '%s' — %s",
            title_company, company_name, title,
        )
        return None

    name = ""
    role_str = ""

    if " - " in title:
        parts = title.split(" - ", 1)
        name = parts[0].strip().title()  # normalise ALL-CAPS scraped names
        role_part = parts[1]
        # Strip trailing " | LinkedIn" suffix
        role_part = re.sub(r"\s*\|\s*LinkedIn.*$", "", role_part).strip()
        # Extract role before " at Company"
        if " at " in role_part:
            role_str = role_part.split(" at ")[0].strip()
        else:
            role_str = role_part
    elif " | " in title:
        name = title.split(" | ")[0].strip()

    if not name or len(name) < 3:
        return None

    # Clean role_str: strip "@ Company" suffix and any trailing "| ..." sections
    # Tavily page titles often include "Role @ Company | Skill | Skill" — keep only the role part
    if role_str and "@" in role_str:
        role_str = role_str.split("@")[0].strip()
    if role_str:
        role_str = role_str.split("|")[0].strip()

    role_lower = (role_str or "").lower()

    # Drop ex-employees: "Ex Data Science Intern", "Former ML Engineer" etc.
    # These people no longer work at the company and cannot refer anyone.
    if role_lower.startswith(("ex ", "ex-", "former ")):
        logger.debug("Skipping ex-employee '%s' at %s", role_str, company_name)
        return None

    relevance = _score_title_relevance(role_str)
    role_lower_for_seniority = (role_str or "").lower()
    _SENIOR_WORDS = {"director", "vp ", "vice president", "head of", "chief", "principal", "staff", "fellow"}
    is_senior = any(w in role_lower_for_seniority for w in _SENIOR_WORDS)

    # Role relevance filter: drop pure SWE/non-DS contacts.
    # Keep if: score >= 1 (ML/DS/manager keyword present) OR title contains "data".
    # "data" catches "Lead Data Engineer", "Data and AI", "Data Analyst" etc.
    # Drops: "Software Engineer", "Associate SWE", "SWE" — no ML signal, no data signal.
    if relevance == 0 and "data" not in role_lower:
        logger.debug("Skipping low-relevance role '%s' at %s", role_str, company_name)
        return None

    # Clean up URL — remove tracking params after the profile slug
    clean_url = re.sub(r"\?.*$", "", href)

    # Confidence: senior contacts (Director/VP/Head) are unlikely to process referrals
    # directly — they need a different message tone. Mid-level ML match = high.
    if is_senior:
        confidence = "low"
    elif relevance >= 2:
        confidence = "high"
    else:
        confidence = "medium"

    return {
        "name": name,
        "title": role_str or "Unknown",
        "company": company_name,
        "linkedin_url": clean_url,
        "tier": 2,
        "connection_type": connection_type,
        "confidence": confidence,
        "is_senior": is_senior,
        "relevance_score": relevance,
    }


def find_tier2_cold(company_name: str, profile_ctx: dict, tavily_api_key: str) -> list[dict]:
    """Find cold contacts at the target company via Tavily search.

    Tavily has better LinkedIn coverage than DDG (DDG has inconsistent LinkedIn indexing).
    Queries built entirely from profile["target"]["search_terms"] — not hardcoded.
    Only India-based (in.linkedin.com) profiles accepted.
    Uses ~5 Tavily credits per job run.

    Query types (all profile-driven):
      - Per search_term:  "[term]" "[company]" site:linkedin.com/in
      - Senior variant:   "senior [term]" "[company]" site:linkedin.com/in  (top term)
      - Manager variant:  "[top term]" manager OR head "[company]" site:linkedin.com/in

    Alumni queries NOT run here — search engines can't reliably find "person who studied
    at X and now works at Y" (college in profile body, not title). Alumni = Tier 1 CSV only.
    """
    if not tavily_api_key:
        logger.error("TAVILY_API_KEY not set — Tier 2 cold search skipped")
        return []

    search_terms = profile_ctx.get("search_terms", [])
    if not search_terms:
        logger.warning("No search_terms in profile_ctx — Tier 2 will return empty")
        return []

    # Use top 3 terms to keep Tavily credit spend low (3 + 1 senior + 1 manager = 5 credits)
    top_terms = search_terms[:3]
    primary = top_terms[0]

    queries: list[tuple[str, str]] = []

    # One query per top search term — exact title match against company
    for term in top_terms:
        queries.append((
            f'"{term}" "{company_name}" site:in.linkedin.com/in',
            "cold",
        ))

    # Senior/lead variant for primary role
    queries.append((
        f'"senior {primary.lower()}" OR "lead {primary.lower()}" "{company_name}" site:in.linkedin.com/in',
        "cold",
    ))

    # Manager query — people who manage the team
    queries.append((
        f'"{primary}" manager OR head OR lead "{company_name}" site:in.linkedin.com/in',
        "cold",
    ))

    seen_urls: set[str] = set()
    seen_names: set[str] = set()
    contacts: list[dict] = []

    for query, connection_type in queries:
        logger.info("Tier 2 Tavily: %s", query)
        results = _tavily_search(query, api_key=tavily_api_key, max_results=5)

        for result in results:
            contact = _parse_linkedin_result(result, connection_type, company_name)
            if contact is None:
                continue

            # India-only filter: only accept in.linkedin.com profiles
            if "in.linkedin.com" not in contact["linkedin_url"]:
                logger.debug("Skipping non-India profile: %s", contact["linkedin_url"])
                continue

            url_key = contact["linkedin_url"].rstrip("/")
            name_key = contact["name"].lower()

            if url_key in seen_urls or name_key in seen_names:
                continue

            seen_urls.add(url_key)
            seen_names.add(name_key)
            contacts.append(contact)

        time.sleep(2)

    logger.info("Tier 2: found %d India-based contacts at %s", len(contacts), company_name)
    return contacts


# ─── Tier 3 — Cold message generation ────────────────────────────────────────


def generate_cold_message(
    contact: dict,
    profile_ctx: dict,
    intel: dict,
    gap: dict,
    job_title: str,
    job_url: str,
    llm: LLMClient,
    config: Config,
) -> str:
    """Generate a personalised LinkedIn cold message for one contact.

    Uses gpt-5.4-mini with career context, job URL, and profile links so the
    recipient has everything they need to refer without any follow-up.
    """
    system_prompt_path = config.prompts_dir / "cold_message_system.txt"
    if not system_prompt_path.exists():
        logger.error("cold_message_system.txt not found — cannot generate message")
        return ""
    system_prompt = system_prompt_path.read_text(encoding="utf-8")

    company_focus = intel.get("ml_relevance", intel.get("business_focus", ""))[:200]
    connection_type = contact.get("connection_type", "cold")

    if connection_type == "college_alumni":
        connection_hint = f"Shared college: {profile_ctx['college']}."
    elif connection_type == "company_alumni":
        connection_hint = f"Both worked at {profile_ctx['current_company']}."
    elif connection_type == "warm_connection":
        connection_hint = "Already connected on LinkedIn."
    else:
        connection_hint = "No prior connection."

    # Build links block — only include lines where the value is non-empty
    resume_url = profile_ctx.get("resume_url", "")
    github_url = profile_ctx.get("github_url", "")
    portfolio_url = profile_ctx.get("portfolio_url", "")

    links_lines = []
    if resume_url:
        links_lines.append(f"Resume: {resume_url}")
    if github_url:
        links_lines.append(f"GitHub: {github_url}")
    if portfolio_url:
        links_lines.append(f"Portfolio: {portfolio_url}")
    if job_url:
        links_lines.append(f"Job link: {job_url}")
    links_block = "\n".join(links_lines) if links_lines else "(no links available)"

    is_senior = contact.get("is_senior", False)
    ask_hint = (
        "Recipient is senior (Director/VP/Head). Do NOT ask for a referral. "
        "Instead, ask briefly for their perspective on the team or role — 1 sentence."
    ) if is_senior else (
        "Ask directly for a referral or to be pointed to the right person. Low pressure."
    )

    user_prompt = f"""Write a LinkedIn cold message. Details below.

Sender: {profile_ctx['name']}, {profile_ctx['short_title']} at {profile_ctx['current_company']}
What they've built: {profile_ctx.get('career_summary', '')}

Recipient: {contact['name']}, {contact['title']} at {contact['company']}
Connection context: {connection_hint}

Role being applied for: {job_title or 'ML/AI Engineer'} at {contact['company']}
Company ML context (use 1 specific detail if interesting): {company_focus or 'not available'}

Ask instruction: {ask_hint}

Links to include in the message exactly as written:
{links_block}"""

    try:
        message = llm.call(system_prompt, user_prompt, model=config.model_nano, max_tokens=600)
        return message.strip()
    except Exception as e:
        logger.error("Message generation failed for %s: %s", contact["name"], e)
        return ""


# ─── Main pipeline ────────────────────────────────────────────────────────────


def _connection_type_priority(contact: dict) -> int:
    """Sort key: lower number = higher priority in final referrals.json."""
    tier = contact.get("tier", 2)
    ctype = contact.get("connection_type", "cold")
    if tier == 1:
        return 0
    if ctype == "college_alumni":
        return 1
    if ctype == "company_alumni":
        return 2
    return 3


def run_referral_finder(job_id: str, skip_csv: bool = False) -> list[dict]:
    """Run the full referral finder pipeline for a given job_id.

    Args:
        job_id:   The artifact folder name (e.g. 'grab_data_scientist_high')
        skip_csv: If True, skip Tier 1 CSV search even if the file exists.
                  Also auto-skipped when profile/linkedin_connections.csv is not found.

    Returns:
        List of referral dicts written to data/artifacts/{job_id}/referrals.json
    """
    config = Config()
    llm = LLMClient()

    # --- Load context ---
    profile_ctx = _load_profile_context(config)
    intel = _load_intel(job_id, config)
    gap = _load_gap(job_id, config)
    job_title, job_url = _load_jd_info(job_id, config)

    company_name = intel.get("company", "")
    if not company_name:
        # Fall back to score_card.json — always present after job discovery, no intel needed
        score_card_path = config.artifacts_dir / job_id / "score_card.json"
        if score_card_path.exists():
            score_card = json.loads(score_card_path.read_text(encoding="utf-8"))
            company_name = score_card.get("company", "")
    if not company_name:
        logger.error("No company name found for job %s — run job discovery first", job_id)
        return []

    logger.info("Running referral finder for job %s at %s", job_id, company_name)

    # --- Tier 1: warm connections ---
    tier1_contacts: list[dict] = []
    if not skip_csv:
        csv_path = config.profile_dir / "linkedin_connections.csv"
        tier1_contacts = find_tier1_connections(company_name, csv_path)
    else:
        logger.info("Tier 1 skipped (skip_csv=True)")

    # --- Tier 2: Tavily cold search ---
    tier2_contacts = find_tier2_cold(company_name, profile_ctx, config.tavily_api_key)

    # --- Deduplicate Tier 2 against Tier 1 names ---
    tier1_names = {c["name"].lower() for c in tier1_contacts}
    tier2_unique = [c for c in tier2_contacts if c["name"].lower() not in tier1_names]

    all_contacts = tier1_contacts + tier2_unique

    if not all_contacts:
        logger.warning("No referral contacts found for %s", company_name)
        return []

    # --- Sort by priority ---
    all_contacts.sort(key=_connection_type_priority)

    # --- Tier 3: generate cold messages ---
    logger.info("Generating cold messages for %d contacts...", len(all_contacts))
    for contact in all_contacts:
        message = generate_cold_message(contact, profile_ctx, intel, gap, job_title, job_url, llm, config)
        contact["outreach_hook"] = message
        contact["status"] = "pending"
        # Remove internal keys before saving
        contact.pop("relevance_score", None)
        contact.pop("is_senior", None)

    # --- Save output ---
    out_dir = config.artifacts_dir / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "referrals.json"
    out_path.write_text(json.dumps(all_contacts, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info("Saved %d referrals to %s", len(all_contacts), out_path)
    return all_contacts
