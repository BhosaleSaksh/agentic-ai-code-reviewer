"""Unit tests for GitHub App authentication and installation token exchange."""

import time
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from app.github.auth import GitHubAppAuthenticator, _normalize_private_key
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
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr


@pytest.fixture(scope="module")
def rsa_test_keys() -> tuple[str, str]:
    """Generate a real in-memory 2048-bit RSA key pair for cryptographic testing."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private_pem, public_pem


@pytest.fixture
def private_pem(rsa_test_keys: tuple[str, str]) -> str:
    return rsa_test_keys[0]


@pytest.fixture
def public_pem(rsa_test_keys: tuple[str, str]) -> str:
    return rsa_test_keys[1]


def test_normalize_private_key(private_pem: str) -> None:
    """Test private key normalization across SecretStr, quotes, and escaped newlines."""
    # 1. Plain string
    assert _normalize_private_key(private_pem) == private_pem.strip()

    # 2. SecretStr
    secret_key = SecretStr(private_pem)
    assert _normalize_private_key(secret_key) == private_pem.strip()

    # 3. Escaped newlines ('\\n')
    escaped = private_pem.replace("\n", "\\n")
    assert _normalize_private_key(escaped) == private_pem.strip()

    # 4. Quoted string
    quoted = f'"{private_pem}"'
    assert _normalize_private_key(quoted) == private_pem.strip()


def test_create_app_jwt_valid(private_pem: str, public_pem: str) -> None:
    """Verify valid RS256 JWT creation with expected claims and expiration."""
    auth = GitHubAppAuthenticator(app_id=123456, private_key=private_pem)
    assert auth.is_configured is True

    jwt_token = auth.create_app_jwt(expiration_seconds=300)
    assert isinstance(jwt_token, str)

    # Decode and verify using public key
    decoded = jwt.decode(jwt_token, public_pem, algorithms=["RS256"])
    assert decoded["iss"] == "123456"
    assert "iat" in decoded
    assert "exp" in decoded

    # Verify iat is ~60s in the past (clock drift compensation)
    now = int(time.time())
    assert abs(decoded["iat"] - (now - 60)) <= 5
    # Verify exp is ~300s from now
    assert abs(decoded["exp"] - (now + 300)) <= 5


def test_create_app_jwt_missing_app_id(
    private_pem: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify error when GitHub App ID is not configured."""
    monkeypatch.setattr("app.core.config.settings.GITHUB_APP_ID", None)
    auth = GitHubAppAuthenticator(app_id=None, private_key=private_pem)
    with pytest.raises(GitHubConfigurationError, match="GITHUB_APP_ID is missing"):
        auth.create_app_jwt()


def test_create_app_jwt_missing_private_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify error when private key is not configured."""
    monkeypatch.setattr("app.core.config.settings.GITHUB_APP_PRIVATE_KEY", None)
    monkeypatch.setattr("app.core.config.settings.GITHUB_PRIVATE_KEY_PATH", None)
    auth = GitHubAppAuthenticator(app_id=123456, private_key=None)
    with pytest.raises(
        GitHubConfigurationError, match="GITHUB_APP_PRIVATE_KEY is missing"
    ):
        auth.create_app_jwt()


def test_create_app_jwt_empty_key() -> None:
    """Verify error when private key is an empty string."""
    auth = GitHubAppAuthenticator(app_id=123456, private_key="   ")
    with pytest.raises(GitHubConfigurationError, match="empty after normalization"):
        auth.create_app_jwt()


def test_create_app_jwt_malformed_key() -> None:
    """Verify error when private key is corrupted/invalid PEM."""
    auth = GitHubAppAuthenticator(app_id=123456, private_key="not-a-valid-pem-key")
    with pytest.raises(
        GitHubAuthenticationError, match="Failed to generate GitHub App JWT"
    ):
        auth.create_app_jwt()


@pytest.mark.asyncio
async def test_get_installation_token_success(private_pem: str) -> None:
    """Verify successful installation access token exchange with mock HTTP response."""
    now = datetime.now(UTC)
    expires_at_dt = now + timedelta(hours=1)
    expires_at_str = expires_at_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/app/installations/998877/access_tokens"
        assert request.headers["Accept"] == "application/vnd.github+json"
        assert request.headers["Authorization"].startswith("Bearer ")
        assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"

        body = {
            "token": "ghs_mockInstallationTokenValue1234567890",
            "expires_at": expires_at_str,
            "permissions": {"pull_requests": "read", "metadata": "read"},
            "repository_selection": "selected",
        }
        return httpx.Response(status_code=201, json=body)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        auth = GitHubAppAuthenticator(
            app_id=123456,
            private_key=private_pem,
            http_client=http_client,
        )

        token = await auth.get_installation_token(998877)
        assert (
            token.token.get_secret_value() == "ghs_mockInstallationTokenValue1234567890"
        )
        assert token.is_expired is False
        assert token.permissions == {"pull_requests": "read", "metadata": "read"}
        assert token.repository_selection == "selected"

        # Test in-memory cache hit: second call should return cached token without transport call
        cached = await auth.get_installation_token(998877)
        assert cached.token.get_secret_value() == token.token.get_secret_value()

        # Clear cache and force refresh
        auth.clear_token_cache()
        refreshed = await auth.get_installation_token(998877, force_refresh=True)
        assert refreshed.token.get_secret_value() == token.token.get_secret_value()


@pytest.mark.asyncio
async def test_get_installation_token_invalid_installation_id(private_pem: str) -> None:
    """Verify error when invalid installation ID (0 or negative) is supplied."""
    auth = GitHubAppAuthenticator(app_id=123456, private_key=private_pem)
    with pytest.raises(
        GitHubConfigurationError, match="Invalid GitHub App installation ID"
    ):
        await auth.get_installation_token(0)
    with pytest.raises(
        GitHubConfigurationError, match="Invalid GitHub App installation ID"
    ):
        await auth.get_installation_token(-5)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "error_class"),
    [
        (401, GitHubAuthenticationError),
        (403, GitHubPermissionError),
        (404, GitHubNotFoundError),
        (429, GitHubRateLimitError),
        (500, GitHubServerError),
        (502, GitHubServerError),
    ],
)
async def test_get_installation_token_http_errors(
    private_pem: str,
    status_code: int,
    error_class: type[Exception],
) -> None:
    """Verify GitHub HTTP error statuses map to appropriate domain exceptions."""

    def mock_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=status_code, json={"message": "Error description"}
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        auth = GitHubAppAuthenticator(
            app_id=123456,
            private_key=private_pem,
            http_client=http_client,
        )
        with pytest.raises(error_class):
            await auth.get_installation_token(12345)


@pytest.mark.asyncio
async def test_get_installation_token_timeout(private_pem: str) -> None:
    """Verify network timeout raises GitHubNetworkError."""

    def mock_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Connection timed out")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        auth = GitHubAppAuthenticator(
            app_id=123456,
            private_key=private_pem,
            http_client=http_client,
        )
        with pytest.raises(GitHubNetworkError, match="timed out"):
            await auth.get_installation_token(12345)


@pytest.mark.asyncio
async def test_get_installation_token_malformed_json(private_pem: str) -> None:
    """Verify 201 response with malformed JSON raises GitHubResponseError."""

    def mock_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=201, content=b"not a valid json string")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        auth = GitHubAppAuthenticator(
            app_id=123456,
            private_key=private_pem,
            http_client=http_client,
        )
        with pytest.raises(GitHubResponseError, match="Malformed response envelope"):
            await auth.get_installation_token(12345)


def test_token_secret_str_masking() -> None:
    """Verify installation token is masked in string and repr formats."""
    from app.schemas.github import GitHubInstallationToken

    token_model = GitHubInstallationToken(
        token=SecretStr("super_secret_github_token_xyz"),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    assert "super_secret_github_token_xyz" not in str(token_model)
    assert "super_secret_github_token_xyz" not in repr(token_model)
    assert "**********" in repr(token_model) or "SecretStr('**********')" in repr(
        token_model
    )
