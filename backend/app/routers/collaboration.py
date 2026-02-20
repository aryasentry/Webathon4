"""
UGIE Collaboration Router
──────────────────────────
Endpoints:
  GET  /repos/{repo_id}/collaboration/collaborators          — List collaborators from DB
  POST /repos/{repo_id}/collaboration/collaborators/refresh  — Re-fetch from GitHub live
  GET  /repos/{repo_id}/collaboration/board                  — Kanban board data
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from supabase import Client

from app.database import get_db
from app.routers.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/repos/{repo_id}/collaboration", tags=["Collaboration"])


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_repo_or_404(repo_id: str, user_id: str, db: Client) -> dict:
    """Fetch a repo, ensuring it belongs to this user."""
    res = (
        db.table("ugie_repositories")
        .select("*")
        .eq("id", repo_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Repository not found or access denied")
    return res.data[0]


# ── Collaborators from DB ─────────────────────────────────────────────────────

@router.get("/collaborators", response_model=List[Dict[str, Any]], summary="List collaborators")
async def get_collaborators(
    repo_id: str,
    db: Client = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Returns enriched collaborator list for a repo, sourced from the
    `ugie_repo_collaborators → ugie_github_identities` join.
    Includes commit/issue/PR stats, permission level, and site user status.
    """
    repo = await _get_repo_or_404(repo_id, current_user["id"], db)

    # Join collaborators with their github identity info
    collab_res = (
        db.table("ugie_repo_collaborators")
        .select("permission, role_name, fetched_at, ugie_github_identities(github_login, github_id, avatar_url, name, site_user_id)")
        .eq("repo_id", repo_id)
        .order("permission")
        .execute()
    )

    # Gather commit/issue/PR stats per login
    all_commits = db.table("ugie_commits").select("author_login").eq("repo_id", repo_id).execute().data or []
    all_issues  = db.table("ugie_issues").select("assignee_login, state").eq("repo_id", repo_id).execute().data or []
    all_prs     = db.table("ugie_pull_requests").select("author_login, state, merged").eq("repo_id", repo_id).execute().data or []

    # Build per-login stats dicts
    stats: dict[str, dict] = {}
    for c in all_commits:
        login = c.get("author_login") or ""
        if login:
            stats.setdefault(login, {"commits": 0, "assigned_issues": 0, "closed_issues": 0, "opened_prs": 0, "merged_prs": 0})
            stats[login]["commits"] += 1
    for i in all_issues:
        login = i.get("assignee_login") or ""
        if login:
            stats.setdefault(login, {"commits": 0, "assigned_issues": 0, "closed_issues": 0, "opened_prs": 0, "merged_prs": 0})
            stats[login]["assigned_issues"] += 1
            if i.get("state") == "closed":
                stats[login]["closed_issues"] += 1
    for p in all_prs:
        login = p.get("author_login") or ""
        if login:
            stats.setdefault(login, {"commits": 0, "assigned_issues": 0, "closed_issues": 0, "opened_prs": 0, "merged_prs": 0})
            stats[login]["opened_prs"] += 1
            if p.get("merged"):
                stats[login]["merged_prs"] += 1

    enriched = []
    for row in (collab_res.data or []):
        identity = row.get("ugie_github_identities") or {}
        login = identity.get("github_login", "")
        user_stats = stats.get(login, {"commits": 0, "assigned_issues": 0, "closed_issues": 0, "opened_prs": 0, "merged_prs": 0})
        enriched.append({
            "login":          login,
            "github_id":      identity.get("github_id"),
            "avatar_url":     identity.get("avatar_url"),
            "name":           identity.get("name"),
            "permission":     row.get("permission", "read"),
            "role_name":      row.get("role_name"),
            "is_site_user":   bool(identity.get("site_user_id")),
            "site_user_id":   identity.get("site_user_id"),
            "fetched_at":     row.get("fetched_at"),
            **user_stats,
        })

    # If no collaborators in DB yet, trigger a background fetch and return empty list
    if not enriched:
        # In the next request they should be populated — trigger silently
        from app.services.github_oauth import decrypt_token
        from app.services.collaborator_ingestion import ingest_collaborators
        try:
            access_token = decrypt_token(current_user.get("encrypted_token", ""))
            await ingest_collaborators(
                db=db,
                repo_id=repo_id,
                owner_login=repo["owner_login"],
                repo_name=repo["name"],
                access_token=access_token,
            )
            # Re-query after ingest
            return await get_collaborators(repo_id, db, current_user)
        except Exception as exc:
            logger.warning("Inline collaborator fetch failed", extra={"error": str(exc)})

    # Sort by permission weight then by commits
    perm_order = {"admin": 0, "maintain": 1, "write": 2, "triage": 3, "read": 4}
    enriched.sort(key=lambda x: (perm_order.get(x["permission"], 9), -x["commits"]))
    return enriched


# ── Refresh endpoint ──────────────────────────────────────────────────────────

@router.post("/collaborators/refresh", summary="Re-fetch collaborators from GitHub")
async def refresh_collaborators(
    repo_id: str,
    background_tasks: BackgroundTasks,
    db: Client = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Force a fresh GitHub collaborator fetch for this repository."""
    repo = await _get_repo_or_404(repo_id, current_user["id"], db)

    from app.services.github_oauth import decrypt_token
    from app.services.collaborator_ingestion import ingest_collaborators

    try:
        access_token = decrypt_token(current_user.get("encrypted_token", ""))
    except Exception:
        raise HTTPException(status_code=400, detail="Could not decrypt access token")

    async def _do_refresh():
        try:
            await ingest_collaborators(
                db=db,
                repo_id=repo_id,
                owner_login=repo["owner_login"],
                repo_name=repo["name"],
                access_token=access_token,
            )
        except Exception as exc:
            logger.error("Collaborator refresh failed", extra={"error": str(exc)})

    background_tasks.add_task(_do_refresh)
    return {"status": "refresh_queued", "repo_id": repo_id}


# ── Kanban Board ──────────────────────────────────────────────────────────────

@router.get("/board", response_model=Dict[str, List[Dict[str, Any]]], summary="Get Kanban board data")
async def get_board(
    repo_id: str,
    db: Client = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Returns active issues and PRs categorized by state for a Kanban board.
    Columns: Todo (open, unassigned) | In Progress (open, assigned) | Review (open PRs) | Done
    """
    await _get_repo_or_404(repo_id, current_user["id"], db)

    issues = db.table("ugie_issues").select("*").eq("repo_id", repo_id).order("updated_at", desc=True).limit(200).execute().data or []
    prs    = db.table("ugie_pull_requests").select("*").eq("repo_id", repo_id).order("updated_at", desc=True).limit(200).execute().data or []

    board: dict[str, list] = {"todo": [], "in_progress": [], "review": [], "done": []}

    for issue in issues:
        item = {
            "id": f"issue-{issue['number']}",
            "number": issue["number"],
            "title": issue["title"],
            "type": "issue",
            "state": issue["state"],
            "author": issue.get("author_login"),
            "assignee": issue.get("assignee_login"),
            "updated_at": issue["updated_at"],
        }
        if issue["state"] == "open":
            board["in_progress" if issue.get("assignee_login") else "todo"].append(item)
        elif len(board["done"]) < 20:
            board["done"].append(item)

    for pr in prs:
        item = {
            "id": f"pr-{pr['number']}",
            "number": pr["number"],
            "title": pr["title"],
            "type": "pull_request",
            "state": pr["state"],
            "author": pr.get("author_login"),
            "merged": pr.get("merged", False),
            "updated_at": pr["updated_at"],
        }
        if pr["state"] == "open":
            board["review"].append(item)
        elif len(board["done"]) < 40:
            board["done"].append(item)

    for col in board:
        board[col] = sorted(board[col], key=lambda x: x["updated_at"], reverse=True)

    return board
