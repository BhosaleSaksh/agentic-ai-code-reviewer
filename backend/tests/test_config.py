"""Unit tests for application configuration management."""

import pytest
from app.core.config import Settings, get_settings
from pydantic import SecretStr


@pytest.mark.unit
def test_default_settings_values() -> None:
    """Verify expected development defaults."""
    settings = Settings()
    assert settings.PROJECT_NAME == "Agentic AI Code Reviewer"
    assert settings.VERSION == "0.1.0"
    assert settings.ENVIRONMENT == "development"
    assert settings.DEBUG is True
    assert settings.POSTGRES_PORT == 5433
    assert settings.POSTGRES_DB == "agentic_reviewer"
    assert settings.POSTGRES_USER == "postgres"
    assert settings.REDIS_HOST == "localhost"
    assert settings.REDIS_PORT == 6380
    assert settings.REDIS_DB == 0
    assert settings.MIN_VERIFICATION_CONFIDENCE == 0.75
    assert settings.MAX_DIFF_LINES_PER_CHUNK == 400


@pytest.mark.unit
def test_async_database_url_derivation() -> None:
    """Verify proper construction of asyncpg connection string."""
    settings = Settings(
        POSTGRES_HOST="127.0.0.1",
        POSTGRES_PORT=5433,
        POSTGRES_USER="testuser",
        POSTGRES_PASSWORD=SecretStr("testpass"),
        POSTGRES_DB="testdb",
    )
    url = settings.async_database_url
    assert url == "postgresql+asyncpg://testuser:testpass@127.0.0.1:5433/testdb"


@pytest.mark.unit
def test_explicit_database_url_precedence() -> None:
    """Verify explicit DATABASE_URL overrides individual components."""
    settings = Settings(
        DATABASE_URL="postgresql+asyncpg://custom:secret@dbhost:5432/customdb"
    )
    assert (
        settings.async_database_url
        == "postgresql+asyncpg://custom:secret@dbhost:5432/customdb"
    )


@pytest.mark.unit
def test_safe_database_url_masks_password() -> None:
    """Verify safe_database_url masks sensitive credentials."""
    settings = Settings(
        POSTGRES_USER="admin",
        POSTGRES_PASSWORD=SecretStr("SuperSecretPassword!"),
        POSTGRES_HOST="localhost",
        POSTGRES_PORT=5433,
        POSTGRES_DB="appdb",
    )
    safe_url = settings.safe_database_url
    assert "SuperSecretPassword!" not in safe_url
    assert "admin:***@localhost:5433/appdb" in safe_url


@pytest.mark.unit
def test_effective_redis_url_derivation() -> None:
    """Verify proper construction of Redis URL."""
    settings = Settings(
        REDIS_HOST="127.0.0.1",
        REDIS_PORT=6380,
        REDIS_DB=1,
    )
    assert settings.effective_redis_url == "redis://127.0.0.1:6380/1"


@pytest.mark.unit
def test_safe_redis_url_masks_password() -> None:
    """Verify safe_redis_url masks sensitive Redis authentication credentials."""
    settings = Settings(
        REDIS_HOST="localhost",
        REDIS_PORT=6380,
        REDIS_DB=0,
        REDIS_PASSWORD=SecretStr("RedisSecretToken"),
    )
    assert "RedisSecretToken" not in settings.safe_redis_url
    assert "redis://:***@localhost:6380/0" in settings.safe_redis_url


@pytest.mark.unit
def test_get_settings_is_cached() -> None:
    """Verify get_settings returns identical singleton instance."""
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


@pytest.mark.unit
def test_effective_github_private_key_direct() -> None:
    """Verify effective_github_private_key unpacks SecretStr and normalizes escaped newlines."""
    raw_pem = "-----BEGIN PRIVATE KEY-----\\nMIIEvgIBADANBg\\n-----END PRIVATE KEY-----"
    settings = Settings(GITHUB_APP_PRIVATE_KEY=SecretStr(raw_pem))
    resolved = settings.effective_github_private_key
    assert resolved is not None
    assert "\n" in resolved
    assert "\\n" not in resolved
    assert resolved.startswith("-----BEGIN PRIVATE KEY-----")


@pytest.mark.unit
def test_effective_github_private_key_from_file(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Verify effective_github_private_key reads from configured file path."""
    key_file = tmp_path / "app-key.pem"  # type: ignore[operator]
    key_file.write_text(
        "-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----",
        encoding="utf-8",
    )

    settings = Settings(GITHUB_PRIVATE_KEY_PATH=str(key_file))
    resolved = settings.effective_github_private_key
    assert (
        resolved
        == "-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----"
    )


@pytest.mark.unit
def test_is_github_app_configured() -> None:
    """Verify is_github_app_configured requires both GITHUB_APP_ID and private key."""
    s1 = Settings(
        GITHUB_APP_ID=None, GITHUB_APP_PRIVATE_KEY=None, GITHUB_PRIVATE_KEY_PATH=None
    )
    assert s1.is_github_app_configured is False

    s2 = Settings(
        GITHUB_APP_ID=123, GITHUB_APP_PRIVATE_KEY=None, GITHUB_PRIVATE_KEY_PATH=None
    )
    assert s2.is_github_app_configured is False

    s3 = Settings(GITHUB_APP_ID=123, GITHUB_APP_PRIVATE_KEY=SecretStr("mock_key"))
    assert s3.is_github_app_configured is True


@pytest.mark.unit
def test_workspace_settings_defaults() -> None:
    """Verify default workspace settings values."""
    settings = Settings()
    assert settings.REVIEW_WORKSPACE_ROOT is not None
    assert settings.WORKSPACE_COMMAND_TIMEOUT_SECONDS == 60.0
    assert settings.WORKSPACE_MAX_SIZE_BYTES == 500 * 1024 * 1024
    assert settings.WORKSPACE_MIN_DISK_FREE_BYTES == 1024 * 1024 * 1024
    assert settings.WORKSPACE_RETENTION_ON_FAILURE is False
    assert settings.WORKSPACE_ENABLED is True
