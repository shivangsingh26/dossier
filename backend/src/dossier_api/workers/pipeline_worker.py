"""Standalone pipeline worker process.

Polls pipeline_runs for queued rows, marks them running, dispatches to a
handler keyed by agent, records completion + refunds (M4: credit refund).

Run: uv run python -m dossier_api.workers.pipeline_worker
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dossier_api.db import _connect, init_db, mark_run_completed, mark_run_failed
from dossier_api.settings import get_settings

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 5


def pick_next_queued_run(*, db_path: Path | None = None) -> dict[str, Any] | None:
    """Atomically claim the oldest queued run, mark it running, return it.

    Returns None if nothing queued.
    """
    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT * FROM pipeline_runs
               WHERE status = 'queued'
               ORDER BY rowid ASC
               LIMIT 1"""
        ).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return None
        run_id = row["run_id"]
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE pipeline_runs SET status='running', started_at=? WHERE run_id=?",
            (now, run_id),
        )
        return dict(row)


def _run_persona_synthesis(run: dict) -> dict:
    """Worker handler for agent=persona_synthesis. Returns output_summary."""
    from dossier_sdk.agents.persona_builder import (
        parse_linkedin_pdf,
        parse_resume,
        synthesize_profile,
    )

    from dossier_api.services import persona_service

    with _connect() as conn:
        row = conn.execute(
            "SELECT data_user_slug FROM accounts WHERE user_id = ?", (run["user_id"],)
        ).fetchone()
    if row is None:
        raise RuntimeError(f"no account for user_id={run['user_id']}")
    slug = row["data_user_slug"]

    profile_dir = persona_service.profile_dir_for(slug)
    raw_dir = persona_service.raw_dir_for(slug)
    questionnaire = persona_service.load_questionnaire(slug) or {}
    quiz_answers = persona_service.load_quiz_answers(slug) or {}

    resume_pdf = None
    linkedin_pdf = None
    for pdf in raw_dir.glob("*.pdf"):
        name = pdf.name.lower()
        if "linkedin" in name and linkedin_pdf is None:
            linkedin_pdf = pdf
        elif resume_pdf is None:
            resume_pdf = pdf

    resume_text = parse_resume(resume_pdf) if resume_pdf else ""
    linkedin_text = parse_linkedin_pdf(linkedin_pdf) if linkedin_pdf else ""

    target = questionnaire.get("target", {})
    identity = questionnaire.get("identity", {})
    work_prefs = questionnaire.get("work_preferences", {})

    profile = synthesize_profile(
        resume_text=resume_text,
        linkedin_text=linkedin_text,
        target=target,
        interview_answers=quiz_answers,
        github_username=identity.get("github_username", ""),
        supporting_files="",
        profile_dir=profile_dir,
        questionnaire_identity=identity,
        full_time_months=int(identity.get("full_time_months") or 0),
        intern_months=int(identity.get("intern_months") or 0),
        work_style=work_prefs.get("work_style", ""),
        open_to_relocation=bool(work_prefs.get("open_to_relocation", False)),
        relocation_cities=work_prefs.get("relocation_cities", []),
    )
    persona_service.save_profile_json(slug, profile)
    return {"profile_written": True, "slug": slug}


_HANDLERS = {
    "persona_synthesis": _run_persona_synthesis,
}


def process_run(run: dict) -> None:
    """Run handler for the agent. On exception, mark failed. On success, mark completed."""
    agent = run["agent"]
    handler = _HANDLERS.get(agent)
    if handler is None:
        mark_run_failed(run["run_id"], error=f"unknown agent: {agent}")
        return
    try:
        summary = handler(run)
        mark_run_completed(run["run_id"], output_summary=summary)
        logger.info("run %s completed (agent=%s)", run["run_id"], agent)
    except Exception as exc:
        logger.exception("run %s failed", run["run_id"])
        mark_run_failed(run["run_id"], error=str(exc))


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="[%(levelname)s] [worker] %(message)s",
    )
    settings = get_settings()
    init_db(settings.accounts_db_path)
    logger.info("worker started · db=%s · poll=%ss", settings.accounts_db_path, POLL_INTERVAL_S)
    while True:
        run = pick_next_queued_run()
        if run is None:
            logger.info("[idle] no queued runs")
            time.sleep(POLL_INTERVAL_S)
            continue
        logger.info("picked run %s (agent=%s)", run["run_id"], run["agent"])
        process_run(run)


if __name__ == "__main__":
    main()
