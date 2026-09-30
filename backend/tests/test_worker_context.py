from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.github.errors import (
    GitHubAuthenticationError,
    GitHubCommitMismatchError,
    GitHubNetworkError,
    GitHubRateLimitError,
    GitHubServerError,
)
from app.schemas.diff import ParsedDiff
from app.schemas.github import (
    GitHubPullRequestFile,
    GitHubPullRequestMetadata,
    PullRequestContext,
)
from app.schemas.job import ReviewJobPayload
from app.schemas.workspace import WorkspaceContext
from app.services.github_service import GitHubService
from app.services.workspace_errors import (
    GitTimeoutError,
)
from app.services.workspace_errors import (
    WorkspaceCommitMismatchError as WsCommitMismatchError,
)
from app.services.workspace_manager import WorkspaceManager
from app.workers.tasks import review_pull_request_job
from arq import Retry


@pytest.fixture
def sample_payload_dict() -> dict:
    return {
        "delivery_id": "72d3162e-cc78-11e3-81ab-4c9367dc09d7",
        "repository_id": 1296269,
        "repository_full_name": "octocat/Hello-World",
        "pr_number": 42,
        "pull_request_id": 990042,
        "head_sha": "6dcb09b5b57875f334f61aebed695e2e4193db5e",
        "base_sha": "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b",
        "action": "opened",
        "event_type": "pull_request",
        "installation_id": 12345678,
    }


@pytest.fixture
def mock_pr_context() -> PullRequestContext:
    head_sha = "6dcb09b5b57875f334f61aebed695e2e4193db5e"
    base_sha = "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b"
    return PullRequestContext(
        repository_id=1296269,
        repository_full_name="octocat/Hello-World",
        pr_number=42,
        head_sha=head_sha,
        base_sha=base_sha,
        metadata=GitHubPullRequestMetadata(
            repository_id=1296269,
            repository_full_name="octocat/Hello-World",
            pr_number=42,
            pr_id=990042,
            title="Sample PR",
            state="open",
            head_sha=head_sha,
            base_sha=base_sha,
            head_branch="feature",
            base_branch="main",
        ),
        files=[
            GitHubPullRequestFile(
                filename="main.py", status="modified", additions=5, deletions=2
            )
        ],
        parsed_diff=ParsedDiff(files=[]),
        raw_diff="diff content",
    )


@pytest.mark.asyncio
async def test_worker_review_job_success(
    sample_payload_dict: dict,
    mock_pr_context: PullRequestContext,
) -> None:
    """Verify worker retrieves PR context and returns execution acknowledgement."""
    mock_github_service = MagicMock(spec=GitHubService)
    mock_github_service.is_configured.return_value = True
    mock_github_service.get_pull_request_context = AsyncMock(
        return_value=mock_pr_context
    )

    ctx = {
        "job_id": "review:72d3162e-cc78-11e3-81ab-4c9367dc09d7",
        "job_try": 1,
        "github_service": mock_github_service,
    }

    result = await review_pull_request_job(ctx, sample_payload_dict)

    assert result["job_id"] == "review:72d3162e-cc78-11e3-81ab-4c9367dc09d7"
    assert result["delivery_id"] == "72d3162e-cc78-11e3-81ab-4c9367dc09d7"
    assert result["repository_full_name"] == "octocat/Hello-World"
    assert result["pr_number"] == 42
    assert result["head_sha"] == "6dcb09b5b57875f334f61aebed695e2e4193db5e"
    assert result["status"] == "acknowledged"

    mock_github_service.get_pull_request_context.assert_awaited_once_with(
        repo_full_name="octocat/Hello-World",
        pr_number=42,
        expected_head_sha="6dcb09b5b57875f334f61aebed695e2e4193db5e",
        expected_base_sha="1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b",
        installation_id=12345678,
    )


@pytest.mark.asyncio
async def test_worker_review_job_sha_mismatch(sample_payload_dict: dict) -> None:
    """Verify worker propagates GitHubCommitMismatchError when PR head commit changed."""
    mock_github_service = MagicMock(spec=GitHubService)
    mock_github_service.is_configured.return_value = True
    mock_github_service.get_pull_request_context = AsyncMock(
        side_effect=GitHubCommitMismatchError(
            message="Commit mismatch",
            expected_sha=sample_payload_dict["head_sha"],
            retrieved_sha="0000000000000000000000000000000000000000",
        )
    )

    ctx = {
        "job_id": "job-1",
        "job_try": 1,
        "github_service": mock_github_service,
    }

    with pytest.raises(GitHubCommitMismatchError):
        await review_pull_request_job(ctx, sample_payload_dict)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "transient_error",
    [
        GitHubRateLimitError("Rate limit exceeded"),
        GitHubServerError("Internal Server Error", status_code=500),
        GitHubNetworkError("Connection timed out"),
    ],
)
async def test_worker_review_job_transient_error_triggers_retry(
    sample_payload_dict: dict,
    transient_error: Exception,
) -> None:
    """Verify transient GitHub failures trigger ARQ Retry with backoff delay."""
    mock_github_service = MagicMock(spec=GitHubService)
    mock_github_service.is_configured.return_value = True
    mock_github_service.get_pull_request_context = AsyncMock(
        side_effect=transient_error
    )

    ctx = {
        "job_id": "job-1",
        "job_try": 1,
        "github_service": mock_github_service,
    }

    with pytest.raises(Retry):
        await review_pull_request_job(ctx, sample_payload_dict)


@pytest.mark.asyncio
async def test_worker_review_job_auth_failure_non_retryable(
    sample_payload_dict: dict,
) -> None:
    """Verify non-retryable authentication failure raises without Retry."""
    mock_github_service = MagicMock(spec=GitHubService)
    mock_github_service.is_configured.return_value = True
    mock_github_service.get_pull_request_context = AsyncMock(
        side_effect=GitHubAuthenticationError("401 Unauthorized")
    )

    ctx = {
        "job_id": "job-1",
        "job_try": 1,
        "github_service": mock_github_service,
    }

    with pytest.raises(GitHubAuthenticationError):
        await review_pull_request_job(ctx, sample_payload_dict)


@pytest.mark.asyncio
async def test_worker_review_job_unconfigured_falls_back_cleanly(
    sample_payload_dict: dict,
) -> None:
    """Verify worker cleanly acknowledges job when GitHub App is not configured."""
    mock_github_service = MagicMock(spec=GitHubService)
    mock_github_service.is_configured.return_value = False

    ctx = {
        "job_id": "job-unconfigured",
        "job_try": 1,
        # note: do not put "github_service" in ctx so it simulates unconfigured environment
    }

    result = await review_pull_request_job(ctx, sample_payload_dict)
    assert result["status"] == "acknowledged"


@pytest.mark.asyncio
async def test_end_to_end_webhook_to_worker_to_pr_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full integration test:

    Webhook Request
        ↓
    HMAC Verification
        ↓
    Triage & Idempotency
        ↓
    ARQ Job Creation
        ↓
    Worker Execution
        ↓
    GitHub App Auth & Token Exchange
        ↓
    PR Metadata, Files & Unified Diff
        ↓
    Diff Parser
        ↓
    Verified PullRequestContext
        ↓
    Worker Acknowledgement
    """
    import hashlib
    import hmac
    import json
    import uuid

    import httpx
    from app.core.config import settings
    from app.github.auth import GitHubAppAuthenticator
    from app.services.github_service import GitHubService
    from pydantic import SecretStr

    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", SecretStr(secret))

    head_sha = "6dcb09b5b57875f334f61aebed695e2e4193db5e"
    base_sha = "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b"
    sample_diff = (
        "diff --git a/app.py b/app.py\n"
        "index 1111111..2222222 100644\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1,3 +1,4 @@\n"
        " def main():\n"
        "+    print('running')\n"
        "     return 0\n"
        " \n"
    )

    def mock_github_transport(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/access_tokens" in path:
            return httpx.Response(
                status_code=201,
                json={
                    "token": "ghs_e2eToken12345",
                    "expires_at": "2026-09-30T18:00:00Z",
                },
            )
        if request.headers.get("Accept") == "application/vnd.github.v3.diff":
            return httpx.Response(status_code=200, text=sample_diff)
        if path.endswith("/files"):
            return httpx.Response(
                status_code=200,
                json=[
                    {
                        "filename": "app.py",
                        "status": "modified",
                        "additions": 1,
                        "deletions": 0,
                        "changes": 1,
                    }
                ],
            )
        return httpx.Response(
            status_code=200,
            json={
                "id": 880011,
                "number": 99,
                "title": "E2E Test PR",
                "state": "open",
                "head": {"sha": head_sha, "ref": "feature", "repo": {"id": 1234}},
                "base": {"sha": base_sha, "ref": "main", "repo": {"id": 1234}},
            },
        )

    github_mock_client = httpx.AsyncClient(
        transport=httpx.MockTransport(mock_github_transport)
    )

    authenticator = GitHubAppAuthenticator(
        app_id=123,
        private_key="test_key",
        http_client=github_mock_client,
    )
    authenticator.create_app_jwt = lambda **_kw: "mock_jwt"  # type: ignore[method-assign]
    github_service = GitHubService(
        authenticator=authenticator, http_client=github_mock_client
    )

    # 1. Prepare webhook payload and HMAC signature
    delivery_id = str(uuid.uuid4())
    secret = "test-webhook-secret"
    payload = {
        "action": "opened",
        "number": 99,
        "pull_request": {
            "id": 880011,
            "number": 99,
            "title": "E2E Test PR",
            "state": "open",
            "head": {"sha": head_sha, "ref": "feature"},
            "base": {"sha": base_sha, "ref": "main"},
        },
        "repository": {
            "id": 1234,
            "name": "Hello-World",
            "full_name": "octocat/Hello-World",
        },
        "installation": {"id": 555666},
    }
    raw_payload = json.dumps(payload).encode()
    mac = hmac.new(secret.encode(), raw_payload, hashlib.sha256).hexdigest()
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": f"sha256={mac}",
        "Content-Type": "application/json",
    }

    from unittest.mock import AsyncMock

    from app.api.v1.webhooks import get_queue_service
    from app.main import app
    from app.services.queue_service import ReviewJobQueueService

    captured_payloads: list[ReviewJobPayload] = []
    mock_queue = AsyncMock(spec=ReviewJobQueueService)

    async def capture_enqueue(job_payload: ReviewJobPayload) -> str:
        captured_payloads.append(job_payload)
        return f"review:{job_payload.delivery_id}"

    mock_queue.enqueue_review_job.side_effect = capture_enqueue
    app.dependency_overrides[get_queue_service] = lambda: mock_queue

    try:
        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as test_client:
            response = await test_client.post(
                "/api/v1/webhooks/github", content=raw_payload, headers=headers
            )
            assert response.status_code == 202
            assert response.json()["status"] == "accepted"
            assert len(captured_payloads) == 1
    finally:
        app.dependency_overrides.pop(get_queue_service, None)

    # 2. Worker executes job
    enqueued_job = captured_payloads[0]
    assert enqueued_job.installation_id == 555666
    assert enqueued_job.head_sha == head_sha

    ctx = {
        "job_id": f"review:{delivery_id}",
        "job_try": 1,
        "github_service": github_service,
    }
    result = await review_pull_request_job(ctx, enqueued_job.model_dump())

    assert result["status"] == "acknowledged"
    assert result["delivery_id"] == delivery_id
    assert result["head_sha"] == head_sha
    assert result["pr_number"] == 99


@pytest.fixture
def mock_workspace_context() -> WorkspaceContext:
    head_sha = "6dcb09b5b57875f334f61aebed695e2e4193db5e"
    return WorkspaceContext(
        workspace_id="ws-1296269-pr42-6dcb09b5b578",
        workspace_path=Path(
            "/tmp/workspaces/1296269/pr_42/6dcb09b5b57875f334f61aebed695e2e4193db5e"
        ),
        repository_id=1296269,
        repository_full_name="octocat/Hello-World",
        pr_number=42,
        expected_head_sha=head_sha,
        actual_head_sha=head_sha,
        is_detached_head=True,
    )


@pytest.mark.asyncio
async def test_worker_review_job_with_workspace_manager_success(
    sample_payload_dict: dict,
    mock_pr_context: PullRequestContext,
    mock_workspace_context: WorkspaceContext,
) -> None:
    """Verify worker orchestrates PR context extraction and workspace preparation."""
    mock_github_service = MagicMock(spec=GitHubService)
    mock_github_service.is_configured.return_value = True
    mock_github_service.get_pull_request_context = AsyncMock(
        return_value=mock_pr_context
    )

    mock_wm = MagicMock(spec=WorkspaceManager)
    mock_wm.is_configured.return_value = True

    @asynccontextmanager
    async def mock_prepare(**_kwargs: object) -> AsyncIterator[WorkspaceContext]:
        yield mock_workspace_context

    mock_wm.prepare = mock_prepare

    ctx = {
        "job_id": "review:ws-success",
        "job_try": 1,
        "github_service": mock_github_service,
        "workspace_manager": mock_wm,
    }

    result = await review_pull_request_job(ctx, sample_payload_dict)

    assert result["status"] == "acknowledged"
    assert result["head_sha"] == mock_pr_context.head_sha


@pytest.mark.asyncio
async def test_worker_review_job_workspace_timeout_triggers_retry(
    sample_payload_dict: dict,
    mock_pr_context: PullRequestContext,
) -> None:
    """Verify Git timeout during workspace checkout triggers ARQ retry."""
    mock_github_service = MagicMock(spec=GitHubService)
    mock_github_service.is_configured.return_value = True
    mock_github_service.get_pull_request_context = AsyncMock(
        return_value=mock_pr_context
    )

    mock_wm = MagicMock(spec=WorkspaceManager)
    mock_wm.is_configured.return_value = True

    @asynccontextmanager
    async def mock_prepare(**_kwargs: object) -> AsyncIterator[None]:
        raise GitTimeoutError("Git command timed out", command=["fetch"], timeout=60.0)
        yield  # pragma: no cover

    mock_wm.prepare = mock_prepare

    ctx = {
        "job_id": "review:ws-timeout",
        "job_try": 1,
        "github_service": mock_github_service,
        "workspace_manager": mock_wm,
    }

    with pytest.raises(Retry):
        await review_pull_request_job(ctx, sample_payload_dict)


@pytest.mark.asyncio
async def test_worker_review_job_workspace_mismatch_fails_immediately(
    sample_payload_dict: dict,
    mock_pr_context: PullRequestContext,
) -> None:
    """Verify WorkspaceCommitMismatchError fails immediately without retry."""
    mock_github_service = MagicMock(spec=GitHubService)
    mock_github_service.is_configured.return_value = True
    mock_github_service.get_pull_request_context = AsyncMock(
        return_value=mock_pr_context
    )

    mock_wm = MagicMock(spec=WorkspaceManager)
    mock_wm.is_configured.return_value = True

    @asynccontextmanager
    async def mock_prepare(**_kwargs: object) -> AsyncIterator[None]:
        raise WsCommitMismatchError(
            "SHA mismatch", expected_sha="a" * 40, actual_sha="b" * 40
        )
        yield  # pragma: no cover

    mock_wm.prepare = mock_prepare

    ctx = {
        "job_id": "review:ws-mismatch",
        "job_try": 1,
        "github_service": mock_github_service,
        "workspace_manager": mock_wm,
    }

    with pytest.raises(WsCommitMismatchError):
        await review_pull_request_job(ctx, sample_payload_dict)


@pytest.mark.asyncio
async def test_worker_review_job_default_workspace_instantiated_when_app_configured(
    monkeypatch: pytest.MonkeyPatch,
    sample_payload_dict: dict,
    mock_pr_context: PullRequestContext,
    mock_workspace_context: WorkspaceContext,
) -> None:
    """Verify default WorkspaceManager is instantiated when GitHub App is configured."""
    from app.core.config import settings
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "GITHUB_APP_ID", 123456)
    monkeypatch.setattr(settings, "GITHUB_APP_PRIVATE_KEY", SecretStr("mock_key"))

    mock_github_service = MagicMock(spec=GitHubService)
    mock_github_service.is_configured.return_value = True
    mock_github_service.get_pull_request_context = AsyncMock(
        return_value=mock_pr_context
    )

    @asynccontextmanager
    async def mock_prepare(**_kwargs: object) -> AsyncIterator[WorkspaceContext]:
        yield mock_workspace_context

    with patch("app.workers.tasks.WorkspaceManager") as mock_wm_class:
        instance = mock_wm_class.return_value
        instance.is_configured.return_value = True
        instance.prepare = mock_prepare

        ctx = {
            "job_id": "review:default-wm",
            "job_try": 1,
            "github_service": mock_github_service,
        }

        result = await review_pull_request_job(ctx, sample_payload_dict)
        assert result["status"] == "acknowledged"
        mock_wm_class.assert_called_once()
