"""
agents/resume_agent.py — Resume and Cover Letter Agent

Given a job ID, produces two tailored documents:
  1. data/artifacts/{job_id}/resume.tex       — LaTeX resume tailored for this specific JD
  2. data/artifacts/{job_id}/cover_letter.txt — Cover letter tailored for this specific JD

Strategy:
  - Reads profile/resume_base.tex as the starting document
  - Reads data/artifacts/{job_id}/gap.json for candidate_has_required / candidate_missing_required
  - Reads data/artifacts/{job_id}/jd.txt for the full job description
  - Three-pass pipeline for the resume:
      Pass 1: Claude Sonnet tailors the draft (resume_tailor_system.txt)
      Pass 2: Claude Haiku critiques the draft for 4 issues (resume_critique_system.txt)
      Pass 3: Claude Sonnet makes only the targeted fixes the critic flagged (resume_revise_system.txt)
             Skipped if the critic finds no issues — Pass 1 output is used directly.
  - Calls Claude Haiku (claude-haiku-4-5-20251001) to write the cover letter — good writing, cost-efficient
  - All prompts are loaded from prompts/ — zero inline prompt strings in this file

Phase A: synchronous calls, one job at a time.
"""

import json
from pathlib import Path

from config import Config
from core.llm_client import LLMClient
from core.logger import get_logger

logger = get_logger(__name__)


# ──────────────────────────────────────────
# Private helpers
# ──────────────────────────────────────────

def _load_prompt(filename: str) -> str:
    """Load a prompt text file from the prompts/ directory."""
    config = Config()
    path = config.prompts_dir / filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def _load_gap_analysis(job_id: str) -> dict:
    """Load gap.json for the given job_id. Raises with a clear message if missing."""
    config = Config()
    gap_path = config.artifacts_dir / job_id / "gap.json"
    if not gap_path.exists():
        raise FileNotFoundError(
            f"gap.json not found for job '{job_id}'.\n"
            f"  → Run gap analysis first: python scripts/run_gap_analysis.py"
        )
    with gap_path.open(encoding="utf-8") as f:
        return json.load(f)


def _load_jd(job_id: str) -> str:
    """Load jd.txt for the given job_id."""
    config = Config()
    jd_path = config.artifacts_dir / job_id / "jd.txt"
    if not jd_path.exists():
        raise FileNotFoundError(f"jd.txt not found for job '{job_id}'.")
    return jd_path.read_text(encoding="utf-8").strip()


def _format_gap_summary(gap: dict) -> str:
    """Convert gap.json into a clean text block for inclusion in the LLM prompt."""
    has = gap.get("candidate_has_required", [])
    missing = gap.get("candidate_missing_required", [])

    lines = ["SKILLS THE CANDIDATE HAS (required by this JD — emphasise these):"]
    for skill in has:
        lines.append(f"  - {skill}")

    lines.append("")
    lines.append("SKILLS THE CANDIDATE IS MISSING (required by JD — do NOT add these):")
    for skill in missing:
        lines.append(f"  - {skill}")

    return "\n".join(lines)


def _build_profile_summary(profile: dict) -> str:
    """Extract relevant profile fields for the cover letter user message."""
    identity = profile.get("identity", {})
    narrative = profile.get("career_narrative", {})
    projects = profile.get("projects", [])

    lines = [
        f"Name: {identity.get('name', '')}",
        f"Current Role: {identity.get('current_role', '')} at {identity.get('current_company', '')}",
        f"Location: {identity.get('location', '')}",
        f"Email: {identity.get('email', '')}",
        "",
        "--- Career Narrative ---",
        f"Why AI Engineering: {narrative.get('why_ai_eng', '')}",
        "",
        f"Strongest Asset: {narrative.get('strongest_asset', '')}",
        "",
        f"Referral Pitch: {narrative.get('referral_pitch', '')}",
        "",
        "--- Key Projects ---",
    ]

    for p in projects:
        tech_str = ", ".join(p.get("tech", []))
        scale = p.get("scale", "")
        scale_str = f" | Scale: {scale}" if scale else ""
        lines.append(
            f"  {p['name']} ({p.get('company', 'Personal')}): "
            f"{p.get('description', '')}{scale_str} | Tech: {tech_str}"
        )

    return "\n".join(lines)


def _strip_markdown_fences(text: str) -> str:
    """
    Remove common markdown code fences Claude sometimes adds despite instructions.
    e.g. ```latex ... ``` or ```tex ... ``` or ``` ... ```
    """
    for fence_open in ["```latex", "```tex", "```"]:
        if text.startswith(fence_open):
            text = text[len(fence_open):].lstrip("\n")
            break
    if text.endswith("```"):
        text = text[:-3].rstrip()
    return text


# ──────────────────────────────────────────
# Public API
# ──────────────────────────────────────────

def tailor_resume(job_id: str, output_filename: str = "resume.tex") -> Path:
    """
    Produce a tailored LaTeX resume for the given job ID.

    Reads:
      - profile/resume_base.tex
      - data/artifacts/{job_id}/gap.json
      - data/artifacts/{job_id}/jd.txt

    Writes:
      - data/artifacts/{job_id}/{output_filename}  (default: resume.tex)

    Returns the path to the written file.
    """
    config = Config()
    llm = LLMClient()

    logger.info(f"[ResumeAgent] Tailoring resume for: {job_id} → {output_filename}")

    # --- Load all inputs ---
    base_tex_path = config.profile_dir / "resume_base.tex"
    if not base_tex_path.exists():
        raise FileNotFoundError(
            f"Base resume not found at {base_tex_path}.\n"
            f"  → Ensure profile/resume_base.tex exists before running the resume agent."
        )
    base_tex = base_tex_path.read_text(encoding="utf-8")
    gap = _load_gap_analysis(job_id)
    jd_text = _load_jd(job_id)
    system_prompt = _load_prompt("resume_tailor_system.txt")
    gap_summary = _format_gap_summary(gap)

    # --- Build user message ---
    user_message = (
        f"=== BASE RESUME (LaTeX) ===\n"
        f"{base_tex}\n\n"
        f"=== GAP ANALYSIS ===\n"
        f"Job ID: {job_id}\n\n"
        f"{gap_summary}\n\n"
        f"=== JOB DESCRIPTION ===\n"
        f"{jd_text}"
    )

    print("[Pass 1/3] Tailoring resume with Claude Sonnet...")
    logger.info("[ResumeAgent] Pass 1 — calling Claude Sonnet to tailor resume...")

    # 4096 tokens gives plenty of headroom for a full LaTeX document (~2500 tokens typical)
    raw_response = llm.call(
        system_prompt=system_prompt,
        user_prompt=user_message,
        model=config.model_resume,
        max_tokens=4096,
    )

    # --- Validate and clean Pass 1 output ---
    draft_tex = raw_response.strip()

    if not draft_tex.startswith("\\documentclass"):
        logger.warning(
            "[ResumeAgent] Pass 1 response did not start with \\documentclass — "
            "attempting markdown fence cleanup."
        )
        draft_tex = _strip_markdown_fences(draft_tex)

    if not draft_tex.startswith("\\documentclass"):
        logger.error(
            "[ResumeAgent] Pass 1 cleanup failed — response does not look like valid LaTeX. "
            "Saving raw output for manual inspection."
        )

    # --- Pass 2: Critique (Claude Haiku) ---
    print("[Pass 2/3] Critiquing draft with Claude Haiku...")
    critique = critique_resume(draft_tex, gap, jd_text)
    logger.info(f"[ResumeAgent] Pass 2 critique:\n{critique}")

    # Detect real actionable issues by marker — not just [ISSUES] header.
    # Haiku can write [ISSUES] but say "no fix needed"; only the action prefix confirms a real issue.
    _ACTION_MARKERS = ("MIRROR:", "HALLUCINATION:", "LATEX:", "ORDER:")
    has_issues = any(m in critique for m in _ACTION_MARKERS)

    if not has_issues:
        print("[Critic] No issues found — using Pass 1 output directly.")
        final_tex = draft_tex
    else:
        print(f"[Critic] Issues found — triggering Pass 3:\n{critique}")
        # --- Pass 3: Revise (Claude Sonnet) — targeted fixes only ---
        print("[Pass 3/3] Revising with Claude Sonnet (targeted fixes only)...")
        final_tex = revise_resume(draft_tex, critique, gap)
        if not final_tex.startswith("\\documentclass"):
            final_tex = _strip_markdown_fences(final_tex)
        if not final_tex.startswith("\\documentclass"):
            logger.error(
                "[ResumeAgent] Pass 3 output invalid — falling back to Pass 1 draft."
            )
            final_tex = draft_tex

    # --- Write final output ---
    output_path = config.artifacts_dir / job_id / output_filename
    output_path.write_text(final_tex, encoding="utf-8")

    logger.info(f"[ResumeAgent] {output_filename} written → {output_path}")
    return output_path


def critique_resume(draft_tex: str, gap: dict, jd_text: str) -> str:
    """
    Pass 2: Claude Haiku audits the draft for 4 issues.
    Returns the structured critic report (CHECK 1–4 with [PASS]/[ISSUES] markers).
    """
    config = Config()
    llm = LLMClient()

    system_prompt = _load_prompt("resume_critique_system.txt")
    gap_summary = _format_gap_summary(gap)

    user_message = (
        f"=== DRAFT RESUME (LaTeX) ===\n"
        f"{draft_tex}\n\n"
        f"=== GAP ANALYSIS ===\n"
        f"{gap_summary}\n\n"
        f"=== JOB DESCRIPTION ===\n"
        f"{jd_text}"
    )

    # ~8K tokens in, ~512 tokens out — Haiku is cost-efficient for this structured audit
    response = llm.call(
        system_prompt=system_prompt,
        user_prompt=user_message,
        model=config.model_cover,
        max_tokens=512,
    )
    return response.strip()


def revise_resume(draft_tex: str, critique: str, gap: dict) -> str:
    """
    Pass 3: Claude Sonnet makes only the targeted fixes the critic flagged.
    Returns complete valid LaTeX — not a re-tailor, only surgical fixes.
    """
    config = Config()
    llm = LLMClient()

    system_prompt = _load_prompt("resume_revise_system.txt")
    gap_summary = _format_gap_summary(gap)

    user_message = (
        f"=== DRAFT RESUME (LaTeX) ===\n"
        f"{draft_tex}\n\n"
        f"=== CRITIC REPORT (fix only [ISSUES] sections) ===\n"
        f"{critique}\n\n"
        f"=== GAP ANALYSIS (reference — do not add missing skills) ===\n"
        f"{gap_summary}"
    )

    raw_response = llm.call(
        system_prompt=system_prompt,
        user_prompt=user_message,
        model=config.model_resume,
        max_tokens=4096,
    )
    return raw_response.strip()


def generate_cover_letter(job_id: str, output_filename: str = "cover_letter.txt") -> Path:
    """
    Generate a tailored cover letter for the given job ID.

    Reads:
      - profile/profile.json
      - data/artifacts/{job_id}/gap.json
      - data/artifacts/{job_id}/jd.txt

    Writes:
      - data/artifacts/{job_id}/{output_filename}  (default: cover_letter.txt)

    Returns the path to the written file.
    """
    config = Config()
    llm = LLMClient()

    logger.info(f"[ResumeAgent] Generating cover letter for: {job_id}")

    # --- Load all inputs ---
    if not config.profile_path.exists():
        raise FileNotFoundError(f"Profile not found at {config.profile_path}.")
    with config.profile_path.open(encoding="utf-8") as f:
        profile = json.load(f)

    gap = _load_gap_analysis(job_id)
    jd_text = _load_jd(job_id)
    system_prompt = _load_prompt("cover_letter_system.txt")

    gap_summary = _format_gap_summary(gap)
    profile_summary = _build_profile_summary(profile)

    # --- Build user message ---
    user_message = (
        f"=== CANDIDATE PROFILE ===\n"
        f"{profile_summary}\n\n"
        f"=== GAP ANALYSIS ===\n"
        f"Job ID: {job_id}\n\n"
        f"{gap_summary}\n\n"
        f"=== JOB DESCRIPTION ===\n"
        f"{jd_text}"
    )

    logger.info(f"[ResumeAgent] Calling Claude Haiku to write cover letter...")

    # 1024 tokens is enough for 350 words at ~3 tokens/word with safety margin
    raw_response = llm.call(
        system_prompt=system_prompt,
        user_prompt=user_message,
        model=config.model_cover,
        max_tokens=1024,
    )

    cover_letter = raw_response.strip()

    # --- Write output ---
    output_path = config.artifacts_dir / job_id / output_filename
    output_path.write_text(cover_letter, encoding="utf-8")

    logger.info(f"[ResumeAgent] {output_filename} written → {output_path}")
    return output_path
