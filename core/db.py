"""
core/db.py — SQLite helpers for job deduplication across runs.

WHY SQLITE (not MongoDB/Redis/VectorDB):
  Our deduplication question is: "Have I scored this URL before?"
  That's an exact key-value lookup — the simplest possible DB operation.

  SQLite is a single file (data/dossier.db), needs no server, uses Python's
  built-in sqlite3 module (zero new dependency), and handles our volume
  (< 100K rows over months of daily runs) with ease.

  MongoDB: server required, document model — overkill for a hash lookup.
  VectorDB: semantic similarity — right for Phase C "find jobs like ones I liked".
  Redis: correct type but needs a running server.

DEDUP SCOPE:
  We save BOTH accepted jobs (score >= min) AND LLM-rejected jobs (score < min).
  This prevents wasted LLM calls on rescoring the same job in future runs.
  Pre-LLM rejections (seniority, PhD filter, etc.) are NOT saved — those checks
  are instant (< 1ms regex) so saving them buys nothing.
"""

import sqlite3
from datetime import datetime, timezone

from config import Config
from core.logger import get_logger

logger = get_logger(__name__)


def _connect() -> sqlite3.Connection:
    """Open or create dossier.db. Returns a connection with Row factory enabled."""
    config = Config()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(config.db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every run startup."""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS seen_jobs (
                url       TEXT PRIMARY KEY,
                job_id    TEXT    NOT NULL,
                score     INTEGER NOT NULL,
                relevancy TEXT    NOT NULL,
                company   TEXT    NOT NULL,
                title     TEXT    NOT NULL,
                source    TEXT    DEFAULT '',
                scored_at TEXT    NOT NULL
            )
        """)
        conn.commit()
    logger.debug("DB initialised — seen_jobs table ready")


def is_job_seen(url: str) -> bool:
    """Return True if this URL was already scored in a previous run."""
    if not url:
        return False
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM seen_jobs WHERE url = ?", (url,)
        ).fetchone()
        return row is not None


def mark_job_seen(
    url: str,
    job_id: str,
    score: int,
    relevancy: str,
    company: str,
    title: str,
    source: str = "",
) -> None:
    """
    Record a scored job URL so it won't be re-scored in future runs.
    Called for both accepted (score >= min) and LLM-rejected (score < min) jobs.
    INSERT OR REPLACE safely handles the rare case of the same URL appearing twice.
    """
    if not url:
        return
    with _connect() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO seen_jobs
                (url, job_id, score, relevancy, company, title, source, scored_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            url, job_id, score, relevancy, company, title, source,
            datetime.now(timezone.utc).isoformat(),
        ))
        conn.commit()


def get_seen_count() -> int:
    """Return total number of jobs in the database (for display in run summaries)."""
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM seen_jobs").fetchone()[0]
