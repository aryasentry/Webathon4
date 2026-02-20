"""
UGIE Retry Utilities
──────────────────────
Exponential back-off decorator built on *tenacity*.
Use @with_retry on any function that calls an external service.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, TypeVar

from tenacity import (
    RetryError,
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def with_retry(
    *,
    max_attempts: int = 4,
    min_wait: float = 1.0,
    max_wait: float = 30.0,
    reraise: bool = True,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[F], F]:
    """
    Decorator factory — wraps a function with exponential back-off retry.

    Args:
        max_attempts: Total attempts before giving up (includes first try).
        min_wait:     Minimum seconds between attempts.
        max_wait:     Maximum seconds between attempts.
        reraise:      If True, re-raise the last exception after exhaustion.
        exceptions:   Only retry on these exception types.

    Example::

        @with_retry(max_attempts=5)
        async def call_github_api(...):
            ...
    """
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
        retry=retry_if_exception_type(exceptions),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=reraise,
    )


__all__ = ["with_retry", "RetryError"]
