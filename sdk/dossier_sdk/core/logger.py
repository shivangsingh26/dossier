"""
core/logger.py — Centralised logging setup for the Dossier project.

Every module calls get_logger(__name__) to get its own named logger.
All loggers inherit settings from the root "dossier" logger set up here.

WHY LOGGING INSTEAD OF PRINT:
- Log levels let you filter noise: set LOG_LEVEL=DEBUG to see everything,
  INFO to see normal flow, WARNING+ to see only problems
- Every log line includes timestamp + module name — you know WHEN and WHERE
- Logs go to both console AND a file simultaneously
- print() in a running agent = noise with no context. Logging = signal with context.

LOGGER HIERARCHY:
  dossier                        ← root logger (set up once in setup_logging)
  dossier.core.llm_client        ← module logger via get_logger(__name__)
  dossier.agents.job_discovery   ← module logger via get_logger(__name__)
"""

import logging
import sys
from pathlib import Path


# Tracks whether logging has been set up already — safe to call setup_logging() multiple times
_logging_configured = False


def setup_logging(log_level: str = "INFO") -> None:
    """Configure the root dossier logger. Safe to call multiple times — only sets up once."""
    global _logging_configured
    if _logging_configured:
        return

    level = getattr(logging, log_level.upper(), logging.INFO)

    # Format: [2026-05-01 10:30:45] [INFO] [core.llm_client] LLM client initialised
    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console: show logs at configured level (INFO by default)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    # File: always write DEBUG and above so nothing is lost
    Path("data").mkdir(exist_ok=True)
    file_handler = logging.FileHandler("data/dossier.log")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # Root dossier logger — all module loggers inherit from this
    root = logging.getLogger("dossier")
    root.setLevel(logging.DEBUG)
    root.addHandler(console_handler)
    root.addHandler(file_handler)

    _logging_configured = True


def get_logger(name: str) -> logging.Logger:
    """
    Return a named logger for a module. Call with __name__ from any module.

    Example:
        from dossier_sdk.core.logger import get_logger
        logger = get_logger(__name__)
        logger.info("Job discovery started")

    This produces: [2026-05-01 10:30:45] [INFO] [dossier.agents.job_discovery] Job discovery started
    """
    # Lazy import to avoid circular dependency at module level
    try:
        from dossier_sdk.config import Config
        log_level = Config().log_level
    except Exception:
        log_level = "INFO"

    setup_logging(log_level)

    # Prefix with "dossier." so all project loggers are under one namespace
    full_name = f"dossier.{name}" if not name.startswith("dossier.") else name
    return logging.getLogger(full_name)
