"""Deterministic Git unified diff parser with exact line coordinate boundaries.

Parses raw unified diffs into structured Pydantic v2 models (ParsedDiff, DiffFile,
DiffHunk, DiffLine) with strict coordinate mapping for additions, deletions,
and context lines, supporting multi-file and multi-hunk diffs, file renames,
binary changes, and explicit error handling for malformed input.
"""

import re
from typing import Final

from app.schemas.diff import DiffFile, DiffHunk, DiffLine, ParsedDiff
from app.schemas.enums import DiffLineType, FileChangeType


class DiffParseError(Exception):
    """Base exception for all Git unified diff parsing errors."""


class MalformedHunkError(DiffParseError):
    """Raised when a hunk header or hunk content violates unified diff formatting."""


class MalformedHeaderError(DiffParseError):
    """Raised when file headers (diff --git, ---, +++) are corrupted or out of order."""


# Standard unified diff hunk header: @@ -old_start[,old_count] +new_start[,new_count] @@ [heading]
HUNK_HEADER_RE: Final[re.Pattern[str]] = re.compile(
    r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@(?:[ \t]*(.*))?$"
)

# Git diff file header: diff --git a/path b/path (handling potential quoted paths)
GIT_DIFF_RE: Final[re.Pattern[str]] = re.compile(
    r"^diff\s+--git\s+(?:a/|[\"']?a/)?(.*?)\s+(?:b/|[\"']?b/)?(.*?)$"
)


class DiffParser:
    """Deterministic parser for Git unified diff text."""

    @classmethod
    def parse(cls, diff_text: str) -> ParsedDiff:
        """Parse raw unified diff text into a structured ParsedDiff object.

        Args:
            diff_text: Raw unified diff output from git diff.

        Returns:
            Structured ParsedDiff containing all files, hunks, and line mappings.

        Raises:
            DiffParseError: If input is corrupted or malformed.
            MalformedHunkError: If hunk coordinates or line boundaries are invalid.
            MalformedHeaderError: If file headers are missing or corrupted.
        """
        if not diff_text or not diff_text.strip():
            return ParsedDiff(files=[])

        lines = diff_text.replace("\r\n", "\n").split("\n")
        # Remove trailing empty string from split if diff ends with newline
        if lines and lines[-1] == "":
            lines.pop()

        files: list[DiffFile] = []
        current_file: DiffFile | None = None
        current_hunk: DiffHunk | None = None

        # Coordinates for currently active hunk
        curr_old: int = 0
        curr_new: int = 0
        actual_old_count: int = 0
        actual_new_count: int = 0

        def finalize_hunk() -> None:
            nonlocal current_hunk, actual_old_count, actual_new_count
            if current_hunk is not None and current_file is not None:
                if (
                    actual_old_count != current_hunk.old_count
                    or actual_new_count != current_hunk.new_count
                ):
                    raise MalformedHunkError(
                        f"Hunk line count mismatch: expected -{current_hunk.old_count},+{current_hunk.new_count}, "
                        f"got -{actual_old_count},+{actual_new_count} in hunk: {current_hunk.header}"
                    )
                current_file.hunks.append(current_hunk)
                current_hunk = None
                actual_old_count = 0
                actual_new_count = 0

        def finalize_file() -> None:
            nonlocal current_file
            finalize_hunk()
            if current_file is not None:
                # Infer status if not explicitly set
                if current_file.status == FileChangeType.MODIFIED:
                    if current_file.old_path in (None, "/dev/null"):
                        current_file.status = FileChangeType.ADDED
                    elif current_file.new_path in (None, "/dev/null"):
                        current_file.status = FileChangeType.DELETED
                    elif current_file.is_rename:
                        current_file.status = FileChangeType.RENAMED
                files.append(current_file)
                current_file = None

        idx = 0
        num_lines = len(lines)

        while idx < num_lines:
            line = lines[idx]

            # 1. Detect Git diff header: diff --git a/... b/...
            if line.startswith("diff --git"):
                finalize_file()
                m = GIT_DIFF_RE.match(line)
                if not m:
                    raise MalformedHeaderError(
                        f"Malformed git diff header at line {idx + 1}: {line}"
                    )
                raw_old = m.group(1).strip().strip("\"'")
                raw_new = m.group(2).strip().strip("\"'")
                current_file = DiffFile(
                    old_path=raw_old,
                    new_path=raw_new,
                    status=FileChangeType.MODIFIED,
                )
                idx += 1
                continue

            # 2. Check for traditional unified diff file headers (without diff --git)
            if line.startswith("--- ") and current_file is None:
                # Start file from traditional header
                old_p = cls._clean_path(line[4:])
                current_file = DiffFile(
                    old_path=None if old_p == "/dev/null" else old_p,
                    status=FileChangeType.MODIFIED,
                )
                idx += 1
                continue

            # 3. Process file header metadata if a file is open but no hunk started yet
            if current_file is not None and current_hunk is None:
                if line.startswith("new file mode"):
                    current_file.status = FileChangeType.ADDED
                    current_file.old_path = None
                    idx += 1
                    continue
                if line.startswith("deleted file mode"):
                    current_file.status = FileChangeType.DELETED
                    current_file.new_path = None
                    idx += 1
                    continue
                if line.startswith("similarity index"):
                    idx += 1
                    continue
                if line.startswith("rename from "):
                    current_file.old_path = cls._clean_path(line[12:])
                    current_file.is_rename = True
                    current_file.status = FileChangeType.RENAMED
                    idx += 1
                    continue
                if line.startswith("rename to "):
                    current_file.new_path = cls._clean_path(line[10:])
                    current_file.is_rename = True
                    current_file.status = FileChangeType.RENAMED
                    idx += 1
                    continue
                if line.startswith("Binary files ") or line.startswith(
                    "GIT binary patch"
                ):
                    current_file.is_binary = True
                    current_file.status = FileChangeType.BINARY
                    idx += 1
                    continue
                if line.startswith("--- "):
                    p = cls._clean_path(line[4:])
                    if p == "/dev/null":
                        current_file.old_path = None
                        current_file.status = FileChangeType.ADDED
                    else:
                        current_file.old_path = p
                    idx += 1
                    continue
                if line.startswith("+++ "):
                    p = cls._clean_path(line[4:])
                    if p == "/dev/null":
                        current_file.new_path = None
                        current_file.status = FileChangeType.DELETED
                    else:
                        current_file.new_path = p
                    idx += 1
                    continue
                if (
                    line.startswith("index ")
                    or line.startswith("old mode ")
                    or line.startswith("new mode ")
                ):
                    idx += 1
                    continue

            # 4. Hunk Header @@ ... @@
            if line.startswith("@@"):
                finalize_hunk()

                if current_file is None:
                    raise MalformedHeaderError(
                        f"Hunk header encountered without prior file header at line {idx + 1}"
                    )

                m = HUNK_HEADER_RE.match(line)
                if not m:
                    raise MalformedHunkError(
                        f"Malformed hunk header syntax at line {idx + 1}: {line}"
                    )

                old_start = int(m.group(1))
                old_count = int(m.group(2)) if m.group(2) is not None else 1
                new_start = int(m.group(3)) if m.group(3) is not None else 1
                new_count = int(m.group(4)) if m.group(4) is not None else 1
                heading = m.group(5).strip() if m.group(5) else None

                current_hunk = DiffHunk(
                    old_start=old_start,
                    old_count=old_count,
                    new_start=new_start,
                    new_count=new_count,
                    header=line,
                    section_heading=heading,
                    lines=[],
                )

                curr_old = old_start
                curr_new = new_start
                actual_old_count = 0
                actual_new_count = 0

                idx += 1
                continue

            # 5. Hunk Body Lines (Context, Addition, Deletion, or No Newline marker)
            if current_hunk is not None:
                # Check for marker: \ No newline at end of file
                if line.startswith("\\"):
                    idx += 1
                    continue

                if line.startswith("+"):
                    current_hunk.lines.append(
                        DiffLine(
                            line_type=DiffLineType.ADDED,
                            old_line_number=None,
                            new_line_number=curr_new,
                            content=line[1:],
                            raw_line=line,
                        )
                    )
                    curr_new += 1
                    actual_new_count += 1
                    idx += 1
                    continue

                if line.startswith("-"):
                    current_hunk.lines.append(
                        DiffLine(
                            line_type=DiffLineType.DELETED,
                            old_line_number=curr_old,
                            new_line_number=None,
                            content=line[1:],
                            raw_line=line,
                        )
                    )
                    curr_old += 1
                    actual_old_count += 1
                    idx += 1
                    continue

                if line.startswith(" ") or line == "":
                    # Context line
                    # Note: an empty string within a hunk is an empty context line
                    content = line[1:] if line.startswith(" ") else ""
                    raw = line if line.startswith(" ") else " "
                    current_hunk.lines.append(
                        DiffLine(
                            line_type=DiffLineType.CONTEXT,
                            old_line_number=curr_old,
                            new_line_number=curr_new,
                            content=content,
                            raw_line=raw,
                        )
                    )
                    curr_old += 1
                    curr_new += 1
                    actual_old_count += 1
                    actual_new_count += 1
                    idx += 1
                    continue

                # If the line does not match any hunk line prefix (+, -, ' ', \)
                # and we already fulfilled expected counts or hit an EOF / next file,
                # finalize current hunk and re-process line.
                finalize_hunk()
                continue

            # If line is outside hunk and outside known headers, advance
            idx += 1

        finalize_file()
        return ParsedDiff(files=files)

    @classmethod
    def _clean_path(cls, path_str: str) -> str:
        """Clean leading 'a/', 'b/', timestamp suffixes, and surrounding quotes."""
        cleaned = path_str.strip().strip("\"'")
        # Traditional diff headers often contain timestamps like: file.py\t2026-09-30 00:00:00
        if "\t" in cleaned:
            cleaned = cleaned.split("\t", 1)[0].strip()
        elif "   " in cleaned:
            cleaned = cleaned.split("   ", 1)[0].strip()

        if cleaned == "/dev/null":
            return "/dev/null"
        if cleaned.startswith("a/") or cleaned.startswith("b/"):
            return cleaned[2:]
        return cleaned


def parse_diff(diff_text: str) -> ParsedDiff:
    """Convenience functional interface for parsing Git unified diff text.

    Args:
        diff_text: Raw unified diff output from git diff.

    Returns:
        Structured ParsedDiff with deterministic line coordinate mappings.
    """
    return DiffParser.parse(diff_text)
