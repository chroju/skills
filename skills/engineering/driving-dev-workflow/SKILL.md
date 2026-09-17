---
name: driving-dev-workflow
description: Drives a development task through requirements agreement, design, red/green implementation, review, and PR with CI — autonomously except where a human decision is needed, with codebase reading and implementation delegated to subagents. Invoke with /driving-dev-workflow <what to build>, /driving-dev-workflow <issue number>, or /driving-dev-workflow with no arguments to resume an in-progress task.
disable-model-invocation: true
argument-hint: "[what to build | issue number | (empty to resume)]"
license: MIT
---

# Driving Dev Workflow

You are the orchestrator. You talk to the user, hold the state, and make
the calls that need a human. Everything that consumes context — reading the
codebase, researching, implementing — goes to a subagent.

Ask the user only where a decision is genuinely theirs: what they want,
which trade-off to take, whether a document is approved. Everything else,
decide and proceed.

Documents are written in the language of the conversation. Headings may
stay in English to match the templates.

## Subagents

Two briefs ship with this skill. Read the file, then pass its whole text as
the leading part of the subagent's prompt, followed by the inputs the brief
asks for.

| Role | File | Launch as |
| --- | --- | --- |
| Explorer — reads the codebase, answers technical questions; never writes | `agents/explorer.md` | `subagent_type: Explore` (built-in, has no Edit/Write) |
| Implementer — builds one unit red → green and commits | `agents/implementer.md` | `subagent_type: general-purpose`, `model: sonnet` |

Add `isolation: worktree` to an implementer launch only when running units
in parallel (Step 3).

## Where things live

`WORK` = `$(git rev-parse --git-common-dir)/dev-workflow/<slug>/`. It is
inside `.git`, so it is never committed, is shared by every worktree of the
repository, and survives deleting a worktree.

| File | Content |
| --- | --- |
| `state.json` | Progress, see below |
| `context.md` | What the explorer reported about the codebase |
| `requirements.md`, `design.md` | The agreed documents — unless `where` is an issue |
| `verify.md` | Red/green records from every implementation unit |
| `review.md` | Review findings and what was done about each |

`state.json`:

```json
{
  "slug": "source-mute",
  "phase": "requirements",
  "branch": null,
  "base": "main",
  "where": "WORK"
}
```

`phase` is `requirements` → `design` → `implement` → `review` → `pr` →
`done`. Advance it as each step completes. `where` is `WORK` or
`issue#<n>`: when the task started from an issue, requirements, design,
and any mock are posted as comments on that issue; on revision, edit your
own comment rather than adding another. Never rewrite the issue body — it
may not be yours.

## Git operations

This skill decides *when* git things happen and what they must contain.
*How* they are done — worktree creation, commit granularity and message
format, PR body conventions, the CI watch-and-fix loop, attribution — is
the job of a git workflow skill if one is loaded (for example
`driving-git-workflow`). Follow it wherever the two overlap; the git
instructions below are the fallback when no such skill is present.

The main checkout is never switched. From Step 2 on you work in a feature
worktree, and so do the implementers — they commit on the feature branch
directly. Only when you run implementers in parallel does each get a
worktree of its own, integrated and discarded afterwards.

## Step 0: Start or resume

Run `git rev-parse --git-common-dir`; if it fails, say this needs a git
repository and stop.

**No argument.** Find a `WORK/state.json` whose `branch` matches the current
branch and resume at its `phase`. If none matches, look at the slugs whose
phase is not `done`: one → confirm and resume it; several → ask which;
none → ask what to build. When the resumed state has a `branch` and you
are not in its worktree, move there first (EnterWorktree, or create it as
in Step 2) — nothing after Step 2 runs from the main checkout.

**Argument.** If it is an issue number, `gh issue view <n>` gives the
request and `where` is `issue#<n>`. Otherwise the argument is the request.
Derive a short kebab-case slug, create WORK, write `state.json` with
`phase: "requirements"` and `base` set to the current branch. If that slug
already exists, ask whether to resume or start over.

## Step 1: Requirements

Launch the explorer in **survey** mode with the request. It reads the
codebase — all of it where that fits, the parts that bear on the request
first where it does not — and returns what matters for this request,
existing patterns, the test setup, stated policy (`CLAUDE.md`,
`CONTRIBUTING`, review guidelines, PR template), and anything in the code
that contradicts or complicates the request. Save its report as
`WORK/context.md`. If it reports that it could not cover the repository,
decide whether a second, narrower survey is needed.

Now pin down what the user wants. Collect every ambiguity, edge case, and
scope boundary and ask about them in one round, not one at a time; for the
low-stakes ones, state the default you would take and let the user
override. If the survey found a contradiction or a technical difficulty,
raise it in the same round and settle the direction before writing
anything.

Write the requirements following `templates/requirements.md` (read the
template first). The acceptance criteria are the goal of the whole task:
each must be checkable by a command, a test, or a procedure that a stranger
could run. No implementation detail belongs here. Save to `where`.

Present the document and wait for explicit approval. Only a direct "OK",
"approved", "go ahead" counts; a question or a topic change does not. If
`[OPEN:]` markers remain, resolve them first. On approval, set `phase` to
`design`.

## Step 2: Design

Decide how to build it. Where a technical question needs evidence — how a
library behaves, whether an API supports something, how an existing module
is wired — launch the explorer in **research** mode with the question, and
append the answer to `context.md`.

If the change has a visual component (GUI, TUI, CLI output layout), produce
a mock before anything else: ASCII for terminal output, a static HTML file
or sketch for GUI. It lives with the design: in `WORK/` next to
`design.md`, or in the design comment when `where` is an issue. Agree on
the mock with the user; it becomes part of the design.

If feasibility is in doubt and a spike is cheap, run one: launch a
`general-purpose` subagent with `isolation: worktree` and a narrow brief
("confirm that X can do Y; report the result, do not build anything").
Keep the finding, discard the branch.

Write the design following `templates/design.md` (read the template first).
The verification plan maps every acceptance criterion to the concrete test
or command that proves it. If the repository has a test framework, tests go
in its style; if it has none, do not introduce one — use a reproducible
command or procedure instead. The work breakdown splits the change into
units an implementer can do alone, each with the files it may touch.

Present the design together with a proposed branch name and wait for
explicit approval, by the same rule as Step 1. On approval, create the
feature branch from `base` in a worktree and move into it (EnterWorktree
if available, otherwise `git worktree add .local/worktrees/<branch> -b
<branch>` with `.local/` excluded via `.git/info/exclude`); record the
branch in `state.json` and set `phase` to `implement`. EnterWorktree moves
the whole session, subagents included. The manual fallback does not: then
give every subagent the worktree path and tell it to work there.

## Step 3: Implement

For each unit in the work breakdown, launch an implementer. Give it: the
requirements, the design, the relevant part of `context.md`, its unit, the
files it may touch, the verification entries it must satisfy, and the
commit conventions to follow (from the survey, or from the git workflow
skill's rules — the implementer does not see either on its own). Do not
give it other units or this conversation.

The default is serial: one implementer at a time, working in the feature
worktree and committing on the feature branch. No integration step, linear
history. When one returns, check that the worktree is clean; if it left
uncommitted changes, decide whether they belong to its unit (commit them)
or not (discard them) before the next implementer starts.

Run units in parallel only when several are independent (disjoint file
sets, no dependency between them) and the time saved is worth the
integration. Then launch each with `isolation: worktree`; it commits on a
branch of its own. Integrate each returned branch from the feature
worktree by rebasing it onto the feature branch and fast-forwarding —
resolve rebase conflicts yourself — so the history stays linear, then
remove the worktree and branch. Never leave merge commits.

After each unit lands, run the full verification plan on the feature
branch; a green that held for one unit must still hold with the others.
Append each red/green record to `WORK/verify.md`. If an implementer
reports a problem it could not solve inside its scope, decide: widen the
scope and relaunch, split the unit, or bring it to the user if it changes
the design.

Where a verification entry is a manual procedure the implementer cannot
run, it records what it could observe and marks the entry pending. Before
leaving this step, ask the user to run each pending procedure and record
the outcome in `verify.md`.

When every criterion is green on the feature branch, set `phase` to
`review`.

## Step 4: Review

Run `/code-review` with the feature branch against `base` as its target
(`<base>..HEAD` or the branch name — with no target it reviews only
uncommitted changes, of which there are none), and `/codex:review` the
same way if it is available. If the survey found a review guideline or
checklist in the repository, check the diff against it too. Finally, go
through the acceptance criteria one by one and confirm each is met by the
diff, not only by the verification record — for a diff too large to read
here, hand each criterion to the explorer in research mode instead.

Write every finding to `WORK/review.md`. Fix what should be fixed by
relaunching the implementer for the affected unit, then re-verify. For
findings you leave alone, write the reason next to them. Show the user the
list only if a finding changes the requirements or design; otherwise
proceed.

Set `phase` to `pr`.

## Step 5: PR and CI

Before pushing, look at the commit history on the feature branch. Each
commit must be a unit someone could revert alone with verification still
passing; reshape the history if it is not.

Push and create the PR the way the git workflow skill says (template,
issue references, attribution). Whatever the shape, the body must carry:
the requirements in summary with a link to `where` if it is an issue, the
design decisions, how it was verified, and any review findings left alone
with their reasons.

Run the CI loop as the git workflow skill defines it, including its limit
on fix attempts. Fallback without one: `gh pr checks --watch`; on failure
find the cause, fix on the feature branch, push, watch again; after three
failed attempts stop and ask the user.

When CI is green, report and set `phase` to `done`. Merging is the user's
decision: never merge unasked.

If `gh` is unavailable, push and tell the user to open the PR by hand.

## Rules

- No design before requirements are approved; no implementation before the
  design is approved. There is no small-change exception.
- Requirements and design always exist as documents in `where`. The
  conversation is not the record.
- Verification comes before implementation: every unit starts red and ends
  green against the same check. A check only a human can run is performed
  by the user before review, never assumed.
- Follow the repository's conventions, hooks, linters, and templates. Never
  bypass a failing check.
- Nothing of the harness is written outside WORK.
