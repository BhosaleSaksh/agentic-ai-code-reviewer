"""Unit tests for EvidencePersistenceService."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.database.models.review_run import ReviewRun
from app.schemas.enums import EvidenceType
from app.schemas.evidence import EvidenceModel
from app.services.evidence_persistence_service import (
    CommitMismatchError,
    EvidencePersistenceError,
    EvidencePersistenceService,
    ReviewRunNotFoundError,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def sample_review_run() -> ReviewRun:
    run = MagicMock(spec=ReviewRun)
    run.id = uuid.uuid4()
    run.commit_sha = "a" * 40
    return run


@pytest.fixture
def sample_evidence_items() -> list[EvidenceModel]:
    return [
        EvidenceModel(
            evidence_type=EvidenceType.STATIC_ANALYSIS,
            file_path="src/main.py",
            start_line=10,
            end_line=12,
            snippet="eval(user_code)",
            rule_or_cve_id="bandit.B307",
            corroborating_tool="bandit",
            metadata={"severity": "HIGH", "commit_sha": "a" * 40},
        ),
        EvidenceModel(
            evidence_type=EvidenceType.DEPENDENCY,
            file_path="requirements.txt",
            start_line=2,
            end_line=2,
            snippet="Vulnerable dependency: flask==0.12 (CVE-2019-1010083)",
            rule_or_cve_id="CVE-2019-1010083",
            corroborating_tool="pip-audit",
            metadata={"package": "flask", "commit_sha": "a" * 40},
        ),
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persist_evidence_batch_success(
    sample_review_run: ReviewRun,
    sample_evidence_items: list[EvidenceModel],
) -> None:
    service = EvidencePersistenceService()
    mock_session = AsyncMock(spec=AsyncSession)

    # Mock execute for review_run lookup
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = sample_review_run
    mock_session.execute.return_value = mock_result

    persisted = await service.persist_evidence_batch(
        session=mock_session,
        review_run_id=sample_review_run.id,
        expected_commit_sha="a" * 40,
        evidence_items=sample_evidence_items,
    )

    assert len(persisted) == 2
    assert mock_session.add.call_count == 2
    assert mock_session.flush.call_count == 1

    item1 = persisted[0]
    assert item1.review_run_id == sample_review_run.id
    assert item1.evidence_type == EvidenceType.STATIC_ANALYSIS.value
    assert item1.file_path == "src/main.py"
    assert item1.rule_or_cve_id == "bandit.B307"
    assert item1.corroborating_tool == "bandit"

    item2 = persisted[1]
    assert item2.evidence_type == EvidenceType.DEPENDENCY.value
    assert item2.file_path == "requirements.txt"
    assert item2.rule_or_cve_id == "CVE-2019-1010083"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persist_evidence_empty_batch(
    sample_review_run: ReviewRun,
) -> None:
    service = EvidencePersistenceService()
    mock_session = AsyncMock(spec=AsyncSession)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = sample_review_run
    mock_session.execute.return_value = mock_result

    persisted = await service.persist_evidence_batch(
        session=mock_session,
        review_run_id=sample_review_run.id,
        expected_commit_sha="a" * 40,
        evidence_items=[],
    )

    assert persisted == []
    assert mock_session.add.call_count == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persist_evidence_review_run_not_found() -> None:
    service = EvidencePersistenceService()
    mock_session = AsyncMock(spec=AsyncSession)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    with pytest.raises(ReviewRunNotFoundError):
        await service.persist_evidence_batch(
            session=mock_session,
            review_run_id=uuid.uuid4(),
            expected_commit_sha="a" * 40,
            evidence_items=[],
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persist_evidence_commit_mismatch(
    sample_review_run: ReviewRun,
) -> None:
    service = EvidencePersistenceService()
    mock_session = AsyncMock(spec=AsyncSession)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = sample_review_run
    mock_session.execute.return_value = mock_result

    # Expected commit is different from sample_review_run.commit_sha ("a"*40)
    with pytest.raises(CommitMismatchError):
        await service.persist_evidence_batch(
            session=mock_session,
            review_run_id=sample_review_run.id,
            expected_commit_sha="b" * 40,
            evidence_items=[],
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persist_evidence_db_error_triggers_rollback(
    sample_review_run: ReviewRun,
    sample_evidence_items: list[EvidenceModel],
) -> None:
    service = EvidencePersistenceService()
    mock_session = AsyncMock(spec=AsyncSession)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = sample_review_run
    mock_session.execute.return_value = mock_result
    mock_session.flush.side_effect = SQLAlchemyError("DB deadlock")

    with pytest.raises(EvidencePersistenceError):
        await service.persist_evidence_batch(
            session=mock_session,
            review_run_id=sample_review_run.id,
            expected_commit_sha="a" * 40,
            evidence_items=sample_evidence_items,
        )

    assert mock_session.rollback.call_count == 1
