"""accounts.db — auth/credits/runs ledger.

Plain sqlite3 (sync). Connection is opened per-call; SQLite handles concurrent
readers natively. Writes are serialized by the default journaling mode.

Schema mirrors spec §7.4 exactly. Any change here requires a migration step
(M2 ships v1; future versions add migration logic).
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dossier_api.settings import get_settings

SCHEMA_VERSION = 1


def _db_path() -> Path:
    return get_settings().accounts_db_path


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path | None = None) -> None:
    """Create all tables if missing. Idempotent."""
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                user_id          TEXT PRIMARY KEY,
                clerk_id         TEXT UNIQUE NOT NULL,
                email            TEXT UNIQUE NOT NULL COLLATE NOCASE,
                data_user_slug   TEXT UNIQUE NOT NULL,
                role             TEXT NOT NULL DEFAULT 'user',
                tier             TEXT NOT NULL DEFAULT 'lite',
                status           TEXT NOT NULL DEFAULT 'pending',
                credits          INTEGER NOT NULL DEFAULT 100,
                credits_reset_at TEXT NOT NULL,
                created_at       TEXT NOT NULL,
                last_login_at    TEXT
            );

            CREATE TABLE IF NOT EXISTS credit_log (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                delta   INTEGER NOT NULL,
                reason  TEXT NOT NULL,
                run_id  TEXT,
                at      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pipeline_runs (
                run_id              TEXT PRIMARY KEY,
                user_id             TEXT NOT NULL,
                parent_run_id       TEXT,
                agent               TEXT NOT NULL,
                status              TEXT NOT NULL,
                credits_cost        INTEGER NOT NULL,
                credits_refunded    INTEGER DEFAULT 0,
                started_at          TEXT,
                finished_at         TEXT,
                progress_json       TEXT,
                error               TEXT,
                output_summary_json TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_pipeline_runs_user_status
                ON pipeline_runs(user_id, status);
            CREATE INDEX IF NOT EXISTS idx_pipeline_runs_parent
                ON pipeline_runs(parent_run_id);

            CREATE TABLE IF NOT EXISTS waitlist (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      TEXT NOT NULL,
                desired_tier TEXT NOT NULL,
                submitted_at TEXT NOT NULL,
                fulfilled    INTEGER NOT NULL DEFAULT 0
            );
            """
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_reset() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def create_account(
    *,
    clerk_id: str,
    email: str,
    data_user_slug: str,
    role: str = "user",
    tier: str = "lite",
    status: str = "pending",
    credits: int = 100,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Insert a fresh account row. Returns the row."""
    user_id = str(uuid.uuid4())
    now = _now()
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO accounts
               (user_id, clerk_id, email, data_user_slug, role, tier, status,
                credits, credits_reset_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, clerk_id, email, data_user_slug, role, tier, status,
             credits, _next_reset(), now),
        )
    return get_account_by_clerk_id(clerk_id, db_path=db_path)  # type: ignore[return-value]


def get_account_by_clerk_id(clerk_id: str, db_path: Path | None = None) -> dict[str, Any] | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM accounts WHERE clerk_id = ?", (clerk_id,),
        ).fetchone()
    return _row_to_dict(row)


def get_account_by_email(email: str, db_path: Path | None = None) -> dict[str, Any] | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM accounts WHERE email = ? COLLATE NOCASE", (email,),
        ).fetchone()
    return _row_to_dict(row)


def update_account_status(clerk_id: str, status: str, db_path: Path | None = None) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE accounts SET status = ? WHERE clerk_id = ?", (status, clerk_id),
        )


def update_last_login(clerk_id: str, db_path: Path | None = None) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE accounts SET last_login_at = ? WHERE clerk_id = ?",
            (_now(), clerk_id),
        )


def enqueue_pipeline_run(
    *, user_id: str, agent: str, credits_cost: int = 0,
    parent_run_id: str | None = None, db_path: Path | None = None,
) -> dict[str, Any]:
    """Insert a queued pipeline_runs row. Returns the row."""
    run_id = str(uuid.uuid4())
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO pipeline_runs
               (run_id, user_id, parent_run_id, agent, status, credits_cost)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (run_id, user_id, parent_run_id, agent, "queued", credits_cost),
        )
    return get_run(run_id, db_path=db_path)  # type: ignore[return-value]


def get_run(run_id: str, db_path: Path | None = None) -> dict[str, Any] | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM pipeline_runs WHERE run_id = ?", (run_id,),
        ).fetchone()
    return _row_to_dict(row)


def mark_run_completed(
    run_id: str, *, output_summary: dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> None:
    import json as _json
    with _connect(db_path) as conn:
        conn.execute(
            """UPDATE pipeline_runs
               SET status='completed', finished_at=?, output_summary_json=?
               WHERE run_id=?""",
            (_now(), _json.dumps(output_summary or {}), run_id),
        )


def mark_run_failed(run_id: str, *, error: str, db_path: Path | None = None) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """UPDATE pipeline_runs
               SET status='failed', finished_at=?, error=?
               WHERE run_id=?""",
            (_now(), error, run_id),
        )


def log_credit_change(
    *, user_id: str, delta: int, reason: str, run_id: str | None = None,
    db_path: Path | None = None,
) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO credit_log (user_id, delta, reason, run_id, at) VALUES (?,?,?,?,?)",
            (user_id, delta, reason, run_id, _now()),
        )
