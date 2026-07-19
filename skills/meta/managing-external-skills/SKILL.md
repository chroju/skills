---
name: managing-external-skills
description: Declarative management (vendoring) of external Agent Skills via a SHA-pinned skills.yaml, supporting project and user scope. Use this skill whenever asked to add, update, remove, or verify external skills, to set up skills.yaml-based management in a repository or dotfiles, to edit or troubleshoot skills.yaml / install.sh / renovate.json / sync-skills.yaml, or when the user says things like "install this skill", "update external skills", or "add this to skills.yaml". Also use it to troubleshoot Renovate PR behavior or drift between the manifest and vendored files.
license: MIT
---

# Managing External Skills

Operational guide for managing external Agent Skills declaratively:
dependencies are declared in `skills.yaml` (SHA-pinned, with a scope per
entry) and installed by `install.sh`. The manifest lives in whatever git
repository suits the entries — a project repository, a dotfiles
repository, or both patterns mixed in one file.

## Files

| File | Role |
|---|---|
| `skills.yaml` | Dependency manifest: list of `{repo, path, sha, scope}` entries |
| `install.sh` | Fetch tarball → extract subpath → install via `rsync --delete`. `--check` verifies integrity. Requires gh (authenticated), yq (mikefarah v4), tar, rsync |
| `renovate.json` | Auto-bumps SHAs to the head of the tracked branch via the git-refs datasource |
| `.github/workflows/sync-skills.yaml` | Re-vendors on Renovate PRs; runs `--check` on other PRs |

## Scopes

Each entry installs to a destination decided by its `scope`:

- `project` (default): `./.claude/skills/` relative to the manifest —
  vendored into the repository, verified by CI.
- `user`: `~/.claude/skills/` of the machine running install.sh — shared
  across all projects on that machine.

Scope characteristics that shape operations:

- On CI runners (`GITHUB_ACTIONS=true`) install.sh skips user-scope
  entries entirely: CI can vendor and verify only project scope.
- User-scope updates take effect per machine, only when install.sh is
  rerun there. After merging a Renovate bump for a user-scope entry, run
  `./install.sh` on each machine (e.g. as part of dotfiles apply).
- `./install.sh --check` treats a user-scope entry that is not installed
  on the current machine as a skip, not a failure.
- Orphan detection covers project scope only — `~/.claude/skills/`
  legitimately holds skills managed by other means (hand-written,
  `gh skill install --scope user`).

## Initial setup (scaffolding a repository)

Copy the files from this skill's `templates/` directory into the target
repository (a project repository or a dotfiles repository):

| Template | Destination |
|---|---|
| `templates/skills.yaml` | repository root (replace example entries with real ones) |
| `templates/install.sh` | repository root (`chmod +x install.sh`) |
| `templates/renovate.json` | repository root (merge into an existing renovate.json if one exists) |
| `templates/sync-skills.yaml` | `.github/workflows/sync-skills.yaml` |

Then follow the "add" procedure below for each initial dependency, run
`./install.sh`, and commit everything together.

## skills.yaml format rules (fragile — follow strictly)

```yaml
skills:
  - repo: anthropics/skills
    path: skills/skill-creator
    # renovate: datasource=git-refs depName=https://github.com/anthropics/skills currentValue=main
    sha: "3f2a1b...full-40-char-sha"
    scope: user   # optional; project (default) or user
```

- **The renovate comment must sit directly above the `sha:` line it
  updates.** Renovate's regex matches the comment and the sha across a
  single newline; any line in between silently disables auto-updates for
  that entry.
- Quote the sha (an all-digit sha would otherwise parse as a number).
- `currentValue` is the branch to track (usually `main`), not a tag.
- SHAs must be the full 40-character form. install.sh rejects short SHAs.

## Operations

### Add

1. Resolve the head SHA of the tracked branch:
   ```bash
   sha=$(gh api "repos/OWNER/REPO/commits/BRANCH" -q .sha)
   ```
2. Verify the path exists at that SHA (catches typos early):
   ```bash
   gh api "repos/OWNER/REPO/contents/PATH?ref=$sha" -q 'type'  # should print "dir"
   ```
3. Decide the scope with the user if not obvious: shared across their
   machine (`user`) or part of this repository (`project`).
4. Append the entry (renovate comment directly above `sha:`) to skills.yaml.
5. Run `./install.sh`.
6. **For project scope, commit skills.yaml and the `.claude/skills/` diff
   together in one commit** — splitting them makes `--check` fail. For
   user scope, commit skills.yaml alone (nothing is vendored into the
   repository). Example message:
   `feat: add external skill <name> (<owner/repo>@<short-sha>)`

### Update

Normally leave this to Renovate (weekly on Mondays; review the upstream diff
in the PR and merge). To update manually, re-resolve the SHA as in step 1 of
"Add", replace it in skills.yaml, and run `./install.sh`.
To pin to a specific tagged version, resolve the tag to a SHA:
```bash
gh api "repos/OWNER/REPO/git/ref/tags/TAG" -q .object.sha
```

### Remove

1. Delete the entry from skills.yaml.
2. Remove the installed copy: `rm -rf .claude/skills/<name>` for project
   scope, `rm -rf ~/.claude/skills/<name>` for user scope (name is the
   basename of the path).
3. For a forgotten project-scope removal, install.sh warns about the
   orphaned directory; user scope has no orphan detection, so step 2 is
   on you.

### Verify

```bash
./install.sh --check
```
Byte-compares the content at the declared SHA against disk. Nonzero exit on
drift. CI runs the same check (project scope only).

## Pitfalls

- **Never edit installed files directly.** The next `install.sh` run will
  clobber them via `rsync --delete`. To change a skill, send a PR upstream
  or point skills.yaml at a fork.
- **Basename collisions**: the install destination is
  `<scope-root>/<basename-of-path>`, so entries with the same basename in
  the same scope collide. install.sh rejects colliding manifests with an
  error. Before adding, check for a basename conflict with existing
  entries; if one exists, report it and ask the user how to proceed.
- **Hand-written skills alongside vendored ones**: skills kept directly in
  `.claude/skills/` will show up in install.sh's orphan warning. Never
  mistake them for removable vendored leftovers.
- **Vendored-file sync on Renovate PRs**: Renovate only rewrites
  skills.yaml; sync-skills.yaml pushes the vendored diff. If that workflow
  failed and the Renovate PR is merged anyway, `--check` will fail on
  main. Before merging, confirm the PR contains a
  `chore: vendor skills per skills.yaml` commit (only needed when
  project-scope entries changed).
- **User-scope drift is invisible to CI**: a machine that never reruns
  install.sh keeps stale user-scope skills, and nothing fails. Rerun
  install.sh when pulling manifest changes.
- **Required status checks vs the vendor commit**: the vendor commit is
  pushed with `GITHUB_TOKEN`, and GitHub does not trigger workflow runs for
  commits pushed with that token. With branch protection requiring status
  checks, the Renovate PR will hang on a commit with no checks — switch the
  workflow to a PAT or GitHub App token in that case.

## Sunset plan

This mechanism is scheduled for retirement once `gh skill` supports a
manifest/lock workflow. Each skills.yaml entry converts mechanically to
`gh skill install OWNER/REPO NAME --pin SHA --scope <scope>`; write a
migration script first, then delete the four files.
