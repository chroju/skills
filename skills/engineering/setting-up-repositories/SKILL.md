---
name: setting-up-repositories
description: Sets up a GitHub repository to a baseline — merge settings, default-branch ruleset, security features, agent instructions, toolchain pinning, and release tooling — for a brand-new repository or one existing repository that was never configured. Invoke with /setting-up-repositories <owner/repo>.
disable-model-invocation: true
argument-hint: "<owner/repo>"
license: MIT
---

# Setting Up Repositories

Brings one GitHub repository to the baseline below, whether it is being
created now or already exists. Uses `gh` for everything on GitHub.

## Out of scope — hand off, do not do

Leave these alone even when they look missing; list them in the final
report as follow-ups (name a dedicated skill if one is installed):

- GitHub Actions: workflow files, Actions repository settings, environments,
  secrets, OIDC. If the repository has no CI, report "no CI yet".
- Required status checks in the ruleset. They need a CI check name that has
  already run once, so they are added later by whoever creates the CI.
- Dependency update config (Renovate, Dependabot version updates).

## Workflow

Copy this checklist and track progress:

```
- [ ] 1. Inspect: owner plan, visibility, current state
- [ ] 2. Propose the full list once; ask only for deviations
- [ ] 3. Local files
- [ ] 4. Create / push (new repository only)
- [ ] 5. Repository settings, then the ruleset last
- [ ] 6. Verify and report
```

### 1. Inspect

- Owner plan: `gh api user --jq .plan.name` when the owner is the
  authenticated user; `gh api orgs/<org> --jq .plan.name` for an org.
  Often null (token lacks the `user` scope, or no org admin rights). For a
  private repository with an unknown plan, mark the plan-dependent items
  "only if available" in the proposal and probe after creation (step 6).
- Visibility: from the request for a new repository, from
  `gh repo view <repo> --json visibility` for an existing one.
- Existing repository: read current settings (`gh api repos/<repo>`,
  `gh api repos/<repo>/rulesets`) and the file tree before proposing.
- `gh repo view <owner>/.github` — the owner's shared community-health
  repository (issue/PR templates, SECURITY.md, CONTRIBUTING.md apply to
  every repository that lacks its own).

Feature availability decides what to skip. Never emit a command that the
plan cannot run; list the item as skipped with the reason instead.

| Feature | Public | Private |
|---|---|---|
| Ruleset | yes | Pro / Team / Enterprise only (Free returns 403) |
| Secret scanning, push protection | yes | only if `security_and_analysis.secret_scanning` appears in `gh api repos/<repo>` (needs Secret Protection) |
| Private vulnerability reporting | yes | no (public only) |
| Dependabot alerts | yes | yes |

### 2. Propose once

Show one table: every baseline item, its default value, and its status
(to apply / already satisfied / skipped: reason / handed off). Then ask a
single question: "Anything to change?" Do not ask item-by-item questions.
Apply the defaults for everything the user does not change.

### 3. Local files

Beyond the usual files:

- **Agent instructions: `AGENTS.md` only.** Do not create `CLAUDE.md`.
  If a `CLAUDE.md` exists, propose `git mv CLAUDE.md AGENTS.md`. Claude
  Code reads `AGENTS.md` when no `CLAUDE.md` / `CLAUDE.local.md` exists in
  the directory or above it.
- **Toolchain: `mise.toml`** pins every runtime the project needs
  (`[tools]` section). Do not create `.nvmrc`, `.node-version`,
  `.tool-versions` or similar; if one exists, propose moving its version
  into `mise.toml` and deleting it.
- **Release tooling — only for a distributed artifact** (CLI binary,
  library package): propose release-please; for Go binaries, pair it with
  goreleaser (`.goreleaser.yaml`) so release-please cuts the tag and
  goreleaser builds on it. The workflow files are a GitHub Actions
  hand-off (see Out of scope). Deployed services (web apps, Workers) get
  no release tooling.
- **Community-health files** (SECURITY.md, issue/PR templates,
  CONTRIBUTING.md): do not add them per repository. If `<owner>/.github`
  exists, rely on it; if not, recommend creating it and leave the content
  out of this run.

### 4. Create / push (new repository only)

`gh repo create <owner>/<name> --<visibility> --source=. --push`.

### 5. Repository settings, ruleset last

Merge settings and features (all plans):

```bash
gh api -X PATCH repos/<repo> \
  -F allow_squash_merge=true -F allow_merge_commit=false -F allow_rebase_merge=false \
  -f squash_merge_commit_title=PR_TITLE -f squash_merge_commit_message=PR_BODY \
  -F allow_auto_merge=true -F delete_branch_on_merge=true \
  -F has_wiki=false -F has_projects=false
gh api -X PUT repos/<repo>/vulnerability-alerts
```

Security features, where step 1 found them available:

```bash
gh api -X PATCH repos/<repo> --input - <<'EOF'
{"security_and_analysis": {"secret_scanning": {"status": "enabled"},
 "secret_scanning_push_protection": {"status": "enabled"}}}
EOF
gh api -X PUT repos/<repo>/private-vulnerability-reporting
```

Ruleset — **after** the initial push, because its `pull_request` rule
blocks direct pushes to the default branch. Create it from
[assets/ruleset.json](assets/ruleset.json) (deletion and force-push
blocked, squash as the only merge method, no required status checks):

```bash
gh api -X POST repos/<repo>/rulesets --input <this-skill-dir>/assets/ruleset.json
```

If a default-branch ruleset already exists, update it with
`gh api -X PUT repos/<repo>/rulesets/<id> --input ...` so its rules match
the asset instead of adding a second one.

### 6. Verify and report

Re-read `gh api repos/<repo>` and `gh api repos/<repo>/rulesets` and
confirm each applied item. A 403 on rulesets or a missing
`security_and_analysis` block means the plan lacks the feature — move the
item to "skipped" rather than retrying. Report applied / already
satisfied / skipped (with reason) / handed off.
