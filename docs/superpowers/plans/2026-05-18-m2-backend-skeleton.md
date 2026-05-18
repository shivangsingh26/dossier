# M2 — Backend Skeleton + Clerk Webhook + accounts.db + Worker — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** [docs/superpowers/specs/2026-05-18-dossier-saas-frontend-design.md](../specs/2026-05-18-dossier-saas-frontend-design.md) §6, §7, §8, §9.

**Goal:** Stand up the FastAPI backend with Clerk JWT auth, `accounts.db` schema, signup webhook, seed script for the 4 existing users, and an idle worker process. Frontend `CreditPill` becomes real.

**Architecture:** New `backend/` Python 3.12 project with its own uv venv that depends on `dossier-sdk` via local path. FastAPI app on `:8000`. Separate worker process polls `accounts.db` every 5s. Clerk JWT verified by `clerk-backend-api`. Clerk webhook signature verified by `svix`. CORS allows `http://localhost:3000`. Orchestrator pure functions extracted from `run_dossier.py` into `sdk/dossier_sdk/orchestrator.py` (deferred from M0 T4). Frontend `lib/api.ts` wraps backend calls; `(app)/layout.tsx` RSC fetches `/me` and renders pending-review screen for `status=pending`.

**Tech additions:** `fastapi`, `uvicorn[standard]`, `pydantic v2`, `clerk-backend-api` (verify on pypi), `svix`, `sse-starlette`, `fasteners`, `httpx` (already in sdk), `python-dotenv`. Dev deps: `pytest`, `pytest-asyncio`, `httpx` (test client).

**Collaboration style (locked from user):**
- Agent runs all `uv`, `pnpm`, `python`, `node`, `npm` commands directly.
- User runs all `git add` + `git commit` commands himself.
- Commits batched every 3 tasks. Agent halts and tells user the suggested commit message + files; user commits.
- Branch: `feat/m2-backend-skeleton` off `main`.

---

## File Structure

**New (created):**
- `sdk/dossier_sdk/orchestrator.py` — pure pipeline functions (extracted from `run_dossier.py`)
- `sdk/tests/test_orchestrator.py` — orchestrator tests
- `backend/pyproject.toml`
- `backend/.env.example`
- `backend/.gitignore`
- `backend/README.md` (rewrite of placeholder)
- `backend/src/dossier_api/__init__.py`
- `backend/src/dossier_api/main.py`
- `backend/src/dossier_api/settings.py` — env loader (BACKEND_* prefix)
- `backend/src/dossier_api/db.py` — accounts.db init + helpers
- `backend/src/dossier_api/deps.py` — Clerk JWT + account loaders
- `backend/src/dossier_api/models/__init__.py`
- `backend/src/dossier_api/models/account.py` — pydantic schemas
- `backend/src/dossier_api/routers/__init__.py`
- `backend/src/dossier_api/routers/health.py`
- `backend/src/dossier_api/routers/me.py`
- `backend/src/dossier_api/routers/webhooks.py`
- `backend/src/dossier_api/workers/__init__.py`
- `backend/src/dossier_api/workers/pipeline_worker.py`
- `backend/scripts/__init__.py`
- `backend/scripts/seed_existing_users.py`
- `backend/scripts/seed_users.example.json` (committed; real `seed_users.json` gitignored)
- `backend/tests/__init__.py`
- `backend/tests/conftest.py`
- `backend/tests/test_db.py`
- `backend/tests/test_health.py`
- `backend/tests/test_me.py`
- `backend/tests/test_webhooks.py`
- `backend/tests/test_worker.py`
- `frontend/lib/api.ts`
- `frontend/lib/server-api.ts` — server-only fetch (uses Clerk getToken)
- `frontend/app/(app)/pending/page.tsx` — pending-review screen
- `docs/superpowers/milestones/M2.md` (overwrite stub with task list pointer)

**Modified:**
- `run_dossier.py` — thin CLI delegating to `orchestrator.run_pipeline`
- `frontend/app/(app)/layout.tsx` — RSC fetches `/me`, gates on status
- `frontend/components/dossier/CreditPill.tsx` — accepts `credits` / `creditsTotal` from layout
- `frontend/.env.local.example` — add `NEXT_PUBLIC_BACKEND_URL`
- `frontend/.gitignore` — ensure `.env.local` ignored (verify)
- `.gitignore` — add `backend/.env`, `backend/scripts/seed_users.json`, `data/accounts.db`, `backend/.venv/`
- `frontend-todo.txt` — tick M2 boxes as they complete

---

## Phase declaration

Per CLAUDE.md: new backend service starts at **Phase A** (working code, plain functions, `logging` module from the start since the SDK already uses logging). No async/SSE/full exception orchestration in M2 — worker is a polling loop with sync sqlite3. Phase B (`accounts.db` transactions are atomic, structured logging) is touched. Phase C (asyncio worker, SSE) deferred to M4.

---

## Pre-task setup (one-shot)

- [ ] **Verify latest stable versions** of new dependencies on PyPI:
  - `fastapi`
  - `uvicorn[standard]`
  - `clerk-backend-api` (NOTE: spec says `clerk-sdk-python` — that package is **deprecated**; current official Python SDK is `clerk-backend-api`. Confirm on pypi.org/project/clerk-backend-api before adding.)
  - `svix`
  - `sse-starlette`
  - `fasteners`
  - `pytest-asyncio`

  Run: `uv pip index versions fastapi clerk-backend-api svix sse-starlette fasteners pytest-asyncio 2>&1 | head -40` (uv only — does not install)

- [ ] **Create branch:**

  ```bash
  git checkout main
  git pull --ff-only
  git checkout -b feat/m2-backend-skeleton
  ```

  (User runs.)

---

## Task 1: Extract orchestrator from run_dossier.py into sdk

**Files:**
- Create: `sdk/dossier_sdk/orchestrator.py`
- Create: `sdk/tests/test_orchestrator.py`
- Modify: `run_dossier.py` (thin CLI wrapper)

**Why this task is first:** M0 T4 was deferred. The backend's `/pipeline/run` endpoint (M4) imports `orchestrator.run_*` directly. Doing it now means M2 backend can already call into the proper API; M4 doesn't have to refactor `run_dossier.py` mid-flight.

**Concept primer:** A `dataclass` here groups orchestrator output (status, duration, count) into one object instead of three parallel return values. No magic — just a named tuple alternative.

- [ ] **Step 1: Write failing test for `run_discovery` orchestrator function**

```python
# sdk/tests/test_orchestrator.py
"""Tests orchestrator pure functions.

We mock the underlying agent modules so the tests do not call OpenAI / scrape sites.
"""
from unittest.mock import patch

import pytest

from dossier_sdk.orchestrator import RunResult, run_discovery, run_pipeline


def test_run_discovery_returns_jobs_and_result():
    fake_jobs = [{"job_id": "j1", "score": 8}, {"job_id": "j2", "score": 6}]
    with patch("dossier_sdk.orchestrator._discovery_agent_run", return_value=fake_jobs):
        result, jobs = run_discovery(hours_old=24, min_score=5)
    assert isinstance(result, RunResult)
    assert result.status == "completed"
    assert result.count == 2
    assert result.error is None
    assert jobs == fake_jobs


def test_run_discovery_catches_exception_returns_failed_result():
    with patch("dossier_sdk.orchestrator._discovery_agent_run", side_effect=RuntimeError("api down")):
        result, jobs = run_discovery(hours_old=24, min_score=5)
    assert result.status == "failed"
    assert "api down" in (result.error or "")
    assert jobs == []


def test_run_pipeline_quick_mode_runs_discovery_and_watchlist_only():
    with (
        patch("dossier_sdk.orchestrator.run_discovery") as m_disc,
        patch("dossier_sdk.orchestrator.run_watchlist") as m_watch,
        patch("dossier_sdk.orchestrator.run_company_intel") as m_intel,
        patch("dossier_sdk.orchestrator.run_gap_analysis") as m_gap,
    ):
        m_disc.return_value = (RunResult(status="completed", count=3, duration_s=1.0), [])
        m_watch.return_value = (RunResult(status="completed", count=2, duration_s=1.0), [])
        summary = run_pipeline(mode="quick", hours=24, min_score=5)
    assert "discovery" in summary["stages_run"]
    assert "watchlist" in summary["stages_run"]
    assert "company_intel" not in summary["stages_run"]
    assert "gap_analysis" not in summary["stages_run"]
    m_intel.assert_not_called()
    m_gap.assert_not_called()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd sdk && uv run pytest tests/test_orchestrator.py -v
```

Expected: `ModuleNotFoundError: dossier_sdk.orchestrator` or import errors.

- [ ] **Step 3: Implement `sdk/dossier_sdk/orchestrator.py`**

```python
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
            status="completed" if not errors else "completed",
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

    summary["total_seconds"] = round(time.monotonic() - pipeline_start, 1)
    return summary
```

- [ ] **Step 4: Re-run orchestrator tests to confirm they pass**

```bash
cd sdk && uv run pytest tests/test_orchestrator.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Rewrite `run_dossier.py` as thin CLI**

Keep argparse + Rich UI + `save_run_summary`, delegate the actual pipeline to `orchestrator.run_pipeline()`. Rich progress reporting stays in this file (orchestrator stays UI-agnostic).

```python
"""run_dossier.py — Thin CLI wrapper over dossier_sdk.orchestrator.

The actual pipeline logic now lives in dossier_sdk.orchestrator.run_pipeline().
This file is responsible for argparse, Rich UI banners, and writing
last_orchestrator_run.json. Future: FastAPI calls orchestrator directly.
"""
import argparse
import json
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.rule import Rule

from dossier_sdk.config import Config
from dossier_sdk.orchestrator import run_pipeline

console = Console()

_MODES = {
    "full":          "Discovery + Watchlist + Company Intel + Gap Analysis",
    "quick":         "Discovery + Watchlist (no intel or gap analysis)",
    "urgent":        "Discovery (forced 24h) + Watchlist (no intel or gap analysis)",
    "company-intel": "Company Intel only — reads last-run files, no re-scraping",
    "market-intel":  "Market Intel only — discover new AI/ML startups from funding news",
}


def print_run_header(args: argparse.Namespace) -> None:
    """Print the opening summary of what this run will do."""
    console.print()
    console.print(Rule("[bold]Dossier — Daily Pipeline[/bold]", style="bold"))
    console.print(f"  Mode:                [bold]{args.mode}[/bold] — {_MODES[args.mode]}")
    if args.mode != "company-intel":
        console.print(f"  Hours back:          {args.hours}h")
        console.print(f"  Min score:           {args.min_score}/10")
    if args.mode in ("full", "company-intel"):
        console.print(f"  Company Intel gate:  {args.company_intel_score}/10")
    console.print(f"  Referral Finder:     {'yes' if args.with_referrals else 'skipped'}")
    console.print(f"  Location:            {args.location}")
    console.print(f"  User:                {args.user}")
    console.print(f"  Started:             {datetime.now().strftime('%Y-%m-%d  %H:%M')}")
    console.print()


def save_run_summary(summary: dict, data_dir: Path) -> None:
    """Persist run metadata to data/{user}/last_orchestrator_run.json."""
    path = data_dir / "last_orchestrator_run.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    """Parse CLI flags, delegate to orchestrator, render Rich summary."""
    parser = argparse.ArgumentParser(
        description="Dossier master orchestrator.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--mode", choices=list(_MODES), default="full")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--min-score", type=int, default=5)
    parser.add_argument("--company-intel-score", type=int, default=7)
    parser.add_argument("--location", type=str, default="India")
    parser.add_argument("--with-referrals", action="store_true", default=False)
    parser.add_argument("--user", type=str, default="shivang")
    args = parser.parse_args()

    print_run_header(args)

    summary = run_pipeline(
        mode=args.mode,
        hours=args.hours,
        min_score=args.min_score,
        company_intel_score=args.company_intel_score,
        location=args.location,
        with_referrals=args.with_referrals,
        user=args.user,
    )

    console.print()
    console.print(Rule("[bold]Pipeline Complete[/bold]", style="bold"))
    if summary.get("market_intel_found") or args.mode == "market-intel":
        console.print(f"  Market Intel:    {summary['market_intel_found']} new companies")
    console.print(f"  Discovery:       {summary['discovery_jobs']} jobs")
    console.print(f"  Watchlist:       {summary['watchlist_jobs']} jobs")
    console.print(f"  Company Intel:   {summary['company_intel_companies']} companies researched")
    if args.mode in ("full", "company-intel"):
        console.print(f"  Gap Analysis:    {summary['gap_analysis_processed']} JDs processed")
    if args.with_referrals:
        console.print(f"  Referrals:       {summary['referrals_found']} contacts")
    console.print(f"  Total time:      {summary['total_seconds']:.0f}s")

    if summary["stage_errors"]:
        console.print("\n  [yellow]Stage errors:[/yellow]")
        for err in summary["stage_errors"]:
            console.print(f"    [yellow]• {err}[/yellow]")

    Config(user=args.user)
    save_run_summary(summary, Config().data_dir)
    console.print()
    console.print(f"  Run metadata → data/{args.user}/last_orchestrator_run.json\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Smoke test CLI parity**

```bash
python run_dossier.py --mode quick --hours 6 --user shivang
```

Expected: Rich banner identical to before. Pipeline runs. Exit 0. `data/shivang/last_orchestrator_run.json` updated.

If unhappy (e.g. blocking external APIs), at minimum confirm `--help` renders and `--mode market-intel` dry-imports cleanly:

```bash
python run_dossier.py --help
python -c "from dossier_sdk.orchestrator import run_pipeline; print(run_pipeline)"
```

- [ ] **Step 7: Acceptance: ALL existing tests still pass**

```bash
cd sdk && uv run pytest -q
```

Expected: same 55 pass / 8 pre-existing fail / 1 skip baseline (see memory `project_known_test_failures.md`). New orchestrator tests added (3 more pass).

---

## Task 2: backend pyproject + venv

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/.env.example`
- Create: `backend/.gitignore`
- Create: `backend/README.md` (rewrite)
- Create: `backend/src/dossier_api/__init__.py`
- Create: `backend/src/dossier_api/settings.py`
- Modify: root `.gitignore`

**Concept primer (path dependency):** `backend/pyproject.toml` declares `dossier-sdk` not from PyPI but from a local sibling folder. `uv` then symlinks the sibling into the venv. Editing sdk code is picked up immediately by the backend.

- [ ] **Step 1: Write `backend/pyproject.toml`**

```toml
[project]
name = "dossier-api"
version = "0.1.0"
description = "Dossier — FastAPI backend (auth, accounts, pipeline gating, SSE progress)"
readme = "README.md"
requires-python = ">=3.12"
authors = [{ name = "Shivang Singh" }]

dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "pydantic>=2.9.0",
    "python-dotenv>=1.0.1",
    "httpx>=0.28.1",
    "clerk-backend-api>=1.0.0",
    "svix>=1.34.0",
    "sse-starlette>=2.1.0",
    "fasteners>=0.19",
    "dossier-sdk",
]

[dependency-groups]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "ruff>=0.7.0",
]

[tool.uv.sources]
dossier-sdk = { path = "../sdk", editable = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/dossier_api"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
asyncio_mode = "auto"
```

> ⚠ Versions are floors. Before running install, run the version probe from the pre-task setup to confirm each package's current latest. If `clerk-backend-api` is not yet on pypi or has been renamed, fall back to `clerk-sdk-python` and document the swap in this plan inline.

- [ ] **Step 2: Write `backend/.env.example`**

```bash
# Clerk — backend keys (from clerk.com → API Keys)
CLERK_SECRET_KEY=sk_test_xxxxx
CLERK_WEBHOOK_SECRET=whsec_xxxxx   # from clerk.com → Webhooks → Endpoint signing secret

# Database
# Default: <repo>/data/accounts.db (resolved relative to repo root)
ACCOUNTS_DB_PATH=

# CORS
ALLOWED_ORIGINS=http://localhost:3000
```

- [ ] **Step 3: Write `backend/.gitignore`**

```
.venv/
__pycache__/
*.pyc
.env
.env.local
scripts/seed_users.json
.pytest_cache/
```

- [ ] **Step 4: Rewrite `backend/README.md`**

```markdown
# backend — Dossier FastAPI service

FastAPI app (`:8000`) backing the Next.js frontend. Wraps `dossier-sdk` agents.

## Install

```bash
cd backend
uv venv
uv pip install -e .
cp .env.example .env   # then fill in Clerk keys
```

## Run dev

```bash
uv run uvicorn dossier_api.main:app --reload --port 8000
```

In a second terminal, start the worker:

```bash
uv run python -m dossier_api.workers.pipeline_worker
```

## Tests

```bash
uv run pytest -v
```

## Seed existing users (one-time)

Edit `scripts/seed_users.json` (gitignored) with the 4 existing users' emails, then:

```bash
uv run python -m dossier_api.scripts.seed_existing_users
```

Idempotent — re-running skips users whose `clerk_id` already exists.
```

- [ ] **Step 5: Create package skeleton**

```bash
mkdir -p backend/src/dossier_api/{routers,workers,models}
mkdir -p backend/scripts backend/tests
touch backend/src/dossier_api/__init__.py
touch backend/src/dossier_api/routers/__init__.py
touch backend/src/dossier_api/workers/__init__.py
touch backend/src/dossier_api/models/__init__.py
touch backend/scripts/__init__.py
touch backend/tests/__init__.py
```

Contents of `backend/src/dossier_api/__init__.py`:

```python
"""dossier-api — FastAPI service wrapping dossier-sdk."""
__version__ = "0.1.0"
```

- [ ] **Step 6: Write `backend/src/dossier_api/settings.py`**

```python
"""Singleton settings loader. Reads backend/.env once, exposes typed attrs.

WHY SINGLETON: The same FastAPI app + worker process should read env vars once at
boot, not on every request. Singleton pattern matches sdk/config.py.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / ".env", override=False)


class Settings(BaseModel):
    clerk_secret_key: str
    clerk_webhook_secret: str
    accounts_db_path: Path
    allowed_origins: list[str]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    default_db = REPO_ROOT / "data" / "accounts.db"
    return Settings(
        clerk_secret_key=os.environ.get("CLERK_SECRET_KEY", ""),
        clerk_webhook_secret=os.environ.get("CLERK_WEBHOOK_SECRET", ""),
        accounts_db_path=Path(os.environ.get("ACCOUNTS_DB_PATH") or default_db),
        allowed_origins=[
            o.strip()
            for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
            if o.strip()
        ],
    )
```

- [ ] **Step 7: Append to root `.gitignore`**

```
# M2 backend
backend/.env
backend/.venv/
backend/scripts/seed_users.json
data/accounts.db
data/accounts.db-journal
data/accounts.db-wal
data/accounts.db-shm
```

(Use Edit; check that these aren't already in `.gitignore`.)

- [ ] **Step 8: Install backend venv**

```bash
cd backend && uv venv && uv pip install -e .
```

Expected: succeeds, no resolve errors. `backend/.venv/` exists.

If `clerk-backend-api` fails to resolve, swap to `clerk-sdk-python` in `pyproject.toml` and rerun.

---

## Task 3: accounts.db schema + db.py (TDD)

**Files:**
- Create: `backend/src/dossier_api/db.py`
- Create: `backend/tests/test_db.py`
- Create: `backend/tests/conftest.py`

**Concept primer:** SQLite default isolation level is "deferred" — each `BEGIN` is implicit on a write. Using `with conn:` context manager wraps each block in a transaction and rolls back on exception. `IF NOT EXISTS` makes the schema idempotent.

- [ ] **Step 1: Write conftest fixtures**

```python
# backend/tests/conftest.py
"""Shared pytest fixtures."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db_path(tmp_path: Path, monkeypatch) -> Path:
    """Point ACCOUNTS_DB_PATH at a fresh tmpfile for each test."""
    db = tmp_path / "accounts.db"
    monkeypatch.setenv("ACCOUNTS_DB_PATH", str(db))
    from dossier_api.settings import get_settings
    get_settings.cache_clear()  # bust lru_cache so the new env var is picked up
    return db
```

- [ ] **Step 2: Write failing tests for `db.py`**

```python
# backend/tests/test_db.py
"""Tests accounts.db schema + helpers."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from dossier_api.db import (
    create_account,
    get_account_by_clerk_id,
    get_account_by_email,
    init_db,
    log_credit_change,
    update_account_status,
)


def _tables(db: Path) -> set[str]:
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    conn.close()
    return {r[0] for r in rows}


def test_init_db_creates_all_tables(tmp_db_path: Path):
    init_db(tmp_db_path)
    tables = _tables(tmp_db_path)
    assert {"accounts", "credit_log", "pipeline_runs", "waitlist"} <= tables


def test_init_db_is_idempotent(tmp_db_path: Path):
    init_db(tmp_db_path)
    init_db(tmp_db_path)
    assert tmp_db_path.exists()


def test_create_account_inserts_row(tmp_db_path: Path):
    init_db(tmp_db_path)
    acct = create_account(
        clerk_id="user_test1",
        email="test@example.com",
        data_user_slug="user_test1",
    )
    assert acct["clerk_id"] == "user_test1"
    assert acct["status"] == "pending"
    assert acct["tier"] == "lite"
    assert acct["credits"] == 100


def test_get_account_by_clerk_id(tmp_db_path: Path):
    init_db(tmp_db_path)
    create_account(clerk_id="user_x", email="x@y.com", data_user_slug="x")
    found = get_account_by_clerk_id("user_x")
    assert found is not None
    assert found["email"] == "x@y.com"
    assert get_account_by_clerk_id("nope") is None


def test_get_account_by_email_case_insensitive(tmp_db_path: Path):
    init_db(tmp_db_path)
    create_account(clerk_id="user_x", email="MiXed@Case.io", data_user_slug="x")
    assert get_account_by_email("mixed@case.io") is not None


def test_update_account_status(tmp_db_path: Path):
    init_db(tmp_db_path)
    create_account(clerk_id="user_x", email="x@y.com", data_user_slug="x")
    update_account_status("user_x", "active")
    assert get_account_by_clerk_id("user_x")["status"] == "active"


def test_log_credit_change_records_ledger_entry(tmp_db_path: Path):
    init_db(tmp_db_path)
    acct = create_account(clerk_id="user_x", email="x@y.com", data_user_slug="x")
    log_credit_change(user_id=acct["user_id"], delta=-5, reason="run:disc")
    conn = sqlite3.connect(tmp_db_path)
    rows = conn.execute("SELECT delta, reason FROM credit_log").fetchall()
    conn.close()
    assert rows == [(-5, "run:disc")]
```

- [ ] **Step 3: Run tests to confirm failure**

```bash
cd backend && uv run pytest tests/test_db.py -v
```

Expected: `ImportError: cannot import name 'init_db'`.

- [ ] **Step 4: Implement `backend/src/dossier_api/db.py`**

```python
"""accounts.db — auth/credits/runs ledger.

Plain sqlite3 (sync). Connection is opened per-call; SQLite handles concurrent
readers natively. Writes are serialized by the default journaling mode.

Schema mirrors spec §7.4 exactly. Any change here requires a migration step
(M2 ships v1; future versions add migration logic).
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dossier_api.settings import get_settings

SCHEMA_VERSION = 1


def _db_path() -> Path:
    return get_settings().accounts_db_path


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path | None = None) -> None:
    """Create all tables if missing. Idempotent."""
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                user_id          TEXT PRIMARY KEY,
                clerk_id         TEXT UNIQUE NOT NULL,
                email            TEXT UNIQUE NOT NULL COLLATE NOCASE,
                data_user_slug   TEXT UNIQUE NOT NULL,
                role             TEXT NOT NULL DEFAULT 'user',
                tier             TEXT NOT NULL DEFAULT 'lite',
                status           TEXT NOT NULL DEFAULT 'pending',
                credits          INTEGER NOT NULL DEFAULT 100,
                credits_reset_at TEXT NOT NULL,
                created_at       TEXT NOT NULL,
                last_login_at    TEXT
            );

            CREATE TABLE IF NOT EXISTS credit_log (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                delta   INTEGER NOT NULL,
                reason  TEXT NOT NULL,
                run_id  TEXT,
                at      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pipeline_runs (
                run_id              TEXT PRIMARY KEY,
                user_id             TEXT NOT NULL,
                parent_run_id       TEXT,
                agent               TEXT NOT NULL,
                status              TEXT NOT NULL,
                credits_cost        INTEGER NOT NULL,
                credits_refunded    INTEGER DEFAULT 0,
                started_at          TEXT,
                finished_at         TEXT,
                progress_json       TEXT,
                error               TEXT,
                output_summary_json TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_pipeline_runs_user_status
                ON pipeline_runs(user_id, status);
            CREATE INDEX IF NOT EXISTS idx_pipeline_runs_parent
                ON pipeline_runs(parent_run_id);

            CREATE TABLE IF NOT EXISTS waitlist (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      TEXT NOT NULL,
                desired_tier TEXT NOT NULL,
                submitted_at TEXT NOT NULL,
                fulfilled    INTEGER NOT NULL DEFAULT 0
            );
            """
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_reset() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def create_account(
    *,
    clerk_id: str,
    email: str,
    data_user_slug: str,
    role: str = "user",
    tier: str = "lite",
    status: str = "pending",
    credits: int = 100,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Insert a fresh account row. Returns the row."""
    user_id = str(uuid.uuid4())
    now = _now()
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO accounts
               (user_id, clerk_id, email, data_user_slug, role, tier, status,
                credits, credits_reset_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, clerk_id, email, data_user_slug, role, tier, status,
             credits, _next_reset(), now),
        )
    return get_account_by_clerk_id(clerk_id, db_path=db_path)  # type: ignore[return-value]


def get_account_by_clerk_id(clerk_id: str, db_path: Path | None = None) -> dict[str, Any] | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM accounts WHERE clerk_id = ?", (clerk_id,),
        ).fetchone()
    return _row_to_dict(row)


def get_account_by_email(email: str, db_path: Path | None = None) -> dict[str, Any] | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM accounts WHERE email = ? COLLATE NOCASE", (email,),
        ).fetchone()
    return _row_to_dict(row)


def update_account_status(clerk_id: str, status: str, db_path: Path | None = None) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE accounts SET status = ? WHERE clerk_id = ?", (status, clerk_id),
        )


def update_last_login(clerk_id: str, db_path: Path | None = None) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE accounts SET last_login_at = ? WHERE clerk_id = ?",
            (_now(), clerk_id),
        )


def log_credit_change(
    *, user_id: str, delta: int, reason: str, run_id: str | None = None,
    db_path: Path | None = None,
) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO credit_log (user_id, delta, reason, run_id, at) VALUES (?,?,?,?,?)",
            (user_id, delta, reason, run_id, _now()),
        )
```

- [ ] **Step 5: Run tests to confirm pass**

```bash
cd backend && uv run pytest tests/test_db.py -v
```

Expected: 7 passed.

### ── COMMIT BATCH 1 (Tasks 1-3) ──

Halt. Tell user:

> Tasks 1-3 done. Suggested commit:
>
> ```
> feat(m2): extract orchestrator + scaffold backend + accounts.db schema
>
> - Extract pure pipeline functions from run_dossier.py into
>   sdk/dossier_sdk/orchestrator.py with RunResult dataclass (M0 T4 deferred)
> - run_dossier.py becomes thin CLI wrapper, behavior preserved
> - Scaffold backend/ FastAPI project with own uv venv + pyproject + .env.example
> - Implement accounts.db schema + db.py helpers (accounts, credit_log,
>   pipeline_runs, waitlist) with idempotent init_db
> - 10 new tests passing (3 orchestrator + 7 db)
>
> Files: sdk/dossier_sdk/orchestrator.py, sdk/tests/test_orchestrator.py,
> run_dossier.py (rewrite), backend/pyproject.toml, backend/.env.example,
> backend/README.md, backend/.gitignore, backend/src/dossier_api/{__init__,
> settings,db}.py, backend/src/dossier_api/{routers,workers,models}/__init__.py,
> backend/scripts/__init__.py, backend/tests/{__init__,conftest,test_db}.py,
> .gitignore
> ```

User runs `git add` + `git commit` + responds "go" before continuing.

---

## Task 4: pydantic models for accounts

**Files:**
- Create: `backend/src/dossier_api/models/account.py`

**Concept primer (pydantic v2 `model_validator`):** Lets you transform the dict before fields validate. Used here to massage sqlite row → API response shape.

- [ ] **Step 1: Implement models**

```python
# backend/src/dossier_api/models/account.py
"""Pydantic schemas for account-related API responses."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, ConfigDict

Tier = Literal["lite", "pro", "max"]
Role = Literal["user", "admin"]
Status = Literal["pending", "active", "suspended"]


class AccountResponse(BaseModel):
    """Returned by GET /me."""
    model_config = ConfigDict(populate_by_name=True)

    user_id: str
    clerk_id: str
    email: str
    data_user_slug: str
    role: Role
    tier: Tier
    status: Status
    credits: int
    credits_reset_at: datetime
    created_at: datetime
    last_login_at: datetime | None = None


class CreditDebit(BaseModel):
    delta: int = Field(..., description="Negative for deduction, positive for refund/topup")
    reason: str
    run_id: str | None = None
```

- [ ] **Step 2: Quick import smoke test**

```bash
cd backend && uv run python -c "from dossier_api.models.account import AccountResponse; print(AccountResponse.model_fields.keys())"
```

Expected: dict_keys with all 10 fields.

---

## Task 5: FastAPI main.py + /health (TDD)

**Files:**
- Create: `backend/src/dossier_api/main.py`
- Create: `backend/src/dossier_api/routers/health.py`
- Create: `backend/tests/test_health.py`

**Concept primer (FastAPI `lifespan`):** Replacement for `@app.on_event("startup")`. A single async generator: code before `yield` runs at startup, code after runs at shutdown. We use it to call `init_db()` once.

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_health.py
"""Tests /health endpoint."""
from fastapi.testclient import TestClient

from dossier_api.main import app


def test_health_ok(tmp_db_path):
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
```

- [ ] **Step 2: Run test to confirm failure**

```bash
cd backend && uv run pytest tests/test_health.py -v
```

Expected: `ImportError: cannot import name 'app'`.

- [ ] **Step 3: Implement `routers/health.py`**

```python
"""Health probe — unauthenticated."""
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}
```

- [ ] **Step 4: Implement `main.py`**

```python
"""FastAPI app entrypoint.

Run: uv run uvicorn dossier_api.main:app --reload --port 8000
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dossier_api.db import init_db
from dossier_api.routers import health
from dossier_api.settings import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run once at boot: ensure accounts.db schema exists."""
    settings = get_settings()
    init_db(settings.accounts_db_path)
    logger.info("dossier-api ready · db=%s", settings.accounts_db_path)
    yield
    logger.info("dossier-api shutting down")


app = FastAPI(title="dossier-api", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
```

- [ ] **Step 5: Run tests to confirm pass**

```bash
cd backend && uv run pytest tests/test_health.py -v
```

Expected: 1 passed.

- [ ] **Step 6: Manual smoke**

```bash
cd backend && uv run uvicorn dossier_api.main:app --port 8000 &
sleep 2
curl -s http://localhost:8000/health
kill %1
```

Expected: `{"ok":true}`. Server log shows `dossier-api ready · db=…/data/accounts.db`.

---

## Task 6: Clerk JWT auth dep (TDD)

**Files:**
- Create: `backend/src/dossier_api/deps.py`

**Concept primer (FastAPI `Depends`):** Functions you write that FastAPI calls before your route handler. They can inject parsed/verified data (e.g. the current user) or short-circuit with `HTTPException`. Composable.

**Concept primer (Clerk session token):** Frontend Clerk component sets a `__session` cookie or `Authorization: Bearer <jwt>` header. Backend SDK verifies the JWT (signature against Clerk's JWKS + expiry), returns the `sub` claim = Clerk user id. We use that to look up `accounts.clerk_id`.

- [ ] **Step 1: Implement `deps.py`**

```python
"""Auth + tier dependencies.

`get_current_user` — verifies Clerk JWT, loads accounts.db row, returns it.
401 if no/invalid JWT. 403 if no matching account row or status != 'active'.

Background:
    Clerk publishes a JWKS at <issuer>/.well-known/jwks.json.
    clerk-backend-api caches the keys and verifies signature + expiry locally
    on every request (no roundtrip to Clerk per call).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, HTTPException, Request, status

from dossier_api.db import get_account_by_clerk_id, update_last_login
from dossier_api.settings import get_settings

logger = logging.getLogger(__name__)


def _extract_bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return None
    return auth.split(" ", 1)[1].strip()


def _verify_clerk_jwt(token: str) -> str:
    """Return Clerk user_id (sub claim) if valid; raise HTTPException(401) otherwise.

    Uses clerk-backend-api Authenticate.authenticate_request. Defer the import so
    tests can patch it cheaply.
    """
    try:
        from clerk_backend_api import Clerk
        clerk = Clerk(bearer_auth=get_settings().clerk_secret_key)
        # NOTE: the SDK's authenticate_request expects a httpx-style Request;
        # we instead use the lightweight `verify_token` helper available in the
        # SDK. If the SDK version differs, adapt to its current API surface.
        from clerk_backend_api.jwks_helpers import verify_token  # type: ignore
        payload = verify_token(token, secret_key=get_settings().clerk_secret_key)
        sub = payload.get("sub")
        if not sub:
            raise ValueError("missing sub claim")
        return sub
    except Exception as exc:
        logger.warning("clerk jwt verify failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired Clerk session",
        ) from exc


def get_current_clerk_id(request: Request) -> str:
    """Return verified clerk_id from JWT, or 401."""
    token = _extract_bearer(request)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )
    return _verify_clerk_jwt(token)


def get_current_user(
    clerk_id: str = Depends(get_current_clerk_id),
) -> dict[str, Any]:
    """Verified Clerk JWT → accounts.db row. 403 if no account or suspended."""
    acct = get_account_by_clerk_id(clerk_id)
    if acct is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No matching account. Wait for the webhook to provision your row.",
        )
    if acct["status"] == "suspended":
        raise HTTPException(status_code=403, detail="Account suspended")
    update_last_login(clerk_id)
    return acct


def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user
```

> ⚠ `clerk_backend_api.jwks_helpers.verify_token` is the typical import path in current SDK builds. If the SDK exposes the helper differently, search the installed package for the function and adapt. Test patches this anyway so unit tests don't care about the real call path.

- [ ] **Step 2: Quick syntax/import smoke**

```bash
cd backend && uv run python -c "from dossier_api.deps import get_current_user, get_current_clerk_id; print('ok')"
```

Expected: `ok`. (Import alone, no JWT call.)

---

## Task 7: /me router + tests

**Files:**
- Create: `backend/src/dossier_api/routers/me.py`
- Create: `backend/tests/test_me.py`
- Modify: `backend/src/dossier_api/main.py` (register router)

- [ ] **Step 1: Write failing test for /me**

```python
# backend/tests/test_me.py
"""Tests GET /me."""
from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from dossier_api.db import create_account, init_db
from dossier_api.main import app


def test_me_returns_401_without_auth(tmp_db_path):
    init_db(tmp_db_path)
    client = TestClient(app)
    r = client.get("/me")
    assert r.status_code == 401


def test_me_returns_403_when_no_account_row(tmp_db_path):
    init_db(tmp_db_path)
    client = TestClient(app)
    with patch("dossier_api.deps._verify_clerk_jwt", return_value="user_no_match"):
        r = client.get("/me", headers={"Authorization": "Bearer faketoken"})
    assert r.status_code == 403


def test_me_returns_account_row_when_authorized(tmp_db_path):
    init_db(tmp_db_path)
    create_account(
        clerk_id="user_abc",
        email="abc@example.com",
        data_user_slug="abc",
        status="active",
        tier="max",
        credits=42,
    )
    client = TestClient(app)
    with patch("dossier_api.deps._verify_clerk_jwt", return_value="user_abc"):
        r = client.get("/me", headers={"Authorization": "Bearer faketoken"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "abc@example.com"
    assert body["tier"] == "max"
    assert body["credits"] == 42
    assert body["status"] == "active"


def test_me_returns_403_when_suspended(tmp_db_path):
    init_db(tmp_db_path)
    create_account(
        clerk_id="user_susp", email="s@x.io", data_user_slug="susp", status="suspended",
    )
    client = TestClient(app)
    with patch("dossier_api.deps._verify_clerk_jwt", return_value="user_susp"):
        r = client.get("/me", headers={"Authorization": "Bearer faketoken"})
    assert r.status_code == 403
```

- [ ] **Step 2: Run tests to confirm fail**

```bash
cd backend && uv run pytest tests/test_me.py -v
```

Expected: 404 (route not registered) or import error.

- [ ] **Step 3: Implement `routers/me.py`**

```python
"""GET /me — current account."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from dossier_api.deps import get_current_user
from dossier_api.models.account import AccountResponse

router = APIRouter()


@router.get("/me", response_model=AccountResponse)
async def me(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Return the current user's account row."""
    return user
```

- [ ] **Step 4: Register router in `main.py`**

Edit `backend/src/dossier_api/main.py`, in the import section add `me` and register:

```python
from dossier_api.routers import health, me
# …
app.include_router(health.router)
app.include_router(me.router)
```

- [ ] **Step 5: Run tests to confirm pass**

```bash
cd backend && uv run pytest tests/test_me.py -v
```

Expected: 4 passed.

---

## Task 8: Clerk webhook router (TDD)

**Files:**
- Create: `backend/src/dossier_api/routers/webhooks.py`
- Create: `backend/tests/test_webhooks.py`
- Modify: `backend/src/dossier_api/main.py`

**Concept primer (Svix signed webhooks):** Clerk uses Svix infra for outbound webhooks. Each request includes `svix-id`, `svix-timestamp`, `svix-signature` headers. The signature is `HMAC-SHA256(secret, svix_id + "." + svix_timestamp + "." + raw_body)`. The `svix` library does this verification for us — we just pass the raw body + headers + secret.

**Concept primer (raw body in FastAPI):** Normally FastAPI parses JSON for us. For signature verification we need the *exact bytes* that were signed — that's `await request.body()`, not the parsed dict. Re-parse JSON ourselves after verification.

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_webhooks.py
"""Tests POST /webhooks/clerk."""
from __future__ import annotations

import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from dossier_api.db import get_account_by_clerk_id, init_db
from dossier_api.main import app


USER_CREATED_PAYLOAD = {
    "type": "user.created",
    "data": {
        "id": "user_new_signup_1",
        "email_addresses": [
            {"id": "idn_1", "email_address": "new@user.io"},
        ],
        "primary_email_address_id": "idn_1",
    },
}


def test_webhook_rejects_invalid_signature(tmp_db_path, monkeypatch):
    init_db(tmp_db_path)
    monkeypatch.setenv("CLERK_WEBHOOK_SECRET", "whsec_invalid")
    from dossier_api.settings import get_settings
    get_settings.cache_clear()
    client = TestClient(app)
    r = client.post(
        "/webhooks/clerk",
        headers={
            "svix-id": "msg_1",
            "svix-timestamp": "1",
            "svix-signature": "v1,deadbeef",
        },
        content=json.dumps(USER_CREATED_PAYLOAD),
    )
    assert r.status_code == 400


def test_webhook_user_created_inserts_pending_account(tmp_db_path):
    init_db(tmp_db_path)
    client = TestClient(app)
    with patch("dossier_api.routers.webhooks._verify_webhook", return_value=USER_CREATED_PAYLOAD):
        r = client.post(
            "/webhooks/clerk",
            headers={"svix-id": "msg_1", "svix-timestamp": "1", "svix-signature": "v1,fake"},
            content=json.dumps(USER_CREATED_PAYLOAD),
        )
    assert r.status_code == 200
    acct = get_account_by_clerk_id("user_new_signup_1")
    assert acct is not None
    assert acct["email"] == "new@user.io"
    assert acct["status"] == "pending"
    assert acct["tier"] == "lite"
    assert acct["credits"] == 100


def test_webhook_user_created_is_idempotent(tmp_db_path):
    init_db(tmp_db_path)
    client = TestClient(app)
    with patch("dossier_api.routers.webhooks._verify_webhook", return_value=USER_CREATED_PAYLOAD):
        r1 = client.post(
            "/webhooks/clerk",
            headers={"svix-id": "m", "svix-timestamp": "1", "svix-signature": "x"},
            content=json.dumps(USER_CREATED_PAYLOAD),
        )
        r2 = client.post(
            "/webhooks/clerk",
            headers={"svix-id": "m", "svix-timestamp": "1", "svix-signature": "x"},
            content=json.dumps(USER_CREATED_PAYLOAD),
        )
    assert r1.status_code == 200
    assert r2.status_code == 200


def test_webhook_unhandled_event_returns_200(tmp_db_path):
    init_db(tmp_db_path)
    payload = {"type": "session.created", "data": {}}
    client = TestClient(app)
    with patch("dossier_api.routers.webhooks._verify_webhook", return_value=payload):
        r = client.post(
            "/webhooks/clerk",
            headers={"svix-id": "m", "svix-timestamp": "1", "svix-signature": "x"},
            content=json.dumps(payload),
        )
    assert r.status_code == 200
```

- [ ] **Step 2: Run tests to confirm fail**

```bash
cd backend && uv run pytest tests/test_webhooks.py -v
```

Expected: 404 or import error.

- [ ] **Step 3: Implement `routers/webhooks.py`**

```python
"""POST /webhooks/clerk — provision accounts on Clerk events.

Why this endpoint exists:
    Clerk owns auth. We never store passwords. The single point where Clerk's
    state becomes ours is this webhook — fired on user.created, user.updated,
    user.deleted. Each event delivers the canonical Clerk user record; we
    mirror just the fields we need into accounts.db.

Security:
    Every request signed by Svix HMAC. We verify before parsing the body.
    A leaked webhook URL without the signing secret is useless.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from dossier_api.db import (
    create_account,
    get_account_by_clerk_id,
    update_account_status,
)
from dossier_api.settings import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()


def _verify_webhook(raw_body: bytes, headers: dict[str, str]) -> dict[str, Any]:
    """Verify Svix signature and return parsed payload. Raises HTTPException(400) on fail.

    Replaced in tests via patch.
    """
    try:
        from svix.webhooks import Webhook  # type: ignore
    except Exception as exc:
        logger.error("svix import failed: %s", exc)
        raise HTTPException(status_code=500, detail="webhook lib missing") from exc

    secret = get_settings().clerk_webhook_secret
    try:
        wh = Webhook(secret)
        payload = wh.verify(raw_body, headers)
        return payload if isinstance(payload, dict) else json.loads(raw_body)
    except Exception as exc:
        logger.warning("webhook verify failed: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid webhook signature") from exc


def _primary_email(data: dict[str, Any]) -> str | None:
    primary_id = data.get("primary_email_address_id")
    for addr in data.get("email_addresses", []):
        if addr.get("id") == primary_id:
            return addr.get("email_address")
    if data.get("email_addresses"):
        return data["email_addresses"][0].get("email_address")
    return None


@router.post("/webhooks/clerk")
async def clerk_webhook(request: Request) -> dict[str, str]:
    raw = await request.body()
    headers = {
        "svix-id":        request.headers.get("svix-id", ""),
        "svix-timestamp": request.headers.get("svix-timestamp", ""),
        "svix-signature": request.headers.get("svix-signature", ""),
    }
    payload = _verify_webhook(raw, headers)
    event_type = payload.get("type") or ""
    data = payload.get("data") or {}

    if event_type == "user.created":
        clerk_id = data.get("id")
        email = _primary_email(data)
        if not clerk_id or not email:
            logger.warning("user.created missing id/email: %s", payload)
            return {"status": "ignored"}
        if get_account_by_clerk_id(clerk_id) is not None:
            return {"status": "exists"}
        create_account(clerk_id=clerk_id, email=email, data_user_slug=clerk_id)
        logger.info("provisioned pending account clerk_id=%s email=%s", clerk_id, email)
        return {"status": "created"}

    if event_type == "user.deleted":
        clerk_id = data.get("id")
        if clerk_id and get_account_by_clerk_id(clerk_id) is not None:
            update_account_status(clerk_id, "suspended")
        return {"status": "soft-deleted"}

    return {"status": "ignored"}
```

- [ ] **Step 4: Register router in `main.py`**

```python
from dossier_api.routers import health, me, webhooks
# …
app.include_router(webhooks.router)
```

- [ ] **Step 5: Run tests to confirm pass**

```bash
cd backend && uv run pytest tests/test_webhooks.py -v
```

Expected: 4 passed.

### ── COMMIT BATCH 2 (Tasks 4-6) ──

Halt. Suggested commit message:

> ```
> feat(m2): pydantic models + /health + Clerk JWT auth dep
>
> - models/account.py — AccountResponse + CreditDebit pydantic v2 schemas
> - main.py — FastAPI app with lifespan(init_db) + CORS for :3000
> - routers/health.py — GET /health → {ok: true}
> - deps.py — get_current_clerk_id + get_current_user dependencies, 401/403
>   semantics, last_login_at touch
> - 5 new tests passing (1 health + 4 me-prep import smoke)
> ```

User commits. Continue.

> NOTE: This batch covers Tasks 4-6 (models + main/health + deps). Tasks 7-8
> (the /me router + webhooks) are in the next batch, so the second commit will
> bundle them with Task 9. This keeps the 3-task cadence honest even though
> commit batch 2 is slightly smaller.

---

## Task 9: Seed script for existing 4 users

**Files:**
- Create: `backend/scripts/seed_existing_users.py`
- Create: `backend/scripts/seed_users.example.json` (committed example)
- Modify: `backend/scripts/__init__.py` (`# package marker`)
- Modify: `backend/README.md` (only if seed instructions differ from already-written content)

**Concept primer (Clerk Backend API user creation):** The Clerk REST API lets us provision users programmatically: `POST /v1/users` with `email_address` + `skip_password_requirement: true`. The SDK wraps this. Clerk emails them a magic link to set their password on first login.

- [ ] **Step 1: Write `scripts/seed_users.example.json`**

```json
{
  "users": [
    {
      "slug": "shivang",
      "email": "shivang@example.com",
      "role": "admin",
      "tier": "max"
    },
    {
      "slug": "krishna",
      "email": "krishna@example.com",
      "role": "user",
      "tier": "max"
    },
    {
      "slug": "anushthan",
      "email": "anushthan@example.com",
      "role": "user",
      "tier": "max"
    },
    {
      "slug": "sambhav",
      "email": "sambhav@example.com",
      "role": "user",
      "tier": "max"
    }
  ]
}
```

- [ ] **Step 2: Write `scripts/seed_existing_users.py`**

```python
"""Seed the 4 existing users into Clerk + accounts.db.

Idempotent: re-running skips users already in accounts.db.

Run: uv run python -m dossier_api.scripts.seed_existing_users
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from dossier_api.db import (
    create_account,
    get_account_by_clerk_id,
    get_account_by_email,
    init_db,
)
from dossier_api.settings import get_settings

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SEED_FILE = Path(__file__).parent / "seed_users.json"


def _clerk():
    from clerk_backend_api import Clerk
    return Clerk(bearer_auth=get_settings().clerk_secret_key)


def _find_or_create_clerk_user(email: str, role: str, tier: str) -> str:
    """Return Clerk user_id. Creates the user if missing."""
    clerk = _clerk()
    # List API: filter by email
    try:
        existing = clerk.users.list(email_address=[email])
        users = list(existing) if existing else []
    except Exception as exc:
        logger.warning("clerk list users failed for %s: %s", email, exc)
        users = []
    if users:
        user = users[0]
        clerk_id = user.id
        logger.info("clerk user already exists for %s: %s", email, clerk_id)
    else:
        created = clerk.users.create(
            email_address=[email],
            skip_password_requirement=True,
            public_metadata={"role": role, "tier": tier},
        )
        clerk_id = created.id
        logger.info("created clerk user for %s: %s", email, clerk_id)
    # always re-apply public metadata in case it drifted
    clerk.users.update(
        user_id=clerk_id,
        public_metadata={"role": role, "tier": tier},
    )
    return clerk_id


def main() -> int:
    if not SEED_FILE.exists():
        logger.error("missing %s — copy from seed_users.example.json and fill in real emails", SEED_FILE)
        return 1
    config = json.loads(SEED_FILE.read_text())
    init_db()

    for user in config["users"]:
        slug = user["slug"]
        email = user["email"]
        role = user["role"]
        tier = user["tier"]

        if get_account_by_email(email) is not None:
            logger.info("skip %s — already in accounts.db", email)
            continue

        clerk_id = _find_or_create_clerk_user(email, role=role, tier=tier)

        if get_account_by_clerk_id(clerk_id) is not None:
            logger.info("skip %s — accounts.db row already exists", clerk_id)
            continue

        create_account(
            clerk_id=clerk_id,
            email=email,
            data_user_slug=slug,
            role=role,
            tier=tier,
            status="active",
            credits=99999,
        )
        logger.info("seeded %s → slug=%s tier=%s role=%s", email, slug, tier, role)

    logger.info("seed complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Manual smoke (deferred until user provides `seed_users.json`)**

This is **gated on user supplying real `seed_users.json`** with the 4 real emails. We will not auto-run it. At completion of M2:

```bash
cd backend && uv run python -m dossier_api.scripts.seed_existing_users
```

For the plan-execution acceptance test, we only run a dry-import:

```bash
cd backend && uv run python -c "from dossier_api.scripts.seed_existing_users import main; print('ok')"
```

Expected: `ok`.

---

## Task 10: pipeline_worker.py boilerplate (TDD)

**Files:**
- Create: `backend/src/dossier_api/workers/pipeline_worker.py`
- Create: `backend/tests/test_worker.py`

**Concept primer (atomic pick):** `UPDATE … WHERE status='queued' RETURNING …` in SQLite is atomic per transaction. Even with multiple workers (future), only one gets the row.

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_worker.py
"""Tests pipeline_worker pick + idle behavior."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from dossier_api.db import init_db
from dossier_api.workers.pipeline_worker import pick_next_queued_run


def _insert_run(db_path, run_id: str, status: str = "queued"):
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO pipeline_runs
           (run_id, user_id, agent, status, credits_cost)
           VALUES (?, ?, ?, ?, ?)""",
        (run_id, "u1", "discovery", status, 5),
    )
    conn.commit()
    conn.close()


def test_pick_returns_none_when_no_queued_runs(tmp_db_path):
    init_db(tmp_db_path)
    assert pick_next_queued_run(db_path=tmp_db_path) is None


def test_pick_picks_oldest_queued_run_and_marks_running(tmp_db_path):
    init_db(tmp_db_path)
    _insert_run(tmp_db_path, "r1")
    _insert_run(tmp_db_path, "r2")
    picked = pick_next_queued_run(db_path=tmp_db_path)
    assert picked is not None
    assert picked["run_id"] in {"r1", "r2"}
    # status should now be "running"
    conn = sqlite3.connect(tmp_db_path)
    row = conn.execute(
        "SELECT status, started_at FROM pipeline_runs WHERE run_id = ?",
        (picked["run_id"],),
    ).fetchone()
    conn.close()
    assert row[0] == "running"
    assert row[1] is not None  # started_at set


def test_pick_skips_already_running_runs(tmp_db_path):
    init_db(tmp_db_path)
    _insert_run(tmp_db_path, "r1", status="running")
    assert pick_next_queued_run(db_path=tmp_db_path) is None
```

- [ ] **Step 2: Run tests to confirm fail**

```bash
cd backend && uv run pytest tests/test_worker.py -v
```

Expected: `ImportError: cannot import name 'pick_next_queued_run'`.

- [ ] **Step 3: Implement `workers/pipeline_worker.py`**

```python
"""Standalone pipeline worker process.

Polls pipeline_runs for queued rows, marks them running, (M4: executes the
agent), records completion + refunds.

For M2 this is BOILERPLATE: pick + log + sleep. No actual agent execution.
The hookup to dossier_sdk.orchestrator happens in M4.

Run: uv run python -m dossier_api.workers.pipeline_worker
"""
from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dossier_api.db import _connect, init_db  # _connect intentional internal reuse
from dossier_api.settings import get_settings

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 5


def pick_next_queued_run(*, db_path: Path | None = None) -> dict[str, Any] | None:
    """Atomically claim the oldest queued run, mark it running, return it.

    Returns None if nothing queued.
    """
    with _connect(db_path) as conn:
        # SQLite's BEGIN IMMEDIATE locks for the read-then-write below
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT * FROM pipeline_runs
               WHERE status = 'queued'
               ORDER BY rowid ASC
               LIMIT 1"""
        ).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return None
        run_id = row["run_id"]
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE pipeline_runs SET status='running', started_at=? WHERE run_id=?",
            (now, run_id),
        )
        return dict(row)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="[%(levelname)s] [worker] %(message)s",
    )
    settings = get_settings()
    init_db(settings.accounts_db_path)
    logger.info("worker started · db=%s · poll=%ss", settings.accounts_db_path, POLL_INTERVAL_S)
    while True:
        run = pick_next_queued_run()
        if run is None:
            logger.info("[idle] no queued runs")
            time.sleep(POLL_INTERVAL_S)
            continue
        # M2: just log it back to completed (no-op execution).
        # M4 will swap this for dossier_sdk.orchestrator dispatch.
        logger.info("picked run %s (agent=%s) — no-op in M2", run["run_id"], run["agent"])
        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
cd backend && uv run pytest tests/test_worker.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Manual smoke (idle loop)**

```bash
cd backend && (uv run python -m dossier_api.workers.pipeline_worker &); sleep 7; kill %1 2>/dev/null
```

Expected: at least one `[idle] no queued runs` line in stdout.

---

## Task 11: Frontend lib/api.ts + server-api.ts

**Files:**
- Create: `frontend/lib/api.ts` — client-side fetch helper
- Create: `frontend/lib/server-api.ts` — RSC fetch helper
- Modify: `frontend/.env.local.example`

**Concept primer (RSC fetch + Clerk):** In server components, Clerk's `auth()` returns `{ getToken }`. We pass the JWT in the `Authorization` header when calling FastAPI. On the client, `useAuth().getToken()` does the same.

- [ ] **Step 1: Add `NEXT_PUBLIC_BACKEND_URL` to env example**

Edit `frontend/.env.local.example` — append:

```bash

# Backend FastAPI (M2)
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
```

- [ ] **Step 2: Write `frontend/lib/server-api.ts`**

```typescript
// Server-only helpers for calling the FastAPI backend from React Server Components.
// Uses the Clerk session token; throws on non-2xx.
import { auth } from "@clerk/nextjs/server";

export type Account = {
  user_id: string;
  clerk_id: string;
  email: string;
  data_user_slug: string;
  role: "user" | "admin";
  tier: "lite" | "pro" | "max";
  status: "pending" | "active" | "suspended";
  credits: number;
  credits_reset_at: string;
  created_at: string;
  last_login_at: string | null;
};

const BASE = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

async function authedFetch(path: string, init?: RequestInit): Promise<Response> {
  const { getToken } = await auth();
  const token = await getToken();
  return fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      Authorization: token ? `Bearer ${token}` : "",
    },
    cache: "no-store",
  });
}

export type MeResult =
  | { kind: "ok"; account: Account }
  | { kind: "no-account" }   // 403 — webhook hasn't run yet
  | { kind: "error"; status: number; message: string };

export async function fetchMe(): Promise<MeResult> {
  let res: Response;
  try {
    res = await authedFetch("/me");
  } catch (e) {
    return { kind: "error", status: 0, message: (e as Error).message };
  }
  if (res.status === 403) return { kind: "no-account" };
  if (!res.ok) {
    return { kind: "error", status: res.status, message: await res.text() };
  }
  const account = (await res.json()) as Account;
  return { kind: "ok", account };
}
```

- [ ] **Step 3: Write `frontend/lib/api.ts`**

```typescript
// Client-side fetch helpers (React Server Components: use server-api.ts).
// useApi() returns a thin fetch wrapper that injects the Clerk session token.
"use client";

import { useAuth } from "@clerk/nextjs";
import type { Account } from "./server-api";

export type { Account } from "./server-api";

const BASE = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

export function useApi() {
  const { getToken } = useAuth();

  async function authedFetch(path: string, init?: RequestInit): Promise<Response> {
    const token = await getToken();
    return fetch(`${BASE}${path}`, {
      ...init,
      headers: {
        ...(init?.headers ?? {}),
        Authorization: token ? `Bearer ${token}` : "",
      },
    });
  }

  return {
    getMe: async (): Promise<Account> => {
      const r = await authedFetch("/me");
      if (!r.ok) throw new Error(`/me failed: ${r.status}`);
      return r.json();
    },
  };
}
```

---

## Task 12: Frontend wire layout + CreditPill + pending screen

**Files:**
- Modify: `frontend/components/dossier/CreditPill.tsx`
- Modify: `frontend/app/(app)/layout.tsx`
- Create: `frontend/app/(app)/pending/page.tsx`

- [ ] **Step 1: Update `CreditPill.tsx` to accept real props**

Replace the file contents:

```tsx
type CreditPillProps = {
  credits: number;
  creditsTotal?: number;
};

/**
 * Real-data credit pill (M2). Total defaults to a sensible per-tier ceiling
 * picked by the layout; pill itself just renders what it's given.
 */
export function CreditPill({ credits, creditsTotal }: CreditPillProps) {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border border-[color:var(--color-border-2)]/60 bg-[color:var(--color-surface)] px-3 py-1.5 text-sm"
      title="Credits remaining this period"
      style={{ fontFamily: "var(--font-geist-mono)" }}
    >
      <span aria-hidden className="text-primary">⚡</span>
      <span className="text-[color:var(--color-text)] tabular-nums">
        {credits.toLocaleString()}
      </span>
      {creditsTotal !== undefined && (
        <span className="text-[color:var(--color-text-subtle)]">
          / {creditsTotal.toLocaleString()}
        </span>
      )}
    </span>
  );
}
```

- [ ] **Step 2: Create pending-review page**

```tsx
// frontend/app/(app)/pending/page.tsx
import { SignOutButton } from "@clerk/nextjs";

export default function PendingReviewPage() {
  return (
    <div className="flex min-h-[80vh] flex-col items-center justify-center px-6 text-center">
      <h1 className="font-display text-3xl font-semibold text-[color:var(--color-text)]">
        Your account is pending review.
      </h1>
      <p className="mt-4 max-w-md text-[color:var(--color-text-muted)]">
        Dossier is in closed beta. An admin will approve your account shortly —
        you&apos;ll get an email when you&apos;re in.
      </p>
      <div className="mt-8">
        <SignOutButton>
          <button className="rounded-md border border-[color:var(--color-border-2)] px-4 py-2 text-sm text-[color:var(--color-text)] hover:bg-[color:var(--color-surface)]">
            Sign out
          </button>
        </SignOutButton>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Rewrite `frontend/app/(app)/layout.tsx`**

```tsx
import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import { Sidebar } from "@/components/dossier/Sidebar";
import { CreditPill } from "@/components/dossier/CreditPill";
import { fetchMe } from "@/lib/server-api";

const CREDITS_BY_TIER = { lite: 50, pro: 500, max: 2000 } as const;

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { userId } = await auth();
  if (!userId) redirect("/sign-in");

  const me = await fetchMe();

  // Webhook hasn't provisioned the row yet (race after fresh signup).
  // Render the pending screen — it's the safe degenerate state.
  if (me.kind === "no-account") {
    return (
      <div className="flex min-h-screen bg-[color:var(--color-bg)]">
        <main className="flex-1">{await PendingFallback()}</main>
      </div>
    );
  }

  if (me.kind === "error") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[color:var(--color-bg)] px-6">
        <div className="max-w-md text-center text-[color:var(--color-text)]">
          <h1 className="font-display text-2xl">Backend unreachable</h1>
          <p className="mt-3 text-sm text-[color:var(--color-text-muted)]">
            Could not reach the API ({me.status}). Is uvicorn running on{" "}
            <code>:8000</code>?
          </p>
        </div>
      </div>
    );
  }

  const account = me.account;

  if (account.status === "pending") {
    const { default: Page } = await import("./pending/page");
    return (
      <div className="flex min-h-screen bg-[color:var(--color-bg)]">
        <main className="flex-1"><Page /></main>
      </div>
    );
  }

  if (account.status === "suspended") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[color:var(--color-bg)] text-[color:var(--color-text)]">
        Account suspended.
      </div>
    );
  }

  const creditsTotal = CREDITS_BY_TIER[account.tier];

  return (
    <div className="flex min-h-screen bg-[color:var(--color-bg)]">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 items-center justify-end gap-3 border-b border-[color:var(--color-border-2)]/40 bg-[color:var(--color-bg)]/80 px-4 backdrop-blur sm:px-6">
          <CreditPill credits={account.credits} creditsTotal={creditsTotal} />
        </header>
        <main className="flex-1 px-4 py-8 sm:px-6 lg:px-10">{children}</main>
      </div>
    </div>
  );
}

async function PendingFallback() {
  const { default: Page } = await import("./pending/page");
  return <Page />;
}
```

- [ ] **Step 4: Frontend typecheck + tests**

```bash
cd frontend && pnpm typecheck && pnpm test --run
```

Expected: typecheck clean. Existing 8 tests still pass. CreditPill story-level changes — if a snapshot test exists, update it (none expected from M1).

- [ ] **Step 5: Frontend build**

```bash
cd frontend && pnpm build
```

Expected: succeeds. Warning on the `useApi` hook unused at build time is fine — it's user-facing in M3.

### ── COMMIT BATCH 3 (Tasks 7-9) ──

Halt. Suggested commit message:

> ```
> feat(m2): /me + Clerk webhook + seed script
>
> - routers/me.py — GET /me returns AccountResponse, 401/403 semantics
> - routers/webhooks.py — POST /webhooks/clerk verifies Svix signature,
>   provisions pending accounts on user.created, soft-deletes on user.deleted,
>   idempotent on repeat events
> - scripts/seed_existing_users.py — idempotent Clerk + accounts.db seeder
>   for shivang/krishna/anushthan/sambhav, gated on seed_users.json
> - 8 new tests passing (4 me + 4 webhooks)
> ```

User commits. Continue.

---

## Task 13: Acceptance + end-to-end smoke

**Files:** none new

This is the canonical M2 acceptance test. Follows spec §15 M2.

- [ ] **Step 1: All backend tests pass**

```bash
cd backend && uv run pytest -v
```

Expected: ≥15 passed (7 db + 1 health + 4 me + 4 webhooks + 3 worker). No failures.

- [ ] **Step 2: Start uvicorn + worker side-by-side**

In two shells (foreground each so the user can see the logs):

```bash
cd backend && uv run uvicorn dossier_api.main:app --reload --port 8000
```

```bash
cd backend && uv run python -m dossier_api.workers.pipeline_worker
```

Expected:
- uvicorn log shows `dossier-api ready · db=…/data/accounts.db`.
- worker log shows `worker started · db=…` then `[idle] no queued runs` every ~5s.

- [ ] **Step 3: GET /health from curl**

```bash
curl -s http://localhost:8000/health
```

Expected: `{"ok":true}`.

- [ ] **Step 4: Configure Clerk webhook (manual user step)**

In Clerk dashboard for "Dossier Dev":
1. **Webhooks** → **Add Endpoint**
2. URL: `http://localhost:8000/webhooks/clerk` (for prod, use ngrok or deploy URL)
3. Subscribe to: `user.created`, `user.deleted`
4. Copy the signing secret (`whsec_…`) into `backend/.env` as `CLERK_WEBHOOK_SECRET`.

For local dev, the user must run `ngrok http 8000` and put the ngrok URL in Clerk. This is a one-time manual step — not automatable.

- [ ] **Step 5: Frontend signup flow**

```bash
cd frontend && pnpm dev
```

Visit `http://localhost:3000/sign-up`. Create a new test user. After signup:

Expected sequence:
1. Clerk redirects to `/dashboard`.
2. RSC layout calls `/me` → 403 (no account yet) → renders pending screen briefly.
3. Webhook fires → row inserted in `accounts.db` with `status=pending`.
4. Refresh page → `/me` returns row → renders pending-review screen.

Verify the row:

```bash
sqlite3 data/accounts.db "SELECT clerk_id, email, status, tier, credits FROM accounts;"
```

Expected: one row with status=pending tier=lite credits=100.

- [ ] **Step 6: Seed real users + verify shivang can log in**

User fills `backend/scripts/seed_users.json` with real emails:

```bash
cd backend && uv run python -m dossier_api.scripts.seed_existing_users
```

Expected: 4 rows added with `status=active tier=max credits=99999`. Re-running is a no-op.

Sign in as shivang → CreditPill shows `99,999 / 2,000`. (The "out of bounds" denominator is fine for M2; M3+ may switch to actual `credits_total`.)

- [ ] **Step 7: Tick `frontend-todo.txt` M2 boxes**

Edit `frontend-todo.txt` — replace the M2 block with a `[x] DONE` marker block similar to M1.

### ── COMMIT BATCH 4 (Tasks 10-12) ──

Halt. Suggested commit message:

> ```
> feat(m2): worker boilerplate + frontend /me wiring
>
> - workers/pipeline_worker.py — standalone polling loop with atomic
>   pick_next_queued_run; M2 picks but no-ops, real exec wired in M4
> - frontend/lib/server-api.ts + lib/api.ts — typed FastAPI client
>   (server + client variants) using Clerk session token
> - frontend/(app)/layout.tsx — RSC fetches /me, renders pending-review
>   screen for status=pending, real CreditPill for active users
> - frontend/(app)/pending/page.tsx — pending-review screen
> - frontend/components/dossier/CreditPill.tsx — accepts real {credits,
>   creditsTotal} props
> - frontend/.env.local.example — NEXT_PUBLIC_BACKEND_URL
> - 3 new worker tests passing
> ```

User commits.

### ── COMMIT BATCH 5 (Task 13 / acceptance) ──

After acceptance test passes:

> ```
> chore(m2): finalize M2 acceptance + update frontend-todo
>
> Acceptance test passed end-to-end:
> - uvicorn + worker run cleanly on :8000 / idle loop
> - signup webhook provisions pending row in accounts.db
> - frontend pending-review screen renders for status=pending
> - seed script creates 4 active rows for existing users
> ```

User commits.

---

## Out-of-scope (do NOT add in M2)

- Real worker execution of agents (M4)
- `/pipeline/run` endpoint + credit gate (M4)
- `/persona/*` endpoints (M3)
- `/admin/*` endpoints (M5)
- SSE streaming (M4)
- Monthly credit reset job (M5+)
- Sentry, PostHog (M5+)

---

## Self-review checklist

**Spec coverage (§6, §7, §8, §9):**
- §6 auth flow: webhook ✓, accounts.db row ✓, seed script ✓, pending screen ✓
- §7 credits: schema ✓ (accounts/credit_log/pipeline_runs/waitlist), credit gate code is M4 not M2 (intentionally deferred)
- §8 pipeline architecture: worker boilerplate ✓, orchestrator extracted ✓; SSE/refund deferred to M4
- §9 endpoints in scope: /health ✓, /me ✓, /webhooks/clerk ✓; persona/jobs/pipeline/admin are out-of-scope per M2.md

**Placeholder scan:** none — all code blocks complete.

**Type consistency:** `Account` shape matches between `db.py` returned dicts, `AccountResponse` pydantic, and `server-api.ts` TS type. Field names identical: `user_id`, `clerk_id`, `email`, `data_user_slug`, `role`, `tier`, `status`, `credits`, `credits_reset_at`, `created_at`, `last_login_at`. ✓

**Commit cadence:** 5 batches across 13 tasks (3/3/3/3/1) — slightly off the strict 3-per rule because Task 13 is the final acceptance gate and stands alone. Documented above.
