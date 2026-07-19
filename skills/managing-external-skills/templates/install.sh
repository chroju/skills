#!/usr/bin/env bash
# Install (vendor) external Agent Skills declared in skills.txt.
# Requires: gh (authenticated), tar, rsync
#
# Usage:
#   ./install.sh              # read skills.txt and vendor into .claude/skills/
#   ./install.sh --check      # verify manifest matches disk; nonzero exit on drift (for CI)
set -euo pipefail

MANIFEST="skills.txt"
DEST_ROOT=".claude/skills"
MODE="install"
[[ "${1:-}" == "--check" ]] && MODE="check"

fail=0

# Clean up the current tmp dir even when gh/tar aborts the script mid-loop
tmp=""
trap '[[ -n "$tmp" ]] && rm -rf "$tmp"' EXIT

# Reject basename collisions up front: entries from different repos with the
# same basename would silently install to the same destination
dupes="$(grep -Ev '^\s*(#|$)' "$MANIFEST" | awk '{print $2}' | xargs -n1 basename | sort | uniq -d)"
if [[ -n "$dupes" ]]; then
  echo "error: basename collision in $MANIFEST (multiple entries install to the same directory):" >&2
  echo "$dupes" | sed 's/^/  - /' >&2
  exit 1
fi

# Process effective lines (skip comments/blanks); process substitution avoids a subshell
while read -r source path sha; do
  if [[ ! "$sha" =~ ^[0-9a-f]{40}$ ]]; then
    echo "error: SHA is not a 40-char commit hash: $source $path $sha" >&2
    exit 1
  fi

  name="$(basename "$path")"
  dest="$DEST_ROOT/$name"
  tmp="$(mktemp -d)"

  echo "==> $name  ($source @ ${sha:0:7})"
  gh api "repos/$source/tarball/$sha" > "$tmp/src.tar.gz"
  mkdir -p "$tmp/src"
  tar xzf "$tmp/src.tar.gz" --strip-components=1 -C "$tmp/src"

  if [[ ! -d "$tmp/src/$path" ]]; then
    echo "error: $path does not exist in $source@${sha:0:7}" >&2
    exit 1
  fi

  if [[ "$MODE" == "check" ]]; then
    # Byte-compare the content at the declared SHA against what is on disk
    if ! diff -r "$tmp/src/$path" "$dest" > /dev/null 2>&1; then
      echo "    NG: $dest does not match the manifest (run install.sh to update)" >&2
      fail=1
    else
      echo "    OK"
    fi
  else
    mkdir -p "$dest"
    rsync -a --delete "$tmp/src/$path/" "$dest/"
  fi

  rm -rf "$tmp"
  tmp=""
done < <(grep -Ev '^\s*(#|$)' "$MANIFEST")

# Orphan detection: warn about directories not declared in the manifest
# (ignore the warning if you keep hand-written skills in the same directory)
declared="$(grep -Ev '^\s*(#|$)' "$MANIFEST" | awk '{print $2}' | xargs -n1 basename | sort)"
if [[ -d "$DEST_ROOT" ]]; then
  actual="$(ls -1 "$DEST_ROOT" | sort)"
  orphans="$(comm -13 <(echo "$declared") <(echo "$actual") || true)"
  if [[ -n "$orphans" ]]; then
    echo "warn: skills present but not declared in the manifest:" >&2
    echo "$orphans" | sed 's/^/  - /' >&2
  fi
fi

exit "$fail"
