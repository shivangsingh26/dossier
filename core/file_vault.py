"""
core/file_vault.py — Artifact storage for the Dossier project.

Every discovered job gets its own folder under data/artifacts/{job_id}/.
All agents write their outputs here — raw JD, score card, intel, resume, outreach.

Phase A: Creates folders and saves JSON/text files. Nothing more.
"""

import json
from pathlib import Path

from config import Config
from core.logger import get_logger

logger = get_logger(__name__)


def get_job_dir(job_id: str) -> Path:
    """Return the artifact directory path for a job. Does not create it."""
    return Config().artifacts_dir / job_id


def create_job_vault(job_id: str) -> Path:
    """Create the artifact folder for a job if it does not exist. Returns the path."""
    job_dir = get_job_dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    logger.debug(f"Vault ready: {job_dir}")
    return job_dir


def save_jd(job_id: str, jd_text: str) -> None:
    """Save the raw job description text to data/artifacts/{job_id}/jd.txt."""
    job_dir = create_job_vault(job_id)
    (job_dir / "jd.txt").write_text(jd_text, encoding="utf-8")
    logger.debug(f"Saved jd.txt for {job_id}")


def save_scorecard(job_id: str, scorecard: dict) -> None:
    """Save the scoring result to data/artifacts/{job_id}/score_card.json."""
    job_dir = create_job_vault(job_id)
    (job_dir / "score_card.json").write_text(
        json.dumps(scorecard, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.debug(f"Saved score_card.json for {job_id}")


def save_json(job_id: str, filename: str, data: dict) -> None:
    """Generic helper to save any JSON file into a job's artifact vault."""
    job_dir = create_job_vault(job_id)
    (job_dir / filename).write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.debug(f"Saved {filename} for {job_id}")


def job_vault_exists(job_id: str) -> bool:
    """Return True if a vault already exists for this job (used for deduplication)."""
    return get_job_dir(job_id).exists()
