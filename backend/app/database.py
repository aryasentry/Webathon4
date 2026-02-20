"""
UGIE Database Layer — Supabase
──────────────────────────────
Provides a singleton Supabase client (service-role) and a lightweight
dependency for FastAPI routes that need DB access.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Generator

from supabase import Client, create_client

from app.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """
    Returns a Supabase client using the service-role key.
    Uses the service-role key so workers can bypass RLS when needed.
    NEVER expose this client to the browser/frontend.
    """
    settings = get_settings()
    client = create_client(
        settings.supabase_url,
        settings.supabase_service_role_key,
    )
    logger.info("Supabase client initialised", extra={"url": settings.supabase_url})
    return client


def get_db() -> Generator[Client, None, None]:
    """
    FastAPI dependency — yields the singleton Supabase client.

    Usage:
        @router.get("/example")
        def example(db: Client = Depends(get_db)):
            ...
    """
    yield get_supabase_client()


async def check_db_connectivity() -> bool:
    """
    Lightweight health probe.  Runs a trivial RPC call and returns True if OK.
    """
    try:
        db = get_supabase_client()
        # ping: list a single row from a system-always-present view
        db.table("ugie_health_ping").select("id").limit(1).execute()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("DB connectivity check failed: %s", exc)
        return False
