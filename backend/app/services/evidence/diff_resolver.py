"""Diff Evidence Resolver for locating, validating, and extracting code coordinates from git diffs."""

from __future__ import annotations

import logging

from app.schemas.diff import DiffFile, DiffHunk, ParsedDiff
from app.schemas.enums import FindingSide

logger = logging.getLogger(__name__)


class DiffEvidenceResolver:
    """Resolves and validates code line coordinates and excerpts against parsed git diffs."""

    def resolve_file(
        self, parsed_diff: ParsedDiff | None, file_path: str
    ) -> DiffFile | None:
        """Find the matching DiffFile within the parsed diff, normalizing path separators."""
        if not parsed_diff or not file_path:
            return None

        clean_path = file_path.replace("\\", "/").strip().lstrip("./")
        # Try direct lookup
        matched = parsed_diff.get_file(clean_path)
        if matched is not None:
            return matched

        # Try suffix or prefix match
        for diff_file in parsed_diff.files:
            df_path = (diff_file.path or "").replace("\\", "/").strip().lstrip("./")
            if (
                df_path == clean_path
                or df_path.endswith(clean_path)
                or clean_path.endswith(df_path)
            ):
                return diff_file

        return None

    def file_exists_in_diff(
        self, parsed_diff: ParsedDiff | None, file_path: str
    ) -> bool:
        """Check if the given file exists in the parsed diff."""
        return self.resolve_file(parsed_diff, file_path) is not None

    def line_in_diff(
        self,
        parsed_diff: ParsedDiff | None,
        file_path: str,
        line_number: int,
        side: FindingSide = FindingSide.RIGHT,
    ) -> bool:
        """Check if a specific line coordinate falls within any hunk of the diff."""
        diff_file = self.resolve_file(parsed_diff, file_path)
        if diff_file is None:
            return False
        return diff_file.contains_line(line_number, side)

    def is_changed_line(
        self,
        parsed_diff: ParsedDiff | None,
        file_path: str,
        line_number: int,
        side: FindingSide = FindingSide.RIGHT,
    ) -> bool:
        """Check if a specific line coordinate was actively added/modified/deleted in the diff."""
        diff_file = self.resolve_file(parsed_diff, file_path)
        if diff_file is None:
            return False
        return diff_file.contains_changed_line(line_number, side)

    def get_covering_hunk(
        self,
        parsed_diff: ParsedDiff | None,
        file_path: str,
        line_number: int,
        side: FindingSide = FindingSide.RIGHT,
    ) -> DiffHunk | None:
        """Return the specific DiffHunk that covers the given line coordinate, if any."""
        diff_file = self.resolve_file(parsed_diff, file_path)
        if diff_file is None:
            return None
        for hunk in diff_file.hunks:
            if hunk.contains_line(line_number, side):
                return hunk
        return None

    def extract_diff_excerpt(
        self,
        parsed_diff: ParsedDiff | None,
        file_path: str,
        line_number: int,
        context_window: int = 3,
        side: FindingSide = FindingSide.RIGHT,
    ) -> tuple[str | None, str | None]:
        """Extract a formatted diff excerpt and the covering hunk header around a target line.

        Returns:
            tuple[excerpt, hunk_header]: The formatted lines around the target line and the hunk header.
        """
        hunk = self.get_covering_hunk(parsed_diff, file_path, line_number, side)
        if hunk is None:
            return None, None

        # Find line index within the hunk
        target_idx: int | None = None
        for idx, line in enumerate(hunk.lines):
            line_no = (
                line.new_line_number
                if side == FindingSide.RIGHT
                else line.old_line_number
            )
            if line_no == line_number:
                target_idx = idx
                break

        if target_idx is None:
            # Fall back to entire hunk
            lines_str = "\n".join(
                dline.raw_line or f"{dline.line_type.value} {dline.content}"
                for dline in hunk.lines
            )
            return lines_str, hunk.header

        start_idx = max(0, target_idx - context_window)
        end_idx = min(len(hunk.lines), target_idx + context_window + 1)
        slice_lines = hunk.lines[start_idx:end_idx]

        excerpt = "\n".join(
            dline.raw_line or f"{dline.line_type.value} {dline.content}"
            for dline in slice_lines
        )
        return excerpt, hunk.header

    def extract_surrounding_code(
        self,
        parsed_diff: ParsedDiff | None,
        file_path: str,
        line_number: int,
        context_window: int = 3,
        side: FindingSide = FindingSide.RIGHT,
    ) -> str | None:
        """Extract clean code text (without diff markers) surrounding the target line."""
        hunk = self.get_covering_hunk(parsed_diff, file_path, line_number, side)
        if hunk is None:
            return None

        code_lines: list[str] = []
        for line in hunk.lines:
            if side == FindingSide.RIGHT and line.is_deleted:
                continue
            if side == FindingSide.LEFT and line.is_added:
                continue
            line_no = (
                line.new_line_number
                if side == FindingSide.RIGHT
                else line.old_line_number
            )
            if line_no is not None and abs(line_no - line_number) <= context_window:
                code_lines.append(f"{line_no:4d} | {line.content}")

        return "\n".join(code_lines) if code_lines else None
