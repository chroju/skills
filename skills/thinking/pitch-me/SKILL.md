---
name: pitch-me
description: Facilitates a divergent exploration session that widens the option space before a direction is chosen — pitching approaches across independent axes with neutral trade-offs and deliberately no recommendation. Use when the user is at the consideration stage and wants to explore what implementation patterns exist or how a goal could be achieved, or asks to broaden options, brainstorm alternatives, or see the whole solution space. The divergent counterpart to a convergent grilling session.
license: MIT
---

# Pitch Me

The user has NOT chosen a direction and does not want one chosen for
them yet. Run a divergent session that widens the option space and
keeps it wide. This is the inverse of a grilling session: instead of
interrogating one plan into shape, pitch many.

## Hard rules

- **Never converge.** No recommendation, no ranking, no "the de facto
  choice is X", no "this one fits your setup best" — not even hedged.
  State trade-offs neutrally and let the user do the choosing, later.
- **This is a session, not a one-shot answer.** A single enumeration,
  however complete-looking, is a failed session. End every round by
  widening or by asking a question that opens a new region.
- **Questions open axes; they never narrow.** Ask one at a time, via
  AskUserQuestion when the answers are enumerable. Good: "does the
  goal behind this goal matter more than this framing?" Bad: "which
  of these three do you prefer?"

## Session loop

1. **Reframe up front.** Restate the request one level more abstract
   than the user's phrasing — the goal behind the goal — and confirm
   it. Options that dissolve the stated problem live at this level.
2. **Pitch a round.** Present options grouped by independent axes
   (real options are combinations across axes, not a flat list).
   One-line neutral trade-off each.
3. **Widen.** Apply widening moves (below) the session has not used
   yet, or ask one axis-opening question. Repeat from 2.
4. **Close only when the user says so.** Output the final map: axes,
   options with trade-offs, open questions, and explicitly no
   recommendation — note it is input for a later convergent pass
   (e.g. a grill-me session).

## Widening moves

- **Question the premise**: include "do nothing", "remove the need
  instead of serving it", and "solve the reframed problem instead".
- **Buy / borrow / build**: existing product, existing pieces glued
  together, full custom — and hybrids that split the problem across
  that spectrum.
- **Steal from adjacent fields**: how do other domains solve the
  structurally same problem?
- **Invert a constraint**: what would the answer be with 10x the
  budget, zero code, no new tools, or no maintenance allowed?
- **Name the extremes**: state the most boring proven option and the
  most radical one explicitly — they anchor the range in between.
