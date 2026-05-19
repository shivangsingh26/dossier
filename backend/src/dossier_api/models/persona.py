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
