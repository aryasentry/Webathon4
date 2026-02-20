"""
UGIE Webhook Event Processor
─────────────────────────────
RQ job that processes a single webhook event from the Redis queue.

Pipeline:
  webhook_events table → fetch event → route by type → ingest → mark processed

Design:
  - Routes: push, pull_request, pull_request_review, issues, issue_comment
  - Idempotent: safe to re-process (commit upsert is idempotent)
  - Exponential retry via RQ's built-in retry
  - Dead-letter: failed events written to DLQ in Redis + webhook_events.failed = True
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app.services.commit_ingestion import upsert_commit
from app.services.issue_ingestion import upsert_issue, upsert_pull_request
from app.utils.logging import get_logger
from app.utils.metrics import inc, WORKER_FAILURES, COMMITS_INGESTED

logger = get_logger(__name__)


def process_webhook_event(event_id: str) -> dict[str, Any]:
    """
    RQ entry point — processes a single webhook event identified by its
    GitHub delivery ID.

    Steps:
      1. Fetch event from ugie_webhook_events
      2. Check not already processed (idempotency guard)
      3. Route by event_type to the correct handler
      4. Mark as processed
      5. On failure: increment retry_count, set failed=True after max retries
    """
    return asyncio.run(_process_event_async(event_id))


async def _process_event_async(event_id: str) -> dict[str, Any]:
    db = get_supabase_client()

    # ── Fetch event ──────────────────────────────────────────────────────────
    result = (
        db.table("ugie_webhook_events")
        .select("*")
        .eq("event_id", event_id)
        .single()
        .execute()
    )

    if not result.data:
        logger.warning("Event not found in DB", extra={"event_id": event_id})
        return {"status": "not_found"}

    event = result.data
    event_type: str = event["event_type"]
    payload: dict[str, Any] = event["raw_payload"]
    repo_id: str | None = event.get("repo_id")

    # ── Idempotency guard ────────────────────────────────────────────────────
    if event.get("processed"):
        logger.info("Event already processed — skipping", extra={"event_id": event_id})
        return {"status": "duplicate", "event_id": event_id}

    try:
        outcome: dict[str, Any] = {}

        # ── Route by event type ──────────────────────────────────────────────
        if event_type == "push":
            outcome = await _handle_push(db, payload, repo_id)
        elif event_type == "pull_request":
            outcome = await _handle_pull_request(db, payload, repo_id)
        elif event_type == "issues":
            outcome = await _handle_issues(db, payload, repo_id)
        elif event_type == "pull_request_review":
            outcome = _handle_generic(event_type, payload)
        elif event_type == "issue_comment":
            outcome = _handle_generic(event_type, payload)
        else:
            logger.warning("Unknown event type", extra={"event_type": event_type})
            outcome = {"status": "unhandled", "event_type": event_type}

        # ── Mark processed ───────────────────────────────────────────────────
        db.table("ugie_webhook_events").update({
            "processed": True,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("event_id", event_id).execute()

        logger.info(
            "Event processed",
            extra={"event_id": event_id, "event_type": event_type, "outcome": outcome},
        )
        return {"status": "ok", "event_id": event_id, **outcome}

    except Exception as exc:
        inc(WORKER_FAILURES)
        # Increment retry counter and mark as failed after threshold
        new_retry_count = event.get("retry_count", 0) + 1
        db.table("ugie_webhook_events").update({
            "retry_count": new_retry_count,
            "failed": new_retry_count >= 5,
            "error_message": str(exc)[:1024],
        }).eq("event_id", event_id).execute()

        logger.error(
            "Event processing failed",
            extra={"event_id": event_id, "retry_count": new_retry_count, "error": str(exc)},
        )
        raise  # Let RQ retry


async def _handle_push(
    db: Any,
    payload: dict[str, Any],
    repo_id: str | None,
) -> dict[str, Any]:
    """
    Process a GitHub push event.
    Each commit in the push is idempotently upserted.
    """
    commits = payload.get("commits", [])
    ingested = 0

    if not repo_id:
        # Try to resolve repo_id from full_name in payload
        full_name = payload.get("repository", {}).get("full_name")
        if full_name:
            result = (
                db.table("ugie_repositories")
                .select("id")
                .eq("full_name", full_name)
                .execute()
            )
            if result.data:
                repo_id = result.data[0]["id"]

    if not repo_id:
        logger.warning("Cannot resolve repo for push event", extra={"payload_keys": list(payload.keys())})
        return {"status": "repo_not_found", "commits": 0}

    for raw_commit in commits:
        # Enrich with repo context from push payload
        raw_commit["_repo_full_name"] = payload.get("repository", {}).get("full_name")
        inserted = upsert_commit(db, repo_id, raw_commit, source="webhook")
        if inserted:
            ingested += 1

    return {"commits_ingested": ingested, "commits_total": len(commits)}


async def _handle_pull_request(
    db: Any,
    payload: dict[str, Any],
    repo_id: str | None,
) -> dict[str, Any]:
    """
    Process a GitHub pull_request event.
    """
    action = payload.get("action", "unknown")
    if not repo_id:
        full_name = payload.get("repository", {}).get("full_name")
        if full_name:
            result = db.table("ugie_repositories").select("id").eq("full_name", full_name).execute()
            if result.data: repo_id = result.data[0]["id"]

    if not repo_id:
        return {"status": "repo_not_found"}

    pr_data = payload.get("pull_request")
    if pr_data:
        upsert_pull_request(db, repo_id, pr_data)

    return {"action": action, "pr_number": pr_data.get("number") if pr_data else None}


async def _handle_issues(
    db: Any,
    payload: dict[str, Any],
    repo_id: str | None,
) -> dict[str, Any]:
    """
    Process a GitHub issues event.
    """
    action = payload.get("action", "unknown")
    if not repo_id:
        full_name = payload.get("repository", {}).get("full_name")
        if full_name:
            result = db.table("ugie_repositories").select("id").eq("full_name", full_name).execute()
            if result.data: repo_id = result.data[0]["id"]

    if not repo_id:
        return {"status": "repo_not_found"}

    issue_data = payload.get("issue")
    if issue_data:
        upsert_issue(db, repo_id, issue_data)

    return {"action": action, "issue_number": issue_data.get("number") if issue_data else None}


def _handle_generic(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Default handler — log and acknowledge."""
    logger.info("Generic event received", extra={"event_type": event_type})
    return {"event_type": event_type, "action": payload.get("action", "unknown")}
