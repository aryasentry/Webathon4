"""
UGIE Analytics Router
──────────────────────
Endpoints:
  GET /analytics/summary              — Overall user metrics
  GET /analytics/velocity/{repo_id}   — Velocity + entropy + burst windows
  GET /analytics/contributors/{repo_id} — Contributor rankings
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from supabase import Client

from app.database import get_db
from app.routers.auth import get_current_user
from app.schemas.analytics import (
    AnalyticsSummary,
    BurstWindow,
    ContributorsReport,
    ContributorStat,
    VelocityPoint,
    VelocityReport,
)
from app.services import analytics as svc
from app.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/analytics", tags=["Analytics"])


def _verify_repo(db: Client, repo_id: str, user_id: str) -> dict:
    result = (
        db.table("ugie_repositories")
        .select("id,full_name")
        .eq("id", repo_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Repository not found")
    return result.data


@router.get("/summary", response_model=AnalyticsSummary, summary="User-level analytics summary")
async def get_summary(
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
) -> AnalyticsSummary:
    """
    Returns aggregated metrics across all repositories:
    total repos, total commits, active repos (7d), frequency baselines.
    """
    data = svc.get_user_summary(db, current_user["id"])
    return AnalyticsSummary(**data)


@router.get(
    "/velocity/{repo_id}",
    response_model=VelocityReport,
    summary="Repository velocity report",
)
async def get_velocity(
    repo_id: str,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
) -> VelocityReport:
    """
    Returns commit velocity (7d + 30d), contributor Shannon entropy,
    burst detection windows, and dormancy status.
    """
    repo = _verify_repo(db, repo_id, current_user["id"])

    # Velocity time series from contribution snapshots
    since_30d = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
    since_7d = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()

    snapshots = (
        db.table("ugie_contribution_snapshots")
        .select("snapshot_date,commit_count,additions,deletions")
        .eq("repo_id", repo_id)
        .gte("snapshot_date", since_30d)
        .order("snapshot_date")
        .execute()
    )
    rows = snapshots.data or []
    all_points = [
        VelocityPoint(
            date=r["snapshot_date"],
            commit_count=r["commit_count"],
            additions=r["additions"],
            deletions=r["deletions"],
        )
        for r in rows
    ]
    seven_day_cutoff = since_7d
    velocity_7d = [p for p in all_points if str(p.date) >= seven_day_cutoff]

    # Intelligence signals
    entropy = svc.compute_contributor_entropy(db, repo_id, days=30)
    bursts_raw = svc.detect_burst_patterns(db, repo_id, days=30)
    burst_windows = [
        BurstWindow(
            start_date=b["date"],
            end_date=b["date"],
            commit_count=b["commit_count"],
            z_score=b["z_score"],
        )
        for b in bursts_raw
    ]
    dormant_days = svc.get_dormant_days(db, repo_id)

    return VelocityReport(
        repo_id=repo_id,
        repo_full_name=repo.get("full_name", ""),
        velocity_7d=velocity_7d,
        velocity_30d=all_points,
        contributor_entropy=entropy,
        burst_windows=burst_windows,
        dormant_days=dormant_days,
    )


@router.get(
    "/contributors/{repo_id}",
    response_model=ContributorsReport,
    summary="Contributor analytics",
)
async def get_contributors(
    repo_id: str,
    days: int = Query(30, ge=1, le=365, description="Lookback window in days"),
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
) -> ContributorsReport:
    """
    Returns ranked contributor list with commit count, additions,
    deletions, and percentage share.
    """
    repo = _verify_repo(db, repo_id, current_user["id"])
    rankings = svc.get_contributor_rankings(db, repo_id, days=days)
    total = sum(c["commit_count"] for c in rankings)

    return ContributorsReport(
        repo_id=repo_id,
        repo_full_name=repo.get("full_name", ""),
        total_commits=total,
        contributors=[ContributorStat(**c) for c in rankings],
    )
