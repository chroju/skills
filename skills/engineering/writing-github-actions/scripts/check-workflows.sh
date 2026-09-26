#!/usr/bin/env bash
# Checks the hardening rules that actionlint and zizmor do not cover:
#   - every job that runs steps has timeout-minutes
#   - the workflow sets concurrency
#   - cancel-in-progress is never a literal `true` on a workflow that also
#     runs on push (default-branch runs must finish; deploys must queue)
# Usage: check-workflows.sh <workflow.yaml>...
# Exit status: 0 when clean, 1 when any finding, 2 on usage/tool errors.
set -euo pipefail

if [ "$#" -eq 0 ]; then
  echo "usage: $0 <workflow.yaml>..." >&2
  exit 2
fi

# mikefarah/yq v4 is required to parse YAML. Fall back to an ephemeral
# run through mise when it is not installed.
if yq --version 2>/dev/null | grep -q mikefarah; then
  YQ=(yq)
elif command -v mise >/dev/null 2>&1; then
  YQ=(mise exec yq@4.53.6 -- yq)
else
  echo "error: mikefarah/yq v4 not found and mise unavailable to fetch it" >&2
  exit 2
fi

status=0
report() {
  echo "$1: $2"
  status=1
}

for file in "$@"; do
  if [ ! -f "$file" ]; then
    echo "error: $file not found" >&2
    exit 2
  fi

  # Jobs that call a reusable workflow (`uses:`) cannot take timeout-minutes.
  while IFS= read -r job; do
    [ -n "$job" ] && report "$file" "job '$job' has no timeout-minutes"
  done < <("${YQ[@]}" '.jobs | to_entries | .[]
    | select(.value.uses == null and .value["timeout-minutes"] == null)
    | .key' "$file")

  if [ "$("${YQ[@]}" 'has("concurrency")' "$file")" != "true" ]; then
    report "$file" "no top-level concurrency"
    continue
  fi

  cancel=$("${YQ[@]}" '.concurrency["cancel-in-progress"] // ""' "$file")
  # `on:` may be a map, a single event string, or a list of events.
  on_push=$("${YQ[@]}" '(.on | select(tag == "!!map") | has("push"))
    // (.on | select(tag == "!!str") | . == "push")
    // (.on | select(tag == "!!seq") | any_c(. == "push"))
    // false' "$file")
  if [ "$cancel" = "true" ] && [ "$on_push" = "true" ]; then
    report "$file" "cancel-in-progress is always true but the workflow runs on push; use \${{ github.event_name == 'pull_request' }} (CI) or false (deploy)"
  fi
done

exit "$status"
