# CLAUDE.md

Agent Skills collection following `gh skill` conventions
(`skills/<name>/SKILL.md`). Versioning and release policy: [README.md](README.md).

## Development policy

- Before creating, reviewing, or editing any skill, read
  [skills/authoring-skills/SKILL.md](skills/authoring-skills/SKILL.md) and
  follow it. It defines the scope gate (apply at intake), house rules
  (English, bash-first scripts, `gh skill` as the baseline), and the TDD
  red → green workflow with subagents.
- Run `gh skill publish --dry-run` at the repository root before
  committing skill changes. CI (`lint.yaml`) runs the same check plus
  `shellcheck -S warning` on all shell scripts.
- Use Conventional Commits with the skill name as scope
  (`feat(managing-external-skills): ...`) so release notes group per skill.

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
