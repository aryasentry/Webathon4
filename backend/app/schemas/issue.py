from datetime import datetime
from pydantic import BaseModel, ConfigDict
from typing import List


class IssueOut(BaseModel):
    id: str
    repo_id: str
    number: int
    title: str
    state: str
    author_login: str | None = None
    assignee_login: str | None = None
    comments_count: int
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None
    ingested_at: datetime

    model_config = ConfigDict(from_attributes=True)


class IssueListResponse(BaseModel):
    total: int
    issues: List[IssueOut]


class PullRequestOut(BaseModel):
    id: str
    repo_id: str
    number: int
    title: str
    state: str
    author_login: str | None = None
    merged: bool
    additions: int
    deletions: int
    changed_files: int
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None
    merged_at: datetime | None = None
    ingested_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PullRequestListResponse(BaseModel):
    total: int
    pull_requests: List[PullRequestOut]
