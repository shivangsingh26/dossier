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
