"""Unit tests for asynchronous authenticated GitHub REST API client."""

import httpx
import pytest
from app.github.client import GitHubClient
from app.github.errors import (
    GitHubAuthenticationError,
    GitHubDiffTooLargeError,
    GitHubNetworkError,
    GitHubNotFoundError,
    GitHubPermissionError,
    GitHubRateLimitError,
    GitHubResponseError,
    GitHubServerError,
)


@pytest.fixture
def mock_pr_payload() -> dict:
    return {
        "id": 101,
        "number": 42,
        "title": "Add feature X",
        "state": "open",
        "html_url": "https://github.com/octocat/Hello-World/pull/42",
        "user": {"login": "octocat"},
        "head": {
            "sha": "6dcb09b5b57875f334f61aebed695e2e4193db5e",
            "ref": "feature-x",
            "repo": {"id": 1296269, "full_name": "octocat/Hello-World"},
        },
        "base": {
            "sha": "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b",
            "ref": "main",
            "repo": {"id": 1296269, "full_name": "octocat/Hello-World"},
        },
        "created_at": "2026-09-30T10:00:00Z",
        "updated_at": "2026-09-30T11:00:00Z",
    }


@pytest.fixture
def mock_files_payload() -> list[dict]:
    return [
        {
            "filename": "src/app.py",
            "status": "modified",
            "additions": 15,
            "deletions": 3,
            "changes": 18,
            "blob_url": "https://github.com/octocat/Hello-World/blob/6dcb/src/app.py",
            "raw_url": "https://github.com/octocat/Hello-World/raw/6dcb/src/app.py",
            "patch": "@@ -1,5 +1,6 @@\n def main():\n+    print('hello')",
        },
        {
            "filename": "old_name.py",
            "status": "renamed",
            "additions": 0,
            "deletions": 0,
            "changes": 0,
            "previous_filename": "previous_name.py",
        },
    ]


@pytest.mark.asyncio
async def test_get_pull_request_success(mock_pr_payload: dict) -> None:
    """Verify get_pull_request parses PR metadata and records rate-limit headers."""

    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/repos/octocat/Hello-World/pulls/42"
        assert request.headers["Authorization"] == "Bearer mock_token_123"
        assert request.headers["Accept"] == "application/vnd.github+json"
        assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"

        headers = {
            "x-ratelimit-limit": "5000",
            "x-ratelimit-remaining": "4995",
            "x-ratelimit-reset": "1727700000",
            "x-ratelimit-used": "5",
            "x-ratelimit-resource": "core",
        }
        return httpx.Response(status_code=200, json=mock_pr_payload, headers=headers)

    transport = httpx.MockTransport(mock_handler)
    async with (
        httpx.AsyncClient(transport=transport) as http_client,
        GitHubClient(token="mock_token_123", http_client=http_client) as client,
    ):
        meta = await client.get_pull_request("octocat/Hello-World", 42)

        assert meta.pr_number == 42
        assert meta.pr_id == 101
        assert meta.repository_id == 1296269
        assert meta.repository_full_name == "octocat/Hello-World"
        assert meta.title == "Add feature X"
        assert meta.state == "open"
        assert meta.head_sha == "6dcb09b5b57875f334f61aebed695e2e4193db5e"
        assert meta.base_sha == "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b"
        assert meta.head_branch == "feature-x"
        assert meta.base_branch == "main"
        assert meta.author == "octocat"
        assert meta.html_url == "https://github.com/octocat/Hello-World/pull/42"

        rate_limit = client.get_last_rate_limit()
        assert rate_limit is not None
        assert rate_limit.limit == 5000
        assert rate_limit.remaining == 4995
        assert rate_limit.used == 5
        assert rate_limit.resource == "core"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "response_headers", "response_body", "expected_exception"),
    [
        (401, {}, {"message": "Bad credentials"}, GitHubAuthenticationError),
        (
            403,
            {"x-ratelimit-remaining": "0"},
            {"message": "Rate limit exceeded"},
            GitHubRateLimitError,
        ),
        (
            403,
            {"x-ratelimit-remaining": "100"},
            {"message": "Resource not accessible by integration"},
            GitHubPermissionError,
        ),
        (404, {}, {"message": "Not Found"}, GitHubNotFoundError),
        (422, {}, {"message": "Validation Failed"}, GitHubResponseError),
        (429, {}, {"message": "Too Many Requests"}, GitHubRateLimitError),
        (500, {}, {"message": "Internal Server Error"}, GitHubServerError),
        (503, {}, {"message": "Service Unavailable"}, GitHubServerError),
    ],
)
async def test_get_pull_request_http_errors(
    status_code: int,
    response_headers: dict[str, str],
    response_body: dict,
    expected_exception: type[Exception],
) -> None:
    """Verify HTTP error codes raise appropriate typed exceptions."""

    def mock_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=status_code, json=response_body, headers=response_headers
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = GitHubClient(token="mock_token", http_client=http_client)
        with pytest.raises(expected_exception):
            await client.get_pull_request("octocat/Hello-World", 42)


@pytest.mark.asyncio
async def test_get_pull_request_network_errors() -> None:
    """Verify timeout and connection errors raise GitHubNetworkError."""

    def timeout_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Timeout")

    transport = httpx.MockTransport(timeout_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = GitHubClient(token="mock_token", http_client=http_client)
        with pytest.raises(GitHubNetworkError, match="Timeout"):
            await client.get_pull_request("octocat/Hello-World", 42)

    def conn_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    transport = httpx.MockTransport(conn_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = GitHubClient(token="mock_token", http_client=http_client)
        with pytest.raises(GitHubNetworkError, match="Network failure"):
            await client.get_pull_request("octocat/Hello-World", 42)


@pytest.mark.asyncio
async def test_get_pull_request_files_success(mock_files_payload: list[dict]) -> None:
    """Verify get_pull_request_files successfully parses file list."""

    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert "/pulls/42/files" in request.url.path
        return httpx.Response(status_code=200, json=mock_files_payload)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = GitHubClient(token="mock_token", http_client=http_client)
        files = await client.get_pull_request_files("octocat/Hello-World", 42)

        assert len(files) == 2
        assert files[0].filename == "src/app.py"
        assert files[0].status == "modified"
        assert files[0].additions == 15
        assert files[0].deletions == 3
        assert files[0].changes == 18
        assert files[0].patch is not None

        assert files[1].filename == "old_name.py"
        assert files[1].status == "renamed"
        assert files[1].previous_filename == "previous_name.py"


@pytest.mark.asyncio
async def test_get_pull_request_files_pagination() -> None:
    """Verify get_pull_request_files paginates through multiple pages up to max_files."""

    def mock_handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", 1))
        if page == 1:
            page_data = [
                {"filename": f"file_{i}.py", "status": "added"} for i in range(100)
            ]
            return httpx.Response(status_code=200, json=page_data)
        elif page == 2:
            page_data = [
                {"filename": f"file_{i}.py", "status": "added"} for i in range(100, 120)
            ]
            return httpx.Response(status_code=200, json=page_data)
        return httpx.Response(status_code=200, json=[])

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = GitHubClient(token="mock_token", http_client=http_client)
        # Fetch with limit = 110
        files = await client.get_pull_request_files(
            "octocat/Hello-World", 42, max_files=110
        )
        assert len(files) == 110


@pytest.mark.asyncio
async def test_get_pull_request_diff_success() -> None:
    """Verify get_pull_request_diff requests diff header and returns raw text."""
    sample_diff = (
        "diff --git a/file.py b/file.py\n"
        "index 1234567..89abcdef 100644\n"
        "--- a/file.py\n"
        "+++ b/file.py\n"
        "@@ -1,3 +1,4 @@\n"
        " context\n"
        "+added line\n"
    )

    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.headers["Accept"] == "application/vnd.github.v3.diff"
        return httpx.Response(status_code=200, text=sample_diff)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = GitHubClient(token="mock_token", http_client=http_client)
        diff_text = await client.get_pull_request_diff("octocat/Hello-World", 42)
        assert diff_text == sample_diff


@pytest.mark.asyncio
async def test_get_pull_request_diff_too_large() -> None:
    """Verify GitHubDiffTooLargeError when diff exceeds maximum byte limit."""
    large_diff = "diff content " * 1000

    def mock_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, text=large_diff)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = GitHubClient(token="mock_token", http_client=http_client)
        with pytest.raises(GitHubDiffTooLargeError, match="exceeds safety boundary"):
            await client.get_pull_request_diff("octocat/Hello-World", 42, max_bytes=100)


@pytest.mark.asyncio
async def test_client_internal_lifecycle_and_close() -> None:
    """Verify GitHubClient initializes and closes its internal HTTP client cleanly."""
    client = GitHubClient(token="secret_token")
    internal = client._get_client()
    assert isinstance(internal, httpx.AsyncClient)
    assert client._internal_client is internal
    await client.close()
    assert client._internal_client is None


@pytest.mark.asyncio
async def test_rate_limit_invalid_headers() -> None:
    """Verify non-integer rate limit headers do not crash rate limit parsing."""
    client = GitHubClient(token="test")
    headers = httpx.Headers(
        {
            "x-ratelimit-limit": "not-an-int",
            "x-ratelimit-remaining": "xyz",
            "x-ratelimit-reset": "invalid",
        }
    )
    client._record_rate_limit(headers)
    assert client.get_last_rate_limit() is None


@pytest.mark.asyncio
async def test_get_pull_request_diff_network_errors() -> None:
    """Verify timeout and network failure in get_pull_request_diff raise GitHubNetworkError."""

    def timeout_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Diff timeout")

    transport = httpx.MockTransport(timeout_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = GitHubClient(token="mock_token", http_client=http_client)
        with pytest.raises(GitHubNetworkError, match="Timeout fetching PR diff"):
            await client.get_pull_request_diff("octocat/Hello-World", 42)

    def conn_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection failed")

    transport = httpx.MockTransport(conn_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = GitHubClient(token="mock_token", http_client=http_client)
        with pytest.raises(
            GitHubNetworkError, match="Network failure fetching PR diff"
        ):
            await client.get_pull_request_diff("octocat/Hello-World", 42)


@pytest.mark.asyncio
async def test_get_pull_request_files_errors() -> None:
    """Verify timeout, connection, and malformed errors in get_pull_request_files."""

    def timeout_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Timeout")

    transport = httpx.MockTransport(timeout_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = GitHubClient(token="mock_token", http_client=http_client)
        with pytest.raises(GitHubNetworkError, match="Timeout fetching PR files"):
            await client.get_pull_request_files("octocat/Hello-World", 42)

    def malformed_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, json={"not": "a list"})

    transport = httpx.MockTransport(malformed_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = GitHubClient(token="mock_token", http_client=http_client)
        with pytest.raises(GitHubResponseError, match="Malformed PR files returned"):
            await client.get_pull_request_files("octocat/Hello-World", 42)
