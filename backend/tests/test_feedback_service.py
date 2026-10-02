"""Unit tests for ReviewFeedback data model and FeedbackService."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.database.models.feedback import ReviewFeedback
from app.database.models.publication import ReviewPublication
from app.schemas.enums import FeedbackSource, FeedbackType
from app.schemas.publication import FeedbackCreate, FeedbackFilter
from app.services.github.feedback_service import FeedbackService
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def mock_session() -> AsyncSession:
    session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    session.execute.return_value = mock_result
    return session


@pytest.mark.asyncio
async def test_record_feedback_direct(mock_session: AsyncSession) -> None:
    service = FeedbackService()
    finding_id = uuid.uuid4()
    run_id = uuid.uuid4()

    create_data = FeedbackCreate(
        finding_id=finding_id,
        review_run_id=run_id,
        repository_id=123,
        pr_number=42,
        github_comment_id=1001,
        github_review_id=2001,
        feedback_type=FeedbackType.FINDING_ACCEPTED,
        feedback_source=FeedbackSource.API,
        reviewer_username="reviewer_alice",
        comment_body="Fix looks great, accepted.",
    )

    record = await service.record_feedback(mock_session, create_data)

    assert record.finding_id == finding_id
    assert record.review_run_id == run_id
    assert record.repository_id == 123
    assert record.pr_number == 42
    assert record.feedback_type == FeedbackType.FINDING_ACCEPTED
    assert record.feedback_source == FeedbackSource.API
    assert record.reviewer_username == "reviewer_alice"
    assert record.comment_body == "Fix looks great, accepted."
    mock_session.add.assert_called_once_with(record)
    mock_session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_record_feedback_correlated_via_comment_id(
    mock_session: AsyncSession,
) -> None:
    service = FeedbackService()
    finding_id = uuid.uuid4()
    run_id = uuid.uuid4()

    # Mock finding correlating publication
    mock_pub = MagicMock(spec=ReviewPublication)
    mock_pub.finding_id = finding_id
    mock_pub.review_run_id = run_id
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_pub
    mock_session.execute.return_value = mock_result

    # Provide github_comment_id but None for finding_id
    create_data = FeedbackCreate(
        finding_id=None,
        review_run_id=None,
        repository_id=123,
        pr_number=42,
        github_comment_id=1001,
        feedback_type=FeedbackType.COMMENT_REPLY,
        reviewer_username="bob",
        comment_body="Can we clarify this?",
    )

    record = await service.record_feedback(mock_session, create_data)

    assert record.finding_id == finding_id
    assert record.review_run_id == run_id
    assert record.github_comment_id == 1001


@pytest.mark.asyncio
async def test_list_feedback_filtering(mock_session: AsyncSession) -> None:
    service = FeedbackService()
    sample_item = MagicMock(spec=ReviewFeedback)
    sample_item.id = uuid.uuid4()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [sample_item]
    mock_session.execute.return_value = mock_result

    filter_params = FeedbackFilter(
        repository_id=123,
        pr_number=42,
        feedback_type=FeedbackType.REACTION_POSITIVE,
    )

    records = await service.list_feedback(
        mock_session, filter_params, limit=10, offset=0
    )

    assert len(records) == 1
    mock_session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_record_webhook_feedback_comment_events(
    mock_session: AsyncSession,
) -> None:
    service = FeedbackService()

    # 1. pull_request_review_comment reply created
    payload_reply = {
        "action": "created",
        "repository": {"id": 999},
        "pull_request": {"number": 12},
        "sender": {"login": "dev_user"},
        "comment": {
            "id": 555,
            "in_reply_to_id": 444,
            "body": "Fixed in latest commit.",
        },
    }

    record_reply = await service.record_webhook_feedback(
        mock_session, "pull_request_review_comment", payload_reply
    )
    assert record_reply is not None
    assert record_reply.feedback_type == FeedbackType.COMMENT_REPLY
    assert record_reply.github_comment_id == 444
    assert record_reply.reviewer_username == "dev_user"

    # 2. pull_request_review_comment deleted (dismissed)
    payload_deleted = {
        "action": "deleted",
        "repository": {"id": 999},
        "pull_request": {"number": 12},
        "sender": {"login": "dev_user"},
        "comment": {"id": 555},
    }
    record_deleted = await service.record_webhook_feedback(
        mock_session, "pull_request_review_comment", payload_deleted
    )
    assert record_deleted is not None
    assert record_deleted.feedback_type == FeedbackType.COMMENT_DISMISSED


@pytest.mark.asyncio
async def test_record_webhook_feedback_review_events(
    mock_session: AsyncSession,
) -> None:
    service = FeedbackService()

    # Approved review
    payload_approved = {
        "action": "submitted",
        "repository": {"id": 999},
        "pull_request": {"number": 12},
        "sender": {"login": "lead_reviewer"},
        "review": {"id": 888, "state": "approved", "body": "LGTM!"},
    }
    record_approved = await service.record_webhook_feedback(
        mock_session, "pull_request_review", payload_approved
    )
    assert record_approved is not None
    assert record_approved.feedback_type == FeedbackType.FINDING_ACCEPTED
    assert record_approved.github_review_id == 888

    # Changes requested review
    payload_changes = {
        "action": "submitted",
        "repository": {"id": 999},
        "pull_request": {"number": 12},
        "sender": {"login": "lead_reviewer"},
        "review": {"id": 889, "state": "changes_requested", "body": "Needs fixes."},
    }
    record_changes = await service.record_webhook_feedback(
        mock_session, "pull_request_review", payload_changes
    )
    assert record_changes is not None
    assert record_changes.feedback_type == FeedbackType.FINDING_REJECTED


@pytest.mark.asyncio
async def test_record_webhook_feedback_reactions(mock_session: AsyncSession) -> None:
    service = FeedbackService()

    # Thumbs up reaction
    payload_reaction_pos = {
        "action": "created",
        "repository": {"id": 999},
        "pull_request": {"number": 12},
        "sender": {"login": "user1"},
        "comment": {"id": 333},
        "reaction": {"content": "+1"},
    }
    record_pos = await service.record_webhook_feedback(
        mock_session, "reaction", payload_reaction_pos
    )
    assert record_pos is not None
    assert record_pos.feedback_type == FeedbackType.REACTION_POSITIVE
    assert record_pos.extra_metadata["reaction_content"] == "+1"

    # Thumbs down reaction
    payload_reaction_neg = {
        "action": "created",
        "repository": {"id": 999},
        "pull_request": {"number": 12},
        "sender": {"login": "user2"},
        "comment": {"id": 333},
        "reaction": {"content": "-1"},
    }
    record_neg = await service.record_webhook_feedback(
        mock_session, "reaction", payload_reaction_neg
    )
    assert record_neg is not None
    assert record_neg.feedback_type == FeedbackType.REACTION_NEGATIVE
