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
