"""Smoke test: dossier_sdk package can be imported and exposes __version__."""


def test_package_importable():
    import dossier_sdk
    assert hasattr(dossier_sdk, "__version__")
    assert dossier_sdk.__version__ == "1.0.0"
