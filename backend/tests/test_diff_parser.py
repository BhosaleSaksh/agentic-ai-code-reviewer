"""Comprehensive tests for deterministic Git unified diff parser.

Verifies:
1. 100% line boundary and hunk coordinate accuracy across additions, deletions, context.
2. Handling of all 20 required edge cases:
   - single-line addition, deletion, mixed
   - unchanged context
   - multiple hunks, multiple files
   - new file, deleted file, renamed file, empty file
   - hunks with omitted counts (e.g. @@ -10 +10,2 @@, @@ -1 +1 @@)
   - hunks at line 1, middle, last line
   - zero-line old side (@@ -0,0 +1,5 @@), zero-line new side (@@ -1,5 +0,0 @@)
   - no newline at end of file markers
   - binary files
   - malformed hunk headers, malformed file headers, empty diff
"""

import pytest
from app.context.diff_parser import (
    MalformedHeaderError,
    MalformedHunkError,
    parse_diff,
)
from app.schemas.enums import DiffLineType, FileChangeType, FindingSide

# ==============================================================================
# Edge Case 1: Single-Line Addition
# ==============================================================================


def test_single_line_addition() -> None:
    diff_text = """diff --git a/hello.py b/hello.py
index e69de29..499d63f 100644
--- a/hello.py
+++ b/hello.py
@@ -10,3 +10,4 @@
 def greet():
     msg = "hello"
+    print(msg)
     return msg
"""
    parsed = parse_diff(diff_text)
    assert parsed.total_files == 1
    assert parsed.total_additions == 1
    assert parsed.total_deletions == 0

    f = parsed.files[0]
    assert f.path == "hello.py"
    assert f.status == FileChangeType.MODIFIED
    assert len(f.hunks) == 1

    h = f.hunks[0]
    assert h.old_start == 10
    assert h.old_count == 3
    assert h.new_start == 10
    assert h.new_count == 4
    assert len(h.lines) == 4

    # Line 1: context line 10
    assert h.lines[0].line_type == DiffLineType.CONTEXT
    assert h.lines[0].old_line_number == 10
    assert h.lines[0].new_line_number == 10

    # Line 2: context line 11
    assert h.lines[1].line_type == DiffLineType.CONTEXT
    assert h.lines[1].old_line_number == 11
    assert h.lines[1].new_line_number == 11

    # Line 3: addition line 12
    assert h.lines[2].line_type == DiffLineType.ADDED
    assert h.lines[2].old_line_number is None
    assert h.lines[2].new_line_number == 12
    assert h.lines[2].content == "    print(msg)"

    # Line 4: context line 12 (old), 13 (new)
    assert h.lines[3].line_type == DiffLineType.CONTEXT
    assert h.lines[3].old_line_number == 12
    assert h.lines[3].new_line_number == 13


# ==============================================================================
# Edge Case 2: Single-Line Deletion
# ==============================================================================


def test_single_line_deletion() -> None:
    diff_text = """diff --git a/app.py b/app.py
index 1234567..89abcdef 100644
--- a/app.py
+++ b/app.py
@@ -20,4 +20,3 @@
 context 1
-unwanted line
 context 2
 context 3
"""
    parsed = parse_diff(diff_text)
    assert parsed.total_additions == 0
    assert parsed.total_deletions == 1

    h = parsed.files[0].hunks[0]
    assert h.old_start == 20
    assert h.old_count == 4
    assert h.new_start == 20
    assert h.new_count == 3

    assert h.lines[0].old_line_number == 20
    assert h.lines[0].new_line_number == 20

    # Deleted line
    assert h.lines[1].line_type == DiffLineType.DELETED
    assert h.lines[1].old_line_number == 21
    assert h.lines[1].new_line_number is None

    # Context line following deletion
    assert h.lines[2].line_type == DiffLineType.CONTEXT
    assert h.lines[2].old_line_number == 22
    assert h.lines[2].new_line_number == 21


# ==============================================================================
# Edge Case 3: Mixed Addition and Deletion
# ==============================================================================


def test_mixed_addition_and_deletion() -> None:
    diff_text = """diff --git a/calc.py b/calc.py
--- a/calc.py
+++ b/calc.py
@@ -5,3 +5,4 @@
 def add(a, b):
-    return a - b
+    # Correct addition
+    return a + b
     pass
"""
    parsed = parse_diff(diff_text)
    h = parsed.files[0].hunks[0]
    assert h.old_count == 3
    assert h.new_count == 4

    # Context line 5
    assert h.lines[0].old_line_number == 5
    assert h.lines[0].new_line_number == 5

    # Deleted line 6
    assert h.lines[1].line_type == DiffLineType.DELETED
    assert h.lines[1].old_line_number == 6
    assert h.lines[1].new_line_number is None

    # Added line 6
    assert h.lines[2].line_type == DiffLineType.ADDED
    assert h.lines[2].old_line_number is None
    assert h.lines[2].new_line_number == 6

    # Added line 7
    assert h.lines[3].line_type == DiffLineType.ADDED
    assert h.lines[3].old_line_number is None
    assert h.lines[3].new_line_number == 7

    # Context line 7 (old), 8 (new)
    assert h.lines[4].line_type == DiffLineType.CONTEXT
    assert h.lines[4].old_line_number == 7
    assert h.lines[4].new_line_number == 8


# ==============================================================================
# Edge Case 4: Unchanged Context
# ==============================================================================


def test_unchanged_context() -> None:
    diff_text = """diff --git a/read.py b/read.py
--- a/read.py
+++ b/read.py
@@ -1,3 +1,3 @@
 line 1
 line 2
 line 3
"""
    parsed = parse_diff(diff_text)
    h = parsed.files[0].hunks[0]
    assert parsed.total_additions == 0
    assert parsed.total_deletions == 0
    assert len(h.context_lines) == 3
    for idx, line in enumerate(h.lines, start=1):
        assert line.old_line_number == idx
        assert line.new_line_number == idx


# ==============================================================================
# Edge Case 5: Multiple Hunks in a Single File
# ==============================================================================


def test_multiple_hunks() -> None:
    diff_text = """diff --git a/multi.py b/multi.py
--- a/multi.py
+++ b/multi.py
@@ -10,3 +10,4 @@
 ctx 10
+add 11
 ctx 11
 ctx 12
@@ -80,4 +81,4 @@
 ctx 80
-del 81
+add 82
 ctx 82
 ctx 83
"""
    parsed = parse_diff(diff_text)
    assert len(parsed.files[0].hunks) == 2

    # Hunk 1 coordinates
    h1 = parsed.files[0].hunks[0]
    assert h1.old_start == 10
    assert h1.new_start == 10
    assert h1.lines[1].new_line_number == 11
    assert h1.lines[1].is_added

    # Hunk 2 coordinates
    h2 = parsed.files[0].hunks[1]
    assert h2.old_start == 80
    assert h2.new_start == 81
    assert h2.lines[1].old_line_number == 81
    assert h2.lines[1].is_deleted
    assert h2.lines[2].new_line_number == 82
    assert h2.lines[2].is_added


# ==============================================================================
# Edge Case 6: Multiple Files in a Single Diff
# ==============================================================================


def test_multiple_files() -> None:
    diff_text = """diff --git a/first.py b/first.py
--- a/first.py
+++ b/first.py
@@ -1,2 +1,3 @@
 ctx 1
+add 2
 ctx 2
diff --git a/second.py b/second.py
--- a/second.py
+++ b/second.py
@@ -5,3 +5,2 @@
 ctx 5
-del 6
 ctx 7
"""
    parsed = parse_diff(diff_text)
    assert parsed.total_files == 2
    assert parsed.files[0].path == "first.py"
    assert parsed.files[1].path == "second.py"
    assert parsed.files[0].total_additions == 1
    assert parsed.files[1].total_deletions == 1


# ==============================================================================
# Edge Case 7: Newly Added File (Old side /dev/null)
# ==============================================================================


def test_newly_added_file() -> None:
    diff_text = """diff --git a/new_module.py b/new_module.py
new file mode 100644
index 0000000..abcdef1
--- /dev/null
+++ b/new_module.py
@@ -0,0 +1,3 @@
+def brand_new():
+    return True
+
"""
    parsed = parse_diff(diff_text)
    f = parsed.files[0]
    assert f.status == FileChangeType.ADDED
    assert f.old_path is None
    assert f.new_path == "new_module.py"
    assert f.total_additions == 3
    assert f.total_deletions == 0

    h = f.hunks[0]
    assert h.old_start == 0
    assert h.old_count == 0
    assert h.new_start == 1
    assert h.new_count == 3
    assert [line.new_line_number for line in h.lines] == [1, 2, 3]


# ==============================================================================
# Edge Case 8: Deleted File (New side /dev/null)
# ==============================================================================


def test_deleted_file() -> None:
    diff_text = """diff --git a/obsolete.py b/obsolete.py
deleted file mode 100644
index abcdef1..0000000
--- a/obsolete.py
+++ /dev/null
@@ -1,3 +0,0 @@
-def obsolete_func():
-    pass
-
"""
    parsed = parse_diff(diff_text)
    f = parsed.files[0]
    assert f.status == FileChangeType.DELETED
    assert f.old_path == "obsolete.py"
    assert f.new_path is None
    assert f.total_deletions == 3
    assert f.total_additions == 0

    h = f.hunks[0]
    assert h.old_start == 1
    assert h.old_count == 3
    assert h.new_start == 0
    assert h.new_count == 0
    assert [line.old_line_number for line in h.lines] == [1, 2, 3]


# ==============================================================================
# Edge Case 9: Renamed File
# ==============================================================================


def test_renamed_file_with_modifications() -> None:
    diff_text = """diff --git a/old_name.py b/new_name.py
similarity index 90%
rename from old_name.py
rename to new_name.py
--- a/old_name.py
+++ b/new_name.py
@@ -1,2 +1,2 @@
-name = "old"
+name = "new"
 ctx
"""
    parsed = parse_diff(diff_text)
    f = parsed.files[0]
    assert f.status == FileChangeType.RENAMED
    assert f.is_rename is True
    assert f.old_path == "old_name.py"
    assert f.new_path == "new_name.py"
    assert f.path == "new_name.py"
    assert f.total_additions == 1
    assert f.total_deletions == 1


# ==============================================================================
# Edge Case 10: Empty File Addition
# ==============================================================================


def test_empty_file_addition() -> None:
    diff_text = """diff --git a/__init__.py b/__init__.py
new file mode 100644
index 0000000..e69de29
"""
    parsed = parse_diff(diff_text)
    assert parsed.total_files == 1
    f = parsed.files[0]
    assert f.path == "__init__.py"
    assert f.status == FileChangeType.ADDED
    assert len(f.hunks) == 0


# ==============================================================================
# Edge Case 11: Hunk with Omitted Counts
# ==============================================================================


def test_hunk_with_omitted_counts() -> None:
    # @@ -10 +10,2 @@ means old_count=1, new_count=2
    diff_text = """diff --git a/omitted.py b/omitted.py
--- a/omitted.py
+++ b/omitted.py
@@ -10 +10,2 @@
-old line
+new line 1
+new line 2
"""
    parsed = parse_diff(diff_text)
    h = parsed.files[0].hunks[0]
    assert h.old_start == 10
    assert h.old_count == 1
    assert h.new_start == 10
    assert h.new_count == 2
    assert h.lines[0].line_type == DiffLineType.DELETED
    assert h.lines[0].old_line_number == 10
    assert h.lines[1].line_type == DiffLineType.ADDED
    assert h.lines[1].new_line_number == 10
    assert h.lines[2].line_type == DiffLineType.ADDED
    assert h.lines[2].new_line_number == 11


# ==============================================================================
# Edge Case 12: Hunk Beginning at Line 1
# ==============================================================================


def test_hunk_beginning_at_line_1() -> None:
    diff_text = """diff --git a/start.py b/start.py
--- a/start.py
+++ b/start.py
@@ -1,2 +1,3 @@
+import sys
 import os
 import io
"""
    parsed = parse_diff(diff_text)
    h = parsed.files[0].hunks[0]
    assert h.old_start == 1
    assert h.new_start == 1
    assert h.lines[0].new_line_number == 1
    assert h.lines[0].is_added
    assert h.lines[1].old_line_number == 1
    assert h.lines[1].new_line_number == 2


# ==============================================================================
# Edge Case 13: Last Line Modification
# ==============================================================================


def test_last_line_modification() -> None:
    diff_text = """diff --git a/end.py b/end.py
--- a/end.py
+++ b/end.py
@@ -98,3 +98,3 @@
 line 98
 line 99
-line 100 old
+line 100 new
"""
    parsed = parse_diff(diff_text)
    h = parsed.files[0].hunks[0]
    assert h.lines[2].old_line_number == 100
    assert h.lines[3].new_line_number == 100


# ==============================================================================
# Edge Case 14 & 15: Zero-line old side / zero-line new side
# ==============================================================================


def test_zero_line_old_and_new_counts() -> None:
    # Zero line old side
    d1 = """--- /dev/null\n+++ b/empty.txt\n@@ -0,0 +1,2 @@\n+line 1\n+line 2\n"""
    p1 = parse_diff(d1)
    assert p1.files[0].hunks[0].old_count == 0
    assert p1.files[0].hunks[0].new_count == 2

    # Zero line new side
    d2 = """--- a/empty.txt\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-line 1\n-line 2\n"""
    p2 = parse_diff(d2)
    assert p2.files[0].hunks[0].old_count == 2
    assert p2.files[0].hunks[0].new_count == 0


# ==============================================================================
# Edge Case 16: No Newline at End of File Marker
# ==============================================================================


def test_no_newline_at_end_of_file() -> None:
    diff_text = """diff --git a/file.txt b/file.txt
--- a/file.txt
+++ b/file.txt
@@ -1,2 +1,2 @@
 line 1
-line 2 without newline
\\ No newline at end of file
+line 2 with newline
"""
    parsed = parse_diff(diff_text)
    h = parsed.files[0].hunks[0]
    assert len(h.lines) == 3
    assert h.lines[0].is_context
    assert h.lines[1].is_deleted
    assert h.lines[1].old_line_number == 2
    assert h.lines[2].is_added
    assert h.lines[2].new_line_number == 2


# ==============================================================================
# Edge Case 17: Binary Files
# ==============================================================================


def test_binary_files_handling() -> None:
    diff_text = """diff --git a/logo.png b/logo.png
index 1234567..89abcdef 100644
Binary files a/logo.png and b/logo.png differ
"""
    parsed = parse_diff(diff_text)
    assert parsed.total_files == 1
    f = parsed.files[0]
    assert f.path == "logo.png"
    assert f.is_binary is True
    assert f.status == FileChangeType.BINARY
    assert len(f.hunks) == 0


# ==============================================================================
# Edge Case 18: Malformed Hunk Header
# ==============================================================================


def test_malformed_hunk_header_raises_error() -> None:
    diff_text = """diff --git a/corrupted.py b/corrupted.py
--- a/corrupted.py
+++ b/corrupted.py
@@ invalid hunk header @@
+broken
"""
    with pytest.raises(MalformedHunkError, match="Malformed hunk header syntax"):
        parse_diff(diff_text)


def test_hunk_line_count_mismatch_raises_error() -> None:
    # Header says 5 lines on new side, but only 1 line is provided
    diff_text = """diff --git a/corrupted.py b/corrupted.py
--- a/corrupted.py
+++ b/corrupted.py
@@ -1,5 +1,5 @@
+only one addition
"""
    with pytest.raises(MalformedHunkError, match="Hunk line count mismatch"):
        parse_diff(diff_text)


# ==============================================================================
# Edge Case 19: Malformed File Header
# ==============================================================================


def test_hunk_without_file_header_raises_error() -> None:
    diff_text = """@@ -1,2 +1,2 @@
 ctx
+add
"""
    with pytest.raises(
        MalformedHeaderError, match="Hunk header encountered without prior file header"
    ):
        parse_diff(diff_text)


# ==============================================================================
# Edge Case 20: Empty Diff Text
# ==============================================================================


def test_empty_diff_returns_empty_parsed_diff() -> None:
    assert parse_diff("").total_files == 0
    assert parse_diff("   \n\n\t  ").total_files == 0


# ==============================================================================
# Task 16: 100% Line Boundary Accuracy Test Corpus
# ==============================================================================


def test_100_percent_line_boundary_accuracy() -> None:
    """Rigorous end-to-end verification of every line coordinate in complex multi-hunk diff."""
    diff_text = (
        "diff --git a/calculator.py b/calculator.py\n"
        "index abcdef1..1234567 100644\n"
        "--- a/calculator.py\n"
        "+++ b/calculator.py\n"
        "@@ -1,4 +1,5 @@\n"
        "+import math\n"
        " import sys\n"
        " import os\n"
        " \n"
        " def square(x):\n"
        "@@ -20,6 +21,7 @@ def multiply(a, b):\n"
        "     return a * b\n"
        " \n"
        " def divide(a, b):\n"
        "+    # Guard against division by zero\n"
        "     if b == 0:\n"
        '-        raise Exception("zero")\n'
        '+        raise ValueError("division by zero")\n'
        "     return a / b\n"
        "@@ -50,4 +52,3 @@ def power(a, b):\n"
        "     # Context line 50\n"
        "     res = a ** b\n"
        "-    temp = 1\n"
        "     return res\n"
    )
    parsed = parse_diff(diff_text)
    assert parsed.total_files == 1
    f = parsed.files[0]
    assert len(f.hunks) == 3

    # HUNK 1 (File Start)
    h1 = f.hunks[0]
    assert h1.old_start == 1
    assert h1.old_count == 4
    assert h1.new_start == 1
    assert h1.new_count == 5
    # Lines in Hunk 1:
    # +import math (new: 1)
    assert h1.lines[0].raw_line == "+import math"
    assert h1.lines[0].old_line_number is None
    assert h1.lines[0].new_line_number == 1
    #  import sys (old: 1, new: 2)
    assert h1.lines[1].old_line_number == 1
    assert h1.lines[1].new_line_number == 2
    #  import os (old: 2, new: 3)
    assert h1.lines[2].old_line_number == 2
    assert h1.lines[2].new_line_number == 3
    #   (old: 3, new: 4)
    assert h1.lines[3].old_line_number == 3
    assert h1.lines[3].new_line_number == 4
    #  def square(x): (old: 4, new: 5)
    assert h1.lines[4].old_line_number == 4
    assert h1.lines[4].new_line_number == 5

    # HUNK 2 (File Middle with Section Heading)
    h2 = f.hunks[1]
    assert h2.old_start == 20
    assert h2.old_count == 6
    assert h2.new_start == 21
    assert h2.new_count == 7
    assert h2.section_heading == "def multiply(a, b):"
    #  return a * b (old: 20, new: 21)
    assert h2.lines[0].old_line_number == 20
    assert h2.lines[0].new_line_number == 21
    #   (old: 21, new: 22)
    assert h2.lines[1].old_line_number == 21
    assert h2.lines[1].new_line_number == 22
    #  def divide(a, b): (old: 22, new: 23)
    assert h2.lines[2].old_line_number == 22
    assert h2.lines[2].new_line_number == 23
    # +# Guard against division by zero (new: 24)
    assert h2.lines[3].old_line_number is None
    assert h2.lines[3].new_line_number == 24
    #  if b == 0: (old: 23, new: 25)
    assert h2.lines[4].old_line_number == 23
    assert h2.lines[4].new_line_number == 25
    # - raise Exception("zero") (old: 24)
    assert h2.lines[5].old_line_number == 24
    assert h2.lines[5].new_line_number is None
    # + raise ValueError("division by zero") (new: 26)
    assert h2.lines[6].old_line_number is None
    assert h2.lines[6].new_line_number == 26
    #  return a / b (old: 25, new: 27)
    assert h2.lines[7].old_line_number == 25
    assert h2.lines[7].new_line_number == 27

    # HUNK 3 (File End)
    h3 = f.hunks[2]
    assert h3.old_start == 50
    assert h3.old_count == 4
    assert h3.new_start == 52
    assert h3.new_count == 3
    #  def power(a, b): (old: 50, new: 52)
    assert h3.lines[0].old_line_number == 50
    assert h3.lines[0].new_line_number == 52
    #  res = a ** b (old: 51, new: 53)
    assert h3.lines[1].old_line_number == 51
    assert h3.lines[1].new_line_number == 53
    # - temp = 1 (old: 52)
    assert h3.lines[2].old_line_number == 52
    assert h3.lines[2].new_line_number is None
    #  return res (old: 53, new: 54)
    assert h3.lines[3].old_line_number == 53
    assert h3.lines[3].new_line_number == 54

    # Verify query helpers on ParsedDiff
    assert parsed.is_line_in_diff("calculator.py", 1, FindingSide.RIGHT) is True
    assert parsed.is_line_in_diff("calculator.py", 24, FindingSide.RIGHT) is True
    assert parsed.is_line_in_diff("calculator.py", 26, FindingSide.RIGHT) is True
    assert parsed.is_line_in_diff("calculator.py", 24, FindingSide.LEFT) is True
    assert parsed.is_line_in_diff("calculator.py", 52, FindingSide.LEFT) is True

    # Check changed vs context lines
    assert parsed.is_changed_line("calculator.py", 1, FindingSide.RIGHT) is True
    assert (
        parsed.is_changed_line("calculator.py", 2, FindingSide.RIGHT) is False
    )  # Context
    assert parsed.is_changed_line("calculator.py", 24, FindingSide.LEFT) is True

    # Test file properties
    assert 1 in f.modified_lines_right
    assert 24 in f.modified_lines_right
    assert 26 in f.modified_lines_right
    assert 24 in f.modified_lines_left
    assert 52 in f.modified_lines_left
    assert f.contains_line(1, FindingSide.RIGHT) is True
    assert f.contains_changed_line(1, FindingSide.RIGHT) is True
    assert f.contains_changed_line(2, FindingSide.RIGHT) is False

    # Negative file lookups on ParsedDiff
    assert parsed.is_line_in_diff("nonexistent.py", 1) is False
    assert parsed.is_changed_line("nonexistent.py", 1) is False


def test_traditional_diff_with_timestamps() -> None:
    """Test traditional unified diffs with tab-separated timestamps in header."""
    diff_text = """--- old.txt\t2026-09-30 00:00:00.000000000 +0000
+++ new.txt   2026-09-30 00:01:00.000000000 +0000
@@ -1 +1 @@
-old line
+new line
"""
    parsed = parse_diff(diff_text)
    assert parsed.total_files == 1
    f = parsed.files[0]
    assert f.old_path == "old.txt"
    assert f.new_path == "new.txt"
    assert f.total_additions == 1
    assert f.total_deletions == 1


def test_git_diff_malformed_header_line() -> None:
    """Test git diff header with invalid format raises MalformedHeaderError."""
    with pytest.raises(MalformedHeaderError, match="Malformed git diff header"):
        parse_diff("diff --git \n@@ -1 +1 @@\n-a\n+b\n")
