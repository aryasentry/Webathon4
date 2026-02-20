"""
UGIE Structured Logging
────────────────────────
Configures every logger in the process to emit JSON lines.
Each log record includes: timestamp, level, logger name, message,
and any extra fields passed (correlation_id, repo_id, etc).
"""

from __future__ import annotations

import logging
import sys
import uuid

from pythonjsonlogger import jsonlogger

from app.config import get_settings

_CONFIGURED = False


def configure_logging() -> None:
    """
    Call once at application startup (inside lifespan).
    Idempotent — safe to call multiple times.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    settings = get_settings()
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        rename_fields={"asctime": "ts", "levelname": "level", "name": "logger"},
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # Quiet noisy third-party loggers
    for noisy in ("httpx", "httpcore", "supabase", "postgrest"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a named logger (JSON-formatted after configure_logging() is called)."""
    return logging.getLogger(name)


def new_correlation_id() -> str:
    """Generate a fresh RFC-4122 correlation ID for a request trace."""
    return str(uuid.uuid4())
