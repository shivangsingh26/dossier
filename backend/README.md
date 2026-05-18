# backend — Dossier FastAPI service

Empty placeholder. Implementation starts in **M2** — see `docs/superpowers/milestones/M2.md`.

## Planned contents

- `pyproject.toml` declaring `dossier-api` package (depends on `../sdk` via path)
- `src/dossier_api/main.py` — FastAPI app with Clerk JWT auth + CORS
- `src/dossier_api/routers/` — `auth`, `me`, `persona` (M3), `jobs` (M4), `pipeline` (M4), `admin` (M5)
- `src/dossier_api/db.py` — `accounts.db` schema + migrations (users, credits, pipeline_runs)
- `src/dossier_api/workers/pipeline_worker.py` — standalone Python worker that polls `accounts.db` for queued runs and executes them via `dossier_sdk.orchestrator` (also created in M2 — extracted from `run_dossier.py`)
- `tests/`

## Has its own venv

```bash
cd backend && uv venv && uv pip install -e .
```

Depends on `dossier-sdk` (editable, via `../sdk`).

## Cost

Free. Local dev only until SaaS goes public. See spec §5 (Tech stack) + §12 (Non-goals).
