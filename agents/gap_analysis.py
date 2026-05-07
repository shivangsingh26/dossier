"""
agents/gap_analysis.py — Analyses all accumulated JDs, extracts skills, and produces
a ranked gap report comparing market demand against the user's profile.

Phase A: Synchronous. ThreadPoolExecutor for the LLM extraction pass only.

PURPOSE:
  The scoring agent answers "does this job fit me?"
  This agent answers "what does the market want that I don't have yet?"

HOW MATCHING WORKS (semantic, not keyword):
  Each JD extraction call includes the candidate's profile summary so the LLM can
  reason about capability equivalence. "LLMs" in a JD matches "LLM Pipeline Engineering
  (can_architect)" in the profile. "PyTorch" matches "Computer Vision (can_architect)" —
  the candidate built neural networks, they know PyTorch. No keyword list to maintain.

SKILL CATEGORIES (6):
  technical        — languages, ML/AI frameworks, model architectures
  tools_platforms  — cloud, databases, infrastructure, DevOps
  domain           — NLP, Computer Vision, Speech, Recommender Systems, etc.
  research_methods — statistics, A/B Testing, causal inference
  behavioral       — interpersonal/process skills explicitly listed as requirements
  certifications   — named certifications, publications, patents

TWO OUTPUTS:
  1. Per-job gap.json (schema_version 2) in each artifact vault — feeds the resume agent.
  2. data/gap_report.json — aggregate per-category frequency map for terminal + frontend.

SCHEMA VERSIONING:
  schema_version 1 → flat skill lists, keyword matching (obsolete)
  schema_version 2 → categorised skills, LLM semantic matching (current)
  scan_artifacts() auto-detects v1 files and marks them for reprocessing.

RUN VIA: python scripts/run_gap_analysis.py
"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table
from rich.rule import Rule

from config import Config
from core.file_vault import get_job_dir
from core.llm_client import LLMClient
from core.logger import get_logger
from core.utils import parse_json_response

logger = get_logger(__name__)
console = Console()

_EXTRACT_WORKERS   = 8    # matches scoring agent parallelism
_SCHEMA_VERSION    = 2    # bump when gap.json format changes
_CATEGORIES        = ["technical", "tools_platforms", "domain",
                      "research_methods", "behavioral", "certifications"]
_RECENCY_WEIGHTS   = [
    (30,  1.0),   # ≤ 30 days old → full weight
    (90,  0.8),   # 31–90 days    → slight discount
    (999, 0.6),   # 90+ days      → lower weight
]


# ─── Profile summary (sent with every JD for semantic matching) ───────────────

def _build_profile_summary(profile: dict) -> str:
    """
    Build a compact text summary of the candidate's skills to include in every
    LLM extraction call. Enables semantic matching without keyword lists.

    Caps aliases at 6 per skill to control token count (~500 tokens total).
    """
    lines: list[str] = []

    name = profile.get("name", "Candidate")
    exp = profile.get("total_experience_months", 0)
    lines.append(f"Candidate: {name} | {exp} months total experience")
    lines.append("")
    lines.append("SKILLS (Name [depth]: common aliases):")

    for skill in profile.get("skills", []):
        skill_name = skill.get("skill", "")
        depth      = skill.get("depth", "can_use")
        aliases    = skill.get("market_aliases", [])  # no cap — all aliases needed for matching
        alias_str  = ", ".join(aliases)
        lines.append(f"- {skill_name} [{depth}]: {alias_str}")

    return "\n".join(lines)


# ─── Artifact scanning ────────────────────────────────────────────────────────

def scan_artifacts(config: Config, force: bool, min_score: int) -> list[dict]:
    """
    Walk data/artifacts/ and return one dict per job that has a jd.txt.

    A job is marked needs_extraction=True when:
      - force=True, OR
      - gap.json is missing, OR
      - gap.json exists but is schema_version < _SCHEMA_VERSION (auto-upgrade)

    min_score=0 keeps all jobs for the broadest market signal.
    """
    artifacts = []
    for job_dir in sorted(config.artifacts_dir.iterdir()):
        if not job_dir.is_dir():
            continue
        jd_path       = job_dir / "jd.txt"
        scorecard_path = job_dir / "score_card.json"
        gap_path      = job_dir / "gap.json"

        if not jd_path.exists():
            continue

        score    = 0
        found_at = None
        if scorecard_path.exists():
            try:
                sc       = json.loads(scorecard_path.read_text(encoding="utf-8"))
                score    = sc.get("score", 0)
                found_at = sc.get("found_at")
            except Exception:
                pass

        if score < min_score:
            continue

        # Auto-detect stale schema: treat v1 files as needing reprocessing
        needs_extraction = force
        if not force:
            if not gap_path.exists():
                needs_extraction = True
            else:
                try:
                    existing = json.loads(gap_path.read_text(encoding="utf-8"))
                    if existing.get("schema_version", 1) < _SCHEMA_VERSION:
                        needs_extraction = True
                        logger.debug(f"Schema v1 → v{_SCHEMA_VERSION} upgrade: {job_dir.name}")
                except Exception:
                    needs_extraction = True  # corrupt file → reprocess

        artifacts.append({
            "job_id":            job_dir.name,
            "jd_path":           jd_path,
            "score":             score,
            "found_at":          found_at,
            "needs_extraction":  needs_extraction,
        })

    return artifacts


# ─── Skill extraction (per JD + semantic matching) ───────────────────────────

def _load_skill_extract_prompt() -> str:
    """Load the system prompt from prompts/skill_extract_system.txt."""
    prompt_path = Config().prompts_dir / "skill_extract_system.txt"
    if not prompt_path.exists():
        raise FileNotFoundError(
            f"Skill extract prompt not found at {prompt_path}. "
            "Run from the project root so relative paths resolve correctly."
        )
    return prompt_path.read_text(encoding="utf-8")


def extract_skills_for_job(
    job: dict,
    system_prompt: str,
    profile_summary: str,
    llm: LLMClient,
    config: Config,
) -> dict | None:
    """
    One LLM call per JD: extract categorised skills AND semantically match them
    against the candidate's profile. Returns the raw result dict or None on failure.

    user_prompt = JD text + separator + profile summary
    The LLM extracts skills AND determines has/missing in a single call.
    """
    job_id = job["job_id"]
    try:
        jd_text = job["jd_path"].read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Could not read jd.txt for {job_id}: {e}")
        return None

    user_prompt = f"{jd_text}\n\n---\nCANDIDATE PROFILE:\n{profile_summary}"

    raw = llm.call(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=config.model_nano,
        max_tokens=2500,  # skill-rich JDs can hit 1500 — 2500 gives safe headroom
    )

    result = parse_json_response(raw, context=f"skill extraction | {job_id}")
    if result is None:
        return None

    # LLM occasionally returns a list instead of the expected dict schema
    if not isinstance(result, dict):
        logger.error(f"LLM returned non-dict JSON for {job_id}: type={type(result).__name__}")
        return None

    # Ensure all expected section keys exist as dicts with category sub-keys.
    # Defensive: LLM sometimes returns a flat list for "required"/"preferred" instead of a dict.
    for section in ("required", "preferred"):
        if not isinstance(result.get(section), dict):
            result[section] = {}
        for cat in _CATEGORIES:
            if cat not in result[section]:
                result[section][cat] = []

    result.setdefault("degree_required", "none")
    result.setdefault("years_required", None)
    result.setdefault("candidate_has_required", [])
    result.setdefault("candidate_has_preferred", [])
    result.setdefault("candidate_missing_required", [])
    result.setdefault("candidate_missing_preferred", [])
    result["job_id"] = job_id
    return result


def extract_skills_parallel(
    jobs_to_process: list[dict],
    system_prompt: str,
    profile_summary: str,
    llm: LLMClient,
    config: Config,
) -> list[dict]:
    """
    Extract skills from multiple JDs in parallel using ThreadPoolExecutor.

    WHY PARALLEL: Each LLM call takes ~1-2s (network I/O). 8 workers processes
    193 jobs in ~35s instead of ~5 minutes. LLMClient is thread-safe after init
    (SDK clients are stateless per request). See llm_client.py for thread-safety notes.
    """
    if not jobs_to_process:
        return []

    results: list[dict] = []
    failed  = 0
    total   = len(jobs_to_process)

    console.print(f"  Extracting skills from {total} JDs ({_EXTRACT_WORKERS} workers)...")

    with ThreadPoolExecutor(max_workers=_EXTRACT_WORKERS) as executor:
        future_to_job = {
            executor.submit(
                extract_skills_for_job, job, system_prompt, profile_summary, llm, config
            ): job
            for job in jobs_to_process
        }
        completed = 0
        for future in as_completed(future_to_job):
            completed += 1
            job = future_to_job[future]
            try:
                result = future.result()
                if result:
                    results.append(result)
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                logger.error(f"Extraction failed for {job['job_id']}: {e}")

            if completed % 20 == 0 or completed == total:
                console.print(f"    {completed}/{total} extracted...")

    console.print(
        f"  Extraction complete — {len(results)} succeeded, {failed} failed"
    )
    return results


# ─── Per-job gap artifact ─────────────────────────────────────────────────────

def write_job_gap_artifact(job_id: str, extracted: dict) -> None:
    """
    Write data/artifacts/{job_id}/gap.json (schema_version 2).

    Stores the LLM-determined has/missing split alongside the categorised skill
    lists. The resume agent reads candidate_missing_required to know which skills
    to acknowledge and which profile strengths to lead with (candidate_has_required).
    """
    gap_data = {
        "schema_version":  _SCHEMA_VERSION,
        "job_id":          job_id,
        "extracted_at":    datetime.now(timezone.utc).isoformat(),
        # Categorised skills extracted from the JD
        "required":        extracted.get("required", {cat: [] for cat in _CATEGORIES}),
        "preferred":       extracted.get("preferred", {cat: [] for cat in _CATEGORIES}),
        # Degree and experience metadata — preserved for future UI display
        "degree_required": extracted.get("degree_required", "none"),
        "years_required":  extracted.get("years_required"),
        # LLM-determined semantic match — the resume agent's primary input
        "candidate_has_required":      extracted.get("candidate_has_required", []),
        "candidate_has_preferred":     extracted.get("candidate_has_preferred", []),
        "candidate_missing_required":  extracted.get("candidate_missing_required", []),
        "candidate_missing_preferred": extracted.get("candidate_missing_preferred", []),
    }

    gap_path = get_job_dir(job_id) / "gap.json"
    gap_path.write_text(
        json.dumps(gap_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.debug(f"Wrote gap.json (v{_SCHEMA_VERSION}) for {job_id}")


# ─── Frequency map ────────────────────────────────────────────────────────────

def _recency_weight(found_at_iso: str | None) -> float:
    """Return a recency multiplier based on how old the job posting is."""
    if not found_at_iso:
        return 0.6

    try:
        posted = datetime.fromisoformat(found_at_iso)
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - posted).days
    except Exception:
        return 0.6

    for threshold, weight in _RECENCY_WEIGHTS:
        if age_days <= threshold:
            return weight
    return 0.6


def build_frequency_map(config: Config) -> dict:
    """
    Read all gap.json (schema_version 2) files and build a per-category frequency map.

    For each skill in each category:
      jd_count        = how many JDs mention this skill (required or preferred)
      missing_count   = how many JDs have this skill in candidate_missing_required
      has_count       = how many JDs have this skill in candidate_has_required
      weighted_score  = (missing_count × 2 + pref_missing_count) × recency_weight
                        The ×2 on required reflects "must have" > "nice to have".

    Returns:
      {
        "by_category": {
          "technical": {skill: {jd_count, missing_count, has_count, weighted_score, ...}},
          "tools_platforms": {...}, ...
        },
        "total_jds": int
      }
    """
    # Structure: category → skill → counters
    by_category: dict[str, dict[str, dict]] = {cat: {} for cat in _CATEGORIES}
    total_jds = 0

    for job_dir in config.artifacts_dir.iterdir():
        if not job_dir.is_dir():
            continue
        gap_path      = job_dir / "gap.json"
        scorecard_path = job_dir / "score_card.json"

        if not gap_path.exists():
            continue

        try:
            gap = json.loads(gap_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        if gap.get("schema_version", 1) < _SCHEMA_VERSION:
            continue  # skip stale v1 files — they will be reprocessed on next run

        found_at = None
        if scorecard_path.exists():
            try:
                sc = json.loads(scorecard_path.read_text(encoding="utf-8"))
                found_at = sc.get("found_at")
            except Exception:
                pass

        weight = _recency_weight(found_at)
        total_jds += 1

        missing_req  = set(gap.get("candidate_missing_required",  []))
        missing_pref = set(gap.get("candidate_missing_preferred", []))
        has_req      = set(gap.get("candidate_has_required",      []))

        def _register(cat: str, skill: str, is_required: bool) -> None:
            if not skill or not cat:
                return
            if cat not in by_category:
                by_category[cat] = {}
            if skill not in by_category[cat]:
                by_category[cat][skill] = {
                    "jd_count": 0, "missing_req_count": 0, "missing_pref_count": 0,
                    "has_count": 0, "weighted_score": 0.0,
                }
            entry = by_category[cat][skill]
            entry["jd_count"] += 1
            if is_required:
                if skill in missing_req:
                    entry["missing_req_count"] += 1
                    entry["weighted_score"] += 2 * weight
                elif skill in has_req:
                    entry["has_count"] += 1
            else:
                if skill in missing_pref:
                    entry["missing_pref_count"] += 1
                    entry["weighted_score"] += 1 * weight

        for cat in _CATEGORIES:
            for skill in gap.get("required", {}).get(cat, []):
                _register(cat, skill, is_required=True)
            for skill in gap.get("preferred", {}).get(cat, []):
                _register(cat, skill, is_required=False)

    # Round weighted scores
    for cat_data in by_category.values():
        for v in cat_data.values():
            v["weighted_score"] = round(v["weighted_score"], 2)

    return {"by_category": by_category, "total_jds": total_jds}


# ─── Gap computation ──────────────────────────────────────────────────────────

def _priority(missing_pct: float) -> str:
    """Assign priority based on how often the candidate is missing this required skill."""
    if missing_pct >= 0.50:
        return "HIGH"
    if missing_pct >= 0.25:
        return "MEDIUM"
    return "LOW"


def compute_gaps(freq_data: dict) -> tuple[dict, dict, dict]:
    """
    Split the frequency map into gaps (candidate missing) and strengths (candidate has).

    Returns three dicts keyed by category:
      required_gaps   — skill appears in required sections AND candidate is missing it
      preferred_gaps  — skill appears in preferred sections AND candidate is missing it
      strong_matches  — skill appears frequently AND candidate has it (pct_of_jds >= 0.20)

    Within each category, skills are sorted by weighted_score descending.
    """
    total_jds     = freq_data["total_jds"]
    by_category   = freq_data["by_category"]

    required_gaps: dict[str, list]  = {cat: [] for cat in _CATEGORIES}
    preferred_gaps: dict[str, list] = {cat: [] for cat in _CATEGORIES}
    strong_matches: dict[str, list] = {cat: [] for cat in _CATEGORIES}

    for cat, skills in by_category.items():
        for skill, counts in skills.items():
            jd_pct      = counts["jd_count"] / total_jds if total_jds else 0.0
            missing_pct = counts["missing_req_count"] / total_jds if total_jds else 0.0

            row = {
                "skill":              skill,
                "jd_count":           counts["jd_count"],
                "missing_req_count":  counts["missing_req_count"],
                "missing_pref_count": counts.get("missing_pref_count", 0),
                "has_count":          counts["has_count"],
                "weighted_score":     counts["weighted_score"],
                "pct_of_jds":         round(jd_pct, 3),
            }

            if counts["missing_req_count"] > 0:
                row["priority"] = _priority(missing_pct)
                required_gaps[cat].append(row)
            elif counts.get("missing_pref_count", 0) > 0:
                row["priority"] = "LOW"
                preferred_gaps[cat].append(row)
            elif counts["has_count"] > 0 and jd_pct >= 0.20:
                strong_matches[cat].append(row)

    # Sort each category by weighted_score descending
    for cat in _CATEGORIES:
        required_gaps[cat].sort(key=lambda x: x["weighted_score"], reverse=True)
        preferred_gaps[cat].sort(key=lambda x: x["weighted_score"], reverse=True)
        strong_matches[cat].sort(key=lambda x: x["weighted_score"], reverse=True)

    return required_gaps, preferred_gaps, strong_matches


# ─── Report output ────────────────────────────────────────────────────────────

def write_gap_report(
    required_gaps: dict,
    preferred_gaps: dict,
    strong_matches: dict,
    total_jds: int,
    llm_usage: dict,
) -> None:
    """Write data/gap_report.json — the frontend-ready aggregate report."""
    config = Config()
    report = {
        "schema_version":     _SCHEMA_VERSION,
        "generated_at":       datetime.now(timezone.utc).isoformat(),
        "total_jds_analyzed": total_jds,
        # Per-category dicts — frontend can render each category as a separate chart
        "required_gaps":      required_gaps,
        "preferred_gaps":     preferred_gaps,
        "strong_matches":     strong_matches,
        "llm_usage":          llm_usage,
    }
    out_path = config.data_dir / "gap_report.json"
    out_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(f"Gap report (v{_SCHEMA_VERSION}) saved → {out_path}")


def _bar(pct: float, width: int = 10) -> str:
    """Render an ASCII frequency bar. pct=0.78 → '███████░░░'"""
    filled = round(pct * width)
    return "█" * filled + "░" * (width - filled)


_CATEGORY_LABELS = {
    "technical":       "Technical",
    "tools_platforms": "Tools & Platforms",
    "domain":          "Domain",
    "research_methods":"Research Methods",
    "behavioral":      "Behavioral",
    "certifications":  "Certifications",
}


def _print_section(
    title: str,
    color: str,
    gaps_by_cat: dict,
    top_n: int,
    show_depth: bool = False,
) -> None:
    """Print one section (required gaps / preferred gaps / strong matches) by category."""
    # Flatten and collect all rows across categories for display
    all_rows: list[dict] = []
    for cat, rows in gaps_by_cat.items():
        for row in rows[:top_n]:
            all_rows.append({**row, "_category": _CATEGORY_LABELS.get(cat, cat)})

    if not all_rows:
        return

    all_rows.sort(key=lambda x: x["weighted_score"], reverse=True)
    all_rows = all_rows[:top_n]

    console.print(f"[bold {color}]{title}[/bold {color}]")
    t = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    t.add_column("#",          style="dim", width=4)
    t.add_column("Skill",      width=22)
    t.add_column("Category",   width=18, style="dim")
    t.add_column("Frequency",  width=12)
    t.add_column("% of JDs",   justify="right", width=10)
    if show_depth:
        t.add_column("Your depth", width=16)
    else:
        t.add_column("Priority",   width=10)

    for i, row in enumerate(all_rows, 1):
        pct = row["pct_of_jds"]
        if show_depth:
            extra_col = f"[green]{row.get('depth', '—')}[/green]"
        else:
            priority = row.get("priority", "LOW")
            color_map = {"HIGH": "red", "MEDIUM": "yellow", "LOW": "dim"}
            pc = color_map.get(priority, "dim")
            extra_col = f"[{pc}]{priority}[/{pc}]"

        t.add_row(
            str(i),
            row["skill"],
            row["_category"],
            _bar(pct),
            f"{pct * 100:.0f}%",
            extra_col,
        )
    console.print(t)
    console.print()


def print_rich_report(
    required_gaps: dict,
    preferred_gaps: dict,
    strong_matches: dict,
    total_jds: int,
    new_this_run: int,
    top_n: int,
) -> None:
    """Print the full colour-coded Rich gap report to the terminal."""
    console.print()
    console.print(Rule("[bold]Dossier — Skill Gap Report[/bold]", style="bold cyan"))
    console.print(
        f"  Based on [bold]{total_jds}[/bold] JDs  "
        f"([bold]{new_this_run}[/bold] extracted this run, "
        f"[dim]{total_jds - new_this_run} loaded from cache[/dim])"
    )
    console.print()

    _print_section(
        "REQUIRED SKILL GAPS — market says must-have, you're missing:",
        "red", required_gaps, top_n,
    )
    _print_section(
        "PREFERRED SKILL GAPS — nice to have, worth learning:",
        "yellow", preferred_gaps, top_n,
    )
    _print_section(
        "YOUR STRONG MATCHES — you have these, market wants them:",
        "green", strong_matches, top_n, show_depth=True,
    )


# ─── Main entry point ─────────────────────────────────────────────────────────

def run(
    force: bool = False,
    min_score: int = 0,
    top_n: int = 20,
) -> dict:
    """
    Run the full gap analysis pipeline.

    Args:
        force:     Reprocess all JDs regardless of existing gap.json.
                   Not needed for schema upgrades — those are auto-detected.
        min_score: Only include JDs with score >= this in the frequency map.
        top_n:     Skills to display per section in the terminal report.

    Returns a summary dict with counts and LLM usage stats.
    """
    config = Config()
    llm    = LLMClient()

    # ── Phase 1: Scan artifacts ────────────────────────────────────────────────
    all_artifacts  = scan_artifacts(config, force=force, min_score=min_score)
    total_in_vault = len(all_artifacts)

    if total_in_vault == 0:
        console.print("[yellow]No JDs found. Run job discovery first.[/yellow]")
        return {}

    to_extract   = [a for a in all_artifacts if a["needs_extraction"]]
    cached_count = total_in_vault - len(to_extract)

    console.print(
        f"\n  Found {total_in_vault} JDs  "
        f"({len(to_extract)} need extraction, {cached_count} already current)"
    )

    # ── Phase 2: Load profile ──────────────────────────────────────────────────
    profile_path = config.profile_path
    if not profile_path.exists():
        console.print(f"[red]Profile not found at {profile_path}. Run persona builder first.[/red]")
        return {}

    profile        = json.loads(profile_path.read_text(encoding="utf-8"))
    profile_summary = _build_profile_summary(profile)
    logger.info(f"Profile summary built ({len(profile_summary.splitlines())} lines)")

    # ── Phase 3: Extract skills from new/stale JDs ────────────────────────────
    new_extracted = 0
    if to_extract:
        system_prompt = _load_skill_extract_prompt()
        extraction_results = extract_skills_parallel(
            to_extract, system_prompt, profile_summary, llm, config
        )

        # ── Phase 4: Write per-job gap.json ───────────────────────────────────
        for extracted in extraction_results:
            job_id = extracted["job_id"]
            try:
                write_job_gap_artifact(job_id, extracted)
                new_extracted += 1
            except Exception as e:
                logger.error(f"Failed to write gap.json for {job_id}: {e}")

        console.print(f"  gap.json (v{_SCHEMA_VERSION}) written for {new_extracted} jobs")
    else:
        console.print("  All JDs current — skipping extraction (use --force to redo)")

    # ── Phase 5: Build frequency map from ALL current gap.json ────────────────
    freq_data  = build_frequency_map(config)
    total_jds  = freq_data["total_jds"]

    # ── Phase 6: Compute gaps vs profile (uses LLM-determined has/missing) ────
    required_gaps, preferred_gaps, strong_matches = compute_gaps(freq_data)

    # ── Phase 7: Write report + print ─────────────────────────────────────────
    llm_usage = llm.get_usage_summary()

    write_gap_report(required_gaps, preferred_gaps, strong_matches, total_jds, llm_usage)

    print_rich_report(
        required_gaps, preferred_gaps, strong_matches,
        total_jds=total_jds,
        new_this_run=new_extracted,
        top_n=top_n,
    )

    if llm_usage["total_calls"] > 0:
        console.print(
            f"  LLM usage: {llm_usage['total_calls']} calls · "
            f"{llm_usage['total_tokens']:,} tokens · "
            f"~${llm_usage['estimated_cost_usd']:.4f}"
        )
    console.print(f"  Gap report → data/gap_report.json\n")

    return {
        "total_jds":            total_jds,
        "new_extracted":        new_extracted,
        "required_gaps_count":  sum(len(v) for v in required_gaps.values()),
        "preferred_gaps_count": sum(len(v) for v in preferred_gaps.values()),
        "strong_matches_count": sum(len(v) for v in strong_matches.values()),
        "llm_usage":            llm_usage,
    }
