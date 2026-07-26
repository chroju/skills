---
name: managing-dependencies
description: Selects versions, evaluates packages, and configures automated updates for any third-party artifact a project pulls in by version — library packages, container base images, CI actions, and infrastructure providers and modules. Use when adding, upgrading, or choosing anything version-referenced in a package manifest (package.json, pyproject.toml, go.mod, Cargo.toml, Gemfile), a Dockerfile or compose file, a CI workflow, or Terraform configuration, and when setting up Renovate or Dependabot.
license: MIT
---

# Managing Dependencies

Ecosystem-neutral rules for third-party dependencies. The ecosystem
changes the commands (npm, pip/uv, Go modules, Cargo, Bundler, ...),
not the rules.

A dependency is anything the project pulls in by version and did not
write: library packages, but equally container base images, CI actions,
and infrastructure providers and modules. All of them execute
third-party code, so the rules below apply to all of them — a workflow
step, a `FROM` line, and a provider constraint are dependency
declarations, not configuration.

## Selecting a version

Never write a version number, image tag, or commit SHA from memory —
trained knowledge is stale, and a remembered digest is usually wrong
outright. Query the source for the available versions **and their
publish dates**: the package registry (`npm view <pkg> time`, its JSON
API, ...), the image registry, the action's repository releases, or the
provider/module registry.

Then apply a cooldown: **do not adopt a version published fewer than 7
days ago**; take the newest version older than that instead. Compromised
releases are usually detected and pulled within days of publication, and
7 days also clears npm's 72-hour unpublish window, so waiting converts
most supply-chain attacks into non-events. Exceptions:

- Adopt a younger version when it fixes a security vulnerability the
  project is exposed to, or when nothing older satisfies a hard
  requirement — state explicitly that you are overriding the cooldown.
- A project may set its own cooldown length; follow it.

## Range or exact pin

Decide by what the project is, not by the ecosystem's default:

- **Application or service** (not consumed as a package): pin the exact
  version in the manifest — `"4.4.3"`, not `"^4.4.3"` (`npm install
  --save-exact`; `==` for Python; `=` for Cargo). Reproducibility beats
  auto-drift; the update bot below handles freshness.
- **Published library**: use the ecosystem's conventional compatible
  range (`^`, `~=`, ...) so downstream consumers can deduplicate.

The range case exists only to let a downstream consumer resolve a
version, so it turns on what **this** project is, never on what the
dependency is. Where nothing downstream consumes this project — a
Dockerfile, a CI workflow, a root Terraform configuration — pin every
reference it makes, regardless of what the ecosystem's examples show.
That a dependency is itself a shared, reusable artifact does not make it
a range: a widely reused registry module gets pinned like anything else.
Only when the thing being authored is the published artifact does its
own declared constraints take a range.

In both cases commit the lockfile, and make CI install from it in
frozen mode (`npm ci`, `--frozen-lockfile`, `--locked`, ...).

### Pin to something immutable

A pin is only worth as much as the identifier's immutability. Where the
ecosystem's version reference is a mutable tag that the publisher can
repoint at different code, pin the immutable digest instead and keep the
human-readable version beside it in a comment:

- Container images: the registry digest (`@sha256:...`), not the tag
  alone — tags are reassigned on every rebuild
- CI actions referenced from a git repository: the full commit SHA, not
  a branch or version tag — tags can be moved

Registry-published artifacts whose versions are immutable once released
(most language packages, Terraform providers and registry modules) need
only the exact version. Where a lockfile exists, commit it: it records
the checksums the version string alone does not
(`.terraform.lock.hcl`, and note it must cover every platform CI and
developers run on).

## Choosing a dependency

First ask whether a dependency is warranted at all: if the need is a
few dozen lines of stable code, write it in the project instead. The
same question applies outside package managers — a CI action wrapping
one CLI invocation is usually better replaced by a `run:` step.

When adopting one, prefer official SDKs, images, and actions backed by a
company, foundation, or established maintainer group. Before adopting,
check:

- Maintenance: recent releases, responsive issue tracker, not deprecated
- Adoption: download counts / dependents relative to alternatives
- License compatible with the project
- Exact name, character by character, against the package's own
  repository or docs — typosquats live one edit away from popular names
- Known vulnerabilities (`npm audit`, `osv-scanner`, `pip-audit`, ...)
- Install-time scripts (npm `postinstall` and similar): a red flag that
  needs justification
- Transitive dependency count: fewer is better at equal fit

Report which of these you checked when proposing the package.

## Automated updates

A project with pinned dependencies needs an update bot; set one up when
it is missing. Choose Renovate when its app can be installed (richer
grouping and presets); choose Dependabot when a config file in the repo
must be sufficient. The configuration must express the same policy as
above:

- Cooldown on ordinary updates: Renovate `minimumReleaseAge: "7 days"`,
  Dependabot `cooldown: { default-days: 7 }`
- Security updates bypass the cooldown and arrive immediately
- Group minor + patch updates into one PR; keep majors as separate PRs
- Keep pins pinned: for applications, Dependabot
  `versioning-strategy: increase`, Renovate `rangeStrategy: pin`
- Enable lockfile maintenance where the bot supports it

Cover every ecosystem the repository actually contains, not just the
language manifest — both bots handle container images, CI actions, and
Terraform as first-class ecosystems, and both understand digest and SHA
pins well enough to bump the pin and rewrite the accompanying version
comment. Digest-pinned dependencies especially need the bot: nothing
about them changes on its own, so without it they never move.
