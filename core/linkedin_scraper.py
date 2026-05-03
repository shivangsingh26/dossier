"""
core/linkedin_scraper.py — LinkedIn job scraper using the public guest API.

LinkedIn's official scraping is blocked, but they expose a public guest API
(no login required) used by their own job search page for non-logged-in visitors.

WHY WE BUILT THIS INSTEAD OF USING JOBSPY FOR LINKEDIN:
- JobSpy + hours_old + LinkedIn = silent empty results (documented limitation)
- LinkedIn rate limits JobSpy around page 10 with one IP
- This direct guest API is more reliable for low-volume personal use

ENDPOINT:
  https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search
  Response: HTML (not JSON) — parsed with BeautifulSoup

KEY PARAMETERS:
  keywords   — search term
  location   — "Bengaluru, India" etc
  f_TPR      — time filter: r86400 (24h), r604800 (7 days), r2592000 (30 days)
  f_E        — experience filter: 2=Entry level, 3=Associate, 4=Mid-Senior
  start      — pagination offset (0, 25, 50 ...)

RATE LIMITING:
  Sleep 1 second between page fetches. For personal job search volume (< 100 jobs/day)
  this is well within LinkedIn's tolerance. Do NOT run this in tight loops.

Phase A: Synchronous, no proxies, plain requests.
"""

import re
import time
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

from core.logger import get_logger

logger = get_logger(__name__)

GUEST_SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
GUEST_DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

# Rotate through a few real browser user agents to avoid trivial blocking
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# f_TPR values — map hours_old to LinkedIn's time filter codes
# LinkedIn only supports these three discrete values, not arbitrary hours
def hours_to_f_tpr(hours_old: int) -> str:
    """Convert hours_old to LinkedIn's f_TPR time filter parameter."""
    if hours_old <= 24:
        return "r86400"    # Past 24 hours
    elif hours_old <= 168:
        return "r604800"   # Past 7 days
    else:
        return "r2592000"  # Past 30 days


# f_E experience level codes
EXPERIENCE_LEVELS = {
    "entry":      "2",   # Entry level (0-2 years)
    "associate":  "3",   # Associate (2-5 years)
    "mid_senior": "4",   # Mid-Senior level
}


def _get_headers(agent_index: int = 0) -> dict:
    """Return HTTP headers that look like a real browser request."""
    return {
        "User-Agent": USER_AGENTS[agent_index % len(USER_AGENTS)],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.linkedin.com/jobs/search/",
        "Connection": "keep-alive",
    }


def _extract_job_id(job_url: str) -> str:
    """Extract the numeric LinkedIn job ID from a job URL.
    URL format: /jobs/view/some-slug-title-4407896335  (ID is the trailing number)
    Also handles: ?currentJobId=4407896335
    """
    match = re.search(r"currentJobId=(\d+)", job_url)
    if match:
        return match.group(1)
    # ID is always the last numeric segment in the URL path
    match = re.search(r"-(\d+)(?:/|\?|$)", job_url)
    return match.group(1) if match else ""


def _parse_date(date_str: str) -> datetime | None:
    """Parse an ISO date string into a datetime. Returns None on failure."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _parse_job_cards(html: str) -> list[dict]:
    """
    Parse LinkedIn job listing HTML into a list of job dicts.
    Returns only the core fields — description is fetched separately.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Each job is a list item containing a div.base-card
    cards = soup.find_all("div", class_="base-card")
    jobs = []

    for card in cards:
        try:
            # Title
            title_el = card.find("h3", class_=lambda c: c and "title" in c.lower())
            if not title_el:
                title_el = card.find("h3")
            title = title_el.get_text(strip=True) if title_el else ""

            # Company
            company_el = card.find("h4", class_=lambda c: c and "subtitle" in c.lower())
            if not company_el:
                company_el = card.find("h4")
            company = company_el.get_text(strip=True) if company_el else ""

            # Location
            loc_el = card.find("span", class_=lambda c: c and "location" in c.lower())
            location = loc_el.get_text(strip=True) if loc_el else ""

            # Job URL + ID
            url_el = card.find("a", class_=lambda c: c and "full-link" in (c or "").lower())
            if not url_el:
                url_el = card.find("a", href=re.compile(r"linkedin\.com/jobs"))
            job_url = url_el.get("href", "").split("?")[0] if url_el else ""
            job_id  = _extract_job_id(job_url)

            # Date posted
            time_el = card.find("time")
            date_str = time_el.get("datetime", "") if time_el else ""
            date_posted = _parse_date(date_str)

            if not title or not company:
                continue

            jobs.append({
                "site":        "linkedin",
                "title":       title,
                "company":     company,
                "location":    location,
                "job_url":     job_url,
                "linkedin_id": job_id,
                "date_posted": date_posted,
                "description": "",   # Filled in by fetch_description()
            })

        except Exception as e:
            logger.debug(f"Failed to parse a LinkedIn job card: {e}")
            continue

    return jobs


def _fetch_description(job_id: str, agent_index: int = 0) -> str:
    """
    Fetch the full job description for a single LinkedIn job ID.
    Returns empty string on failure.
    """
    if not job_id:
        return ""
    try:
        url = GUEST_DETAIL_URL.format(job_id=job_id)
        resp = requests.get(url, headers=_get_headers(agent_index), timeout=10)
        if resp.status_code != 200:
            return ""

        soup = BeautifulSoup(resp.text, "html.parser")
        desc_el = soup.find("div", class_=lambda c: c and "description" in (c or "").lower())
        if not desc_el:
            desc_el = soup.find("section", class_=lambda c: c and "description" in (c or "").lower())
        return desc_el.get_text(separator="\n", strip=True) if desc_el else ""

    except Exception as e:
        logger.debug(f"Failed to fetch description for LinkedIn job {job_id}: {e}")
        return ""


def scrape_linkedin_jobs(
    search_term: str,
    location: str,
    hours_old: int = 72,
    results_wanted: int = 25,
    experience_levels: list[str] | None = None,
    fetch_descriptions: bool = True,
    sleep_between_pages: float = 1.2,
) -> list[dict]:
    """
    Scrape LinkedIn jobs using the public guest API.

    Args:
        search_term:        e.g. "Machine Learning Engineer"
        location:           e.g. "Bengaluru, India"
        hours_old:          Only return jobs posted within last N hours (24, 72, or 168+)
        results_wanted:     Max number of jobs to return
        experience_levels:  List of levels to filter — ["entry", "associate"] by default
                            entry=0-2yr, associate=2-5yr, mid_senior=5yr+
        fetch_descriptions: If True, make a second API call per job to get full description
                            (needed for scoring, but adds 1-2 seconds per job)
        sleep_between_pages: Seconds to wait between page fetches (rate limit protection)

    Returns:
        List of job dicts with fields: site, title, company, location, job_url,
        date_posted, description
    """
    if experience_levels is None:
        experience_levels = ["entry", "associate"]  # 0-5 years by default

    f_tpr   = hours_to_f_tpr(hours_old)
    f_e     = ",".join(EXPERIENCE_LEVELS[lvl] for lvl in experience_levels if lvl in EXPERIENCE_LEVELS)
    cutoff  = datetime.now(timezone.utc) - timedelta(hours=hours_old)

    all_jobs: list[dict] = []
    start     = 0
    page      = 0
    max_pages = max(1, (results_wanted // 25) + 2)   # fetch a couple extra pages as buffer

    logger.info(f"LinkedIn guest API: '{search_term}' in '{location}' | f_TPR={f_tpr} | f_E={f_e}")

    while len(all_jobs) < results_wanted and page < max_pages:
        params: dict = {
            "keywords": search_term,
            "location": location,
            "f_TPR":    f_tpr,
            "start":    start,
        }
        if f_e:
            params["f_E"] = f_e

        try:
            resp = requests.get(
                GUEST_SEARCH_URL,
                params=params,
                headers=_get_headers(page),
                timeout=15,
            )

            if resp.status_code == 429:
                logger.warning("LinkedIn guest API: rate limited (429). Stopping early.")
                break
            if resp.status_code != 200:
                logger.warning(f"LinkedIn guest API returned {resp.status_code} on page {page}")
                break

            page_jobs = _parse_job_cards(resp.text)

            if not page_jobs:
                logger.debug(f"LinkedIn: no jobs on page {page}, stopping")
                break

            # Filter by actual date (f_TPR is best-effort on LinkedIn's side)
            # Normalize naive datetimes to UTC before comparing with timezone-aware cutoff
            filtered = []
            for job in page_jobs:
                posted = job.get("date_posted")
                if posted is None:
                    filtered.append(job)
                else:
                    if posted.tzinfo is None:
                        posted = posted.replace(tzinfo=timezone.utc)
                    if posted >= cutoff:
                        filtered.append(job)

            all_jobs.extend(filtered)
            logger.debug(f"LinkedIn page {page}: {len(page_jobs)} raw, {len(filtered)} after date filter")

        except requests.Timeout:
            logger.warning(f"LinkedIn guest API timed out on page {page}")
            break
        except requests.RequestException as e:
            logger.error(f"LinkedIn guest API request failed: {e}")
            break

        start += 25
        page  += 1

        # Polite delay between page fetches
        if page < max_pages and len(all_jobs) < results_wanted:
            time.sleep(sleep_between_pages)

    all_jobs = all_jobs[:results_wanted]

    # Fetch descriptions (second API call per job — needed for LLM scoring)
    if fetch_descriptions and all_jobs:
        logger.info(f"Fetching descriptions for {len(all_jobs)} LinkedIn jobs...")
        for i, job in enumerate(all_jobs):
            if job.get("linkedin_id"):
                job["description"] = _fetch_description(job["linkedin_id"], agent_index=i)
                time.sleep(0.5)  # brief pause between description fetches

    logger.info(f"LinkedIn guest API: returned {len(all_jobs)} jobs for '{search_term}'")
    return all_jobs
