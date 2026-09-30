"""GitHub webhook signature verification using HMAC-SHA256.

Provides timing-safe comparison to validate webhook payload authenticity
without leaking secret credentials or full signatures into logs or exceptions.
"""

import hashlib
import hmac
import logging

from pydantic import SecretStr

logger = logging.getLogger(__name__)


def verify_github_signature(
    raw_payload: bytes,
    signature_header: str | None,
    secret: SecretStr | str | None,
) -> bool:
    """Verify GitHub webhook payload HMAC-SHA256 signature in constant time.

    Args:
        raw_payload: Exact unparsed bytes received from GitHub webhook HTTP request.
        signature_header: Value of X-Hub-Signature-256 header (format: 'sha256=<hex>').
        secret: Configured GitHub webhook secret (SecretStr or str).

    Returns:
        bool: True if signature is valid and authentic, False otherwise.
    """
    if not signature_header:
        logger.warning("Webhook rejection: Missing X-Hub-Signature-256 header.")
        return False

    if not secret:
        logger.error(
            "Webhook rejection: GITHUB_WEBHOOK_SECRET is not configured or empty."
        )
        return False

    # Extract secret bytes safely
    if isinstance(secret, SecretStr):
        secret_bytes = secret.get_secret_value().encode("utf-8")
    elif isinstance(secret, str):
        secret_bytes = secret.encode("utf-8")
    else:
        logger.error("Webhook rejection: Invalid secret type.")
        return False

    if not secret_bytes:
        logger.error("Webhook rejection: GITHUB_WEBHOOK_SECRET is empty.")
        return False

    # Validate header format: must be 'sha256=<hex_digest>'
    prefix = "sha256="
    if not signature_header.startswith(prefix):
        logger.warning(
            "Webhook rejection: Malformed signature header (missing 'sha256=' prefix)."
        )
        return False

    provided_hex = signature_header[len(prefix) :].strip()
    if not provided_hex:
        logger.warning("Webhook rejection: Empty digest in signature header.")
        return False

    # Compute expected HMAC-SHA256 hex digest
    mac = hmac.new(key=secret_bytes, msg=raw_payload, digestmod=hashlib.sha256)
    expected_hex = mac.hexdigest()

    # Constant-time comparison preventing timing attacks
    is_valid = hmac.compare_digest(expected_hex.lower(), provided_hex.lower())
    if not is_valid:
        logger.warning("Webhook rejection: HMAC-SHA256 signature mismatch.")
        return False

    return True
