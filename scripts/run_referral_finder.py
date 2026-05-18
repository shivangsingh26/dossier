"""
scripts/run_referral_finder.py — CLI runner for the Referral Finder Agent

Usage:
  # List all jobs with company intel ready (intel.json required), sorted by score
  python scripts/run_referral_finder.py --list

  # Find referrals for a specific job (uses LinkedIn CSV + DDG cold search)
  python scripts/run_referral_finder.py --job-id <job_id>

  # Skip Tier 1 (LinkedIn CSV) — run cold DDG search only
  python scripts/run_referral_finder.py --job-id <job_id> --no-csv

Output (written to data/artifacts/{job_id}/):
  referrals.json — [{name, title, company, linkedin_url, tier, connection_type,
                      outreach_hook, confidence, status}]

Tier 1 (warm):    Existing LinkedIn connections at the company.
                  Requires: profile/linkedin_connections.csv
                  Export from: LinkedIn → Settings → Data Privacy → Get a copy of your data → Connections

Tier 2 (cold):    DuckDuckGo search — college alumni, company alumni, hiring managers, Sr ML/DS.
                  No API key needed. No Tavily credits used.

Tier 3 (message): gpt-5 generates a personalised LinkedIn cold message per contact.
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to path so imports work from any directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def list_available_jobs(artifacts_dir: Path) -> None:
    """Print all jobs that have intel.json ready, sorted by score descending."""
    rows = []
    for job_dir in sorted(artifacts_dir.iterdir()):
        if not job_dir.is_dir():
            continue

        if not (job_dir / "score_card.json").exists():
            continue  # Need at least score_card.json for company name

        score_card_path = job_dir / "score_card.json"
        score = "?"
        relevancy = "?"
        company = "?"
        title = "?"
        already_done = (job_dir / "referrals.json").exists()

        if score_card_path.exists():
            try:
                card = json.loads(score_card_path.read_text(encoding="utf-8"))
                score = card.get("score", "?")
                relevancy = card.get("relevancy", "?").upper()
                company = card.get("company", "?")
                title = card.get("title", "?")
            except (json.JSONDecodeError, KeyError):
                pass

        rows.append((score, relevancy, company, title, job_dir.name, already_done))

    if not rows:
        print("\n  No jobs with company intel found.")
        print("  → Run: python scripts/run_company_intel.py --min-score 7\n")
        return

    rows.sort(key=lambda r: (r[0] if isinstance(r[0], int) else -1), reverse=True)

    print(f"\n{'Score':>5}  {'Relevancy':<8}  {'Company':<28}  {'Title':<35}  {'Done':>4}  Job ID")
    print("-" * 115)
    for score, relevancy, company, title, job_id, already_done in rows:
        done_mark = " ✓" if already_done else "  "
        print(
            f"{str(score):>5}  {relevancy:<8}  {company[:28]:<28}  {title[:35]:<35}  "
            f"{done_mark:>4}  {job_id}"
        )
    print()
    print("  ✓ = referrals.json already generated")
    print("  → To run:         python scripts/run_referral_finder.py --job-id <job_id>")
    print("  → To skip CSV:    python scripts/run_referral_finder.py --job-id <job_id> --no-csv")
    print("  → Needs CSV:      profile/linkedin_connections.csv  (LinkedIn official export)\n")


def _print_referrals(referrals: list[dict], job_id: str) -> None:
    """Print a summary table of referrals found."""
    if not referrals:
        print("\n  No referrals found.\n")
        return

    print(f"\n{'─' * 90}")
    print(f"  Referrals found for: {job_id}  ({len(referrals)} contacts)")
    print(f"{'─' * 90}")

    tier_labels = {1: "Warm", 2: "Cold"}
    type_labels = {
        "warm_connection": "Connected",
        "college_alumni":  "College  ",
        "company_alumni":  "Ex-Employer",
        "cold":            "Cold     ",
    }

    for i, r in enumerate(referrals, 1):
        tier_label = tier_labels.get(r.get("tier", 2), "?")
        type_label = type_labels.get(r.get("connection_type", "cold"), "Cold     ")
        name = r.get("name", "Unknown")[:28]
        title = r.get("title", "")[:35]
        confidence = r.get("confidence", "?")
        url = r.get("linkedin_url", "") or "(no URL — warm connection)"

        print(f"\n  [{i}] {name}  ·  {title}")
        print(f"       Tier {r.get('tier', '?')} ({tier_label}) · {type_label} · confidence: {confidence}")
        print(f"       {url}")

        hook = r.get("outreach_hook", "")
        if hook:
            # Show first 3 lines of the generated message
            lines = [l for l in hook.strip().splitlines() if l.strip()][:3]
            print(f"       ── Message preview ──")
            for line in lines:
                print(f"       {line}")
            if len(hook.strip().splitlines()) > 3:
                print(f"       ...")

    print(f"\n{'─' * 90}")
    print(f"  Full referrals saved to: data/artifacts/{job_id}/referrals.json")
    print(f"{'─' * 90}\n")


def run(job_id: str, no_csv: bool = False) -> None:
    """Run the full referral finder pipeline for a given job_id."""
    from dossier_sdk.config import Config
    from dossier_sdk.agents.referral_finder import run_referral_finder
    from dossier_sdk.core.llm_client import LLMClient
    from dossier_sdk.core.logger import get_logger
    logger = get_logger(__name__)

    config = Config()
    artifact_dir = config.artifacts_dir / job_id

    if not artifact_dir.exists():
        print(f"\n  ✗ Job ID not found: {job_id}")
        print(f"    Expected directory: data/artifacts/{job_id}/")
        sys.exit(1)

    if not (artifact_dir / "intel.json").exists():
        if not (artifact_dir / "score_card.json").exists():
            print(f"\n  ✗ No score_card.json or intel.json found for {job_id}")
            print(f"    Run job discovery first.")
            sys.exit(1)
        print(f"\n  [!] No intel.json for {job_id} — using score_card.json for company name.")
        print(f"      Cold messages will have less company context. Run company intel for richer messages.")
        print(f"      → python scripts/run_company_intel.py --min-score 7")

    csv_path = config.profile_dir / "linkedin_connections.csv"
    if not no_csv and not csv_path.exists():
        print(f"\n  [!] LinkedIn connections CSV not found at: {csv_path}")
        print(f"      Tier 1 (warm connections) will be skipped automatically.")
        print(f"      To get it: LinkedIn → Settings → Data Privacy → Get a copy of your data → Connections")
        print(f"      Continuing with Tier 2 (cold DDG search) only...\n")

    if no_csv:
        print(f"\n[ReferralFinder] --no-csv: skipping Tier 1, running cold DDG search only")

    print(f"\n[ReferralFinder] Starting for job: {job_id}")
    print(f"{'─' * 60}")

    try:
        referrals = run_referral_finder(job_id, skip_csv=no_csv)
    except Exception as e:
        logger.error("Referral finder failed: %s", e, exc_info=True)
        print(f"\n  ✗ Failed: {e}")
        sys.exit(1)

    _print_referrals(referrals, job_id)

    # Cost summary
    usage = LLMClient().get_usage_summary()
    print(f"[Cost] {usage['total_calls']} LLM calls | "
          f"{usage['total_tokens']:,} tokens | "
          f"~${usage['estimated_cost_usd']:.4f} USD")
    for model, stats in usage.get("per_model", {}).items():
        print(f"  {model}: {stats['calls']} calls, "
              f"{stats['prompt_tokens']:,}p + {stats['completion_tokens']:,}c tokens, "
              f"~${stats['cost_usd']:.4f}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find referral contacts at the target company for a specific job.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/run_referral_finder.py --list\n"
            "  python scripts/run_referral_finder.py --job-id grab_data_scientist_high\n"
            "  python scripts/run_referral_finder.py --job-id grab_data_scientist_high --no-csv"
        ),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all jobs with company intel ready, sorted by score",
    )
    parser.add_argument(
        "--job-id",
        type=str,
        help="Job ID to find referrals for",
    )
    parser.add_argument(
        "--no-csv",
        action="store_true",
        help=(
            "Skip Tier 1 (LinkedIn connections CSV) and run cold DDG search only. "
            "Useful before you have exported your connections, or to re-run cold search alone."
        ),
    )
    parser.add_argument(
        "--user", type=str, default="shivang",
        help="Run for this user. Reads from profile/{user}/, writes to data/{user}/. (default: shivang)",
    )
    args = parser.parse_args()

    from dossier_sdk.config import Config
    Config(user=args.user)

    config = Config()

    if args.list:
        list_available_jobs(config.artifacts_dir)
        return

    if args.job_id:
        run(args.job_id, no_csv=args.no_csv)
        return

    print("\nNo arguments provided. Showing available jobs:\n")
    list_available_jobs(config.artifacts_dir)
    print("Usage: python scripts/run_referral_finder.py --job-id <job_id>\n")


if __name__ == "__main__":
    main()
