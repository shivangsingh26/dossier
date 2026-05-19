"""FastAPI app entrypoint.

Run: uv run uvicorn dossier_api.main:app --reload --port 8000
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dossier_api.db import init_db
from dossier_api.routers import health, me, persona, pipeline, webhooks
from dossier_api.settings import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run once at boot: ensure accounts.db schema exists."""
    settings = get_settings()
    init_db(settings.accounts_db_path)
    logger.info("dossier-api ready · db=%s", settings.accounts_db_path)
    yield
    logger.info("dossier-api shutting down")


app = FastAPI(title="dossier-api", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(me.router)
app.include_router(persona.router)
app.include_router(pipeline.router)
app.include_router(webhooks.router)
