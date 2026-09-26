# Design: <slug>

## Summary

<!-- The approach in a few sentences. Enough to predict the diff. -->

## Mock

<!-- Only when the change has a visual component. ASCII for terminal
     output, a static HTML file or sketch for GUI. Agreed with the user
     before the rest of the design. Delete the section otherwise. -->

## Changes

<!-- Per file or module: what changes and why. Real paths. -->

### `<path>`

## Data and interfaces

<!-- New or changed data shapes, signatures, config keys, CLI flags.
     Delete the section if nothing changes. -->

## Verification plan

<!-- One row per acceptance criterion. Tests in the repository's own style
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

<!-- Rejected approaches and what ruled them out. -->

- **<alternative>** — rejected because <reason>.
