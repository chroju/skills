#!/usr/bin/env bash
# Runs actionlint, zizmor, and check-workflows.sh on the given workflow
# files. Tools that are not installed are fetched for this run only, at the
# pinned versions below (both released well past a 7-day cooldown).
# Usage: validate.sh <file>...   (workflow files and .github/dependabot.yml)
# Exit status: 0 when every check passes, 1 otherwise, 2 on setup errors.
set -uo pipefail

ACTIONLINT_VERSION=1.7.12
ZIZMOR_VERSION=1.30.1

if [ "$#" -eq 0 ]; then
  echo "usage: $0 <workflow.yaml>..." >&2
  exit 2
fi
here=$(cd "$(dirname "$0")" && pwd)

# A command on PATH may be an unconfigured shim; require that it runs.
works() { "$@" --version >/dev/null 2>&1; }

if works actionlint; then
  ACTIONLINT=(actionlint)
elif command -v mise >/dev/null 2>&1; then
  ACTIONLINT=(mise exec "actionlint@$ACTIONLINT_VERSION" -- actionlint)
else
  echo "error: actionlint not installed and mise unavailable to fetch it" >&2
  exit 2
fi

if works zizmor; then
  ZIZMOR=(zizmor)
elif command -v uvx >/dev/null 2>&1; then
  ZIZMOR=(uvx "zizmor@$ZIZMOR_VERSION")
elif command -v mise >/dev/null 2>&1; then
  ZIZMOR=(mise exec "zizmor@$ZIZMOR_VERSION" -- zizmor)
else
  echo "error: zizmor not installed and neither uvx nor mise available to fetch it" >&2
  exit 2
fi

# zizmor's online audits (e.g. known-vulnerable actions) need a token.
if [ -z "${GH_TOKEN:-}" ] && command -v gh >/dev/null 2>&1; then
  GH_TOKEN=$(gh auth token 2>/dev/null || true)
  export GH_TOKEN
fi

# zizmor audits every file (workflows, dependabot.yml, action.yml);
# actionlint and check-workflows only understand workflow files.
workflows=()
for f in "$@"; do
  case "$f" in
    */.github/workflows/*.yml|*/.github/workflows/*.yaml|.github/workflows/*.yml|.github/workflows/*.yaml)
      workflows+=("$f") ;;
  esac
done

status=0
if [ "${#workflows[@]}" -gt 0 ]; then
  echo "== actionlint"
  "${ACTIONLINT[@]}" "${workflows[@]}" || status=1
fi
echo "== zizmor"
"${ZIZMOR[@]}" --config "$here/zizmor.yml" "$@" || status=1
if [ "${#workflows[@]}" -gt 0 ]; then
  echo "== check-workflows"
  "$here/check-workflows.sh" "${workflows[@]}" || status=1
fi

exit "$status"
