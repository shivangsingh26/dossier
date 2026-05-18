"""GET /me — current account."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from dossier_api.deps import get_current_user
from dossier_api.models.account import AccountResponse

router = APIRouter()


@router.get("/me", response_model=AccountResponse)
async def me(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Return the current user's account row."""
    return user
