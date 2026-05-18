"""
run_dossier.py — Master orchestrator for the Dossier daily pipeline.

Runs all stages in sequence. Each stage is wrapped in try/except so a
failure in one stage does not abort the others.

MODES:
  full          (default) — Discovery + Watchlist + Company Intel + Gap Analysis
  quick                   — Discovery + Watchlist, skip company intel + gap analysis
  urgent                  — Discovery (forced 24h) + Watchlist, no intel/gap
  company-intel           — Company Intel only, reads last-run files (no re-scraping)

FLAGS:
  --with-referrals  Also run Referral Finder for jobs scoring >= company-intel-score.
                    Uses ~5 Tavily credits per job. Skipped by default.

USAGE:
  python run_dossier.py                                # full pipeline, last 24h
  python run_dossier.py --hours 72                     # last 72 hours
  python run_dossier.py --mode quick                   # discovery + watchlist only
  python run_dossier.py --mode urgent                  # forced 24h, no intel/gap
  python run_dossier.py --mode company-intel           # fresh company intel on yesterday's jobs
  python run_dossier.py --with-referrals               # also find referral contacts
  python run_dossier.py --min-score 6                  # stricter quality gate
  python run_dossier.py --company-intel-score 8        # only research top-scoring jobs

COST GUIDE (approximate, after week-1 SQLite dedup fills up):
  full:                ~$0.09 LLM + Tavily (cached = 0) + ~$0.002 gap analysis
  full --with-referrals: add ~$0.005–$0.01 per high-score job (Tavily + gpt-5.4-mini)
  quick:               ~$0.09 LLM, 0 Tavily
  urgent:              ~$0.03 LLM, 0 Tavily
  company-intel:       ~$0.001 LLM + Tavily only for uncached companies
"""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.rule import Rule

console = Console()

_MODES = {
    "full":          "Discovery + Watchlist + Company Intel + Gap Analysis",
    "quick":         "Discovery + Watchlist (no intel or gap analysis)",
    "urgent":        "Discovery (forced 24h) + Watchlist (no intel or gap analysis)",
    "company-intel": "Company Intel only — reads last-run files, no re-scraping",
    "market-intel":  "Market Intel only — discover new AI/ML startups from funding news",
}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def load_last_run(path: Path) -> list[dict]:
    """Load a saved last-run JSON file. Returns empty list if missing or corrupt."""
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def print_stage_banner(label: str, detail: str = "") -> None:
    """Print a visible separator before each pipeline stage."""
    console.print()
    console.print(Rule(f"[bold cyan]{label}[/bold cyan]  [dim]{detail}[/dim]", style="cyan"))
    console.print()


def print_run_header(args: argparse.Namespace) -> None:
    """Print the opening summary of what this run will do."""
    console.print()
    console.print(Rule("[bold]Dossier — Daily Pipeline[/bold]", style="bold"))
    console.print(f"  Mode:                [bold]{args.mode}[/bold] — {_MODES[args.mode]}")
    if args.mode != "company-intel":
        console.print(f"  Hours back:          {args.hours}h  (jobs posted in last {args.hours} hours)")
        console.print(f"  Min score:           {args.min_score}/10")
    if args.mode in ("full", "company-intel"):
        console.print(f"  Company Intel gate:  {args.company_intel_score}/10  (research only jobs above this)")
    console.print(f"  Gap Analysis:        {'yes (new JDs only)' if args.mode in ('full', 'company-intel') else 'skipped'}")
    console.print(f"  Referral Finder:     {'yes (jobs >= ' + str(args.company_intel_score) + ')' if args.with_referrals else 'skipped (use --with-referrals)'}")
    console.print(f"  Location:            {args.location}")
    console.print(f"  Started:             {datetime.now().strftime('%Y-%m-%d  %H:%M')}")
    console.print()


def save_run_summary(summary: dict, data_dir: Path) -> None:
    """Persist run metadata to data/{user}/last_orchestrator_run.json."""
    path = data_dir / "last_orchestrator_run.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    """Parse CLI flags, determine which stages to run, execute pipeline."""
    parser = argparse.ArgumentParser(
        description="Dossier master orchestrator — single command for the full daily pipeline.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        choices=["full", "quick", "urgent", "company-intel", "market-intel"],
        default="full",
        help=(
            "full          — Discovery + Watchlist + Company Intel  [default]\n"
            "quick         — Discovery + Watchlist (no company intel, fastest)\n"
            "urgent        — Discovery (forced 24h) + Watchlist (no company intel)\n"
            "company-intel — Company Intel only (reads yesterday's results)\n"
            "market-intel  — Market Intel only (discover new AI/ML startups)\n"
        ),
    )
    parser.add_argument(
        "--hours", type=int, default=24,
        help=(
            "How many hours back to fetch jobs.\n"
            "Examples: --hours 6 (very recent), --hours 24 (today), --hours 168 (1 week).\n"
            "Forced to 24 in urgent mode regardless of this flag.\n"
            "(default: 72)"
        ),
    )
    parser.add_argument(
        "--min-score", type=int, default=5,
        help="Minimum LLM score gate for discovery and watchlist results. (default: 5)",
    )
    parser.add_argument(
        "--company-intel-score", type=int, default=7,
        help="Minimum job score to trigger company intel research. (default: 7)",
    )
    parser.add_argument(
        "--location", type=str, default="India",
        help="Location filter for watchlist LinkedIn searches. (default: India)",
    )
    parser.add_argument(
        "--with-referrals", action="store_true", default=False,
        help=(
            "Also run Referral Finder for jobs scoring >= company-intel-score.\n"
            "Uses ~5 Tavily credits per job. Off by default."
        ),
    )
    parser.add_argument(
        "--user", type=str, default="shivang",
        help="Run for this user. Reads from profile/{user}/, writes to data/{user}/. (default: shivang)",
    )
    args = parser.parse_args()

    from dossier_sdk.config import Config
    Config(user=args.user)
    config      = Config()
    data_dir    = config.data_dir
    artifacts_dir = config.artifacts_dir

    # urgent mode always collapses to 24h regardless of --hours
    if args.mode == "urgent":
        args.hours = 24

    run_market_intel  = args.mode == "market-intel"
    run_discovery     = args.mode in ("full", "quick", "urgent")
    run_watchlist     = args.mode in ("full", "quick", "urgent")
    run_company_intel = args.mode in ("full", "company-intel")
    run_gap_analysis  = args.mode in ("full", "company-intel")
    run_referrals     = args.with_referrals

    print_run_header(args)

    pipeline_start = time.monotonic()

    summary: dict = {
        "run_at":                  datetime.now(timezone.utc).isoformat(),
        "mode":                    args.mode,
        "hours":                   args.hours,
        "min_score":               args.min_score,
        "company_intel_score":     args.company_intel_score,
        "stages_run":              [],
        "market_intel_found":      0,
        "discovery_jobs":          0,
        "watchlist_jobs":          0,
        "company_intel_companies": 0,
        "gap_analysis_processed":  0,
        "referrals_found":         0,
        "stage_errors":            [],
        "total_seconds":           0.0,
    }

    discovery_jobs: list[dict] = []
    watchlist_jobs: list[dict] = []

    # ── Stage 0: Market Intel ─────────────────────────────────────────────────
    if run_market_intel:
        print_stage_banner(
            "Stage 0 — Market Intel",
            "discover new AI/ML startups from Indian funding news",
        )
        t0 = time.monotonic()
        try:
            from dossier_sdk.agents.market_intel_agent import run as _market_intel
            discovered = _market_intel() or []
            summary["stages_run"].append("market_intel")
            watchlist_adds = sum(1 for c in discovered if c.get("pipeline_stage") == "watchlist")
            cold_outreach  = sum(1 for c in discovered if c.get("pipeline_stage") == "cold_outreach")
            summary["market_intel_found"] = len(discovered)
            console.print(
                f"\n  [green]✓ Market Intel complete[/green] — "
                f"{watchlist_adds} → watchlist · {cold_outreach} → cold outreach · "
                f"{time.monotonic() - t0:.0f}s"
            )
        except Exception as exc:
            console.print(f"\n  [red]✗ Market Intel failed:[/red] {exc}")
            summary["stage_errors"].append(f"market_intel: {exc}")

    # ── Stage 1: Job Discovery ────────────────────────────────────────────────
    if run_discovery:
        print_stage_banner(
            "Stage 1 — Job Discovery",
            f"last {args.hours}h · min score {args.min_score}",
        )
        t0 = time.monotonic()
        try:
            from dossier_sdk.agents.job_discovery import run as _discover
            discovery_jobs = _discover(hours_old=args.hours, min_score=args.min_score) or []
            summary["discovery_jobs"] = len(discovery_jobs)
            summary["stages_run"].append("discovery")
            console.print(
                f"\n  [green]✓ Discovery complete[/green] — "
                f"{len(discovery_jobs)} jobs · {time.monotonic() - t0:.0f}s"
            )
        except Exception as exc:
            console.print(f"\n  [red]✗ Discovery failed:[/red] {exc}")
            console.print("  [dim]Falling back to last-run file for downstream stages...[/dim]")
            summary["stage_errors"].append(f"discovery: {exc}")
            discovery_jobs = load_last_run(data_dir / "last_discovery_run.json")

    # ── Stage 2: Watchlist ────────────────────────────────────────────────────
    if run_watchlist:
        print_stage_banner(
            "Stage 2 — Watchlist Agent",
            f"70 target companies · min score {args.min_score}",
        )
        t0 = time.monotonic()
        try:
            from dossier_sdk.agents.watchlist_agent import run as _watchlist
            watchlist_jobs = _watchlist(min_score=args.min_score, location=args.location) or []
            summary["watchlist_jobs"] = len(watchlist_jobs)
            summary["stages_run"].append("watchlist")
            console.print(
                f"\n  [green]✓ Watchlist complete[/green] — "
                f"{len(watchlist_jobs)} jobs · {time.monotonic() - t0:.0f}s"
            )
        except Exception as exc:
            console.print(f"\n  [red]✗ Watchlist failed:[/red] {exc}")
            console.print("  [dim]Falling back to last-run file for company intel stage...[/dim]")
            summary["stage_errors"].append(f"watchlist: {exc}")
            watchlist_jobs = load_last_run(data_dir / "last_watchlist_run.json")

    # ── Stage 3: Company Intel ────────────────────────────────────────────────
    if run_company_intel:
        print_stage_banner(
            "Stage 3 — Company Intel",
            f"jobs scoring ≥ {args.company_intel_score} · Tavily cache-aware",
        )
        t0 = time.monotonic()
        try:
            from dossier_sdk.agents.company_intel import print_intel_summary
            from dossier_sdk.agents.company_intel import run as _company_intel

            # company-intel mode: load results from last run since stages 1 & 2 were skipped
            if args.mode == "company-intel":
                discovery_jobs = load_last_run(data_dir / "last_discovery_run.json")
                watchlist_jobs = load_last_run(data_dir / "last_watchlist_run.json")
                total_loaded   = len(discovery_jobs) + len(watchlist_jobs)
                if total_loaded == 0:
                    console.print(
                        "  [red]No last-run files found.[/red]\n"
                        "  Run discovery or watchlist first, then re-run with --mode company-intel."
                    )
                    return
                console.print(
                    f"  Loaded {len(discovery_jobs)} discovery + "
                    f"{len(watchlist_jobs)} watchlist jobs from last run"
                )

            all_jobs              = discovery_jobs + watchlist_jobs
            company_intel_results = _company_intel(all_jobs, min_score=args.company_intel_score) or []

            if company_intel_results:
                print_intel_summary(company_intel_results)

            summary["company_intel_companies"] = len(company_intel_results)
            summary["stages_run"].append("company_intel")
            console.print(
                f"\n  [green]✓ Company Intel complete[/green] — "
                f"{len(company_intel_results)} companies researched · {time.monotonic() - t0:.0f}s"
            )
        except Exception as exc:
            console.print(f"\n  [red]✗ Company Intel failed:[/red] {exc}")
            summary["stage_errors"].append(f"company_intel: {exc}")

    # ── Stage 4: Gap Analysis ─────────────────────────────────────────────────
    if run_gap_analysis:
        print_stage_banner(
            "Stage 4 — Gap Analysis",
            f"semantic skill extraction for new high-score jobs · min score {args.min_score}",
        )
        t0 = time.monotonic()
        try:
            from dossier_sdk.agents.gap_analysis import run as _gap_analysis
            # force=False → only processes JDs that don't have gap.json yet (new jobs only)
            result = _gap_analysis(force=False, min_score=args.min_score) or {}
            processed = result.get("new_extracted", 0)
            summary["gap_analysis_processed"] = processed
            summary["stages_run"].append("gap_analysis")
            console.print(
                f"\n  [green]✓ Gap Analysis complete[/green] — "
                f"{processed} JDs processed · {time.monotonic() - t0:.0f}s"
            )
        except Exception as exc:
            console.print(f"\n  [red]✗ Gap Analysis failed:[/red] {exc}")
            summary["stage_errors"].append(f"gap_analysis: {exc}")

    # ── Stage 5: Referral Finder ──────────────────────────────────────────────
    if run_referrals:
        # Collect job IDs for high-score jobs that don't already have referrals.json
        all_jobs    = discovery_jobs + watchlist_jobs
        target_jobs = [
            j for j in all_jobs
            if j.get("score", 0) >= args.company_intel_score
            and not (artifacts_dir / j["job_id"] / "referrals.json").exists()
        ]
        print_stage_banner(
            "Stage 5 — Referral Finder",
            f"{len(target_jobs)} jobs scoring ≥ {args.company_intel_score} without referrals yet",
        )
        t0 = time.monotonic()
        total_referrals = 0
        try:
            from dossier_sdk.agents.referral_finder import run_referral_finder
            for job in target_jobs:
                job_id = job["job_id"]
                try:
                    contacts = run_referral_finder(job_id, skip_csv=False) or []
                    total_referrals += len(contacts)
                    console.print(
                        f"  [cyan]{job_id}[/cyan] — {len(contacts)} contacts found"
                    )
                except Exception as exc:
                    console.print(f"  [yellow]✗ {job_id}: {exc}[/yellow]")
                    summary["stage_errors"].append(f"referrals/{job_id}: {exc}")
            summary["referrals_found"] = total_referrals
            summary["stages_run"].append("referrals")
            console.print(
                f"\n  [green]✓ Referral Finder complete[/green] — "
                f"{total_referrals} contacts across {len(target_jobs)} jobs · "
                f"{time.monotonic() - t0:.0f}s"
            )
        except Exception as exc:
            console.print(f"\n  [red]✗ Referral Finder failed:[/red] {exc}")
            summary["stage_errors"].append(f"referrals: {exc}")

    # ── Final Summary ─────────────────────────────────────────────────────────
    total_seconds            = time.monotonic() - pipeline_start
    summary["total_seconds"] = round(total_seconds, 1)

    console.print()
    console.print(Rule("[bold]Pipeline Complete[/bold]", style="bold"))
    if summary["market_intel_found"] or run_market_intel:
        console.print(f"  Market Intel:    {summary['market_intel_found']} new companies discovered")
    console.print(f"  Discovery:       {summary['discovery_jobs']} jobs")
    console.print(f"  Watchlist:       {summary['watchlist_jobs']} jobs")
    console.print(f"  Company Intel:   {summary['company_intel_companies']} companies researched")
    if run_gap_analysis:
        console.print(f"  Gap Analysis:    {summary['gap_analysis_processed']} JDs processed")
    if run_referrals:
        console.print(f"  Referrals:       {summary['referrals_found']} contacts found")
    console.print(f"  Total time:      {total_seconds:.0f}s")

    if summary["stage_errors"]:
        console.print(f"\n  [yellow]Stage errors:[/yellow]")
        for err in summary["stage_errors"]:
            console.print(f"    [yellow]• {err}[/yellow]")

    console.print()
    save_run_summary(summary, data_dir)
    console.print(f"  Run metadata → data/last_orchestrator_run.json\n")


if __name__ == "__main__":
    main()
