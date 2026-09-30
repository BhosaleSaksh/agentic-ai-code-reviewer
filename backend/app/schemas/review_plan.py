"""ReviewPlan schema representing the planning-stage output.

Corresponds to FR-03, Section B.1, and Section G of the project architecture:
scoping PR changes, selecting active specialist agents, determining
large PR chunking strategies, and setting focus directives.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReviewPlan(BaseModel):
    """Canonical data contract for the PR review plan produced by the Planner Agent.

    Determines review scope, which specialist agents execute, whether
    semantic chunking is required, and focus directives based on PR triage.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    review_scope: str = Field(
        default="FULL",
        description="Overall scope of the review: FULL, FOCUSED, SECURITY_ONLY, TRIVIAL, etc.",
    )
    active_agents: list[str] = Field(
        default_factory=list,
        description="List of specialist agent identifiers activated for this PR",
    )
    focus_areas: list[str] = Field(
        default_factory=list,
        description="Directives and focus areas (e.g. 'auth', 'database migrations', 'input validation')",
    )
    target_files: list[str] = Field(
        default_factory=list,
        description="Subset of repository files in scope for review",
    )
    is_large_pr: bool = Field(
        default=False,
        description="Flag indicating whether total lines changed exceed threshold (>400 LOC)",
    )
    chunking_strategy: str | None = Field(
        None,
        description="Decomposition strategy if PR is large: NONE, FILE_MODULE, SEMANTIC_AST",
    )
    file_chunks: list[list[str]] = Field(
        default_factory=list,
        description="Grouped target files partitioned for parallel specialist fan-out",
    )
    reasoning: str | None = Field(
        None,
        description="Planner explanation justifying agent selection and triage strategy",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional planner metadata, e.g. token counts, file change breakdown",
    )

    @field_validator("review_scope")
    @classmethod
    def validate_review_scope(cls, v: str) -> str:
        """Ensure review scope is non-empty."""
        cleaned = v.strip().upper()
        if not cleaned:
            raise ValueError("review_scope cannot be blank")
        return cleaned

    @field_validator("active_agents", "focus_areas", "target_files")
    @classmethod
    def strip_string_lists(cls, v: list[str]) -> list[str]:
        """Strip whitespace and filter empty items."""
        return [item.strip() for item in v if item and item.strip()]
