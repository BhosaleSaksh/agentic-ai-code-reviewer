"""Comprehensive test suite for GitHub webhook ingestion and HMAC verification.

Covers HMAC-SHA256 signature verification edge cases, header validation,
event classification, delivery idempotency across Redis and PostgreSQL,
security properties, transaction boundaries, and error contracts.
"""

import hashlib
import hmac
import json
import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from app.core.config import Settings, get_settings
from app.database.models.webhook_delivery import WebhookDelivery
from app.database.session import async_engine, get_db_session
from app.github.verifier import verify_github_signature
from app.main import app
from app.services.webhook_service import WebhookService
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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
async def configure_test_settings() -> AsyncGenerator[None, None]:
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
async def async_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Provide an asynchronous HTTP client configured with ASGITransport."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


# ==============================================================================
# 1. HMAC-SHA256 SIGNATURE VERIFICATION UNIT TESTS
# ==============================================================================


@pytest.mark.unit
def test_hmac_valid_signature_accepted() -> None:
    """Verify authentic signature matches and passes verification."""
    payload = b'{"action":"opened"}'
    sig = compute_signature(payload, TEST_SECRET)
    assert verify_github_signature(payload, sig, TEST_SECRET) is True
    assert verify_github_signature(payload, sig, SecretStr(TEST_SECRET)) is True


@pytest.mark.unit
def test_hmac_invalid_signature_rejected() -> None:
    """Verify mismatched digest signature is rejected."""
    payload = b'{"action":"opened"}'
    invalid_sig = (
        "sha256=0000000000000000000000000000000000000000000000000000000000000000"
    )
    assert verify_github_signature(payload, invalid_sig, TEST_SECRET) is False


@pytest.mark.unit
def test_hmac_missing_signature_rejected() -> None:
    """Verify missing signature header returns False."""
    payload = b'{"action":"opened"}'
    assert verify_github_signature(payload, None, TEST_SECRET) is False
    assert verify_github_signature(payload, "", TEST_SECRET) is False


@pytest.mark.unit
def test_hmac_malformed_signature_rejected() -> None:
    """Verify malformed signatures (missing prefix, empty digest) are rejected."""
    payload = b'{"action":"opened"}'
    # Missing sha256= prefix
    assert verify_github_signature(payload, "abcdef123456", TEST_SECRET) is False
    # Empty digest after prefix
    assert verify_github_signature(payload, "sha256=", TEST_SECRET) is False
    assert verify_github_signature(payload, "sha256=   ", TEST_SECRET) is False


@pytest.mark.unit
def test_hmac_wrong_secret_rejected() -> None:
    """Verify signature computed with a different secret is rejected."""
    payload = b'{"action":"opened"}'
    sig_wrong_secret = compute_signature(payload, "wrong-secret-key")
    assert verify_github_signature(payload, sig_wrong_secret, TEST_SECRET) is False


@pytest.mark.unit
def test_hmac_unconfigured_secret_rejected() -> None:
    """Verify verification returns False when secret is None or empty."""
    payload = b'{"action":"opened"}'
    sig = compute_signature(payload, TEST_SECRET)
    assert verify_github_signature(payload, sig, None) is False
    assert verify_github_signature(payload, sig, "") is False
    assert verify_github_signature(payload, sig, SecretStr("")) is False


@pytest.mark.unit
def test_hmac_raw_bytes_exact_matching() -> None:
    """Verify signature is bound to the exact raw byte sequence."""
    payload1 = b'{"action": "opened", "number": 1}'
    payload2 = b'{"number": 1, "action": "opened"}'  # Equivalent dict, different bytes

    sig1 = compute_signature(payload1, TEST_SECRET)
    assert verify_github_signature(payload1, sig1, TEST_SECRET) is True
    # Same JSON semantics but altered raw byte representation fails
    assert verify_github_signature(payload2, sig1, TEST_SECRET) is False


@pytest.mark.unit
def test_hmac_constant_time_comparison_used() -> None:
    """Verify hmac.compare_digest is utilized during verification."""
    payload = b'{"test": true}'
    sig = compute_signature(payload, TEST_SECRET)

    with patch("hmac.compare_digest", wraps=hmac.compare_digest) as mock_compare:
        result = verify_github_signature(payload, sig, TEST_SECRET)
        assert result is True
        assert mock_compare.call_count == 1


# ==============================================================================
# 2. ENDPOINT HEADER & AUTHENTICATION TESTS
# ==============================================================================


@pytest.mark.unit
async def test_webhook_endpoint_missing_signature_header(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify missing X-Hub-Signature-256 returns 401 Unauthorized."""
    delivery_id = str(uuid.uuid4())
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
    }
    response = await async_client.post(
        "/api/v1/webhooks/github",
        content=b"{}",
        headers=headers,
    )
    assert response.status_code == 401
    assert "Missing X-Hub-Signature-256 header" in response.json()["detail"]


@pytest.mark.unit
async def test_webhook_endpoint_invalid_signature(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify invalid X-Hub-Signature-256 returns 401 Unauthorized."""
    delivery_id = str(uuid.uuid4())
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": "sha256=badbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadb",
    }
    response = await async_client.post(
        "/api/v1/webhooks/github",
        content=b"{}",
        headers=headers,
    )
    assert response.status_code == 401
    assert "Invalid webhook signature" in response.json()["detail"]


@pytest.mark.unit
async def test_webhook_endpoint_missing_delivery_header(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify missing X-GitHub-Delivery returns 400 Bad Request."""
    payload = b'{"action":"opened"}'
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": compute_signature(payload, TEST_SECRET),
    }
    response = await async_client.post(
        "/api/v1/webhooks/github",
        content=payload,
        headers=headers,
    )
    assert response.status_code == 400
    assert "Missing X-GitHub-Delivery header" in response.json()["detail"]


@pytest.mark.unit
async def test_webhook_endpoint_missing_event_header(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify missing X-GitHub-Event returns 400 Bad Request."""
    payload = b'{"action":"opened"}'
    headers = {
        "X-GitHub-Delivery": str(uuid.uuid4()),
        "X-Hub-Signature-256": compute_signature(payload, TEST_SECRET),
    }
    response = await async_client.post(
        "/api/v1/webhooks/github",
        content=payload,
        headers=headers,
    )
    assert response.status_code == 400
    assert "Missing X-GitHub-Event header" in response.json()["detail"]


# ==============================================================================
# 3. SUPPORTED EVENT TRIAGE TESTS (opened, synchronize, reopened)
# ==============================================================================


@pytest.mark.integration
async def test_webhook_pull_request_opened_success(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify pull_request.opened returns 202 and is marked accepted."""
    delivery_id = str(uuid.uuid4())
    raw_payload = json.dumps(build_pr_payload(action="opened", number=101)).encode()
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": compute_signature(raw_payload, TEST_SECRET),
        "Content-Type": "application/json",
    }

    response = await async_client.post(
        "/api/v1/webhooks/github",
        content=raw_payload,
        headers=headers,
    )
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "accepted"
    assert data["delivery_id"] == delivery_id
    assert data["event"] == "pull_request"
    assert data["action"] == "opened"


@pytest.mark.integration
async def test_webhook_pull_request_synchronize_success(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify pull_request.synchronize returns 202 and is marked accepted."""
    delivery_id = str(uuid.uuid4())
    raw_payload = json.dumps(
        build_pr_payload(action="synchronize", number=102)
    ).encode()
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": compute_signature(raw_payload, TEST_SECRET),
        "Content-Type": "application/json",
    }

    response = await async_client.post(
        "/api/v1/webhooks/github",
        content=raw_payload,
        headers=headers,
    )
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "accepted"
    assert data["delivery_id"] == delivery_id
    assert data["action"] == "synchronize"


@pytest.mark.integration
async def test_webhook_pull_request_reopened_success(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify pull_request.reopened returns 202 and is marked accepted."""
    delivery_id = str(uuid.uuid4())
    raw_payload = json.dumps(build_pr_payload(action="reopened", number=103)).encode()
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": compute_signature(raw_payload, TEST_SECRET),
        "Content-Type": "application/json",
    }

    response = await async_client.post(
        "/api/v1/webhooks/github",
        content=raw_payload,
        headers=headers,
    )
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "accepted"
    assert data["delivery_id"] == delivery_id
    assert data["action"] == "reopened"


# ==============================================================================
# 4. UNSUPPORTED EVENTS & ACTIONS TESTS
# ==============================================================================


@pytest.mark.integration
async def test_webhook_unsupported_event_ignored(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify non-PR events (e.g. ping, push) are acknowledged but marked ignored."""
    delivery_id = str(uuid.uuid4())
    raw_payload = b'{"zen": "Non-blocking is better than blocking."}'
    headers = {
        "X-GitHub-Event": "ping",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": compute_signature(raw_payload, TEST_SECRET),
        "Content-Type": "application/json",
    }

    response = await async_client.post(
        "/api/v1/webhooks/github",
        content=raw_payload,
        headers=headers,
    )
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "ignored"
    assert data["delivery_id"] == delivery_id
    assert data["event"] == "ping"
    assert "ignored" in data["message"]


@pytest.mark.integration
async def test_webhook_unsupported_action_ignored(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify unsupported PR actions (e.g. closed, labeled) are acknowledged as ignored."""
    delivery_id = str(uuid.uuid4())
    raw_payload = json.dumps(build_pr_payload(action="closed", number=104)).encode()
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": compute_signature(raw_payload, TEST_SECRET),
        "Content-Type": "application/json",
    }

    response = await async_client.post(
        "/api/v1/webhooks/github",
        content=raw_payload,
        headers=headers,
    )
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "ignored"
    assert data["delivery_id"] == delivery_id
    assert data["action"] == "closed"
    assert "ignored" in data["message"]


@pytest.mark.integration
async def test_webhook_malformed_pull_request_payload_422(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify malformed PR payloads trigger 422 Unprocessable Content."""
    delivery_id = str(uuid.uuid4())
    # Missing required 'pull_request' object in payload
    raw_payload = b'{"action": "opened", "number": 1}'
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": compute_signature(raw_payload, TEST_SECRET),
        "Content-Type": "application/json",
    }

    response = await async_client.post(
        "/api/v1/webhooks/github",
        content=raw_payload,
        headers=headers,
    )
    assert response.status_code == 422
    assert "Malformed pull_request webhook payload" in response.json()["detail"]


# ==============================================================================
# 5. IDEMPOTENCY & DEDUPLICATION TESTS
# ==============================================================================


@pytest.mark.integration
async def test_webhook_idempotency_duplicate_delivery(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify sending identical X-GitHub-Delivery twice marks second call as duplicate."""
    delivery_id = str(uuid.uuid4())
    raw_payload = json.dumps(build_pr_payload(action="opened", number=105)).encode()
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": compute_signature(raw_payload, TEST_SECRET),
        "Content-Type": "application/json",
    }

    # First delivery: accepted
    resp1 = await async_client.post(
        "/api/v1/webhooks/github",
        content=raw_payload,
        headers=headers,
    )
    assert resp1.status_code == 202
    assert resp1.json()["status"] == "accepted"

    # Second delivery with same delivery_id: recognized as duplicate
    resp2 = await async_client.post(
        "/api/v1/webhooks/github",
        content=raw_payload,
        headers=headers,
    )
    assert resp2.status_code == 202
    data2 = resp2.json()
    assert data2["status"] == "duplicate"
    assert data2["delivery_id"] == delivery_id
    assert "already been processed" in data2["message"]


@pytest.mark.integration
async def test_webhook_independent_deliveries_processed(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify different delivery IDs are processed independently."""
    delivery_id_1 = str(uuid.uuid4())
    delivery_id_2 = str(uuid.uuid4())
    raw_payload = json.dumps(build_pr_payload(action="opened", number=106)).encode()

    headers1 = {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id_1,
        "X-Hub-Signature-256": compute_signature(raw_payload, TEST_SECRET),
        "Content-Type": "application/json",
    }
    headers2 = {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id_2,
        "X-Hub-Signature-256": compute_signature(raw_payload, TEST_SECRET),
        "Content-Type": "application/json",
    }

    resp1 = await async_client.post(
        "/api/v1/webhooks/github", content=raw_payload, headers=headers1
    )
    resp2 = await async_client.post(
        "/api/v1/webhooks/github", content=raw_payload, headers=headers2
    )

    assert resp1.status_code == 202
    assert resp1.json()["status"] == "accepted"
    assert resp2.status_code == 202
    assert resp2.json()["status"] == "accepted"


@pytest.mark.integration
async def test_unauthenticated_duplicate_rejected_before_idempotency(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify duplicate delivery with invalid signature is rejected with 401."""
    delivery_id = str(uuid.uuid4())
    raw_payload = json.dumps(build_pr_payload(action="opened", number=107)).encode()

    valid_headers = {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": compute_signature(raw_payload, TEST_SECRET),
        "Content-Type": "application/json",
    }
    resp1 = await async_client.post(
        "/api/v1/webhooks/github", content=raw_payload, headers=valid_headers
    )
    assert resp1.status_code == 202

    # Second request with identical delivery_id but bad signature must be 401
    bad_headers = {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": "sha256=invalidhex00000000000000000000000000000000000000000000000000000000",
        "Content-Type": "application/json",
    }
    resp2 = await async_client.post(
        "/api/v1/webhooks/github", content=raw_payload, headers=bad_headers
    )
    assert resp2.status_code == 401


# ==============================================================================
# 6. PERSISTENCE & TRANSACTION TESTS
# ==============================================================================


@pytest.mark.integration
async def test_webhook_delivery_persisted_in_database(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify WebhookDelivery entity is persisted in PostgreSQL with correct columns."""
    delivery_id = str(uuid.uuid4())
    raw_payload = json.dumps(build_pr_payload(action="opened", number=108)).encode()
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": compute_signature(raw_payload, TEST_SECRET),
        "Content-Type": "application/json",
    }

    response = await async_client.post(
        "/api/v1/webhooks/github", content=raw_payload, headers=headers
    )
    assert response.status_code == 202

    # Directly inspect PostgreSQL database record
    async for session in get_db_session():
        stmt = select(WebhookDelivery).where(WebhookDelivery.delivery_id == delivery_id)
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()
        assert record is not None
        assert record.delivery_id == delivery_id
        assert record.event_type == "pull_request"
        assert record.action == "opened"
        assert record.pr_number == 108
        assert record.status == "accepted"
        assert record.head_sha == "6dcb09b5b57875f334f61aebed695e2e4193db5e"
        assert record.delivered_at is not None


@pytest.mark.unit
async def test_webhook_service_integrity_error_handled_as_duplicate() -> None:
    """Verify IntegrityError on delivery commit triggers rollback and duplicate response."""
    service = WebhookService()
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.execute = AsyncMock(
        return_value=AsyncMock(scalar_one_or_none=lambda: None)
    )
    mock_session.commit = AsyncMock(
        side_effect=IntegrityError("duplicate key", params=None, orig=Exception())
    )
    mock_session.rollback = AsyncMock()

    raw_payload = json.dumps(build_pr_payload(action="opened", number=109)).encode()
    delivery_id = str(uuid.uuid4())

    response = await service.process_webhook(
        event_type="pull_request",
        delivery_id=delivery_id,
        raw_body=raw_payload,
        session=mock_session,
        redis_client=None,
    )

    assert response.status == "duplicate"
    assert response.delivery_id == delivery_id
    assert mock_session.rollback.call_count == 1


# ==============================================================================
# 7. SECURITY & CREDENTIAL NON-DISCLOSURE TESTS
# ==============================================================================


@pytest.mark.unit
async def test_security_credentials_not_in_responses(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify webhook secret, signature, and sensitive tokens never appear in response."""
    delivery_id = str(uuid.uuid4())
    raw_payload = json.dumps(build_pr_payload(action="opened", number=110)).encode()
    sig = compute_signature(raw_payload, TEST_SECRET)

    headers = {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": sig,
        "Content-Type": "application/json",
    }

    response = await async_client.post(
        "/api/v1/webhooks/github", content=raw_payload, headers=headers
    )
    assert response.status_code == 202

    response_text = response.text.lower()
    assert TEST_SECRET.lower() not in response_text
    assert sig.lower() not in response_text
    assert "postgresql" not in response_text
    assert "redis" not in response_text


@pytest.mark.unit
def test_hmac_invalid_secret_type_rejected() -> None:
    """Verify invalid secret type (e.g. integer) is rejected."""
    payload = b'{"test": 1}'
    sig = compute_signature(payload, TEST_SECRET)
    # Passing an invalid type instead of str or SecretStr
    assert verify_github_signature(payload, sig, 12345) is False  # type: ignore[arg-type]


@pytest.mark.unit
async def test_webhook_delivery_model_repr() -> None:
    """Verify __repr__ method of WebhookDelivery model."""
    record = WebhookDelivery(
        delivery_id="deliv-1234",
        event_type="pull_request",
        status="accepted",
    )
    repr_str = repr(record)
    assert "deliv-1234" in repr_str
    assert "pull_request" in repr_str
    assert "accepted" in repr_str


@pytest.mark.unit
async def test_webhook_service_redis_failure_falls_back_to_db() -> None:
    """Verify Redis failure in is_duplicate_delivery falls back to DB without crash."""
    service = WebhookService()
    mock_redis = AsyncMock()
    mock_redis.get.side_effect = ConnectionError("Redis cache down")

    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.execute = AsyncMock(
        return_value=AsyncMock(scalar_one_or_none=lambda: None)
    )

    is_dup = await service.is_duplicate_delivery("test-deliv", mock_session, mock_redis)
    assert is_dup is False
    assert mock_session.execute.call_count == 1


@pytest.mark.unit
async def test_webhook_service_redis_cache_hit_returns_true() -> None:
    """Verify Redis cache hit in is_duplicate_delivery returns True without querying DB."""
    service = WebhookService()
    mock_redis = AsyncMock()
    mock_redis.get.return_value = "accepted"

    mock_session = AsyncMock(spec=AsyncSession)
    is_dup = await service.is_duplicate_delivery("test-deliv", mock_session, mock_redis)
    assert is_dup is True
    assert mock_session.execute.call_count == 0


@pytest.mark.unit
async def test_webhook_service_redis_set_failure_is_non_fatal() -> None:
    """Verify Redis failure during _record_delivery does not prevent successful persistence."""
    service = WebhookService()
    mock_redis = AsyncMock()
    mock_redis.set.side_effect = ConnectionError("Redis write failed")

    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.execute = AsyncMock(
        return_value=AsyncMock(scalar_one_or_none=lambda: None)
    )
    mock_session.commit = AsyncMock()

    persisted = await service._record_delivery(
        session=mock_session,
        delivery_id="deliv-xyz",
        event_type="pull_request",
        delivery_status="accepted",
        redis_client=mock_redis,
    )
    assert persisted is True
    assert mock_session.commit.call_count == 1
