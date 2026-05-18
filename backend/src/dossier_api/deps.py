"""Auth + tier dependencies.

`get_current_user` — verifies Clerk JWT, loads accounts.db row, returns it.
401 if no/invalid JWT. 403 if no matching account row or status != 'active'.

Background:
    Clerk publishes a JWKS at <issuer>/.well-known/jwks.json.
    clerk-backend-api caches the keys and verifies signature + expiry locally
    on every request (no roundtrip to Clerk per call).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, HTTPException, Request, status

from dossier_api.db import get_account_by_clerk_id, update_last_login
from dossier_api.settings import get_settings

logger = logging.getLogger(__name__)


def _extract_bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return None
    return auth.split(" ", 1)[1].strip()


def _verify_clerk_jwt(token: str) -> str:
    """Return Clerk user_id (sub claim) if valid; raise HTTPException(401) otherwise.

    Uses clerk-backend-api 5.x: security.verifytoken.verify_token(token, options).
    Patched in tests so unit tests do not need real Clerk infra.
    """
    try:
        from clerk_backend_api.security.types import VerifyTokenOptions
        from clerk_backend_api.security.verifytoken import verify_token

        payload = verify_token(
            token,
            VerifyTokenOptions(secret_key=get_settings().clerk_secret_key),
        )
        sub = payload.get("sub")
        if not sub:
            raise ValueError("missing sub claim")
        return sub
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("clerk jwt verify failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired Clerk session",
        ) from exc


def get_current_clerk_id(request: Request) -> str:
    """Return verified clerk_id from JWT, or 401."""
    token = _extract_bearer(request)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )
    return _verify_clerk_jwt(token)


def get_current_user(
    clerk_id: str = Depends(get_current_clerk_id),
) -> dict[str, Any]:
    """Verified Clerk JWT → accounts.db row. 403 if no account or suspended."""
    acct = get_account_by_clerk_id(clerk_id)
    if acct is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No matching account. Wait for the webhook to provision your row.",
        )
    if acct["status"] == "suspended":
        raise HTTPException(status_code=403, detail="Account suspended")
    update_last_login(clerk_id)
    return acct


def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user
