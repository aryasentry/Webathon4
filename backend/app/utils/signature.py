"""
UGIE Webhook Signature Verification
─────────────────────────────────────
GitHub signs every webhook payload with HMAC-SHA256 using the shared
webhook secret.  We verify this before processing any event.

https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries
"""

from __future__ import annotations

import hashlib
import hmac


def verify_github_signature(
    payload_bytes: bytes,
    secret: str,
    signature_header: str | None,
) -> bool:
    """
    Return True if *signature_header* matches the expected HMAC-SHA256
    of *payload_bytes* signed with *secret*.

    Always uses ``hmac.compare_digest`` to prevent timing attacks.

    Args:
        payload_bytes:    Raw request body bytes.
        secret:           The webhook secret configured in GitHub.
        signature_header: Value of the ``X-Hub-Signature-256`` request header.

    Returns:
        True on valid signature, False on any mismatch or malformed header.
    """
    if not signature_header:
        return False

    if not signature_header.startswith("sha256="):
        return False

    expected = hmac.new(
        key=secret.encode("utf-8"),
        msg=payload_bytes,
        digestmod=hashlib.sha256,
    ).hexdigest()

    provided = signature_header[len("sha256="):]

    return hmac.compare_digest(expected, provided)
