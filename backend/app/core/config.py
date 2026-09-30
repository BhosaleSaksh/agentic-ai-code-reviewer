"""Application configuration management using Pydantic Settings.

Provides strongly typed configuration for application, PostgreSQL, Redis,
and future analysis/review subsystems. Loads from environment variables
or an optional .env file with strict typing and secret masking.
"""

import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from arq.connections import RedisSettings
from pydantic import BeforeValidator, Field, SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_cors_origins(v: object) -> list[str]:
    """Parse CORS origins if passed as comma-separated string or list."""
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",") if i.strip()]
    elif isinstance(v, list):
        return [str(i) for i in v]
    return ["http://localhost:3000", "http://localhost:5173"]


class Settings(BaseSettings):
    """Centralized application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- Application Configuration ---
    PROJECT_NAME: str = "Agentic AI Code Reviewer"
    VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "console"
    API_V1_PREFIX: str = "/api/v1"
    SECRET_KEY: SecretStr = SecretStr(
        "change-this-to-a-secure-random-secret-key-min-32-chars"
    )
    BACKEND_CORS_ORIGINS: Annotated[list[str], BeforeValidator(_parse_cors_origins)] = [
        "http://localhost:3000",
        "http://localhost:5173",
    ]

    # --- PostgreSQL Database Configuration ---
    # Default host port 5433 per ADR-0001 (container port 5432 mapped to host 5433)
    POSTGRES_HOST: str = "localhost"
    POSTGRES_SERVER: str | None = None
    POSTGRES_PORT: int = 5433
    POSTGRES_DB: str = "agentic_reviewer"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: SecretStr = SecretStr("postgres")
    DATABASE_URL: str | None = None

    # --- Redis Configuration ---
    # Default host port 6380 (container port 6379 mapped to host 6380 to avoid local collision)
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6380
    REDIS_DB: int = 0
    REDIS_PASSWORD: SecretStr | None = None
    REDIS_URL: str | None = None

    # --- ARQ / Asynchronous Worker Queue Configuration ---
    ARQ_QUEUE_NAME: str = "agentic_review_queue"
    ARQ_JOB_TIMEOUT_SECONDS: int = 600
    ARQ_MAX_JOBS: int = 10
    ARQ_MAX_RETRIES: int = 3
    ARQ_RETRY_DELAY_SECONDS: int = 10
    ARQ_KEEP_RESULT_SECONDS: int = 3600

    # --- GitHub App Integration ---
    GITHUB_APP_ID: int | None = None
    GITHUB_WEBHOOK_SECRET: SecretStr | None = None
    GITHUB_PRIVATE_KEY_PATH: str | None = None
    GITHUB_APP_PRIVATE_KEY: SecretStr | None = None
    GITHUB_APP_INSTALLATION_ID: int | None = None
    GITHUB_API_BASE_URL: str = "https://api.github.com"
    GITHUB_API_TIMEOUT_SECONDS: float = 30.0
    GITHUB_MAX_DIFF_BYTES: int = 5 * 1024 * 1024  # 5 MB safe boundary

    # --- Local Repository Workspace Settings (Phase 1.9) ---
    REVIEW_WORKSPACE_ROOT: Path = Field(
        default_factory=lambda: Path(tempfile.gettempdir()) / "agentic_workspaces"
    )
    WORKSPACE_COMMAND_TIMEOUT_SECONDS: float = 60.0
    WORKSPACE_MAX_SIZE_BYTES: int = 500 * 1024 * 1024  # 500 MB
    WORKSPACE_MIN_DISK_FREE_BYTES: int = 1024 * 1024 * 1024  # 1 GB
    WORKSPACE_RETENTION_ON_FAILURE: bool = False
    WORKSPACE_ENABLED: bool = True

    # --- LLM Provider Settings (Placeholders for Future Checkpoints) ---
    LLM_PROVIDER: str = "openai"
    LLM_TEMPERATURE: float = 0.1
    LLM_MAX_RETRIES: int = 3
    OPENAI_API_KEY: SecretStr | None = None
    OPENAI_MODEL: str = "gpt-4o"
    ANTHROPIC_API_KEY: SecretStr | None = None
    ANTHROPIC_MODEL: str = "claude-3-5-sonnet-20241022"
    GOOGLE_API_KEY: SecretStr | None = None
    GOOGLE_MODEL: str = "gemini-1.5-pro"

    # --- Static Analysis Sandbox Limits ---
    DOCKER_SANDBOX_ENABLED: bool = True
    SEMGREP_TIMEOUT_SECONDS: int = 60
    BANDIT_TIMEOUT_SECONDS: int = 45
    PIP_AUDIT_TIMEOUT_SECONDS: int = 45

    # --- Review & Verification Parameters ---
    MIN_VERIFICATION_CONFIDENCE: float = 0.75
    MAX_REVIEW_FILES: int = 50
    MAX_DIFF_LINES_PER_CHUNK: int = 400

    @computed_field  # type: ignore[prop-decorator]
    @property
    def effective_postgres_host(self) -> str:
        """Resolve database host preferring POSTGRES_HOST over POSTGRES_SERVER."""
        return self.POSTGRES_HOST or self.POSTGRES_SERVER or "localhost"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def async_database_url(self) -> str:
        """Derive the async SQLAlchemy database URL.

        Ensures the asyncpg driver prefix is applied.
        """
        if self.DATABASE_URL:
            url = self.DATABASE_URL
            if url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            elif not url.startswith("postgresql+asyncpg://"):
                url = f"postgresql+asyncpg://{url.split('://', 1)[-1]}"
            return url

        password = self.POSTGRES_PASSWORD.get_secret_value()
        user = self.POSTGRES_USER
        host = self.effective_postgres_host
        port = self.POSTGRES_PORT
        db = self.POSTGRES_DB
        return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def safe_database_url(self) -> str:
        """Return the database URL with the password masked for logging/inspection."""
        raw_url = self.async_database_url
        if "@" in raw_url and ":" in raw_url.split("@")[0]:
            prefix, remainder = raw_url.split("@", 1)
            scheme_user = prefix.rsplit(":", 1)[0]
            return f"{scheme_user}:***@{remainder}"
        return raw_url

    @computed_field  # type: ignore[prop-decorator]
    @property
    def effective_redis_url(self) -> str:
        """Derive the Redis connection URL."""
        if self.REDIS_URL:
            return self.REDIS_URL

        auth = ""
        if self.REDIS_PASSWORD:
            auth = f":{self.REDIS_PASSWORD.get_secret_value()}@"
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def safe_redis_url(self) -> str:
        """Return the Redis connection URL with the password masked for logging/inspection."""
        raw_url = self.effective_redis_url
        if "@" in raw_url and ":" in raw_url.split("@")[0]:
            prefix, remainder = raw_url.split("@", 1)
            scheme = prefix.split("://")[0]
            return f"{scheme}://:***@{remainder}"
        return raw_url

    @property
    def arq_redis_settings(self) -> RedisSettings:
        """Construct ARQ RedisSettings reusing application Redis configuration."""
        return RedisSettings(
            host=self.REDIS_HOST,
            port=self.REDIS_PORT,
            database=self.REDIS_DB,
            password=(
                self.REDIS_PASSWORD.get_secret_value() if self.REDIS_PASSWORD else None
            ),
        )

    @property
    def effective_github_private_key(self) -> str | None:
        """Resolve GitHub App private key PEM string.

        Checks GITHUB_APP_PRIVATE_KEY first (direct PEM string in env/config),
        then reads from GITHUB_PRIVATE_KEY_PATH if configured and file exists.
        Normalizes literal '\\n' sequences if private key was passed in single-line env.
        """
        if self.GITHUB_APP_PRIVATE_KEY:
            raw = self.GITHUB_APP_PRIVATE_KEY.get_secret_value().strip()
            if "\\n" in raw and "\n" not in raw:
                raw = raw.replace("\\n", "\n")
            return raw

        if self.GITHUB_PRIVATE_KEY_PATH:
            path = Path(self.GITHUB_PRIVATE_KEY_PATH)
            if path.is_file():
                return path.read_text(encoding="utf-8").strip()

        return None

    @property
    def is_github_app_configured(self) -> bool:
        """Check whether minimum credentials for GitHub App auth are present."""
        return bool(self.GITHUB_APP_ID and self.effective_github_private_key)


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings singleton."""
    return Settings()


settings: Settings = get_settings()
