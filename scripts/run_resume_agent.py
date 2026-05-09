"""
scripts/run_resume_agent.py — CLI runner for the Resume and Cover Letter Agent

Usage:
  # See all jobs that have a gap analysis ready, sorted by score
  python scripts/run_resume_agent.py --list

  # Generate tailored resume + cover letter + PDF preview for a specific job
  python scripts/run_resume_agent.py --job-id <job_id>

  # Save as a new version instead of overwriting (resume_v2.tex, cover_letter_v2.txt)
  python scripts/run_resume_agent.py --job-id <job_id> --version

Output (written to data/artifacts/{job_id}/):
  resume.tex        — tailored LaTeX resume for this job
  resume.pdf        — compiled PDF (opened in Preview automatically)
  cover_letter.txt  — tailored cover letter for this job

Requires pdflatex for PDF compilation:
  brew install --cask mactex-no-gui   (smaller, ~100 MB)
  brew install --cask mactex          (full MacTeX, ~4 GB)
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

# Add project root to path so imports work from any directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config
from agents.resume_agent import tailor_resume, generate_cover_letter
from core.llm_client import LLMClient
from core.logger import get_logger

logger = get_logger(__name__)


def _next_version_filenames(artifact_dir: Path) -> tuple[str, str]:
    """
    Find the next unused version number and return filenames for resume and cover letter.
    Starts at v2 (v1 is the default resume.tex / cover_letter.txt).
    Example: if resume_v2.tex exists, returns ("resume_v3.tex", "cover_letter_v3.txt").
    """
    v = 2
    while (artifact_dir / f"resume_v{v}.tex").exists():
        v += 1
    return f"resume_v{v}.tex", f"cover_letter_v{v}.txt"


def _warn_if_over_one_page(pdf_path: Path) -> None:
    """
    Check the compiled PDF page count using pdfinfo (ships with MacTeX).
    Prints a loud warning if the resume is more than 1 page — resume must be exactly 1 page.
    Falls back silently if pdfinfo is not available.
    """
    if not shutil.which("pdfinfo"):
        return  # pdfinfo not available — skip silently

    result = subprocess.run(
        ["pdfinfo", str(pdf_path)],
        capture_output=True,
        text=True,
    )
    for line in result.stdout.splitlines():
        if line.startswith("Pages:"):
            try:
                pages = int(line.split(":")[-1].strip())
            except ValueError:
                return
            if pages > 1:
                print(f"\n  ⚠  RESUME IS {pages} PAGES — must be exactly 1 page!")
                print("     Shorten bullet points in the .tex file and recompile.")
                print("     Tip: keep each bullet to 1.5 lines max, remove the weakest bullet per job.")
            else:
                print(f"  ✓ Page count: {pages} page")
            return


def compile_and_preview_pdf(tex_path: Path) -> Path | None:
    """
    Compile a LaTeX .tex file to PDF using pdflatex, then open in the default viewer.
    Cleans up auxiliary files (.aux, .log, .out) after compilation.
    Returns the PDF path on success, None if pdflatex is not installed or compilation fails.
    """
    if not shutil.which("pdflatex"):
        print("\n  ⚠  pdflatex not installed — PDF preview skipped.")
        print("     To enable: brew install --cask mactex-no-gui")
        print(f"     Then compile manually: pdflatex -output-directory={tex_path.parent} {tex_path}")
        return None

    print(f"\n[PDF] Compiling {tex_path.name}...")

    result = subprocess.run(
        [
            "pdflatex",
            "-interaction=nonstopmode",
            f"-output-directory={tex_path.parent.resolve()}",
            str(tex_path.resolve()),
        ],
        capture_output=True,
        text=True,
    )

    # Clean up auxiliary files pdflatex generates alongside the PDF
    for suffix in [".aux", ".log", ".out"]:
        aux = tex_path.with_suffix(suffix)
        if aux.exists():
            aux.unlink()

    pdf_path = tex_path.with_suffix(".pdf")

    if result.returncode != 0 or not pdf_path.exists():
        print(f"  ✗ pdflatex failed (exit {result.returncode})")
        # Print the last 10 lines of pdflatex output to help diagnose LaTeX errors
        error_lines = [l for l in result.stdout.splitlines() if l.strip()][-10:]
        for line in error_lines:
            print(f"    {line}")
        return None

    print(f"  ✓ PDF compiled → {pdf_path}")

    # Check page count — resume must be exactly 1 page
    _warn_if_over_one_page(pdf_path)

    # macOS: open in default PDF viewer (Preview)
    subprocess.run(["open", str(pdf_path)], check=False)

    return pdf_path


def list_available_jobs(artifacts_dir: Path) -> None:
    """Print a table of all jobs that have gap.json, sorted by score descending."""
    rows = []
    for job_dir in sorted(artifacts_dir.iterdir()):
        if not job_dir.is_dir():
            continue

        gap_path = job_dir / "gap.json"
        score_path = job_dir / "score_card.json"

        if not gap_path.exists():
            continue  # Gap analysis not run yet — skip

        score = "?"
        relevancy = "?"
        company = "?"
        title = "?"
        already_done = (job_dir / "resume.tex").exists()

        if score_path.exists():
            try:
                with score_path.open() as f:
                    card = json.load(f)
                score = card.get("score", "?")
                relevancy = card.get("relevancy", "?").upper()
                company = card.get("company", "?")
                title = card.get("title", "?")
            except (json.JSONDecodeError, KeyError):
                pass

        rows.append((score, relevancy, company, title, job_dir.name, already_done))

    if not rows:
        print("\n  No jobs with gap analysis found.")
        print("  → Run: python scripts/run_gap_analysis.py\n")
        return

    # Sort by score descending ("?" jobs go to the bottom)
    rows.sort(key=lambda r: (r[0] if isinstance(r[0], int) else -1), reverse=True)

    print(f"\n{'Score':>5}  {'Relevancy':<8}  {'Company':<30}  {'Title':<35}  {'Done':>4}  Job ID")
    print("-" * 120)
    for score, relevancy, company, title, job_id, already_done in rows:
        done_mark = " ✓" if already_done else "  "
        print(
            f"{str(score):>5}  {relevancy:<8}  {company[:30]:<30}  {title[:35]:<35}  "
            f"{done_mark:>4}  {job_id}"
        )
    print()
    print("  ✓ = resume.tex already generated")
    print("  → To generate: python scripts/run_resume_agent.py --job-id <job_id>")
    print("  → To version:  python scripts/run_resume_agent.py --job-id <job_id> --version\n")


def run(job_id: str, use_version: bool = False) -> None:
    """
    Run tailor_resume + generate_cover_letter + PDF compilation for the given job_id.
    If use_version=True, saves to resume_v{N}.tex instead of overwriting resume.tex.
    """
    config = Config()
    artifact_dir = config.artifacts_dir / job_id

    # Determine output filenames
    if use_version:
        resume_filename, cover_filename = _next_version_filenames(artifact_dir)
        print(f"\n[ResumeAgent] Versioning → {resume_filename} / {cover_filename}")
    else:
        resume_filename, cover_filename = "resume.tex", "cover_letter.txt"

    print(f"\n[ResumeAgent] Starting for job: {job_id}")
    print("[ResumeAgent] 3-pass self-evaluation: tailor → critique → revise")
    print("─" * 60)

    # --- Resume ---
    try:
        resume_path = tailor_resume(job_id, output_filename=resume_filename)
        print(f"\n  ✓ Resume written → {resume_path}")
    except FileNotFoundError as e:
        print(f"\n  ✗ Resume failed: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error tailoring resume: {e}", exc_info=True)
        print(f"\n  ✗ Resume failed (unexpected): {e}")
        sys.exit(1)

    # --- Cover letter ---
    try:
        cover_path = generate_cover_letter(job_id, output_filename=cover_filename)
        print(f"  ✓ Cover letter written → {cover_path}")
    except FileNotFoundError as e:
        print(f"\n  ✗ Cover letter failed: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error generating cover letter: {e}", exc_info=True)
        print(f"\n  ✗ Cover letter failed (unexpected): {e}")
        sys.exit(1)

    # --- Cost summary ---
    usage = LLMClient().get_usage_summary()
    print(f"\n[Cost] {usage['total_calls']} calls | "
          f"{usage['total_tokens']:,} tokens | "
          f"~${usage['estimated_cost_usd']:.4f} USD")
    for model, stats in usage.get("per_model", {}).items():
        print(f"  {model}: {stats['calls']} calls, "
              f"{stats['prompt_tokens']:,}p + {stats['completion_tokens']:,}c tokens, "
              f"~${stats['cost_usd']:.4f}")

    # --- PDF compilation (mandatory) ---
    compile_and_preview_pdf(resume_path)

    print(f"\n[ResumeAgent] Done. All files in: data/artifacts/{job_id}/\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a tailored resume, cover letter, and PDF for a specific job.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/run_resume_agent.py --list\n"
            "  python scripts/run_resume_agent.py --job-id grab_data_scientist_high\n"
            "  python scripts/run_resume_agent.py --job-id grab_data_scientist_high --version"
        ),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all jobs with gap analysis ready, sorted by score",
    )
    parser.add_argument(
        "--job-id",
        type=str,
        help="Job ID to generate resume and cover letter for",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help=(
            "Save as a new version instead of overwriting. "
            "Finds the next unused number: resume_v2.tex, resume_v3.tex, etc."
        ),
    )
    args = parser.parse_args()

    config = Config()

    if args.list:
        list_available_jobs(config.artifacts_dir)
        return

    if args.job_id:
        run(args.job_id, use_version=args.version)
        return

    # No args — show list as default helpful behaviour
    print("\nNo arguments provided. Showing available jobs:\n")
    list_available_jobs(config.artifacts_dir)
    print("Usage: python scripts/run_resume_agent.py --job-id <job_id>\n")


if __name__ == "__main__":
    main()
