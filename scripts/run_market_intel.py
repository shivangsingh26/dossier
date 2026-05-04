"""
scripts/run_market_intel.py — Run the Market Intel Agent.

Searches Indian startup funding news (YourStory, Inc42, TechCrunch) for new AI/ML
companies not yet in your watchlist. Two-path output:
  • Companies with public ML openings → auto-added to target_companies.json (watchlist)
  • Companies with no openings       → cold outreach alert (reach them before they post)

Also performs a one-time schema backfill on target_companies.json (adds pipeline_stage,
funding_stage, discovered_via, and 4 other fields to all existing 70 companies).

Usage:
    python scripts/run_market_intel.py
"""

import sys
from pathlib import Path

# Add project root to sys.path so imports work when run from any directory
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.market_intel_agent import run


def main() -> None:
    """Run the market intel agent and print a follow-up action summary."""
    discovered = run()

    if not discovered:
        return

    watchlist_adds = [c for c in discovered if c.get("pipeline_stage") == "watchlist"]
    cold_outreach  = [c for c in discovered if c.get("pipeline_stage") == "cold_outreach"]

    print("\n" + "─" * 60)
    print(f"  {len(watchlist_adds)} added to watchlist · {len(cold_outreach)} cold outreach targets")

    if watchlist_adds:
        print("\n  Next: run the watchlist agent to fetch jobs for new companies:")
        print("    python scripts/run_watchlist.py --min-score 5")

    if cold_outreach:
        print("\n  Cold outreach queue saved to:")
        print("    data/market_intel_queue.json  (pipeline_stage=cold_outreach entries)")
        print("  Next: referral_finder agent will find CTO/ML Lead contacts (coming soon)")

    print()


if __name__ == "__main__":
    main()
