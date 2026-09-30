"""Unit tests for container execution abstraction (ContainerExecutionService)."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.static_analysis.container_runner import (
    ContainerExecutionConfig,
    ContainerExecutionService,
)


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "repo"
    ws.mkdir()
    (ws / "main.py").write_text("print('hello')", encoding="utf-8")
    return ws


@pytest.mark.unit
def test_build_docker_args_security_invariants(temp_workspace: Path) -> None:
    service = ContainerExecutionService(docker_binary="docker")
    extra_rules = temp_workspace / "rules.yml"
    extra_rules.write_text("rules: []", encoding="utf-8")

    config = ContainerExecutionConfig(
        image="semgrep/semgrep:1.78.0",
        command=["semgrep", "scan", "--json", "/workspace"],
        workspace_path=temp_workspace,
        container_workspace_mount="/workspace",
        read_only_mount=True,
        extra_mounts={extra_rules: "/rules/rules.yml:ro"},
        user="1000:1000",
        memory_limit="512m",
        cpu_limit="1.5",
        network="none",
        timeout_seconds=30.0,
        max_output_bytes=1024 * 1024,
        environment={"SEMGREP_SEND_METRICS": "off"},
        working_dir="/workspace",
    )

    args = service.build_docker_args(config, "test-container-123")

    # Command structure: docker run --rm --name <name>
    assert args[0] == "run"
    assert args[1] == "--rm"
    assert args[2] == "--name"
    assert args[3] == "test-container-123"

    # Security: network isolation
    assert "--network" in args
    net_idx = args.index("--network")
    assert args[net_idx + 1] == "none"

    # Security: unprivileged non-root user
    assert "--user" in args
    user_idx = args.index("--user")
    assert args[user_idx + 1] == "1000:1000"

    # Resource limits: memory and CPU
    assert "--memory" in args
    mem_idx = args.index("--memory")
    assert args[mem_idx + 1] == "512m"

    assert "--cpus" in args
    cpu_idx = args.index("--cpus")
    assert args[cpu_idx + 1] == "1.5"

    # Hardening: no-new-privileges
    assert "--security-opt" in args
    sec_idx = args.index("--security-opt")
    assert args[sec_idx + 1] == "no-new-privileges"

    # Workspace mount: read-only
    formatted_ws = str(temp_workspace.resolve()).replace("\\", "/")
    expected_ws_mount = f"{formatted_ws}:/workspace:ro"
    assert "-v" in args
    assert expected_ws_mount in args

    # Extra mount: rules
    formatted_rules = str(extra_rules.resolve()).replace("\\", "/")
    assert f"{formatted_rules}:/rules/rules.yml:ro" in args

    # Controlled environment
    assert "-e" in args
    assert "SEMGREP_SEND_METRICS=off" in args

    # Working dir
    assert "-w" in args
    assert args[args.index("-w") + 1] == "/workspace"

    # Pinned image and command at the end
    assert args[-5] == "semgrep/semgrep:1.78.0"
    assert args[-4:] == ["semgrep", "scan", "--json", "/workspace"]


@pytest.mark.unit
def test_missing_workspace_raises_file_not_found(tmp_path: Path) -> None:
    service = ContainerExecutionService()
    non_existent = tmp_path / "does_not_exist"

    config = ContainerExecutionConfig(
        image="alpine:latest",
        command=["echo", "hi"],
        workspace_path=non_existent,
    )

    with pytest.raises(FileNotFoundError, match="Workspace path does not exist"):
        asyncio.run(service.run(config))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_success_mocked(temp_workspace: Path) -> None:
    service = ContainerExecutionService()
    config = ContainerExecutionConfig(
        image="alpine:latest",
        command=["echo", "ok"],
        workspace_path=temp_workspace,
    )

    mock_proc = AsyncMock()
    mock_proc.stdout = AsyncMock()
    mock_proc.stdout.read = AsyncMock(side_effect=[b'{"status": "ok"}', b""])
    mock_proc.stderr = AsyncMock()
    mock_proc.stderr.read = AsyncMock(side_effect=[b"diagnostic info", b""])
    mock_proc.wait = AsyncMock(return_value=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await service.run(config)

    assert result.exit_code == 0
    assert result.stdout == '{"status": "ok"}'
    assert result.stderr == "diagnostic info"
    assert not result.timed_out
    assert not result.output_limit_exceeded
    assert result.duration_seconds >= 0.0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_timeout_handling(temp_workspace: Path) -> None:
    service = ContainerExecutionService()
    config = ContainerExecutionConfig(
        image="alpine:latest",
        command=["sleep", "60"],
        workspace_path=temp_workspace,
        timeout_seconds=0.05,
    )

    mock_proc = AsyncMock()
    mock_proc.stdout = AsyncMock()
    mock_proc.stderr = AsyncMock()

    async def slow_read(*_args: object) -> bytes:
        await asyncio.sleep(1.0)
        return b""

    mock_proc.stdout.read = slow_read
    mock_proc.stderr.read = slow_read
    mock_proc.wait = AsyncMock(return_value=None)
    mock_proc.kill = MagicMock()

    cleanup_mock = AsyncMock()
    service._cleanup_container = cleanup_mock  # type: ignore[method-assign]

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await service.run(config)

    assert result.timed_out is True
    assert result.exit_code is None
    cleanup_mock.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_output_limit_exceeded_handling(temp_workspace: Path) -> None:
    service = ContainerExecutionService()
    config = ContainerExecutionConfig(
        image="alpine:latest",
        command=["cat", "bigfile"],
        workspace_path=temp_workspace,
        max_output_bytes=100,
    )

    mock_proc = AsyncMock()
    mock_proc.stdout = AsyncMock()
    mock_proc.stdout.read = AsyncMock(side_effect=[b"x" * 80, b"x" * 80, b""])
    mock_proc.stderr = AsyncMock()
    mock_proc.stderr.read = AsyncMock(return_value=b"")
    mock_proc.wait = AsyncMock(return_value=0)

    cleanup_mock = AsyncMock()
    service._cleanup_container = cleanup_mock  # type: ignore[method-assign]

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await service.run(config)

    assert result.output_limit_exceeded is True
    cleanup_mock.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_spawn_failure_raises_runtime_error(temp_workspace: Path) -> None:
    service = ContainerExecutionService()
    config = ContainerExecutionConfig(
        image="alpine:latest",
        command=["echo"],
        workspace_path=temp_workspace,
    )

    with (
        patch(
            "asyncio.create_subprocess_exec",
            side_effect=OSError("Docker binary missing"),
        ),
        pytest.raises(RuntimeError, match="Unable to execute Docker process"),
    ):
        await service.run(config)
