"""Reusable container execution abstraction for static analysis tools.

Provides secure, isolated Docker container execution for static analyzers (Semgrep, Bandit)
with strictly enforced security boundaries:
- Read-only workspace mounting (:ro)
- Unprivileged non-root execution (--user UID:GID)
- Disabled network access (--network none)
- Hard memory and CPU limits
- Security opt no-new-privileges
- Strict execution timeouts with container termination
- Output size limits to prevent memory exhaustion
- Credential isolation (no host env, no Docker socket, no host credentials)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


def _format_mount_path(path: Path) -> str:
    """Format a host filesystem path for Docker volume mounting.

    Normalizes Windows backslashes to forward slashes for cross-platform Docker CLI compatibility.
    """
    return str(path.resolve()).replace("\\", "/")


@dataclass(frozen=True)
class ContainerExecutionConfig:
    """Configuration contract for launching an isolated static analysis container."""

    image: str
    command: list[str]
    workspace_path: Path
    container_workspace_mount: str = "/workspace"
    read_only_mount: bool = True
    extra_mounts: dict[Path, str] = field(default_factory=dict)
    user: str = "1000:1000"
    memory_limit: str = "512m"
    cpu_limit: str | None = "1.0"
    network: str = "none"
    timeout_seconds: float = 60.0
    max_output_bytes: int = 10 * 1024 * 1024  # 10 MB default limit
    environment: dict[str, str] = field(default_factory=dict)
    working_dir: str | None = None
    entrypoint: str | None = None


@dataclass(frozen=True)
class ContainerExecutionResult:
    """Structured result of a containerized static analysis execution."""

    stdout: str
    stderr: str
    exit_code: int | None
    duration_seconds: float
    timed_out: bool = False
    output_limit_exceeded: bool = False
    container_name: str | None = None


class ContainerExecutionService:
    """Orchestrates secure, resource-bounded container execution for static analyzers."""

    def __init__(self, docker_binary: str | None = None) -> None:
        self.docker_binary = docker_binary or shutil.which("docker") or "docker"

    def is_docker_available(self) -> bool:
        """Check whether Docker CLI is installed and the Docker daemon is responsive."""
        if not shutil.which(self.docker_binary):
            return False
        try:
            import subprocess

            res = subprocess.run(
                [self.docker_binary, "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                timeout=5.0,
            )
            return res.returncode == 0
        except Exception:
            return False

    def build_docker_args(
        self,
        config: ContainerExecutionConfig,
        container_name: str,
    ) -> list[str]:
        """Construct the deterministic command-line arguments for 'docker run'.

        Enforces all security invariants: non-root user, read-only mounts, network none,
        resource limits, and privilege drop.
        """
        args: list[str] = [
            "run",
            "--rm",
            "--name",
            container_name,
        ]

        # 1. Network isolation
        args.extend(["--network", config.network])

        # 2. Non-root user execution
        if config.user:
            args.extend(["--user", config.user])

        # 3. Resource boundaries
        if config.memory_limit:
            args.extend(["--memory", config.memory_limit])
        if config.cpu_limit:
            args.extend(["--cpus", config.cpu_limit])

        # 4. Security hardening: drop new privileges
        args.extend(["--security-opt", "no-new-privileges"])

        # 5. Read-only workspace mount
        mount_mode = "ro" if config.read_only_mount else "rw"
        formatted_ws = _format_mount_path(config.workspace_path)
        args.extend(
            ["-v", f"{formatted_ws}:{config.container_workspace_mount}:{mount_mode}"]
        )

        # 6. Extra read-only mounts (e.g. rule files)
        for host_path, target_spec in config.extra_mounts.items():
            formatted_extra = _format_mount_path(host_path)
            args.extend(["-v", f"{formatted_extra}:{target_spec}"])

        # 7. Environment variables (explicit and controlled only)
        for env_key, env_val in config.environment.items():
            args.extend(["-e", f"{env_key}={env_val}"])

        # 8. Working directory
        if config.working_dir:
            args.extend(["-w", config.working_dir])

        # 9. Entrypoint override
        if config.entrypoint:
            args.extend(["--entrypoint", config.entrypoint])

        # 10. Pinned image & command
        args.append(config.image)
        args.extend(config.command)

        return args

    async def _cleanup_container(self, container_name: str) -> None:
        """Forcefully kill and remove an orphaned or timed-out container."""
        try:
            kill_proc = await asyncio.create_subprocess_exec(
                self.docker_binary,
                "rm",
                "-f",
                container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(kill_proc.wait(), timeout=5.0)
        except Exception as exc:
            logger.debug(
                "Failed to force-cleanup container %s: %s", container_name, exc
            )

    async def run(self, config: ContainerExecutionConfig) -> ContainerExecutionResult:
        """Execute a static analysis container with strict timeouts and output bounds.

        Args:
            config: Complete container execution parameters.

        Returns:
            ContainerExecutionResult: Captured stdout, stderr, exit code, and safety status.

        Raises:
            FileNotFoundError: If the workspace path does not exist on disk.
            RuntimeError: If Docker binary cannot be spawned.
        """
        if not config.workspace_path.is_dir():
            raise FileNotFoundError(
                f"Workspace path does not exist or is not a directory: {config.workspace_path}"
            )

        container_name = f"agentic-sa-{uuid.uuid4().hex[:12]}"
        docker_args = self.build_docker_args(config, container_name)

        logger.debug(
            "Launching static analysis container: name=%s, image=%s, timeout=%.1fs",
            container_name,
            config.image,
            config.timeout_seconds,
        )

        start_time = time.monotonic()
        timed_out = False
        output_limit_exceeded = False
        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []
        total_stdout_bytes = 0
        total_stderr_bytes = 0
        exit_code: int | None = None

        # Prepare clean environment for Docker CLI execution (do not leak host secrets)
        proc_env = {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "DOCKER_HOST": os.environ.get("DOCKER_HOST", ""),
        }
        proc_env = {k: v for k, v in proc_env.items() if v}

        try:
            proc = await asyncio.create_subprocess_exec(
                self.docker_binary,
                *docker_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=proc_env,
            )
        except Exception as exc:
            logger.error("Failed to spawn Docker subprocess: %s", exc)
            raise RuntimeError(f"Unable to execute Docker process: {exc}") from exc

        async def _read_bounded(
            stream: asyncio.StreamReader,
            is_stdout: bool,
        ) -> bool:
            """Read stream up to max_output_bytes. Return True if limit exceeded."""
            nonlocal total_stdout_bytes, total_stderr_bytes
            limit = config.max_output_bytes
            while True:
                chunk = await stream.read(65536)
                if not chunk:
                    break
                if is_stdout:
                    total_stdout_bytes += len(chunk)
                    if total_stdout_bytes > limit:
                        stdout_chunks.append(
                            chunk[: max(0, limit - (total_stdout_bytes - len(chunk)))]
                        )
                        return True
                    stdout_chunks.append(chunk)
                else:
                    total_stderr_bytes += len(chunk)
                    if total_stderr_bytes > limit:
                        stderr_chunks.append(
                            chunk[: max(0, limit - (total_stderr_bytes - len(chunk)))]
                        )
                        return True
                    stderr_chunks.append(chunk)
            return False

        try:
            # Run stream reading and process wait concurrently under timeout
            async with asyncio.timeout(config.timeout_seconds):
                if proc.stdout is None or proc.stderr is None:
                    raise RuntimeError("Subprocess stdout or stderr pipe is None")

                out_task = asyncio.create_task(_read_bounded(proc.stdout, True))
                err_task = asyncio.create_task(_read_bounded(proc.stderr, False))
                wait_task = asyncio.create_task(proc.wait())

                # Wait for all stream reading and process completion
                results = await asyncio.gather(out_task, err_task, wait_task)
                out_exceeded, err_exceeded, return_code = (
                    results[0],
                    results[1],
                    results[2],
                )
                exit_code = return_code

                if out_exceeded or err_exceeded:
                    output_limit_exceeded = True
                    logger.warning(
                        "Static analysis container %s exceeded output limit (%d bytes)",
                        container_name,
                        config.max_output_bytes,
                    )
                    await self._cleanup_container(container_name)

        except TimeoutError:
            timed_out = True
            logger.warning(
                "Static analysis container %s timed out after %.1f seconds",
                container_name,
                config.timeout_seconds,
            )
            # Terminate CLI process and purge Docker container
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await self._cleanup_container(container_name)
        except Exception as exc:
            logger.error("Unexpected error during container execution: %s", exc)
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await self._cleanup_container(container_name)
            raise

        duration = time.monotonic() - start_time
        stdout_str = b"".join(stdout_chunks).decode("utf-8", errors="replace")
        stderr_str = b"".join(stderr_chunks).decode("utf-8", errors="replace")

        return ContainerExecutionResult(
            stdout=stdout_str,
            stderr=stderr_str,
            exit_code=exit_code,
            duration_seconds=duration,
            timed_out=timed_out,
            output_limit_exceeded=output_limit_exceeded,
            container_name=container_name,
        )
