---
name: authoring-skills
description: Review, create, and improve Agent Skills against Anthropic's official best practices and shared house rules. Use whenever asked to write a new skill, review or evaluate an existing skill, check a skill against best practices, validate skill format with gh skill, or when editing any SKILL.md in a skills repository.
license: MIT
---

# Authoring Skills

Portable conventions for authoring Agent Skills in any skills repository.
Claude already reviews general code quality well; this skill adds only what
it cannot know: the live official checklist and the house rules below.

## Check against the live best-practices doc

Do not review or author from memorized guidance alone — the doc evolves.
Fetch it with WebFetch and use its checklist as the baseline:

https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices

Points memorized snapshots most often miss: gerund-form names
(`managing-databases`), "pushy" descriptions with explicit trigger phrases,
matching freedom level to task fragility.

## House rules

- **`gh skill` is the baseline**: skills live in one of `gh skill`'s
  discovery layouts (`skills/<name>/SKILL.md` or
  `skills/<scope>/<name>/SKILL.md`) and the frontmatter `name` matches the
  skill directory name. Which layout and scope taxonomy a repository uses
  is repository-specific — check its CLAUDE.md or README, and decide the
  placement of a new skill at intake, as part of the scope gate. After creating or editing a skill,
  validate the format by running `gh skill publish --dry-run` at the
  repository root and resolve every error and warning it reports. The
  command is in preview; if its behavior looks off, recheck
  `gh skill publish --help`.
- **Portability**: a skill is distributed as its directory alone and must
  work standalone in any host environment. Never bake in facts about the
  source repository — its structure, files outside the skill directory, or
  its policies. Repository-specific guidance belongs in the host
  repository's CLAUDE.md or README.
- **Language**: write SKILL.md and bundled docs in English unless the user
  says otherwise.
- **Scripts**: default to bash while the script stays thin (one file, simple
  control flow, no real data structures). A task bash covers in a few lines
  (e.g. fetching JSON = `curl`) does not justify Python. When bash gets
  unwieldy, switch to a language with minimal dependencies — standard
  library first; justify every external package.
- **Versioning**: versions are repository-level tags created by
  `gh skill publish`. Never add a `version` frontmatter field, never create
  per-skill tags (`skill-name/v1.2.0`), and scope Conventional Commits by
  skill name (`feat(managing-external-skills): ...`) so release notes read
  per skill. The release and bump policy lives in the repository README.
- **Scope gate — apply at intake, before writing or testing anything**:
  when asked to add or change skill content, first decide where the
  content belongs and tell the user, before drafting text or spending a
  red test on it. Skill content must be what the agent needs at the moment
  that skill triggers; knowledge for a different moment (e.g. release
  policy in an authoring-time skill) belongs in the README or another
  skill. Rejecting a misplaced request at intake is cheaper than
  discovering the mismatch in testing.
- **TDD (red → green)**: verify skill behavior with subagents.
  1. Red: give a subagent 1–3 representative task prompts and record the
     failure. For a brand-new skill, the baseline is no skill at all. For
     an improvement to an existing skill, the baseline is a pre-edit
     snapshot of that skill (e.g. `cp -r` the skill directory aside before
     editing) — comparing against "no skill" would also credit content
     the skill already had, not the change under test. The red must be
     observed, never assumed. There is no "too small to test" exemption —
     if you cannot construct a prompt that fails against the baseline,
     that is the signal to cut the content, not to skip the test.
  2. Write the minimal skill body that closes only the observed gaps.
  3. Green: rerun the same task prompts with the subagent instructed to
     read the skill file first. The prompts must exercise the task itself;
     asking the agent to recite or explain the skill's content always
     passes and proves nothing. Score every green against the rubric
     below and report the numbers alongside the verdict — "green" on its
     own doesn't say whether it was clean or merely passable, and a
     prompt that completes but only partly (some called-for steps
     skipped, or padded with unrequested extra work) is not a clean
     green even though it "passed".
  4. Iterate. Content that does not flip a red to green is unnecessary —
     cut it.
  5. Expand to N prompts (5–10) and report a pass rate (e.g. "6/10
     passed") instead of a single pass/fail when either: the prompts are
     a trigger eval (a single query is too noisy a sample for trigger
     precision — see below), or a 1–3 prompt round comes back split
     (some pass, some fail) rather than cleanly red or green. A 1–3
     prompt round that is cleanly red or green does not need expanding.
- **Rubric for green quality**: judge every completed prompt — not just
  ones that look sloppy — on two dimensions that a separate subagent can
  measure objectively, without relying on its own judgment call of "is
  this correct":
  - **Coverage**: list the steps the content calls for and check off
    which ones the transcript actually performed — report as a
    fraction (e.g. "4/5 steps covered"), not a felt impression.
  - **Concision**: compare length and tool-call count against the
    baseline run (no skill, or pre-edit snapshot — see step 1) for the
    same prompt; flag a green that is a fixed multiple longer (e.g.
    >1.5x) or that adds tool calls the task didn't require.
  Correctness (are the claims actually true) is deliberately left out
  of this rubric — verifying it needs a domain-specific check (running
  the code, diffing against a spec) that this skill cannot supply in
  general, and a judge asked to score it without one is just relabeling
  a subjective guess as a number.
- **Trigger evals**: verify a description's trigger precision the same
  way — with observed red/green, not judgment calls. Build two query
  sets: should-trigger (realistic prompts this skill must catch) and
  should-not-trigger (realistic prompts it must not catch). Spend the
  should-not-trigger budget on near misses — prompts that share keywords
  or domain with this skill but where a different skill or tool is
  actually the right fit — since an unrelated negative can't fail and
  proves nothing. Phrase every query the way a real user would type it:
  concrete file paths, casual tone, typos, surrounding context — not a
  clean restatement of the skill's own description. Use the pass-rate
  expansion above: trigger precision on 1–3 queries is too noisy to
  trust either way.
- **Persist TDD prompts as a regression suite**: once a red/green round
  closes, save the task prompts and their pass/fail assertions — or pass
  rate and rubric scores, when the round used those — as JSON outside
  the skill directory — a skill is distributed as its directory
  alone, so it must not carry its own eval fixtures (see Portability).
  Where exactly they live in the host repository is that repository's
  call; point to its README or CLAUDE.md for the path convention instead
  of assuming one. Persisting turns a one-off red/green check into a
  reusable suite for two purposes: (a) rerun it after a model update to
  catch regressions in skills that used to pass; (b) rerun it with the
  skill removed — if the no-skill baseline now passes on its own, that is
  a signal the skill's content has been absorbed by the model and is a
  candidate for trimming or removal. This is the same principle as
  "content that does not flip a red to green is unnecessary — cut it,"
  applied after the fact instead of at authoring time.

## Review procedure

1. Read SKILL.md and every bundled file (scripts, templates, references).
2. Fetch the best-practices doc and check compliance.
3. Check the house rules above.
4. Run `gh skill publish --dry-run` at the repository root; treat its
   errors and warnings as findings.
5. For scripts: syntax-check them and run the happy path where practical;
   reproduce findings instead of assuming them.
6. Report findings ordered by severity: bugs first, then best-practice
   violations, then style.
