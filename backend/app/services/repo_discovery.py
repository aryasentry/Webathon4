"""
UGIE Repository Discovery Service
───────────────────────────────────
Discovers the COMPLETE repository surface for a user:
  - Owned repositories
  - Collaborated repositories
  - Organization repositories
  - Outside collaborator repositories

For each repo it:
  1. Upserts a `ugie_repositories` record
  2. Registers a GitHub webhook
  3. Enqueues a backfill job via RQ
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from supabase import Client

from app.services import github_client as gh
from app.utils.logging import get_logger
from app.utils.metrics import inc, REPOS_DISCOVERED, BACKFILL_JOBS_QUEUED

logger = get_logger(__name__)

WEBHOOK_EVENTS = ["push", "pull_request", "pull_request_review", "issues", "issue_comment"]


async def discover_and_upsert_repos(
    db: Client,
    user_id: str,
    github_id: int,
    access_token: str,
) -> list[dict[str, Any]]:
    """
    Fast repository graph discovery for the given user.

    Steps:
      1. Fetch /user/repos  (owned + collaborator)
      2. Fetch /user/orgs → /orgs/{org}/repos
      3. Deduplicate by github_id
      4. Upsert each repo into ugie_repositories WITHOUT webhooks

    Args:
        db:               Supabase client.
        user_id:          Internal UGIE user UUID.
        github_id:        User's GitHub numeric ID (for attribution).
        access_token:     Decrypted GitHub token.
    """
    logger.info("Starting full repo discovery", extra={"user_id": user_id})

    seen_github_ids: set[int] = set()
    all_repos: list[dict[str, Any]] = []

    # ── 1. User-owned + collaborator repos ────────────────────────────────────
    user_repo_items = await gh.collect_all(
        "/user/repos",
        access_token,
        params={"type": "all", "sort": "updated"},
    )
    for repo in user_repo_items:
        rid = repo["id"]
        if rid not in seen_github_ids:
            seen_github_ids.add(rid)
            all_repos.append(_normalise_repo(repo, user_id, "owner" if repo.get("owner", {}).get("id") == github_id else "collaborator"))

    # ── 2. Organisation repos ────────────────────────────────────────────────
    try:
        orgs = await gh.collect_all("/user/orgs", access_token)
        for org in orgs:
            org_login = org["login"]
            org_repos = await gh.collect_all(
                f"/orgs/{org_login}/repos",
                access_token,
                params={"type": "all"},
            )
            for repo in org_repos:
                rid = repo["id"]
                if rid not in seen_github_ids:
                    seen_github_ids.add(rid)
                    all_repos.append(_normalise_repo(repo, user_id, "org_member"))
    except Exception as exc:
        logger.warning("Org repo discovery partially failed", extra={"error": str(exc)})

    logger.info(
        "Repo discovery complete",
        extra={"user_id": user_id, "total_repos": len(all_repos)},
    )

    # ── 2.5 Delete stale repositories ────────────────────────────────────────
    active_github_ids = [r["github_id"] for r in all_repos]
    try:
        existing_res = db.table("ugie_repositories").select("github_id").eq("user_id", user_id).execute()
        existing_ids = [row["github_id"] for row in existing_res.data]
        stale_ids = list(set(existing_ids) - set(active_github_ids))
        
        if stale_ids:
            logger.info("Removing stale repositories", extra={"user_id": user_id, "count": len(stale_ids)})
            db.table("ugie_repositories").delete().eq("user_id", user_id).in_("github_id", stale_ids).execute()
    except Exception as exc:
        logger.error("Failed to clean up stale repositories", extra={"error": str(exc)})

    # ── 3. Upsert each repo fast ───────────────────────────────
    upserted: list[dict[str, Any]] = []
    for repo_data in all_repos:
        repo_data["webhook_id"] = None
        repo_data["webhook_active"] = False
        repo_data["last_synced_at"] = datetime.now(timezone.utc).isoformat()
        try:
            # Upsert into Supabase
            result = (
                db.table("ugie_repositories")
                .upsert(repo_data, on_conflict="user_id,github_id")
                .execute()
            )
            if result.data:
                upserted.append(result.data[0])
                inc(REPOS_DISCOVERED)

        except Exception as exc:
            logger.error(
                "Failed to upsert repo",
                extra={"full_name": repo_data.get("full_name"), "error": str(exc)},
            )

    return upserted


async def process_webhooks_and_backfill(
    db: Client,
    user_id: str,
    access_token: str,
    encrypted_token: str,
    repos: list[dict[str, Any]],
    webhook_base_url: str,
    webhook_secret: str,
    depth: int = 200,
) -> None:
    """
    Background worker function that takes the rapidly discovered repos, 
    registers webhooks for them, updates the database, and enqueues backfills.
    """
    import redis as redis_lib
    from rq import Queue as RQ
    from app.config import get_settings
    
    settings = get_settings()
    r = redis_lib.from_url(settings.redis_url)
    q = RQ("default", connection=r)
    
    for repo in repos:
        if not repo.get("id"):
            continue
            
        try:
            # Register webhook
            webhook_id = await _register_webhook(
                access_token,
                repo["owner_login"],
                repo["name"],
                webhook_base_url,
                webhook_secret,
            )
            
            # Update DB with webhook status
            if webhook_id:
                db.table("ugie_repositories").update({
                    "webhook_id": webhook_id,
                    "webhook_active": True,
                }).eq("id", repo["id"]).execute()
                
        except Exception as exc:
            logger.warning("Failed to register webhook in background", extra={"repo_id": repo["id"], "error": str(exc)})
            
    # Enqueue backfills for all
    repo_ids = [r["id"] for r in repos if r.get("id")]
    if repo_ids:
        await enqueue_backfills(q, repo_ids, user_id, encrypted_token, depth)


async def _register_webhook(
    access_token: str,
    owner: str,
    repo: str,
    base_url: str,
    secret: str,
) -> int | None:
    """
    Register a GitHub webhook on the given repo.
    Returns the webhook ID, or None if registration failed (e.g. no admin access).
    """
    try:
        payload = {
            "name": "web",
            "active": True,
            "events": WEBHOOK_EVENTS,
            "config": {
                "url": f"{base_url}/webhooks/github",
                "content_type": "json",
                "secret": secret,
                "insecure_ssl": "0",
            },
        }
        result = await gh.get(
            f"/repos/{owner}/{repo}/hooks",
            access_token,
        )
        # Use POST via httpx since our client only wraps GET
        import httpx
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"https://api.github.com/repos/{owner}/{repo}/hooks",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json=payload,
            )
            if resp.status_code in (200, 201):
                return resp.json().get("id")
            elif resp.status_code == 422:
                # Webhook already exists — find existing
                for hook in (result if isinstance(result, list) else []):
                    if "/webhooks/github" in hook.get("config", {}).get("url", ""):
                        return hook["id"]
            return None
    except Exception as exc:
        logger.warning(
            "Webhook registration failed (likely no admin access)",
            extra={"owner": owner, "repo": repo, "error": str(exc)},
        )
        return None


def _normalise_repo(raw: dict[str, Any], user_id: str, role: str) -> dict[str, Any]:
    """Map a raw GitHub API repo object to our Supabase schema."""
    return {
        "user_id": user_id,
        "github_id": raw["id"],
        "owner_login": raw.get("owner", {}).get("login", ""),
        "name": raw.get("name", ""),
        "full_name": raw.get("full_name", ""),
        "private": raw.get("private", False),
        "archived": raw.get("archived", False),
        "default_branch": raw.get("default_branch", "main"),
        "language": raw.get("language"),
        "stargazers_count": raw.get("stargazers_count", 0),
        "forks_count": raw.get("forks_count", 0),
        "open_issues_count": raw.get("open_issues_count", 0),
        "role": role,
        "webhook_id": None,
        "webhook_active": False,
        "backfill_complete": False,
    }


async def enqueue_backfills(
    rq_queue: Any,
    repo_ids: list[str],
    user_id: str,
    access_token_encrypted: str,
    depth: int = 200,
) -> None:
    """
    Enqueue a backfill job for each repo into the RQ queue.
    """
    from app.workers.backfill_worker import backfill_repo

    for repo_id in repo_ids:
        job = rq_queue.enqueue(
            backfill_repo,
            args=(repo_id, user_id, access_token_encrypted, depth),
            job_timeout=600,
        )
        inc(BACKFILL_JOBS_QUEUED)
        logger.info(
            "Backfill job enqueued",
            extra={"repo_id": repo_id, "job_id": job.id},
        )
