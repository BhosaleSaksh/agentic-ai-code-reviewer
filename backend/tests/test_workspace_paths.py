"""Unit tests for workspace path resolution and path traversal protection.

Validates that:
- Clean paths are created inside REVIEW_WORKSPACE_ROOT.
- Path traversal sequences (../, ..\\, embedded separators) are rejected.
- Invalid repository IDs, PR numbers, or commit SHAs are rejected.
- Null bytes and drive-letter escapes are rejected.
"""

from pathlib import Path

import pytest
from app.services.workspace_errors import WorkspacePathTraversalError
from app.services.workspace_manager import WorkspaceManager


@pytest.fixture
def workspace_manager(tmp_path: Path) -> WorkspaceManager:
    """Fixture providing a WorkspaceManager configured with a temporary root."""
    return WorkspaceManager(workspace_root=tmp_path)


@pytest.mark.unit
def test_resolve_workspace_path_valid(
    workspace_manager: WorkspaceManager, tmp_path: Path
) -> None:
    """Verify standard valid inputs produce a properly contained, canonical path."""
    repo_id = 1296269
    pr_number = 42
    head_sha = "6dcb09b5b57875f334f61aebed695e2e4193db5e"

    resolved = workspace_manager.resolve_workspace_path(repo_id, pr_number, head_sha)

    assert resolved.is_relative_to(tmp_path)
    assert resolved.name == head_sha.lower()
    assert resolved.parent.name == f"pr_{pr_number}"
    assert resolved.parent.parent.name == str(repo_id)


@pytest.mark.unit
def test_resolve_workspace_path_case_normalization(
    workspace_manager: WorkspaceManager, tmp_path: Path
) -> None:
    """Verify uppercase SHA is normalized to lowercase for filesystem consistency."""
    repo_id = 999
    pr_number = 10
    head_sha = "6DCB09B5B57875F334F61AEBED695E2E4193DB5E"

    resolved = workspace_manager.resolve_workspace_path(repo_id, pr_number, head_sha)

    assert resolved.name == head_sha.lower()
    assert resolved.is_relative_to(tmp_path)


@pytest.mark.unit
@pytest.mark.parametrize(
    "invalid_repo_id",
    [0, -1, -999, "123", None, 3.14],
)
def test_resolve_workspace_path_invalid_repository_id(
    workspace_manager: WorkspaceManager, invalid_repo_id: object
) -> None:
    """Verify invalid repository IDs raise WorkspacePathTraversalError."""
    with pytest.raises(WorkspacePathTraversalError, match="Invalid repository_id"):
        workspace_manager.resolve_workspace_path(
            repository_id=invalid_repo_id,  # type: ignore[arg-type]
            pr_number=1,
            head_sha="6dcb09b5b57875f334f61aebed695e2e4193db5e",
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "invalid_pr_number",
    [0, -1, -50, "42", None, 2.5],
)
def test_resolve_workspace_path_invalid_pr_number(
    workspace_manager: WorkspaceManager, invalid_pr_number: object
) -> None:
    """Verify non-positive or non-integer PR numbers raise WorkspacePathTraversalError."""
    with pytest.raises(WorkspacePathTraversalError, match="Invalid pr_number"):
        workspace_manager.resolve_workspace_path(
            repository_id=100,
            pr_number=invalid_pr_number,  # type: ignore[arg-type]
            head_sha="6dcb09b5b57875f334f61aebed695e2e4193db5e",
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "invalid_sha",
    [
        "../../etc/passwd",
        r"..\..\Windows\System32",
        "short_sha",
        "6dcb09b5b57875f334f61aebed695e2e4193db5e;rm -rf /",
        "6dcb09b5b57875f334f61aebed695e2e4193db5e\x00extra",
        "zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",  # non-hex
        "",
        "6dcb09b5b57875f334f61aebed695e2e4193db5e/extra",
    ],
)
def test_resolve_workspace_path_invalid_head_sha(
    workspace_manager: WorkspaceManager, invalid_sha: str
) -> None:
    """Verify invalid or traversal-attempting head SHAs are strictly rejected."""
    with pytest.raises(WorkspacePathTraversalError, match="Invalid head_sha"):
        workspace_manager.resolve_workspace_path(
            repository_id=100,
            pr_number=1,
            head_sha=invalid_sha,
        )


@pytest.mark.unit
def test_resolve_workspace_path_containment_guarantee(tmp_path: Path) -> None:
    """Verify that resolved paths strictly remain children of workspace_root."""
    custom_root = tmp_path / "custom_workspaces"
    custom_root.mkdir()
    wm = WorkspaceManager(workspace_root=custom_root)

    path = wm.resolve_workspace_path(
        repository_id=555,
        pr_number=7,
        head_sha="1111222233334444555566667777888899990000",
    )

    assert path.is_relative_to(custom_root)
    assert str(path).startswith(str(custom_root.resolve()))
