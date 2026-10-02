"""Test Adequacy Specialist Agent implementation.

Corresponds to Section D.5 and Section 6 of the project architecture:
evaluates whether PR changes have adequate automated test validation,
identifies untested branches, and assesses regression risks.
"""

from __future__ import annotations

from app.agents.base import BaseSpecialistAgent, SpecialistContext
from app.agents.test_adequacy_prompt import (
    PROMPT_VERSION,
    TEST_ADEQUACY_SYSTEM_PROMPT,
    build_test_adequacy_user_prompt,
)
from app.schemas.enums import IssueType
from app.services.llm.service import LLMService


class TestAdequacyAgent(BaseSpecialistAgent):
    """Specialist agent focusing on test coverage, regression risks, and assertion quality."""

    __test__ = False

    def __init__(self, llm_service: LLMService | None = None) -> None:
        super().__init__(
            name="test_adequacy_agent",
            issue_type=IssueType.TEST_ADEQUACY,
            system_prompt=TEST_ADEQUACY_SYSTEM_PROMPT,
            prompt_version=PROMPT_VERSION,
            llm_service=llm_service,
        )

    def build_user_prompt(self, context: SpecialistContext) -> str:
        """Construct the test adequacy and regression risk user prompt."""
        return build_test_adequacy_user_prompt(context)
