# backend — Dossier FastAPI service

FastAPI app (`:8000`) backing the Next.js frontend. Wraps `dossier-sdk` agents.

## Install

```bash
cd backend
uv sync                    # creates .venv and installs deps + dossier-sdk (editable, ../sdk)
cp .env.example .env       # then fill in Clerk keys
```

## Run dev

```bash
uv run uvicorn dossier_api.main:app --reload --port 8000
```

In a second terminal, start the worker:

```bash
uv run python -m dossier_api.workers.pipeline_worker
```

## Tests

```bash
uv run pytest -v
```

## Seed existing users (one-time)

Edit `scripts/seed_users.json` (gitignored) with the 4 existing users' emails, then:

```bash
uv run python -m dossier_api.scripts.seed_existing_users
```

Idempotent — re-running skips users whose `clerk_id` already exists.

## Layout

| Path | Purpose |
|---|---|
| `src/dossier_api/main.py` | FastAPI app, lifespan(init_db), CORS |
| `src/dossier_api/settings.py` | env loader singleton |
| `src/dossier_api/db.py` | `accounts.db` schema + helpers |
| `src/dossier_api/deps.py` | `get_current_user`, `require_admin` |
| `src/dossier_api/routers/` | health, me, webhooks (M3+: persona, jobs, pipeline, admin) |
| `src/dossier_api/workers/pipeline_worker.py` | polls queued runs; M4 wires to orchestrator |
| `scripts/seed_existing_users.py` | seeds existing 4 users into Clerk + accounts.db |

## Cost

Free. Local dev only until SaaS goes public. See spec §5 (Tech stack) + §12 (Non-goals).
