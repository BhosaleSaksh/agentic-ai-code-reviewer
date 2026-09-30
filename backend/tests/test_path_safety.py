"""Unit tests for path normalization and traversal prevention in analyzer outputs."""

import pytest
from app.static_analysis.path_utils import (
    PathTraversalSecurityError,
    normalize_reported_path,
)


@pytest.mark.unit
def test_normalize_clean_relative_path() -> None:
    assert normalize_reported_path("backend/app/main.py") == "backend/app/main.py"
    assert normalize_reported_path("app/utils.py") == "app/utils.py"
    assert normalize_reported_path("main.py") == "main.py"


@pytest.mark.unit
def test_normalize_leading_dotslash_and_slashes() -> None:
    assert normalize_reported_path("./backend/app/main.py") == "backend/app/main.py"
    assert normalize_reported_path(".//app/utils.py") == "app/utils.py"
    assert normalize_reported_path("/app/utils.py") == "app/utils.py"


@pytest.mark.unit
def test_normalize_windows_backslashes() -> None:
    assert normalize_reported_path(r"backend\app\main.py") == "backend/app/main.py"
    assert normalize_reported_path(r".\backend\app\main.py") == "backend/app/main.py"


@pytest.mark.unit
def test_normalize_container_workspace_prefixes() -> None:
    assert (
        normalize_reported_path("/workspace/backend/app/main.py")
        == "backend/app/main.py"
    )
    assert normalize_reported_path("/workspace/main.py") == "main.py"
    assert normalize_reported_path("/src/backend/app/main.py") == "backend/app/main.py"
    assert (
        normalize_reported_path("workspace/backend/app/main.py")
        == "backend/app/main.py"
    )
    assert normalize_reported_path("src/backend/app/main.py") == "backend/app/main.py"
    assert (
        normalize_reported_path(r"\workspace\backend\app\main.py")
        == "backend/app/main.py"
    )


@pytest.mark.unit
def test_normalize_root_target() -> None:
    assert normalize_reported_path("/workspace") == "."
    assert normalize_reported_path("/src") == "."
    assert normalize_reported_path(".") == "."


@pytest.mark.unit
@pytest.mark.parametrize(
    "invalid_path",
    [
        "../../etc/passwd",
        "../secret.txt",
        "app/../../etc/shadow",
        "/workspace/../../etc/passwd",
        "foo/../../../bar",
        "....//etc/passwd",
    ],
)
def test_reject_directory_traversal(invalid_path: str) -> None:
    with pytest.raises(PathTraversalSecurityError) as exc_info:
        normalize_reported_path(invalid_path)
    assert exc_info.value.raw_path == invalid_path


@pytest.mark.unit
def test_reject_null_bytes() -> None:
    with pytest.raises(PathTraversalSecurityError, match="Null byte detected"):
        normalize_reported_path("backend/app/\x00evil.py")


@pytest.mark.unit
@pytest.mark.parametrize(
    "drive_path",
    [
        r"C:\Windows\System32\cmd.exe",
        "C:/Windows/System32/cmd.exe",
        "D:/Projects/secret.txt",
        "e:/foo/bar.py",
    ],
)
def test_reject_windows_drive_paths(drive_path: str) -> None:
    with pytest.raises(PathTraversalSecurityError, match="Windows drive path detected"):
        normalize_reported_path(drive_path)


@pytest.mark.unit
@pytest.mark.parametrize(
    "unc_path",
    [
        r"\\server\share\file.py",
        r"\\192.168.1.1\c$\passwords.txt",
        "//server/share/file.py",
    ],
)
def test_reject_unc_network_paths(unc_path: str) -> None:
    with pytest.raises(PathTraversalSecurityError, match="UNC network path detected"):
        normalize_reported_path(unc_path)


@pytest.mark.unit
@pytest.mark.parametrize("empty_input", ["", "   ", "\t\n"])
def test_reject_empty_paths(empty_input: str) -> None:
    with pytest.raises(PathTraversalSecurityError, match="Empty path reported"):
        normalize_reported_path(empty_input)


@pytest.mark.unit
def test_reject_non_string() -> None:
    with pytest.raises(PathTraversalSecurityError, match="Path must be a string"):
        normalize_reported_path(123)  # type: ignore[arg-type]
