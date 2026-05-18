"""
scripts/run_watchlist.py — Run the watchlist agent against all 50 target companies.

Searches by company ID (not keyword) to catch promoted/sponsored listings
that the regular job discovery pipeline misses.

Usage:
    python scripts/run_watchlist.py                   # default: min score 5
    python scripts/run_watchlist.py --min-score 7     # high relevancy only
    python scripts/run_watchlist.py --location "Mumbai"
"""

import argparse
import sys
from pathlib import Path

# Add project root to sys.path so imports work when run from any directory
sys.path.insert(0, str(Path(__file__).parent.parent))


def main() -> None:
    """Parse CLI flags and run the watchlist agent."""
    parser = argparse.ArgumentParser(
        description="Dossier watchlist agent — searches target companies directly"
    )
    parser.add_argument(
        "--user", type=str, default="shivang",
        help="Run for this user. Reads from profile/{user}/, writes to data/{user}/. (default: shivang)",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=5,
        help="Minimum LLM score to include in results (1-10, default: 5)",
    )
    parser.add_argument(
        "--location",
        type=str,
        default="India",
        help="Primary location for LinkedIn searches (default: India)",
    )

    args = parser.parse_args()

    from dossier_sdk.config import Config
    Config(user=args.user)

    from dossier_sdk.agents.watchlist_agent import run
    run(min_score=args.min_score, location=args.location)


if __name__ == "__main__":
    main()
