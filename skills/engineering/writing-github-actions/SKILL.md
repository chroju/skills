---
name: writing-github-actions
description: Hardening and deploy rules for GitHub Actions workflows — least-privilege permissions, timeouts, checkout credentials, concurrency, test-gated deploys, environments, OIDC, and validation. Use whenever creating or editing any file under .github/workflows/, adding CI or a deploy workflow, making a deploy wait for tests, or moving deploy secrets.
license: MIT
---

# Writing GitHub Actions

Action selection and SHA pinning follow the dependency rules of the
project (or a dependency-management skill if installed); this skill does
not repeat them.

## Harden every file you touch

Apply this checklist to **every workflow file you create or edit — the
whole file, not only the lines you changed**. Editing an existing
workflow is where it is most often skipped.

- Top-level `permissions: {}`; grant each job only what it needs
  (e.g. `contents: read`, `id-token: write` for OIDC).
- `timeout-minutes` on every job.
- `persist-credentials: false` on every `actions/checkout`, unless the
  job pushes — then say why.
- `concurrency`: CI workflows
  `group: ${{ github.workflow }}-${{ github.ref }}` with
  `cancel-in-progress: ${{ github.event_name == 'pull_request' }}`
  (superseded PR runs are cancelled; default-branch runs always finish);
  deploy workflows a fixed group with `cancel-in-progress: false` (queue,
  never abort a deploy).

Workflow files you did not need to touch: do not edit them. List the
checklist items they miss in your report instead.

## Deploys

**Gate on tests with `needs`, not `workflow_run`.** Make the test
workflow reusable (`on: workflow_call` added to its triggers) and call it
from the deploy workflow:

```yaml
jobs:
  test:
    uses: ./.github/workflows/test.yaml
  deploy:
    needs: test
```

Then remove the default-branch `push` trigger from the test workflow
(keep its `pull_request` trigger) — the deploy workflow now runs the
tests on that push, and keeping both runs them twice.

Do not chain them with `workflow_run` (or `pull_request_target`): that
splits test and deploy into separately triggered runs, while `needs`
keeps both in one run on the same commit.

**Credentials: OIDC first.** Check the deploy target's docs for GitHub
OIDC federation (AWS, Google Cloud, Azure and others support it). If
supported, use it (`id-token: write`) and scope the cloud-side trust to
the environment through the `sub` claim. Check the repository's actual
`sub` format before writing the trust policy: newer repositories (and
ones that opted in) use immutable subjects with owner and repository IDs
(`repo:<owner>@<owner-id>/<repo>@<repo-id>:...`) instead of
`repo:<owner>/<repo>:...`. If
not, use a narrowly scoped API token and state in the report that the
target has no OIDC support.

**Where the secrets live** depends on what the repository can use:

- Public repository, or private on a paid plan: put the deploy job in an
  environment (`environment: production`), store its secrets there, and
  restrict deployment to the default branch:

  ```bash
  gh api -X PUT repos/<repo>/environments/production --input - <<'EOF'
  {"deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}}
  EOF
  gh api -X POST repos/<repo>/environments/production/deployment-branch-policies \
    -f name=<default-branch> -f type=branch
  gh secret set <NAME> --env production
  ```

  Move existing repository-level deploy secrets into the environment and
  delete the repository-level copies.
- Private repository on the Free plan (environment secrets and branch
  policies unavailable): keep the deploy in its own workflow triggered
  only by `push` to the default branch (plus `workflow_dispatch` if
  wanted), so no PR-triggered workflow ever runs with deploy secrets.

## Validate

Run `actionlint` and `zizmor` on the changed files if they are installed
and fix what they report. If either is missing, say in the report that
it was skipped — do not substitute a generic YAML check silently.
