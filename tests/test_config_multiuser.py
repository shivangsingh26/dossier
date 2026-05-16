"""Tests for Config multi-user path isolation."""
import os
import pytest
from pathlib import Path
from unittest.mock import patch
from config import Config


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


def test_default_user_is_me():
    config = Config()
    assert config.user == "me"
    assert config.profile_path == Path("profile/me/profile.json")
    assert config.db_path == Path("data/me/dossier.db")
    assert config.artifacts_dir == Path("data/me/artifacts")


def test_custom_user_isolates_paths():
    config = Config(user="anushthan")
    assert config.user == "anushthan"
    assert config.profile_path == Path("profile/anushthan/profile.json")
    assert config.db_path == Path("data/anushthan/dossier.db")
    assert config.artifacts_dir == Path("data/anushthan/artifacts")


def test_singleton_ignores_second_user_arg():
    c1 = Config(user="me")
    c2 = Config(user="anushthan")  # second call — user arg ignored
    assert c1 is c2
    assert c2.user == "me"


def test_shared_paths_not_user_scoped():
    config = Config(user="krishna")
    assert config.target_companies_path == Path("profile/target_companies.json")
    assert config.linkedin_id_cache_path == Path("data/linkedin_company_ids.json")
