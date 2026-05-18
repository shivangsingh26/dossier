"""Standalone pipeline worker process.

Polls pipeline_runs for queued rows, marks them running, (M4: executes the
agent), records completion + refunds.

For M2 this is BOILERPLATE: pick + log + sleep. No actual agent execution.
The hookup to dossier_sdk.orchestrator happens in M4.

Run: uv run python -m dossier_api.workers.pipeline_worker
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dossier_api.db import _connect, init_db
from dossier_api.settings import get_settings

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 5


def pick_next_queued_run(*, db_path: Path | None = None) -> dict[str, Any] | None:
    """Atomically claim the oldest queued run, mark it running, return it.

    Returns None if nothing queued.
    """
    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT * FROM pipeline_runs
               WHERE status = 'queued'
               ORDER BY rowid ASC
               LIMIT 1"""
        ).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return None
        run_id = row["run_id"]
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE pipeline_runs SET status='running', started_at=? WHERE run_id=?",
            (now, run_id),
        )
        return dict(row)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="[%(levelname)s] [worker] %(message)s",
    )
    settings = get_settings()
    init_db(settings.accounts_db_path)
    logger.info("worker started · db=%s · poll=%ss", settings.accounts_db_path, POLL_INTERVAL_S)
    while True:
        run = pick_next_queued_run()
        if run is None:
            logger.info("[idle] no queued runs")
            time.sleep(POLL_INTERVAL_S)
            continue
        # M2: just log it. M4 will swap this for dossier_sdk.orchestrator dispatch.
        logger.info("picked run %s (agent=%s) — no-op in M2", run["run_id"], run["agent"])
        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    main()
