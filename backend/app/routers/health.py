"""
UGIE Health Router
───────────────────
Exposes:
  GET /health/live   — liveness probe (returns 200 if process is alive)
  GET /health/ready  — readiness probe (checks DB + Redis connectivity)
  GET /metrics       — current in-process counters + gauges
"""

from __future__ import annotations

import logging

import redis as redis_lib
from fastapi import APIRouter, Response
from supabase import Client

from app.config import get_settings
from app.database import check_db_connectivity
from app.utils import metrics

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Observability"])
settings = get_settings()


@router.get("/health/live", summary="Liveness probe")
async def liveness() -> dict:
    """Always returns 200 if the process is running."""
    return {"status": "alive", "service": "UGIE"}


@router.get("/health/ready", summary="Readiness probe")
async def readiness(response: Response) -> dict:
    """
    Returns 200 if both Supabase (DB) and Redis are reachable.
    Returns 503 if either dependency is down.
    """
    db_ok = await check_db_connectivity()

    redis_ok = False
    try:
        r = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
        redis_ok = r.ping()
    except Exception as exc:
        logger.warning("Redis connectivity check failed: %s", exc)

    all_ok = db_ok and redis_ok

    if not all_ok:
        response.status_code = 503

    return {
        "status": "ready" if all_ok else "degraded",
        "checks": {
            "database": "ok" if db_ok else "unreachable",
            "redis": "ok" if redis_ok else "unreachable",
        },
    }


@router.get("/metrics", summary="In-process metrics dump")
async def get_metrics() -> dict:
    """
    Returns a JSON snapshot of all in-process counters and gauges.
    Suitable for polling by a monitoring agent.
    """
    return metrics.snapshot()
