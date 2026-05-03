"""
scripts/run_persona_builder.py — Entry point to build your profile.json.

Usage:
    python scripts/run_persona_builder.py

What it does:
    Parses resume + LinkedIn PDFs, runs a 12-question interview,
    synthesises everything into profile/profile.json using Claude.

Run this once before running job discovery.
Re-run only when your situation changes significantly (new project, new skills, etc.)
"""

import sys
from pathlib import Path

# Add project root to path so imports work regardless of where you run from
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.persona_builder import run

if __name__ == "__main__":
    run()
