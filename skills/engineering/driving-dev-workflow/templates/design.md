# Design: <slug>

## Summary

<!-- How the approved solution is built, in a few sentences. Enough to
     predict the diff. What users see is fixed in the solution; do not
     restate or change it here. -->

## Changes

<!-- Per file or module: what changes and why. Real paths. -->

### `<path>`

## Internal data and interfaces

<!-- New or changed internal data shapes, function signatures, storage
     layout. External ones (flags, config keys, API shapes) are in the
     solution. Delete the section if nothing changes. -->

## Verification plan

<!-- One row per acceptance criterion, driven through the solution's
     external spec. Tests in the repository's own style
     if it has a framework; otherwise a reproducible command or procedure.
     Name the state the check runs in, not only the command: most missed
     bugs live in the gap between the feature at rest and the feature after
     the user has already done something. "Open the screen and read it" is
     rarely the check. -->

| Acceptance criterion | State it is checked in | Check |
| --- | --- | --- |
| <criterion> | <what has already happened when it matters> | <test file, command, or procedure> |

## Landing plan

<!-- One pull request or several, and which acceptance criteria go in each.
     Splittable means the first part can ship on its own — usually a design
     choice, not a fact: adding a field beside an existing one splits,
     replacing it does not. Past ~500 lines of production code (tests,
     specs and fixtures excluded) decide explicitly, and write "does not
     split, because …" if that is the answer. -->

| PR | Criteria | Ships on its own because |
| --- | --- | --- |
|  |  |  |

## Work breakdown

<!-- Units one implementer can do alone with no other context. File sets of
     units meant to run in parallel must not overlap. -->

### Unit 1: <name>

- **Depends on**: none
- **Files**: `<path>`, `<path>`
- **Does**: <what this unit implements>
- **Verified by**: <rows of the plan above>

## Alternatives considered

<!-- Rejected ways of building the chosen solution and what ruled them
     out. Rejected solutions are in the solution document. -->

- **<alternative>** — rejected because <reason>.
