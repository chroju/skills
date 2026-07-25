#!/usr/bin/env bash
# Install (vendor) external Agent Skills declared in skills.yaml.
# Requires: gh (authenticated), yq (mikefarah v4), tar, rsync
#
# Each entry has a scope deciding its install destination:
#   project (default) -> ./.claude/skills/  (relative to this manifest)
#   user              -> ~/.claude/skills/
#
# An entry with `bulk: true` treats `path` as a tree: every directory
# under it containing a SKILL.md is installed as an individual skill.
#
# Usage:
#   ./install-skills.sh              # vendor all entries
#   ./install-skills.sh --check      # verify manifest matches disk; nonzero
#                                    # exit on drift (for CI)
#
# On CI runners (GITHUB_ACTIONS=true) user-scope entries are skipped:
# the runner's $HOME is not the machine the entry targets.
set -euo pipefail

# The manifest sits next to this script, and project-scope installs are
# relative to it — operate from the script's own directory so invoking
# this script from any working directory behaves the same.
cd "$(dirname "${BASH_SOURCE[0]}")"

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

# Reject basename collisions between non-bulk entries in the same scope up
# front: such entries would silently install to the same destination. Bulk
# entries' skill names are only known after fetching, so those are checked
# against $seen inside the loop instead.
dupes="$(yq '.skills[] | select((.bulk // false) == false) | (.scope // "project") + " " + (.path | split("/") | .[-1])' "$MANIFEST" | sort | uniq -d)"
if [[ -n "$dupes" ]]; then
  echo "error: basename collision in $MANIFEST (multiple entries install to the same directory):" >&2
  echo "$dupes" | sed 's/^/  - /' >&2
  exit 1
fi

seen=""              # "<scope> <name>" pairs claimed during this run
declared_project=""  # project-scope skill names, for orphan detection

for ((i = 0; i < count; i++)); do
  source="$(yq ".skills[$i].repo" "$MANIFEST")"
  path="$(yq ".skills[$i].path" "$MANIFEST")"
  sha="$(yq ".skills[$i].sha" "$MANIFEST")"
  scope="$(yq ".skills[$i].scope // \"project\"" "$MANIFEST")"
  bulk="$(yq ".skills[$i].bulk // false" "$MANIFEST")"

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

  if [[ "$scope" == "user" && "${GITHUB_ACTIONS:-}" == "true" ]]; then
    echo "==> $source/$path  (@ ${sha:0:7}, user scope) — skipped on CI"
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

  skill_srcs=()
  if [[ "$bulk" == "true" ]]; then
    while IFS= read -r dir; do
      skill_srcs+=("$dir")
    done < <(find "$tmp/src/$path" -type f -name SKILL.md | sed 's|/SKILL\.md$||' | sort)
    if [[ ${#skill_srcs[@]} -eq 0 ]]; then
      echo "error: no SKILL.md found under $path in $source@${sha:0:7}" >&2
      exit 1
    fi
  else
    skill_srcs=("$tmp/src/$path")
  fi

  for src in "${skill_srcs[@]}"; do
    name="$(basename "$src")"
    dest="$dest_root/$name"

    if grep -qxF "$scope $name" <<< "$seen"; then
      echo "error: multiple entries install the $scope-scope skill '$name'" >&2
      exit 1
    fi
    seen+="$scope $name"$'\n'
    if [[ "$scope" == "project" ]]; then
      declared_project+="$name"$'\n'
    fi

    echo "==> $name  ($source @ ${sha:0:7}, $scope scope)"

    if [[ "$MODE" == "check" && "$scope" == "user" && ! -d "$dest" ]]; then
      # A user-scope skill not installed on this machine is not drift;
      # run install-skills.sh to install it.
      echo "    skip: not installed at $dest"
      continue
    fi

    if [[ "$MODE" == "check" ]]; then
      # Byte-compare the content at the declared SHA against what is on disk
      if ! diff -r "$src" "$dest" > /dev/null 2>&1; then
        echo "    NG: $dest does not match the manifest (run install-skills.sh to update)" >&2
        fail=1
      else
        echo "    OK"
      fi
    else
      mkdir -p "$dest"
      rsync -a --delete "$src/" "$dest/"
    fi
  done

  rm -rf "$tmp"
  tmp=""
done

# Orphan detection, project scope only: ~/.claude/skills legitimately holds
# skills managed by other means (hand-written, gh skill install), so only
# the project directory is compared against the manifest. Bulk entries'
# names are collected while fetching, so this runs after the loop in both
# modes.
declared="$(printf '%s' "$declared_project" | sort)"
if [[ -d "$PROJECT_DEST" ]]; then
  actual="$(ls -1 "$PROJECT_DEST" | sort)"
  orphans="$(comm -13 <(echo "$declared") <(echo "$actual") || true)"
  if [[ -n "$orphans" ]]; then
    echo "warn: skills present but not declared in the manifest:" >&2
    echo "$orphans" | sed 's/^/  - /' >&2
  fi
fi

exit "$fail"
