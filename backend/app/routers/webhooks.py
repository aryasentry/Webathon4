"""
UGIE Webhooks Router
──────────────────────
Receives and validates GitHub webhook deliveries.

Pipeline:
  1. Read raw body (before JSON parsing to verify signature)
  2. Verify HMAC-SHA256 signature
  3. Check X-GitHub-Delivery for replay protection (Redis dedup)
  4. Store raw event in ugie_webhook_events
  5. Enqueue processing job in Redis
  6. Return 202 Accepted within 2 seconds
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import redis as redis_lib
from fastapi import APIRouter, Header, HTTPException, Request, Response, Depends
from rq import Queue as RQ
from supabase import Client

from app.config import get_settings
from app.database import get_db
from app.utils.logging import get_logger, new_correlation_id
from app.utils.metrics import inc, WEBHOOK_RECEIVED, WEBHOOK_VERIFIED, WEBHOOK_REJECTED, WEBHOOK_DUPLICATE
from app.utils.signature import verify_github_signature
from app.workers.event_processor import process_webhook_event

logger = get_logger(__name__)
router = APIRouter(prefix="/webhooks", tags=["Webhooks"])
settings = get_settings()

# Redis dedup TTL (24h) — if we've seen this delivery ID, skip it
DEDUP_TTL = settings.redis_dedup_ttl
DEDUP_PREFIX = "ugie:delivery:"


def _get_redis() -> redis_lib.Redis:
    return redis_lib.from_url(settings.redis_url)


@router.post(
    "/github",
    status_code=202,
    summary="GitHub webhook receiver",
    description=(
        "Receives webhook deliveries from GitHub. "
        "Verifies signature, deduplicates, persists event, and enqueues for processing."
    ),
)
async def receive_github_webhook(
    request: Request,
    db: Client = Depends(get_db),
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None),
) -> dict:
    cid = new_correlation_id()
    inc(WEBHOOK_RECEIVED)

    # ── Read raw body ────────────────────────────────────────────────────────
    body = await request.body()

    # ── Signature verification ───────────────────────────────────────────────
    if not verify_github_signature(body, settings.github_webhook_secret, x_hub_signature_256):
        inc(WEBHOOK_REJECTED)
        logger.warning(
            "Webhook signature verification failed",
            extra={"cid": cid, "delivery": x_github_delivery},
        )
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    inc(WEBHOOK_VERIFIED)

    # ── Replay protection via Redis ──────────────────────────────────────────
    if not x_github_delivery:
        # Assign a synthetic delivery ID if missing
        x_github_delivery = f"synthetic-{cid}"

    r = _get_redis()
    dedup_key = f"{DEDUP_PREFIX}{x_github_delivery}"
    if r.get(dedup_key):
        inc(WEBHOOK_DUPLICATE)
        logger.info("Duplicate delivery skipped", extra={"delivery": x_github_delivery})
        return {"status": "duplicate", "delivery_id": x_github_delivery}

    # Mark delivery as seen (TTL = 24h)
    r.setex(dedup_key, DEDUP_TTL, "1")

    # ── Parse payload ────────────────────────────────────────────────────────
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = x_github_event or "unknown"

    # ── Resolve repo_id if possible ──────────────────────────────────────────
    full_name = payload.get("repository", {}).get("full_name")
    repo_id: str | None = None
    if full_name:
        result = (
            db.table("ugie_repositories")
            .select("id")
            .eq("full_name", full_name)
            .limit(1)
            .execute()
        )
        if result.data:
            repo_id = result.data[0]["id"]

    # ── Persist raw event ────────────────────────────────────────────────────
    db.table("ugie_webhook_events").insert({
        "event_id": x_github_delivery,
        "event_type": event_type,
        "repo_id": repo_id,
        "raw_payload": payload,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }).execute()

    # ── Enqueue for async processing ─────────────────────────────────────────
    try:
        q = RQ("default", connection=r)
        job = q.enqueue(
            process_webhook_event,
            args=(x_github_delivery,),
            job_timeout=120,
            retry=rq_retry(max=3),
        )
        logger.info(
            "Webhook enqueued",
            extra={
                "cid": cid,
                "delivery": x_github_delivery,
                "event_type": event_type,
                "job_id": job.id,
            },
        )
    except Exception as exc:
        logger.error("Failed to enqueue webhook event", extra={"error": str(exc), "cid": cid})
        # Don't 500 — event is already persisted, worker can pick it up later

    return {
        "status": "accepted",
        "delivery_id": x_github_delivery,
        "event_type": event_type,
    }


# Lazy import to avoid circular at startup
def rq_retry(max: int = 3):
    from rq.job import Retry
    return Retry(max=max, interval=[10, 30, 60])
