"""Singleton settings loader. Reads backend/.env once, exposes typed attrs.

WHY SINGLETON: The same FastAPI app + worker process should read env vars once at
boot, not on every request. Singleton pattern matches sdk/config.py.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / ".env", override=False)


class Settings(BaseModel):
    clerk_secret_key: str
    clerk_webhook_secret: str
    accounts_db_path: Path
    allowed_origins: list[str]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    default_db = REPO_ROOT / "data" / "accounts.db"
    return Settings(
        clerk_secret_key=os.environ.get("CLERK_SECRET_KEY", ""),
        clerk_webhook_secret=os.environ.get("CLERK_WEBHOOK_SECRET", ""),
        accounts_db_path=Path(os.environ.get("ACCOUNTS_DB_PATH") or default_db),
        allowed_origins=[
            o.strip()
            for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
            if o.strip()
        ],
    )
