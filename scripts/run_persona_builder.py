"""
scripts/run_persona_builder.py — Entry point to build a user's profile.json.

Usage:
    # Interactive mode (Shivang's own profile — terminal interview)
    python scripts/run_persona_builder.py

    # File mode (build a friend's profile from their filled questionnaire)
    python scripts/run_persona_builder.py --user anushthan --answers profile/anushthan/questionnaire.md
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import Config


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dossier persona builder")
    parser.add_argument(
        "--user", type=str, default="shivang",
        help="User to build profile for. Reads from profile/{user}/. (default: shivang)"
    )
    parser.add_argument(
        "--answers", type=str, default=None,
        help="Path to filled questionnaire.md. If omitted, runs interactive interview."
    )
    args = parser.parse_args()

    # Initialise Config with the user BEFORE importing the agent
    Config(user=args.user)

    from agents.persona_builder import run

    answers_path = Path(args.answers) if args.answers else None
    if answers_path and not answers_path.exists():
        print(f"Error: answers file not found: {answers_path}")
        sys.exit(1)

    run(answers_path=answers_path)
