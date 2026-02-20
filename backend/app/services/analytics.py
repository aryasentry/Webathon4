"""
UGIE Analytics Service
───────────────────────
Computes intelligence signals from stored commit data.

Signals:
  - Commit frequency baseline (7d / 30d rolling)
  - Contributor entropy (Shannon entropy)
  - Burst pattern detection (z-score)
  - Dormant branch detection
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from supabase import Client

from app.utils.logging import get_logger

logger = get_logger(__name__)


def compute_commit_frequency(
    db: Client,
    repo_id: str,
    days: int = 7,
) -> float:
    """
    Compute average commits per day over the last *days* days.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()

    result = (
        db.table("ugie_contribution_snapshots")
        .select("commit_count")
        .eq("repo_id", repo_id)
        .gte("snapshot_date", since)
        .execute()
    )

    if not result.data:
        return 0.0

    total = sum(row["commit_count"] for row in result.data)
    return round(total / days, 2)


def compute_contributor_entropy(db: Client, repo_id: str, days: int = 30) -> float:
    """
    Shannon entropy over the commit distribution among contributors.

      H = -Σ p_i * log2(p_i)

    H = 0    → single contributor monopoly
    H = high → healthy distribution

    Returns entropy value (bits).
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    result = (
        db.table("ugie_commits")
        .select("author_login")
        .eq("repo_id", repo_id)
        .gte("authored_at", since)
        .execute()
    )

    if not result.data:
        return 0.0

    counts = Counter(
        row["author_login"] or "unknown" for row in result.data
    )
    total = sum(counts.values())
    entropy = -sum(
        (c / total) * math.log2(c / total)
        for c in counts.values()
        if c > 0
    )
    return round(entropy, 4)


def detect_burst_patterns(
    db: Client,
    repo_id: str,
    days: int = 30,
    z_threshold: float = 2.0,
) -> list[dict[str, Any]]:
    """
    Detect commit burst windows using z-score analysis.

    Any day where commit_count > mean + z_threshold * stddev is a burst.

    Returns:
        List of dicts: {date, commit_count, z_score}
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()

    result = (
        db.table("ugie_contribution_snapshots")
        .select("snapshot_date,commit_count")
        .eq("repo_id", repo_id)
        .gte("snapshot_date", since)
        .order("snapshot_date")
        .execute()
    )

    if not result.data or len(result.data) < 3:
        return []

    counts = [row["commit_count"] for row in result.data]
    mean = sum(counts) / len(counts)
    variance = sum((c - mean) ** 2 for c in counts) / len(counts)
    stddev = math.sqrt(variance) if variance > 0 else 1.0

    bursts = []
    for row in result.data:
        count = row["commit_count"]
        z = (count - mean) / stddev if stddev > 0 else 0.0
        if z >= z_threshold:
            bursts.append({
                "date": row["snapshot_date"],
                "commit_count": count,
                "z_score": round(z, 2),
            })

    return bursts


def get_dormant_days(db: Client, repo_id: str) -> int | None:
    """
    Return the number of days since the last commit, or None if recent (< 1 day).
    """
    result = (
        db.table("ugie_commits")
        .select("authored_at")
        .eq("repo_id", repo_id)
        .order("authored_at", desc=True)
        .limit(1)
        .execute()
    )

    if not result.data:
        return None

    last_ts = datetime.fromisoformat(
        result.data[0]["authored_at"].replace("Z", "+00:00")
    )
    delta = datetime.now(timezone.utc) - last_ts
    return delta.days if delta.days > 0 else None


def get_contributor_rankings(
    db: Client,
    repo_id: str,
    days: int = 30,
) -> list[dict[str, Any]]:
    """
    Return contributors ranked by commit count over the last *days* days.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    result = (
        db.table("ugie_commits")
        .select("author_login,additions,deletions")
        .eq("repo_id", repo_id)
        .gte("authored_at", since)
        .execute()
    )

    if not result.data:
        return []

    stats: dict[str, dict[str, int]] = defaultdict(lambda: {"commits": 0, "additions": 0, "deletions": 0})
    for row in result.data:
        login = row.get("author_login") or "unknown"
        stats[login]["commits"] += 1
        stats[login]["additions"] += row.get("additions", 0)
        stats[login]["deletions"] += row.get("deletions", 0)

    total_commits = sum(v["commits"] for v in stats.values())
    ranked = sorted(stats.items(), key=lambda x: x[1]["commits"], reverse=True)

    return [
        {
            "login": login,
            "commit_count": data["commits"],
            "additions": data["additions"],
            "deletions": data["deletions"],
            "share_pct": round(100 * data["commits"] / total_commits, 1) if total_commits else 0.0,
        }
        for login, data in ranked
    ]


def get_user_summary(db: Client, user_id: str) -> dict[str, Any]:
    """
    High-level summary metrics for a user across all their repos.
    """
    repos_result = (
        db.table("ugie_repositories")
        .select("id")
        .eq("user_id", user_id)
        .execute()
    )
    total_repos = len(repos_result.data) if repos_result.data else 0

    commits_result = (
        db.table("ugie_contribution_snapshots")
        .select("commit_count,snapshot_date")
        .eq("user_id", user_id)
        .execute()
    )

    total_commits = sum(r["commit_count"] for r in (commits_result.data or []))

    since_7d = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
    since_30d = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()

    freq_7d_total = sum(
        r["commit_count"] for r in (commits_result.data or [])
        if r["snapshot_date"] >= since_7d
    )
    freq_30d_total = sum(
        r["commit_count"] for r in (commits_result.data or [])
        if r["snapshot_date"] >= since_30d
    )

    # Active repos in last 7 days
    active_repos_result = (
        db.table("ugie_contribution_snapshots")
        .select("repo_id")
        .eq("user_id", user_id)
        .gte("snapshot_date", since_7d)
        .execute()
    )
    active_repos_7d = len({r["repo_id"] for r in (active_repos_result.data or [])})

    return {
        "user_id": user_id,
        "total_repos": total_repos,
        "total_commits": total_commits,
        "active_repos_7d": active_repos_7d,
        "commit_frequency_7d": round(freq_7d_total / 7, 2),
        "commit_frequency_30d": round(freq_30d_total / 30, 2),
    }
