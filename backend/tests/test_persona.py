"""Tests /persona/* endpoints."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from dossier_api.db import create_account, init_db
from dossier_api.main import app


@pytest.fixture
def active_user(tmp_db_path, tmp_path, monkeypatch):
    """Active user with isolated profile dir. Patches persona_service.profile_dir_for."""
    init_db(tmp_db_path)
    create_account(
        clerk_id="user_p1", email="p1@x.io", data_user_slug="p1",
        status="active", tier="max",
    )
    profile_root = tmp_path / "profile"
    profile_root.mkdir()

    def _slug_to_dir(slug: str) -> Path:
        d = profile_root / slug
        d.mkdir(parents=True, exist_ok=True)
        return d

    monkeypatch.setattr("dossier_api.services.persona_service.profile_dir_for", _slug_to_dir)
    return {"clerk_id": "user_p1", "slug": "p1", "profile_root": profile_root}


def _client_for(clerk_id: str) -> TestClient:
    return TestClient(app)


def test_get_persona_returns_404_when_no_profile_json(active_user):
    client = _client_for(active_user["clerk_id"])
    with patch("dossier_api.deps._verify_clerk_jwt", return_value=active_user["clerk_id"]):
        r = client.get("/persona", headers={"Authorization": "Bearer t"})
    assert r.status_code == 404


def test_upload_pdf_requires_at_least_one_file(active_user):
    client = _client_for(active_user["clerk_id"])
    with patch("dossier_api.deps._verify_clerk_jwt", return_value=active_user["clerk_id"]):
        r = client.post("/persona/upload-pdf", headers={"Authorization": "Bearer t"})
    assert r.status_code == 400


def test_upload_pdf_saves_resume_file(active_user):
    fake_pdf = b"%PDF-1.4 fake content"
    client = _client_for(active_user["clerk_id"])
    with patch("dossier_api.deps._verify_clerk_jwt", return_value=active_user["clerk_id"]):
        r = client.post(
            "/persona/upload-pdf",
            headers={"Authorization": "Bearer t"},
            files={"resume": ("my_resume.pdf", fake_pdf, "application/pdf")},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "resume" in body["saved"]
    saved_path = active_user["profile_root"] / active_user["slug"] / "raw" / "my_resume.pdf"
    assert saved_path.exists()
    assert saved_path.read_bytes() == fake_pdf


def test_upload_pdf_rejects_oversized_file(active_user):
    big = b"x" * (11 * 1024 * 1024)  # 11MB > 10MB cap
    client = _client_for(active_user["clerk_id"])
    with patch("dossier_api.deps._verify_clerk_jwt", return_value=active_user["clerk_id"]):
        r = client.post(
            "/persona/upload-pdf",
            headers={"Authorization": "Bearer t"},
            files={"resume": ("big.pdf", big, "application/pdf")},
        )
    assert r.status_code == 413


def test_post_questionnaire_saves_json(active_user):
    payload = {
        "identity": {"name": "Test", "current_role": "MLE"},
        "target": {"min_salary_lpa": 25, "roles": ["MLE-1"]},
        "work_preferences": {"remote_ok": True},
    }
    client = _client_for(active_user["clerk_id"])
    with patch("dossier_api.deps._verify_clerk_jwt", return_value=active_user["clerk_id"]):
        r = client.post(
            "/persona/questionnaire",
            headers={"Authorization": "Bearer t"},
            json=payload,
        )
    assert r.status_code == 200
    saved = active_user["profile_root"] / active_user["slug"] / "questionnaire.json"
    assert saved.exists()
    assert json.loads(saved.read_text())["target"]["min_salary_lpa"] == 25


def test_get_state_reports_progress(active_user):
    client = _client_for(active_user["clerk_id"])
    with patch("dossier_api.deps._verify_clerk_jwt", return_value=active_user["clerk_id"]):
        r = client.get("/persona/state", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "pdfs_uploaded": False,
        "questionnaire_done": False,
        "quiz_done": False,
        "synthesized": False,
    }


def test_get_quiz_questions_returns_sdk_set(active_user):
    from dossier_sdk.agents.persona_builder import INTERVIEW_QUESTIONS

    client = _client_for(active_user["clerk_id"])
    with patch("dossier_api.deps._verify_clerk_jwt", return_value=active_user["clerk_id"]):
        r = client.get("/persona/quiz-questions", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["questions"]) == len(INTERVIEW_QUESTIONS)
    assert {"id", "question", "hint"} <= set(body["questions"][0].keys())


def test_post_quiz_answers_saves_dict(active_user):
    payload = {"answers": {f"q{i}": f"answer {i}" for i in range(13)}}
    client = _client_for(active_user["clerk_id"])
    with patch("dossier_api.deps._verify_clerk_jwt", return_value=active_user["clerk_id"]):
        r = client.post(
            "/persona/quiz-answers",
            headers={"Authorization": "Bearer t"},
            json=payload,
        )
    assert r.status_code == 200
    saved = active_user["profile_root"] / active_user["slug"] / "quiz_answers.json"
    assert json.loads(saved.read_text())["q0"] == "answer 0"


def test_finalize_requires_prereqs(active_user):
    client = _client_for(active_user["clerk_id"])
    with patch("dossier_api.deps._verify_clerk_jwt", return_value=active_user["clerk_id"]):
        r = client.post("/persona/finalize", headers={"Authorization": "Bearer t"})
    assert r.status_code == 400


def test_finalize_enqueues_run_when_ready(active_user):
    slug = active_user["slug"]
    root = active_user["profile_root"] / slug
    (root / "raw").mkdir(parents=True, exist_ok=True)
    (root / "raw" / "resume.pdf").write_bytes(b"%PDF fake")
    (root / "questionnaire.json").write_text(json.dumps({"target": {"min_salary_lpa": 25}}))
    (root / "quiz_answers.json").write_text(json.dumps({"q1": "a"}))
    client = _client_for(active_user["clerk_id"])
    with patch("dossier_api.deps._verify_clerk_jwt", return_value=active_user["clerk_id"]):
        r = client.post("/persona/finalize", headers={"Authorization": "Bearer t"})
    assert r.status_code == 202, r.text
    body = r.json()
    assert "run_id" in body
    assert body["status"] == "queued"


def test_patch_persona_merges_into_profile(active_user):
    slug = active_user["slug"]
    slug_dir = active_user["profile_root"] / slug
    slug_dir.mkdir(exist_ok=True)
    initial = {"identity": {"name": "Old"}, "target": {"min_salary_lpa": 25}}
    (slug_dir / "profile.json").write_text(json.dumps(initial))
    client = _client_for(active_user["clerk_id"])
    with patch("dossier_api.deps._verify_clerk_jwt", return_value=active_user["clerk_id"]):
        r = client.patch(
            "/persona",
            headers={"Authorization": "Bearer t"},
            json={"patch": {"identity": {"name": "New"}}},
        )
    assert r.status_code == 200
    after = json.loads((slug_dir / "profile.json").read_text())
    assert after["identity"]["name"] == "New"
    assert after["target"]["min_salary_lpa"] == 25


def test_patch_persona_returns_404_if_no_profile(active_user):
    client = _client_for(active_user["clerk_id"])
    with patch("dossier_api.deps._verify_clerk_jwt", return_value=active_user["clerk_id"]):
        r = client.patch(
            "/persona",
            headers={"Authorization": "Bearer t"},
            json={"patch": {"identity": {"name": "x"}}},
        )
    assert r.status_code == 404


def test_get_persona_returns_profile_json_when_present(active_user):
    fake_profile = {"identity": {"name": "Test"}, "target": {"min_salary_lpa": 25}}
    slug_dir = active_user["profile_root"] / active_user["slug"]
    slug_dir.mkdir(exist_ok=True)
    (slug_dir / "profile.json").write_text(json.dumps(fake_profile))
    client = _client_for(active_user["clerk_id"])
    with patch("dossier_api.deps._verify_clerk_jwt", return_value=active_user["clerk_id"]):
        r = client.get("/persona", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    assert r.json()["identity"]["name"] == "Test"
