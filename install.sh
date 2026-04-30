#!/usr/bin/env bash
#
# Installs utilities into ~/bin as symlinks (default) or copies (--copy).
# Symlinks run directly from this directory; copies are independent of it.

set -euo pipefail

COPY=false
for arg in "$@"; do
    case "$arg" in
        -c|--copy) COPY=true ;;
        *) echo "Usage: install.sh [-c|--copy]" >&2; exit 1 ;;
    esac
done

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/bin"

# Each entry is "source_file:installed_name"
UTILS=(
    "git_scan.py:git_scan"
    "tiny.py:tiny"
    "cosmic-tap.sh:cosmic-tap"
)

mkdir -p "$BIN_DIR"

for entry in "${UTILS[@]}"; do
    src="${entry%%:*}"
    name="${entry##*:}"
    target="$REPO_DIR/$src"
    dest="$BIN_DIR/$name"

    if [[ ! -f "$target" ]]; then
        echo "WARNING: source not found, skipping: $target"
        continue
    fi

    if $COPY; then
        cp "$target" "$dest"
        chmod +x "$dest"
        echo "COPIED: $dest"
    else
        if [[ -L "$dest" ]]; then
            existing="$(readlink "$dest")"
            if [[ "$existing" == "$target" ]]; then
                echo "OK (already installed): $dest"
            else
                ln -sf "$target" "$dest"
                echo "UPDATED: $dest -> $target  (was -> $existing)"
            fi
        elif [[ -e "$dest" ]]; then
            echo "SKIPPED: $dest exists but is not a symlink — remove it manually to reinstall"
        else
            ln -s "$target" "$dest"
            echo "INSTALLED: $dest -> $target"
        fi
    fi
done

# Warn if ~/bin is not on PATH
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
        echo ""
        echo "WARNING: $BIN_DIR is not in your PATH."
        echo "Add the following line to your ~/.zshrc (or ~/.bashrc):"
        echo "  export PATH=\"\$HOME/bin:\$PATH\""
        ;;
esac
