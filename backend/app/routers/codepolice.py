"""
CodePolice Router
─────────────────
Exposes the uncommitted-change tracking data recorded by the CodePolice
VS Code extension.  All data lives in the shared Supabase project.

Endpoints (all scoped to a linked ugie_repository):
  GET /codepolice/{repo_id}/workspaces           — workspaces tracking this repo
  GET /codepolice/{repo_id}/live                  — combined live snapshot
      active task + latest alignment score + recent file descriptions
  GET /codepolice/{repo_id}/alignment             — alignment score history
  GET /codepolice/{repo_id}/changes               — recent file-change descriptions
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from supabase import Client

from app.database import get_db
from app.routers.auth import get_current_user
from app.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/codepolice", tags=["CodePolice"])


# ── Pydantic response models ──────────────────────────────────────────────────

class WorkspaceOut(BaseModel):
    id: str
    path: str
    name: str | None = None
    github_user: str | None = None

    model_config = {"from_attributes": True}


class ActiveTaskOut(BaseModel):
    id: str
    task_key: str | None = None
    title: str | None = None
    description: str | None = None
    is_active: bool = True
    created_at: str | None = None

    model_config = {"from_attributes": True}


class AlignmentSnapshotOut(BaseModel):
    id: str
    workspace_id: str
    score: float | None = None
    state: str | None = None
    files_changed: int | None = None
    computed_at: str | None = None

    model_config = {"from_attributes": True}


class FileDescriptionOut(BaseModel):
    id: str
    file_change_id: str
    workspace_id: str
    on_task_score: float | None = None
    classification: str | None = None
    # summary column may be named differently depending on extension version
    summary: str | None = None
    description: str | None = None
    file_path: str | None = None          # joined from file_changes
    created_at: str | None = None

    model_config = {"from_attributes": True}


class LiveSnapshotResponse(BaseModel):
    workspace: WorkspaceOut
    active_task: ActiveTaskOut | None = None
    latest_alignment: AlignmentSnapshotOut | None = None
    recent_descriptions: list[FileDescriptionOut] = []
    score_history: list[AlignmentSnapshotOut] = []


# ── Helpers ───────────────────────────────────────────────────────────────────

def _verify_repo_ownership(db: Client, repo_id: str, user_id: str) -> None:
    """Raise 404 if the repo doesn't belong to this user."""
    result = (
        db.table("ugie_repositories")
        .select("id")
        .eq("id", repo_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Repository not found")


def _get_workspaces(db: Client, repo_id: str) -> list[dict[str, Any]]:
    result = (
        db.table("workspaces")
        .select("id, path, name, github_user")
        .eq("repo_id", repo_id)
        .execute()
    )
    return result.data or []


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/{repo_id}/workspaces", response_model=list[WorkspaceOut])
async def list_workspaces(
    repo_id: str,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
) -> list[WorkspaceOut]:
    """Return all VS Code workspaces the CodePolice extension has registered
    for this repository."""
    _verify_repo_ownership(db, repo_id, current_user["id"])
    rows = _get_workspaces(db, repo_id)
    return [WorkspaceOut(**r) for r in rows]


@router.get("/{repo_id}/live", response_model=list[LiveSnapshotResponse])
async def get_live_snapshot(
    repo_id: str,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
    descriptions_limit: int = Query(20, ge=1, le=100),
    history_limit: int = Query(48, ge=1, le=200),
) -> list[LiveSnapshotResponse]:
    """Return a combined live view for every workspace linked to this repo.

    For each workspace returns:
    - The currently active task
    - The most recent alignment snapshot
    - The last N file-change descriptions
    - The last N alignment snapshots for the history chart
    """
    _verify_repo_ownership(db, repo_id, current_user["id"])
    workspaces = _get_workspaces(db, repo_id)

    if not workspaces:
        return []

    results: list[LiveSnapshotResponse] = []

    for ws in workspaces:
        ws_id = ws["id"]

        # Active task
        task_result = (
            db.table("tasks")
            .select("*")
            .eq("workspace_id", ws_id)
            .eq("is_active", True)
            .maybe_single()
            .execute()
        )
        active_task: ActiveTaskOut | None = None
        if task_result.data:
            d = task_result.data
            active_task = ActiveTaskOut(
                id=d["id"],
                task_key=d.get("task_key"),
                title=d.get("title"),
                description=d.get("description"),
                is_active=d.get("is_active", True),
                created_at=str(d.get("created_at", "")),
            )

        # Score history (also gives us the latest)
        history_result = (
            db.table("alignment_snapshots")
            .select("id, workspace_id, score, state, files_changed, computed_at")
            .eq("workspace_id", ws_id)
            .order("computed_at", desc=True)
            .limit(history_limit)
            .execute()
        )
        history_rows = history_result.data or []
        score_history = [AlignmentSnapshotOut(**r) for r in history_rows]
        latest_alignment = score_history[0] if score_history else None

        # Recent file-change descriptions joined to file_changes for file_path
        desc_result = (
            db.table("change_descriptions")
            .select("id, file_change_id, workspace_id, on_task_score, classification, summary, description, created_at, file_changes(file_path)")
            .eq("workspace_id", ws_id)
            .order("created_at", desc=True)
            .limit(descriptions_limit)
            .execute()
        )
        descriptions: list[FileDescriptionOut] = []
        for d in (desc_result.data or []):
            fc = d.pop("file_changes", None) or {}
            file_path = fc.get("file_path") if isinstance(fc, dict) else None
            descriptions.append(FileDescriptionOut(**d, file_path=file_path))

        results.append(
            LiveSnapshotResponse(
                workspace=WorkspaceOut(**ws),
                active_task=active_task,
                latest_alignment=latest_alignment,
                recent_descriptions=descriptions,
                score_history=score_history,
            )
        )

    return results


@router.get("/{repo_id}/alignment", response_model=list[AlignmentSnapshotOut])
async def get_alignment_history(
    repo_id: str,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
    workspace_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> list[AlignmentSnapshotOut]:
    """Return alignment score history across all (or one specific) workspace."""
    _verify_repo_ownership(db, repo_id, current_user["id"])
    workspaces = _get_workspaces(db, repo_id)
    if not workspaces:
        return []

    ws_ids = (
        [workspace_id]
        if workspace_id
        else [ws["id"] for ws in workspaces]
    )

    result = (
        db.table("alignment_snapshots")
        .select("id, workspace_id, score, state, files_changed, computed_at")
        .in_("workspace_id", ws_ids)
        .order("computed_at", desc=True)
        .limit(limit)
        .execute()
    )
    return [AlignmentSnapshotOut(**r) for r in (result.data or [])]


@router.get("/{repo_id}/changes", response_model=list[FileDescriptionOut])
async def get_recent_changes(
    repo_id: str,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
    workspace_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> list[FileDescriptionOut]:
    """Return LLM-generated descriptions of recent uncommitted file changes."""
    _verify_repo_ownership(db, repo_id, current_user["id"])
    workspaces = _get_workspaces(db, repo_id)
    if not workspaces:
        return []

    ws_ids = (
        [workspace_id]
        if workspace_id
        else [ws["id"] for ws in workspaces]
    )

    result = (
        db.table("change_descriptions")
        .select("id, file_change_id, workspace_id, on_task_score, classification, summary, description, created_at, file_changes(file_path)")
        .in_("workspace_id", ws_ids)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    descriptions: list[FileDescriptionOut] = []
    for d in (result.data or []):
        fc = d.pop("file_changes", None) or {}
        file_path = fc.get("file_path") if isinstance(fc, dict) else None
        descriptions.append(FileDescriptionOut(**d, file_path=file_path))
    return descriptions
