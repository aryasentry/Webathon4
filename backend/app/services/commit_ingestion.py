"""
UGIE Commit Ingestion Service
──────────────────────────────
Idempotent upsert of commit records.

The idempotency key is (repo_id, sha) — enforced at the DB level via
a UNIQUE constraint. We use INSERT ... ON CONFLICT DO NOTHING so that
backfill + webhook overlap never causes duplicates or errors.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

from supabase import Client

from app.utils.logging import get_logger
from app.utils.metrics import inc, COMMITS_INGESTED, COMMITS_DEDUPLICATED

logger = get_logger(__name__)


def upsert_commit(
    db: Client,
    repo_id: str,
    raw_commit: dict[str, Any],
    source: str = "backfill",
) -> bool:
    """
    Idempotently insert a commit record.

    Args:
        db:         Supabase client.
        repo_id:    UUID of the ugie_repositories row.
        raw_commit: Normalised commit dict (see _normalise_commit).
        source:     "backfill" | "webhook"

    Returns:
        True if inserted, False if already existed (deduplicated).
    """
    record = _normalise_commit(raw_commit, repo_id, source)

    try:
        result = (
            db.table("ugie_commits")
            .upsert(record, on_conflict="repo_id,sha", ignore_duplicates=True)
            .execute()
        )
        if result.data:
            inc(COMMITS_INGESTED)
            _update_contribution_snapshot(db, repo_id, record)
            return True
        else:
            inc(COMMITS_DEDUPLICATED)
            return False
    except Exception as exc:
        logger.error(
            "Commit upsert failed",
            extra={"repo_id": repo_id, "sha": record.get("sha"), "error": str(exc)},
        )
        raise


def _normalise_commit(raw: dict[str, Any], repo_id: str, source: str) -> dict[str, Any]:
    """
    Map various raw formats (GitHub API /commits endpoint, webhook push payload)
    to a consistent ugie_commits record.
    """
    # Webhook push payload nests commit data differently from the REST API
    commit_data = raw.get("commit", raw)

    author = commit_data.get("author") or {}
    stats = raw.get("stats", {})

    # Parse authored timestamp
    authored_at_raw = author.get("date") or commit_data.get("author", {}).get("date") or raw.get("timestamp")
    try:
        if authored_at_raw:
            # handle both ISO 8601 with Z and +00:00
            authored_at = datetime.fromisoformat(
                authored_at_raw.replace("Z", "+00:00")
            ).isoformat()
        else:
            authored_at = datetime.now(timezone.utc).isoformat()
    except ValueError:
        authored_at = datetime.now(timezone.utc).isoformat()

    return {
        "repo_id": repo_id,
        "sha": raw.get("sha") or raw.get("id", ""),
        "message": (commit_data.get("message") or "")[:2048].split("\n")[0],
        "author_login": raw.get("author", {}).get("login") if isinstance(raw.get("author"), dict) else author.get("name"),
        "author_email": author.get("email"),
        "authored_at": authored_at,
        "additions": stats.get("additions", 0),
        "deletions": stats.get("deletions", 0),
        "files_changed": len(raw.get("files", [])) or stats.get("total", 0),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
    }


def _update_contribution_snapshot(
    db: Client,
    repo_id: str,
    commit_record: dict[str, Any],
) -> None:
    """
    Atomically increment the daily contribution snapshot for this repo/user.
    Uses Supabase's upsert with addition semantics via RPC.
    """
    try:
        # Get user_id from repo
        repo_result = (
            db.table("ugie_repositories")
            .select("user_id")
            .eq("id", repo_id)
            .single()
            .execute()
        )
        if not repo_result.data:
            return

        user_id = repo_result.data["user_id"]
        snapshot_date = datetime.fromisoformat(
            commit_record["authored_at"].replace("Z", "+00:00")
        ).date().isoformat()

        # Try to increment an existing snapshot or insert new
        existing = (
            db.table("ugie_contribution_snapshots")
            .select("id,commit_count,additions,deletions,files_changed")
            .eq("user_id", user_id)
            .eq("repo_id", repo_id)
            .eq("snapshot_date", snapshot_date)
            .execute()
        )

        additions = commit_record.get("additions", 0)
        deletions = commit_record.get("deletions", 0)
        files_changed = commit_record.get("files_changed", 0)

        if existing.data:
            row = existing.data[0]
            db.table("ugie_contribution_snapshots").update({
                "commit_count": row["commit_count"] + 1,
                "additions": row["additions"] + additions,
                "deletions": row["deletions"] + deletions,
                "files_changed": row["files_changed"] + files_changed,
            }).eq("id", row["id"]).execute()
        else:
            db.table("ugie_contribution_snapshots").insert({
                "user_id": user_id,
                "repo_id": repo_id,
                "snapshot_date": snapshot_date,
                "commit_count": 1,
                "additions": additions,
                "deletions": deletions,
                "files_changed": files_changed,
            }).execute()

    except Exception as exc:
        # Non-fatal — log and continue
        logger.warning(
            "Contribution snapshot update failed",
            extra={"repo_id": repo_id, "error": str(exc)},
        )
