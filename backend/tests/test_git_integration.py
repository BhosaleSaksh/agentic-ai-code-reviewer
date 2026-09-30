"""Integration test using real local Git repositories and processes.

Section 24 Compliance:
Proves end-to-end repository creation, multiple commits, exact commit checkout,
detached HEAD verification, filesystem state validation, and clean teardown
without requiring GitHub credentials or external network access.
"""

from pathlib import Path

import pytest
from app.services.git_runner import GitRunner
from app.services.workspace_manager import WorkspaceManager


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_git_repository_checkout_integration(tmp_path: Path) -> None:
    """Verify WorkspaceManager performs exact commit checkout against a real Git repository."""
    runner = GitRunner()
    if not runner.is_git_available():
        pytest.fail("Git binary is required for integration tests but was not found.")

    source_repo_dir = tmp_path / "source_repo"
    source_repo_dir.mkdir(parents=True, exist_ok=True)
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir(parents=True, exist_ok=True)

    # 1. Initialize real Git source repository
    await runner.run(["init"], cwd=source_repo_dir)
    await runner.run(["config", "user.name", "Integration Tester"], cwd=source_repo_dir)
    await runner.run(
        ["config", "user.email", "integration@test.local"], cwd=source_repo_dir
    )
    # Enable fileMode false for Windows compatibility
    await runner.run(["config", "core.fileMode", "false"], cwd=source_repo_dir)

    # 2. Create Commit 1: calculator.py
    calc_file = source_repo_dir / "calculator.py"
    calc_file.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    await runner.run(["add", "calculator.py"], cwd=source_repo_dir)
    await runner.run(
        ["commit", "-m", "Initial commit: add calculator"], cwd=source_repo_dir
    )
    res_sha1 = await runner.run(["rev-parse", "HEAD"], cwd=source_repo_dir)
    commit_1_sha = res_sha1.stdout.strip()
    assert len(commit_1_sha) == 40

    # 3. Create Commit 2: feature.py
    feat_file = source_repo_dir / "feature.py"
    feat_file.write_text("def multiply(a, b):\n    return a * b\n", encoding="utf-8")
    await runner.run(["add", "feature.py"], cwd=source_repo_dir)
    await runner.run(
        ["commit", "-m", "Second commit: add feature"], cwd=source_repo_dir
    )
    res_sha2 = await runner.run(["rev-parse", "HEAD"], cwd=source_repo_dir)
    commit_2_sha = res_sha2.stdout.strip()
    assert len(commit_2_sha) == 40
    assert commit_1_sha != commit_2_sha

    # 4. Invoke WorkspaceManager to checkout Commit 1 specifically
    wm = WorkspaceManager(workspace_root=workspace_root)
    workspace_dir_path: Path | None = None

    async with wm.prepare(
        repository_id=777,
        repository_full_name="test-org/test-repo",
        pr_number=15,
        head_sha=commit_1_sha,
        source_repo_url=str(source_repo_dir),
    ) as ws:
        workspace_dir_path = ws.workspace_path

        # 5. Verify exact commit checkout and metadata
        assert ws.actual_head_sha.lower() == commit_1_sha.lower()
        assert ws.expected_head_sha.lower() == commit_1_sha.lower()
        assert ws.is_detached_head is True
        assert ws.size_bytes > 0
        assert workspace_dir_path.exists()

        # 6. Verify filesystem contents match Commit 1 exactly
        checked_out_calc = workspace_dir_path / "calculator.py"
        checked_out_feat = workspace_dir_path / "feature.py"

        assert checked_out_calc.exists()
        assert "def add(a, b):" in checked_out_calc.read_text(encoding="utf-8")
        # Commit 1 MUST NOT have feature.py (which was added in Commit 2)
        assert not checked_out_feat.exists()

        # 7. Verify no sensitive credentials exist in .git/config
        config_path = workspace_dir_path / ".git" / "config"
        assert config_path.exists()
        config_text = config_path.read_text(encoding="utf-8")
        assert "Authorization" not in config_text
        assert "Bearer" not in config_text
        assert "ghs_" not in config_text

    # 8. Verify automated cleanup upon exiting prepare context
    assert workspace_dir_path is not None
    assert not workspace_dir_path.exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_git_checkout_later_commit(tmp_path: Path) -> None:
    """Verify WorkspaceManager checks out the second commit including newly added files."""
    runner = GitRunner()
    if not runner.is_git_available():
        pytest.fail("Git binary is required for integration tests but was not found.")

    source_repo_dir = tmp_path / "source_repo_2"
    source_repo_dir.mkdir(parents=True, exist_ok=True)
    workspace_root = tmp_path / "workspaces_2"
    workspace_root.mkdir(parents=True, exist_ok=True)

    await runner.run(["init"], cwd=source_repo_dir)
    await runner.run(
        ["config", "user.name", "Integration Tester 2"], cwd=source_repo_dir
    )
    await runner.run(
        ["config", "user.email", "integration2@test.local"], cwd=source_repo_dir
    )
    await runner.run(["config", "core.fileMode", "false"], cwd=source_repo_dir)

    (source_repo_dir / "base.py").write_text("# base", encoding="utf-8")
    await runner.run(["add", "base.py"], cwd=source_repo_dir)
    await runner.run(["commit", "-m", "commit 1"], cwd=source_repo_dir)

    (source_repo_dir / "added.py").write_text("# added in commit 2", encoding="utf-8")
    await runner.run(["add", "added.py"], cwd=source_repo_dir)
    await runner.run(["commit", "-m", "commit 2"], cwd=source_repo_dir)
    res_sha2 = await runner.run(["rev-parse", "HEAD"], cwd=source_repo_dir)
    commit_2_sha = res_sha2.stdout.strip()

    wm = WorkspaceManager(workspace_root=workspace_root)
    workspace_dir_path: Path | None = None

    async with wm.prepare(
        repository_id=888,
        repository_full_name="test-org/second-repo",
        pr_number=99,
        head_sha=commit_2_sha,
        source_repo_url=str(source_repo_dir),
    ) as ws:
        workspace_dir_path = ws.workspace_path
        assert ws.actual_head_sha.lower() == commit_2_sha.lower()
        # Both base.py and added.py must be present in commit 2
        assert (workspace_dir_path / "base.py").exists()
        assert (workspace_dir_path / "added.py").exists()

    assert workspace_dir_path is not None
    assert not workspace_dir_path.exists()
