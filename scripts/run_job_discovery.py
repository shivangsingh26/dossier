"""
scripts/run_job_discovery.py — Entry point for job discovery.

Usage:
    python scripts/run_job_discovery.py              # jobs from last 72 hours, min score 5
    python scripts/run_job_discovery.py --hours 24   # only last 24 hours (URGENT focus)
    python scripts/run_job_discovery.py --min-score 7  # high relevancy only

What it does:
    Reads profile/profile.json, fetches jobs from LinkedIn/Indeed/Naukri/Google,
    scores each against your profile, saves artifacts to data/artifacts/,
    and prints a ranked results table.
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dossier job discovery agent")
    parser.add_argument(
        "--user", type=str, default="shivang",
        help="Run for this user. Reads from profile/{user}/, writes to data/{user}/. (default: shivang)",
    )
    parser.add_argument(
        "--hours", type=int, default=72,
        help="Only fetch jobs posted in the last N hours (default: 72)"
    )
    parser.add_argument(
        "--min-score", type=int, default=5,
        help="Skip jobs scoring below this (1-10, default: 5)"
    )
    args = parser.parse_args()

    from dossier_sdk.config import Config
    Config(user=args.user)

    from dossier_sdk.agents.job_discovery import run
    run(hours_old=args.hours, min_score=args.min_score)
