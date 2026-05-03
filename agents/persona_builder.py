"""
agents/persona_builder.py — Builds profile.json from resume, LinkedIn, and a terminal interview.

Phase A: Plain functions, synchronous, terminal I/O.

PIPELINE:
1. Parse resume PDF + LinkedIn PDF with PyMuPDF → raw text
2. Show extracted summary, ask if anything is missing
3. Run 12-question interview to add evidence + depth PDFs can't capture
4. Load tone.md + voice.md from profile/me/
5. Send everything to claude-sonnet-4-6 → synthesise profile.json
6. Show output, confirm before saving

RUN VIA: python scripts/run_persona_builder.py
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from config import Config
from core.llm_client import LLMClient
from core.logger import get_logger

logger = get_logger(__name__)


PROFILE_ME_DIR = Path("profile/me")
LINKEDIN_PDF   = PROFILE_ME_DIR / "Shivang_Linkedin_Profile.pdf"

# Supported resume formats — script checks for these in order, uses first found
RESUME_CANDIDATES = [
    PROFILE_ME_DIR / "Shivang_Singh_Resume.pdf",
    PROFILE_ME_DIR / "Shivang_Singh_Resume.png",
    PROFILE_ME_DIR / "Shivang_Singh_Resume.jpg",
    PROFILE_ME_DIR / "Shivang_Singh_Resume.jpeg",
]
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

# Pre-filled defaults — user confirms or edits at runtime
IDENTITY_DEFAULTS = {
    "name":             "Shivang Singh",
    "current_role":     "AI Engineer",
    "current_company":  "Publicis Sapient",
    "location":         "Bengaluru, India",
    "education":        "B.Tech CS, IIIT SriCity",
    "months_experience": "11",
    "current_ctc_lpa":  "20",
}

TARGET_DEFAULTS = {
    "min_salary_lpa":       25,
    "preferred_salary_lpa": 30,
    "roles":         ["MLE-1", "AI Engineer", "Applied Scientist", "Data Scientist"],
    "locations":     ["Bengaluru", "Remote"],
    "company_tiers": ["MAANG India", "funded_startup", "top_product_co"],
    "hard_nos":      ["service_company", "no_ml_in_prod"],
    "target_by":     "2027-06",
}

INTERVIEW_QUESTIONS = [
    {
        "id": "technical_depth",
        "question": "Walk me through the most technically complex thing you built. What was the hardest part and how did you solve it?",
        "hint": "Be specific — tool names, what failed, what worked. Numbers help.",
    },
    {
        "id": "scale_impact",
        "question": "What is the largest scale your code has run at? Give numbers — assets processed, requests, data volume, users — whatever fits.",
        "hint": "Even small numbers are fine. We want production evidence, not big-tech scale.",
    },
    {
        "id": "decision_making",
        "question": "Tell me about a technical decision you made and later had to defend or change. What did you pick, why, and what happened?",
        "hint": "No wrong answer. Changing a decision shows engineering maturity.",
    },
    {
        "id": "skill_assessment",
        "question": "List your top 5-7 technical skills and rate each honestly.\n  (a) can_use      — I can work with it\n  (b) can_architect — I can design systems with it\n  (c) can_teach    — I could explain it to others\n\nFormat: one skill per line as  skill: level",
        "hint": "Example:\n  Python: can_teach\n  LangGraph: can_use\n  LLM Eval: can_architect",
    },
    {
        "id": "known_gaps",
        "question": "What technical areas do you know you are weak in right now, and want to build at your next role?",
        "hint": "Honest gaps feed into cover letters and the gap analysis engine.",
    },
    {
        "id": "team_collaboration",
        "question": "Describe a recent project in terms of team structure — how many people, your specific role vs the team, how did you hand off work?",
        "hint": "Helps match culture signals — solo contributor vs team player, startup vs enterprise.",
    },
    {
        "id": "why_ai_eng",
        "question": "Why AI Engineering specifically? What made you choose this over pure SWE or pure data science?",
        "hint": "Your actual answer goes into every cover letter. Take your time with this one.",
    },
    {
        "id": "good_week",
        "question": "At your next company, what does a good week look like? Describe the work, team size, and how you would feel at the end of it.",
        "hint": "Used to match against Glassdoor reviews and company culture signals.",
    },
    {
        "id": "hard_nos",
        "question": "What would make you leave a role within 6 months? What is a hard no for you in a company or team?",
        "hint": "Used to filter out companies during job scoring.",
    },
    {
        "id": "strongest_asset",
        "question": "What is the one thing you do better than most engineers at your level? The thing you would bet on in a direct comparison?",
        "hint": "This becomes the opening line of your strongest cover letters.",
    },
    {
        "id": "side_projects",
        "question": "What have you built, learned, or shipped outside your job in the last 12 months? Does not matter how small.",
        "hint": "Self-directed learning is a very high signal for MLE and AI Engineer roles.",
    },
    {
        "id": "referral_pitch",
        "question": "If someone at Google or Sarvam asked 'why should I refer you?' — what is your honest 3-sentence answer?",
        "hint": "The Referral Finder Agent uses this directly. Write in your own natural voice.",
    },
]

SYNTHESIS_SYSTEM_PROMPT = """You are a profile synthesis engine for a job search system called Dossier.

Your input: resume text, LinkedIn text, a structured interview, and the candidate's tone + voice files.
Your output: a single profile.json that will drive all downstream agents — job scoring, cold messages, resume tailoring, cover letters.

Rules:
- Evidence-mapped skills: every skill entry has specific proof from their actual work, not just a name
- Honest depth: infer depth from HOW they described using the skill — do not inflate
- Use the candidate's exact project names, tool names, and numbers in evidence fields
- market_aliases: 3-5 common JD keyword variants per skill so job scoring can match them
- known_gaps: extract from their own words, do not invent
- career_narrative: use their words, clean up typos only
- The resume and LinkedIn are the source of truth for roles, dates, education
- The interview adds depth and evidence that the resume cannot capture

Output ONLY valid JSON. No markdown fences, no explanation, nothing before or after the JSON object.

Schema:
{
  "identity": {
    "name": "string",
    "current_role": "string",
    "current_company": "string",
    "months_experience": number,
    "current_ctc_lpa": number,
    "education": "string",
    "location": "string"
  },
  "target": {
    "roles": ["string"],
    "min_salary_lpa": number,
    "preferred_salary_lpa": number,
    "locations": ["string"],
    "company_tiers": ["string"],
    "hard_nos": ["string"],
    "target_by": "string"
  },
  "skills": [
    {
      "skill": "string",
      "evidence": "string",
      "depth": "can_use or can_architect or can_teach",
      "last_used": "current or recent or YYYY-MM",
      "market_aliases": ["string"]
    }
  ],
  "known_gaps": ["string"],
  "career_narrative": {
    "why_ai_eng": "string",
    "strongest_asset": "string",
    "referral_pitch": "string",
    "good_week_looks_like": "string",
    "hard_nos_detail": "string"
  },
  "tone_ref": "profile/me/tone.md",
  "voice_ref": "profile/me/voice.md",
  "writing_samples_ref": "profile/writing_samples/",
  "github": {
    "username": "string or null",
    "top_repos": ["string"],
    "primary_languages": ["string"]
  },
  "meta": {
    "last_updated": "string",
    "sources_ingested": ["string"],
    "validation_status": "human_validated"
  }
}"""


# ─── Resume Parsing — handles both PDF and image formats ─────────────────────

def find_resume_file() -> Path | None:
    """Return the first resume file found from RESUME_CANDIDATES list."""
    for candidate in RESUME_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def parse_resume(resume_path: Path) -> str:
    """
    Extract text from a resume file. Supports both PDF and image formats.

    - PDF  → PyMuPDF (fitz) extracts text directly, fast and accurate
    - PNG/JPG/JPEG → Claude vision API reads the image and extracts text

    WHY TWO METHODS:
    PyMuPDF extracts text embedded in the PDF (vector text), which is perfect.
    Images have no embedded text — we need a vision model to read them pixel by pixel.
    Claude Haiku handles this cheaply and accurately in one API call.
    """
    if not resume_path.exists():
        logger.warning(f"Resume file not found: {resume_path}")
        return ""

    suffix = resume_path.suffix.lower()

    if suffix == ".pdf":
        return _parse_pdf(resume_path)
    elif suffix in IMAGE_EXTENSIONS:
        return _parse_image(resume_path)
    else:
        logger.warning(f"Unsupported resume format: {suffix}. Expected PDF or image.")
        return ""


def _parse_pdf(pdf_path: Path) -> str:
    """Extract text from a PDF using PyMuPDF."""
    import fitz  # PyMuPDF — import name is fitz, package name is pymupdf
    doc = fitz.open(str(pdf_path))
    pages = [page.get_text() for page in doc]
    doc.close()
    text = "\n".join(pages).strip()
    logger.info(f"Parsed PDF: {pdf_path.name} — {len(text)} chars, {len(pages)} pages")
    return text


def _parse_image(image_path: Path) -> str:
    """Extract text from an image resume using Claude's vision API."""
    llm = LLMClient()
    logger.info(f"Parsing image resume via Claude vision: {image_path.name}")
    text = llm.call_vision(
        image_path=image_path,
        prompt=(
            "This is a resume image. Extract ALL text from it exactly as it appears — "
            "preserve section headings, bullet points, company names, dates, and metrics. "
            "Do not summarise or skip anything. Output plain text only."
        ),
    )
    logger.info(f"Image resume extracted — {len(text)} chars")
    return text


def parse_linkedin_pdf(pdf_path: Path) -> str:
    """Extract text from a LinkedIn PDF export using PyMuPDF."""
    if not pdf_path.exists():
        logger.warning(f"LinkedIn PDF not found: {pdf_path}")
        return ""
    import fitz
    doc = fitz.open(str(pdf_path))
    pages = [page.get_text() for page in doc]
    doc.close()
    text = "\n".join(pages).strip()
    logger.info(f"Parsed LinkedIn PDF: {pdf_path.name} — {len(text)} chars")
    return text


def load_supporting_files() -> str:
    """Load tone.md and voice.md for the LLM to understand writing style."""
    content = ""
    for filepath in [PROFILE_ME_DIR / "tone.md", PROFILE_ME_DIR / "voice.md"]:
        if filepath.exists():
            content += f"\n\n--- {filepath.name} ---\n{filepath.read_text(encoding='utf-8')}"
    return content


# ─── Terminal I/O helpers ─────────────────────────────────────────────────────

def ask(question: str, hint: str = "") -> str:
    """Print a question and collect a multi-line answer. Press Enter twice to submit."""
    print(f"\n{'─' * 64}")
    print(f"  {question}")
    if hint:
        print(f"\n  Hint: {hint}")
    print(f"{'─' * 64}")
    print("  Your answer (press Enter twice when done):\n")
    lines = []
    while True:
        line = input("  ")
        if line == "" and lines and lines[-1] == "":
            break
        lines.append(line)
    return "\n".join(lines).strip()


def confirm(label: str, default: str) -> str:
    """Show a pre-filled value. Press Enter to accept, or type to override."""
    user_input = input(f"  {label} [{default}]: ").strip()
    return user_input if user_input else default


# ─── Interview ────────────────────────────────────────────────────────────────

def collect_targets() -> dict:
    """Ask the user to confirm job targets. Returns target dict."""
    print("\n  JOB TARGETS — confirm or edit\n")
    target = dict(TARGET_DEFAULTS)

    min_sal = confirm("Minimum target salary (LPA)", str(TARGET_DEFAULTS["min_salary_lpa"]))
    target["min_salary_lpa"] = int(min_sal) if min_sal.isdigit() else TARGET_DEFAULTS["min_salary_lpa"]

    pref_sal = confirm("Preferred target salary (LPA)", str(TARGET_DEFAULTS["preferred_salary_lpa"]))
    target["preferred_salary_lpa"] = int(pref_sal) if pref_sal.isdigit() else TARGET_DEFAULTS["preferred_salary_lpa"]

    return target


def conduct_interview() -> dict:
    """Run the 12-question interview. Returns answers dict."""
    print("\n\n  INTERVIEW — 12 questions")
    print("  Take your time. Specific answers produce better job matches.")
    print("  Press Enter TWICE after each answer to move to the next.\n")

    answers = {}
    for i, q in enumerate(INTERVIEW_QUESTIONS, 1):
        print(f"\n  Question {i} of {len(INTERVIEW_QUESTIONS)}")
        answers[q["id"]] = ask(q["question"], q["hint"])
    return answers


# ─── Synthesis ────────────────────────────────────────────────────────────────

def synthesize_profile(
    resume_text: str,
    linkedin_text: str,
    target: dict,
    interview_answers: dict,
    github_username: str,
    supporting_files: str,
) -> dict:
    """Send all collected data to claude-sonnet-4-6. Returns parsed profile.json dict."""
    llm = LLMClient()
    config = Config()

    user_prompt = f"""
=== RESUME (parsed from PDF) ===
{resume_text[:6000]}

=== LINKEDIN PROFILE (parsed from PDF) ===
{linkedin_text[:4000]}

=== JOB TARGETS (confirmed by candidate) ===
{json.dumps(target, indent=2)}

=== INTERVIEW ANSWERS ===
{json.dumps(interview_answers, indent=2)}

=== GITHUB USERNAME ===
{github_username or "not provided"}

=== TONE + VOICE FILES ===
{supporting_files}

=== TODAY'S DATE ===
{datetime.now(timezone.utc).strftime("%Y-%m-%d")}

=== INSTRUCTIONS ===
- Resume + LinkedIn are the source of truth for roles, companies, dates, education
- Interview answers add depth, evidence, and specifics that resumes cannot capture
- For each skill, write evidence using actual project names and numbers from the resume/interview
- market_aliases should cover how JDs phrase the same skill (vary the wording)
- meta.sources_ingested: ["resume", "linkedin", "interview", "tone_file", "voice_file"]
"""

    print("\n  Sending to claude-sonnet-4-6 for synthesis...")
    print("  This takes about 20-30 seconds.\n")

    raw = llm.call(
        system_prompt=SYNTHESIS_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        model=config.model_resume,  # claude-sonnet-4-6
        max_tokens=4096,
    )

    # Strip accidental markdown fences
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
        cleaned = cleaned.rsplit("```", 1)[0].strip()

    return json.loads(cleaned)


def save_profile(profile: dict) -> None:
    """Save the final profile dict to profile/profile.json."""
    config = Config()
    config.profile_path.parent.mkdir(parents=True, exist_ok=True)
    config.profile_path.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(f"Profile saved to {config.profile_path}")
    print(f"\n  Saved → {config.profile_path}")


# ─── Main entry point ─────────────────────────────────────────────────────────

def run() -> None:
    """Run the full persona builder pipeline."""
    print("\n" + "═" * 64)
    print("  DOSSIER — Persona Builder")
    print("  Builds profile.json from your resume, LinkedIn, and a short interview.")
    print("  This runs once. Re-run only when your situation changes significantly.")
    print("═" * 64)

    # Step 1: Parse resume + LinkedIn
    print("\n  Step 1/4 — Parsing resume and LinkedIn profile...")

    resume_file = find_resume_file()
    if not resume_file:
        print(f"\n  Warning: No resume file found in {PROFILE_ME_DIR}/")
        print(f"  Expected one of: Shivang_Singh_Resume.pdf / .png / .jpg")
        resume_text = ""
    else:
        print(f"  Found resume: {resume_file.name} ({'image — using Claude vision' if resume_file.suffix.lower() in IMAGE_EXTENSIONS else 'PDF — using PyMuPDF'})")
        resume_text = parse_resume(resume_file)
        print(f"  Resume parsed OK ({len(resume_text)} chars)")

    linkedin_text = parse_linkedin_pdf(LINKEDIN_PDF)
    if not linkedin_text:
        print(f"  Warning: Could not parse LinkedIn PDF at {LINKEDIN_PDF}")
    else:
        print(f"  LinkedIn parsed OK ({len(linkedin_text)} chars)")

    # Step 2: Confirm targets
    print("\n  Step 2/4 — Confirm job targets")
    target = collect_targets()

    # Step 3: Interview
    print("\n  Step 3/4 — Interview")
    interview_answers = conduct_interview()

    github_username = confirm("\n  GitHub username (optional, press Enter to skip)", "").strip() or None

    # Step 4: Synthesize
    print("\n  Step 4/4 — Synthesising profile.json")
    supporting_files = load_supporting_files()

    try:
        profile = synthesize_profile(
            resume_text=resume_text,
            linkedin_text=linkedin_text,
            target=target,
            interview_answers=interview_answers,
            github_username=github_username,
            supporting_files=supporting_files,
        )
    except json.JSONDecodeError as e:
        print(f"\n  Error: Claude returned invalid JSON — {e}")
        print("  Try re-running. If it keeps failing, check your ANTHROPIC_API_KEY.")
        return

    # Show result and ask to save
    print("\n" + "═" * 64)
    print("  GENERATED profile.json — review before saving:")
    print("═" * 64 + "\n")
    print(json.dumps(profile, indent=2, ensure_ascii=False))

    print("\n" + "═" * 64)
    save_it = input("  Save as profile/profile.json? (yes/no): ").strip().lower()
    if save_it in ("yes", "y"):
        save_profile(profile)
        print("  Done. Run scripts/run_job_discovery.py next.")
    else:
        print("  Not saved. Re-run when ready.")
