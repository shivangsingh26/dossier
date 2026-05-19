"""All /persona/* endpoints. Auth-gated; uses persona_service for I/O."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from dossier_api.deps import get_current_user
from dossier_api.models.persona import QuestionnairePayload
from dossier_api.services import persona_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/persona")


@router.get("")
async def get_persona(user: dict[str, Any] = Depends(get_current_user)):
    profile = persona_service.load_profile_json(user["data_user_slug"])
    if profile is None:
        raise HTTPException(status_code=404, detail="profile.json not yet synthesized")
    return profile


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
