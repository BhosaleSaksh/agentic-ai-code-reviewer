"""Evidence Grounding Engine package.

Provides deterministic validation, git diff line resolution, static analysis correlation,
and structured verification context assembly for the Critic Agent.
"""

from app.services.evidence.diff_resolver import DiffEvidenceResolver
from app.services.evidence.grounding_service import EvidenceGroundingService
from app.services.evidence.static_matcher import StaticEvidenceMatcher
from app.services.evidence.validator import FindingEvidenceValidator

__all__ = [
    "EvidenceGroundingService",
    "DiffEvidenceResolver",
    "StaticEvidenceMatcher",
    "FindingEvidenceValidator",
]
