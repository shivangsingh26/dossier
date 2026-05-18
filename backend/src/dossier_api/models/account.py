"""Pydantic schemas for account-related API responses."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Tier = Literal["lite", "pro", "max"]
Role = Literal["user", "admin"]
Status = Literal["pending", "active", "suspended"]


class AccountResponse(BaseModel):
    """Returned by GET /me."""
    model_config = ConfigDict(populate_by_name=True)

    user_id: str
    clerk_id: str
    email: str
    data_user_slug: str
    role: Role
    tier: Tier
    status: Status
    credits: int
    credits_reset_at: datetime
    created_at: datetime
    last_login_at: datetime | None = None


class CreditDebit(BaseModel):
    delta: int = Field(..., description="Negative for deduction, positive for refund/topup")
    reason: str
    run_id: str | None = None
