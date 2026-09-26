# CLAUDE.md

This is a distribution repository: Agent Skills under
`skills/<scope>/<name>/` are the products, installed standalone into other
environments via `gh skill install chroju/skills <name>`. Consumers receive
only the skill directory — never this repository's README, CLAUDE.md, CI,
or LICENSE file. Everything under `skills/` must therefore be portable and
self-contained; repository-specific facts (scope taxonomy, CI, release
policy) live outside `skills/`, here or in the README. Versioning and
release policy: [README.md](README.md).

## Development policy

- Before creating, reviewing, or editing any skill, read
  [skills/meta/authoring-skills/SKILL.md](skills/meta/authoring-skills/SKILL.md) and
  follow it. It defines the scope gate (apply at intake), house rules
  (English, bash-first scripts, `gh skill` as the baseline), and the TDD
  red → green workflow with subagents.
- This repository does not persist TDD prompts or results as a regression
  suite. Run the red → green checks properly each time and report the
  numbers in the PR; keep prompts and grades in scratch space only.
- Run `gh skill publish --dry-run` at the repository root before
  committing skill changes. CI (`lint.yaml`) runs the same check plus
  `shellcheck -S warning` on all shell scripts.
- Use Conventional Commits with the skill name as scope
  (`feat(managing-external-skills): ...`) so release notes group per skill.
- Directory scopes categorize skills. Apply these rules in order and use
  the first that fits:
  1. `meta/` — how skills or agents themselves are handled: authoring or
     managing skills, orchestrating subagents.
  2. `setup/` — used once when preparing a project or its development
     environment (repository baseline, devcontainer).
  3. `engineering/` — everything else used repeatedly in day-to-day
     development.
  Decide the scope at intake. If none fits, propose a new one to the user.
  Moving an existing skill between scopes is a MAJOR change (see README).

## Releases

- Releases are manual and human-decided: the `release` workflow
  (workflow_dispatch) validates and publishes via
  `gh skill publish --tag vX.Y.Z`. The MAJOR/MINOR/PATCH decision follows
  the README policy.
- After user-visible skill changes land on main (skill added, behavior
  changed, bug fixed), proactively remind the user to cut a release:
  state which skills changed and recommend a bump level with a one-line
  rationale. Do not trigger the release workflow yourself unless asked.
- Doc-only or CI-only changes do not warrant a release reminder.
