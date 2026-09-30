"""GitHub App authentication service for JWT creation and installation token exchange.

Implements short-lived RS256 JWT generation with strict claims validation and exchanges
JWTs for ephemeral GitHub App installation access tokens without persisting secrets.
"""

import logging
import time
from datetime import UTC, datetime
from typing import Any

import httpx
import jwt
from pydantic import SecretStr

from app.core.config import get_settings
from app.github.errors import (
    GitHubAuthenticationError,
    GitHubConfigurationError,
    GitHubNetworkError,
    GitHubNotFoundError,
    GitHubPermissionError,
    GitHubRateLimitError,
    GitHubResponseError,
    GitHubServerError,
)
from app.schemas.github import GitHubInstallationToken

logger = logging.getLogger(__name__)


def _normalize_private_key(raw_key: str | SecretStr) -> str:
    """Normalize multiline RSA PEM private key string.

    Handles SecretStr unpacking, removes wrapping quotes, and normalizes
    escaped newlines ('\\n') commonly introduced by environment variables.
    """
    if isinstance(raw_key, SecretStr):
        key_str = raw_key.get_secret_value()
    else:
        key_str = str(raw_key)

    key_str = key_str.strip()
    if (key_str.startswith('"') and key_str.endswith('"')) or (
        key_str.startswith("'") and key_str.endswith("'")
    ):
        key_str = key_str[1:-1]

    if "\\n" in key_str and "\n" not in key_str:
        key_str = key_str.replace("\\n", "\n")

    return key_str.strip()


class GitHubAppAuthenticator:
    """Authenticates as a GitHub App using an RSA private key and exchanges JWTs for tokens."""

    def __init__(
        self,
        app_id: int | str | None = None,
        private_key: str | SecretStr | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize GitHub App authenticator with credentials or application settings."""
        settings = get_settings()
        self._app_id = app_id if app_id is not None else settings.GITHUB_APP_ID
        self._private_key = (
            private_key
            if private_key is not None
            else settings.effective_github_private_key
        )
        self._base_url = (
            base_url.rstrip("/")
            if base_url
            else settings.GITHUB_API_BASE_URL.rstrip("/")
        )
        self._timeout = (
            timeout if timeout is not None else settings.GITHUB_API_TIMEOUT_SECONDS
        )
        self._http_client = http_client
        self._token_cache: dict[int, GitHubInstallationToken] = {}

    @property
    def is_configured(self) -> bool:
        """Return True if both App ID and private key are available."""
        return bool(self._app_id and self._private_key)

    def clear_token_cache(self) -> None:
        """Clear all in-memory cached installation tokens."""
        self._token_cache.clear()

    def create_app_jwt(self, expiration_seconds: int = 540) -> str:
        """Create a signed RS256 JWT for GitHub App authentication.

        Args:
            expiration_seconds: JWT lifetime in seconds (default 540s / 9m; max 600s).

        Returns:
            str: RS256-signed JWT string.

        Raises:
            GitHubConfigurationError: If App ID or private key is missing.
            GitHubAuthenticationError: If private key is malformed or signing fails.
        """
        if not self._app_id:
            raise GitHubConfigurationError(
                "GitHub App ID is not configured (GITHUB_APP_ID is missing)."
            )
        if not self._private_key:
            raise GitHubConfigurationError(
                "GitHub App private key is not configured (GITHUB_APP_PRIVATE_KEY is missing)."
            )

        key_pem = _normalize_private_key(self._private_key)
        if not key_pem:
            raise GitHubConfigurationError(
                "GitHub App private key is empty after normalization."
            )

        now = int(time.time())
        # 60s clock drift tolerance per GitHub documentation
        issued_at = now - 60
        clamped_exp_seconds = min(max(expiration_seconds, 60), 600)
        expires_at = now + clamped_exp_seconds

        payload = {
            "iat": issued_at,
            "exp": expires_at,
            "iss": str(self._app_id),
        }

        try:
            token = jwt.encode(payload, key_pem, algorithm="RS256")
            return token
        except (jwt.PyJWTError, ValueError, TypeError) as exc:
            logger.error("Failed to sign GitHub App JWT: %s", type(exc).__name__)
            raise GitHubAuthenticationError(
                f"Failed to generate GitHub App JWT: {type(exc).__name__}"
            ) from exc

    async def get_installation_token(
        self,
        installation_id: int,
        force_refresh: bool = False,
    ) -> GitHubInstallationToken:
        """Exchange GitHub App JWT for a scoped installation access token.

        Args:
            installation_id: GitHub App installation ID.
            force_refresh: If True, bypass in-memory token cache.

        Returns:
            GitHubInstallationToken: Active installation access token contract.

        Raises:
            GitHubConfigurationError: If installation ID is invalid.
            GitHubAuthenticationError: If JWT is rejected (401).
            GitHubPermissionError: If installation lacks access (403).
            GitHubNotFoundError: If installation ID is not found (404).
            GitHubRateLimitError: If rate limit is hit (429).
            GitHubServerError: If GitHub API returns 5xx.
            GitHubNetworkError: If HTTP request fails or times out.
            GitHubResponseError: If response payload is malformed.
        """
        if not installation_id or installation_id <= 0:
            raise GitHubConfigurationError(
                f"Invalid GitHub App installation ID: {installation_id}"
            )

        # 1. Check in-memory cache if not forcing refresh
        if not force_refresh:
            cached_token = self._token_cache.get(installation_id)
            if cached_token and not cached_token.is_expired:
                return cached_token

        # 2. Generate short-lived App JWT
        app_jwt = self.create_app_jwt()

        # 3. Call GitHub installation access tokens endpoint
        url = f"{self._base_url}/app/installations/{installation_id}/access_tokens"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {app_jwt}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "agentic-ai-code-reviewer",
        }

        should_close_client = False
        client = self._http_client
        if client is None:
            client = httpx.AsyncClient(timeout=self._timeout)
            should_close_client = True

        try:
            response = await client.post(url, headers=headers)
        except httpx.TimeoutException as exc:
            logger.error(
                "GitHub installation token request timed out for installation_id=%d",
                installation_id,
            )
            raise GitHubNetworkError(
                f"GitHub installation token request timed out for installation_id={installation_id}"
            ) from exc
        except httpx.RequestError as exc:
            logger.error(
                "GitHub installation token network error for installation_id=%d: %s",
                installation_id,
                type(exc).__name__,
            )
            raise GitHubNetworkError(
                f"GitHub installation token network connection failed: {type(exc).__name__}"
            ) from exc
        finally:
            if should_close_client:
                await client.aclose()

        # 4. Handle HTTP response status
        if response.status_code == 201:
            try:
                data: dict[str, Any] = response.json()
                raw_token = data["token"]
                expires_at_str = data["expires_at"]
                # Parse ISO timestamp (e.g. '2026-09-30T18:00:00Z')
                if expires_at_str.endswith("Z"):
                    expires_at_str = expires_at_str[:-1] + "+00:00"
                expires_at = datetime.fromisoformat(expires_at_str)
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=UTC)

                token_model = GitHubInstallationToken(
                    token=SecretStr(raw_token),
                    expires_at=expires_at,
                    permissions=data.get("permissions", {}),
                    repository_selection=data.get("repository_selection"),
                )
                self._token_cache[installation_id] = token_model
                logger.info(
                    "Obtained GitHub installation access token for installation_id=%d",
                    installation_id,
                )
                return token_model
            except Exception as exc:
                logger.error(
                    "Malformed response from GitHub installation access token endpoint: %s",
                    type(exc).__name__,
                )
                raise GitHubResponseError(
                    "Malformed response envelope received for installation token"
                ) from exc

        if response.status_code == 401:
            logger.error("GitHub rejected App JWT authentication (HTTP 401)")
            raise GitHubAuthenticationError(
                "GitHub App authentication failed: invalid JWT or private key"
            )

        if response.status_code == 403:
            logger.error(
                "GitHub returned HTTP 403 Forbidden for installation_id=%d",
                installation_id,
            )
            raise GitHubPermissionError(
                f"GitHub installation permission denied for installation_id={installation_id}"
            )

        if response.status_code == 404:
            logger.error(
                "GitHub installation_id=%d not found (HTTP 404)", installation_id
            )
            raise GitHubNotFoundError(
                f"GitHub installation ID {installation_id} was not found"
            )

        if response.status_code == 429:
            logger.warning("GitHub API rate limit hit during token exchange (HTTP 429)")
            raise GitHubRateLimitError(
                "GitHub API rate limit exceeded during token exchange"
            )

        if response.status_code >= 500:
            logger.error(
                "GitHub server error during token exchange (HTTP %d)",
                response.status_code,
            )
            raise GitHubServerError(
                f"GitHub server error during token exchange: HTTP {response.status_code}",
                status_code=response.status_code,
            )

        logger.error(
            "Unexpected HTTP %d from GitHub token endpoint for installation_id=%d",
            response.status_code,
            installation_id,
        )
        raise GitHubResponseError(
            f"Unexpected HTTP {response.status_code} during token exchange"
        )
