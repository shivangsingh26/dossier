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

RATE LIMITING STRATEGY:
  - requests.Session() reuses TCP connections and persists cookies (looks more like a browser)
  - Jitter on all sleeps: no robot-perfect intervals
  - 429 retry with exponential backoff: waits 30s → 60s → 120s before giving up
  - Parallel description fetching (5 workers): ~4x speedup, safe because each
    request hits a different URL and workers start with random jitter delays

Phase B: Session-based, parallel description fetching, retry on 429.
"""

import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

from dossier_sdk.core.logger import get_logger

logger = get_logger(__name__)

GUEST_SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
GUEST_DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

# Seconds to wait between 429 retries — exponential: 30s, 60s, 120s
_BACKOFF_SCHEDULE = [30, 60, 120]

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
                "description": "",   # Filled in by _fetch_descriptions_parallel()
            })

        except Exception as e:
            logger.debug(f"Failed to parse a LinkedIn job card: {e}")
            continue

    return jobs


def _fetch_description(job_id: str, session: requests.Session, agent_index: int = 0) -> str:
    """
    Fetch the full job description for a single LinkedIn job ID.
    Retries once on 429 after a short backoff. Returns empty string on failure.
    """
    if not job_id:
        return ""

    url = GUEST_DETAIL_URL.format(job_id=job_id)

    for attempt in range(2):  # one retry on 429
        try:
            resp = session.get(url, headers=_get_headers(agent_index), timeout=10)

            if resp.status_code == 429:
                if attempt == 0:
                    wait = random.uniform(15, 30)
                    logger.debug(f"Description fetch rate limited. Waiting {wait:.0f}s...")
                    time.sleep(wait)
                    continue
                return ""

            if resp.status_code != 200:
                return ""

            soup = BeautifulSoup(resp.text, "html.parser")
            desc_el = soup.find("div", class_=lambda c: c and "description" in (c or "").lower())
            if not desc_el:
                desc_el = soup.find("section", class_=lambda c: c and "description" in (c or "").lower())
            return desc_el.get_text(separator="\n", strip=True) if desc_el else ""

        except requests.Timeout:
            logger.debug(f"Description fetch timed out for job {job_id}")
            return ""
        except requests.RequestException as e:
            logger.debug(f"Description fetch failed for job {job_id}: {e}")
            return ""

    return ""


def _fetch_descriptions_parallel(
    jobs: list[dict],
    session: requests.Session,
    max_workers: int = 5,
) -> None:
    """
    Fetch descriptions for all jobs in parallel. Mutates jobs list in-place.

    WHY THREADPOOLEXECUTOR: description fetches are pure network I/O — each one
    waits 0.5-2s for LinkedIn to respond. Fetching 5 at a time (different URLs,
    different job pages) gives ~4x speedup with no extra detection risk. Workers
    start with a random jitter so requests don't all fire at the same millisecond.
    """
    def fetch_one(args: tuple) -> tuple[int, str]:
        index, job = args
        # Stagger by slot: spread requests 0.4s apart so the 3 workers don't all
        # fire within the same second (LinkedIn soft-throttles concurrent bursts).
        time.sleep((index % max_workers) * 0.4 + random.uniform(0.0, 0.2))
        desc = _fetch_description(job.get("linkedin_id", ""), session, agent_index=index)
        return index, desc

    logger.info(f"Fetching descriptions for {len(jobs)} LinkedIn jobs...")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(fetch_one, enumerate(jobs)))

    for index, desc in results:
        jobs[index]["description"] = desc


def scrape_linkedin_jobs(
    search_term: str,
    location: str,
    hours_old: int = 72,
    results_wanted: int = 25,
    experience_levels: list[str] | None = None,
    fetch_descriptions: bool = True,
    sleep_between_pages: float = 1.2,
    desc_workers: int = 3,
    company_id: str | None = None,
) -> list[dict]:
    """
    Scrape LinkedIn jobs using the public guest API.

    Args:
        search_term:        e.g. "Machine Learning Engineer" — pass "" for company-only search
        location:           e.g. "Bengaluru, India"
        hours_old:          Only return jobs posted within last N hours (24, 72, or 168+)
        results_wanted:     Max number of jobs to return
        experience_levels:  List of levels to filter — ["entry", "associate"] by default
                            entry=0-2yr, associate=2-5yr, mid_senior=5yr+
        fetch_descriptions: If True, fetch full descriptions in parallel (needed for scoring)
        sleep_between_pages: Base seconds between page fetches — actual sleep adds ±30% jitter
        company_id:         LinkedIn numeric company ID — when set, adds f_C= filter to
                            fetch jobs from that specific company (used by watchlist agent
                            to catch promoted listings that keyword search misses)

    Returns:
        List of job dicts with fields: site, title, company, location, job_url,
        date_posted, description
    """
    if experience_levels is None:
        experience_levels = ["entry", "associate"]  # 0-5 years by default

    f_tpr   = hours_to_f_tpr(hours_old)
    f_e     = ",".join(EXPERIENCE_LEVELS[lvl] for lvl in experience_levels if lvl in EXPERIENCE_LEVELS)
    cutoff  = datetime.now(timezone.utc) - timedelta(hours=hours_old)

    # Session reuse: TCP connection reuse + cookie persistence across requests.
    # This looks more like a real browser and is faster than creating a new
    # connection per request.
    session   = requests.Session()
    all_jobs: list[dict] = []
    start     = 0
    page      = 0
    max_pages = max(1, (results_wanted // 25) + 2)   # fetch a couple extra pages as buffer

    log_label = f"f_C={company_id}" if company_id else f"'{search_term}'"
    logger.info(f"LinkedIn guest API: {log_label} in '{location}' | f_TPR={f_tpr} | f_E={f_e}")

    while len(all_jobs) < results_wanted and page < max_pages:
        params: dict = {
            "keywords": search_term,
            "location": location,
            "f_TPR":    f_tpr,
            "start":    start,
        }
        if f_e:
            params["f_E"] = f_e
        if company_id:
            params["f_C"] = company_id

        page_jobs = None

        # Retry loop with exponential backoff on 429
        for attempt, backoff in enumerate([0] + _BACKOFF_SCHEDULE):
            if backoff:
                logger.warning(f"LinkedIn rate limited (429). Waiting {backoff}s before retry {attempt}/{len(_BACKOFF_SCHEDULE)}...")
                time.sleep(backoff)

            try:
                resp = session.get(
                    GUEST_SEARCH_URL,
                    params=params,
                    headers=_get_headers(page),
                    timeout=15,
                )

                if resp.status_code == 429:
                    continue  # trigger next backoff iteration

                if resp.status_code != 200:
                    logger.warning(f"LinkedIn guest API returned {resp.status_code} on page {page}")
                    page_jobs = []
                    break

                page_jobs = _parse_job_cards(resp.text)
                break  # success — exit retry loop

            except requests.Timeout:
                logger.warning(f"LinkedIn guest API timed out on page {page}")
                page_jobs = []
                break
            except requests.RequestException as e:
                logger.error(f"LinkedIn guest API request failed: {e}")
                page_jobs = []
                break
        else:
            # Exhausted all retries on 429
            logger.warning(f"LinkedIn guest API: gave up after {len(_BACKOFF_SCHEDULE)} retries on page {page}")
            break

        if page_jobs is None or not page_jobs:
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

        start += 25
        page  += 1

        # Jitter on inter-page sleep: ±40% of the base value so requests
        # don't arrive at perfectly regular intervals (a bot detection signal)
        if page < max_pages and len(all_jobs) < results_wanted:
            jitter = sleep_between_pages * random.uniform(0.6, 1.4)
            time.sleep(jitter)

    all_jobs = all_jobs[:results_wanted]

    # Parallel description fetching — ~4x faster than sequential
    if fetch_descriptions and all_jobs:
        _fetch_descriptions_parallel(all_jobs, session, max_workers=desc_workers)

    logger.info(f"LinkedIn guest API: returned {len(all_jobs)} jobs for '{search_term}'")
    return all_jobs
