"""Bidirectional mapping between canonical Pydantic schemas and SQLAlchemy ORM models.

Maintains strict separation between domain data contracts (ReviewFinding, EvidenceModel)
and persistence entities (Finding, EvidenceItem) while preserving full semantic fidelity.
"""

import uuid

from app.database.models.evidence_item import EvidenceItem
from app.database.models.finding import Finding
from app.schemas.enums import (
    EvidenceType,
    FindingSide,
    IssueType,
    PublishStatus,
    Severity,
    VerificationStatus,
)
from app.schemas.evidence import EvidenceModel
from app.schemas.finding import ReviewFinding


def evidence_to_orm(
    evidence: EvidenceModel,
    review_run_id: uuid.UUID | None = None,
    finding_id: uuid.UUID | None = None,
    evidence_id: uuid.UUID | None = None,
) -> EvidenceItem:
    """Convert a canonical Pydantic EvidenceModel into an ORM EvidenceItem entity.

    Args:
        evidence: Canonical Pydantic evidence instance.
        review_run_id: Parent ReviewRun UUID required by the persistence model.
        finding_id: Parent Finding UUID if attached to a specific finding.
        evidence_id: Optional existing UUID for the evidence record.

    Returns:
        SQLAlchemy EvidenceItem entity.
    """
    effective_run_id = review_run_id or uuid.UUID(int=0)
    return EvidenceItem(
        id=evidence_id or uuid.uuid4(),
        review_run_id=effective_run_id,
        finding_id=finding_id,
        evidence_type=evidence.evidence_type.value,
        file_path=evidence.file_path,
        start_line=evidence.start_line,
        end_line=evidence.end_line,
        content_snippet=evidence.snippet,
        rule_or_cve_id=evidence.rule_or_cve_id,
        corroborating_tool=evidence.corroborating_tool,
        extra_metadata=evidence.metadata,
    )


def orm_to_evidence(orm_evidence: EvidenceItem) -> EvidenceModel:
    """Convert a persistence EvidenceItem entity into a canonical EvidenceModel.

    Args:
        orm_evidence: SQLAlchemy EvidenceItem instance.

    Returns:
        Canonical Pydantic EvidenceModel.
    """
    return EvidenceModel(
        evidence_type=EvidenceType(orm_evidence.evidence_type),
        file_path=orm_evidence.file_path,
        start_line=orm_evidence.start_line,
        end_line=orm_evidence.end_line,
        snippet=orm_evidence.content_snippet,
        rule_or_cve_id=orm_evidence.rule_or_cve_id,
        corroborating_tool=orm_evidence.corroborating_tool,
        metadata=orm_evidence.extra_metadata,
    )


def finding_to_orm(
    finding: ReviewFinding,
    review_run_id: uuid.UUID | None = None,
) -> Finding:
    """Convert a canonical Pydantic ReviewFinding into an ORM Finding entity.

    Preserves candidate origin, verification status, confidence scores,
    suggested patch, critic notes, publication state, and evidence relationships.

    Args:
        finding: Canonical Pydantic ReviewFinding instance.
        review_run_id: Parent ReviewRun UUID required by the database schema.

    Returns:
        SQLAlchemy Finding entity with nested EvidenceItem children.
    """
    effective_run_id = review_run_id or uuid.UUID(int=0)
    orm_finding = Finding(
        id=finding.finding_id,
        review_run_id=effective_run_id,
        agent_name=finding.agent_name,
        issue_type=finding.issue_type.value,
        severity=finding.severity.value,
        file_path=finding.affected_file,
        line_number=finding.line_number,
        side=finding.side.value,
        title=finding.title,
        explanation=finding.explanation,
        recommendation=finding.recommendation,
        suggested_patch=finding.suggested_patch,
        confidence_score=finding.confidence_score,
        raw_confidence=finding.raw_confidence,
        verification_status=finding.verification_status.value,
        rejection_reason=finding.rejection_reason,
        critic_notes=finding.critic_notes,
        github_comment_id=finding.github_comment_id,
        publish_status=finding.publish_status.value,
    )

    # Attach child evidence items with bidirectional foreign key linkage
    orm_finding.evidence_items = [
        evidence_to_orm(
            evidence=ev,
            review_run_id=effective_run_id,
            finding_id=finding.finding_id,
        )
        for ev in finding.evidence
    ]

    return orm_finding


def orm_to_finding(orm_finding: Finding) -> ReviewFinding:
    """Convert a persistence Finding entity into a canonical ReviewFinding.

    Restores all semantic attributes including typed enums, confidence values,
    and associated evidence items.

    Args:
        orm_finding: SQLAlchemy Finding instance.

    Returns:
        Canonical Pydantic ReviewFinding.
    """
    evidence_models: list[EvidenceModel] = []
    if hasattr(orm_finding, "evidence_items") and orm_finding.evidence_items:
        evidence_models = [orm_to_evidence(item) for item in orm_finding.evidence_items]

    return ReviewFinding(
        finding_id=orm_finding.id,
        agent_name=orm_finding.agent_name,
        issue_type=IssueType(orm_finding.issue_type),
        severity=Severity(orm_finding.severity),
        affected_file=orm_finding.file_path,
        line_number=orm_finding.line_number,
        side=FindingSide(orm_finding.side),
        title=orm_finding.title,
        explanation=orm_finding.explanation,
        recommendation=orm_finding.recommendation,
        suggested_patch=orm_finding.suggested_patch,
        confidence_score=orm_finding.confidence_score,
        raw_confidence=orm_finding.raw_confidence,
        verification_status=VerificationStatus(orm_finding.verification_status),
        rejection_reason=orm_finding.rejection_reason,
        critic_notes=orm_finding.critic_notes,
        github_comment_id=orm_finding.github_comment_id,
        publish_status=PublishStatus(orm_finding.publish_status),
        evidence=evidence_models,
    )
