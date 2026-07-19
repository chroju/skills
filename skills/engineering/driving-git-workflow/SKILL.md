---
name: driving-git-workflow
description: Drives the git development workflow end to end — worktree-based branching, incremental commits, pull requests, CI watch-and-fix loops, review response, and merge with cleanup. Use when starting work on a feature, fix, or issue in a git repository, when committing or pushing changes, when creating a pull request, or when a PR's CI checks or review comments need attention.
license: MIT
---

# Driving Git Workflow

Workflow rules from branch creation to merge. One principle overrides
everything below: **the repository's own conventions win**. Before the
first commit, check `.github/` (templates, workflows), `CONTRIBUTING`,
commitlint config or `.gitmessage`, and the style of recent commits and
PRs. Where the repository has a convention — format, scope, language —
follow it and treat this skill as the fallback. Write in English unless
recent commits/PRs are predominantly in another language.

## Branching: always a worktree

Never commit work directly on the default branch, and do not switch the
main checkout to a feature branch — use a git worktree per task:

- If the EnterWorktree tool is available, use it (pass the branch name
  as `name`); the session moves into the worktree.
- Otherwise:

  ```bash
  git check-ignore -q .local || echo ".local/" >> "$(git rev-parse --git-common-dir)/info/exclude"
  git worktree add "$(git rev-parse --show-toplevel)/.local/worktrees/<branch>" -b <branch>
  ```

Branch names are descriptive with a type prefix: `feat/add-auth`,
`fix/empty-name-fallback`.

## Commits: proactive, small, explained

Commit on your own initiative at each logical unit of work — do not
save everything for one commit at the end, and do not mix unrelated
changes in one commit. Stage explicitly (`git add <files>`, never
`git add -A`).

Message format (repository convention first; this is the fallback):

```
<type>(<scope>): <imperative subject, ≤50 chars>

<why this change was needed and what it does, wrapped at 72 chars,
about 5 lines maximum>

Refs #<issue>

Co-Authored-By: Claude <model name> <noreply@anthropic.com>
```

- The body states the reason, not the mechanics. A change whose reason
  is fully carried by the subject (e.g. a typo fix) may omit the body.
- When the work originates from an issue, put `Refs #N` in the footer.
  Reserve closing keywords (`Closes #N`, `Fixes #N`) for the PR body so
  the issue closes when the PR merges, not before.

Push policy: while no PR exists, keep commits local (history can still
be reorganized). Push when creating the PR; once a PR exists, push
after every commit so CI runs.

## Pull requests

Fill the repository's PR template if one exists under `.github/`.
Fallback body: a Summary and a Test plan, in prose matched to the
repository's language. Issue references (`Closes #N`) go on their own
bullet line — GitHub only expands link previews for list items. End
the body with the attribution line (below).

After creating the PR, start the CI loop.

## CI loop

1. `gh pr checks <number> --watch` and wait for completion.
2. All green → report, and ask the user about merging.
3. On failure: `gh run view <run-id> --log-failed`, analyze, fix,
   commit, push, and watch again.
4. After **3 failed fix attempts** on the same PR, stop: summarize what
   failed and what was tried, and ask the user how to proceed.

## Review comments

- Clear, code-level requests: fix, commit, push, and reply to the
  thread (with the attribution line).
- Ambiguous or design-level feedback: do not act on it — summarize and
  ask the user.

## Merge and cleanup

Merging is irreversible: **always confirm with the user immediately
before merging**, even when CI is green and the PR is approved. Use the
repository's configured merge method.

After the merge, clean up without asking: leave and remove the worktree
(ExitWorktree with `remove`, or `git worktree remove` plus
`git branch -d`), switch the main checkout to the default branch, and
pull.

## Attribution

Everything published under your hand must say it came from Claude Code
**including the model name** (the session model's display name, e.g.
"Claude Fable 5"):

- Commits: the `Co-Authored-By: Claude <model name>
  <noreply@anthropic.com>` footer shown above — sufficient on its own.
- PR bodies and issue/PR comments — last line:

  ```
  🤖 Generated with [Claude Code](https://claude.com/claude-code) (<model name>)
  ```
