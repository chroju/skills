#!/usr/bin/env bash
# Install (vendor) external Agent Skills declared in skills.yaml.
# Requires: gh (authenticated), yq (mikefarah v4), tar, rsync
#
# Each entry has a scope deciding its install destination:
#   project (default) -> ./.claude/skills/  (relative to this manifest)
#   user              -> ~/.claude/skills/
#
# Usage:
#   ./install.sh              # vendor all entries
#   ./install.sh --check      # verify manifest matches disk; nonzero exit
#                             # on drift (for CI)
#
# On CI runners (GITHUB_ACTIONS=true) user-scope entries are skipped:
# the runner's $HOME is not the machine the entry targets.
set -euo pipefail

MANIFEST="skills.yaml"
PROJECT_DEST=".claude/skills"
USER_DEST="$HOME/.claude/skills"
MODE="install"
[[ "${1:-}" == "--check" ]] && MODE="check"

for cmd in gh yq tar rsync; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "error: required command not found: $cmd" >&2; exit 1; }
done

count="$(yq '.skills | length' "$MANIFEST")"
if [[ ! "$count" =~ ^[0-9]+$ || "$count" -eq 0 ]]; then
  echo "error: no entries under .skills in $MANIFEST" >&2
  exit 1
fi

fail=0

# Clean up the current tmp dir even when gh/tar aborts the script mid-loop
tmp=""
trap '[[ -n "$tmp" ]] && rm -rf "$tmp"' EXIT

# Reject basename collisions within the same scope up front: such entries
# would silently install to the same destination
dupes="$(yq '.skills[] | (.scope // "project") + " " + (.path | split("/") | .[-1])' "$MANIFEST" | sort | uniq -d)"
if [[ -n "$dupes" ]]; then
  echo "error: basename collision in $MANIFEST (multiple entries install to the same directory):" >&2
  echo "$dupes" | sed 's/^/  - /' >&2
  exit 1
fi

for ((i = 0; i < count; i++)); do
  source="$(yq ".skills[$i].repo" "$MANIFEST")"
  path="$(yq ".skills[$i].path" "$MANIFEST")"
  sha="$(yq ".skills[$i].sha" "$MANIFEST")"
  scope="$(yq ".skills[$i].scope // \"project\"" "$MANIFEST")"

  if [[ ! "$sha" =~ ^[0-9a-f]{40}$ ]]; then
    echo "error: SHA is not a 40-char commit hash: $source $path $sha" >&2
    exit 1
  fi

  case "$scope" in
    project) dest_root="$PROJECT_DEST" ;;
    user)    dest_root="$USER_DEST" ;;
    *)
      echo "error: invalid scope '$scope' for $source $path (use project or user)" >&2
      exit 1
      ;;
  esac

  name="$(basename "$path")"
  dest="$dest_root/$name"

  if [[ "$scope" == "user" && "${GITHUB_ACTIONS:-}" == "true" ]]; then
    echo "==> $name  ($source @ ${sha:0:7}, user scope) — skipped on CI"
    continue
  fi

  echo "==> $name  ($source @ ${sha:0:7}, $scope scope)"

  if [[ "$MODE" == "check" && "$scope" == "user" && ! -d "$dest" ]]; then
    # A user-scope entry not installed on this machine is not drift;
    # run install.sh to install it.
    echo "    skip: not installed at $dest"
    continue
  fi

  tmp="$(mktemp -d)"
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
done

# Orphan detection, project scope only: ~/.claude/skills legitimately holds
# skills managed by other means (hand-written, gh skill install), so only
# the project directory is compared against the manifest
declared="$(yq '.skills[] | select((.scope // "project") == "project") | .path | split("/") | .[-1]' "$MANIFEST" | sort)"
if [[ -d "$PROJECT_DEST" ]]; then
  actual="$(ls -1 "$PROJECT_DEST" | sort)"
  orphans="$(comm -13 <(echo "$declared") <(echo "$actual") || true)"
  if [[ -n "$orphans" ]]; then
    echo "warn: skills present but not declared in the manifest:" >&2
    echo "$orphans" | sed 's/^/  - /' >&2
  fi
fi

exit "$fail"
