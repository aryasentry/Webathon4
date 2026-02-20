"""
UGIE Issue and Pull Request Ingestion Service
─────────────────────────────────────────────
Idempotent upsert of GitHub Issues and Pull Requests.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from supabase import Client

from app.utils.logging import get_logger

logger = get_logger(__name__)


def upsert_issue(db: Client, repo_id: str, raw_issue: dict[str, Any]) -> bool:
    """
    Idempotently insert or update an issue record.
    Also handles Pull Requests if they are routed here (though we prefer upsert_pull_request).
    """
    # Skip if it's actually a PR; the GitHub /issues endpoint returns PRs too.
    if "pull_request" in raw_issue:
        return False

    author = raw_issue.get("user") or {}
    assignee = raw_issue.get("assignee") or {}

    record = {
        "repo_id": repo_id,
        "number": raw_issue.get("number"),
        "title": (raw_issue.get("title") or "")[:2048],
        "state": raw_issue.get("state", "open"),
        "author_login": author.get("login"),
        "assignee_login": assignee.get("login"),
        "comments_count": raw_issue.get("comments", 0),
        "created_at": _parse_date(raw_issue.get("created_at")),
        "updated_at": _parse_date(raw_issue.get("updated_at")),
        "closed_at": _parse_date(raw_issue.get("closed_at")),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        # We use upscale upsert that overwrites existing data if state/comments changed
        result = (
            db.table("ugie_issues")
            .upsert(record, on_conflict="repo_id,number", ignore_duplicates=False)
            .execute()
        )
        return bool(result.data)
    except Exception as exc:
        logger.error(
            "Issue upsert failed",
            extra={"repo_id": repo_id, "number": record.get("number"), "error": str(exc)},
        )
        raise


def upsert_pull_request(db: Client, repo_id: str, raw_pr: dict[str, Any]) -> bool:
    """
    Idempotently insert or update a pull request record.
    """
    author = raw_pr.get("user") or {}
    
    # GitHub /pulls list endpoint doesn't include additions/deletions/changed_files by default.
    # It only includes them if you fetch the single PR endpoint. 
    # For backfill speed, we just default to 0 if missing.
    additions = raw_pr.get("additions", 0)
    deletions = raw_pr.get("deletions", 0)
    changed_files = raw_pr.get("changed_files", 0)
    
    # Sometimes merged is a boolean, sometimes we must imply it from merged_at
    merged_at = _parse_date(raw_pr.get("merged_at"))
    merged = raw_pr.get("merged", bool(merged_at))

    record = {
        "repo_id": repo_id,
        "number": raw_pr.get("number"),
        "title": (raw_pr.get("title") or "")[:2048],
        "state": raw_pr.get("state", "open"),
        "author_login": author.get("login"),
        "merged": merged,
        "additions": additions,
        "deletions": deletions,
        "changed_files": changed_files,
        "created_at": _parse_date(raw_pr.get("created_at")),
        "updated_at": _parse_date(raw_pr.get("updated_at")),
        "closed_at": _parse_date(raw_pr.get("closed_at")),
        "merged_at": merged_at,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        result = (
            db.table("ugie_pull_requests")
            .upsert(record, on_conflict="repo_id,number", ignore_duplicates=False)
            .execute()
        )
        return bool(result.data)
    except Exception as exc:
        logger.error(
            "PR upsert failed",
            extra={"repo_id": repo_id, "number": record.get("number"), "error": str(exc)},
        )
        raise


def _parse_date(date_str: str | None) -> str | None:
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return None
