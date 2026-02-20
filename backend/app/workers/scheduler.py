"""
UGIE Periodic Sync Scheduler
────────────────────────────
Runs as a background asyncio task inside the FastAPI application.
Periodically (every 5 minutes) wakes up, fetches all repositories,
and enqueues lightweight backfill jobs to keep commits, issues, and PRs fresh.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from redis import Redis
from rq import Queue

from app.config import get_settings
from app.database import get_supabase_client
from app.utils.logging import get_logger
from app.workers.backfill_worker import backfill_repo

logger = get_logger(__name__)


async def run_periodic_sync(interval_minutes: int = 5) -> None:
    """
    Sleeping loop that periodically schedules deep syncs for all federated repos.
    """
    settings = get_settings()
    pool = Redis.from_url(settings.redis_url)
    queue = Queue("default", connection=pool)

    # Initial delay so it doesn't slam the queue instantly on boot
    await asyncio.sleep(30)

    while True:
        try:
            logger.info("Starting periodic Deep Sync sweep")
            db = get_supabase_client()
            
            # Fetch all repos along with their owner's encrypted token
            result = (
                db.table("ugie_repositories")
                .select("id, user_id, ugie_users(encrypted_token)")
                .execute()
            )
            
            repos = result.data or []
            jobs_enqueued = 0

            for repo in repos:
                repo_id = repo["id"]
                user_id = repo["user_id"]
                user_data = repo.get("ugie_users")
                
                if not user_data or not user_data.get("encrypted_token"):
                    continue
                    
                encrypted = user_data.get("encrypted_token")
                
                # We use a stable job id per window to avoid duplicate enqueues 
                # if the scheduler accidentally runs twice.
                window_id = datetime.now(timezone.utc).strftime('%Y%j%H%M')
                job_id = f"deepsync-{repo_id}-{window_id}"
                
                # Fetch up to 50 latest items across commits/issues/pulls
                queue.enqueue(
                    backfill_repo,
                    repo_id=repo_id,
                    user_id=user_id,
                    encrypted_token=encrypted,
                    depth=50,
                    job_id=job_id
                )
                jobs_enqueued += 1
                
            logger.info(
                "Enqueued periodic Deep Sync jobs", 
                extra={"jobs": jobs_enqueued, "interval_m": interval_minutes}
            )
            
        except Exception as exc:
            logger.error(
                "Periodic Deep Sync sweep failed", 
                extra={"error": str(exc)}
            )
            
        await asyncio.sleep(interval_minutes * 60)
