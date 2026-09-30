"""Tests for ARQ queue infrastructure, ReviewJobPayload, queue service, and worker.

Covers:
- ReviewJobPayload schema validation and serialization
- ReviewJobResult schema validation
- ReviewJobQueueService enqueueing and error handling
- Worker tasks execution, validation, and retry mechanics
- WorkerSettings configuration and lifecycle hooks
- Real Redis integration testing
- End-to-end webhook -> Redis -> worker execution
- Failure scenarios (queue failure -> HTTP 503 -> DB marked failed -> retry allowed)
"""

import hashlib
import hmac
import json
import uuid
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from app.api.v1.webhooks import get_queue_service
from app.core.config import Settings, get_settings
from app.database.models.webhook_delivery import WebhookDelivery
from app.database.session import async_engine, get_db_session
from app.main import app
from app.schemas.job import ReviewJobPayload, ReviewJobResult
from app.services.queue_service import QueueEnqueueError, ReviewJobQueueService
from app.workers.settings import WorkerSettings, on_shutdown, on_startup
from app.workers.tasks import review_pull_request_job
from arq import Retry
from arq.connections import ArqRedis, create_pool
from arq.jobs import Job, JobStatus
from pydantic import SecretStr, ValidationError
from sqlalchemy import select

TEST_SECRET = "test-webhook-secret-key-32-chars-minimum"


def compute_signature(payload: bytes, secret: str = TEST_SECRET) -> str:
    """Generate canonical GitHub X-Hub-Signature-256 header value."""
    mac = hmac.new(key=secret.encode("utf-8"), msg=payload, digestmod=hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def build_pr_payload(
    action: str = "opened",
    number: int = 42,
    head_sha: str = "6dcb09b5b57875f334f61aebed695e2e4193db5e",
    base_sha: str = "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b",
    repo_name: str = "octocat/Hello-World",
    repo_id: int = 1296269,
) -> dict[str, Any]:
    """Construct a minimal valid pull_request webhook payload."""
    return {
        "action": action,
        "number": number,
        "pull_request": {
            "id": 990000 + number,
            "number": number,
            "title": f"PR #{number}: Automated Review Test",
            "state": "open",
            "head": {
                "sha": head_sha,
                "ref": "feature/branch",
            },
            "base": {
                "sha": base_sha,
                "ref": "main",
            },
            "html_url": f"https://github.com/{repo_name}/pull/{number}",
            "user": {"login": "octocat", "id": 1},
        },
        "repository": {
            "id": repo_id,
            "name": repo_name.split("/")[-1],
            "full_name": repo_name,
            "html_url": f"https://github.com/{repo_name}",
            "default_branch": "main",
        },
        "sender": {"id": 1, "login": "octocat"},
    }


@pytest.fixture(autouse=True)
async def configure_test_settings() -> Any:
    """Configure Settings with a test webhook secret and clear dependency overrides."""

    def test_settings() -> Settings:
        return Settings(
            GITHUB_WEBHOOK_SECRET=SecretStr(TEST_SECRET),
        )

    app.dependency_overrides[get_settings] = test_settings
    yield
    app.dependency_overrides.clear()
    await async_engine.dispose()


@pytest.fixture
async def async_client() -> Any:
    """Provide an asynchronous HTTP client configured with ASGITransport."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


# ==============================================================================
# 1. REVIEW JOB CONTRACT SCHEMA TESTS
# ==============================================================================


@pytest.mark.unit
def test_review_job_payload_valid() -> None:
    """Verify creation and attributes of valid ReviewJobPayload."""
    payload = ReviewJobPayload(
        delivery_id="deliv-12345",
        repository_id=1296269,
        repository_full_name="octocat/Hello-World",
        pr_number=42,
        pull_request_id=990042,
        head_sha="6dcb09b5b57875f334f61aebed695e2e4193db5e",
        base_sha="1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b",
        action="opened",
    )
    assert payload.delivery_id == "deliv-12345"
    assert payload.repository_id == 1296269
    assert payload.repository_full_name == "octocat/Hello-World"
    assert payload.pr_number == 42
    assert payload.pull_request_id == 990042
    assert payload.head_sha == "6dcb09b5b57875f334f61aebed695e2e4193db5e"
    assert payload.base_sha == "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b"
    assert payload.action == "opened"
    assert payload.event_type == "pull_request"
    assert payload.enqueued_at is not None


@pytest.mark.unit
def test_review_job_payload_missing_required_fields() -> None:
    """Verify ValidationError when mandatory fields are omitted."""
    with pytest.raises(ValidationError) as exc_info:
        ReviewJobPayload.model_validate(
            {
                "delivery_id": "deliv-123",
                "repository_id": 1234,
                # Missing repository_full_name, pr_number, pull_request_id, head_sha, base_sha, action
            }
        )
    errors = str(exc_info.value)
    assert "repository_full_name" in errors
    assert "pr_number" in errors
    assert "head_sha" in errors


@pytest.mark.unit
def test_review_job_payload_invalid_commit_sha() -> None:
    """Verify ValidationError when commit SHAs do not match 40-character hex pattern."""
    # Invalid length (too short)
    with pytest.raises(ValidationError):
        ReviewJobPayload(
            delivery_id="deliv-123",
            repository_id=1234,
            repository_full_name="org/repo",
            pr_number=1,
            pull_request_id=10,
            head_sha="6dcb09b",  # Short
            base_sha="1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b",
            action="opened",
        )

    # Invalid characters (non-hex)
    with pytest.raises(ValidationError):
        ReviewJobPayload(
            delivery_id="deliv-123",
            repository_id=1234,
            repository_full_name="org/repo",
            pr_number=1,
            pull_request_id=10,
            head_sha="zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",  # Non-hex
            base_sha="1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b",
            action="opened",
        )


@pytest.mark.unit
def test_review_job_payload_extra_fields_forbidden() -> None:
    """Verify extra attributes are forbidden to prevent credential/metadata leakage."""
    with pytest.raises(ValidationError) as exc_info:
        ReviewJobPayload.model_validate(
            {
                "delivery_id": "deliv-123",
                "repository_id": 1234,
                "repository_full_name": "org/repo",
                "pr_number": 1,
                "pull_request_id": 10,
                "head_sha": "6dcb09b5b57875f334f61aebed695e2e4193db5e",
                "base_sha": "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b",
                "action": "opened",
                "github_token": "ghp_secretToken12345",  # Forbidden extra field!
            }
        )
    assert "Extra inputs are not permitted" in str(exc_info.value)


@pytest.mark.unit
def test_review_job_payload_serialization_roundtrip() -> None:
    """Verify deterministic JSON serialization and deserialization."""
    payload = ReviewJobPayload(
        delivery_id="deliv-roundtrip",
        repository_id=1296269,
        repository_full_name="octocat/Hello-World",
        pr_number=42,
        pull_request_id=990042,
        head_sha="6dcb09b5b57875f334f61aebed695e2e4193db5e",
        base_sha="1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b",
        action="synchronize",
    )
    json_str = payload.model_dump_json()
    reconstructed = ReviewJobPayload.model_validate_json(json_str)
    assert reconstructed.delivery_id == payload.delivery_id
    assert reconstructed.head_sha == payload.head_sha
    assert reconstructed.action == "synchronize"


@pytest.mark.unit
def test_review_job_result_valid() -> None:
    """Verify creation and serialization of ReviewJobResult."""
    result = ReviewJobResult(
        job_id="review:deliv-999",
        delivery_id="deliv-999",
        repository_full_name="octocat/Hello-World",
        pr_number=42,
        head_sha="6dcb09b5b57875f334f61aebed695e2e4193db5e",
        status="acknowledged",
    )
    data = result.model_dump(mode="json")
    assert data["job_id"] == "review:deliv-999"
    assert data["status"] == "acknowledged"
    assert "processed_at" in data


# ==============================================================================
# 2. QUEUE SERVICE UNIT TESTS
# ==============================================================================


@pytest.mark.unit
async def test_queue_service_enqueue_success() -> None:
    """Verify ReviewJobQueueService enqueues job and returns job ID."""
    mock_pool = AsyncMock()
    mock_job = AsyncMock()
    mock_job.job_id = "review:deliv-123"
    mock_pool.enqueue_job.return_value = mock_job

    service = ReviewJobQueueService(arq_pool=mock_pool)
    payload = ReviewJobPayload(
        delivery_id="deliv-123",
        repository_id=1296269,
        repository_full_name="octocat/Hello-World",
        pr_number=42,
        pull_request_id=990042,
        head_sha="6dcb09b5b57875f334f61aebed695e2e4193db5e",
        base_sha="1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b",
        action="opened",
    )

    job_id = await service.enqueue_review_job(payload)
    assert job_id == "review:deliv-123"
    assert mock_pool.enqueue_job.call_count == 1
    call_kwargs = mock_pool.enqueue_job.call_args[1]
    assert call_kwargs["_job_id"] == "review:deliv-123"


@pytest.mark.unit
async def test_queue_service_duplicate_job_returns_deterministic_id() -> None:
    """Verify duplicate job submission returning None from ARQ returns original job ID."""
    mock_pool = AsyncMock()
    # ARQ returns None when _job_id already exists in queue/redis
    mock_pool.enqueue_job.return_value = None

    service = ReviewJobQueueService(arq_pool=mock_pool)
    payload = ReviewJobPayload(
        delivery_id="deliv-duplicate",
        repository_id=1296269,
        repository_full_name="octocat/Hello-World",
        pr_number=42,
        pull_request_id=990042,
        head_sha="6dcb09b5b57875f334f61aebed695e2e4193db5e",
        base_sha="1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b",
        action="opened",
    )

    job_id = await service.enqueue_review_job(payload)
    assert job_id == "review:deliv-duplicate"


@pytest.mark.unit
async def test_queue_service_enqueue_failure_raises_queue_enqueue_error() -> None:
    """Verify connection or Redis errors are wrapped in QueueEnqueueError."""
    mock_pool = AsyncMock()
    mock_pool.enqueue_job.side_effect = ConnectionError("Redis unreachable")

    service = ReviewJobQueueService(arq_pool=mock_pool)
    payload = ReviewJobPayload(
        delivery_id="deliv-fail",
        repository_id=1296269,
        repository_full_name="octocat/Hello-World",
        pr_number=42,
        pull_request_id=990042,
        head_sha="6dcb09b5b57875f334f61aebed695e2e4193db5e",
        base_sha="1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b",
        action="opened",
    )

    with pytest.raises(QueueEnqueueError) as exc_info:
        await service.enqueue_review_job(payload)
    assert "deliv-fail" in str(exc_info.value)
    assert "Redis unreachable" in str(exc_info.value)


# ==============================================================================
# 3. WORKER TASKS & SETTINGS UNIT TESTS
# ==============================================================================


@pytest.mark.unit
async def test_worker_review_job_valid_dict_payload() -> None:
    """Verify review_pull_request_job executes cleanly with dict payload."""
    ctx = {"job_id": "review:test-1", "job_try": 1}
    payload = {
        "delivery_id": "deliv-test-1",
        "repository_id": 1296269,
        "repository_full_name": "octocat/Hello-World",
        "pr_number": 42,
        "pull_request_id": 990042,
        "head_sha": "6dcb09b5b57875f334f61aebed695e2e4193db5e",
        "base_sha": "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b",
        "action": "opened",
    }
    result = await review_pull_request_job(ctx, payload)
    assert result["job_id"] == "review:test-1"
    assert result["delivery_id"] == "deliv-test-1"
    assert result["repository_full_name"] == "octocat/Hello-World"
    assert result["pr_number"] == 42
    assert result["head_sha"] == "6dcb09b5b57875f334f61aebed695e2e4193db5e"
    assert result["status"] == "acknowledged"


@pytest.mark.unit
async def test_worker_review_job_valid_json_string_payload() -> None:
    """Verify review_pull_request_job executes cleanly with JSON string payload."""
    ctx = {"job_id": "review:test-2", "job_try": 1}
    payload_dict = {
        "delivery_id": "deliv-test-2",
        "repository_id": 1296269,
        "repository_full_name": "octocat/Hello-World",
        "pr_number": 42,
        "pull_request_id": 990042,
        "head_sha": "6dcb09b5b57875f334f61aebed695e2e4193db5e",
        "base_sha": "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b",
        "action": "opened",
    }
    result = await review_pull_request_job(ctx, json.dumps(payload_dict))
    assert result["job_id"] == "review:test-2"
    assert result["delivery_id"] == "deliv-test-2"


@pytest.mark.unit
async def test_worker_review_job_malformed_payload_raises_value_error() -> None:
    """Verify malformed payload raises ValueError (non-retryable permanent failure)."""
    ctx = {"job_id": "review:bad", "job_try": 1}
    bad_payload = {"delivery_id": "missing-fields"}
    with pytest.raises(ValueError) as exc_info:
        await review_pull_request_job(ctx, bad_payload)
    assert "Malformed ReviewJobPayload" in str(exc_info.value)


@pytest.mark.unit
async def test_worker_review_job_unsupported_type_raises_value_error() -> None:
    """Verify passing non-dict/non-string raises ValueError."""
    ctx = {"job_id": "review:type", "job_try": 1}
    with pytest.raises(ValueError) as exc_info:
        await review_pull_request_job(ctx, 12345)  # type: ignore[arg-type]
    assert "Unsupported payload type" in str(exc_info.value)


@pytest.mark.unit
async def test_worker_review_job_transient_failure_retried() -> None:
    """Verify simulated transient error raises arq.Retry on first try."""
    ctx = {"job_id": "review:retry", "job_try": 1}
    payload = {
        "delivery_id": "deliv-retry",
        "repository_id": 1296269,
        "repository_full_name": "octocat/Hello-World",
        "pr_number": 42,
        "pull_request_id": 990042,
        "head_sha": "6dcb09b5b57875f334f61aebed695e2e4193db5e",
        "base_sha": "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b",
        "action": "opened",
        "_simulate_transient_failure": True,
    }

    # First attempt: raises arq.Retry
    with pytest.raises(Retry) as exc_info:
        await review_pull_request_job(ctx, payload)
    assert exc_info.value.defer_score is not None

    # Second attempt (job_try=2): completes successfully
    ctx_retry = {"job_id": "review:retry", "job_try": 2}
    result = await review_pull_request_job(ctx_retry, payload)
    assert result["status"] == "acknowledged"


@pytest.mark.unit
def test_worker_settings_configuration() -> None:
    """Verify WorkerSettings reflects application configuration."""
    settings = get_settings()
    assert WorkerSettings.queue_name == settings.ARQ_QUEUE_NAME
    assert WorkerSettings.max_jobs == settings.ARQ_MAX_JOBS
    assert WorkerSettings.job_timeout == settings.ARQ_JOB_TIMEOUT_SECONDS
    assert WorkerSettings.max_tries == settings.ARQ_MAX_RETRIES
    assert WorkerSettings.keep_result == settings.ARQ_KEEP_RESULT_SECONDS
    assert review_pull_request_job in WorkerSettings.functions


@pytest.mark.unit
async def test_worker_lifecycle_hooks() -> None:
    """Verify on_startup and on_shutdown lifecycle callbacks run without error."""
    ctx: dict[str, Any] = {}
    await on_startup(ctx)
    await on_shutdown(ctx)


# ==============================================================================
# 4. WEBHOOK TO QUEUE INTEGRATION TESTS
# ==============================================================================


@pytest.mark.integration
async def test_webhook_pr_opened_enqueues_arq_job(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify pull_request.opened persists delivery and enqueues job with exact contract."""
    delivery_id = str(uuid.uuid4())
    raw_payload = json.dumps(build_pr_payload(action="opened", number=201)).encode()
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": compute_signature(raw_payload, TEST_SECRET),
        "Content-Type": "application/json",
    }

    mock_queue = AsyncMock(spec=ReviewJobQueueService)
    mock_queue.enqueue_review_job.return_value = f"review:{delivery_id}"

    app.dependency_overrides[get_queue_service] = lambda: mock_queue
    try:
        response = await async_client.post(
            "/api/v1/webhooks/github", content=raw_payload, headers=headers
        )
    finally:
        app.dependency_overrides.pop(get_queue_service, None)

    assert response.status_code == 202
    assert response.json()["status"] == "accepted"
    assert mock_queue.enqueue_review_job.call_count == 1

    job_payload: ReviewJobPayload = mock_queue.enqueue_review_job.call_args[0][0]
    assert job_payload.delivery_id == delivery_id
    assert job_payload.action == "opened"
    assert job_payload.pr_number == 201
    assert job_payload.head_sha == "6dcb09b5b57875f334f61aebed695e2e4193db5e"
    assert job_payload.base_sha == "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b"


@pytest.mark.integration
async def test_webhook_pr_synchronize_enqueues_job(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify pull_request.synchronize enqueues review job."""
    delivery_id = str(uuid.uuid4())
    raw_payload = json.dumps(
        build_pr_payload(action="synchronize", number=202)
    ).encode()
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": compute_signature(raw_payload, TEST_SECRET),
        "Content-Type": "application/json",
    }

    mock_queue = AsyncMock(spec=ReviewJobQueueService)
    mock_queue.enqueue_review_job.return_value = f"review:{delivery_id}"

    app.dependency_overrides[get_queue_service] = lambda: mock_queue
    try:
        response = await async_client.post(
            "/api/v1/webhooks/github", content=raw_payload, headers=headers
        )
    finally:
        app.dependency_overrides.pop(get_queue_service, None)

    assert response.status_code == 202
    assert mock_queue.enqueue_review_job.call_count == 1
    assert mock_queue.enqueue_review_job.call_args[0][0].action == "synchronize"


@pytest.mark.integration
async def test_webhook_pr_reopened_enqueues_job(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify pull_request.reopened enqueues review job."""
    delivery_id = str(uuid.uuid4())
    raw_payload = json.dumps(build_pr_payload(action="reopened", number=203)).encode()
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": compute_signature(raw_payload, TEST_SECRET),
        "Content-Type": "application/json",
    }

    mock_queue = AsyncMock(spec=ReviewJobQueueService)
    mock_queue.enqueue_review_job.return_value = f"review:{delivery_id}"

    app.dependency_overrides[get_queue_service] = lambda: mock_queue
    try:
        response = await async_client.post(
            "/api/v1/webhooks/github", content=raw_payload, headers=headers
        )
    finally:
        app.dependency_overrides.pop(get_queue_service, None)

    assert response.status_code == 202
    assert mock_queue.enqueue_review_job.call_count == 1
    assert mock_queue.enqueue_review_job.call_args[0][0].action == "reopened"


@pytest.mark.integration
async def test_webhook_unsupported_action_does_not_enqueue(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify unsupported PR action (e.g. closed) does NOT enqueue any ARQ job."""
    delivery_id = str(uuid.uuid4())
    raw_payload = json.dumps(build_pr_payload(action="closed", number=204)).encode()
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": compute_signature(raw_payload, TEST_SECRET),
        "Content-Type": "application/json",
    }

    mock_queue = AsyncMock(spec=ReviewJobQueueService)

    app.dependency_overrides[get_queue_service] = lambda: mock_queue
    try:
        response = await async_client.post(
            "/api/v1/webhooks/github", content=raw_payload, headers=headers
        )
    finally:
        app.dependency_overrides.pop(get_queue_service, None)

    assert response.status_code == 202
    assert response.json()["status"] == "ignored"
    assert mock_queue.enqueue_review_job.call_count == 0


@pytest.mark.integration
async def test_webhook_unsupported_event_does_not_enqueue(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify unsupported event (e.g. ping) does NOT enqueue any ARQ job."""
    delivery_id = str(uuid.uuid4())
    raw_payload = b'{"zen": "Favor focus."}'
    headers = {
        "X-GitHub-Event": "ping",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": compute_signature(raw_payload, TEST_SECRET),
        "Content-Type": "application/json",
    }

    mock_queue = AsyncMock(spec=ReviewJobQueueService)

    app.dependency_overrides[get_queue_service] = lambda: mock_queue
    try:
        response = await async_client.post(
            "/api/v1/webhooks/github", content=raw_payload, headers=headers
        )
    finally:
        app.dependency_overrides.pop(get_queue_service, None)

    assert response.status_code == 202
    assert response.json()["status"] == "ignored"
    assert mock_queue.enqueue_review_job.call_count == 0


@pytest.mark.integration
async def test_webhook_duplicate_delivery_does_not_enqueue_again(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify duplicate delivery ID does NOT enqueue a second ARQ job."""
    delivery_id = str(uuid.uuid4())
    raw_payload = json.dumps(build_pr_payload(action="opened", number=205)).encode()
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": compute_signature(raw_payload, TEST_SECRET),
        "Content-Type": "application/json",
    }

    mock_queue = AsyncMock(spec=ReviewJobQueueService)
    mock_queue.enqueue_review_job.return_value = f"review:{delivery_id}"

    app.dependency_overrides[get_queue_service] = lambda: mock_queue
    try:
        # Delivery 1: accepted and enqueued
        resp1 = await async_client.post(
            "/api/v1/webhooks/github", content=raw_payload, headers=headers
        )
        assert resp1.status_code == 202
        assert resp1.json()["status"] == "accepted"
        assert mock_queue.enqueue_review_job.call_count == 1

        # Delivery 2 (same delivery_id): recognized as duplicate, NOT enqueued
        resp2 = await async_client.post(
            "/api/v1/webhooks/github", content=raw_payload, headers=headers
        )
        assert resp2.status_code == 202
        assert resp2.json()["status"] == "duplicate"
        assert mock_queue.enqueue_review_job.call_count == 1
    finally:
        app.dependency_overrides.pop(get_queue_service, None)


@pytest.mark.integration
async def test_webhook_invalid_hmac_cannot_reach_queue(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify invalid HMAC is rejected with 401 and never touches queue or Redis."""
    delivery_id = str(uuid.uuid4())
    raw_payload = json.dumps(build_pr_payload(action="opened", number=206)).encode()
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": "sha256=badsignature000000000000000000000000000000000000000000000000000000",
        "Content-Type": "application/json",
    }

    mock_queue = AsyncMock(spec=ReviewJobQueueService)

    app.dependency_overrides[get_queue_service] = lambda: mock_queue
    try:
        response = await async_client.post(
            "/api/v1/webhooks/github", content=raw_payload, headers=headers
        )
    finally:
        app.dependency_overrides.pop(get_queue_service, None)

    assert response.status_code == 401
    assert mock_queue.enqueue_review_job.call_count == 0


# ==============================================================================
# 5. FAILURE & CONSISTENCY SCENARIO (Prompt Section 18)
# ==============================================================================


@pytest.mark.integration
async def test_webhook_queue_enqueue_failure_returns_503_and_allows_retry(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify queue failure returns HTTP 503, marks delivery failed, and allows retry."""
    delivery_id = str(uuid.uuid4())
    raw_payload = json.dumps(build_pr_payload(action="opened", number=207)).encode()
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": compute_signature(raw_payload, TEST_SECRET),
        "Content-Type": "application/json",
    }

    # Step 1: Queue fails
    failing_queue = AsyncMock(spec=ReviewJobQueueService)
    failing_queue.enqueue_review_job.side_effect = QueueEnqueueError(
        "Simulated Redis queue connection timeout"
    )

    app.dependency_overrides[get_queue_service] = lambda: failing_queue
    try:
        response1 = await async_client.post(
            "/api/v1/webhooks/github", content=raw_payload, headers=headers
        )
    finally:
        app.dependency_overrides.pop(get_queue_service, None)

    # Must NOT report success!
    assert response1.status_code == 503
    assert "Review job queue unavailable" in response1.json()["detail"]

    # Verify DB state: marked as 'failed' (not 'accepted')
    async for session in get_db_session():
        stmt = select(WebhookDelivery).where(WebhookDelivery.delivery_id == delivery_id)
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()
        assert record is not None
        assert record.status == "failed"

    # Step 2: GitHub retries the delivery (same delivery ID) when queue is recovered
    healthy_queue = AsyncMock(spec=ReviewJobQueueService)
    healthy_queue.enqueue_review_job.return_value = f"review:{delivery_id}"

    app.dependency_overrides[get_queue_service] = lambda: healthy_queue
    try:
        response2 = await async_client.post(
            "/api/v1/webhooks/github", content=raw_payload, headers=headers
        )
    finally:
        app.dependency_overrides.pop(get_queue_service, None)

    # Must succeed and NOT be dropped as duplicate!
    assert response2.status_code == 202
    assert response2.json()["status"] == "accepted"
    assert healthy_queue.enqueue_review_job.call_count == 1

    # Verify DB state is updated to 'accepted'
    async for session in get_db_session():
        stmt = select(WebhookDelivery).where(WebhookDelivery.delivery_id == delivery_id)
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()
        assert record is not None
        assert record.status == "accepted"


# ==============================================================================
# 6. END-TO-END LIVE REDIS + WORKER INTEGRATION TEST (Prompt Section 17)
# ==============================================================================


@pytest.mark.integration
async def test_end_to_end_webhook_to_redis_to_worker(
    async_client: httpx.AsyncClient,
) -> None:
    """End-to-end integration test against live Docker Redis container:

    HTTP webhook request
            ↓
    HMAC verification
            ↓
    PR event accepted
            ↓
    delivery deduplication
            ↓
    ARQ enqueue into real Redis
            ↓
    Worker consumes and executes placeholder job
            ↓
    Result verified
    """
    settings = get_settings()
    redis_settings = settings.arq_redis_settings

    # Verify real Redis is reachable
    arq_pool: ArqRedis = await create_pool(redis_settings)
    try:
        await arq_pool.ping()
    except Exception as exc:
        pytest.skip(f"Docker Redis is not available: {exc}")

    delivery_id = str(uuid.uuid4())
    raw_payload = json.dumps(build_pr_payload(action="opened", number=301)).encode()
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": compute_signature(raw_payload, TEST_SECRET),
        "Content-Type": "application/json",
    }

    # 1. Post webhook to live API (uses real Redis queue)
    response = await async_client.post(
        "/api/v1/webhooks/github", content=raw_payload, headers=headers
    )
    assert response.status_code == 202
    assert response.json()["status"] == "accepted"

    # 2. Check that the job exists in Redis
    job_id = f"review:{delivery_id}"
    job = Job(job_id, arq_pool, _queue_name=settings.ARQ_QUEUE_NAME)
    job_status = await job.status()
    assert job_status in (
        JobStatus.queued,
        JobStatus.deferred,
        JobStatus.in_progress,
        JobStatus.complete,
    )

    # 3. Simulate worker consuming the enqueued job from Redis
    raw_job_info = await job.info()
    assert raw_job_info is not None
    assert raw_job_info.function == "review_pull_request_job"

    # Execute worker task with the exact payload enqueued in Redis
    ctx = {"job_id": job_id, "job_try": 1, "redis": arq_pool}
    worker_result = await review_pull_request_job(ctx, raw_job_info.args[0])

    assert worker_result["job_id"] == job_id
    assert worker_result["delivery_id"] == delivery_id
    assert worker_result["status"] == "acknowledged"
    assert worker_result["pr_number"] == 301
    assert worker_result["head_sha"] == "6dcb09b5b57875f334f61aebed695e2e4193db5e"

    # 4. Idempotency test: send duplicate webhook delivery
    dup_response = await async_client.post(
        "/api/v1/webhooks/github", content=raw_payload, headers=headers
    )
    assert dup_response.status_code == 202
    aclose_fn = getattr(arq_pool, "aclose", None)
    if callable(aclose_fn):
        await aclose_fn()
    else:
        await arq_pool.close()
