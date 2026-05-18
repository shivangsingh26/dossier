"""Tests GET /me."""
from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from dossier_api.db import create_account, init_db
from dossier_api.main import app


def test_me_returns_401_without_auth(tmp_db_path):
    init_db(tmp_db_path)
    client = TestClient(app)
    r = client.get("/me")
    assert r.status_code == 401


def test_me_returns_403_when_no_account_row(tmp_db_path):
    init_db(tmp_db_path)
    client = TestClient(app)
    with patch("dossier_api.deps._verify_clerk_jwt", return_value="user_no_match"):
        r = client.get("/me", headers={"Authorization": "Bearer faketoken"})
    assert r.status_code == 403


def test_me_returns_account_row_when_authorized(tmp_db_path):
    init_db(tmp_db_path)
    create_account(
        clerk_id="user_abc",
        email="abc@example.com",
        data_user_slug="abc",
        status="active",
        tier="max",
        credits=42,
    )
    client = TestClient(app)
    with patch("dossier_api.deps._verify_clerk_jwt", return_value="user_abc"):
        r = client.get("/me", headers={"Authorization": "Bearer faketoken"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "abc@example.com"
    assert body["tier"] == "max"
    assert body["credits"] == 42
    assert body["status"] == "active"


def test_me_returns_403_when_suspended(tmp_db_path):
    init_db(tmp_db_path)
    create_account(
        clerk_id="user_susp", email="s@x.io", data_user_slug="susp", status="suspended",
    )
    client = TestClient(app)
    with patch("dossier_api.deps._verify_clerk_jwt", return_value="user_susp"):
        r = client.get("/me", headers={"Authorization": "Bearer faketoken"})
    assert r.status_code == 403
