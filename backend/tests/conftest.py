"""Shared pytest fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_db_path(tmp_path: Path, monkeypatch) -> Path:
    """Point ACCOUNTS_DB_PATH at a fresh tmpfile for each test."""
    db = tmp_path / "accounts.db"
    monkeypatch.setenv("ACCOUNTS_DB_PATH", str(db))
    from dossier_api.settings import get_settings
    get_settings.cache_clear()  # bust lru_cache so the new env var is picked up
    return db
