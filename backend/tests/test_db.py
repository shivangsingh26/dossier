"""Tests accounts.db schema + helpers."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from dossier_api.db import (
    create_account,
    get_account_by_clerk_id,
    get_account_by_email,
    init_db,
    log_credit_change,
    update_account_status,
)


def _tables(db: Path) -> set[str]:
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    conn.close()
    return {r[0] for r in rows}


def test_init_db_creates_all_tables(tmp_db_path: Path):
    init_db(tmp_db_path)
    tables = _tables(tmp_db_path)
    assert {"accounts", "credit_log", "pipeline_runs", "waitlist"} <= tables


def test_init_db_is_idempotent(tmp_db_path: Path):
    init_db(tmp_db_path)
    init_db(tmp_db_path)
    assert tmp_db_path.exists()


def test_create_account_inserts_row(tmp_db_path: Path):
    init_db(tmp_db_path)
    acct = create_account(
        clerk_id="user_test1",
        email="test@example.com",
        data_user_slug="user_test1",
    )
    assert acct["clerk_id"] == "user_test1"
    assert acct["status"] == "pending"
    assert acct["tier"] == "lite"
    assert acct["credits"] == 100


def test_get_account_by_clerk_id(tmp_db_path: Path):
    init_db(tmp_db_path)
    create_account(clerk_id="user_x", email="x@y.com", data_user_slug="x")
    found = get_account_by_clerk_id("user_x")
    assert found is not None
    assert found["email"] == "x@y.com"
    assert get_account_by_clerk_id("nope") is None


def test_get_account_by_email_case_insensitive(tmp_db_path: Path):
    init_db(tmp_db_path)
    create_account(clerk_id="user_x", email="MiXed@Case.io", data_user_slug="x")
    assert get_account_by_email("mixed@case.io") is not None


def test_update_account_status(tmp_db_path: Path):
    init_db(tmp_db_path)
    create_account(clerk_id="user_x", email="x@y.com", data_user_slug="x")
    update_account_status("user_x", "active")
    assert get_account_by_clerk_id("user_x")["status"] == "active"


def test_log_credit_change_records_ledger_entry(tmp_db_path: Path):
    init_db(tmp_db_path)
    acct = create_account(clerk_id="user_x", email="x@y.com", data_user_slug="x")
    log_credit_change(user_id=acct["user_id"], delta=-5, reason="run:disc")
    conn = sqlite3.connect(tmp_db_path)
    rows = conn.execute("SELECT delta, reason FROM credit_log").fetchall()
    conn.close()
    assert rows == [(-5, "run:disc")]
