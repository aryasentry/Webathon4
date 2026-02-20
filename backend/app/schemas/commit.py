"""
Commit schemas.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class CommitOut(BaseModel):
    id: str
    repo_id: str
    sha: str
    message: str
    author_login: Optional[str] = None
    author_email: Optional[str] = None
    authored_at: datetime
    additions: int
    deletions: int
    files_changed: int
    ingested_at: datetime
    source: str  # "backfill" | "webhook"


class CommitListResponse(BaseModel):
    total: int
    commits: list[CommitOut]
