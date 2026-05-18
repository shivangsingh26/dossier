"""
agents/persona_builder.py — Builds profile.json from resume, LinkedIn, and a terminal interview.

Phase A: Plain functions, synchronous, terminal I/O.

PIPELINE:
1. Parse resume PDF + LinkedIn PDF with PyMuPDF → raw text
2. Show extracted summary, ask if anything is missing
3. Run 12-question interview to add evidence + depth PDFs can't capture
4. Load tone.md + voice.md from profile/{user}/
5. Send everything to claude-sonnet-4-6 → synthesise profile.json
6. Show output, confirm before saving

RUN VIA: python scripts/run_persona_builder.py
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from dossier_sdk.config import Config
from dossier_sdk.core.llm_client import LLMClient
from dossier_sdk.core.logger import get_logger

logger = get_logger(__name__)


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
        "id": "why_this_direction",
        "question": "Why are you targeting these specific roles and companies? What made you choose this direction over other paths you could have taken?",
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
        "hint": "Self-directed learning is a strong signal for engineering roles. Any size counts.",
    },
    {
        "id": "referral_pitch",
        "question": "If someone at Google or Sarvam asked 'why should I refer you?' — what is your honest 3-sentence answer?",
        "hint": "The Referral Finder Agent uses this directly. Write in your own natural voice.",
    },
    {
        "id": "voice_sample",
        "question": "Write 2–3 sentences as you'd write in a casual LinkedIn message introducing yourself to a hiring manager. Natural voice — not formal, not a pitch.",
        "hint": "Example: 'Hey, I'm Alex — Backend Engineer at Acme. I've spent the past year building distributed data pipelines and I'm looking to move to a product company with larger scale.'",
    },
]


def find_user_pdfs(profile_dir: Path) -> tuple[Path | None, Path | None]:
    """
    Scan profile_dir for resume and LinkedIn PDFs.
    LinkedIn: any PDF with "linkedin" (case-insensitive) in the filename.
    Resume: any other PDF found in the directory.
    Returns (resume_path, linkedin_path) — either can be None if not found.
    """
    pdfs = list(profile_dir.glob("*.pdf")) + list(profile_dir.glob("*.PDF"))
    linkedin_pdf = None
    resume_pdf = None
    for pdf in pdfs:
        if "linkedin" in pdf.name.lower():
            linkedin_pdf = pdf
        elif resume_pdf is None:
            resume_pdf = pdf
    return resume_pdf, linkedin_pdf


def parse_questionnaire_file_from_string(content: str) -> dict:
    """
    Parse a filled questionnaire.md string into identity, target, and interview_answers.
    Returns dict with keys: identity, target, interview_answers.
    Used by parse_questionnaire_file() and directly in tests.
    """
    lines = content.splitlines()

    def extract_field(label: str) -> str:
        """Find 'Label: value' in lines, return value stripped."""
        for line in lines:
            if line.strip().startswith(label + ":"):
                return line.split(":", 1)[1].strip()
        return ""

    def extract_list_field(label: str) -> list[str]:
        """Find 'Label: a, b, c' and return as list."""
        raw = extract_field(label)
        return [item.strip() for item in raw.split(",") if item.strip()]

    def safe_int(value: str, fallback: int) -> int:
        try:
            return int(float(value))  # handles "37.4", "17 months..." → graceful
        except (ValueError, TypeError):
            return fallback

    # Support both new split fields and old single "Total months" field for backward compat
    _ft_raw    = extract_field("Full-time months of experience (write 0 if fresher / student)")
    _total_raw = extract_field("Total months of professional work experience (write 0 if fresher)")
    _full_time_months = safe_int(_ft_raw, 0) if _ft_raw else safe_int(_total_raw, 0)
    _intern_months    = safe_int(extract_field("Internship months of experience (write 0 if none)"), 0)

    # Work style and relocation — values come from the questionnaire file
    _work_style_raw = extract_field("WorkStyle")
    _work_style = _work_style_raw.strip() if _work_style_raw.strip() else ""

    _relocation_raw = extract_field("Relocation").strip()
    _open_to_relocation = bool(_relocation_raw) and _relocation_raw.lower() not in ("no", "none", "n/a", "-")
    _relocation_cities = [c.strip() for c in _relocation_raw.split(",")
                          if c.strip() and c.strip().lower() not in ("yes", "no", "none", "n/a")]

    identity = {
        "name":               extract_field("Name"),
        "current_role":       extract_field("Current title / role (e.g. Software Engineer, Data Scientist)"),
        "short_title":        extract_field("Short title — 2-3 words to use in casual intros (e.g. Backend Engineer, AI Engineer)"),
        "current_company":    extract_field("Current company (write NONE if student or between jobs)"),
        "location":           extract_field("City / location (e.g. Bengaluru, India)"),
        "education":          extract_field("Education (e.g. B.Tech CS, IIIT SriCity)"),
        "full_time_months":   _full_time_months,
        "intern_months":      _intern_months,
        "current_ctc_lpa":    safe_int(extract_field("Current CTC in LPA (write 0 if student or not disclosed)"), 0),
        "notice_period_months": safe_int(extract_field("Notice period in months (write 0 if immediate joiner or student)"), 0),
        "github_username":    extract_field("GitHub username (leave blank if none)") or None,
        "work_style":         _work_style,
        "open_to_relocation": _open_to_relocation,
        "relocation_cities":  _relocation_cities,
    }

    target = {
        "roles":                extract_list_field("TargetRoles"),
        "min_salary_lpa":       safe_int(extract_field("MinSalary"), 0),
        "preferred_salary_lpa": safe_int(extract_field("PrefSalary"), 0),
        "locations":            extract_list_field("Locations"),
        "hard_nos":             extract_list_field("HardNos"),
        "target_by":            extract_field("TargetBy"),
        "company_tiers":        ["MAANG India", "funded_startup", "top_product_co"],
    }

    question_pattern = re.compile(r"^\[Q(\d+)\]", re.MULTILINE)
    answer_pattern   = re.compile(r"Answer:\s*\n(.*?)(?=\[Q\d+\]|\Z)", re.DOTALL)
    q_id_by_index    = {i + 1: q["id"] for i, q in enumerate(INTERVIEW_QUESTIONS)}

    interview_answers: dict[str, str] = {}
    for match in question_pattern.finditer(content):
        q_num  = int(match.group(1))
        q_id   = q_id_by_index.get(q_num)
        if not q_id:
            continue
        next_match  = question_pattern.search(content, match.end())
        block_end   = next_match.start() if next_match else len(content)
        block       = content[match.start():block_end]
        ans_match   = answer_pattern.search(block)
        interview_answers[q_id] = ans_match.group(1).strip() if ans_match else ""

    return {
        "identity":          identity,
        "target":            target,
        "interview_answers": interview_answers,
    }


def parse_questionnaire_file(path: Path) -> dict:
    """
    Read a filled questionnaire.md from disk and parse it.
    Returns the same dict as parse_questionnaire_file_from_string().
    """
    content = path.read_text(encoding="utf-8")
    return parse_questionnaire_file_from_string(content)


SYNTHESIS_SYSTEM_PROMPT = """You are a profile synthesis engine for a job search system called Dossier.

Your input: resume text, LinkedIn text, a structured interview, and the candidate's tone + voice files.
Your output: a single profile.json that will drive all downstream agents — job scoring, cold messages, resume tailoring, cover letters.

CLASH RESOLUTION — when resume and LinkedIn disagree on the same fact:
- Job title: resume wins (official document used in background checks)
- Employment dates: LinkedIn wins (more precise month/year, more recently maintained)
- Metrics and numbers (%, FPS, latency, scale): resume wins (LinkedIn rarely has precise numbers)
- Skills: use BOTH sources — merge all skills, never discard from either
- Bio / summary narrative: LinkedIn wins (richer, more current)
- Education institution and degree: resume wins
- Education grades / CGPA: resume wins (LinkedIn rarely shows grades)
- Location / current city: LinkedIn wins (reflects current status)
- Certifications: LinkedIn wins (this is the definitive maintained list)
- Contact / GitHub / links: LinkedIn wins (from contact section)
- Project descriptions: merge the best of both — resume has concise metrics, LinkedIn may have more detail

EXTRACTION RULES:
- skills: every entry must have specific proof (project name + number) from actual work; infer depth from HOW they described use, do not inflate
- market_aliases: 3-5 JD keyword variants per skill for job scoring matching
- known_gaps: extract from candidate's own words only — do not invent
- career_narrative: use their exact words, clean typos only
- short_title: copy EXACTLY from questionnaire "Short title" field — never infer from LinkedIn headline or target roles
- full_time_months: from questionnaire if provided; else infer from resume timeline counting only full-time roles (exclude intern/trainee titles)
- intern_months: from questionnaire if provided; else infer from resume counting internship/trainee roles only
- search_terms: 6-10 exact job title strings for Indeed/LinkedIn APIs — match how real postings are titled (e.g. "Software Engineer", "SDE-2", not "SWE")
- watchlist_title_keywords: 8-15 lowercase partial keywords to substring-match job titles — shorter catches variants (e.g. "backend" catches "Backend Engineer" AND "Senior Backend Engineer")
- role_domain: exactly one of "ml_ai" (ML/AI/Data Science), "sde" (software engineering), "data" (data analyst/BI/analytics), "other"
- certifications: extract ALL certs from LinkedIn "Certifications" section and resume — include name, issuer, year if available; empty array if none
- publications: extract ALL research papers, conference papers, patents from resume and LinkedIn — include title, venue, year, url if present; empty array if none
- key_projects: extract 3-5 most impressive projects from resume — exact project names, impact-focused one-sentence description, full tech stack, specific metric/outcome, URL if listed, type (work/personal/open_source); order: work projects with production metrics first
- preferred_work_style: copy from questionnaire WorkStyle field verbatim
- open_to_relocation: true only if questionnaire Relocation field has a non-empty, non-"no" value
- relocation_cities: list of cities from questionnaire Relocation field; empty array if not open to relocation

Output ONLY valid JSON. No markdown fences, no explanation, nothing before or after the JSON object.

Schema:
{
  "identity": {
    "name": "string",
    "short_title": "string",
    "current_role": "string",
    "current_company": "string",
    "full_time_months": number,
    "intern_months": number,
    "current_ctc_lpa": number,
    "notice_period_months": number,
    "education": "string",
    "location": "string"
  },
  "target": {
    "roles": ["string"],
    "role_domain": "ml_ai or sde or data or other",
    "search_terms": ["string"],
    "watchlist_title_keywords": ["string"],
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
    "why_this_direction": "string",
    "strongest_asset": "string",
    "referral_pitch": "string",
    "good_week_looks_like": "string",
    "hard_nos_detail": "string",
    "voice_sample": "string"
  },
  "certifications": [
    {"name": "string", "issuer": "string", "year": "string or null"}
  ],
  "publications": [
    {"title": "string", "venue": "string", "year": "string or null", "url": "string or null"}
  ],
  "key_projects": [
    {
      "name": "string",
      "description": "string — one sentence, impact-focused",
      "tech_stack": ["string"],
      "impact": "string — specific metric, outcome, or result",
      "url": "string or null",
      "type": "work or personal or open_source"
    }
  ],
  "preferred_work_style": "string",
  "open_to_relocation": false,
  "relocation_cities": ["string"],
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


def load_supporting_files(profile_dir: Path) -> str:
    """Load tone.md and voice.md for the LLM to understand writing style."""
    content = ""
    for filename in ["tone.md", "voice.md"]:
        filepath = profile_dir / filename
        if filepath.exists():
            content += f"\n\n--- {filename} ---\n{filepath.read_text(encoding='utf-8')}"
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
    profile_dir: Path,
    questionnaire_identity: dict | None = None,
    full_time_months: int = 0,
    intern_months: int = 0,
    work_style: str = "",
    open_to_relocation: bool = False,
    relocation_cities: list | None = None,
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

=== IDENTITY FROM QUESTIONNAIRE (use these values VERBATIM in identity fields) ===
{json.dumps(questionnaire_identity or {}, indent=2)}
Rules for identity fields:
- short_title: copy EXACTLY from questionnaire — never infer from LinkedIn headline or target roles
- current_ctc_lpa: use questionnaire value (0 only if questionnaire says 0 or not disclosed)
- notice_period_months: use questionnaire value
- name, current_role, current_company, education, location: questionnaire + resume/LinkedIn both valid; prefer resume/LinkedIn for objective facts

=== EXPERIENCE FROM QUESTIONNAIRE ===
full_time_months (questionnaire): {full_time_months} (0 = not provided; infer from resume timeline if 0)
intern_months (questionnaire): {intern_months} (0 = not provided or none; infer from resume timeline if 0)

=== WORK PREFERENCES FROM QUESTIONNAIRE ===
preferred_work_style: {work_style or "not specified"}
open_to_relocation: {open_to_relocation}
relocation_cities: {relocation_cities or []}

=== INSTRUCTIONS ===
- Follow all clash resolution and extraction rules from the system prompt exactly
- Interview answers add depth, evidence, and specifics that resumes cannot capture
- meta.sources_ingested: always include "resume", "linkedin", "interview"; add "tone_file" only if TONE + VOICE FILES section above is non-empty
"""

    print("\n  Sending to claude-sonnet-4-6 for synthesis...")
    print("  This takes about 20-30 seconds.\n")

    raw = llm.call(
        system_prompt=SYNTHESIS_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        model=config.model_resume,  # claude-sonnet-4-6
        max_tokens=6000,
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

def run(answers_path: Path | None = None) -> None:
    """
    Run the full persona builder pipeline.
    answers_path: if provided, parse a filled questionnaire.md instead of running
                  an interactive interview. Used for building friend profiles.
    """
    config      = Config()
    profile_dir = config.profile_dir
    is_file_mode = answers_path is not None

    print("\n" + "═" * 64)
    print("  DOSSIER — Persona Builder")
    if is_file_mode:
        print(f"  File mode: reading answers from {answers_path}")
    else:
        print("  Interactive mode: terminal interview")
    print("═" * 64)

    # Step 1: Parse resume + LinkedIn
    print(f"\n  Step 1/4 — Parsing resume and LinkedIn profile from {profile_dir}/")
    resume_pdf, linkedin_pdf = find_user_pdfs(profile_dir)

    if not resume_pdf:
        print(f"\n  Warning: No resume PDF found in {profile_dir}/")
        resume_text = ""
    else:
        print(f"  Found resume: {resume_pdf.name}")
        resume_text = parse_resume(resume_pdf)
        print(f"  Resume parsed OK ({len(resume_text)} chars)")

    if not linkedin_pdf:
        print(f"  Warning: No LinkedIn PDF found in {profile_dir}/")
        print("  Tip: rename your LinkedIn PDF to include 'linkedin' in the filename.")
        linkedin_text = ""
    else:
        linkedin_text = parse_linkedin_pdf(linkedin_pdf)
        if linkedin_text:
            print(f"  LinkedIn parsed OK ({len(linkedin_text)} chars)")

    # Step 2: Get targets and interview answers
    full_time_months      = 0
    intern_months         = 0
    questionnaire_identity = None
    if is_file_mode:
        print(f"\n  Step 2/4 — Parsing questionnaire from {answers_path}")
        parsed = parse_questionnaire_file(answers_path)
        target                 = parsed["target"]
        interview_answers      = parsed["interview_answers"]
        questionnaire_identity = parsed["identity"]
        github_username        = questionnaire_identity.get("github_username")
        full_time_months       = questionnaire_identity.get("full_time_months", 0)
        intern_months          = questionnaire_identity.get("intern_months", 0)
        work_style             = questionnaire_identity.get("work_style", "")
        open_to_relocation     = questionnaire_identity.get("open_to_relocation", False)
        relocation_cities      = questionnaire_identity.get("relocation_cities", [])
        print(f"  Parsed {len(interview_answers)} answers, "
              f"{len(target['roles'])} target roles")
    else:
        print("\n  Step 2/4 — Confirm job targets")
        target = collect_targets()
        print("\n  Step 3/4 — Interview")
        interview_answers = conduct_interview()
        github_username = confirm("\n  GitHub username (optional, press Enter to skip)", "").strip() or None

    # Step 3: Synthesize
    print("\n  Step 4/4 — Synthesising profile.json")
    supporting_files = load_supporting_files(profile_dir)

    try:
        profile = synthesize_profile(
            resume_text=resume_text,
            linkedin_text=linkedin_text,
            target=target,
            interview_answers=interview_answers,
            github_username=github_username,
            supporting_files=supporting_files,
            profile_dir=profile_dir,
            questionnaire_identity=questionnaire_identity,
            full_time_months=full_time_months,
            intern_months=intern_months,
            work_style=work_style,
            open_to_relocation=open_to_relocation,
            relocation_cities=relocation_cities,
        )
    except json.JSONDecodeError as e:
        print(f"\n  Error: Claude returned invalid JSON — {e}")
        print("  Try re-running. If it keeps failing, check your ANTHROPIC_API_KEY.")
        return

    # Inject file refs deterministically — only include paths that exist on disk
    for filename, key in [("tone.md", "tone_ref"), ("voice.md", "voice_ref")]:
        if (profile_dir / filename).exists():
            profile[key] = str(profile_dir / filename)
        else:
            profile.pop(key, None)
    writing_samples_dir = profile_dir / "writing_samples"
    if writing_samples_dir.exists():
        profile["writing_samples_ref"] = str(writing_samples_dir) + "/"
    else:
        profile.pop("writing_samples_ref", None)

    # Show result
    print("\n" + "═" * 64)
    print("  GENERATED profile.json — review before saving:")
    print("═" * 64 + "\n")
    print(json.dumps(profile, indent=2, ensure_ascii=False))
    print("\n" + "═" * 64)

    if is_file_mode:
        save_profile(profile)
        print(f"  Done. Run: python run_dossier.py --user {config.user}")
    else:
        save_it = input("  Save as profile.json? (yes/no): ").strip().lower()
        if save_it in ("yes", "y"):
            save_profile(profile)
            print("  Done. Run scripts/run_job_discovery.py next.")
        else:
            print("  Not saved. Re-run when ready.")
