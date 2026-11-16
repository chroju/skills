#!/usr/bin/env bash
# Runs actionlint, zizmor, and check-workflows.sh on the given workflow
# files. Tools that are not installed are fetched for this run only, at the
# pinned versions below (both released well past a 7-day cooldown).
# Where a workflow lockfile (.github/workflows/actions.lock) sits next to
# the given workflows, also runs `gh actions-lock --verify` on that
# repository.
# Usage: validate.sh <file>...   (workflow files and .github/dependabot.yml)
# Exit status: 0 when every check passes, 1 otherwise, 2 on setup errors.
set -uo pipefail

ACTIONLINT_VERSION=1.7.12
# 1.32.0 is the first zizmor that reads the workflow lockfile; older
# versions report every locked tag reference as unpinned.
ZIZMOR_VERSION=1.32.0

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

# Repositories (one per line) whose workflows are covered by a lockfile.
lock_roots=
for f in ${workflows[@]+"${workflows[@]}"}; do
  dir=$(cd "$(dirname "$f")" && pwd) || continue
  [ -f "$dir/actions.lock" ] || continue
  root=$(cd "$dir/../.." && pwd)
  case "$lock_roots" in
    *"$root"$'\n'*) ;;
    *) lock_roots+="$root"$'\n' ;;
  esac
done
if [ -n "$lock_roots" ] && ! gh actions-lock --help >/dev/null 2>&1; then
  echo "error: .github/workflows/actions.lock found but the gh actions-lock extension is not installed; run: gh extension install github/gh-actions-lock" >&2
  exit 2
fi

status=0
if [ "${#workflows[@]}" -gt 0 ]; then
  echo "== actionlint"
  # actionlint does not know the `$/...` self-repository syntax yet; the
  # two ignores drop only its format errors for such references.
  "${ACTIONLINT[@]}" \
    -ignore '^reusable workflow call "\$/' \
    -ignore '^specifying action "\$/' \
    "${workflows[@]}" || status=1
fi
echo "== zizmor"
"${ZIZMOR[@]}" --config "$here/zizmor.yml" "$@" || status=1
if [ "${#workflows[@]}" -gt 0 ]; then
  echo "== check-workflows"
  "$here/check-workflows.sh" "${workflows[@]}" || status=1
fi
while IFS= read -r root; do
  [ -n "$root" ] || continue
  echo "== gh actions-lock --verify ($root)"
  (cd "$root" && gh actions-lock --verify) || status=1
done <<<"$lock_roots"

exit "$status"
