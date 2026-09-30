"""Unit and integration tests for GitHubService and PullRequestContext extraction."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from app.github.auth import GitHubAppAuthenticator
from app.github.errors import (
    GitHubCommitMismatchError,
    GitHubConfigurationError,
    GitHubNotFoundError,
)
from app.schemas.github import (
    PullRequestContext,
)
from app.services.github_service import GitHubService, get_github_service


@pytest.fixture
def sample_unified_diff() -> str:
    return (
        "diff --git a/calculator.py b/calculator.py\n"
        "index 1111111..2222222 100644\n"
        "--- a/calculator.py\n"
        "+++ b/calculator.py\n"
        "@@ -10,3 +10,5 @@ def add(a, b):\n"
        " def add(a, b):\n"
        "     return a + b\n"
        "+def multiply(a, b):\n"
        "+    return a * b\n"
        " \n"
    )


@pytest.mark.asyncio
async def test_get_pull_request_context_success(sample_unified_diff: str) -> None:
    """Verify end-to-end PR context extraction, parsing, and model assembly."""
    head_sha = "6dcb09b5b57875f334f61aebed695e2e4193db5e"
    base_sha = "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b"

    def mock_handler(request: httpx.Request) -> httpx.Response:
        url_path = request.url.path

        # 1. Installation token exchange
        if "/access_tokens" in url_path:
            return httpx.Response(
                status_code=201,
                json={
                    "token": "ghs_testToken12345",
                    "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                    "permissions": {"pull_requests": "read"},
                },
            )

        # 2. PR files
        if url_path.endswith("/files"):
            return httpx.Response(
                status_code=200,
                json=[
                    {
                        "filename": "calculator.py",
                        "status": "modified",
                        "additions": 2,
                        "deletions": 0,
                        "changes": 2,
                        "patch": "@@ -10,4 +10,5 @@\n+def multiply(a, b):\n+    return a * b",
                    }
                ],
            )

        # 3. PR metadata vs diff
        if request.headers.get("Accept") == "application/vnd.github.v3.diff":
            return httpx.Response(status_code=200, text=sample_unified_diff)

        # PR metadata JSON
        return httpx.Response(
            status_code=200,
            json={
                "id": 999111,
                "number": 42,
                "title": "Add multiplication function",
                "state": "open",
                "head": {"sha": head_sha, "ref": "feature/calc", "repo": {"id": 888}},
                "base": {"sha": base_sha, "ref": "main", "repo": {"id": 888}},
                "user": {"login": "developer"},
            },
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        authenticator = GitHubAppAuthenticator(
            app_id=123,
            private_key="test_key",
            http_client=http_client,
        )
        # Monkeypatch authenticator to return dummy JWT
        authenticator.create_app_jwt = lambda **_kw: "mock_jwt"  # type: ignore[method-assign]

        service = GitHubService(authenticator=authenticator, http_client=http_client)

        context = await service.get_pull_request_context(
            repo_full_name="octocat/Hello-World",
            pr_number=42,
            expected_head_sha=head_sha,
            expected_base_sha=base_sha,
            installation_id=10001,
        )

        assert isinstance(context, PullRequestContext)
        assert context.repository_full_name == "octocat/Hello-World"
        assert context.pr_number == 42
        assert context.head_sha == head_sha
        assert context.base_sha == base_sha
        assert context.metadata.title == "Add multiplication function"
        assert len(context.files) == 1
        assert context.files[0].filename == "calculator.py"

        # Verify deterministic diff parser was utilized
        assert context.parsed_diff.total_files == 1
        assert context.parsed_diff.total_hunks == 1
        assert context.parsed_diff.files[0].path == "calculator.py"
        assert context.parsed_diff.files[0].hunks[0].new_count == 5


@pytest.mark.asyncio
async def test_get_pull_request_context_sha_mismatch() -> None:
    """Verify GitHubCommitMismatchError is raised when PR head SHA has changed."""
    expected_sha = "6dcb09b5b57875f334f61aebed695e2e4193db5e"
    actual_new_sha = "ffffffffffffffffffffffffffffffffffffffff"

    def mock_handler(request: httpx.Request) -> httpx.Response:
        if "/access_tokens" in request.url.path:
            return httpx.Response(
                status_code=201,
                json={
                    "token": "ghs_testToken",
                    "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                },
            )
        return httpx.Response(
            status_code=200,
            json={
                "id": 999111,
                "number": 42,
                "title": "Title",
                "state": "open",
                "head": {"sha": actual_new_sha, "ref": "feature", "repo": {"id": 888}},
                "base": {
                    "sha": "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b",
                    "ref": "main",
                    "repo": {"id": 888},
                },
            },
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        authenticator = GitHubAppAuthenticator(
            app_id=123, private_key="test_key", http_client=http_client
        )
        authenticator.create_app_jwt = lambda **_kw: "mock_jwt"  # type: ignore[method-assign]

        service = GitHubService(authenticator=authenticator, http_client=http_client)

        with pytest.raises(GitHubCommitMismatchError) as exc_info:
            await service.get_pull_request_context(
                repo_full_name="octocat/Hello-World",
                pr_number=42,
                expected_head_sha=expected_sha,
                installation_id=10001,
            )

        assert exc_info.value.expected_sha == expected_sha
        assert exc_info.value.retrieved_sha == actual_new_sha
        assert "Commit SHA mismatch" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_pull_request_context_missing_installation_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify error when installation ID is neither passed nor configured."""
    monkeypatch.setattr("app.core.config.settings.GITHUB_APP_INSTALLATION_ID", None)
    service = GitHubService()

    with pytest.raises(GitHubConfigurationError, match="installation ID is required"):
        await service.get_pull_request_context(
            repo_full_name="octocat/Hello-World",
            pr_number=42,
            expected_head_sha="6dcb09b5b57875f334f61aebed695e2e4193db5e",
            installation_id=None,
        )


@pytest.mark.asyncio
async def test_get_pull_request_context_upstream_error() -> None:
    """Verify upstream GitHub REST errors propagate as typed exceptions."""

    def mock_handler(request: httpx.Request) -> httpx.Response:
        if "/access_tokens" in request.url.path:
            return httpx.Response(
                status_code=201,
                json={
                    "token": "ghs_testToken",
                    "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                },
            )
        return httpx.Response(status_code=404, json={"message": "Not Found"})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        authenticator = GitHubAppAuthenticator(
            app_id=123, private_key="test_key", http_client=http_client
        )
        authenticator.create_app_jwt = lambda **_kw: "mock_jwt"  # type: ignore[method-assign]
        service = GitHubService(authenticator=authenticator, http_client=http_client)

        with pytest.raises(GitHubNotFoundError):
            await service.get_pull_request_context(
                repo_full_name="octocat/Hello-World",
                pr_number=42,
                expected_head_sha="6dcb09b5b57875f334f61aebed695e2e4193db5e",
                installation_id=10001,
            )


def test_get_github_service_provider() -> None:
    """Verify get_github_service provider returns instance."""
    service = get_github_service()
    assert isinstance(service, GitHubService)


@pytest.mark.asyncio
async def test_get_pull_request_context_base_sha_discrepancy(
    sample_unified_diff: str,
) -> None:
    """Verify base SHA discrepancy is logged as a warning without failing execution."""
    head_sha = "6dcb09b5b57875f334f61aebed695e2e4193db5e"
    retrieved_base_sha = "1111111111111111111111111111111111111111"
    expected_base_sha = "2222222222222222222222222222222222222222"

    def mock_handler(request: httpx.Request) -> httpx.Response:
        if "/access_tokens" in request.url.path:
            return httpx.Response(
                status_code=201,
                json={
                    "token": "tok",
                    "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                },
            )
        if request.headers.get("Accept") == "application/vnd.github.v3.diff":
            return httpx.Response(status_code=200, text=sample_unified_diff)
        if request.url.path.endswith("/files"):
            return httpx.Response(status_code=200, json=[])
        return httpx.Response(
            status_code=200,
            json={
                "id": 1,
                "number": 1,
                "title": "T",
                "state": "open",
                "head": {"sha": head_sha, "ref": "feat", "repo": {"id": 1}},
                "base": {"sha": retrieved_base_sha, "ref": "main", "repo": {"id": 1}},
            },
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        auth = GitHubAppAuthenticator(
            app_id=1, private_key="k", http_client=http_client
        )
        auth.create_app_jwt = lambda **_kw: "jwt"  # type: ignore[method-assign]
        service = GitHubService(authenticator=auth, http_client=http_client)

        context = await service.get_pull_request_context(
            repo_full_name="org/repo",
            pr_number=1,
            expected_head_sha=head_sha,
            expected_base_sha=expected_base_sha,
            installation_id=1,
        )
        assert context.head_sha == head_sha
        assert context.base_sha == retrieved_base_sha
