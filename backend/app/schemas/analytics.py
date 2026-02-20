"""
Analytics schemas.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class VelocityPoint(BaseModel):
    date: date
    commit_count: int
    additions: int
    deletions: int


class ContributorStat(BaseModel):
    login: str
    commit_count: int
    additions: int
    deletions: int
    share_pct: float  # percent of total commits


class BurstWindow(BaseModel):
    start_date: date
    end_date: date
    commit_count: int
    z_score: float


class AnalyticsSummary(BaseModel):
    user_id: str
    total_repos: int
    total_commits: int
    active_repos_7d: int
    commit_frequency_7d: float  # commits/day over last 7 days
    commit_frequency_30d: float


class VelocityReport(BaseModel):
    repo_id: str
    repo_full_name: str
    velocity_7d: list[VelocityPoint]
    velocity_30d: list[VelocityPoint]
    contributor_entropy: float      # Shannon entropy — 0 = single contributor, higher = more distributed
    burst_windows: list[BurstWindow]
    dormant_days: Optional[int] = None  # days since last commit, None if recent


class ContributorsReport(BaseModel):
    repo_id: str
    repo_full_name: str
    total_commits: int
    contributors: list[ContributorStat]
