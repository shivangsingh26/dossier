"""
scripts/export_questionnaire.py — Generate a fillable questionnaire to send to a user.

Usage:
    python scripts/export_questionnaire.py --user anushthan
    python scripts/export_questionnaire.py --user sambhav

Creates profile/{user}/questionnaire.md with all 12 interview questions + basic info fields.
Send the file to the user (WhatsApp, email, Google Drive). They fill it, send back.
When you have the filled file, run:
    python scripts/run_persona_builder.py --user anushthan --answers profile/anushthan/questionnaire.md
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dossier_sdk.agents.persona_builder import INTERVIEW_QUESTIONS

# Q7 is ML-specific in the default interview — override with a generic version
GENERIC_Q7 = (
    "Why are you targeting these specific roles and companies? "
    "What made you choose this direction over other paths you could have taken?"
)

QUESTION_TITLES = [
    "Technical Depth",
    "Scale and Impact",
    "Decision Making",
    "Skill Assessment",
    "Known Gaps",
    "Team Collaboration",
    "Why This Direction",
    "Good Week Vision",
    "Hard Nos Detail",
    "Strongest Asset",
    "Side Projects",
    "Referral Pitch",
    "Your Voice",
]

HEADER = """\
DOSSIER — PROFILE QUESTIONNAIRE
================================
For: {user}

INSTRUCTIONS:
  - Fill in every section. Be specific — tool names, project names, and
    numbers produce significantly better job matches.
  - For multi-line answers: just keep writing after "Answer:" — the next
    [Qn] marker ends the previous answer.
  - Do NOT use [Q or == on a line by itself — those are reserved markers.
  - Save the file and send it back when done.
  - Also drop these 3 files into profile/{user}/ and send them along:
      1. Resume PDF (any filename, must NOT contain "linkedin")
      2. LinkedIn profile PDF (filename must contain "linkedin")
      3. LinkedIn connections CSV — export from:
         LinkedIn → Settings → Data Privacy → Get a copy of your data → Connections
         This enables warm referral matching (people you already know at target companies).

================================
== BASIC INFO ==
================================

Name:
Current title / role (e.g. Software Engineer, Data Scientist):
Short title — 2-3 words to use in casual intros (e.g. Backend Engineer, AI Engineer):
Current company (write NONE if student or between jobs):
City / location (e.g. Bengaluru, India):
Education (e.g. B.Tech CS, IIIT SriCity):
Full-time months of experience (write 0 if fresher / student):
Internship months of experience (write 0 if none):
Current CTC in LPA (write 0 if student or not disclosed):
Notice period in months (write 0 if immediate joiner or student):
GitHub username (leave blank if none):
WorkStyle: (e.g. Hybrid 2-3 days / Remote only / In-office / Flexible)
Relocation: (leave blank if no; or list cities e.g. Pune, Hyderabad)

================================
== JOB TARGETS ==
================================

What job titles are you targeting? (comma separated)
TargetRoles:

Minimum salary you will accept (in LPA):
MinSalary:

Preferred / expected salary (in LPA):
PrefSalary:

Locations you will work in (comma separated, e.g. Bengaluru, Remote):
Locations:

Types of companies or work you will NEVER join — your hard nos:
(e.g. service companies like TCS/Infosys, bond agreements, no equity < 0.1%)
HardNos:

By when do you want to switch? (e.g. 2027-01):
TargetBy:

================================
== INTERVIEW ==
================================
"""

QUESTION_BLOCK = """\
[Q{n}] {title}
{question}
Tip: {hint}

Answer:


"""


def build_questions_text() -> str:
    blocks = []
    for i, q in enumerate(INTERVIEW_QUESTIONS, 1):
        question_text = GENERIC_Q7 if q["id"] == "why_ai_eng" else q["question"]
        blocks.append(QUESTION_BLOCK.format(
            n=i,
            title=QUESTION_TITLES[i - 1],
            question=question_text,
            hint=q["hint"],
        ))
    return "".join(blocks)


def export_questionnaire(user: str) -> Path:
    """Create profile/{user}/ and write questionnaire.md. Returns the file path."""
    profile_dir = Path("profile") / user
    profile_dir.mkdir(parents=True, exist_ok=True)

    output_path = profile_dir / "questionnaire.md"
    content = HEADER.format(user=user) + build_questions_text()
    output_path.write_text(content, encoding="utf-8")
    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate a profile questionnaire to send to a user."
    )
    parser.add_argument("--user", required=True, help="Username, e.g. anushthan, sambhav")
    args = parser.parse_args()

    path = export_questionnaire(args.user)

    print(f"\nQuestionnaire written → {path}")
    print(f"\nNext steps:")
    print(f"  1. Ask {args.user} to drop resume PDF + LinkedIn PDF into:  profile/{args.user}/")
    print(f"       Resume:   any PDF not containing 'linkedin' in the filename")
    print(f"       LinkedIn: any PDF with 'linkedin' in the filename")
    print(f"  2. Send them:  profile/{args.user}/questionnaire.md")
    print(f"       They fill every section and return the filled file.")
    print(f"  3. Place the returned file back at:  profile/{args.user}/questionnaire.md")
    print(f"  4. Run the builder:")
    print(f"       python scripts/run_persona_builder.py --user {args.user} --answers profile/{args.user}/questionnaire.md")
