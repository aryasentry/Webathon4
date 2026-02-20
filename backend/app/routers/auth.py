"""
UGIE Auth Router
─────────────────
Handles GitHub OAuth flow, session management, and token health.

Endpoints:
  GET  /auth/github      — Redirect to GitHub OAuth
  GET  /auth/callback    — Handle OAuth callback, create session
  GET  /auth/status      — Token & scope status for current user
  DELETE /auth/disconnect — Revoke token and disconnect GitHub
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

import httpx
from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Response, BackgroundTasks
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from supabase import Client

from app.config import get_settings
from app.database import get_db
from app.schemas.auth import OAuthStateResponse, SessionResponse, TokenStatus, UserSession
from app.services import github_oauth as oauth
from app.services.repo_discovery import discover_and_upsert_repos, process_webhooks_and_backfill
from app.utils.logging import get_logger, new_correlation_id

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentication"])
settings = get_settings()

# In-memory state store — replace with Redis in production
_oauth_states: dict[str, str] = {}


def create_jwt(user_id: str, github_login: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expiry_minutes)
    return jwt.encode(
        {"sub": user_id, "login": github_login, "exp": expire},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def decode_jwt(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc


async def get_current_user(
    db: Annotated[Client, Depends(get_db)],
    authorization: str | None = Header(None),
) -> dict:
    """Dependency — extracts and validates the JWT from Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization[len("Bearer "):]
    payload = decode_jwt(token)
    user_id = payload.get("sub")

    result = db.table("ugie_users").select("*").eq("id", user_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=401, detail="User not found")
    return result.data


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get(
    "/github",
    response_class=RedirectResponse,
    summary="Initiate GitHub OAuth",
)
async def github_authorize() -> RedirectResponse:
    """
    Generates a GitHub OAuth authorization URL with a CSRF state token
    and redirects the user directly to GitHub.
    """
    url, state = oauth.get_authorization_url()
    _oauth_states[state] = new_correlation_id()
    return RedirectResponse(url)


async def _run_webhooks_background(
    user_id: str, 
    access_token: str, 
    encrypted: str, 
    repos: list[dict]
):
    try:
        db = get_supabase_client_direct()
        await process_webhooks_and_backfill(
            db=db,
            user_id=user_id,
            access_token=access_token,
            encrypted_token=encrypted,
            repos=repos,
            webhook_base_url=settings.github_oauth_redirect_uri.rsplit("/", 1)[0],
            webhook_secret=settings.github_webhook_secret,
            depth=settings.backfill_depth,
        )
    except Exception as exc:
        logger.warning("Background webhook registration failed", extra={"error": str(exc)})


@router.get("/callback", summary="GitHub OAuth callback")
async def github_callback(
    background_tasks: BackgroundTasks,
    code: str = Query(...),
    state: str = Query(...),
    db: Client = Depends(get_db),
) -> Response:
    """
    Handles the GitHub OAuth redirect.

    1. Validates CSRF state
    2. Exchanges code for access token
    3. Fetches GitHub user profile
    4. Creates or updates user record with encrypted token
    5. Triggers async repo discovery
    6. Returns JWT session
    """
    cid = new_correlation_id()

    # CSRF guard
    if state not in _oauth_states:
        raise HTTPException(status_code=400, detail="Invalid OAuth state — possible CSRF")
    del _oauth_states[state]

    try:
        # Exchange code for token
        token_data = await oauth.exchange_code_for_token(code)
        access_token: str = token_data["access_token"]
        scopes = [s.strip() for s in token_data.get("scope", "").split(",") if s.strip()]

        # Fetch GitHub user
        gh_user = await oauth.fetch_github_user(access_token)
        encrypted = oauth.encrypt_token(access_token)

        # Upsert user
        user_record = {
            "github_id": gh_user["id"],
            "login": gh_user["login"],
            "email": gh_user.get("email"),
            "avatar_url": gh_user.get("avatar_url"),
            "encrypted_token": encrypted,
            "token_scopes": scopes,
            "token_valid": True,
            "token_checked_at": datetime.now(timezone.utc).isoformat(),
        }
        result = (
            db.table("ugie_users")
            .upsert(user_record, on_conflict="github_id")
            .execute()
        )
        user = result.data[0]
        user_id = user["id"]

        # Fast repo discovery (no webhooks yet)
        repos = await discover_and_upsert_repos(
            db=db,
            user_id=user_id,
            github_id=gh_user["id"],
            access_token=access_token,
        )

        # Trigger webhook setup and backfill in background
        background_tasks.add_task(
            _run_webhooks_background,
            user_id,
            access_token,
            encrypted,
            repos,
        )

        # Resolve any pending GitHub identity links for this user (e.g. from collaborator lists)
        from app.services.collaborator_ingestion import resolve_new_user_identities
        background_tasks.add_task(resolve_new_user_identities, db, user_id, gh_user["id"])

        jwt_token = create_jwt(user_id, gh_user["login"])

        logger.info("OAuth callback complete", extra={"login": gh_user["login"], "cid": cid})

        redirect_url = f"{settings.frontend_url}?token={jwt_token}"
        return RedirectResponse(redirect_url)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("OAuth callback error", extra={"error": str(exc), "cid": cid})
        raise HTTPException(status_code=500, detail=f"OAuth flow failed: {exc}") from exc


@router.get("/status", response_model=TokenStatus, summary="Token health check")
async def token_status(current_user: dict = Depends(get_current_user)) -> TokenStatus:
    """Returns current token validity and granted scopes."""
    encrypted = current_user.get("encrypted_token", "")
    valid, scopes = await oauth.check_token_health(encrypted)

    db = get_supabase_client_direct()
    db.table("ugie_users").update({
        "token_valid": valid,
        "token_scopes": scopes,
        "token_checked_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", current_user["id"]).execute()

    return TokenStatus(
        valid=valid,
        scopes=scopes,
        github_login=current_user["login"],
        checked_at=datetime.now(timezone.utc),
    )


@router.delete("/disconnect", summary="Disconnect GitHub account")
async def disconnect(
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
) -> dict:
    """Clear the stored token and mark account as disconnected."""
    db.table("ugie_users").update({
        "encrypted_token": None,
        "token_valid": False,
        "token_scopes": [],
    }).eq("id", current_user["id"]).execute()

    logger.info("User disconnected GitHub", extra={"user_id": current_user["id"]})
    return {"status": "disconnected"}


@router.get("/me", summary="Get current user profile")
async def get_me(current_user: dict = Depends(get_current_user)) -> dict:
    """Return the currently authenticated user's details."""
    # Omit sensitive keys
    user_safe = {k: v for k, v in current_user.items() if k not in ("encrypted_token",)}
    return {"user": user_safe, "user_id": current_user["id"]}


# Helper to get db without dependency injection (used in non-route context)
def get_supabase_client_direct() -> Client:
    from app.database import get_supabase_client
    return get_supabase_client()
