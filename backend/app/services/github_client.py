"""
UGIE GitHub REST Client
────────────────────────
Async, paginated, rate-limit-aware wrapper around the GitHub API v3.

Features:
  - Auto-follows Link: rel="next" pagination
  - Reads X-RateLimit-* headers and backs off when near the limit
  - Structured logging on every call
  - Centralised metric increments
  - Easy to swap for GitHub GraphQL later
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

import httpx

from app import utils
from app.utils.logging import get_logger
from app.utils.metrics import inc, API_CALLS_MADE, RATE_LIMIT_HITS
from app.utils.retry import with_retry

logger = get_logger(__name__)

GITHUB_API_BASE = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"

# Back off when remaining calls drop below this threshold
RATE_LIMIT_SAFE_THRESHOLD = 100


def _build_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }


async def _handle_rate_limit(response: httpx.Response) -> None:
    """Inspect rate-limit headers and sleep if we're near exhaustion."""
    remaining = int(response.headers.get("X-RateLimit-Remaining", "999"))
    reset_at = int(response.headers.get("X-RateLimit-Reset", "0"))

    if remaining < RATE_LIMIT_SAFE_THRESHOLD or response.status_code == 429:
        inc(RATE_LIMIT_HITS)
        import time
        sleep_for = max(reset_at - int(time.time()), 1)
        logger.warning(
            "GitHub rate limit near exhaustion — sleeping",
            extra={"remaining": remaining, "sleep_seconds": sleep_for},
        )
        await asyncio.sleep(sleep_for)


# ── Single-resource fetch ─────────────────────────────────────────────────────

@with_retry(max_attempts=4, exceptions=(httpx.HTTPStatusError, httpx.RequestError))
async def get(
    path: str,
    token: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Fetch a single resource from the GitHub API.

    Args:
        path:   API path (e.g. "/user").
        token:  GitHub OAuth access token.
        params: Optional query parameters.

    Returns:
        Parsed JSON response.
    """
    url = f"{GITHUB_API_BASE}{path}"
    logger.debug("GitHub API GET", extra={"path": path, "params": params})
    inc(API_CALLS_MADE)

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(url, headers=_build_headers(token), params=params)
        await _handle_rate_limit(resp)
        resp.raise_for_status()
        return resp.json()


# ── Paginated list fetch ──────────────────────────────────────────────────────

async def paginate(
    path: str,
    token: str,
    params: dict[str, Any] | None = None,
    per_page: int = 100,
) -> AsyncIterator[list[dict[str, Any]]]:
    """
    Async generator that yields successive pages from a GitHub list endpoint.
    Follows Link: rel="next" headers automatically.

    Args:
        path:     API path (e.g. "/user/repos").
        token:    GitHub OAuth access token.
        params:   Extra query parameters.
        per_page: Items per page (max 100 for GitHub API).

    Yields:
        One page (list of dicts) per iteration.

    Example::
        async for page in paginate("/user/repos", token):
            for repo in page:
                process(repo)
    """
    url = f"{GITHUB_API_BASE}{path}"
    query: dict[str, Any] = {"per_page": per_page, **(params or {})}

    async with httpx.AsyncClient(timeout=30.0) as client:
        while url:
            logger.debug("GitHub API paginate", extra={"url": url, "params": query})
            inc(API_CALLS_MADE)

            resp = await client.get(url, headers=_build_headers(token), params=query)
            await _handle_rate_limit(resp)
            resp.raise_for_status()

            data = resp.json()
            if not isinstance(data, list):
                # Some endpoints wrap data (e.g. /search)
                data = data.get("items", data.get("repositories", [data]))

            yield data

            # Follow Link: rel="next" header
            link_header = resp.headers.get("Link", "")
            next_url = _parse_next_link(link_header)
            url = next_url  # type: ignore[assignment]
            query = {}      # params are already encoded in the next URL


def _parse_next_link(link_header: str) -> str | None:
    """
    Parse GitHub's Link header to extract the rel="next" URL.

    Format: <https://api.github.com/...>; rel="next", <...>; rel="last"
    """
    if not link_header:
        return None

    for part in link_header.split(","):
        segments = [s.strip() for s in part.split(";")]
        if len(segments) == 2 and segments[1] == 'rel="next"':
            return segments[0].strip("<>")
    return None


# ── Convenience collectors ────────────────────────────────────────────────────

async def collect_all(
    path: str,
    token: str,
    params: dict[str, Any] | None = None,
    max_items: int | None = None,
) -> list[dict[str, Any]]:
    """
    Collect all pages into a single list.  Optionally cap at *max_items*.
    """
    results: list[dict[str, Any]] = []
    async for page in paginate(path, token, params):
        results.extend(page)
        if max_items and len(results) >= max_items:
            return results[:max_items]
    return results
