"""Seed the 4 existing users into Clerk + accounts.db.

Idempotent: re-running skips users already in accounts.db.

Run: cd backend && uv run python -m scripts.seed_existing_users
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

# Allow running as `python -m scripts.seed_existing_users` from backend/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dossier_api.db import (  # noqa: E402
    create_account,
    get_account_by_clerk_id,
    get_account_by_email,
    init_db,
)
from dossier_api.settings import get_settings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SEED_FILE = Path(__file__).parent / "seed_users.json"


def _clerk():
    from clerk_backend_api import Clerk
    return Clerk(bearer_auth=get_settings().clerk_secret_key)


def _find_or_create_clerk_user(email: str, role: str, tier: str) -> str:
    """Return Clerk user_id. Creates the user if missing."""
    from clerk_backend_api.models import GetUserListRequest

    clerk = _clerk()
    try:
        users = clerk.users.list(request=GetUserListRequest(email_address=[email])) or []
    except Exception as exc:
        logger.warning("clerk list users failed for %s: %s", email, exc)
        users = []

    if users:
        clerk_id = users[0].id
        logger.info("clerk user already exists for %s: %s", email, clerk_id)
    else:
        created = clerk.users.create(
            email_address=[email],
            skip_password_requirement=True,
            public_metadata={"role": role, "tier": tier},
        )
        clerk_id = created.id
        logger.info("created clerk user for %s: %s", email, clerk_id)

    # Re-apply public metadata in case it drifted.
    clerk.users.update(
        user_id=clerk_id,
        public_metadata={"role": role, "tier": tier},
    )
    return clerk_id


def main() -> int:
    if not SEED_FILE.exists():
        logger.error(
            "missing %s — copy from seed_users.example.json and fill in real emails",
            SEED_FILE,
        )
        return 1
    config = json.loads(SEED_FILE.read_text())
    init_db()

    for user in config["users"]:
        slug = user["slug"]
        email = user["email"]
        role = user["role"]
        tier = user["tier"]

        if get_account_by_email(email) is not None:
            logger.info("skip %s — already in accounts.db", email)
            continue

        clerk_id = _find_or_create_clerk_user(email, role=role, tier=tier)

        if get_account_by_clerk_id(clerk_id) is not None:
            logger.info("skip %s — accounts.db row already exists", clerk_id)
            continue

        create_account(
            clerk_id=clerk_id,
            email=email,
            data_user_slug=slug,
            role=role,
            tier=tier,
            status="active",
            credits=99999,
        )
        logger.info("seeded %s → slug=%s tier=%s role=%s", email, slug, tier, role)

    logger.info("seed complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
