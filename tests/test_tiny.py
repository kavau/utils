"""
Tests for tiny_edit.py — no real terminal required.

Run with:
    cd ~/projects/utils
    python3 -m pytest tests/test_tiny.py -v

Run a single class or test:
    python3 -m pytest tests/test_tiny.py::TestSave -v
    python3 -m pytest tests/test_tiny.py::TestSave::test_save_writes_file -v
"""

import os
import re
import sys
import stat

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tiny import Editor


# ── helpers ───────────────────────────────────────────────────────────────────

def _goto_positions(buf_str):
    """Extract all (row, col) pairs from ESC[row;colH sequences in buf_str."""
    return [
        (int(m.group(1)), int(m.group(2)))
        for m in re.finditer(r'\x1b\[(\d+);(\d+)H', buf_str)
    ]


def _make_render_editor(cols=80, top=1, view_h=5, filename=None):
    """Create an Editor ready for render tests (no real terminal needed)."""
    e = Editor(filename, view_h=view_h)
    e.cols = cols
    e.top = top
    e._flush = lambda: None  # suppress stdout; keeps _buf intact for inspection
    return e


# ── TestFileLoading ───────────────────────────────────────────────────────────

class TestFileLoading:
    def test_nonexistent_file(self):
        e = Editor(None)
        assert e.lines == [""]

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        e = Editor(str(f))
        assert e.lines == [""]

    def test_content_no_trailing_newline(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("hello\nworld")
        e = Editor(str(f))
        assert e.lines == ["hello", "world"]

    def test_content_with_trailing_newline(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("hello\nworld\n")
        e = Editor(str(f))
        assert e.lines == ["hello", "world", ""]

    def test_single_newline(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("\n")
        e = Editor(str(f))
        assert e.lines == ["", ""]


# ── TestSave ──────────────────────────────────────────────────────────────────

class TestSave:
    def test_save_writes_file(self, tmp_path):
        f = tmp_path / "out.txt"
        e = Editor(str(f))
        e.lines = ["a", "b"]
        e.save()
        assert f.read_text() == "a\nb"

    def test_save_clears_dirty(self, tmp_path):
        f = tmp_path / "out.txt"
        e = Editor(str(f))
        e.dirty = True
        e.save()
        assert e.dirty is False

    def test_save_returns_true_on_success(self, tmp_path):
        f = tmp_path / "out.txt"
        e = Editor(str(f))
        assert e.save() is True

    def test_save_without_filename_returns_false(self):
        e = Editor(None)
        assert e.save() is False

    def test_save_without_filename_sets_status(self):
        e = Editor(None)
        e.save()
        assert e.status != ""

    def test_save_oserror_sets_status(self, tmp_path):
        f = tmp_path / "out.txt"
        f.write_text("x")
        f.chmod(0o444)
        e = Editor(str(f))
        e.lines = ["changed"]
        result = e.save()
        assert result is False
        assert "Save failed" in e.status


# ── TestClampCol ──────────────────────────────────────────────────────────────

class TestClampCol:
    def test_clamp_col_within_line(self):
        e = Editor(None)
        e.lines = ["hello"]
        e.col = 3
        e._clamp_col()
        assert e.col == 3

    def test_clamp_col_beyond_line(self):
        e = Editor(None)
        e.lines = ["hi"]
        e.col = 10
        e._clamp_col()
        assert e.col == 2

    def test_clamp_col_empty_line(self):
        e = Editor(None)
        e.lines = [""]
        e.col = 5
        e._clamp_col()
        assert e.col == 0


# ── TestEnsureVisible ─────────────────────────────────────────────────────────

class TestEnsureVisible:
    def _make(self, view_h=5, cols=80):
        e = Editor(None, view_h=view_h)
        e.cols = cols
        return e

    def test_vertical_scroll_up(self):
        e = self._make()
        e.row = 2
        e.v_scroll = 5
        e._ensure_visible()
        assert e.v_scroll == 2

    def test_vertical_scroll_down(self):
        e = self._make(view_h=5)
        e.row = 8
        e.v_scroll = 0
        e._ensure_visible()
        assert e.v_scroll == 4  # 8 - 5 + 1

    def test_vertical_already_visible(self):
        e = self._make(view_h=5)
        e.row = 3
        e.v_scroll = 1
        e._ensure_visible()
        assert e.v_scroll == 1

    def test_horizontal_scroll_left(self):
        e = self._make()
        e.col = 3
        e.h_scroll = 8
        e._ensure_visible()
        assert e.h_scroll == 3

    def test_horizontal_scroll_right(self):
        e = self._make(cols=20)
        e.col = 20
        e.h_scroll = 0
        e._ensure_visible()
        # inner_w = 20 - 4 = 16; h_scroll = 20 - 16 + 1 = 5
        assert e.h_scroll == 5

    def test_horizontal_already_visible(self):
        e = self._make(cols=80)
        e.col = 5
        e.h_scroll = 0
        e._ensure_visible()
        assert e.h_scroll == 0


# ── TestDeleteForward ─────────────────────────────────────────────────────────

class TestDeleteForward:
    def test_delete_char_in_middle(self):
        e = Editor(None)
        e.lines = ["hello"]
        e.col = 2
        e._delete_forward()
        assert e.lines == ["helo"]
        assert e.col == 2

    def test_delete_char_at_start(self):
        e = Editor(None)
        e.lines = ["hello"]
        e.col = 0
        e._delete_forward()
        assert e.lines == ["ello"]

    def test_delete_at_eol_joins_next(self):
        e = Editor(None)
        e.lines = ["foo", "bar"]
        e.col = 3  # EOL of "foo"
        e._delete_forward()
        assert e.lines == ["foobar"]
        assert e.col == 3

    def test_delete_on_last_line_at_eol_noop(self):
        e = Editor(None)
        e.lines = ["foo"]
        e.col = 3  # EOL, no next line
        e._delete_forward()
        assert e.lines == ["foo"]

    def test_delete_marks_dirty(self):
        e = Editor(None)
        e.lines = ["hello"]
        e.col = 0
        e._delete_forward()
        assert e.dirty is True


# ── TestKillToEol ─────────────────────────────────────────────────────────────

class TestKillToEol:
    def test_kill_mid_line(self):
        e = Editor(None)
        e.lines = ["hello world"]
        e.col = 5
        e._kill_to_eol()
        assert e.lines == ["hello"]
        assert e.col == 5

    def test_kill_at_eol_joins_next(self):
        e = Editor(None)
        e.lines = ["foo", "bar"]
        e.col = 3  # EOL of "foo"
        e._kill_to_eol()
        assert e.lines == ["foobar"]
        assert e.col == 3

    def test_kill_on_last_line_at_eol_noop(self):
        e = Editor(None)
        e.lines = ["foo"]
        e.col = 3  # EOL, no next line
        e._kill_to_eol()
        assert e.lines == ["foo"]

    def test_kill_marks_dirty(self):
        e = Editor(None)
        e.lines = ["hello"]
        e.col = 0
        e._kill_to_eol()
        assert e.dirty is True


# ── TestJoinNextLine ──────────────────────────────────────────────────────────

class TestJoinNextLine:
    def test_join_appends(self):
        e = Editor(None)
        e.lines = ["foo", "bar"]
        e.row = 0
        e._join_next_line()
        assert e.lines == ["foobar"]

    def test_join_marks_dirty(self):
        e = Editor(None)
        e.lines = ["foo", "bar"]
        e.row = 0
        e._join_next_line()
        assert e.dirty is True


# ── TestRender ────────────────────────────────────────────────────────────────

class TestRender:
    def test_render_no_crash_normal(self):
        e = _make_render_editor()
        e.render()  # must not raise

    def test_render_no_crash_narrow_terminal(self):
        e = _make_render_editor(cols=10)
        e.render()  # must not raise even with very narrow cols

    def test_render_cursor_row_clamped(self):
        """row < v_scroll is inconsistent but render must not produce negative rows."""
        e = _make_render_editor(top=5)
        e.row = 0
        e.v_scroll = 3  # inconsistent: cursor would be above viewport without fix
        e.render()
        buf = "".join(e._buf)
        for row, col in _goto_positions(buf):
            assert row >= 1, f"Terminal row in goto sequence went below 1: {row}"

    def test_render_display_col_not_negative(self):
        """col < h_scroll is inconsistent but display_col must be clamped to >= 0."""
        e = _make_render_editor(top=1)
        e.col = 0
        e.h_scroll = 5  # inconsistent: col is behind h_scroll
        e.render()
        buf = "".join(e._buf)
        positions = _goto_positions(buf)
        # The last goto positions the cursor; its col must be >= 3 (display_col+3, min 0+3)
        cursor_col = positions[-1][1]
        assert cursor_col >= 3, f"Cursor column went negative: {cursor_col}"

    def test_title_contains_filename(self, tmp_path):
        f = tmp_path / "foo.txt"
        f.write_text("")
        e = _make_render_editor(filename=str(f))
        e.render()
        buf = "".join(e._buf)
        assert "foo.txt" in buf

    def test_title_shows_dirty_indicator(self):
        e = _make_render_editor()
        e.dirty = True
        e.render()
        buf = "".join(e._buf)
        assert "[+]" in buf

    def test_status_bar_contains_line_number(self):
        e = _make_render_editor()
        e.row = 2
        e.lines = ["a", "b", "c", "d"]
        e.render()
        buf = "".join(e._buf)
        assert "Ln 3/" in buf


# ── TestNoBorder ──────────────────────────────────────────────────────────────

def _make_borderless_editor(cols=80, top=1, view_h=5, filename=None):
    e = Editor(filename, view_h=view_h, border=False)
    e.cols = cols
    e.top = top
    e._flush = lambda: None
    return e


class TestNoBorder:
    def test_no_box_drawing_chars(self):
        e = _make_borderless_editor()
        e.render()
        buf = "".join(e._buf)
        for ch in "╭╮╰╯│─":
            assert ch not in buf, f"Box-drawing char {ch!r} found in borderless output"

    def test_no_title_bar(self, tmp_path):
        f = tmp_path / "foo.txt"
        f.write_text("")
        e = _make_borderless_editor(filename=str(f))
        e.render()
        buf = "".join(e._buf)
        assert "foo.txt" not in buf

    def test_no_status_bar(self):
        e = _make_borderless_editor()
        e.render()
        buf = "".join(e._buf)
        assert "Ln " not in buf

    def test_full_width_content(self):
        """With border=False, inner_w == cols so a line exactly cols wide is not truncated."""
        cols = 40
        e = _make_borderless_editor(cols=cols)
        e.lines = ["x" * cols]
        e.render()
        buf = "".join(e._buf)
        # The ellipsis (…) should NOT appear because the line fits exactly
        assert "…" not in buf

    def test_cursor_col_offset_is_one(self):
        """Cursor should be placed at display_col + 1 (no border padding)."""
        e = _make_borderless_editor(cols=80, top=1)
        e.col = 0
        e.h_scroll = 0
        e.render()
        buf = "".join(e._buf)
        positions = _goto_positions(buf)
        cursor_col = positions[-1][1]
        assert cursor_col == 1

    def test_ensure_visible_horizontal_uses_full_width(self):
        """h_scroll threshold should use cols (not cols-4) when border=False."""
        e = _make_borderless_editor(cols=20)
        e.col = 20
        e.h_scroll = 0
        e._ensure_visible()
        # inner_w = 20; h_scroll = 20 - 20 + 1 = 1
        assert e.h_scroll == 1

    def test_render_no_crash(self):
        e = _make_borderless_editor()
        e.render()  # must not raise

    def test_render_no_crash_narrow(self):
        e = _make_borderless_editor(cols=5)
        e.render()  # must not raise even with very narrow cols
