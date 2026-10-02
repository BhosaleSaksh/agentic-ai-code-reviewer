"""Bug and Logic Analysis Specialist Agent implementation.

Corresponds to Section D.3 and Section 4 of the project architecture:
traces algorithmic invariants, control flow, edge cases, state transitions,
and type safety to discover and ground candidate bug/logic findings.
"""

from __future__ import annotations

from app.agents.base import BaseSpecialistAgent, SpecialistContext
from app.agents.bug_logic_prompt import (
    BUG_LOGIC_SYSTEM_PROMPT,
    PROMPT_VERSION,
    build_bug_logic_user_prompt,
)
from app.schemas.enums import IssueType
from app.services.llm.service import LLMService


class BugLogicAgent(BaseSpecialistAgent):
    """Specialist agent focusing on algorithmic bugs, edge cases, invariants, and regressions."""

    def __init__(self, llm_service: LLMService | None = None) -> None:
        super().__init__(
            name="bug_logic_agent",
            issue_type=IssueType.BUG_LOGIC,
            system_prompt=BUG_LOGIC_SYSTEM_PROMPT,
            prompt_version=PROMPT_VERSION,
            llm_service=llm_service,
        )

    def build_user_prompt(self, context: SpecialistContext) -> str:
        """Construct the algorithmic correctness and logic defect user prompt."""
        return build_bug_logic_user_prompt(context)
