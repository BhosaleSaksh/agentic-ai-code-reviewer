"""Pydantic schemas for application health and readiness probes.

Provides structured response models for system liveness, dependency
connectivity, and service metadata without leaking sensitive credentials.
"""

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    """Schema for basic application liveness health probe."""

    model_config = ConfigDict(frozen=True)

    status: str = Field(
        default="ok",
        description="Overall service liveness status",
        examples=["ok"],
    )
    service: str = Field(
        description="Application or service identifier",
        examples=["Agentic AI Code Reviewer"],
    )
    version: str = Field(
        description="Application semantic version",
        examples=["0.1.0"],
    )
    environment: str = Field(
        description="Runtime environment name",
        examples=["development", "production"],
    )


class DependencyStatus(BaseModel):
    """Health and connectivity status of an infrastructure dependency."""

    model_config = ConfigDict(frozen=True)

    status: str = Field(
        description="Component health status ('healthy' or 'unhealthy')",
        examples=["healthy", "unhealthy"],
    )
    latency_ms: float | None = Field(
        default=None,
        description="Round-trip ping/check latency in milliseconds",
        examples=[1.45],
    )
    details: str | None = Field(
        default=None,
        description="Sanitized non-sensitive diagnostic or error summary",
        examples=["connected", "connection refused"],
    )


class ReadinessResponse(BaseModel):
    """Schema for readiness health probe validating critical dependencies."""

    model_config = ConfigDict(frozen=True)

    status: str = Field(
        description="Overall readiness status ('ready' or 'degraded')",
        examples=["ready", "degraded"],
    )
    database: DependencyStatus = Field(
        description="PostgreSQL persistence engine connectivity status",
    )
    redis: DependencyStatus = Field(
        description="Redis queue and cache store connectivity status",
    )
