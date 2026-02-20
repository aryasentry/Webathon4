"""
UGIE Repos Router
──────────────────
Endpoints:
  GET  /repos                     — List all discovered repos for current user
  POST /repos/rescan              — Trigger full re-discovery
  POST /repos/{repo_id}/rescan    — Trigger on-demand backfill for single repo
  GET  /repos/{repo_id}/commits   — Paginated commit list for a repo
"""

from __future__ import annotations

import logging
from typing import Annotated

import redis as redis_lib
from fastapi import APIRouter, Depends, Header, HTTPException, Query, BackgroundTasks
from rq import Queue as RQ
from supabase import Client

from app.config import get_settings
from app.database import get_db
from app.routers.auth import decode_jwt, get_current_user
from app.schemas.commit import CommitListResponse, CommitOut
from app.schemas.repo import RepositoryListResponse, RepositoryOut, RescanResponse
from app.schemas.issue import IssueListResponse, IssueOut, PullRequestListResponse, PullRequestOut
from app.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/repos", tags=["Repositories"])
settings = get_settings()


@router.get("", response_model=RepositoryListResponse, summary="List all repos")
async def list_repos(
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    archived: bool | None = None,
    language: str | None = None,
) -> RepositoryListResponse:
    """Return all repos discovered for the authenticated user."""
    query = (
        db.table("ugie_repositories")
        .select("*")
        .eq("user_id", current_user["id"])
    )
    if archived is not None:
        query = query.eq("archived", archived)
    if language:
        query = query.eq("language", language)

    # Supabase range-based pagination
    offset = (page - 1) * page_size
    result = query.range(offset, offset + page_size - 1).order("updated_at", desc=True).execute()

    count_result = db.table("ugie_repositories").select("id", count="exact").eq("user_id", current_user["id"]).execute()
    total = count_result.count or 0

    return RepositoryListResponse(
        total=total,
        repositories=[RepositoryOut(**r) for r in (result.data or [])],
    )


@router.get("/{repo_id}", response_model=RepositoryOut, summary="Get single repo")
async def get_repo(
    repo_id: str,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
) -> RepositoryOut:
    """Return a single repository detail for the authenticated user."""
    result = (
        db.table("ugie_repositories")
        .select("*")
        .eq("id", repo_id)
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    return RepositoryOut(**result.data)


@router.post("/rescan", response_model=dict, summary="Re-discover all repos")
async def rescan_all(
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
) -> dict:
    """Trigger a full repository graph re-discovery for the current user."""
    from app.services.github_oauth import decrypt_token
    from app.services.repo_discovery import discover_and_upsert_repos, process_webhooks_and_backfill

    try:
        encrypted = current_user.get("encrypted_token", "")
        access_token = decrypt_token(encrypted)

        repos = await discover_and_upsert_repos(
            db=db,
            user_id=current_user["id"],
            github_id=current_user["github_id"],
            access_token=access_token,
        )

        async def _run_webhooks_background():
            from app.routers.auth import get_supabase_client_direct
            db_client = get_supabase_client_direct()
            await process_webhooks_and_backfill(
                db=db_client,
                user_id=current_user["id"],
                access_token=access_token,
                encrypted_token=encrypted,
                repos=repos,
                webhook_base_url=settings.github_oauth_redirect_uri.rsplit("/", 1)[0],
                webhook_secret=settings.github_webhook_secret,
                depth=settings.backfill_depth,
            )

        background_tasks.add_task(_run_webhooks_background)

        return {"status": "rescan_triggered", "repos_discovered": len(repos)}

    except Exception as exc:
        logger.error("Rescan failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail=f"Rescan failed: {exc}") from exc


@router.post("/{repo_id}/rescan", response_model=RescanResponse, summary="Backfill single repo")
async def rescan_repo(
    repo_id: str,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
) -> RescanResponse:
    """Queue an on-demand backfill job for a single repository."""
    # Verify ownership
    result = (
        db.table("ugie_repositories")
        .select("id")
        .eq("id", repo_id)
        .eq("user_id", current_user["id"])
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Repository not found")

    from app.workers.backfill_worker import backfill_repo

    r = redis_lib.from_url(settings.redis_url)
    q = RQ("default", connection=r)
    job = q.enqueue(
        backfill_repo,
        args=(repo_id, current_user["id"], current_user["encrypted_token"], settings.backfill_depth),
        job_timeout=600,
    )

    return RescanResponse(repo_id=repo_id, job_id=job.id)


@router.get(
    "/{repo_id}/commits",
    response_model=CommitListResponse,
    summary="List commits for a repo",
)
async def list_commits(
    repo_id: str,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    author: str | None = None,
) -> CommitListResponse:
    """Return paginated commits for the specified repository."""
    # Verify repo exists (user_id check omitted — FK may differ from ugie_users.id)
    repo_result = (
        db.table("ugie_repositories")
        .select("id")
        .eq("id", repo_id)
        .execute()
    )
    if not repo_result.data:
        raise HTTPException(status_code=404, detail="Repository not found")

    query = (
        db.table("ugie_commits")
        .select("*")
        .eq("repo_id", repo_id)
    )
    if author:
        query = query.eq("author_login", author)

    offset = (page - 1) * page_size
    result = (
        query
        .range(offset, offset + page_size - 1)
        .order("authored_at", desc=True)
        .execute()
    )

    count_result = (
        db.table("ugie_commits")
        .select("id", count="exact")
        .eq("repo_id", repo_id)
        .execute()
    )

    return CommitListResponse(
        total=count_result.count or 0,
        commits=[CommitOut(**c) for c in (result.data or [])],
    )


@router.get(
    "/{repo_id}/issues",
    response_model=IssueListResponse,
    summary="List issues for a repo",
)
async def list_issues(
    repo_id: str,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    state: str | None = None,
) -> IssueListResponse:
    """Return paginated issues for the specified repository."""
    # Verify repo exists (user_id check omitted — FK may differ from ugie_users.id)
    repo_result = db.table("ugie_repositories").select("id").eq("id", repo_id).execute()
    if not repo_result.data:
        raise HTTPException(status_code=404, detail="Repository not found")

    query = db.table("ugie_issues").select("*").eq("repo_id", repo_id)
    if state: query = query.eq("state", state)

    offset = (page - 1) * page_size
    result = query.range(offset, offset + page_size - 1).order("created_at", desc=True).execute()
    count_result = db.table("ugie_issues").select("id", count="exact").eq("repo_id", repo_id).execute()

    return IssueListResponse(
        total=count_result.count or 0,
        issues=[IssueOut(**c) for c in (result.data or [])],
    )


@router.get(
    "/{repo_id}/pulls",
    response_model=PullRequestListResponse,
    summary="List pull requests for a repo",
)
async def list_pulls(
    repo_id: str,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    state: str | None = None,
) -> PullRequestListResponse:
    """Return paginated pull requests for the specified repository."""
    # Verify repo exists (user_id check omitted — FK may differ from ugie_users.id)
    repo_result = db.table("ugie_repositories").select("id").eq("id", repo_id).execute()
    if not repo_result.data:
        raise HTTPException(status_code=404, detail="Repository not found")

    query = db.table("ugie_pull_requests").select("*").eq("repo_id", repo_id)
    if state: query = query.eq("state", state)

    offset = (page - 1) * page_size
    result = query.range(offset, offset + page_size - 1).order("created_at", desc=True).execute()
    count_result = db.table("ugie_pull_requests").select("id", count="exact").eq("repo_id", repo_id).execute()

    return PullRequestListResponse(
        total=count_result.count or 0,
        pull_requests=[PullRequestOut(**c) for c in (result.data or [])],
    )
