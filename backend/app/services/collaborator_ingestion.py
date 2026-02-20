"""
UGIE Collaborator Ingestion Service
─────────────────────────────────────
Fetches GitHub collaborators for a repository, upserts them into the
identity registry, and resolves which ones are already UGIE site users.

GitHub endpoint: GET /repos/{owner}/{repo}/collaborators
Docs: https://docs.github.com/en/rest/collaborators/collaborators
"""

from __future__ import annotations

import logging
from typing import Any

from supabase import Client

from app.services import github_client

logger = logging.getLogger(__name__)


async def ingest_collaborators(
    db: Client,
    repo_id: str,
    owner_login: str,
    repo_name: str,
    access_token: str,
) -> list[dict[str, Any]]:
    """
    Fetch all collaborators for a GitHub repo and persist them into:
      - ugie_github_identities  (canonical GitHub user registry)
      - ugie_repo_collaborators (links identity → repo with permission)

    Returns the enriched list of collaborator records (including site_user_id if resolved).
    """
    path = f"/repos/{owner_login}/{repo_name}/collaborators"
    raw_collaborators: list[dict] = []

    try:
        raw_collaborators = await github_client.collect_all(
            path=path,
            token=access_token,
            params={"affiliation": "all"},
        )
    except Exception as exc:
        logger.warning(
            "Failed to fetch collaborators from GitHub — may lack admin access",
            extra={"repo": f"{owner_login}/{repo_name}", "error": str(exc)},
        )
        # Fall back to empty list — the endpoint returns 403 for repos you don't own
        raw_collaborators = []

    enriched: list[dict[str, Any]] = []

    for gh_user in raw_collaborators:
        login: str = gh_user.get("login", "")
        github_id: int | None = gh_user.get("id")
        avatar_url: str | None = gh_user.get("avatar_url")
        
        # Extract permission level from GitHub response
        permissions: dict = gh_user.get("permissions", {})
        if permissions.get("admin"):
            permission = "admin"
        elif permissions.get("maintain"):
            permission = "maintain"
        elif permissions.get("push"):
            permission = "write"
        elif permissions.get("triage"):
            permission = "triage"
        else:
            permission = "read"

        role_name: str | None = gh_user.get("role_name")

        if not login:
            continue

        # ── Step 1: Upsert into ugie_github_identities ──────────────────────
        identity_record = {
            "github_login": login,
            "github_id": github_id,
            "avatar_url": avatar_url,
            "last_seen_at": "NOW()",
        }

        identity_res = (
            db.table("ugie_github_identities")
            .upsert(identity_record, on_conflict="github_login")
            .execute()
        )

        identity = identity_res.data[0] if identity_res.data else {}
        identity_id: str | None = identity.get("id")

        # ── Step 2: Auto-resolve site_user_id if not yet linked ─────────────
        site_user_id: str | None = identity.get("site_user_id")
        if not site_user_id and github_id:
            # Check if this GitHub user has signed into UGIE
            user_res = (
                db.table("ugie_users")
                .select("id")
                .eq("github_id", github_id)
                .limit(1)
                .execute()
            )
            if user_res.data:
                site_user_id = user_res.data[0]["id"]
                # Persist the resolved link
                db.table("ugie_github_identities").update({
                    "site_user_id": site_user_id,
                    "resolved_at": "NOW()",
                }).eq("id", identity_id).execute()

        # ── Step 3: Upsert into ugie_repo_collaborators ──────────────────────
        if identity_id:
            collab_record = {
                "repo_id": repo_id,
                "github_identity_id": identity_id,
                "permission": permission,
                "role_name": role_name,
                "fetched_at": "NOW()",
            }
            db.table("ugie_repo_collaborators").upsert(
                collab_record,
                on_conflict="repo_id,github_identity_id",
            ).execute()

        enriched.append({
            "login": login,
            "github_id": github_id,
            "avatar_url": avatar_url,
            "permission": permission,
            "role_name": role_name,
            "identity_id": identity_id,
            "site_user_id": site_user_id,
            "is_site_user": bool(site_user_id),
        })

    logger.info(
        "Collaborator ingestion complete",
        extra={"repo": f"{owner_login}/{repo_name}", "count": len(enriched)},
    )
    return enriched


async def resolve_new_user_identities(db: Client, user_id: str, github_id: int) -> None:
    """
    Called when a new user registers/logs in. Links their UGIE user account to
    any existing ugie_github_identities rows that match their GitHub ID.
    This ensures consistency — any past commits/collaborator entries get linked.
    """
    try:
        unresolved = (
            db.table("ugie_github_identities")
            .select("id")
            .eq("github_id", github_id)
            .is_("site_user_id", "null")
            .execute()
        )
        if unresolved.data:
            ids_to_update = [r["id"] for r in unresolved.data]
            for identity_id in ids_to_update:
                db.table("ugie_github_identities").update({
                    "site_user_id": user_id,
                    "resolved_at": "NOW()",
                }).eq("id", identity_id).execute()

            logger.info(
                "Resolved GitHub identity links for new site user",
                extra={"user_id": user_id, "identities_linked": len(ids_to_update)},
            )
    except Exception as exc:
        logger.warning("Identity resolution failed", extra={"error": str(exc)})
