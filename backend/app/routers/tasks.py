"""
UGIE Tasks Router
──────────────────
Endpoints:
  POST   /tasks/                        — Create a task
  GET    /tasks/?frontend_project_id=…  — List tasks for a project
  GET    /tasks/by-date                 — List tasks for a specific scheduled date
  GET    /tasks/calendar                — Task counts per day in a date range (calendar markers)
  PATCH  /tasks/{task_id}               — Update task (status, title, etc.)
  DELETE /tasks/{task_id}               — Delete a task
"""
from __future__ import annotations

from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from supabase import Client

from app.database import get_db
from app.routers.auth import get_current_user
from app.schemas.task import TaskCreate, TaskListResponse, TaskOut, TaskUpdate
from app.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.post("", response_model=TaskOut, summary="Create a task")
async def create_task(
    body: TaskCreate,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
) -> TaskOut:
    row = {
        "user_id": current_user["id"],
        "frontend_project_id": body.frontend_project_id,
        "repo_id": body.repo_id,
        "title": body.title,
        "description": body.description,
        "assignee": body.assignee,
        "priority": body.priority,
        "deadline": body.deadline.isoformat() if body.deadline else None,
        "scheduled_date": body.scheduled_date.isoformat() if body.scheduled_date else None,
        "tags": body.tags,
        "status": body.status,
        "story_points": body.story_points,
        "created_by": current_user.get("login"),
        "source": body.source,
    }
    import re as _re
    FK_COLUMNS = ("user_id", "repo_id")
    saved = None
    current_row = dict(row)
    last_exc: str = ""
    for _attempt in range(10):
        try:
            result = db.table("ugie_tasks").insert(current_row).execute()
            if result.data:
                saved = result.data[0]
                break
        except Exception as exc:
            exc_str = str(exc)
            last_exc = exc_str
            stripped_col = None
            if "23503" in exc_str:
                for fk_col in FK_COLUMNS:
                    if fk_col in exc_str and fk_col in current_row:
                        stripped_col = fk_col
                        break
            elif "PGRST204" in exc_str:
                m = _re.search(r"find the '([^']+)' column", exc_str)
                if m and m.group(1) in current_row:
                    stripped_col = m.group(1)
            if stripped_col:
                logger.warning(f"ugie_tasks: stripping '{stripped_col}' and retrying")
                current_row = {k: v for k, v in current_row.items() if k != stripped_col}
            else:
                break

    if saved is None:
        raise HTTPException(status_code=500, detail=f"Failed to create task: {last_exc}")
    return TaskOut(**saved)


@router.get("", response_model=TaskListResponse, summary="List tasks for a project")
async def list_tasks(
    frontend_project_id: str = Query(...),
    status: str | None = Query(None),
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
) -> TaskListResponse:
    query = (
        db.table("ugie_tasks")
        .select("*")
        .eq("frontend_project_id", frontend_project_id)
        .or_(f"user_id.eq.{current_user['id']},user_id.is.null")
        .order("created_at", desc=False)
    )
    if status:
        query = query.eq("status", status)

    result = query.execute()
    tasks = [TaskOut(**r) for r in (result.data or [])]
    return TaskListResponse(total=len(tasks), tasks=tasks)


@router.patch("/{task_id}", response_model=TaskOut, summary="Update a task")
async def update_task(
    task_id: str,
    body: TaskUpdate,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
) -> TaskOut:
    # Verify ownership (also accept tasks where user_id was stripped during FK retry)
    existing = (
        db.table("ugie_tasks")
        .select("id")
        .eq("id", task_id)
        .or_(f"user_id.eq.{current_user['id']},user_id.is.null")
        .maybe_single()
        .execute()
    )
    if not existing or not existing.data:
        raise HTTPException(status_code=404, detail="Task not found")

    updates = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if "deadline" in updates and updates["deadline"] is not None:
        updates["deadline"] = updates["deadline"].isoformat()
    if "scheduled_date" in updates and updates["scheduled_date"] is not None:
        updates["scheduled_date"] = updates["scheduled_date"].isoformat()

    result = (
        db.table("ugie_tasks")
        .update(updates)
        .eq("id", task_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=500, detail="Update failed")
    return TaskOut(**result.data[0])


# ─── Calendar helpers ────────────────────────────────────────────────────────

@router.get("/by-date", response_model=TaskListResponse, summary="Tasks for a scheduled date")
async def list_tasks_by_date(
    scheduled_date: str = Query(..., description="YYYY-MM-DD"),
    frontend_project_id: str | None = Query(None),
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
) -> TaskListResponse:
    """Return all tasks for the current user that are scheduled on *scheduled_date*."""
    query = (
        db.table("ugie_tasks")
        .select("*")
        .eq("user_id", current_user["id"])
        .eq("scheduled_date", scheduled_date)
        .order("created_at", desc=False)
    )
    if frontend_project_id:
        query = query.eq("frontend_project_id", frontend_project_id)
    result = query.execute()
    tasks = [TaskOut(**r) for r in (result.data or [])]
    return TaskListResponse(total=len(tasks), tasks=tasks)


@router.get("/calendar", summary="Task counts per day for calendar markers")
async def calendar_task_counts(
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    frontend_project_id: str | None = Query(None),
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
) -> dict:
    """Return a dict mapping date → {total, done} for calendar dot rendering."""
    query = (
        db.table("ugie_tasks")
        .select("scheduled_date,status")
        .eq("user_id", current_user["id"])
        .gte("scheduled_date", start)
        .lte("scheduled_date", end)
    )
    if frontend_project_id:
        query = query.eq("frontend_project_id", frontend_project_id)
    result = query.execute()
    counts: dict[str, dict] = {}
    for row in (result.data or []):
        d = str(row["scheduled_date"])
        if d not in counts:
            counts[d] = {"total": 0, "done": 0}
        counts[d]["total"] += 1
        if row["status"] == "done":
            counts[d]["done"] += 1
    return counts


@router.delete("/{task_id}", summary="Delete a task")
async def delete_task(
    task_id: str,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
) -> dict:
    existing = (
        db.table("ugie_tasks")
        .select("id")
        .eq("id", task_id)
        .or_(f"user_id.eq.{current_user['id']},user_id.is.null")
        .maybe_single()
        .execute()
    )
    if not existing or not existing.data:
        raise HTTPException(status_code=404, detail="Task not found")

    db.table("ugie_tasks").delete().eq("id", task_id).execute()
    return {"deleted": True}
