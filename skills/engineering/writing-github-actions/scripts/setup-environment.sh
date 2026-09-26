#!/usr/bin/env bash
# Creates (or updates) a deployment environment that only the default
# branch can deploy to, then prompts for each secret value and stores it in
# the environment. Safe to re-run.
# Usage: setup-environment.sh <owner/repo> <environment> [SECRET_NAME...]
# Requires: gh (authenticated with repo admin rights). Needs a public
# repository or a paid plan — environment secrets and branch policies are
# unavailable for private repositories on GitHub Free.
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "usage: $0 <owner/repo> <environment> [SECRET_NAME...]" >&2
  exit 2
fi
repo=$1 env=$2
shift 2

branch=$(gh api "repos/$repo" --jq .default_branch)

gh api -X PUT "repos/$repo/environments/$env" --silent --input - <<'EOF'
{"deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}}
EOF

existing=$(gh api "repos/$repo/environments/$env/deployment-branch-policies" \
  --jq ".branch_policies[] | select(.name == \"$branch\" and .type == \"branch\") | .id")
if [ -z "$existing" ]; then
  gh api -X POST "repos/$repo/environments/$env/deployment-branch-policies" \
    --silent -f name="$branch" -f type=branch
fi
echo "environment '$env': deployments limited to branch '$branch'"

for name in "$@"; do
  # gh prompts for the value on a TTY; pipe it in when running unattended.
  gh secret set "$name" --repo "$repo" --env "$env"
done
