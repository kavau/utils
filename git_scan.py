#!/usr/bin/env python3
"""
Recursively scans subdirectories for git repositories and reports their status:
  - local ahead / remote ahead (compared to tracking branch)
  - untracked files
  - untracked directories

Useful if you have too many git repositories to check manually, or want a quick
overview of their status.

Run with --help for all options.

REQUIREMENTS: Python 3.8+
"""

import os
import subprocess
import sys
import argparse
from pathlib import Path


def build_parser():
    parser = argparse.ArgumentParser(
        description='Scan subdirectories for git repos and report divergence / untracked items.'
    )
    parser.add_argument(
        'path',
        nargs='?',
        default='.',
        help='Root directory to scan (default: current directory)',
    )
    parser.add_argument(
        '-f', '--fetch',
        action='store_true',
        help='Run "git fetch" on each repo before checking (slower but up-to-date)',
    )
    parser.add_argument(
        '-l', '--local',
        action='store_true',
        help='Treat repos where only the remote is ahead as clean',
    )
    parser.add_argument(
        '-C', '--no-colour', '--no-color',
        action='store_true',
        help='Disable ANSI colour output',
    )
    return parser


# ANSI colours
BOLD   = '\033[1m'
RED    = '\033[31m'
GREEN  = '\033[32m'
YELLOW = '\033[33m'
BLUE   = '\033[34m'
CYAN   = '\033[36m'
DIM    = '\033[2m'
RESET  = '\033[0m'


def no_colour():
    global BOLD, RED, GREEN, YELLOW, BLUE, CYAN, DIM, RESET
    BOLD = RED = GREEN = YELLOW = BLUE = CYAN = DIM = RESET = ''


def run(cmd, cwd):
    """Run a command, return (stdout, stderr, returncode)."""
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return result.stdout.rstrip(), result.stderr.strip(), result.returncode


def find_git_repos(root: Path):
    """
    Yield git repo root paths found under *root*.
    Does not recurse inside a found repository.
    """
    try:
        entries = sorted(os.scandir(root), key=lambda e: e.name)
    except PermissionError:
        return

    for entry in entries:
        if not entry.is_dir(follow_symlinks=False):
            continue
        if entry.name.startswith('.'):
            continue
        path = Path(entry.path)
        if (path / '.git').exists() or (path / '.git').is_file():
            yield path
        else:
            yield from find_git_repos(path)


def find_non_git_dirs(root: Path, repos: list):
    """
    Return direct children of *root* that are not git repos and contain
    no git repos (i.e. have no git presence whatsoever).
    """
    # Build the set of directories that are repos or ancestors of repos
    covered: set = set(repos)
    for repo in repos:
        try:
            rel = repo.relative_to(root)
        except ValueError:
            continue
        p = root
        for part in rel.parts:
            p = p / part
            covered.add(p)

    non_git = []
    try:
        entries = sorted(os.scandir(root), key=lambda e: e.name)
    except PermissionError:
        return non_git

    for entry in entries:
        if not entry.is_dir(follow_symlinks=False):
            continue
        if entry.name.startswith('.'):
            continue
        path = Path(entry.path)
        if path not in covered:
            non_git.append(path)

    return non_git


def check_ahead_behind(repo: Path, fetch: bool):
    """
    Return (ahead, behind, message) where ahead/behind are int counts and
    message is a human-readable note (e.g. when there is no upstream).
    """
    if fetch:
        _, fetch_stderr, fetch_rc = run(['git', 'fetch', '--quiet', '--all'], cwd=repo)
        if fetch_rc != 0:
            msg = fetch_stderr or 'git fetch failed (no output)'
            return None, None, f"fetch failed: {msg}"

    stdout, stderr, rc = run(
        ['git', 'rev-list', '--left-right', '--count', 'HEAD...@{upstream}'],
        cwd=repo,
    )
    if rc == 0 and stdout:
        parts = stdout.split()
        if len(parts) == 2:
            return int(parts[0]), int(parts[1]), None

    # No upstream – find out the current branch name for a nicer message
    branch, _, _ = run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd=repo)
    return None, None, f"no upstream configured for branch '{branch}'"


def check_untracked(repo: Path):
    """
    Return (untracked_files, untracked_dirs, changed_files) as lists of
    relative path strings.  Uses -unormal so git reports untracked directories
    as a single entry (dir/).  changed_files covers modified, staged, deleted,
    renamed, etc. (any porcelain entry that is not untracked or ignored).
    """
    stdout, _, rc = run(
        ['git', 'status', '--porcelain', '-unormal'],
        cwd=repo,
    )
    files = []
    dirs = []
    changed = []
    if rc != 0 or not stdout:
        return files, dirs, changed

    for line in stdout.splitlines():
        if not line:
            continue
        xy = line[:2]
        path = line[3:]
        if xy == '??':
            if path.endswith('/'):
                dirs.append(path.rstrip('/'))
            else:
                files.append(path)
        elif xy != '!!':
            changed.append(path)

    return files, dirs, changed


def format_list(items, limit=4):
    if len(items) <= limit:
        return ', '.join(items)
    return ', '.join(items[:limit]) + f' … (+{len(items) - limit} more)'


def get_repo_status(repo: Path, root: Path, fetch: bool, ignore_remote_ahead: bool = False):
    """Return (rel_path, issues) where issues is a list of formatted strings."""
    try:
        rel = repo.relative_to(root)
    except ValueError:
        rel = repo

    issues = []

    # --- ahead / behind ---
    ahead, behind, note = check_ahead_behind(repo, fetch)
    if note:
        if note.startswith('fetch failed:'):
            issues.append(f"{RED}{note}{RESET}")
        else:
            issues.append(f"{DIM}{note}{RESET}")
    else:
        if ahead:
            issues.append(f"{YELLOW}local  ahead  by {ahead} commit(s){RESET}")
        if behind and not ignore_remote_ahead:
            issues.append(f"{RED}remote ahead  by {behind} commit(s){RESET}")

    # --- untracked / changed ---
    untracked_files, untracked_dirs, changed_files = check_untracked(repo)
    if changed_files:
        issues.append(
            f"{YELLOW}uncommitted changes ({len(changed_files)}): "
            f"{format_list(changed_files)}{RESET}"
        )
    if untracked_files:
        issues.append(
            f"{CYAN}untracked files ({len(untracked_files)}): "
            f"{format_list(untracked_files)}{RESET}"
        )
    if untracked_dirs:
        issues.append(
            f"{CYAN}untracked dirs  ({len(untracked_dirs)}): "
            f"{format_list(untracked_dirs)}{RESET}"
        )

    return rel, issues


def main():
    args = build_parser().parse_args()

    if args.no_colour or not sys.stdout.isatty():
        no_colour()

    root = Path(args.path).resolve()
    if (root / '.git').exists() or (root / '.git').is_file():
        repos = [root] + list(find_git_repos(root))
    else:
        repos = list(find_git_repos(root))

    if not repos:
        non_git = find_non_git_dirs(root, repos)
        if non_git:
            print(f"No git repositories found under {root}.")
            print(f"{BOLD}Directories with no git presence:{RESET}")
            for d in non_git:
                try:
                    rel = d.relative_to(root)
                except ValueError:
                    rel = d
                print(f"  {RED}{rel}{RESET}  (not a git repository)")
            print()
        else:
            print('No git repositories found.')
        return

    count = len(repos)
    label = 'repository' if count == 1 else 'repositories'
    suffix = '  (fetching remotes …)' if args.fetch else ''
    print(f"Scanning {count} git {label} under {root}{suffix}")

    results = [get_repo_status(repo, root, args.fetch, args.local) for repo in repos]

    clean = [(rel, issues) for rel, issues in results if not issues]
    unclean = [(rel, issues) for rel, issues in results if issues]

    for rel, _ in clean:
        print(f"{rel}  {GREEN}✓  clean{RESET}")

    for i, (rel, issues) in enumerate(unclean):
        if i > 0 or clean:
            print()
        print(f"{BOLD}{BLUE}{rel}{RESET}")
        for issue in issues:
            print(f"  {issue}")

    non_git = find_non_git_dirs(root, repos)
    if non_git:
        if clean or unclean:
            print()
        print(f"{BOLD}Directories with no git presence:{RESET}")
        for d in non_git:
            try:
                rel = d.relative_to(root)
            except ValueError:
                rel = d
            print(f"  {RED}{rel}{RESET}  (not a git repository)")

    print()


if __name__ == '__main__':
    main()
