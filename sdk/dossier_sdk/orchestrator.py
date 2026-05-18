"""Pure pipeline orchestration functions.

Extracted from run_dossier.py (M2). Each stage is a function returning a RunResult
(plus the list of jobs where downstream stages need them). No CLI/argparse here —
that stays in run_dossier.py. The FastAPI backend will import these directly.

All functions are intentionally Phase A: plain functions, blocking I/O, no asyncio.
Asyncification is deferred to Phase C (M4+) once worker concurrency proves needed.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    """One stage's outcome. Maps 1:1 onto a future pipeline_runs row."""
    status: str                       # "completed" | "failed"
    count: int = 0                    # jobs / companies / contacts produced
    duration_s: float = 0.0
    error: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


# Indirection layer so tests can patch the agent imports without touching agent modules.
def _discovery_agent_run(hours_old: int, min_score: int) -> list[dict]:
    from dossier_sdk.agents.job_discovery import run as _r
    return _r(hours_old=hours_old, min_score=min_score) or []


def _watchlist_agent_run(min_score: int, location: str) -> list[dict]:
    from dossier_sdk.agents.watchlist_agent import run as _r
    return _r(min_score=min_score, location=location) or []


def _company_intel_run(jobs: list[dict], min_score: int) -> list[dict]:
    from dossier_sdk.agents.company_intel import run as _r
    return _r(jobs, min_score=min_score) or []


def _gap_analysis_run(force: bool, min_score: int) -> dict:
    from dossier_sdk.agents.gap_analysis import run as _r
    return _r(force=force, min_score=min_score) or {}


def _market_intel_run() -> list[dict]:
    from dossier_sdk.agents.market_intel_agent import run as _r
    return _r() or []


def _referral_finder_run(job_id: str, skip_csv: bool = False) -> list[dict]:
    from dossier_sdk.agents.referral_finder import run_referral_finder as _r
    return _r(job_id, skip_csv=skip_csv) or []


def run_discovery(*, hours_old: int, min_score: int) -> tuple[RunResult, list[dict]]:
    """Run the discovery agent. Returns (RunResult, jobs)."""
    t0 = time.monotonic()
    try:
        jobs = _discovery_agent_run(hours_old=hours_old, min_score=min_score)
        return RunResult(
            status="completed", count=len(jobs), duration_s=time.monotonic() - t0,
        ), jobs
    except Exception as exc:
        logger.exception("discovery failed")
        return RunResult(
            status="failed", count=0, duration_s=time.monotonic() - t0, error=str(exc),
        ), []


def run_watchlist(*, min_score: int, location: str) -> tuple[RunResult, list[dict]]:
    """Run watchlist scrape. Returns (RunResult, jobs)."""
    t0 = time.monotonic()
    try:
        jobs = _watchlist_agent_run(min_score=min_score, location=location)
        return RunResult(
            status="completed", count=len(jobs), duration_s=time.monotonic() - t0,
        ), jobs
    except Exception as exc:
        logger.exception("watchlist failed")
        return RunResult(
            status="failed", count=0, duration_s=time.monotonic() - t0, error=str(exc),
        ), []


def run_company_intel(jobs: list[dict], *, min_score: int) -> RunResult:
    """Research companies for jobs scoring >= min_score."""
    t0 = time.monotonic()
    try:
        results = _company_intel_run(jobs, min_score=min_score)
        return RunResult(
            status="completed", count=len(results), duration_s=time.monotonic() - t0,
        )
    except Exception as exc:
        logger.exception("company_intel failed")
        return RunResult(
            status="failed", count=0, duration_s=time.monotonic() - t0, error=str(exc),
        )


def run_gap_analysis(*, force: bool, min_score: int) -> RunResult:
    """Extract skills from new JDs."""
    t0 = time.monotonic()
    try:
        result = _gap_analysis_run(force=force, min_score=min_score)
        return RunResult(
            status="completed",
            count=int(result.get("new_extracted", 0)),
            duration_s=time.monotonic() - t0,
            extras=result,
        )
    except Exception as exc:
        logger.exception("gap_analysis failed")
        return RunResult(
            status="failed", count=0, duration_s=time.monotonic() - t0, error=str(exc),
        )


def run_market_intel() -> RunResult:
    """Discover new AI/ML startups from funding news."""
    t0 = time.monotonic()
    try:
        discovered = _market_intel_run()
        return RunResult(
            status="completed", count=len(discovered), duration_s=time.monotonic() - t0,
        )
    except Exception as exc:
        logger.exception("market_intel failed")
        return RunResult(
            status="failed", count=0, duration_s=time.monotonic() - t0, error=str(exc),
        )


def run_referrals(jobs: list[dict], *, min_score: int, artifacts_dir: Path) -> RunResult:
    """Run referral finder for high-score jobs that don't already have referrals.json."""
    t0 = time.monotonic()
    target_jobs = [
        j for j in jobs
        if j.get("score", 0) >= min_score
        and not (artifacts_dir / j["job_id"] / "referrals.json").exists()
    ]
    total = 0
    errors: list[str] = []
    try:
        for job in target_jobs:
            try:
                contacts = _referral_finder_run(job["job_id"])
                total += len(contacts)
            except Exception as exc:
                errors.append(f"{job['job_id']}: {exc}")
        return RunResult(
            status="completed",
            count=total,
            duration_s=time.monotonic() - t0,
            error="; ".join(errors) if errors else None,
            extras={"jobs_processed": len(target_jobs)},
        )
    except Exception as exc:
        logger.exception("referrals failed")
        return RunResult(
            status="failed", count=0, duration_s=time.monotonic() - t0, error=str(exc),
        )


def run_pipeline(
    *,
    mode: str = "full",
    hours: int = 24,
    min_score: int = 5,
    company_intel_score: int = 7,
    location: str = "India",
    with_referrals: bool = False,
    user: str = "shivang",
) -> dict:
    """Run a full pipeline. Returns a summary dict that mirrors what
    run_dossier.py previously wrote to last_orchestrator_run.json.

    Modes:
      full          — discovery + watchlist + company_intel + gap_analysis
      quick         — discovery + watchlist only
      urgent        — discovery (forced 24h) + watchlist
      company-intel — company_intel + gap_analysis only (reads last-run files)
      market-intel  — market_intel only
    """
    from dossier_sdk.config import Config

    Config(user=user)
    config = Config()
    data_dir = config.data_dir
    artifacts_dir = config.artifacts_dir

    if mode == "urgent":
        hours = 24

    do_market_intel  = mode == "market-intel"
    do_discovery     = mode in ("full", "quick", "urgent")
    do_watchlist     = mode in ("full", "quick", "urgent")
    do_company_intel = mode in ("full", "company-intel")
    do_gap           = mode in ("full", "company-intel")

    summary: dict[str, Any] = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "stages_run": [],
        "stage_errors": [],
        "discovery_jobs": 0,
        "watchlist_jobs": 0,
        "company_intel_companies": 0,
        "gap_analysis_processed": 0,
        "market_intel_found": 0,
        "referrals_found": 0,
        "total_seconds": 0.0,
    }

    pipeline_start = time.monotonic()
    discovery_jobs: list[dict] = []
    watchlist_jobs: list[dict] = []

    if do_market_intel:
        r = run_market_intel()
        if r.status == "completed":
            summary["stages_run"].append("market_intel")
            summary["market_intel_found"] = r.count
        else:
            summary["stage_errors"].append(f"market_intel: {r.error}")

    if do_discovery:
        r, discovery_jobs = run_discovery(hours_old=hours, min_score=min_score)
        if r.status == "completed":
            summary["stages_run"].append("discovery")
            summary["discovery_jobs"] = r.count
        else:
            summary["stage_errors"].append(f"discovery: {r.error}")

    if do_watchlist:
        r, watchlist_jobs = run_watchlist(min_score=min_score, location=location)
        if r.status == "completed":
            summary["stages_run"].append("watchlist")
            summary["watchlist_jobs"] = r.count
        else:
            summary["stage_errors"].append(f"watchlist: {r.error}")

    if do_company_intel:
        all_jobs = discovery_jobs + watchlist_jobs
        r = run_company_intel(all_jobs, min_score=company_intel_score)
        if r.status == "completed":
            summary["stages_run"].append("company_intel")
            summary["company_intel_companies"] = r.count
        else:
            summary["stage_errors"].append(f"company_intel: {r.error}")

    if do_gap:
        r = run_gap_analysis(force=False, min_score=min_score)
        if r.status == "completed":
            summary["stages_run"].append("gap_analysis")
            summary["gap_analysis_processed"] = r.count
        else:
            summary["stage_errors"].append(f"gap_analysis: {r.error}")

    if with_referrals:
        all_jobs = discovery_jobs + watchlist_jobs
        r = run_referrals(all_jobs, min_score=company_intel_score, artifacts_dir=artifacts_dir)
        if r.status == "completed":
            summary["stages_run"].append("referrals")
            summary["referrals_found"] = r.count
        else:
            summary["stage_errors"].append(f"referrals: {r.error}")

    # Silence unused-var lint; data_dir is reserved for future last_run_path writeback.
    _ = data_dir

    summary["total_seconds"] = round(time.monotonic() - pipeline_start, 1)
    return summary
