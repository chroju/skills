---
name: driving-dev-workflow
argument-hint: '[what to build | issue number | (empty to resume)]'
description: Drives a development task through requirements agreement, design, red/green implementation, review, and PR with CI — autonomously except where a human decision is needed, with codebase reading and implementation delegated to subagents. Invoke with /driving-dev-workflow <what to build>, /driving-dev-workflow <issue number>, or /driving-dev-workflow with no arguments to resume an in-progress task.
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
| Verifier — checks the acceptance criteria against the running system, knowing nothing about how it was built | `agents/verifier.md` | `subagent_type: general-purpose`, `model: opus` |

The verifier is given the acceptance criteria and **not** the diff, the
design, or the implementer's tests. That is the whole point of it: whoever
wrote the code checks the path they meant to build, and so does anyone who
has read their diff. Do not economise by folding this into the implementer
or doing it yourself right after reviewing the change.

Add `isolation: worktree` to an implementer launch only when running units
in parallel (Step 3).

## Scripts

Two checks ship in `scripts/`. Both hand the document to jev — TypeSafe's
System One model (https://docs.typesafe.ai), which answers typed yes/no
questions with a probability and generates no text — as a reader that has
seen nothing of this conversation, and print a markdown table. They need
`TYPESAFE_API_KEY` in the environment, `curl` and `jq`.

| Script | Asks | Used in |
| --- | --- | --- |
| `scripts/check-criteria.sh <requirements.md>` | Per acceptance criterion: can a stranger check it with a command, test or procedure; does it describe how the change is built; does vague wording carry it | Step 1 |
| `scripts/check-verification.sh <design.md> [requirements.md]` | Per verification-plan row: is the check aimed at its criterion, and could it fail on a system without the change; with the requirements, which criteria have no row | Step 2 |

Exit 0 means nothing flagged, 1 that the table has flagged rows, 3 that jev
could not be used — no key, network, rate limit — which the script says on
stderr. On 3, apply the same questions yourself, as these steps did before
the scripts existed; the check is not skipped because the tool is down.

A flag is a probability from a reader without context, not a verdict.
Rewrite what it catches; where you keep a line as written, say why when you
present the document. Documents are written in the language of the
conversation and the reader is strongest in English, so treat a flag on a
Japanese line as a prompt to re-read it, and a clean table as no more than
the absence of obvious problems.

## Where things live

`WORK` = `$(git rev-parse --git-common-dir)/dev-workflow/<slug>/`. It is
inside `.git`, so it is never committed, is shared by every worktree of the
repository, and survives deleting a worktree.

| File | Content |
| --- | --- |
| `state.json` | Progress, see below |
| `context.md` | What the explorer reported about the codebase |
| `requirements.md`, `design.md` | The agreed documents — unless `where` is an issue |
| `verify.md` | Red/green records from every implementation unit, then the verifier's report on the criteria |
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

**Argument.** If it is an issue number, read it with whatever GitHub access
this session has — `gh`, a GitHub MCP tool, the API — and `where` is
`issue#<n>`. Otherwise the argument is the request.
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

Before presenting, run `scripts/check-criteria.sh` on the document
(Scripts, above; when `where` is an issue, save the text you are about to
post to `WORK/requirements.md` and run it on that). Rewrite each flagged
criterion, or turn it into an `[OPEN:]` when the fix needs the user, and
run it again until nothing is flagged or every remaining flag has a reason
you will state.

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
a mock before anything else: ASCII for terminal output, a rendered page or
sketch for GUI. Draw it from the real design tokens the survey found —
the actual colours, spacing and type of the thing being changed — so that
agreeing on the mock agrees on something true.

**If the repository already keeps drawings of its screens** — a wireframe
folder, a design directory, a storybook — make the mock *in that format, in
that place*, and let it be committed with the change. It is then one drawing
that gets agreed, built against, and left behind as the record. Producing a
throwaway mock now and redrawing the same screen in the repository's format
at the end means drawing it twice, and the second drawing has to be told to
follow the implementation rather than the mock, because by then they differ.
Only when the repository keeps no such drawings does the mock live in
`WORK/` next to `design.md`, or in the design comment when `where` is an
issue.

Whatever its home, show the user a rendering they can actually look at, and
agree on it; it becomes part of the design.

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

Run `scripts/check-verification.sh` with the design and the requirements
(Scripts, above; same file rule as Step 1 when `where` is an issue). A row
whose check is not aimed at its criterion, or would pass on the unchanged
system too, is rewritten — usually by naming what it observes and the state
it runs in. A criterion without a row gets one.

The design also decides **how the work lands**: one pull request or several,
and which criteria go in each. Ask it explicitly, because the answer is
usually a design choice rather than a fact — a change is splittable when the
first part can ship without the second, and that is something an interface
can be designed for or against. Adding a field beside an existing one splits;
replacing the existing one does not. Where a split is cheap to enable, enable
it.

Size is a prompt to ask the question, not a rule: past roughly 500 lines of
production code in one pull request — tests, specs and fixtures do not count,
or you have built a reason to write fewer tests — stop and decide whether it
splits. Record the answer in the design, including "it does not split, and
here is why".

Present the design together with a proposed branch name and wait for
explicit approval, by the same rule as Step 1. On approval, create the
feature branch from `base` in a worktree and move into it (EnterWorktree
if available, otherwise `git worktree add .local/worktrees/<branch> -b
<branch>` with `.local/` excluded via `.git/info/exclude`); record the
branch in `state.json` and set `phase` to `implement`. EnterWorktree moves
the whole session, subagents included. The manual fallback does not: then
give every subagent the worktree path and tell it to work there.

## Step 3: Implement

Before the first implementer, run the repository's own checks yourself and
watch them execute — the full test command, the linter, the type checker. An
implementer that cannot observe a red cannot work, and discovering that
inside a subagent wastes the launch. If they do not run, make them run first:
missing dependencies, an absent env file, an unbuilt fixture. *How* is the
repository's business — a setup script, a hook, a line in its own docs — not
this skill's; but confirming it is yours.

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
branch of its own. A fresh worktree carries none of the repository's
installed dependencies, so the checks will not run there until they are
installed again — in an ecosystem where that is slow or large, this alone
can cost more than the parallelism saves. Integrate each returned branch from the feature
worktree by rebasing it onto the feature branch and fast-forwarding —
resolve rebase conflicts yourself — so the history stays linear, then
remove the worktree and branch. Never leave merge commits.

After each unit lands, run the full verification plan on the feature
branch; a green that held for one unit must still hold with the others.
Append each red/green record to `WORK/verify.md`. If an implementer
reports a problem it could not solve inside its scope, decide: widen the
scope and relaunch, split the unit, or bring it to the user if it changes
the design.

An implementer verifies its own unit only in the narrow sense that matters
to it: the check it was given went red, then green. That is not the same as
the acceptance criteria holding, and it cannot be — it is checking the path
it just built.

So when the units are in, launch the **verifier** against the running system
with the acceptance criteria and nothing else. Give it how to start and
reach the app, and the environment it needs — the port, a browser's location,
credentials. Do not give it the diff, the design, or the tests. File its
report in `verify.md` alongside the implementers' red/green records.

A criterion it returns **not met** goes back to the implementer for that
unit, then to the verifier again — not to you to reason about. A criterion
it can only mark **cannot check here** (a real device, production data, a
human judging an aesthetic) is the one thing to hand to the user, with the
verifier's own description of what they would have to do.

When every criterion is met on the feature branch, set `phase` to `review`.

## Step 4: Review

First bring the base branch in. Fetch it and merge it into the feature
branch, resolve whatever conflicts appear, and re-run the checks. A branch
that has drifted from its base gets reviewed against a repository that no
longer exists, and the conflict you would rather find now is the one nobody
sees in a diff: two branches that both edited nothing in common but both
claimed the same decision number, migration index, or reserved name. Look
for that deliberately in anything the repository numbers by hand. If
resolving a conflict touched code the verifier already passed, rerun the
verifier on the merged branch before moving on — a manual conflict
resolution is a code change like any other, and nothing so far has checked
it against the acceptance criteria.

Then run `/code-review` with the feature branch against `base` as its target
(`<base>..HEAD` or the branch name — with no target it reviews only
uncommitted changes, of which there are none), and `/codex:review` the
same way if it is available. If the survey found a review guideline or
checklist in the repository, check the diff against it too. Finally, go
through the acceptance criteria one by one and confirm each is met by the
diff, not only by the verification record — for a diff too large to read
here, hand each criterion to the explorer in research mode instead.

Write every finding to `WORK/review.md` and sort each into one of three
classes, with the evidence for the class next to it:

- **A — the approved work is not done.** An acceptance criterion, a
  requirement, or a decision in the design does not hold in the diff.
- **B — this change broke something.** Behaviour that worked on `base` no
  longer works on the feature branch. Show it: the same input, the output
  on `base`, the output now.
- **C — everything else.** Problems that exist on `base` too, edge cases no
  requirement names, hardening, style, simplification, "a better design
  would be". A reviewer's severity label does not move a finding out of C;
  only evidence that it is A or B does.

This pull request fixes A and B, and nothing else. Relaunch the implementer
for the affected unit with the A and B findings only. C stays in
`review.md` with one line on why it waits, and goes into the PR body; if it
is worth doing, raise it as a separate task or issue. Fixing C here is how a
review turns into rounds: every fix is new code, new code draws new
findings, and most of them are C again.

After the fixes, review **only the diff of the fixes**, and only for A and
B — above all B, since a fix that reorders or rewrites logic is where new
regressions come from. Do not rerun a full review of the branch. Then rerun
the verifier once, on the final head, rather than after each fix.

When the root cause of an A or B finding lies outside the approved scope —
the fix belongs in a module the requirements left out, or the only way to
fix it inside the scope is to guess — stop and bring it to the user with
the options (widen the scope, accept the limitation, or split it off). Do
not paper over it with heuristics inside the scope: each heuristic breaks a
different set of inputs, and every one of those is a new B.

Show the user the list only if a finding changes the requirements or
design, or needs the decision above; otherwise proceed.

Set `phase` to `pr`.

## Step 5: PR and CI

Before pushing, look at the commit history on the feature branch. Each
commit must be a unit someone could revert alone with verification still
passing; reshape the history if it is not.

Check the change against the landing plan the design settled. If it grew
past what that plan assumed, split it now rather than explaining the size in
the PR body; if it genuinely cannot be split, say so in the body in one line
so the reviewer knows it was considered. Anything you added along the way
that the criteria never asked for — a fix you noticed in passing, a tidy-up
in a file you happened to open — comes out and goes somewhere of its own.

Push and create the PR the way the git workflow skill says (template,
issue references, attribution). Whatever the shape, the body must carry:
the requirements in summary with a link to `where` if it is an issue, the
design decisions, how it was verified, and any review findings left alone
with their reasons.

Run the CI loop as the git workflow skill defines it, including its limit
on fix attempts. Fallback without one: watch the checks with whatever GitHub
access this session has (`gh`, a GitHub MCP tool, the API); on failure find
the cause, fix on the feature branch, push, watch again; after three failed
attempts stop and ask the user.

When CI is green, report and set `phase` to `done`. Merging is the user's
decision: never merge unasked.

If this session has no GitHub access at all, push and tell the user to open
the PR by hand.

## Rules

- No design before requirements are approved; no implementation before the
  design is approved. There is no small-change exception.
- Requirements and design always exist as documents in `where`. The
  conversation is not the record.
- Verification comes before implementation: every unit starts red and ends
  green against the same check.
- Whoever built a thing does not get to be the one who says it works. The
  implementer's red/green covers its own unit; the acceptance criteria are
  checked by the verifier, which is not shown the diff. A check only a
  person can run is performed by the user before review, never assumed.
- Before review, the feature branch is brought up to date with its base.
- Review fixes only what the approved work requires: unmet requirements and
  design (A) and regressions against base (B). Everything else is recorded
  and left for separate work.
- Follow the repository's conventions, hooks, linters, and templates. Never
  bypass a failing check.
- Nothing of the harness is written outside WORK.
