"""Tests worker handler for agent=persona_synthesis."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from dossier_api.db import (
    create_account,
    enqueue_pipeline_run,
    get_run,
    init_db,
)
from dossier_api.workers.pipeline_worker import process_run


@pytest.fixture
def seeded_run(tmp_db_path, tmp_path, monkeypatch):
    init_db(tmp_db_path)
    acct = create_account(
        clerk_id="user_w", email="w@x.io", data_user_slug="w",
        status="active", tier="max",
    )
    profile_root = tmp_path / "profile"
    (profile_root / acct["data_user_slug"] / "raw").mkdir(parents=True)
    (profile_root / acct["data_user_slug"] / "raw" / "resume.pdf").write_bytes(b"%PDF")
    (profile_root / acct["data_user_slug"] / "questionnaire.json").write_text(
        json.dumps({
            "identity": {"name": "W"},
            "target": {"min_salary_lpa": 25, "roles": ["MLE"]},
            "work_preferences": {},
        })
    )
    (profile_root / acct["data_user_slug"] / "quiz_answers.json").write_text(
        json.dumps({f"q{i}": "a" for i in range(13)})
    )

    def _slug_to_dir(slug: str) -> Path:
        d = profile_root / slug
        d.mkdir(parents=True, exist_ok=True)
        return d
    monkeypatch.setattr("dossier_api.services.persona_service.profile_dir_for", _slug_to_dir)

    run = enqueue_pipeline_run(user_id=acct["user_id"], agent="persona_synthesis", credits_cost=0)
    return {"acct": acct, "run": run, "profile_root": profile_root}


def test_process_run_persona_synthesis_writes_profile_json(seeded_run):
    fake_profile = {"identity": {"name": "Synthesized"}, "target": {"min_salary_lpa": 25}}
    with (
        patch("dossier_sdk.agents.persona_builder.parse_resume", return_value="resume text"),
        patch("dossier_sdk.agents.persona_builder.parse_linkedin_pdf", return_value=""),
        patch(
            "dossier_sdk.agents.persona_builder.synthesize_profile",
            return_value=fake_profile,
        ),
    ):
        process_run(seeded_run["run"])
    finished = get_run(seeded_run["run"]["run_id"])
    assert finished["status"] == "completed"
    saved = seeded_run["profile_root"] / seeded_run["acct"]["data_user_slug"] / "profile.json"
    assert json.loads(saved.read_text())["identity"]["name"] == "Synthesized"


def test_process_run_unknown_agent_marks_failed(tmp_db_path):
    init_db(tmp_db_path)
    acct = create_account(clerk_id="u", email="u@x.io", data_user_slug="u", status="active")
    run = enqueue_pipeline_run(user_id=acct["user_id"], agent="bogus", credits_cost=0)
    process_run(run)
    finished = get_run(run["run_id"])
    assert finished["status"] == "failed"
    assert "unknown agent" in (finished["error"] or "").lower()
