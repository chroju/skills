---
name: managing-external-skills
description: Declarative management (vendoring) of external Agent Skills via skills.txt. Use this skill whenever asked to add, update, remove, or verify external skills, to set up skills.txt-based management in a repository, to edit or troubleshoot skills.txt / install.sh / renovate.json / sync-skills.yaml, or when the user says things like "install this skill", "update external skills", or "add this to skills.txt". Also use it to troubleshoot Renovate PR behavior or drift between the manifest and vendored files.
license: MIT
---

# Managing External Skills

Operational guide for managing external Agent Skills declaratively in a
repository: dependencies are declared in `skills.txt` (SHA-pinned) and
vendored into `.claude/skills/` by `install.sh`.

## Files

| File | Role |
|---|---|
| `skills.txt` | Dependency manifest. Three columns: `<owner/repo> <path-in-repo> <40-char commit SHA>` |
| `install.sh` | Fetch tarball → extract subpath → vendor via `rsync --delete`. `--check` verifies integrity |
| `renovate.json` | Auto-bumps SHAs to the head of the tracked branch via the git-refs datasource |
| `.github/workflows/sync-skills.yaml` | Re-vendors on Renovate PRs; runs `--check` on other PRs |

## Initial setup (scaffolding a repository)

Copy the files from this skill's `templates/` directory into the target repository:

| Template | Destination |
|---|---|
| `templates/skills.txt` | repository root (replace example entries with real ones) |
| `templates/install.sh` | repository root (`chmod +x install.sh`) |
| `templates/renovate.json` | repository root (merge into an existing renovate.json if one exists) |
| `templates/sync-skills.yaml` | `.github/workflows/sync-skills.yaml` |

Then follow the "add" procedure below for each initial dependency, run
`./install.sh`, and commit everything together.

## skills.txt format rules (fragile — follow strictly)

```
# renovate: datasource=git-refs depName=https://github.com/anthropics/skills currentValue=main
anthropics/skills document-skills/docx 3f2a1b...full-40-char-sha
```

- **Never put a blank line between the renovate comment and its entry.**
  Renovate's regex matches the two lines across a single newline; a blank
  line silently disables auto-updates for that entry.
- `currentValue` is the branch to track (usually `main`), not a tag.
- SHAs must be the full 40-character form. install.sh rejects short SHAs.
- Blank lines between entries are fine (only the comment/entry pair must be adjacent).

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
3. Append the two lines (renovate comment + entry, no blank line between) to skills.txt.
4. Run `./install.sh` to vendor.
5. **Commit skills.txt and the `.claude/skills/` diff together in one commit.**
   Splitting them makes `--check` fail. Example message:
   `feat: add external skill <name> (<owner/repo>@<short-sha>)`

### Update

Normally leave this to Renovate (weekly on Mondays; review the upstream diff
in the PR and merge). To update manually, re-resolve the SHA as in step 1 of
"Add", replace it in skills.txt, and run `./install.sh`.
To pin to a specific tagged version, resolve the tag to a SHA:
```bash
gh api "repos/OWNER/REPO/git/ref/tags/TAG" -q .object.sha
```

### Remove

1. Delete the two lines (renovate comment + entry) from skills.txt.
2. `rm -rf .claude/skills/<name>` (name is the basename of the path).
3. If you forget step 2, install.sh will warn about the orphaned directory.

### Verify

```bash
./install.sh --check
```
Byte-compares the content at the declared SHA against disk. Nonzero exit on
drift. Same check that CI runs.

## Pitfalls

- **Never edit vendored files directly.** The next `install.sh` run will
  clobber them via `rsync --delete`. To change a skill, send a PR upstream
  or point skills.txt at a fork.
- **Basename collisions**: the install destination is
  `.claude/skills/<basename-of-path>`, so entries from different repos with
  the same basename collide. install.sh rejects colliding manifests with an
  error. Before adding, check for a basename conflict with existing entries;
  if one exists, report it and ask the user how to proceed.
- **Hand-written skills alongside vendored ones**: skills kept directly in
  `.claude/skills/` will show up in install.sh's orphan warning. Never
  mistake them for removable vendored leftovers.
- **Vendored-file sync on Renovate PRs**: Renovate only rewrites skills.txt;
  sync-skills.yaml pushes the vendored diff. If that workflow failed and the
  Renovate PR is merged anyway, `--check` will fail on main. Before merging,
  confirm the PR contains a `chore: vendor skills per skills.txt` commit.
- **Required status checks vs the vendor commit**: the vendor commit is
  pushed with `GITHUB_TOKEN`, and GitHub does not trigger workflow runs for
  commits pushed with that token. With branch protection requiring status
  checks, the Renovate PR will hang on a commit with no checks — switch the
  workflow to a PAT or GitHub App token in that case.

## Sunset plan

This mechanism is scheduled for retirement once `gh skill` supports a
manifest/lock workflow. Each skills.txt entry converts mechanically to
`gh skill install OWNER/REPO NAME --pin SHA`; write a migration script
first, then delete the four files.
