#!/usr/bin/env bash
# Creates (or updates) a deployment environment that only one ref pattern
# can deploy to — the default branch by default, or a tag pattern for
# tag-triggered releases — then prompts for each secret value and stores
# it in the environment. Safe to re-run.
# Usage: setup-environment.sh [--tag <pattern>] <owner/repo> <environment> [SECRET_NAME...]
#   --tag 'v*'   allow only tags matching the pattern instead of the default branch
# Requires: gh (authenticated with repo admin rights). Needs a public
# repository or a paid plan — environment secrets and branch policies are
# unavailable for private repositories on GitHub Free.
set -euo pipefail

usage() {
  echo "usage: $0 [--tag <pattern>] <owner/repo> <environment> [SECRET_NAME...]" >&2
  exit 2
}

type=branch pattern=
if [ "${1:-}" = "--tag" ]; then
  [ "$#" -ge 2 ] || usage
  type=tag pattern=$2
  shift 2
fi
[ "$#" -ge 2 ] || usage
repo=$1 env=$2
shift 2

if [ "$type" = branch ]; then
  pattern=$(gh api "repos/$repo" --jq .default_branch)
fi

gh api -X PUT "repos/$repo/environments/$env" --silent --input - <<'EOF'
{"deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}}
EOF

existing=$(gh api "repos/$repo/environments/$env/deployment-branch-policies" \
  --jq ".branch_policies[] | select(.name == \"$pattern\" and .type == \"$type\") | .id")
if [ -z "$existing" ]; then
  gh api -X POST "repos/$repo/environments/$env/deployment-branch-policies" \
    --silent -f name="$pattern" -f type="$type"
fi
echo "environment '$env': deployments limited to $type '$pattern'"

for name in "$@"; do
  # gh prompts for the value on a TTY; pipe it in when running unattended.
  gh secret set "$name" --repo "$repo" --env "$env"
done
