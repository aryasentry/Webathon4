"""
UGIE GitHub OAuth Service
──────────────────────────
Handles:
  - Building the GitHub Authorization URL
  - Exchanging the OAuth code for an access token
  - Fernet-based token encryption / decryption
  - Token scope verification (prevents permission drift)
  - Background token health checks
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Any

import httpx
from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings
from app.utils.logging import get_logger
from app.utils.retry import with_retry

logger = get_logger(__name__)
settings = get_settings()

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_BASE = "https://api.github.com"

# ── Fernet cipher (cached) ────────────────────────────────────────────────────

def _get_fernet() -> Fernet:
    return Fernet(settings.token_encryption_key.encode())


# ── Token vault ───────────────────────────────────────────────────────────────

def encrypt_token(plaintext_token: str) -> str:
    """Encrypt a GitHub PAT / OAuth token for storage."""
    return _get_fernet().encrypt(plaintext_token.encode()).decode()


def decrypt_token(encrypted_token: str) -> str:
    """Decrypt a stored token. Raises ValueError on tamper detection."""
    try:
        return _get_fernet().decrypt(encrypted_token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Token decryption failed — possible tampering") from exc


# ── OAuth flow ────────────────────────────────────────────────────────────────

def get_authorization_url() -> tuple[str, str]:
    """
    Build and return the GitHub OAuth authorization URL along with the
    CSRF state token.

    Returns:
        (authorization_url, state)
    """
    state = secrets.token_urlsafe(32)
    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": settings.github_oauth_redirect_uri,
        "scope": settings.github_oauth_scopes,
        "state": state,
        "allow_signup": "true",
    }
    param_str = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{GITHUB_AUTHORIZE_URL}?{param_str}"
    logger.info("OAuth authorization URL generated", extra={"state": state})
    return url, state


@with_retry(max_attempts=3)
async def exchange_code_for_token(code: str) -> dict[str, Any]:
    """
    Exchange the one-time OAuth code for an access token.

    Returns:
        Dict with at minimum: access_token, token_type, scope
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            GITHUB_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
                "redirect_uri": settings.github_oauth_redirect_uri,
            },
        )
        response.raise_for_status()
        data = response.json()

    if "error" in data:
        raise ValueError(f"GitHub OAuth error: {data.get('error_description', data['error'])}")

    logger.info("OAuth code exchanged successfully")
    return data


@with_retry(max_attempts=2)
async def fetch_github_user(access_token: str) -> dict[str, Any]:
    """
    Fetch authenticated user profile from GitHub API.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{GITHUB_API_BASE}/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def verify_token_scopes(access_token: str) -> list[str]:
    """
    Check which scopes the token actually has by inspecting the
    X-OAuth-Scopes response header.

    Returns:
        List of granted scope strings.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{GITHUB_API_BASE}/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        resp.raise_for_status()
        scopes_header = resp.headers.get("X-OAuth-Scopes", "")
        scopes = [s.strip() for s in scopes_header.split(",") if s.strip()]
        logger.info("Token scopes verified", extra={"scopes": scopes})
        return scopes


async def check_token_health(encrypted_token: str) -> tuple[bool, list[str]]:
    """
    Decrypt and probe a stored token.

    Returns:
        (is_valid, scopes_list)
    """
    try:
        token = decrypt_token(encrypted_token)
        scopes = await verify_token_scopes(token)
        return True, scopes
    except Exception as exc:  # noqa: BLE001
        logger.warning("Token health check failed", extra={"error": str(exc)})
        return False, []
