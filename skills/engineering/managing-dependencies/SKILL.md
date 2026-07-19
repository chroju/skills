---
name: managing-dependencies
description: Selects versions, evaluates packages, and configures automated updates when working with third-party dependencies. Use when adding, upgrading, or choosing a dependency in any package manifest (package.json, pyproject.toml, go.mod, Cargo.toml, Gemfile) or when setting up Renovate or Dependabot.
license: MIT
---

# Managing Dependencies

Ecosystem-neutral rules for third-party dependencies. The ecosystem
changes the commands (npm, pip/uv, Go modules, Cargo, Bundler, ...),
not the rules.

## Selecting a version

Never write a version number from memory — trained knowledge is stale.
Query the registry for the available versions **and their publish
dates** (e.g. `npm view <pkg> time`, the registry's JSON API, ...).

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

In both cases commit the lockfile, and make CI install from it in
frozen mode (`npm ci`, `--frozen-lockfile`, `--locked`, ...).

## Choosing a package

First ask whether a dependency is warranted at all: if the need is a
few dozen lines of stable code, write it in the project instead.

When adopting one, prefer official SDKs and packages backed by a
company, foundation, or established maintainer group. Before
installing, check:

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
