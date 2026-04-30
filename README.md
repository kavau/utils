# utils

A small collection of command-line tools for everyday development tasks. Each one is self-contained with no third-party dependencies — just copy, symlink, or run directly.

## Tools

### `tiny` — inline terminal text editor

Edits a file using a small viewport inside your terminal rather than taking over the whole screen. No dependencies beyond the Python stdlib.

```
tiny [file] [-n LINES] [-p]
```

| Key | Action |
|-----|--------|
| Arrows | Move cursor |
| Home / End | Line start / end |
| PgUp / PgDn | Scroll by page |
| Del | Delete char under cursor |
| Ctrl+S | Save |
| Ctrl+Q | Quit (prompts if unsaved) |
| Ctrl+K | Delete to end of line |
| Ctrl+A / Ctrl+E | Line start / end |

Options:
- `-n LINES` — number of visible rows (default: 10)
- `-p` / `--plain` — omit the title/status border

---

### `git_scan` — scan directories for git repo status

Recursively finds all git repositories under a path and reports anything needing attention: uncommitted changes, untracked files, and commits ahead of or behind the remote.

```
git_scan [path] [-f] [-l] [-C]
```

Options:
- `-f` / `--fetch` — run `git fetch` before checking (slower, but shows true remote state)
- `-l` / `--local` — ignore repos where only the remote is ahead
- `-C` / `--no-color` — disable ANSI colour output

---

### `cosmic-tap` — Super key double-tap for COSMIC desktop

Makes the Super key context-sensitive: a single tap opens the Launcher, a double tap opens the App Library. Uses a 200 ms window and a `/dev/shm` state file to distinguish the two.

Requires COSMIC desktop. Setup:
1. Set the default Super key action to **Disabled** in COSMIC Settings
2. Add a custom keyboard shortcut: `Super` → `cosmic-tap`

---

## Installation

```bash
./install.sh          # install as symlinks (default)
./install.sh --copy   # copy files instead; repo can be moved or deleted afterwards
```

Installs into `~/bin` without file extensions (`tiny`, `git_scan`, `cosmic-tap`).
