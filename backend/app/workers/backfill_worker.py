"""
UGIE Backfill Worker
─────────────────────
RQ job that reconstructs commit history for a single repository.

Design principles:
  - Resumable via backfill_cursor (last seen SHA)
  - Rate-limit aware (backs off on 429)
  - Idempotent (upsert logic handles overlaps)
  - Configurable depth (default 200, or time-window based)
  - Updates repo backfill_complete flag on success
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app.database import get_supabase_client
from app.services import github_client as gh
from app.services.commit_ingestion import upsert_commit
from app.services.issue_ingestion import upsert_issue, upsert_pull_request
from app.services.github_oauth import decrypt_token
from app.utils.logging import get_logger
from app.utils.metrics import inc, BACKFILL_JOBS_DONE, WORKER_FAILURES, COMMITS_INGESTED

logger = get_logger(__name__)


def backfill_repo(
    repo_id: str,
    user_id: str,
    encrypted_token: str,
    depth: int = 200,
) -> dict[str, Any]:
    """
    RQ entry point — synchronous wrapper around the async implementation.
    RQ workers run sync jobs; we use asyncio.run() to drive the async code.
    """
    return asyncio.run(_backfill_repo_async(repo_id, user_id, encrypted_token, depth))


async def _backfill_repo_async(
    repo_id: str,
    user_id: str,
    encrypted_token: str,
    depth: int,
) -> dict[str, Any]:
    """
    Async implementation of the backfill job.

    Flow:
      1. Decrypt token
      2. Fetch repo metadata (owner/name) and existing backfill cursor
      3. Paginate commits up to `depth` items
      4. Upsert each commit idempotently
      5. Update backfill_cursor on every page (resumability)
      6. Mark backfill_complete = True when done
    """
    db = get_supabase_client()
    ingested = 0
    last_sha: str | None = None

    try:
        # ── Fetch repo info ──────────────────────────────────────────────────
        repo_result = (
            db.table("ugie_repositories")
            .select("owner_login,name,backfill_cursor,backfill_complete")
            .eq("id", repo_id)
            .maybe_single()
            .execute()
        )
        if not repo_result or not repo_result.data:
            logger.error("Repo not found", extra={"repo_id": repo_id})
            return {"status": "error", "reason": "repo_not_found"}

        repo = repo_result.data

        owner = repo["owner_login"]
        name = repo["name"]
        cursor = repo.get("backfill_cursor")

        # ── Decrypt token ────────────────────────────────────────────────────
        access_token = decrypt_token(encrypted_token)

        logger.info(
            "Backfill started",
            extra={"repo_id": repo_id, "full_name": f"{owner}/{name}", "depth": depth},
        )

        params: dict[str, Any] = {"per_page": 100}
        if cursor:
            # Resume from last saved SHA by using 'until' param or just
            # filtering during processing — GitHub doesn't support sha-based
            # start, so we stop when we see a SHA we already ingested
            logger.info("Resuming backfill from cursor", extra={"cursor": cursor})

        # ── Paginate and ingest commits ──────────────────────────────────────
        hit_cursor = False
        async for page in gh.paginate(
            f"/repos/{owner}/{name}/commits",
            access_token,
            params=params,
        ):
            for raw_commit in page:
                sha = raw_commit.get("sha", "")

                # Stop if we've hit the cursor (resume point / already processed)
                if cursor and sha == cursor:
                    logger.info("Reached backfill cursor — stopping commits", extra={"sha": sha})
                    hit_cursor = True
                    break

                inserted = upsert_commit(db, repo_id, raw_commit, source="backfill")
                if inserted:
                    ingested += 1
                    last_sha = sha

                if ingested >= depth:
                    hit_cursor = True
                    break

            # Persist progress after each page for resumability
            if last_sha:
                db.table("ugie_repositories").update(
                    {"backfill_cursor": last_sha}
                ).eq("id", repo_id).execute()

            if hit_cursor or ingested >= depth:
                break

        # ── Paginate and ingest PRs ──────────────────────────────────────────
        ingested_prs = 0
        try:
            async for page in gh.paginate(f"/repos/{owner}/{name}/pulls", access_token, params={"state": "all", "per_page": 100}):
                for raw_pr in page:
                    upsert_pull_request(db, repo_id, raw_pr)
                    ingested_prs += 1
                    if ingested_prs >= depth: break
                if ingested_prs >= depth: break
        except Exception as exc:
            logger.warning("PR sync failed", extra={"repo_id": repo_id, "error": str(exc)})

        # ── Paginate and ingest Issues ───────────────────────────────────────
        ingested_issues = 0
        try:
            async for page in gh.paginate(f"/repos/{owner}/{name}/issues", access_token, params={"state": "all", "per_page": 100}):
                for raw_issue in page:
                    upsert_issue(db, repo_id, raw_issue)
                    ingested_issues += 1
                    if ingested_issues >= depth: break
                if ingested_issues >= depth: break
        except Exception as exc:
            logger.warning("Issue sync failed", extra={"repo_id": repo_id, "error": str(exc)})

        # ── Mark complete ─────────────────────────────────────────────────────
        _mark_complete(db, repo_id)
        inc(BACKFILL_JOBS_DONE)

        logger.info(
            "Backfill complete",
            extra={"repo_id": repo_id, "commits_ingested": ingested},
        )
        return {"status": "complete", "commits_ingested": ingested}

    except Exception as exc:
        inc(WORKER_FAILURES)
        logger.error(
            "Backfill job failed",
            extra={"repo_id": repo_id, "error": str(exc)},
        )
        raise  # Let RQ handle retry


def _mark_complete(db: Any, repo_id: str) -> None:
    db.table("ugie_repositories").update({
        "backfill_complete": True,
        "last_synced_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", repo_id).execute()
