"""
scripts/run_company_intel.py — Run the company intel agent on recent high-scoring jobs.

Reads the output of your last discovery and/or watchlist run, filters for
jobs above the score threshold, and gathers structured intel for each unique company.

Intel is saved to data/artifacts/{job_id}/intel.json for every qualifying job.

USAGE:
    python scripts/run_company_intel.py                   # both sources, min score 7
    python scripts/run_company_intel.py --min-score 8     # only very strong matches
    python scripts/run_company_intel.py --source watchlist
    python scripts/run_company_intel.py --source discovery

PREREQUISITE: Run job discovery and/or watchlist first so the last-run files exist:
    python scripts/run_job_discovery.py --hours 240
    python scripts/run_watchlist.py --min-score 5
"""

import argparse
import json
from pathlib import Path

from rich.console import Console

console = Console()


def load_jobs_from_file(path: Path) -> list[dict]:
    """Load scored jobs from a last-run JSON file. Returns empty list if file is missing."""
    if not path.exists():
        console.print(f"  [yellow]Not found: {path} — skipping[/yellow]")
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        console.print(f"  [yellow]Could not load {path}: {e}[/yellow]")
        return []


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run company intel agent on recent high-scoring jobs."
    )
    parser.add_argument(
        "--user", type=str, default="shivang",
        help="Run for this user. Reads from profile/{user}/, writes to data/{user}/. (default: shivang)",
    )
    parser.add_argument(
        "--min-score", type=int, default=7,
        help="Minimum job score to research (default: 7)",
    )
    parser.add_argument(
        "--source", choices=["discovery", "watchlist", "both"], default="both",
        help="Which last-run file(s) to read from (default: both)",
    )
    args = parser.parse_args()

    from config import Config
    Config(user=args.user)

    from agents.company_intel import print_intel_summary, run

    console.print("\n[bold]Dossier — Company Intel Agent[/bold]")
    console.print("━" * 50)

    discovery_jobs: list[dict] = []
    watchlist_jobs: list[dict] = []

    if args.source in ("discovery", "both"):
        discovery_jobs = load_jobs_from_file(Path("data/last_discovery_run.json"))
        console.print(f"  Discovery jobs loaded:  {len(discovery_jobs)}")

    if args.source in ("watchlist", "both"):
        watchlist_jobs = load_jobs_from_file(Path("data/last_watchlist_run.json"))
        console.print(f"  Watchlist jobs loaded:  {len(watchlist_jobs)}")

    all_jobs = discovery_jobs + watchlist_jobs
    if not all_jobs:
        console.print("\n[red]  No jobs found. Run job discovery or watchlist first.[/red]")
        return

    console.print(f"\n[bold]Step 1/2[/bold] — Fetching company intel (min score {args.min_score}/10)...")
    results = run(all_jobs, min_score=args.min_score)

    if not results:
        return

    console.print(f"\n[bold]Step 2/2[/bold] — Summary")
    print_intel_summary(results)

    good      = sum(1 for r in results if r["intel"].get("data_quality") == "good")
    partial   = sum(1 for r in results if r["intel"].get("data_quality") == "partial")
    not_found = sum(1 for r in results if r["intel"].get("data_quality") == "not_found")

    console.print(
        f"\n  Intel saved → data/artifacts/{{job_id}}/intel.json\n"
        f"  Quality breakdown: "
        f"[green]{good} good[/green] | "
        f"[yellow]{partial} partial[/yellow] | "
        f"[red]{not_found} not found[/red]\n"
    )


if __name__ == "__main__":
    main()
