"""
Task schemas.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel


class TaskCreate(BaseModel):
    frontend_project_id: str
    repo_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    assignee: Optional[str] = None
    priority: str = "medium"          # low | medium | high | critical
    deadline: Optional[date] = None
    scheduled_date: Optional[date] = None  # calendar day this task is planned for
    tags: list[str] = []
    status: str = "todo"              # todo | in-progress | done
    story_points: int = 1
    source: str = "manual"            # manual | ai


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    assignee: Optional[str] = None
    priority: Optional[str] = None
    deadline: Optional[date] = None
    scheduled_date: Optional[date] = None
    tags: Optional[list[str]] = None
    status: Optional[str] = None
    story_points: Optional[int] = None


class TaskOut(BaseModel):
    id: str
    user_id: Optional[str] = None
    frontend_project_id: str
    repo_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    assignee: Optional[str] = None
    priority: str
    deadline: Optional[date] = None
    scheduled_date: Optional[date] = None
    tags: list[str]
    status: str
    story_points: int
    created_by: Optional[str] = None
    source: str
    created_at: datetime
    updated_at: datetime


class TaskListResponse(BaseModel):
    total: int
    tasks: list[TaskOut]


# ─── AI task-create response ──────────────────────────────────────────────────

class TaskCreateResponse(BaseModel):
    created: bool
    task: Optional[TaskOut] = None
    message: str                       # human-readable confirmation or follow-up question
