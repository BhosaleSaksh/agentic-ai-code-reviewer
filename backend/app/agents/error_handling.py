"""Error Handling Specialist Agent implementation.

Corresponds to Section D.4 and Section 5 of the project architecture:
inspects modified code for swallowed exceptions, resource leaks, missing error traps,
and improper exception propagation to produce grounded candidate findings.
"""

from __future__ import annotations

from app.agents.base import BaseSpecialistAgent, SpecialistContext
from app.agents.error_handling_prompt import (
    ERROR_HANDLING_SYSTEM_PROMPT,
    PROMPT_VERSION,
    build_error_handling_user_prompt,
)
from app.schemas.enums import IssueType
from app.services.llm.service import LLMService


class ErrorHandlingAgent(BaseSpecialistAgent):
    """Specialist agent focusing on exception handling, resource cleanup, and failure resilience."""

    def __init__(self, llm_service: LLMService | None = None) -> None:
        super().__init__(
            name="error_handling_agent",
            issue_type=IssueType.ERROR_HANDLING,
            system_prompt=ERROR_HANDLING_SYSTEM_PROMPT,
            prompt_version=PROMPT_VERSION,
            llm_service=llm_service,
        )

    def build_user_prompt(self, context: SpecialistContext) -> str:
        """Construct the error handling and resilience user prompt."""
        return build_error_handling_user_prompt(context)
