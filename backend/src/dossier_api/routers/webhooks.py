"""POST /webhooks/clerk — provision accounts on Clerk events.

Why this endpoint exists:
    Clerk owns auth. We never store passwords. The single point where Clerk's
    state becomes ours is this webhook — fired on user.created, user.updated,
    user.deleted. Each event delivers the canonical Clerk user record; we
    mirror just the fields we need into accounts.db.

Security:
    Every request signed by Svix HMAC. We verify before parsing the body.
    A leaked webhook URL without the signing secret is useless.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from dossier_api.db import (
    create_account,
    get_account_by_clerk_id,
    update_account_status,
)
from dossier_api.settings import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()


def _verify_webhook(raw_body: bytes, headers: dict[str, str]) -> dict[str, Any]:
    """Verify Svix signature and return parsed payload. Raises HTTPException(400) on fail.

    Replaced in tests via patch.
    """
    try:
        from svix.webhooks import Webhook
    except Exception as exc:
        logger.error("svix import failed: %s", exc)
        raise HTTPException(status_code=500, detail="webhook lib missing") from exc

    secret = get_settings().clerk_webhook_secret
    try:
        wh = Webhook(secret)
        payload = wh.verify(raw_body, headers)
        return payload if isinstance(payload, dict) else json.loads(raw_body)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("webhook verify failed: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid webhook signature") from exc


def _primary_email(data: dict[str, Any]) -> str | None:
    primary_id = data.get("primary_email_address_id")
    for addr in data.get("email_addresses", []):
        if addr.get("id") == primary_id:
            return addr.get("email_address")
    if data.get("email_addresses"):
        return data["email_addresses"][0].get("email_address")
    return None


@router.post("/webhooks/clerk")
async def clerk_webhook(request: Request) -> dict[str, str]:
    raw = await request.body()
    headers = {
        "svix-id":        request.headers.get("svix-id", ""),
        "svix-timestamp": request.headers.get("svix-timestamp", ""),
        "svix-signature": request.headers.get("svix-signature", ""),
    }
    payload = _verify_webhook(raw, headers)
    event_type = payload.get("type") or ""
    data = payload.get("data") or {}

    if event_type == "user.created":
        clerk_id = data.get("id")
        email = _primary_email(data)
        if not clerk_id or not email:
            logger.warning("user.created missing id/email: %s", payload)
            return {"status": "ignored"}
        if get_account_by_clerk_id(clerk_id) is not None:
            return {"status": "exists"}
        create_account(clerk_id=clerk_id, email=email, data_user_slug=clerk_id)
        logger.info("provisioned pending account clerk_id=%s email=%s", clerk_id, email)
        return {"status": "created"}

    if event_type == "user.deleted":
        clerk_id = data.get("id")
        if clerk_id and get_account_by_clerk_id(clerk_id) is not None:
            update_account_status(clerk_id, "suspended")
        return {"status": "soft-deleted"}

    return {"status": "ignored"}
