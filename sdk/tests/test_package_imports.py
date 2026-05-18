"""Smoke test: dossier_sdk package can be imported and exposes __version__."""

import re
from importlib.metadata import version


def test_package_importable():
    import dossier_sdk
    assert hasattr(dossier_sdk, "__version__")
    # Version must match the metadata (the source of truth in pyproject.toml).
    assert dossier_sdk.__version__ == version("dossier-sdk")


def test_version_is_pep440_ish():
    """Version should look like 'N.N.N' (with optional suffix). Not '0.0.0+dev'."""
    import dossier_sdk
    assert re.match(r"^\d+\.\d+\.\d+", dossier_sdk.__version__), (
        f"Unexpected version: {dossier_sdk.__version__!r}. "
        "Did you forget to `uv pip install -e ./sdk`?"
    )
