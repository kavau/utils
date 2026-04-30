#!/usr/bin/env python3
"""
tiny — a minimal inline terminal text editor

Edits a file in-place using a few terminal lines instead of taking over the
entire screen. No dependencies beyond stdlib. Useful for quick edits without
leaving your terminal context.

Usage: tiny [file] [-n LINES] [-p]

  Arrows       move cursor            Home / End    line start / end
  PgUp / PgDn  scroll by page         Del           delete char under cursor
  Ctrl+S       save                   Ctrl+Q        quit (prompts if unsaved)
  Ctrl+K       delete to end of line  Ctrl+A / ^E   line start / end
"""

import sys, os, tty, termios, re, argparse, shutil, select

ESC = "\x1b"

# ── terminal helpers ──────────────────────────────────────────────────────────

def term_size():
    s = shutil.get_terminal_size()
    return s.columns, s.lines


def get_cursor_pos():
    """Ask the terminal for the current cursor position (1-indexed row, col)."""
    sys.stdout.write(ESC + "[6n")
    sys.stdout.flush()
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    buf = b""
    try:
        tty.setraw(fd)
        while True:
            r, _, _ = select.select([fd], [], [], 2.0)
            if not r:
                break  # terminal didn't respond; fall through to fallback (1,1)
            c = os.read(fd, 1)
            buf += c
            if c == b"R":
                break
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    m = re.search(rb"\[(\d+);(\d+)R", buf)
    return (int(m.group(1)), int(m.group(2))) if m else (1, 1)


_ESC_TIMEOUT = 0.15  # seconds to wait for the next byte in an escape sequence

def read_key(fd):
    """Read one complete keypress.  Returns a string token."""
    c = os.read(fd, 1)
    if c != b"\x1b":
        return c.decode("utf-8", errors="replace")
    buf = b"\x1b"
    # Read the introducer byte (e.g. '[' for CSI, 'O' for SS3).
    r, _, _ = select.select([fd], [], [], _ESC_TIMEOUT)
    if not r:
        return ESC
    intro = os.read(fd, 1)
    buf += intro
    if intro not in (b"[", b"O"):
        # Simple two-byte ESC sequence — done.
        return buf.decode("latin-1")
    # CSI / SS3 sequence: read until the final byte (0x40–0x7E).
    # Parameter bytes (0x30–0x3F) and intermediate bytes (0x20–0x2F) are not final.
    while True:
        r, _, _ = select.select([fd], [], [], _ESC_TIMEOUT)
        if not r:
            break
        b = os.read(fd, 1)
        buf += b
        if 0x40 <= b[0] <= 0x7E:
            break
    return buf.decode("latin-1")


# Common key constants
K_UP    = ESC + "[A"
K_DOWN  = ESC + "[B"
K_RIGHT = ESC + "[C"
K_LEFT  = ESC + "[D"
K_HOME  = ESC + "[H"
K_END   = ESC + "[F"
K_HOME2 = ESC + "[1~"
K_END2  = ESC + "[4~"
K_PGUP  = ESC + "[5~"
K_PGDN  = ESC + "[6~"
K_DEL   = ESC + "[3~"


# ── editor ────────────────────────────────────────────────────────────────────

class Editor:
    def __init__(self, filename: str | None, view_h: int = 10, border: bool = True):
        self.filename = filename
        self.view_h   = view_h
        self.border   = border
        self.lines    = [""]
        self.row = self.col = 0   # cursor position in content
        self.v_scroll  = 0        # first visible content line
        self.h_scroll  = 0        # horizontal scroll offset
        self.dirty     = False
        self.status    = ""
        self.rows      = 0
        self._buf: list[str] = [] # write buffer

        if filename and os.path.isfile(filename):
            with open(filename, "r", errors="replace") as f:
                data = f.read()
            self.lines = data.splitlines() or [""]
            # Preserve trailing newline: represent it as an extra empty line so
            # that saving with "\n".join(lines) round-trips correctly.
            # A file with no trailing newline does NOT get an empty last line.
            if data.endswith("\n"):
                self.lines.append("")

    # ── output buffering ───────────────────────────────────────────────────

    def _w(self, s: str):
        self._buf.append(s)

    def _flush(self):
        sys.stdout.write("".join(self._buf))
        self._buf.clear()
        sys.stdout.flush()

    def _goto(self, row: int, col: int):
        """Move terminal cursor to absolute (row, col), 1-indexed."""
        self._w(f"{ESC}[{row};{col}H")

    # ── rendering ─────────────────────────────────────────────────────────

    def render(self):
        cols    = self.cols
        if self.border:
            inner_w     = cols - 4      # space between the │ borders
            total_h     = self.view_h + 2
            content_top = self.top + 1
        else:
            inner_w     = cols
            total_h     = self.view_h
            content_top = self.top
            # Status needs a line below the editor; scroll the terminal if at the bottom.
            if self.status and self.rows and self.top + self.view_h > self.rows:
                self._goto(self.rows, 1)
                self._w("\n")
                self.top -= 1
                content_top = self.top
        if inner_w < 1:
            inner_w = 1

        self._w(ESC + "[?25l")       # hide cursor while drawing

        if self.border:
            # ── title bar ──
            fname = (self.filename or "untitled") + (" [+]" if self.dirty else "")
            hints = "^S save  ^Q quit"
            left  = f" {fname} "
            right = f" {hints} "
            fill  = max(0, cols - len(left) - len(right) - 2)
            title = "\u256d" + left + "\u2500" * fill + right + "\u256e"
            self._goto(self.top, 1)
            self._w("\x1b[2K" + title[:cols])

        # ── content rows ──
        for i in range(self.view_h):
            li = i + self.v_scroll
            self._goto(content_top + i, 1)
            self._w("\x1b[2K")

            if li < len(self.lines):
                line    = self.lines[li]
                segment = line[self.h_scroll:]
                if len(segment) > inner_w:
                    display = segment[:inner_w - 1] + "\u2026"  # …
                else:
                    display = segment.ljust(inner_w)
            else:
                display = "~" + " " * (inner_w - 1)

            if self.border:
                self._w(f"\u2502 {display} \u2502")
            else:
                self._w(display)

        if self.border:
            # ── status bar ──
            pos_text   = f"Ln {self.row+1}/{len(self.lines)}  Col {self.col+1}"
            left_text  = f" {self.status} " if self.status else ""
            fill       = max(0, cols - len(left_text) - len(pos_text) - 3)
            status_bar = "\u2570" + left_text + "\u2500" * fill + pos_text + " \u256f"
            self._goto(self.top + total_h - 1, 1)
            self._w("\x1b[2K" + status_bar[:cols])
        elif self.status:
            self._goto(self.top + self.view_h, 1)
            self._w("\x1b[2K" + self.status[:cols])

        # ── place cursor ──
        display_col = max(0, min(self.col - self.h_scroll, inner_w))
        cursor_view_row = max(0, min(self.row - self.v_scroll, self.view_h - 1))
        col_offset = 3 if self.border else 1
        self._goto(content_top + cursor_view_row, display_col + col_offset)
        self._w(ESC + "[?25h")      # show cursor
        self._flush()

    # ── scrolling helpers ─────────────────────────────────────────────────

    def _ensure_visible(self):
        """Adjust scroll so the cursor line/col is visible."""
        # vertical
        if self.row < self.v_scroll:
            self.v_scroll = self.row
        elif self.row >= self.v_scroll + self.view_h:
            self.v_scroll = self.row - self.view_h + 1
        # horizontal
        inner_w = self.cols - 4 if self.border else self.cols
        if self.col < self.h_scroll:
            self.h_scroll = self.col
        elif self.col >= self.h_scroll + inner_w:
            self.h_scroll = self.col - inner_w + 1

    def _clamp_col(self):
        self.col = min(self.col, len(self.lines[self.row]))

    # ── file I/O ──────────────────────────────────────────────────────────

    def save(self):
        if not self.filename:
            self.status = "No filename — pass a filename on the command line"
            return False
        try:
            with open(self.filename, "w") as f:
                f.write("\n".join(self.lines))
            self.dirty  = False
            self.status = f"Saved \u2192 {self.filename}"
            return True
        except OSError as e:
            self.status = f"Save failed: {e}"
            return False

    def _join_next_line(self):
        """Append the next line onto the current one and remove it."""
        nxt = self.lines.pop(self.row + 1)
        self.lines[self.row] += nxt
        self.dirty = True

    def _delete_forward(self):
        """Delete the char at the cursor, or join with the next line if at EOL."""
        ln = self.lines[self.row]
        if self.col < len(ln):
            self.lines[self.row] = ln[:self.col] + ln[self.col + 1:]
            self.dirty = True
        elif self.row < len(self.lines) - 1:
            self._join_next_line()

    def _kill_to_eol(self):
        """Delete from cursor to end of line, or join with next line if at EOL."""
        ln = self.lines[self.row]
        if self.col < len(ln):
            self.lines[self.row] = ln[:self.col]
            self.dirty = True
        elif self.row < len(self.lines) - 1:
            self._join_next_line()

    # ── main loop ─────────────────────────────────────────────────────────

    def run(self):
        total_h = self.view_h + 2 if self.border else self.view_h
        self.cols, self.rows = term_size()
        MIN_COLS = 20
        if self.cols < MIN_COLS:
            sys.exit(f"tiny: terminal too narrow (need at least {MIN_COLS} columns)")

        # Reserve vertical space: print blank lines then walk back up.
        # We reserve total_h-1 rows so the cursor's landing row is the last
        # row of the editor itself (no blank gap below during editing).
        # The \n on exit then scrolls the prompt onto a fresh line.
        reserve_h = total_h - 1
        sys.stdout.write("\n" * reserve_h)
        sys.stdout.flush()
        cur_row, _ = get_cursor_pos()
        self.top = cur_row - reserve_h  # absolute terminal row of first editor row
        fd  = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            self.render()

            while True:
                key = read_key(fd)
                self.status = ""

                # ── quit ──
                if key == "\x11":                    # Ctrl+Q
                    if self.dirty:
                        self.status = "Unsaved changes \u2014 save? (y / n)"
                        self.render()
                        ans = read_key(fd)
                        if ans in ("y", "Y"):
                            self.save()
                    break

                # ── save ──
                elif key == "\x13":                  # Ctrl+S
                    self.save()

                # ── movement ──
                elif key == K_UP:
                    if self.row > 0:
                        self.row -= 1
                        self._clamp_col()

                elif key == K_DOWN:
                    if self.row < len(self.lines) - 1:
                        self.row += 1
                        self._clamp_col()

                elif key == K_LEFT:
                    if self.col > 0:
                        self.col -= 1
                    elif self.row > 0:
                        self.row -= 1
                        self.col = len(self.lines[self.row])

                elif key == K_RIGHT:
                    if self.col < len(self.lines[self.row]):
                        self.col += 1
                    elif self.row < len(self.lines) - 1:
                        self.row += 1
                        self.col = 0

                elif key in (K_HOME, K_HOME2, "\x01"):   # Home / Ctrl+A
                    self.col = 0

                elif key in (K_END, K_END2, "\x05"):     # End / Ctrl+E
                    self.col = len(self.lines[self.row])

                elif key == K_PGUP:
                    self.row = max(0, self.row - self.view_h)
                    self._clamp_col()

                elif key == K_PGDN:
                    self.row = min(len(self.lines) - 1, self.row + self.view_h)
                    self._clamp_col()

                # ── editing ──
                elif key in ("\r", "\n"):               # Enter
                    line = self.lines[self.row]
                    self.lines[self.row] = line[:self.col]
                    self.lines.insert(self.row + 1, line[self.col:])
                    self.row  += 1
                    self.col   = 0
                    self.dirty = True

                elif key in ("\x7f", "\x08"):           # Backspace
                    if self.col > 0:
                        ln = self.lines[self.row]
                        self.lines[self.row] = ln[:self.col - 1] + ln[self.col:]
                        self.col  -= 1
                        self.dirty = True
                    elif self.row > 0:
                        prev = self.lines[self.row - 1]
                        cur  = self.lines.pop(self.row)
                        self.row -= 1
                        self.col  = len(prev)
                        self.lines[self.row] = prev + cur
                        self.dirty = True

                elif key == K_DEL:                      # Delete
                    self._delete_forward()

                elif key == "\x0b":                     # Ctrl+K — kill to EOL
                    self._kill_to_eol()

                elif len(key) == 1 and (0x20 <= ord(key) <= 0x7E or ord(key) > 0x7F):
                    # Printable ASCII or multibyte UTF-8 character
                    ln = self.lines[self.row]
                    self.lines[self.row] = ln[:self.col] + key + ln[self.col:]
                    self.col  += 1
                    self.dirty = True

                self._ensure_visible()
                self.render()

        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
            # Leave cursor on the line just below the editor.
            self._goto(self.top + total_h, 1)
            self._w("\n")
            self._flush()


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="tiny — a small inline terminal text editor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("file",  nargs="?",
                    help="file to edit (created on save if absent)")
    ap.add_argument("-n", "--lines", type=int, default=10,
                    help="number of visible content rows (default: 10)")
    ap.add_argument("-p", "--plain", action="store_true",
                    help="omit the title/status frame and box-drawing borders")
    args = ap.parse_args()

    if not sys.stdin.isatty():
        ap.error("tiny requires an interactive terminal")

    Editor(args.file, args.lines, border=not args.plain).run()


if __name__ == "__main__":
    main()
