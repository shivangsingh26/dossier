"""Tests pipeline_worker pick + idle behavior."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from dossier_api.db import init_db
from dossier_api.workers.pipeline_worker import pick_next_queued_run


def _insert_run(db_path: Path, run_id: str, status: str = "queued") -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO pipeline_runs
           (run_id, user_id, agent, status, credits_cost)
           VALUES (?, ?, ?, ?, ?)""",
        (run_id, "u1", "discovery", status, 5),
    )
    conn.commit()
    conn.close()


def test_pick_returns_none_when_no_queued_runs(tmp_db_path: Path):
    init_db(tmp_db_path)
    assert pick_next_queued_run(db_path=tmp_db_path) is None


def test_pick_picks_oldest_queued_run_and_marks_running(tmp_db_path: Path):
    init_db(tmp_db_path)
    _insert_run(tmp_db_path, "r1")
    _insert_run(tmp_db_path, "r2")
    picked = pick_next_queued_run(db_path=tmp_db_path)
    assert picked is not None
    assert picked["run_id"] in {"r1", "r2"}
    conn = sqlite3.connect(tmp_db_path)
    row = conn.execute(
        "SELECT status, started_at FROM pipeline_runs WHERE run_id = ?",
        (picked["run_id"],),
    ).fetchone()
    conn.close()
    assert row[0] == "running"
    assert row[1] is not None


def test_pick_skips_already_running_runs(tmp_db_path: Path):
    init_db(tmp_db_path)
    _insert_run(tmp_db_path, "r1", status="running")
    assert pick_next_queued_run(db_path=tmp_db_path) is None
