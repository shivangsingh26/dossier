"""
scripts/run_gap_analysis.py — CLI runner for the Gap Analysis Agent.

Reads all JDs from data/artifacts/*/jd.txt, extracts skills via gpt-5.4-mini,
writes per-job gap.json to each artifact vault, and prints a ranked skill gap
report to the terminal.

USAGE:
  python scripts/run_gap_analysis.py                   # incremental: only new JDs
  python scripts/run_gap_analysis.py --force           # reprocess all JDs
  python scripts/run_gap_analysis.py --min-score 7     # only analyze high-scoring jobs
  python scripts/run_gap_analysis.py --top 15          # show top 15 skills per section

COST GUIDE:
  First run  (~193 JDs): ~$0.07   (193 × ~500 tokens × $0.75/M input)
  Daily runs (~10 new):  ~$0.003  (incremental — only new JDs are extracted)
"""

import argparse
import sys
from pathlib import Path

# Allow running from project root: python scripts/run_gap_analysis.py
sys.path.insert(0, str(Path(__file__).parent.parent))


def main() -> None:
    """Parse CLI args and run the gap analysis pipeline."""
    parser = argparse.ArgumentParser(
        description="Dossier Gap Analysis — extract skills from all JDs and report gaps vs profile.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--user", type=str, default="shivang",
        help="Run for this user. Reads from profile/{user}/, writes to data/{user}/. (default: shivang)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reprocess all JDs even if gap.json already exists (default: skip already-processed).",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=0,
        help=(
            "Only include JDs with LLM score >= this value in the frequency map.\n"
            "Default 0 = include all JDs for the broadest market signal.\n"
            "Use --min-score 7 to focus the report on jobs you're most likely to apply to."
        ),
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Number of skills to show per section in the terminal report. (default: 20)",
    )
    args = parser.parse_args()

    from config import Config
    Config(user=args.user)

    from core.logger import get_logger, setup_logging
    from agents.gap_analysis import run as run_gap_analysis

    logger = get_logger(__name__)

    config = Config()
    setup_logging(config.log_level)

    logger.info(
        f"Gap analysis started | force={args.force} | "
        f"min_score={args.min_score} | top_n={args.top}"
    )

    summary = run_gap_analysis(
        force=args.force,
        min_score=args.min_score,
        top_n=args.top,
    )

    if not summary:
        sys.exit(1)

    logger.info(
        f"Gap analysis complete | "
        f"jds={summary.get('total_jds', 0)} | "
        f"new={summary.get('new_extracted', 0)} | "
        f"required_gaps={summary.get('required_gaps_count', 0)} | "
        f"preferred_gaps={summary.get('preferred_gaps_count', 0)} | "
        f"strong_matches={summary.get('strong_matches_count', 0)} | "
        f"cost=${summary.get('llm_usage', {}).get('estimated_cost_usd', 0):.4f}"
    )


if __name__ == "__main__":
    main()
