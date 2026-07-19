# skills

Claude Code agent skills.

## Install

```bash
gh skill install chroju/skills <skill-name>
```

## Skills

| Skill | Description |
|-------|-------------|
| [engineering/driving-git-workflow](./skills/engineering/driving-git-workflow/) | Git workflow from worktree-based branching through commits, PRs, CI fix loops, and merge with cleanup |
| [engineering/managing-dependencies](./skills/engineering/managing-dependencies/) | Version selection, package vetting, and update-bot policy for third-party dependencies |
| [meta/authoring-skills](./skills/meta/authoring-skills/) | Review and author skills against Anthropic's best practices and this repository's house rules |
| [meta/claude-devcontainer](./skills/meta/claude-devcontainer/) | Generate a devcontainer.json optimized for Claude Code development |
| [meta/managing-external-skills](./skills/meta/managing-external-skills/) | Declarative vendoring of external skills via a SHA-pinned skills.txt |

## Versioning and releases

Versions are collection-level, not per-skill. `gh skill publish` tags the
whole repository (semver), and `skill@vX.Y.Z` / `--pin` resolve as git refs
on the repository.

- **MAJOR**: any skill is removed, renamed, or breaks its documented behavior
- **MINOR**: a skill is added or gains a capability
- **PATCH**: fixes and documentation changes

"Which skill changed" is expressed in release notes, not in the version
number: commits use Conventional Commits with the skill name as scope
(`feat(claude-devcontainer): ...`), so auto-generated release notes read
per skill.

Coarse repository-level versioning is harmless here because `gh skill
update` detects changes by comparing each skill directory's tree SHA —
tagging a release never churns skills that did not change. Per-skill tags
(`skill-name/v1.2.0`) are not used: `gh skill publish` does not produce
them and the ecosystem does not consume them. The Agent Skills spec has no
first-class `version` frontmatter field, so skills do not carry one.

## License

[MIT](LICENSE)
