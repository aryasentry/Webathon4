"""
Repository schemas.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class RepositoryOut(BaseModel):
    id: str
    github_id: int
    owner_login: str
    name: str
    full_name: str
    private: bool
    archived: bool
    default_branch: str
    language: Optional[str] = None
    stargazers_count: int
    forks_count: int
    open_issues_count: int
    role: str                  # owner | collaborator | org_member | outside_collaborator
    webhook_active: bool
    last_synced_at: Optional[datetime] = None
    backfill_cursor: Optional[str] = None


class RepositoryListResponse(BaseModel):
    total: int
    repositories: list[RepositoryOut]


class RescanResponse(BaseModel):
    repo_id: str
    job_id: str
    status: str = "queued"
