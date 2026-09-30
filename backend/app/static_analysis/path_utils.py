"""Path safety and normalization utilities for untrusted static analysis outputs.

Ensures that file paths reported by containerized analyzers (Semgrep, Bandit) are strictly
contained within the analyzed workspace, normalized to POSIX relative format, and free from
directory traversal, drive specifiers, UNC paths, and null bytes.
"""

from __future__ import annotations

import posixpath
import re

_NULL_BYTE_PATTERN = re.compile(r"\x00")
_WINDOWS_DRIVE_PATTERN = re.compile(r"^[a-zA-Z]:")
_UNC_PATTERN = re.compile(r"^[\\/]{2}")


class PathTraversalSecurityError(ValueError):
    """Raised when an analyzer reports a path attempting traversal outside the workspace."""

    def __init__(self, message: str, raw_path: str) -> None:
        super().__init__(message)
        self.raw_path = raw_path


def normalize_reported_path(
    raw_path: str,
    container_mount_prefixes: tuple[str, ...] = ("/workspace", "/src"),
) -> str:
    """Normalize and validate a file path reported by an analyzer container.

    Args:
        raw_path: The raw path string extracted from tool output (JSON).
        container_mount_prefixes: Known container mount directory prefixes to strip.

    Returns:
        str: Clean, workspace-relative POSIX path (e.g. 'backend/app/main.py').

    Raises:
        PathTraversalSecurityError: If the path contains null bytes, attempts traversal,
            references a host drive / UNC path, or points outside the workspace root.
    """
    if not isinstance(raw_path, str):
        raise PathTraversalSecurityError(
            f"Path must be a string, got {type(raw_path).__name__}",
            raw_path=str(raw_path),
        )

    # 1. Null byte check
    if _NULL_BYTE_PATTERN.search(raw_path):
        raise PathTraversalSecurityError(
            "Null byte detected in analyzer path",
            raw_path=raw_path,
        )

    stripped = raw_path.strip()
    if not stripped:
        raise PathTraversalSecurityError(
            "Empty path reported by analyzer", raw_path=raw_path
        )

    # 2. Check for Windows drive letter or UNC prefix
    if _WINDOWS_DRIVE_PATTERN.match(stripped):
        raise PathTraversalSecurityError(
            f"Windows drive path detected in analyzer output: {stripped!r}",
            raw_path=raw_path,
        )
    if _UNC_PATTERN.match(stripped):
        raise PathTraversalSecurityError(
            f"UNC network path detected in analyzer output: {stripped!r}",
            raw_path=raw_path,
        )

    # 3. Standardize slashes to forward slash
    normalized = stripped.replace("\\", "/")

    # 4. Strip known container volume mount prefixes
    for prefix in container_mount_prefixes:
        clean_prefix = prefix.strip().replace("\\", "/").rstrip("/")
        if normalized == clean_prefix:
            normalized = ""
            break
        elif normalized.startswith(f"{clean_prefix}/"):
            normalized = normalized[len(clean_prefix) + 1 :]
            break
        # Also handle relative prefix without leading slash (e.g. 'workspace/...')
        rel_prefix = clean_prefix.lstrip("/")
        if normalized == rel_prefix:
            normalized = ""
            break
        elif normalized.startswith(f"{rel_prefix}/"):
            normalized = normalized[len(rel_prefix) + 1 :]
            break

    # 5. Clean up leading './' and extra slashes
    normalized = posixpath.normpath(normalized)
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.lstrip("/")

    # 6. Verify traversal escapes
    if not normalized or normalized == ".":
        # Points to the workspace root directly
        return "."

    parts = normalized.split("/")
    if ".." in parts or normalized.startswith(".."):
        raise PathTraversalSecurityError(
            f"Path traversal detected: {stripped!r} resolves to {normalized!r}",
            raw_path=raw_path,
        )

    # 7. Additional safety check using os.path.isabs
    if posixpath.isabs(normalized):
        raise PathTraversalSecurityError(
            f"Path remains absolute after prefix stripping: {normalized!r}",
            raw_path=raw_path,
        )

    return normalized
