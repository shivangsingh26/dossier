"""Tests POST /webhooks/clerk."""
from __future__ import annotations

import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from dossier_api.db import get_account_by_clerk_id, init_db
from dossier_api.main import app


USER_CREATED_PAYLOAD = {
    "type": "user.created",
    "data": {
        "id": "user_new_signup_1",
        "email_addresses": [
            {"id": "idn_1", "email_address": "new@user.io"},
        ],
        "primary_email_address_id": "idn_1",
    },
}


def test_webhook_rejects_invalid_signature(tmp_db_path, monkeypatch):
    init_db(tmp_db_path)
    monkeypatch.setenv("CLERK_WEBHOOK_SECRET", "whsec_invalid")
    from dossier_api.settings import get_settings
    get_settings.cache_clear()
    client = TestClient(app)
    r = client.post(
        "/webhooks/clerk",
        headers={
            "svix-id": "msg_1",
            "svix-timestamp": "1",
            "svix-signature": "v1,deadbeef",
        },
        content=json.dumps(USER_CREATED_PAYLOAD),
    )
    assert r.status_code == 400


def test_webhook_user_created_inserts_pending_account(tmp_db_path):
    init_db(tmp_db_path)
    client = TestClient(app)
    with patch("dossier_api.routers.webhooks._verify_webhook", return_value=USER_CREATED_PAYLOAD):
        r = client.post(
            "/webhooks/clerk",
            headers={"svix-id": "msg_1", "svix-timestamp": "1", "svix-signature": "v1,fake"},
            content=json.dumps(USER_CREATED_PAYLOAD),
        )
    assert r.status_code == 200
    acct = get_account_by_clerk_id("user_new_signup_1")
    assert acct is not None
    assert acct["email"] == "new@user.io"
    assert acct["status"] == "pending"
    assert acct["tier"] == "lite"
    assert acct["credits"] == 100


def test_webhook_user_created_is_idempotent(tmp_db_path):
    init_db(tmp_db_path)
    client = TestClient(app)
    with patch("dossier_api.routers.webhooks._verify_webhook", return_value=USER_CREATED_PAYLOAD):
        r1 = client.post(
            "/webhooks/clerk",
            headers={"svix-id": "m", "svix-timestamp": "1", "svix-signature": "x"},
            content=json.dumps(USER_CREATED_PAYLOAD),
        )
        r2 = client.post(
            "/webhooks/clerk",
            headers={"svix-id": "m", "svix-timestamp": "1", "svix-signature": "x"},
            content=json.dumps(USER_CREATED_PAYLOAD),
        )
    assert r1.status_code == 200
    assert r2.status_code == 200


def test_webhook_unhandled_event_returns_200(tmp_db_path):
    init_db(tmp_db_path)
    payload = {"type": "session.created", "data": {}}
    client = TestClient(app)
    with patch("dossier_api.routers.webhooks._verify_webhook", return_value=payload):
        r = client.post(
            "/webhooks/clerk",
            headers={"svix-id": "m", "svix-timestamp": "1", "svix-signature": "x"},
            content=json.dumps(payload),
        )
    assert r.status_code == 200
