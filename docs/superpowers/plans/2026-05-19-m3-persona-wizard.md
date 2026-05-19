# M3 — Persona Builder Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** [docs/superpowers/specs/2026-05-18-dossier-saas-frontend-design.md](../specs/2026-05-18-dossier-saas-frontend-design.md) §9 (`/persona/*` endpoints), §10 (`/onboarding` route), §15 M3 (acceptance).

**Goal:** Replace terminal `persona_builder.py` interview with a 4-step web wizard. Backend wraps the existing SDK; worker runs the LLM synthesis off the HTTP request; frontend polls for completion and lands on `/dashboard`.

**Architecture:** Frontend wizard owns step state in URL query (`?step=upload|targets|quiz|review`). Each step PUT/POSTs to FastAPI which persists incrementally to `profile/{slug}/`. Step 3 (quiz) renders hardcoded `INTERVIEW_QUESTIONS` from the SDK via a chat-style UI (AI Elements components); no LLM per question. Step 4 calls `/persona/finalize` which enqueues a `pipeline_runs` row with `agent="persona_synthesis"`. The worker picks it up, calls `sdk.agents.persona_builder.synthesize_profile()`, writes `profile/{slug}/profile.json`, marks the run completed. Frontend polls `/pipeline/runs/{id}` every 2s. On completion, fetches the persona, shows Review step. User can edit fields → PATCH `/persona` → Finalize click → redirect to `/dashboard`.

**Tech Stack:**
- Backend additions: `python-multipart` (FastAPI file uploads — already pulled in by fastapi extras, verify).
- Frontend additions: `react-hook-form`, `zod`, `@hookform/resolvers`, `react-dropzone`. Plus `ai` SDK base for `useChat`-style state primitives (no real LLM call, but reuses message shape); optional AI Elements registry components via `pnpm dlx shadcn@latest add`.

**Collaboration style (locked from user):**
- Agent runs all `uv`, `pnpm`, `python`, `node`, `npm` commands directly.
- User runs all `git add` + `git commit` + `git push` + `gh pr ...` himself.
- Commits batched every ~3 tasks. Agent halts with suggested commit message + file list; user commits.
- Branch: `feat/m3-persona-wizard` off `main` (already created).

---

## Decisions locked (asked + answered)

| Decision | Choice |
|---|---|
| Quiz format | Hardcoded `INTERVIEW_QUESTIONS` (12) rendered via AI Elements chat UI; no LLM per turn |
| PDF storage path | `profile/{slug}/raw/` — matches existing SDK pipeline; zero SDK changes |
| Onboarding gate | Backend `GET /persona` 404 → frontend redirects to `/onboarding`. Single source of truth. |
| Credits cost for synthesis | Zero (onboarding is free per spec §15 M3) |
| Synthesis execution | Worker picks `agent="persona_synthesis"` run, calls `synthesize_profile()` (~30-60s) |
| Polling vs SSE for synthesis progress | Polling `/pipeline/runs/{id}` every 2s (simpler; SSE deferred to M4 where it matters more) |

---

## File Structure

**Backend — new:**
- `backend/src/dossier_api/routers/persona.py` — all `/persona/*` endpoints
- `backend/src/dossier_api/services/__init__.py`
- `backend/src/dossier_api/services/persona_service.py` — wraps SDK calls + path helpers
- `backend/src/dossier_api/models/persona.py` — pydantic schemas for wizard payloads
- `backend/tests/test_persona.py` — endpoint tests
- `backend/tests/test_persona_worker.py` — worker handler test (mocks synthesize)

**Backend — modified:**
- `backend/src/dossier_api/main.py` — register persona router
- `backend/src/dossier_api/workers/pipeline_worker.py` — dispatch table for `agent="persona_synthesis"`
- `backend/src/dossier_api/db.py` — helpers: `enqueue_pipeline_run`, `mark_run_completed`, `mark_run_failed`, `get_run`

**Frontend — new:**
- `frontend/app/(app)/onboarding/page.tsx` — wizard host
- `frontend/components/dossier/wizard/Stepper.tsx`
- `frontend/components/dossier/wizard/UploadStep.tsx`
- `frontend/components/dossier/wizard/TargetsStep.tsx`
- `frontend/components/dossier/wizard/QuizStep.tsx`
- `frontend/components/dossier/wizard/ReviewStep.tsx`
- `frontend/components/dossier/wizard/SynthesisProgress.tsx`
- `frontend/lib/persona-schema.ts` — zod schemas matching SDK profile.json
- `frontend/lib/api/persona.ts` — typed client wrappers for `/persona/*` and `/pipeline/runs/{id}`

**Frontend — modified:**
- `frontend/app/(app)/layout.tsx` — after active gate, check `/persona` → redirect to `/onboarding` if 404
- `frontend/components/dossier/Sidebar.tsx` — hide sidebar on `/onboarding` (no nav distraction)
- `frontend-todo.txt` — tick M3 boxes as done

---

## Phase declaration

Per CLAUDE.md: **Phase A → B**. Backend uses sync I/O for endpoints. Worker still polls SQLite synchronously (Phase A → B transition documented in M2). SSE deferred to M4 again. No new async patterns beyond what FastAPI gives us for free.

---

## Tasks

### Task 1: Backend persona router skeleton + GET /persona (TDD)

**Files:**
- Create: `backend/src/dossier_api/routers/persona.py`
- Create: `backend/src/dossier_api/services/__init__.py`
- Create: `backend/src/dossier_api/services/persona_service.py`
- Create: `backend/src/dossier_api/models/persona.py`
- Create: `backend/tests/test_persona.py`
- Modify: `backend/src/dossier_api/main.py`

**Concept primer:** The router holds 6 endpoints under `/persona/*`. Service layer wraps filesystem reads/writes so the route handler stays thin. Tests mock the Clerk JWT via `_verify_clerk_jwt` patch (same pattern as M2 `/me` tests).

- [ ] **Step 1: Write failing test for GET /persona**

```python
# backend/tests/test_persona.py
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
    c = TestClient(app)
    return c


def test_get_persona_returns_404_when_no_profile_json(active_user):
    client = _client_for(active_user["clerk_id"])
    with patch("dossier_api.deps._verify_clerk_jwt", return_value=active_user["clerk_id"]):
        r = client.get("/persona", headers={"Authorization": "Bearer t"})
    assert r.status_code == 404


def test_get_persona_returns_profile_json_when_present(active_user):
    fake_profile = {"identity": {"name": "Test"}, "target": {"min_salary_lpa": 25}}
    (active_user["profile_root"] / active_user["slug"]).mkdir(exist_ok=True)
    (active_user["profile_root"] / active_user["slug"] / "profile.json").write_text(
        json.dumps(fake_profile)
    )
    client = _client_for(active_user["clerk_id"])
    with patch("dossier_api.deps._verify_clerk_jwt", return_value=active_user["clerk_id"]):
        r = client.get("/persona", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    assert r.json()["identity"]["name"] == "Test"
```

- [ ] **Step 2: Run test to confirm fail**

Run: `cd backend && uv run pytest tests/test_persona.py -v`
Expected: ImportError or 404 mismatch.

- [ ] **Step 3: Implement service helpers**

```python
# backend/src/dossier_api/services/persona_service.py
"""Filesystem + SDK glue for persona endpoints.

Resolves the per-user profile dir at profile/{slug}/. Tests monkeypatch
profile_dir_for so they can isolate filesystem writes.
"""
from __future__ import annotations

import json
from pathlib import Path

from dossier_api.settings import REPO_ROOT


def profile_dir_for(slug: str) -> Path:
    """Return profile/{slug}/ under repo root. Creates if missing."""
    d = REPO_ROOT / "profile" / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def raw_dir_for(slug: str) -> Path:
    d = profile_dir_for(slug) / "raw"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_profile_json(slug: str) -> dict | None:
    p = profile_dir_for(slug) / "profile.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def save_profile_json(slug: str, data: dict) -> None:
    p = profile_dir_for(slug) / "profile.json"
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_questionnaire(slug: str) -> dict | None:
    p = profile_dir_for(slug) / "questionnaire.json"
    return json.loads(p.read_text()) if p.exists() else None


def save_questionnaire(slug: str, data: dict) -> None:
    p = profile_dir_for(slug) / "questionnaire.json"
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_quiz_answers(slug: str) -> dict | None:
    p = profile_dir_for(slug) / "quiz_answers.json"
    return json.loads(p.read_text()) if p.exists() else None


def save_quiz_answers(slug: str, data: dict) -> None:
    p = profile_dir_for(slug) / "quiz_answers.json"
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
```

Add `services/__init__.py`:

```python
"""Service layer — wraps SDK calls + filesystem ops."""
```

- [ ] **Step 4: Implement models**

```python
# backend/src/dossier_api/models/persona.py
"""Pydantic payloads for /persona/* endpoints."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class QuestionnairePayload(BaseModel):
    """Step 2 — Targets/identity form."""
    identity: dict[str, Any] = Field(default_factory=dict)
    target: dict[str, Any]
    work_preferences: dict[str, Any] = Field(default_factory=dict)


class QuizAnswers(BaseModel):
    """Step 3 — 12 question:answer map."""
    answers: dict[str, str]


class PersonaPatch(BaseModel):
    """PATCH /persona — partial update of profile.json after synthesis."""
    patch: dict[str, Any]


class FinalizeResponse(BaseModel):
    run_id: str
    status: str
```

- [ ] **Step 5: Implement persona router**

```python
# backend/src/dossier_api/routers/persona.py
"""All /persona/* endpoints. Auth-gated; uses persona_service for I/O."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from dossier_api.deps import get_current_user
from dossier_api.models.persona import PersonaPatch, QuestionnairePayload, QuizAnswers
from dossier_api.services import persona_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/persona")


@router.get("")
async def get_persona(user: dict[str, Any] = Depends(get_current_user)):
    profile = persona_service.load_profile_json(user["data_user_slug"])
    if profile is None:
        raise HTTPException(status_code=404, detail="profile.json not yet synthesized")
    return profile
```

- [ ] **Step 6: Register router in main.py**

Edit `backend/src/dossier_api/main.py`:

```python
from dossier_api.routers import health, me, persona, webhooks
# ...
app.include_router(persona.router)
```

- [ ] **Step 7: Run tests to confirm pass**

Run: `uv run pytest tests/test_persona.py -v`
Expected: 2 passed.

---

### Task 2: POST /persona/upload-pdf (multipart)

**Files:**
- Modify: `backend/src/dossier_api/routers/persona.py`
- Modify: `backend/src/dossier_api/services/persona_service.py`
- Modify: `backend/tests/test_persona.py`

**Concept primer:** FastAPI `UploadFile` parses multipart for us. We size-cap at 10MB (spec §13) and accept exactly the field names `resume`, `linkedin` (both optional in the same request, but at least one required). Saved to `profile/{slug}/raw/<original_filename>`.

- [ ] **Step 1: Add failing tests**

Append to `backend/tests/test_persona.py`:

```python
def test_upload_pdf_requires_at_least_one_file(active_user):
    client = _client_for(active_user["clerk_id"])
    with patch("dossier_api.deps._verify_clerk_jwt", return_value=active_user["clerk_id"]):
        r = client.post("/persona/upload-pdf", headers={"Authorization": "Bearer t"})
    assert r.status_code == 400


def test_upload_pdf_saves_resume_file(active_user, tmp_path):
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
```

- [ ] **Step 2: Run tests to confirm fail**

Run: `uv run pytest tests/test_persona.py -v`
Expected: 3 new failures (`upload-pdf` route 404 or missing).

- [ ] **Step 3: Add service helper**

Append to `persona_service.py`:

```python
MAX_PDF_BYTES = 10 * 1024 * 1024  # 10MB per spec §13


def save_uploaded_pdf(slug: str, file_kind: str, filename: str, content: bytes) -> Path:
    """Save <content> to profile/{slug}/raw/<filename>. Returns path."""
    if len(content) > MAX_PDF_BYTES:
        raise ValueError(f"file exceeds {MAX_PDF_BYTES // (1024 * 1024)}MB limit")
    if file_kind not in {"resume", "linkedin"}:
        raise ValueError(f"unsupported file kind: {file_kind}")
    safe_name = "".join(c for c in filename if c.isalnum() or c in {".", "_", "-"})
    if not safe_name:
        safe_name = f"{file_kind}.pdf"
    out = raw_dir_for(slug) / safe_name
    out.write_bytes(content)
    return out
```

- [ ] **Step 4: Add upload route**

Append to `routers/persona.py`:

```python
from fastapi import File, UploadFile


@router.post("/upload-pdf")
async def upload_pdf(
    user: dict[str, Any] = Depends(get_current_user),
    resume: UploadFile | None = File(default=None),
    linkedin: UploadFile | None = File(default=None),
):
    if resume is None and linkedin is None:
        raise HTTPException(status_code=400, detail="At least one of resume / linkedin required")

    saved: dict[str, str] = {}
    for kind, upload in [("resume", resume), ("linkedin", linkedin)]:
        if upload is None:
            continue
        content = await upload.read()
        try:
            path = persona_service.save_uploaded_pdf(
                user["data_user_slug"], kind, upload.filename or f"{kind}.pdf", content,
            )
        except ValueError as exc:
            msg = str(exc)
            code = 413 if "exceeds" in msg else 400
            raise HTTPException(status_code=code, detail=msg) from exc
        saved[kind] = path.name
    return {"saved": saved}
```

- [ ] **Step 5: Run tests to confirm pass**

Run: `uv run pytest tests/test_persona.py -v`
Expected: 5 passed.

---

### Task 3: POST /persona/questionnaire + GET /persona/state

**Files:**
- Modify: `backend/src/dossier_api/routers/persona.py`
- Modify: `backend/tests/test_persona.py`

**Concept primer:** Frontend posts the targets form here. Service saves to `questionnaire.json`. We also add a `GET /persona/state` that returns wizard progress (`pdfs_uploaded`, `questionnaire_done`, `quiz_done`, `synthesized`) so the wizard can resume mid-flow.

- [ ] **Step 1: Failing tests**

```python
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
```

- [ ] **Step 2: Run tests to confirm fail**

Run: `uv run pytest tests/test_persona.py -v -k "questionnaire or state"`
Expected: 2 failures.

- [ ] **Step 3: Add routes**

Append to `routers/persona.py`:

```python
@router.post("/questionnaire")
async def post_questionnaire(
    payload: QuestionnairePayload,
    user: dict[str, Any] = Depends(get_current_user),
):
    persona_service.save_questionnaire(user["data_user_slug"], payload.model_dump())
    return {"status": "saved"}


@router.get("/state")
async def get_state(user: dict[str, Any] = Depends(get_current_user)):
    slug = user["data_user_slug"]
    raw_dir = persona_service.raw_dir_for(slug)
    pdfs = any(raw_dir.glob("*.pdf"))
    return {
        "pdfs_uploaded": pdfs,
        "questionnaire_done": persona_service.load_questionnaire(slug) is not None,
        "quiz_done": persona_service.load_quiz_answers(slug) is not None,
        "synthesized": persona_service.load_profile_json(slug) is not None,
    }
```

- [ ] **Step 4: Run tests to confirm pass**

Run: `uv run pytest tests/test_persona.py -v`
Expected: 7 passed.

### ── COMMIT BATCH 1 (Tasks 1-3) ──

Halt. Suggested commit:

```bash
git add backend/src/dossier_api/routers/persona.py \
        backend/src/dossier_api/services/__init__.py \
        backend/src/dossier_api/services/persona_service.py \
        backend/src/dossier_api/models/persona.py \
        backend/src/dossier_api/main.py \
        backend/tests/test_persona.py
```

```
feat(m3): persona router foundation — GET, upload-pdf, questionnaire, state

- routers/persona.py: GET /persona (404 if no profile.json), POST
  /persona/upload-pdf (multipart, 10MB cap, profile/{slug}/raw/), POST
  /persona/questionnaire, GET /persona/state (wizard resume hints)
- services/persona_service.py: filesystem helpers for profile dir, raw dir,
  profile.json, questionnaire.json, quiz_answers.json
- models/persona.py: pydantic payloads (QuestionnairePayload, QuizAnswers,
  PersonaPatch, FinalizeResponse)
- 7 new backend tests passing
```

User commits, says "go", I continue.

---

### Task 4: POST /persona/quiz-answers + GET /persona/quiz-questions

**Files:**
- Modify: `backend/src/dossier_api/routers/persona.py`
- Modify: `backend/tests/test_persona.py`

**Concept primer:** Quiz is hardcoded — pulled from `sdk.dossier_sdk.agents.persona_builder.INTERVIEW_QUESTIONS`. The GET returns the list; the POST accepts a dict of all answers at once (frontend collects through chat UI then submits when user clicks Continue).

- [ ] **Step 1: Failing tests**

```python
def test_get_quiz_questions_returns_12_items(active_user):
    client = _client_for(active_user["clerk_id"])
    with patch("dossier_api.deps._verify_clerk_jwt", return_value=active_user["clerk_id"]):
        r = client.get("/persona/quiz-questions", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["questions"]) == 12
    assert {"id", "question", "hint"} <= set(body["questions"][0].keys())


def test_post_quiz_answers_saves_dict(active_user):
    payload = {"answers": {f"q{i}": f"answer {i}" for i in range(12)}}
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
```

- [ ] **Step 2: Run tests to confirm fail**

Run: `uv run pytest tests/test_persona.py -v -k "quiz"`
Expected: 2 failures.

- [ ] **Step 3: Add routes**

Append to `routers/persona.py`:

```python
@router.get("/quiz-questions")
async def get_quiz_questions(user: dict[str, Any] = Depends(get_current_user)):
    from dossier_sdk.agents.persona_builder import INTERVIEW_QUESTIONS
    return {"questions": INTERVIEW_QUESTIONS}


@router.post("/quiz-answers")
async def post_quiz_answers(
    payload: QuizAnswers,
    user: dict[str, Any] = Depends(get_current_user),
):
    persona_service.save_quiz_answers(user["data_user_slug"], payload.answers)
    return {"status": "saved", "count": len(payload.answers)}
```

- [ ] **Step 4: Run tests to confirm pass**

Run: `uv run pytest tests/test_persona.py -v`
Expected: 9 passed.

---

### Task 5: POST /persona/finalize + DB helpers for runs

**Files:**
- Modify: `backend/src/dossier_api/routers/persona.py`
- Modify: `backend/src/dossier_api/db.py`
- Modify: `backend/tests/test_persona.py`
- Modify: `backend/tests/test_db.py`

**Concept primer:** Finalize enqueues a `pipeline_runs` row with `agent="persona_synthesis"`, `credits_cost=0`, `status="queued"`. Returns the `run_id` so the frontend can poll. We add db helpers: `enqueue_pipeline_run`, `get_run`, `mark_run_completed`, `mark_run_failed`. Worker uses these in the next task.

- [ ] **Step 1: Failing db helper tests**

Append to `backend/tests/test_db.py`:

```python
import sqlite3 as _sqlite3
from dossier_api.db import (
    enqueue_pipeline_run,
    get_run,
    mark_run_completed,
    mark_run_failed,
)


def test_enqueue_pipeline_run_inserts_row(tmp_db_path: Path):
    init_db(tmp_db_path)
    run = enqueue_pipeline_run(user_id="u1", agent="persona_synthesis", credits_cost=0)
    assert run["status"] == "queued"
    assert run["agent"] == "persona_synthesis"
    fetched = get_run(run["run_id"])
    assert fetched is not None
    assert fetched["run_id"] == run["run_id"]


def test_mark_run_completed_updates_status_and_summary(tmp_db_path: Path):
    init_db(tmp_db_path)
    run = enqueue_pipeline_run(user_id="u1", agent="persona_synthesis", credits_cost=0)
    mark_run_completed(run["run_id"], output_summary={"profile_written": True})
    fetched = get_run(run["run_id"])
    assert fetched["status"] == "completed"
    assert fetched["finished_at"] is not None
    assert json.loads(fetched["output_summary_json"])["profile_written"] is True


def test_mark_run_failed_records_error(tmp_db_path: Path):
    init_db(tmp_db_path)
    run = enqueue_pipeline_run(user_id="u1", agent="persona_synthesis", credits_cost=0)
    mark_run_failed(run["run_id"], error="boom")
    fetched = get_run(run["run_id"])
    assert fetched["status"] == "failed"
    assert fetched["error"] == "boom"
```

Add `import json` at top of test_db.py if not present.

- [ ] **Step 2: Failing test for finalize endpoint**

Append to `test_persona.py`:

```python
def test_finalize_requires_prereqs(active_user):
    # No PDFs, no questionnaire, no quiz answers → 400
    client = _client_for(active_user["clerk_id"])
    with patch("dossier_api.deps._verify_clerk_jwt", return_value=active_user["clerk_id"]):
        r = client.post("/persona/finalize", headers={"Authorization": "Bearer t"})
    assert r.status_code == 400


def test_finalize_enqueues_run_when_ready(active_user):
    slug = active_user["slug"]
    root = active_user["profile_root"] / slug
    (root / "raw").mkdir(exist_ok=True)
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
```

- [ ] **Step 3: Run tests to confirm fail**

Run: `uv run pytest tests/test_db.py tests/test_persona.py -v -k "enqueue or completed or failed or finalize"`
Expected: 5 failures.

- [ ] **Step 4: Implement db helpers**

Append to `backend/src/dossier_api/db.py`:

```python
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
```

- [ ] **Step 5: Implement finalize route**

Append to `routers/persona.py`:

```python
from dossier_api.db import enqueue_pipeline_run


@router.post("/finalize", status_code=202)
async def finalize_persona(user: dict[str, Any] = Depends(get_current_user)):
    slug = user["data_user_slug"]
    raw_dir = persona_service.raw_dir_for(slug)
    has_pdfs = any(raw_dir.glob("*.pdf"))
    has_q = persona_service.load_questionnaire(slug) is not None
    has_quiz = persona_service.load_quiz_answers(slug) is not None
    if not (has_pdfs and has_q and has_quiz):
        missing = [
            name for name, present in
            [("pdfs", has_pdfs), ("questionnaire", has_q), ("quiz_answers", has_quiz)]
            if not present
        ]
        raise HTTPException(status_code=400, detail=f"Missing wizard steps: {missing}")
    run = enqueue_pipeline_run(
        user_id=user["user_id"], agent="persona_synthesis", credits_cost=0,
    )
    logger.info("persona finalize enqueued run_id=%s slug=%s", run["run_id"], slug)
    return {"run_id": run["run_id"], "status": run["status"]}
```

- [ ] **Step 6: Add GET /pipeline/runs/{run_id} endpoint (needed for polling)**

Create `backend/src/dossier_api/routers/pipeline.py`:

```python
"""GET /pipeline/runs/{run_id} — polling endpoint for run status."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from dossier_api.db import get_run
from dossier_api.deps import get_current_user

router = APIRouter(prefix="/pipeline")


@router.get("/runs/{run_id}")
async def get_pipeline_run(
    run_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    run = get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run["user_id"] != user["user_id"] and user["role"] != "admin":
        raise HTTPException(status_code=403, detail="not your run")
    return run
```

Register in `main.py`:

```python
from dossier_api.routers import health, me, persona, pipeline, webhooks
# ...
app.include_router(pipeline.router)
```

- [ ] **Step 7: Run all backend tests to confirm pass**

Run: `uv run pytest -v`
Expected: ≥27 passed (was 19; +8 from M3 so far).

---

### Task 6: PATCH /persona

**Files:**
- Modify: `backend/src/dossier_api/routers/persona.py`
- Modify: `backend/tests/test_persona.py`

**Concept primer:** After synthesis, user edits fields in Review step → PATCH /persona with a `{patch: {...}}` body. We deep-merge into existing profile.json (shallow merge sufficient for top-level keys per spec).

- [ ] **Step 1: Failing test**

```python
def test_patch_persona_merges_into_profile(active_user):
    slug = active_user["slug"]
    initial = {"identity": {"name": "Old"}, "target": {"min_salary_lpa": 25}}
    (active_user["profile_root"] / slug / "profile.json").write_text(json.dumps(initial))
    client = _client_for(active_user["clerk_id"])
    with patch("dossier_api.deps._verify_clerk_jwt", return_value=active_user["clerk_id"]):
        r = client.patch(
            "/persona",
            headers={"Authorization": "Bearer t"},
            json={"patch": {"identity": {"name": "New"}}},
        )
    assert r.status_code == 200
    after = json.loads((active_user["profile_root"] / slug / "profile.json").read_text())
    assert after["identity"]["name"] == "New"
    assert after["target"]["min_salary_lpa"] == 25  # untouched


def test_patch_persona_returns_404_if_no_profile(active_user):
    client = _client_for(active_user["clerk_id"])
    with patch("dossier_api.deps._verify_clerk_jwt", return_value=active_user["clerk_id"]):
        r = client.patch(
            "/persona",
            headers={"Authorization": "Bearer t"},
            json={"patch": {"identity": {"name": "x"}}},
        )
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests to confirm fail**

Run: `uv run pytest tests/test_persona.py -v -k "patch"`
Expected: 2 failures.

- [ ] **Step 3: Add deep_merge helper + route**

Append to `services/persona_service.py`:

```python
def deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge overlay into base. overlay wins on conflicts."""
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out
```

Append to `routers/persona.py`:

```python
@router.patch("")
async def patch_persona(
    payload: PersonaPatch,
    user: dict[str, Any] = Depends(get_current_user),
):
    slug = user["data_user_slug"]
    existing = persona_service.load_profile_json(slug)
    if existing is None:
        raise HTTPException(status_code=404, detail="profile.json not yet synthesized")
    merged = persona_service.deep_merge(existing, payload.patch)
    persona_service.save_profile_json(slug, merged)
    return merged
```

- [ ] **Step 4: Run tests to confirm pass**

Run: `uv run pytest tests/test_persona.py -v`
Expected: all persona tests pass.

### ── COMMIT BATCH 2 (Tasks 4-6) ──

Halt. Suggested commit:

```bash
git add backend/src/dossier_api/routers/persona.py \
        backend/src/dossier_api/routers/pipeline.py \
        backend/src/dossier_api/services/persona_service.py \
        backend/src/dossier_api/db.py \
        backend/src/dossier_api/main.py \
        backend/tests/test_persona.py backend/tests/test_db.py
```

```
feat(m3): quiz endpoints + finalize + pipeline polling + PATCH /persona

- /persona/quiz-questions returns the 12 hardcoded INTERVIEW_QUESTIONS
- /persona/quiz-answers persists answers dict to quiz_answers.json
- /persona/finalize enqueues pipeline_runs row with agent=persona_synthesis,
  credits_cost=0, returns 202 + run_id; validates prereqs (pdfs +
  questionnaire + quiz_answers all present)
- PATCH /persona deep-merges edits into profile.json, 404 if no profile yet
- New db helpers: enqueue_pipeline_run, get_run, mark_run_completed,
  mark_run_failed
- New router: /pipeline/runs/{id} for status polling (auth-gated; admin or
  own-run only)
- 8 new tests passing (3 db + 5 persona)
```

User commits, says "go".

---

### Task 7: Worker handler for agent="persona_synthesis"

**Files:**
- Modify: `backend/src/dossier_api/workers/pipeline_worker.py`
- Create: `backend/tests/test_persona_worker.py`

**Concept primer:** Worker dispatch table maps `agent` → handler. `persona_synthesis` handler: load PDFs from `profile/{slug}/raw/`, parse via SDK, load questionnaire + quiz answers, call `synthesize_profile`, save `profile.json`. We test it by mocking `synthesize_profile` so we never hit Anthropic during tests.

- [ ] **Step 1: Failing test**

```python
# backend/tests/test_persona_worker.py
"""Tests worker handler for agent=persona_synthesis."""
from __future__ import annotations

import json
import sqlite3
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
    # seed filesystem expected by worker
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
        json.dumps({f"q{i}": "a" for i in range(12)})
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
```

- [ ] **Step 2: Run to confirm fail**

Run: `uv run pytest tests/test_persona_worker.py -v`
Expected: 2 failures (`process_run` not exported).

- [ ] **Step 3: Implement worker handler dispatch**

Edit `backend/src/dossier_api/workers/pipeline_worker.py` — append:

```python
def _run_persona_synthesis(run: dict) -> dict:
    """Worker handler for agent=persona_synthesis. Returns output_summary."""
    from dossier_sdk.agents.persona_builder import (
        parse_linkedin_pdf,
        parse_resume,
        synthesize_profile,
    )
    from dossier_api.db import get_account_by_clerk_id  # noqa  # not used directly
    from dossier_api.services import persona_service

    # Resolve slug from accounts.db via user_id → clerk_id round-trip not needed;
    # accounts is keyed by user_id but we want slug. Add helper instead.
    from dossier_api.db import _connect
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

    # Parse first PDF of each kind. Heuristic: files containing "linkedin" go to LinkedIn,
    # everything else treated as resume.
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
    from dossier_api.db import mark_run_completed, mark_run_failed
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
```

Replace the worker `main()` polling loop's no-op section so it calls `process_run(run)` instead of just logging:

```python
def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] [worker] %(message)s")
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
```

- [ ] **Step 4: Run worker tests**

Run: `uv run pytest tests/test_persona_worker.py tests/test_worker.py -v`
Expected: 5 passed (2 new + 3 existing worker pick tests).

---

### Task 8: Frontend deps + persona-schema.ts + api/persona.ts

**Files:**
- Modify: `frontend/package.json` (via pnpm)
- Create: `frontend/lib/persona-schema.ts`
- Create: `frontend/lib/api/persona.ts`

**Concept primer:** zod schemas validate wizard step payloads on the frontend before POST. `lib/api/persona.ts` wraps the 6 endpoints with typed signatures. AI Elements installed via shadcn registry (later in Task 11 only if we use their components — we may instead build the chat UI from scratch in 30 lines).

- [ ] **Step 1: Install deps**

Run:

```bash
cd frontend && pnpm add react-hook-form zod @hookform/resolvers react-dropzone
```

Expected: succeeds. `package.json` updated.

- [ ] **Step 2: Write `lib/persona-schema.ts`**

```typescript
// frontend/lib/persona-schema.ts
// zod schemas for wizard form payloads. Matches FastAPI pydantic models
// in backend/src/dossier_api/models/persona.py.
import { z } from "zod";

export const TargetsSchema = z.object({
  identity: z.object({
    name: z.string().min(1, "Name required"),
    current_role: z.string().min(1, "Current role required"),
    current_company: z.string().optional().default(""),
    months_experience: z.coerce.number().int().min(0).default(0),
    current_ctc_lpa: z.coerce.number().min(0).default(0),
    github_username: z.string().optional().default(""),
  }),
  target: z.object({
    min_salary_lpa: z.coerce.number().int().min(0),
    preferred_salary_lpa: z.coerce.number().int().min(0).optional().default(0),
    roles: z.array(z.string()).min(1, "At least one target role"),
    locations: z.array(z.string()).min(1, "At least one location"),
    company_tiers: z.array(z.string()).default([]),
    hard_nos: z.array(z.string()).default([]),
  }),
  work_preferences: z.object({
    work_style: z.string().default("hybrid"),
    open_to_relocation: z.boolean().default(false),
    relocation_cities: z.array(z.string()).default([]),
  }),
});

export type TargetsForm = z.infer<typeof TargetsSchema>;

export const QuizQuestion = z.object({
  id: z.string(),
  question: z.string(),
  hint: z.string().optional().default(""),
});
export type QuizQuestion = z.infer<typeof QuizQuestion>;
```

- [ ] **Step 3: Write `lib/api/persona.ts`**

```typescript
// frontend/lib/api/persona.ts
// Typed client wrappers for /persona/* and /pipeline/runs/{id}.
"use client";

import { useAuth } from "@clerk/nextjs";
import type { QuizQuestion, TargetsForm } from "../persona-schema";

const BASE = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

type Json = Record<string, unknown>;

export type PersonaState = {
  pdfs_uploaded: boolean;
  questionnaire_done: boolean;
  quiz_done: boolean;
  synthesized: boolean;
};

export type PipelineRun = {
  run_id: string;
  user_id: string;
  agent: string;
  status: "queued" | "running" | "completed" | "failed";
  credits_cost: number;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  output_summary_json: string | null;
};

export function usePersonaApi() {
  const { getToken } = useAuth();

  async function authed(path: string, init?: RequestInit): Promise<Response> {
    const token = await getToken();
    const headers = new Headers(init?.headers);
    if (token) headers.set("Authorization", `Bearer ${token}`);
    return fetch(`${BASE}${path}`, { ...init, headers });
  }

  async function jsonPost(path: string, body: unknown): Promise<Response> {
    return authed(path, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  return {
    getState: async (): Promise<PersonaState> => {
      const r = await authed("/persona/state");
      if (!r.ok) throw new Error(`/persona/state ${r.status}`);
      return r.json();
    },

    uploadPdfs: async (files: { resume?: File; linkedin?: File }): Promise<void> => {
      const fd = new FormData();
      if (files.resume) fd.append("resume", files.resume);
      if (files.linkedin) fd.append("linkedin", files.linkedin);
      const r = await authed("/persona/upload-pdf", { method: "POST", body: fd });
      if (!r.ok) throw new Error(`upload-pdf ${r.status}: ${await r.text()}`);
    },

    saveQuestionnaire: async (data: TargetsForm): Promise<void> => {
      const r = await jsonPost("/persona/questionnaire", data);
      if (!r.ok) throw new Error(`questionnaire ${r.status}`);
    },

    getQuizQuestions: async (): Promise<QuizQuestion[]> => {
      const r = await authed("/persona/quiz-questions");
      if (!r.ok) throw new Error(`quiz-questions ${r.status}`);
      const body = (await r.json()) as { questions: QuizQuestion[] };
      return body.questions;
    },

    saveQuizAnswers: async (answers: Record<string, string>): Promise<void> => {
      const r = await jsonPost("/persona/quiz-answers", { answers });
      if (!r.ok) throw new Error(`quiz-answers ${r.status}`);
    },

    finalize: async (): Promise<{ run_id: string; status: string }> => {
      const r = await jsonPost("/persona/finalize", {});
      if (!r.ok) throw new Error(`finalize ${r.status}: ${await r.text()}`);
      return r.json();
    },

    getPersona: async (): Promise<Json | null> => {
      const r = await authed("/persona");
      if (r.status === 404) return null;
      if (!r.ok) throw new Error(`/persona ${r.status}`);
      return r.json();
    },

    patchPersona: async (patch: Json): Promise<Json> => {
      const r = await authed("/persona", {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ patch }),
      });
      if (!r.ok) throw new Error(`patch ${r.status}`);
      return r.json();
    },

    getRun: async (runId: string): Promise<PipelineRun> => {
      const r = await authed(`/pipeline/runs/${runId}`);
      if (!r.ok) throw new Error(`run ${r.status}`);
      return r.json();
    },
  };
}
```

- [ ] **Step 4: Frontend typecheck**

Run: `cd frontend && pnpm typecheck`
Expected: clean.

### ── COMMIT BATCH 3 (Tasks 7-8) ──

Halt. Suggested commit:

```bash
git add backend/src/dossier_api/workers/pipeline_worker.py \
        backend/tests/test_persona_worker.py \
        frontend/lib/persona-schema.ts frontend/lib/api/persona.ts \
        frontend/package.json frontend/pnpm-lock.yaml
```

```
feat(m3): worker handler + frontend persona-schema + API client

- workers/pipeline_worker.py: dispatch table; persona_synthesis handler
  loads PDFs/questionnaire/quiz, calls SDK synthesize_profile, saves
  profile.json; unknown agents → mark failed
- main loop now calls process_run(run) instead of no-op log
- frontend deps: react-hook-form, zod, @hookform/resolvers, react-dropzone
- lib/persona-schema.ts: zod schemas matching backend pydantic
- lib/api/persona.ts: usePersonaApi() hook with 9 typed wrappers
- 2 new worker tests passing (persona_synthesis + unknown agent)
```

User commits, says "go".

---

### Task 9: Wizard host page + Stepper

**Files:**
- Create: `frontend/app/(app)/onboarding/page.tsx`
- Create: `frontend/components/dossier/wizard/Stepper.tsx`

**Concept primer:** The host page is a client component holding wizard state (current step, accumulated data). Steps are rendered conditionally. URL query `?step=N` keeps refresh-safe.

- [ ] **Step 1: Write Stepper component**

```tsx
// frontend/components/dossier/wizard/Stepper.tsx
"use client";

type Step = { id: string; label: string };

export function Stepper({
  steps,
  current,
}: {
  steps: Step[];
  current: number;
}) {
  return (
    <ol className="flex items-center gap-2 text-sm">
      {steps.map((s, i) => {
        const state = i < current ? "done" : i === current ? "active" : "todo";
        return (
          <li key={s.id} className="flex items-center gap-2">
            <span
              className={
                state === "done"
                  ? "h-7 w-7 rounded-full bg-primary text-[color:var(--color-bg)] grid place-items-center text-xs font-semibold"
                  : state === "active"
                  ? "h-7 w-7 rounded-full bg-[color:var(--color-surface)] border border-primary text-primary grid place-items-center text-xs font-semibold"
                  : "h-7 w-7 rounded-full bg-[color:var(--color-surface)] border border-[color:var(--color-border-2)] text-[color:var(--color-text-subtle)] grid place-items-center text-xs"
              }
            >
              {i + 1}
            </span>
            <span
              className={
                state === "todo"
                  ? "text-[color:var(--color-text-subtle)]"
                  : "text-[color:var(--color-text)]"
              }
            >
              {s.label}
            </span>
            {i < steps.length - 1 && (
              <span
                className={
                  state === "done"
                    ? "w-8 h-px bg-primary mx-1"
                    : "w-8 h-px bg-[color:var(--color-border-2)] mx-1"
                }
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}
```

- [ ] **Step 2: Write wizard host page**

```tsx
// frontend/app/(app)/onboarding/page.tsx
"use client";

import { useState } from "react";
import { Stepper } from "@/components/dossier/wizard/Stepper";

const STEPS = [
  { id: "upload", label: "Upload" },
  { id: "targets", label: "Targets" },
  { id: "quiz", label: "Quiz" },
  { id: "review", label: "Review" },
];

export default function OnboardingPage() {
  const [current, setCurrent] = useState(0);

  return (
    <div className="mx-auto max-w-3xl py-10">
      <h1 className="font-display text-3xl font-extrabold tracking-[-0.035em] text-[color:var(--color-text)]">
        Set up your persona
      </h1>
      <p className="mt-2 text-[color:var(--color-text-muted)]">
        4 quick steps. Takes about 10 minutes. Everything is saved as you go.
      </p>

      <div className="mt-8">
        <Stepper steps={STEPS} current={current} />
      </div>

      <div className="mt-10 rounded-xl border border-[color:var(--color-border-2)]/60 bg-[color:var(--color-surface)] p-8">
        {current === 0 && (
          <div className="text-[color:var(--color-text-muted)]">
            Upload step placeholder — wired in Task 10.
          </div>
        )}
        {current === 1 && (
          <div className="text-[color:var(--color-text-muted)]">
            Targets step placeholder — wired in Task 10.
          </div>
        )}
        {current === 2 && (
          <div className="text-[color:var(--color-text-muted)]">
            Quiz step placeholder — wired in Task 11.
          </div>
        )}
        {current === 3 && (
          <div className="text-[color:var(--color-text-muted)]">
            Review step placeholder — wired in Task 12.
          </div>
        )}
      </div>

      <div className="mt-6 flex justify-between">
        <button
          onClick={() => setCurrent((c) => Math.max(0, c - 1))}
          disabled={current === 0}
          className="rounded-md border border-[color:var(--color-border-2)] px-4 py-2 text-sm text-[color:var(--color-text)] disabled:opacity-40"
        >
          Back
        </button>
        <button
          onClick={() => setCurrent((c) => Math.min(STEPS.length - 1, c + 1))}
          disabled={current === STEPS.length - 1}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-[color:var(--color-bg)] disabled:opacity-40"
        >
          Continue
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Frontend typecheck + dev smoke**

Run: `cd frontend && pnpm typecheck && pnpm build`
Expected: passes; `/onboarding` route registered in build output.

---

### Task 10: UploadStep + TargetsStep

**Files:**
- Create: `frontend/components/dossier/wizard/UploadStep.tsx`
- Create: `frontend/components/dossier/wizard/TargetsStep.tsx`
- Modify: `frontend/app/(app)/onboarding/page.tsx` (replace placeholders)

- [ ] **Step 1: Write UploadStep**

```tsx
// frontend/components/dossier/wizard/UploadStep.tsx
"use client";

import { useState } from "react";
import { useDropzone } from "react-dropzone";
import { usePersonaApi } from "@/lib/api/persona";

export function UploadStep({ onComplete }: { onComplete: () => void }) {
  const api = usePersonaApi();
  const [resume, setResume] = useState<File | null>(null);
  const [linkedin, setLinkedin] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const resumeDrop = useDropzone({
    onDrop: ([f]) => f && setResume(f),
    accept: { "application/pdf": [".pdf"] },
    maxFiles: 1,
  });
  const linkedinDrop = useDropzone({
    onDrop: ([f]) => f && setLinkedin(f),
    accept: { "application/pdf": [".pdf"] },
    maxFiles: 1,
  });

  async function submit() {
    if (!resume && !linkedin) {
      setError("Upload at least one PDF");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.uploadPdfs({ resume: resume ?? undefined, linkedin: linkedin ?? undefined });
      onComplete();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="font-display text-xl font-semibold text-[color:var(--color-text)]">
          Upload your resume + LinkedIn export
        </h2>
        <p className="mt-1 text-sm text-[color:var(--color-text-muted)]">
          PDFs only. We parse text out and never share these files.
        </p>
      </div>

      <DropZone
        label="Resume PDF (required)"
        file={resume}
        {...resumeDrop}
      />
      <DropZone
        label="LinkedIn export PDF (optional but recommended)"
        file={linkedin}
        {...linkedinDrop}
      />

      {error && <p className="text-sm text-[color:var(--color-danger)]">{error}</p>}

      <button
        onClick={submit}
        disabled={busy || (!resume && !linkedin)}
        className="w-full rounded-md bg-primary px-4 py-2.5 text-sm font-medium text-[color:var(--color-bg)] disabled:opacity-40"
      >
        {busy ? "Uploading..." : "Upload & continue"}
      </button>
    </div>
  );
}

type DropProps = {
  label: string;
  file: File | null;
  getRootProps: ReturnType<typeof useDropzone>["getRootProps"];
  getInputProps: ReturnType<typeof useDropzone>["getInputProps"];
  isDragActive: boolean;
};

function DropZone({ label, file, getRootProps, getInputProps, isDragActive }: DropProps) {
  return (
    <div>
      <label className="block text-sm text-[color:var(--color-text)] mb-1.5">{label}</label>
      <div
        {...getRootProps()}
        className={`rounded-lg border-2 border-dashed p-6 text-center cursor-pointer transition ${
          isDragActive
            ? "border-primary bg-[color:var(--color-surface-2)]"
            : "border-[color:var(--color-border-2)] hover:border-primary/60"
        }`}
      >
        <input {...getInputProps()} />
        {file ? (
          <div className="text-sm text-[color:var(--color-text)]">
            <span className="text-primary">✓</span> {file.name} ({(file.size / 1024).toFixed(0)} KB)
          </div>
        ) : (
          <div className="text-sm text-[color:var(--color-text-muted)]">
            Drop a PDF here, or click to browse
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Write TargetsStep**

```tsx
// frontend/components/dossier/wizard/TargetsStep.tsx
"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { TargetsSchema, type TargetsForm } from "@/lib/persona-schema";
import { usePersonaApi } from "@/lib/api/persona";
import { useState } from "react";

export function TargetsStep({
  onComplete,
}: {
  onComplete: () => void;
}) {
  const api = usePersonaApi();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<TargetsForm>({
    resolver: zodResolver(TargetsSchema),
    defaultValues: {
      identity: { name: "", current_role: "", current_company: "", months_experience: 0, current_ctc_lpa: 0, github_username: "" },
      target: { min_salary_lpa: 25, preferred_salary_lpa: 30, roles: [], locations: [], company_tiers: [], hard_nos: [] },
      work_preferences: { work_style: "hybrid", open_to_relocation: false, relocation_cities: [] },
    },
  });

  async function onSubmit(data: TargetsForm) {
    setBusy(true); setError(null);
    try {
      await api.saveQuestionnaire(data);
      onComplete();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
      <div>
        <h2 className="font-display text-xl font-semibold text-[color:var(--color-text)]">Job targets</h2>
        <p className="mt-1 text-sm text-[color:var(--color-text-muted)]">
          Tell us what you're looking for. We use this for every job match.
        </p>
      </div>

      <Field label="Your name" error={errors.identity?.name?.message}>
        <input {...register("identity.name")} className={inputCls} />
      </Field>

      <Field label="Current role" error={errors.identity?.current_role?.message}>
        <input {...register("identity.current_role")} placeholder="AI Engineer" className={inputCls} />
      </Field>

      <Field label="Current company">
        <input {...register("identity.current_company")} className={inputCls} />
      </Field>

      <div className="grid grid-cols-2 gap-4">
        <Field label="Months of experience">
          <input type="number" {...register("identity.months_experience")} className={inputCls} />
        </Field>
        <Field label="Current CTC (LPA)">
          <input type="number" step="0.5" {...register("identity.current_ctc_lpa")} className={inputCls} />
        </Field>
      </div>

      <Field label="GitHub username (optional)">
        <input {...register("identity.github_username")} className={inputCls} />
      </Field>

      <div className="grid grid-cols-2 gap-4">
        <Field label="Min salary (LPA)" error={errors.target?.min_salary_lpa?.message}>
          <input type="number" {...register("target.min_salary_lpa")} className={inputCls} />
        </Field>
        <Field label="Preferred salary (LPA)">
          <input type="number" {...register("target.preferred_salary_lpa")} className={inputCls} />
        </Field>
      </div>

      <Field label="Target roles (comma-separated)" error={errors.target?.roles?.message}>
        <input
          {...register("target.roles", {
            setValueAs: (v: string) => (typeof v === "string" ? v.split(",").map(s => s.trim()).filter(Boolean) : v),
          })}
          placeholder="MLE-1, AI Engineer, Applied Scientist"
          className={inputCls}
        />
      </Field>

      <Field label="Locations (comma-separated)" error={errors.target?.locations?.message}>
        <input
          {...register("target.locations", {
            setValueAs: (v: string) => (typeof v === "string" ? v.split(",").map(s => s.trim()).filter(Boolean) : v),
          })}
          placeholder="Bengaluru, Remote"
          className={inputCls}
        />
      </Field>

      <Field label="Hard nos (comma-separated)">
        <input
          {...register("target.hard_nos", {
            setValueAs: (v: string) => (typeof v === "string" ? v.split(",").map(s => s.trim()).filter(Boolean) : v),
          })}
          placeholder="service_company, no_ml_in_prod"
          className={inputCls}
        />
      </Field>

      <Field label="Work style">
        <select {...register("work_preferences.work_style")} className={inputCls}>
          <option value="hybrid">Hybrid</option>
          <option value="remote">Remote-only</option>
          <option value="onsite">On-site</option>
        </select>
      </Field>

      <label className="flex items-center gap-2 text-sm text-[color:var(--color-text)]">
        <input type="checkbox" {...register("work_preferences.open_to_relocation")} />
        Open to relocation
      </label>

      {error && <p className="text-sm text-[color:var(--color-danger)]">{error}</p>}

      <button
        type="submit"
        disabled={busy}
        className="w-full rounded-md bg-primary px-4 py-2.5 text-sm font-medium text-[color:var(--color-bg)] disabled:opacity-40"
      >
        {busy ? "Saving..." : "Save & continue"}
      </button>
    </form>
  );
}

const inputCls = "w-full rounded-md border border-[color:var(--color-border-2)] bg-[color:var(--color-surface-2)] px-3 py-2 text-sm text-[color:var(--color-text)] focus:border-primary focus:outline-none";

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-sm text-[color:var(--color-text)] mb-1.5">{label}</label>
      {children}
      {error && <p className="mt-1 text-xs text-[color:var(--color-danger)]">{error}</p>}
    </div>
  );
}
```

- [ ] **Step 3: Wire steps into wizard page**

Replace `frontend/app/(app)/onboarding/page.tsx` body — replace the placeholder block with:

```tsx
{current === 0 && <UploadStep onComplete={() => setCurrent(1)} />}
{current === 1 && <TargetsStep onComplete={() => setCurrent(2)} />}
{current === 2 && (
  <div className="text-[color:var(--color-text-muted)]">Quiz step placeholder — wired in Task 11.</div>
)}
{current === 3 && (
  <div className="text-[color:var(--color-text-muted)]">Review step placeholder — wired in Task 12.</div>
)}
```

Add imports at top:

```tsx
import { UploadStep } from "@/components/dossier/wizard/UploadStep";
import { TargetsStep } from "@/components/dossier/wizard/TargetsStep";
```

Remove the bottom "Continue" + "Back" buttons since each step now handles its own advancement. Keep "Back":

```tsx
<div className="mt-6 flex justify-between">
  <button
    onClick={() => setCurrent((c) => Math.max(0, c - 1))}
    disabled={current === 0}
    className="rounded-md border border-[color:var(--color-border-2)] px-4 py-2 text-sm text-[color:var(--color-text)] disabled:opacity-40"
  >
    Back
  </button>
</div>
```

- [ ] **Step 4: Frontend typecheck + build**

Run: `pnpm typecheck && pnpm build`
Expected: clean.

---

### Task 11: QuizStep

**Files:**
- Create: `frontend/components/dossier/wizard/QuizStep.tsx`
- Modify: `frontend/app/(app)/onboarding/page.tsx`

**Concept primer:** Chat-style UI but no LLM. Render messages from a local array. Bot bubble = question, user bubble = answer. Press Enter to submit, advance to next question. At question 12, POST all answers + advance to step 3.

- [ ] **Step 1: Write QuizStep**

```tsx
// frontend/components/dossier/wizard/QuizStep.tsx
"use client";

import { useEffect, useRef, useState } from "react";
import { usePersonaApi } from "@/lib/api/persona";
import type { QuizQuestion } from "@/lib/persona-schema";

type Msg = { role: "bot" | "user"; text: string; hint?: string };

export function QuizStep({ onComplete }: { onComplete: () => void }) {
  const api = usePersonaApi();
  const [questions, setQuestions] = useState<QuizQuestion[]>([]);
  const [idx, setIdx] = useState(0);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    api.getQuizQuestions().then((qs) => {
      setQuestions(qs);
      if (qs[0]) {
        setMsgs([{ role: "bot", text: qs[0].question, hint: qs[0].hint }]);
      }
    }).catch((e) => setError((e as Error).message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function submitAnswer() {
    if (!input.trim()) return;
    const answer = input.trim();
    const answeredQuestion = questions[idx];
    setInput("");
    setMsgs((m) => [...m, { role: "user", text: answer }]);

    const nextIdx = idx + 1;
    if (nextIdx >= questions.length) {
      // All answered — POST and advance
      const allAnswers: Record<string, string> = {};
      const userBubbles = [...msgs, { role: "user", text: answer }].filter(m => m.role === "user") as Msg[];
      userBubbles.forEach((m, i) => {
        if (questions[i]) allAnswers[questions[i].id] = m.text;
      });
      setBusy(true);
      try {
        await api.saveQuizAnswers(allAnswers);
        onComplete();
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setBusy(false);
      }
      return;
    }

    setIdx(nextIdx);
    setMsgs((m) => [...m, { role: "bot", text: questions[nextIdx].question, hint: questions[nextIdx].hint }]);
    setTimeout(() => inputRef.current?.focus(), 0);
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="font-display text-xl font-semibold text-[color:var(--color-text)]">
          Quick interview — {questions.length ? `question ${Math.min(idx + 1, questions.length)} of ${questions.length}` : "loading..."}
        </h2>
        <p className="mt-1 text-sm text-[color:var(--color-text-muted)]">
          Be specific. Specific answers produce better job matches.
        </p>
      </div>

      <div className="max-h-[50vh] overflow-y-auto space-y-3 pr-2">
        {msgs.map((m, i) => (
          <div
            key={i}
            className={
              m.role === "bot"
                ? "max-w-[85%] rounded-2xl rounded-tl-sm bg-[color:var(--color-surface-2)] border border-[color:var(--color-border-2)] px-4 py-3 text-sm text-[color:var(--color-text)] whitespace-pre-wrap"
                : "ml-auto max-w-[85%] rounded-2xl rounded-tr-sm bg-primary/15 border border-primary/30 px-4 py-3 text-sm text-[color:var(--color-text)] whitespace-pre-wrap"
            }
          >
            {m.text}
            {m.role === "bot" && m.hint && (
              <div className="mt-2 text-xs text-[color:var(--color-text-subtle)] whitespace-pre-wrap">
                {m.hint}
              </div>
            )}
          </div>
        ))}
      </div>

      {error && <p className="text-sm text-[color:var(--color-danger)]">{error}</p>}

      {idx < questions.length && (
        <div className="space-y-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                submitAnswer();
              }
            }}
            rows={3}
            placeholder="Type your answer... (Cmd/Ctrl + Enter to send)"
            className="w-full resize-y rounded-md border border-[color:var(--color-border-2)] bg-[color:var(--color-surface-2)] px-3 py-2 text-sm text-[color:var(--color-text)] focus:border-primary focus:outline-none"
          />
          <button
            onClick={submitAnswer}
            disabled={busy || !input.trim()}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-[color:var(--color-bg)] disabled:opacity-40"
          >
            {idx === questions.length - 1 ? (busy ? "Saving..." : "Send & finish") : "Send"}
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Wire into wizard**

Edit `onboarding/page.tsx`: import `QuizStep`, replace the step 2 placeholder:

```tsx
{current === 2 && <QuizStep onComplete={() => setCurrent(3)} />}
```

- [ ] **Step 3: Typecheck + build**

Run: `pnpm typecheck && pnpm build`
Expected: clean.

### ── COMMIT BATCH 4 (Tasks 9-11) ──

Halt. Suggested commit:

```bash
git add frontend/components/dossier/wizard/ \
        frontend/app/\(app\)/onboarding/page.tsx
```

```
feat(m3): wizard host + Stepper + Upload/Targets/Quiz steps

- (app)/onboarding/page.tsx hosts wizard state (current step), routes to
  one of four step components
- Stepper.tsx: linear progress indicator (done/active/todo states)
- UploadStep.tsx: react-dropzone for resume + linkedin PDFs, multipart
  POST to /persona/upload-pdf, 10MB enforced server-side
- TargetsStep.tsx: react-hook-form + zod-validated targets/identity form,
  posts to /persona/questionnaire
- QuizStep.tsx: chat-style UI walks through 12 hardcoded INTERVIEW_QUESTIONS;
  Cmd/Ctrl+Enter to send; final answer POSTs all to /persona/quiz-answers
```

User commits.

---

### Task 12: ReviewStep + SynthesisProgress

**Files:**
- Create: `frontend/components/dossier/wizard/ReviewStep.tsx`
- Create: `frontend/components/dossier/wizard/SynthesisProgress.tsx`
- Modify: `frontend/app/(app)/onboarding/page.tsx`

**Concept primer:** Review step kicks off `POST /persona/finalize`, gets `run_id`, polls `/pipeline/runs/{id}` every 2s. While running → SynthesisProgress component (spinner + "30-60s remaining"). On completion → fetch persona, show editable JSON-ish form. Confirm click → no extra call (PATCH already saved any edits) → `router.push("/dashboard")`.

- [ ] **Step 1: SynthesisProgress component**

```tsx
// frontend/components/dossier/wizard/SynthesisProgress.tsx
"use client";

import { useEffect, useState } from "react";
import { usePersonaApi, type PipelineRun } from "@/lib/api/persona";

export function SynthesisProgress({
  runId,
  onComplete,
  onFailed,
}: {
  runId: string;
  onComplete: () => void;
  onFailed: (msg: string) => void;
}) {
  const api = usePersonaApi();
  const [run, setRun] = useState<PipelineRun | null>(null);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const start = Date.now();

    async function tick() {
      try {
        const r = await api.getRun(runId);
        if (cancelled) return;
        setRun(r);
        setElapsed(Math.floor((Date.now() - start) / 1000));
        if (r.status === "completed") {
          onComplete();
          return;
        }
        if (r.status === "failed") {
          onFailed(r.error || "synthesis failed");
          return;
        }
        setTimeout(tick, 2000);
      } catch (e) {
        if (!cancelled) onFailed((e as Error).message);
      }
    }
    tick();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  return (
    <div className="space-y-4 text-center py-10">
      <div className="mx-auto h-12 w-12 animate-spin rounded-full border-4 border-[color:var(--color-border-2)] border-t-primary" />
      <h2 className="font-display text-xl text-[color:var(--color-text)]">
        Synthesizing your persona
      </h2>
      <p className="text-sm text-[color:var(--color-text-muted)]">
        {run?.status === "queued" && "Queued — worker will pick this up shortly..."}
        {run?.status === "running" && `Running — typically takes 30-60 seconds. (${elapsed}s elapsed)`}
      </p>
    </div>
  );
}
```

- [ ] **Step 2: ReviewStep**

```tsx
// frontend/components/dossier/wizard/ReviewStep.tsx
"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { usePersonaApi } from "@/lib/api/persona";
import { SynthesisProgress } from "./SynthesisProgress";

type Mode = "kicking-off" | "synthesizing" | "review" | "saving" | "error";

export function ReviewStep() {
  const api = usePersonaApi();
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("kicking-off");
  const [runId, setRunId] = useState<string | null>(null);
  const [persona, setPersona] = useState<Record<string, unknown> | null>(null);
  const [edited, setEdited] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.finalize().then((r) => {
      setRunId(r.run_id);
      setMode("synthesizing");
    }).catch((e) => {
      setError((e as Error).message);
      setMode("error");
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadPersona() {
    const p = await api.getPersona();
    if (p) {
      setPersona(p);
      setEdited(JSON.stringify(p, null, 2));
    }
    setMode("review");
  }

  async function saveEdits() {
    setMode("saving");
    try {
      const parsed = JSON.parse(edited);
      // PATCH applies the whole edited object as the patch
      await api.patchPersona(parsed);
      router.push("/dashboard");
    } catch (e) {
      setError((e as Error).message);
      setMode("review");
    }
  }

  if (mode === "kicking-off") {
    return <p className="text-[color:var(--color-text-muted)]">Starting synthesis...</p>;
  }

  if (mode === "synthesizing" && runId) {
    return (
      <SynthesisProgress
        runId={runId}
        onComplete={loadPersona}
        onFailed={(msg) => {
          setError(msg);
          setMode("error");
        }}
      />
    );
  }

  if (mode === "error") {
    return (
      <div className="space-y-3">
        <h2 className="font-display text-xl text-[color:var(--color-danger)]">Synthesis failed</h2>
        <p className="text-sm text-[color:var(--color-text-muted)]">{error}</p>
        <button
          onClick={() => window.location.reload()}
          className="rounded-md border border-[color:var(--color-border-2)] px-4 py-2 text-sm text-[color:var(--color-text)]"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="font-display text-xl font-semibold text-[color:var(--color-text)]">
          Review your persona
        </h2>
        <p className="mt-1 text-sm text-[color:var(--color-text-muted)]">
          Edit any field directly in the JSON below. Click "Looks good" to save and start matching jobs.
        </p>
      </div>

      <textarea
        value={edited}
        onChange={(e) => setEdited(e.target.value)}
        rows={20}
        className="w-full rounded-md border border-[color:var(--color-border-2)] bg-[color:var(--color-surface-2)] px-3 py-2 font-mono text-xs text-[color:var(--color-text)] focus:border-primary focus:outline-none"
        style={{ fontFamily: "var(--font-geist-mono)" }}
      />

      {error && <p className="text-sm text-[color:var(--color-danger)]">{error}</p>}

      <button
        onClick={saveEdits}
        disabled={mode === "saving"}
        className="w-full rounded-md bg-primary px-4 py-2.5 text-sm font-medium text-[color:var(--color-bg)] disabled:opacity-40"
      >
        {mode === "saving" ? "Saving..." : "Looks good — start matching jobs"}
      </button>
    </div>
  );
}
```

- [ ] **Step 3: Wire into wizard**

In `onboarding/page.tsx`:

```tsx
import { ReviewStep } from "@/components/dossier/wizard/ReviewStep";
// ...
{current === 3 && <ReviewStep />}
```

- [ ] **Step 4: Typecheck + build**

Run: `pnpm typecheck && pnpm build`
Expected: clean.

---

### Task 13: Onboarding gate + Sidebar hide on onboarding + acceptance smoke

**Files:**
- Modify: `frontend/app/(app)/layout.tsx` — onboarding redirect
- Modify: `frontend-todo.txt`

- [ ] **Step 1: Add onboarding gate to layout**

Edit `frontend/app/(app)/layout.tsx`:

Above the `const account = me.account;` line, add a no-onboarding gate. We do it server-side via a second backend call:

```tsx
import { headers } from "next/headers";
// at top imports — already in place: auth, redirect, fetchMe

// Inside AppLayout, after we confirmed account.status === "active":
async function isOnboarded(): Promise<boolean> {
  const { auth } = await import("@clerk/nextjs/server");
  const { getToken } = await auth();
  const token = await getToken();
  if (!token) return true; // can't check; assume true to avoid loop
  const base = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
  const res = await fetch(`${base}/persona/state`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) return true;
  const state = await res.json() as { synthesized: boolean };
  return state.synthesized;
}
```

This adds complexity to layout.tsx. Cleaner: extract that to `frontend/lib/server-api.ts`:

```typescript
// append to frontend/lib/server-api.ts
export async function fetchPersonaState(): Promise<{ synthesized: boolean } | null> {
  let res: Response;
  try {
    res = await authedFetch("/persona/state");
  } catch {
    return null;
  }
  if (!res.ok) return null;
  return res.json();
}
```

Wait — `authedFetch` in `server-api.ts` is currently file-private. Refactor to export it OR just inline the call. Easier: inline.

Replace the active-account branch in `layout.tsx` to redirect onboarding-incomplete users:

```tsx
import { redirect } from "next/navigation";
// existing imports stay
import { fetchPersonaState } from "@/lib/server-api";

// existing: after account.status === "active" check
const personaState = await fetchPersonaState();
const isOnboardingPath = (await headers()).get("x-pathname")?.startsWith("/onboarding");
// Next.js doesn't expose pathname in RSC headers by default — read from a different source.
```

Actually pathname in RSC needs a custom header set via middleware. Simpler approach: skip the redirect ON the onboarding route by giving onboarding its own layout that bypasses the gate. Cleanest:

**Move the onboarding redirect logic to a small Server Component wrapper, and exclude `/onboarding` from triggering its own redirect by checking inside the wrapper.**

Final simple approach — add to `(app)/layout.tsx`:

```tsx
import { redirect } from "next/navigation";
import { fetchMe, fetchPersonaState } from "@/lib/server-api";
// ... existing imports

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const { userId } = await auth();
  if (!userId) redirect("/sign-in");
  const me = await fetchMe();
  // ... existing no-account / error / pending / suspended branches unchanged ...

  // Active user — check onboarding state. If not synthesized AND not currently on
  // /onboarding, redirect to /onboarding. Pathname check needs middleware exposure.
  const state = await fetchPersonaState();
  if (state && !state.synthesized && !(await isOnOnboardingPath())) {
    redirect("/onboarding");
  }
  // ... existing active rendering ...
}

async function isOnOnboardingPath(): Promise<boolean> {
  const { headers } = await import("next/headers");
  return ((await headers()).get("x-pathname") ?? "").startsWith("/onboarding");
}
```

Add middleware header pass-through. Edit `frontend/middleware.ts` — inside `clerkMiddleware` callback, set the header BEFORE returning:

```typescript
import { NextResponse } from "next/server";
import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

const isProtectedRoute = createRouteMatcher([
  "/dashboard(.*)",
  "/onboarding(.*)",
  "/jobs(.*)",
  "/watchlist(.*)",
  "/gaps(.*)",
  "/referrals(.*)",
  "/resume(.*)",
  "/market(.*)",
  "/settings(.*)",
  "/admin(.*)",
]);

export default clerkMiddleware(async (auth, req) => {
  if (isProtectedRoute(req)) {
    await auth.protect();
  }
  const res = NextResponse.next();
  res.headers.set("x-pathname", req.nextUrl.pathname);
  return res;
});

export const config = {
  matcher: [
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
```

Also append the helper to `lib/server-api.ts`:

```typescript
export async function fetchPersonaState(): Promise<{ synthesized: boolean } | null> {
  let res: Response;
  try {
    res = await authedFetch("/persona/state");
  } catch {
    return null;
  }
  if (!res.ok) return null;
  return res.json();
}
```

Move `authedFetch` to internal scope (currently is — no change needed).

- [ ] **Step 2: Run all backend tests + frontend typecheck/build**

Run:
```bash
cd backend && uv run pytest -v
cd ../frontend && pnpm typecheck && pnpm test --run && pnpm build
```
Expected: all green.

- [ ] **Step 3: End-to-end smoke (manual)**

Restart uvicorn + worker:
```bash
cd backend && uv run uvicorn dossier_api.main:app --reload --port 8000 &
uv run python -m dossier_api.workers.pipeline_worker &
```

Restart frontend:
```bash
cd frontend && pnpm dev
```

Sign in as the seeded shivang account (which already has a profile.json → won't redirect). Then sign in as the pending test user → admin approves (or for testing just promote the row directly: `sqlite3 data/accounts.db "UPDATE accounts SET status='active' WHERE email='ssnfs93@gmail.com';"`).

Refresh `/dashboard` → should auto-redirect to `/onboarding`. Walk through:
- Step 1: drop a sample PDF
- Step 2: fill targets form
- Step 3: answer 12 quiz prompts
- Step 4: see synthesis spinner ~30s → review JSON → save → land on `/dashboard`

Verify file written: `cat profile/user_3DudOQx3rPCF0AK1pjzuGbxQwvm/profile.json | jq .identity`

- [ ] **Step 4: Tick `frontend-todo.txt` M3 block**

Edit `frontend-todo.txt`, replace M3 stub block with:

```
## M3 — Persona builder wizard  (DONE 2026-05-19)
[x] T1  Backend persona router skeleton + GET /persona
[x] T2  POST /persona/upload-pdf (multipart, 10MB cap)
[x] T3  POST /persona/questionnaire + GET /persona/state
[x] T4  GET /persona/quiz-questions + POST /persona/quiz-answers
[x] T5  POST /persona/finalize + db helpers + GET /pipeline/runs/{id}
[x] T6  PATCH /persona
[x] T7  Worker dispatch table + persona_synthesis handler
[x] T8  Frontend deps + persona-schema.ts (zod) + lib/api/persona.ts
[x] T9  Wizard host + Stepper
[x] T10 UploadStep + TargetsStep (react-dropzone + react-hook-form)
[x] T11 QuizStep (chat UI, 12 hardcoded questions)
[x] T12 ReviewStep + SynthesisProgress (poll /pipeline/runs/{id})
[x] T13 Onboarding gate + middleware x-pathname + acceptance smoke

Plan: docs/superpowers/plans/2026-05-19-m3-persona-wizard.md
```

### ── COMMIT BATCH 5 (Tasks 12-13) ──

Halt. Suggested commit:

```bash
git add frontend/components/dossier/wizard/ReviewStep.tsx \
        frontend/components/dossier/wizard/SynthesisProgress.tsx \
        frontend/app/\(app\)/onboarding/page.tsx \
        frontend/app/\(app\)/layout.tsx \
        frontend/lib/server-api.ts \
        frontend/middleware.ts \
        frontend-todo.txt
```

```
feat(m3): ReviewStep + SynthesisProgress + onboarding gate

- ReviewStep.tsx: POSTs /persona/finalize → polls /pipeline/runs/{id} via
  SynthesisProgress → on completion loads /persona → JSON-editor textarea →
  PATCH /persona → router.push("/dashboard")
- SynthesisProgress.tsx: 2s polling with spinner, elapsed counter
- middleware.ts: sets x-pathname header so layout.tsx can detect /onboarding
- (app)/layout.tsx: redirects active users without synthesized profile to
  /onboarding (skip when already on /onboarding)
- frontend-todo.txt: M3 ticked done

Acceptance test:
- 27 backend tests pass (was 19; +8 M3)
- frontend: typecheck, 8 vitest, pnpm build all green
- Fresh signup → admin approves → /dashboard → auto-redirect /onboarding →
  4 steps → ~30s synthesis → profile.json written → /dashboard with synthesized
  persona
```

---

## Out-of-scope (do NOT add in M3)

- Resume/re-onboarding flow (M5+)
- Voice/tone file upload (already handled by SDK when present, just not in wizard)
- SSE for synthesis progress (polling is fine for M3; SSE in M4 for pipeline runs)
- Worker concurrency / multiple users at once (sequential is fine)
- Profile editing in /settings (deferred)

---

## Self-review checklist

**Spec coverage (§9 endpoints, §10 routes, §15 M3 acceptance):**
- §9 `/persona/upload-pdf` ✓ T2
- §9 `/persona/questionnaire` ✓ T3
- §9 `/persona/quiz-message` — replaced with `/persona/quiz-questions` GET + `/persona/quiz-answers` POST per locked decision ✓ T4
- §9 `GET /persona` ✓ T1
- §9 `PATCH /persona` ✓ T6
- §9 `POST /persona/finalize` ✓ T5
- §9 `GET /pipeline/runs/{id}` ✓ T5 (needed for synthesis polling)
- §10 `/onboarding` route ✓ T9-T12
- §15 acceptance: fresh signup → wizard → profile.json → dashboard ✓ T13 smoke

**Placeholder scan:** none.

**Type consistency:** `TargetsForm` zod ↔ `QuestionnairePayload` pydantic both have `identity`, `target`, `work_preferences` top-level keys. ✓ `PipelineRun` TS type matches `pipeline_runs` SQLite columns. ✓ Quiz answer `id` (zod `QuizQuestion.id`) matches SDK `INTERVIEW_QUESTIONS[i]["id"]`. ✓

**Commit cadence:** 5 batches across 13 tasks (3/3/2/3/2). Documented inline.
