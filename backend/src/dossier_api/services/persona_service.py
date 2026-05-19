"""Filesystem + SDK glue for persona endpoints.

Resolves the per-user profile dir at profile/{slug}/. Tests monkeypatch
profile_dir_for so they can isolate filesystem writes.
"""
from __future__ import annotations

import json
from pathlib import Path

from dossier_api.settings import REPO_ROOT


def profile_dir_for(slug: str) -> Path:
    """Return profile/{slug}/ under repo root. Creates if missing."""
    d = REPO_ROOT / "profile" / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def raw_dir_for(slug: str) -> Path:
    d = profile_dir_for(slug) / "raw"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_profile_json(slug: str) -> dict | None:
    p = profile_dir_for(slug) / "profile.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def save_profile_json(slug: str, data: dict) -> None:
    p = profile_dir_for(slug) / "profile.json"
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_questionnaire(slug: str) -> dict | None:
    p = profile_dir_for(slug) / "questionnaire.json"
    return json.loads(p.read_text()) if p.exists() else None


def save_questionnaire(slug: str, data: dict) -> None:
    p = profile_dir_for(slug) / "questionnaire.json"
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_quiz_answers(slug: str) -> dict | None:
    p = profile_dir_for(slug) / "quiz_answers.json"
    return json.loads(p.read_text()) if p.exists() else None


def save_quiz_answers(slug: str, data: dict) -> None:
    p = profile_dir_for(slug) / "quiz_answers.json"
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


MAX_PDF_BYTES = 10 * 1024 * 1024  # 10MB per spec §13


def deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge overlay into base. overlay wins on conflicts."""
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def save_uploaded_pdf(slug: str, file_kind: str, filename: str, content: bytes) -> Path:
    """Save <content> to profile/{slug}/raw/<filename>. Returns path."""
    if len(content) > MAX_PDF_BYTES:
        raise ValueError(f"file exceeds {MAX_PDF_BYTES // (1024 * 1024)}MB limit")
    if file_kind not in {"resume", "linkedin"}:
        raise ValueError(f"unsupported file kind: {file_kind}")
    safe_name = "".join(c for c in filename if c.isalnum() or c in {".", "_", "-"})
    if not safe_name:
        safe_name = f"{file_kind}.pdf"
    out = raw_dir_for(slug) / safe_name
    out.write_bytes(content)
    return out
