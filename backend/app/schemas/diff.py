"""Data contracts for structured Git unified diff representation.

Provides typed Pydantic models for diff lines, hunks, files, and parsed diffs
with exact coordinate mapping for additions, deletions, and context lines.
"""

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.schemas.enums import DiffLineType, FileChangeType, FindingSide


class DiffLine(BaseModel):
    """A single line within a unified diff hunk.

    Maintains exact 1-based coordinates in both the old (base) and new (head)
    file representations.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        validate_assignment=True,
    )

    line_type: DiffLineType = Field(
        ...,
        description="Line type: ADDED ('+'), DELETED ('-'), or CONTEXT (' ')",
    )
    old_line_number: int | None = Field(
        None,
        description="1-based line number in the old/base file (for CONTEXT and DELETED lines)",
    )
    new_line_number: int | None = Field(
        None,
        description="1-based line number in the new/head file (for CONTEXT and ADDED lines)",
    )
    content: str = Field(
        ...,
        description="Line text content without the diff prefix character",
    )
    raw_line: str = Field(
        default="",
        description="Original diff line including prefix character (+, -, ' ')",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_added(self) -> bool:
        """Return True if line was added in the new file."""
        return self.line_type == DiffLineType.ADDED

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_deleted(self) -> bool:
        """Return True if line was deleted from the old file."""
        return self.line_type == DiffLineType.DELETED

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_context(self) -> bool:
        """Return True if line is unchanged context."""
        return self.line_type == DiffLineType.CONTEXT


class DiffHunk(BaseModel):
    """A contiguous hunk of changes within a diff file.

    Parsed from the hunk header '@@ -old_start,old_count +new_start,new_count @@'.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        validate_assignment=True,
    )

    old_start: int = Field(
        ...,
        description="1-based starting line number in the old file (0 for new files)",
    )
    old_count: int = Field(
        ...,
        ge=0,
        description="Number of lines in the old file covered by this hunk",
    )
    new_start: int = Field(
        ...,
        description="1-based starting line number in the new file (0 for deleted files)",
    )
    new_count: int = Field(
        ...,
        ge=0,
        description="Number of lines in the new file covered by this hunk",
    )
    header: str = Field(
        ...,
        description="Raw hunk header text (e.g. '@@ -10,5 +10,6 @@')",
    )
    section_heading: str | None = Field(
        None,
        description="Optional function/class context following the hunk header",
    )
    lines: list[DiffLine] = Field(
        default_factory=list,
        description="Ordered sequence of diff lines belonging to this hunk",
    )

    @property
    def added_lines(self) -> list[DiffLine]:
        """Return all added lines in this hunk."""
        return [line for line in self.lines if line.is_added]

    @property
    def deleted_lines(self) -> list[DiffLine]:
        """Return all deleted lines in this hunk."""
        return [line for line in self.lines if line.is_deleted]

    @property
    def context_lines(self) -> list[DiffLine]:
        """Return all context lines in this hunk."""
        return [line for line in self.lines if line.is_context]

    def contains_line(
        self, line_number: int, side: FindingSide = FindingSide.RIGHT
    ) -> bool:
        """Check if a specific line coordinate is covered by this hunk.

        For side=RIGHT, checks added and context lines by new_line_number.
        For side=LEFT, checks deleted and context lines by old_line_number.
        """
        if side == FindingSide.RIGHT:
            return any(
                line.new_line_number == line_number
                for line in self.lines
                if line.new_line_number is not None
            )
        return any(
            line.old_line_number == line_number
            for line in self.lines
            if line.old_line_number is not None
        )

    def contains_changed_line(
        self, line_number: int, side: FindingSide = FindingSide.RIGHT
    ) -> bool:
        """Check if a specifically changed line (ADDED for RIGHT, DELETED for LEFT) is in this hunk."""
        if side == FindingSide.RIGHT:
            return any(line.new_line_number == line_number for line in self.added_lines)
        return any(line.old_line_number == line_number for line in self.deleted_lines)


class DiffFile(BaseModel):
    """Structured representation of a single file in a Git diff."""

    model_config = ConfigDict(
        populate_by_name=True,
        validate_assignment=True,
    )

    old_path: str | None = Field(
        None,
        description="Path in the base commit (None or /dev/null for newly added files)",
    )
    new_path: str | None = Field(
        None,
        description="Path in the head commit (None or /dev/null for deleted files)",
    )
    status: FileChangeType = Field(
        default=FileChangeType.MODIFIED,
        description="File change classification: MODIFIED, ADDED, DELETED, RENAMED, BINARY",
    )
    is_binary: bool = Field(
        default=False,
        description="Flag indicating if the file is a binary file",
    )
    is_rename: bool = Field(
        default=False,
        description="Flag indicating if the file was renamed",
    )
    hunks: list[DiffHunk] = Field(
        default_factory=list,
        description="List of change hunks within this file",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def path(self) -> str:
        """Effective path of the file in the PR (prefers new_path, falls back to old_path)."""
        return self.new_path or self.old_path or ""

    @property
    def total_additions(self) -> int:
        """Total number of added lines across all hunks."""
        return sum(len(hunk.added_lines) for hunk in self.hunks)

    @property
    def total_deletions(self) -> int:
        """Total number of deleted lines across all hunks."""
        return sum(len(hunk.deleted_lines) for hunk in self.hunks)

    @property
    def modified_lines_right(self) -> set[int]:
        """Set of new line numbers added in this file (side=RIGHT)."""
        lines: set[int] = set()
        for hunk in self.hunks:
            for line in hunk.added_lines:
                if line.new_line_number is not None:
                    lines.add(line.new_line_number)
        return lines

    @property
    def modified_lines_left(self) -> set[int]:
        """Set of old line numbers deleted in this file (side=LEFT)."""
        lines: set[int] = set()
        for hunk in self.hunks:
            for line in hunk.deleted_lines:
                if line.old_line_number is not None:
                    lines.add(line.old_line_number)
        return lines

    def contains_line(
        self, line_number: int, side: FindingSide = FindingSide.RIGHT
    ) -> bool:
        """Check if any hunk covers the line number on the specified side."""
        return any(hunk.contains_line(line_number, side) for hunk in self.hunks)

    def contains_changed_line(
        self, line_number: int, side: FindingSide = FindingSide.RIGHT
    ) -> bool:
        """Check if any hunk contains an actual change on the line number."""
        return any(hunk.contains_changed_line(line_number, side) for hunk in self.hunks)


class ParsedDiff(BaseModel):
    """Complete structured representation of a Pull Request Git unified diff."""

    model_config = ConfigDict(
        populate_by_name=True,
        validate_assignment=True,
    )

    files: list[DiffFile] = Field(
        default_factory=list,
        description="List of altered files extracted from the diff",
    )

    @property
    def total_files(self) -> int:
        """Total number of files in the diff."""
        return len(self.files)

    @property
    def total_additions(self) -> int:
        """Total number of added lines across all files."""
        return sum(f.total_additions for f in self.files)

    @property
    def total_deletions(self) -> int:
        """Total number of deleted lines across all files."""
        return sum(f.total_deletions for f in self.files)

    @property
    def total_hunks(self) -> int:
        """Total number of hunks across all files in the diff."""
        return sum(len(f.hunks) for f in self.files)

    def get_file(self, path: str) -> DiffFile | None:
        """Find a file by path, new_path, or old_path (ignoring leading 'a/' or 'b/')."""
        normalized = path.removeprefix("a/").removeprefix("b/")
        for f in self.files:
            if (
                f.path == normalized
                or f.new_path == normalized
                or f.old_path == normalized
            ):
                return f
        return None

    def has_file(self, path: str) -> bool:
        """Check if a file exists in the parsed diff."""
        return self.get_file(path) is not None

    def is_line_in_diff(
        self,
        path: str,
        line_number: int,
        side: FindingSide = FindingSide.RIGHT,
    ) -> bool:
        """Determine if a file line coordinate falls within a diff hunk."""
        f = self.get_file(path)
        if f is None:
            return False
        return f.contains_line(line_number, side)

    def is_changed_line(
        self,
        path: str,
        line_number: int,
        side: FindingSide = FindingSide.RIGHT,
    ) -> bool:
        """Determine if a file line coordinate was actively changed in the diff."""
        f = self.get_file(path)
        if f is None:
            return False
        return f.contains_changed_line(line_number, side)
