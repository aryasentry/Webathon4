"""
UGIE In-Process Metrics
────────────────────────
Lightweight counter/gauge store that can be dumped via the /metrics endpoint.
No external dependency — pure Python thread-safe counters.
For production replace with prometheus_client if needed.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any

_lock = threading.Lock()
_counters: dict[str, int] = defaultdict(int)
_gauges: dict[str, float] = {}
_start_time: float = time.time()

# ── Public metric names ──────────────────────────────────────────────────────
WEBHOOK_RECEIVED      = "webhook_received"
WEBHOOK_VERIFIED      = "webhook_verified"
WEBHOOK_REJECTED      = "webhook_rejected"
WEBHOOK_DUPLICATE     = "webhook_duplicate"
COMMITS_INGESTED      = "commits_ingested"
COMMITS_DEDUPLICATED  = "commits_deduplicated"
API_CALLS_MADE        = "github_api_calls_made"
RATE_LIMIT_HITS       = "github_rate_limit_hits"
WORKER_FAILURES       = "worker_failures"
REPOS_DISCOVERED      = "repos_discovered"
BACKFILL_JOBS_QUEUED  = "backfill_jobs_queued"
BACKFILL_JOBS_DONE    = "backfill_jobs_done"


def inc(name: str, amount: int = 1) -> None:
    """Increment a counter by *amount*."""
    with _lock:
        _counters[name] += amount


def set_gauge(name: str, value: float) -> None:
    """Set an absolute gauge value."""
    with _lock:
        _gauges[name] = value


def snapshot() -> dict[str, Any]:
    """Return a copy of all metrics suitable for JSON serialisation."""
    with _lock:
        return {
            "uptime_seconds": round(time.time() - _start_time, 2),
            "counters": dict(_counters),
            "gauges": dict(_gauges),
        }


def reset() -> None:
    """Reset all counters — useful in tests."""
    with _lock:
        _counters.clear()
        _gauges.clear()
