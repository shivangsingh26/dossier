"""Tests for Config multi-user path isolation.

Post-M0: paths are anchored to the repo root (absolute) so the SDK works
from any cwd. Tests assert (a) the user slug is correct and (b) the path
ends with the expected user-scoped relative segment.
"""
import os
import pytest
from pathlib import Path
from unittest.mock import patch
from dossier_sdk.config import Config


@pytest.fixture(autouse=True)
def reset_config_singleton():
    """Reset singleton and patch required env vars so tests run without a real .env."""
    Config._instance = None
    with patch.dict(os.environ, {
        "OPENAI_API_KEY": "test-openai-key",
        "ANTHROPIC_API_KEY": "test-anthropic-key",
    }):
        yield
    Config._instance = None


def _ends_with(path: Path, suffix: str) -> bool:
    """True if the absolute path ends with the given relative suffix."""
    return path.is_absolute() and str(path).endswith(suffix)


def test_default_user_is_shivang():
    """Default user is 'shivang' (the creator). Paths are absolute, anchored to repo root."""
    config = Config()
    assert config.user == "shivang"
    assert _ends_with(config.profile_path, "profile/shivang/profile.json")
    assert _ends_with(config.db_path, "data/shivang/dossier.db")
    assert _ends_with(config.artifacts_dir, "data/shivang/artifacts")


def test_custom_user_isolates_paths():
    """Passing a different user scopes every user-specific path."""
    config = Config(user="anushthan")
    assert config.user == "anushthan"
    assert _ends_with(config.profile_path, "profile/anushthan/profile.json")
    assert _ends_with(config.db_path, "data/anushthan/dossier.db")
    assert _ends_with(config.artifacts_dir, "data/anushthan/artifacts")


def test_singleton_ignores_second_user_arg():
    """Once Config() is called, subsequent calls reuse the same instance."""
    c1 = Config(user="krishna")
    c2 = Config(user="anushthan")  # second call — user arg ignored
    assert c1 is c2
    assert c2.user == "krishna"


def test_shared_paths_not_user_scoped():
    """target_companies.json and linkedin_id_cache.json are global, not per-user."""
    config = Config(user="krishna")
    assert _ends_with(config.target_companies_path, "profile/target_companies.json")
    assert _ends_with(config.linkedin_id_cache_path, "data/linkedin_company_ids.json")
    # Confirm no user slug in shared paths
    assert "krishna" not in str(config.target_companies_path)
    assert "krishna" not in str(config.linkedin_id_cache_path)


def test_paths_are_absolute():
    """All paths must be absolute so the SDK works from any cwd (CLI, FastAPI, pytest)."""
    config = Config(user="shivang")
    for attr in ("profile_dir", "profile_path", "data_dir", "artifacts_dir",
                 "db_path", "prompts_dir", "target_companies_path",
                 "exception_companies_path", "linkedin_id_cache_path"):
        path = getattr(config, attr)
        assert isinstance(path, Path), f"{attr} is not a Path"
        assert path.is_absolute(), f"{attr} is not absolute: {path}"
