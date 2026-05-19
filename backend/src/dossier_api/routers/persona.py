"""All /persona/* endpoints. Auth-gated; uses persona_service for I/O."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from dossier_api.db import enqueue_pipeline_run
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


@router.post("/questionnaire")
async def post_questionnaire(
    payload: QuestionnairePayload,
    user: dict[str, Any] = Depends(get_current_user),
):
    persona_service.save_questionnaire(user["data_user_slug"], payload.model_dump())
    return {"status": "saved"}


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
