"""Security Analysis Specialist Agent implementation.

Corresponds to Section D.2 and Section 3 of the project architecture:
inspects changed code and deterministic static analysis evidence (Semgrep, Bandit, pip-audit)
to discover and ground candidate security findings with OWASP/CWE context.
"""

from __future__ import annotations

from app.agents.base import BaseSpecialistAgent, SpecialistContext
from app.agents.security_prompt import (
    PROMPT_VERSION,
    SECURITY_SYSTEM_PROMPT,
    build_security_user_prompt,
)
from app.schemas.enums import IssueType
from app.services.llm.service import LLMService


class SecurityAgent(BaseSpecialistAgent):
    """Application Security specialist agent focusing on vulnerabilities and secret exposures."""

    def __init__(self, llm_service: LLMService | None = None) -> None:
        super().__init__(
            name="security_agent",
            issue_type=IssueType.SECURITY,
            system_prompt=SECURITY_SYSTEM_PROMPT,
            prompt_version=PROMPT_VERSION,
            llm_service=llm_service,
        )

    def build_user_prompt(self, context: SpecialistContext) -> str:
        """Construct the security-focused user prompt with static tool evidence."""
        return build_security_user_prompt(context)
