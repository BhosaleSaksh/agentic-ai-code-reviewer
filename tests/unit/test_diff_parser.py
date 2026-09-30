"""Unit test for diff parser as specified in ROADMAP.md milestone 1.3/1.4."""

from app.context.diff_parser import parse_diff
from app.schemas.enums import DiffLineType, FileChangeType, FindingSide


def test_roadmap_diff_parser_hunk_boundary_accuracy() -> None:
    """Validate 100% hunk boundary accuracy per ROADMAP.md acceptance criteria."""
    diff_text = """diff --git a/services/order.py b/services/order.py
index 1000000..2000000 100644
--- a/services/order.py
+++ b/services/order.py
@@ -45,5 +45,6 @@ def process_order(order_id: int):
     # Pre-condition check
     order = get_order(order_id)
-    validate(order)
+    validate_order(order)
+    audit_log(order)
     save_audit_event(order)
     return order.save()
"""
    parsed = parse_diff(diff_text)
    assert parsed.total_files == 1
    file_diff = parsed.files[0]
    assert file_diff.path == "services/order.py"
    assert file_diff.status == FileChangeType.MODIFIED
    assert len(file_diff.hunks) == 1

    hunk = file_diff.hunks[0]
    assert hunk.old_start == 45
    assert hunk.old_count == 5
    assert hunk.new_start == 45
    assert hunk.new_count == 6

    # Verify line coordinates
    # Line 45 (Context)
    assert hunk.lines[0].line_type == DiffLineType.CONTEXT
    assert hunk.lines[0].old_line_number == 45
    assert hunk.lines[0].new_line_number == 45

    # Line 46 (Context)
    assert hunk.lines[1].line_type == DiffLineType.CONTEXT
    assert hunk.lines[1].old_line_number == 46
    assert hunk.lines[1].new_line_number == 46

    # Line 47 (Deleted)
    assert hunk.lines[2].line_type == DiffLineType.DELETED
    assert hunk.lines[2].old_line_number == 47
    assert hunk.lines[2].new_line_number is None

    # Line 47 (Added)
    assert hunk.lines[3].line_type == DiffLineType.ADDED
    assert hunk.lines[3].old_line_number is None
    assert hunk.lines[3].new_line_number == 47

    # Line 48 (Added)
    assert hunk.lines[4].line_type == DiffLineType.ADDED
    assert hunk.lines[4].old_line_number is None
    assert hunk.lines[4].new_line_number == 48

    # Line 48 (Old context) -> Line 49 (New context)
    assert hunk.lines[5].line_type == DiffLineType.CONTEXT
    assert hunk.lines[5].old_line_number == 48
    assert hunk.lines[5].new_line_number == 49

    # Line 49 (Old context) -> Line 50 (New context)
    assert hunk.lines[6].line_type == DiffLineType.CONTEXT
    assert hunk.lines[6].old_line_number == 49
    assert hunk.lines[6].new_line_number == 50

    # Verify query helpers
    assert parsed.is_line_in_diff("services/order.py", 48, FindingSide.RIGHT) is True
    assert parsed.is_line_in_diff("services/order.py", 47, FindingSide.LEFT) is True
    assert parsed.is_changed_line("services/order.py", 48, FindingSide.RIGHT) is True
