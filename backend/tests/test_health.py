"""Tests /health endpoint."""
from fastapi.testclient import TestClient

from dossier_api.main import app


def test_health_ok(tmp_db_path):
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
