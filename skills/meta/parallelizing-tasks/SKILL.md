---
name: parallelizing-tasks
description: Plans, decomposes, and executes large tasks with parallel subagents routed to cheaper models — read-only investigation on the cheapest tier, code edits on a mid tier in isolated git worktrees, with a parent-run verification gate and one-tier model escalation on failure. Use when a task splits into independent subtasks (multi-area codebase investigation, bulk edits or migrations across many files, repeating one procedure over many targets) or when the user asks to parallelize work, fan out subagents, or delegate to cheaper models.
license: MIT
---

# Parallelizing Tasks

Workflow: decompose → route models → approval gate (code changes) →
parallel dispatch → integrate → verify → escalate failures.

## 1. Decide whether to parallelize

Parallelize only subtasks that are independent — no subtask may need
another's output or touch another's files. Do the task yourself, without
subagents, when there are fewer than ~3 independent subtasks or the whole
task fits in a handful of tool calls: dispatch overhead would exceed the
gain.

## 2. Decompose and route models

One subagent per subtask. Set each subagent's `model` parameter by
subtask type — never leave every subagent on the default model:

| Subtask type | `model` |
|---|---|
| Read-only: investigate, search, summarize, analyze | `haiku` (cheapest tier) |
| Code-editing, even mechanical edits | `sonnet` (mid tier) |
| Design decisions or cross-cutting judgment | omit — inherit your own model |

## 3. Approval gate — mandatory when code changes

If any subtask edits files, present the decomposition to the user and
wait for approval before dispatching anything:

| # | Subtask | Files touched | Model |

Adjust the plan to their feedback. A decomposition that is entirely
read-only skips this gate and proceeds autonomously.

## 4. Dispatch

- Launch all subagents in a single message so they run concurrently.
- Write self-contained prompts: absolute paths, goal, constraints, and
  the exact shape of the expected result. Subagents share no context
  with you or with each other.
- Read-only subagents work in place and return findings as text.
- Code-editing subagents must not share a working tree. Create one git
  worktree per subtask before dispatch:

  ```bash
  git worktree add <tmpdir>/<subtask> -b para/<subtask>
  ```

  Instruct each subagent to work only inside its worktree and commit its
  changes on its branch (never push).

## 5. Integrate

Merge each branch back sequentially, resolving conflicts yourself, then
clean up:

```bash
git merge para/<subtask>
git worktree remove <tmpdir>/<subtask> && git branch -d para/<subtask>
```

## 6. Verification gate — run it yourself

After integrating, run the project's real verification commands: the
test suite, build, lint — whatever CI would run. Static inspection
(grep, syntax checks) and subagent self-reports are not sufficient.
Attribute each failure to its subtask and fix it before reporting done.

## 7. On subagent failure

Retry the failed subtask once, one model tier up: `haiku` → `sonnet` →
do it yourself on your own model. Never retry at the same tier — a model
that failed a task usually fails it the same way again.
