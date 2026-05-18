# dossier-sdk

Python SDK for the Dossier autonomous job-search system.

## Modules

- `dossier_sdk.config` — singleton config loader (reads `.env` from repo root)
- `dossier_sdk.core` — shared utilities (LLM client, DB, logger, caches, file vault)
- `dossier_sdk.agents` — pipeline agents (persona, discovery, watchlist, intel, gap, referral, resume, market)
- `dossier_sdk.prompts` — system + user prompt templates
- `dossier_sdk.orchestrator` — high-level pipeline functions used by the CLI and FastAPI backend

## Install (editable, from repo root)

```bash
uv pip install -e ./sdk
```

## Use

```python
from dossier_sdk.config import Config
from dossier_sdk.agents.job_discovery import discover_jobs
```
