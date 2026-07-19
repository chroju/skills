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
  1. Red: give a subagent 1–3 representative task prompts WITHOUT the
     proposed content and record the failure. The red must be observed,
     never assumed. There is no "too small to test" exemption — if you
     cannot construct a prompt that fails without the content, that is
     the signal to cut the content, not to skip the test.
  2. Write the minimal skill body that closes only the observed gaps.
  3. Green: rerun the same task prompts with the subagent instructed to
     read the skill file first. The prompts must exercise the task itself;
     asking the agent to recite or explain the skill's content always
     passes and proves nothing.
  4. Iterate. Content that does not flip a red to green is unnecessary —
     cut it.

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
