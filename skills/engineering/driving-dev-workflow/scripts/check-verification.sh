#!/bin/bash
# check-verification.sh <design.md> [requirements.md]
#
# Reads the Verification plan table with jev, an outside reader, and asks per
# row:
#   checks    — is the check aimed at the criterion: does it observe the
#               behaviour the criterion describes? (asked this way on purpose;
#               "would a pass prove the whole criterion" rates every terse but
#               sound row low)
#   can fail  — would the check fail on a system where the criterion does not
#               hold? (a check that passes on the unchanged system proves nothing)
#   state     — is the state something that has already happened, not "at rest"?
#               (informational; printed, never flagged; "—" when the row has none)
# With the requirements given, it also asks, per acceptance criterion, whether
# any row checks it, and lists the criteria that have no row.
#
# Exit codes: 0 nothing flagged · 1 some rows or criteria flagged · 2 usage
#             error · 3 jev unavailable (reason on stderr; judge by hand).
# CHECK_THRESHOLD (default 0.5) is the probability at which a question flags.
set -u

HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=jev.sh
. "$HERE/jev.sh"

T="${CHECK_THRESHOLD:-0.5}"
ME=$(basename "$0")

if [ $# -lt 1 ] || [ $# -gt 2 ] || [ ! -f "$1" ] || { [ $# -eq 2 ] && [ ! -f "$2" ]; }; then
  echo "usage: $ME <design.md> [requirements.md]" >&2
  exit 2
fi

ROWS=$(extract_verification_rows "$1")
if [ -z "$ROWS" ]; then
  echo "$ME: no verification plan table found in $1" >&2
  exit 2
fi

CRITERIA=""
if [ $# -eq 2 ]; then
  CRITERIA=$(extract_criteria "$2")
  if [ -z "$CRITERIA" ]; then
    echo "$ME: no acceptance criteria found in $2" >&2
    exit 2
  fi
fi

flagged=0

# ---- 1. Each row on its own -------------------------------------------------

# Tables are printed at the end, so an exit 3 midway leaves stdout empty.
rows_table=""
i=0
while IFS=$'\037' read -r criterion state check; do
  [ -n "$criterion$state$check" ] || continue
  i=$((i + 1))

  # A row often names its criterion tersely ("AC3 …"). When the requirements
  # were given, hand jev the full criterion text as well.
  full=$criterion
  if [ -n "$CRITERIA" ]; then
    id=$(printf '%s' "$criterion" | sed -nE 's/^\**(AC[0-9]+)\**.*/\1/p')
    if [ -n "$id" ]; then
      match=$(printf '%s\n' "$CRITERIA" | grep -m1 -E "^(\*\*)?$id(\*\*)?([^0-9]|$)")
      [ -n "$match" ] && full="$criterion — $match"
    fi
  fi

  request=$(jq -cn --arg c "$full" --arg s "$state" --arg k "$check" '{
    model: "jev-latest",
    state: { criterion: $c, state: $s, check: $k },
    questions: {
      checks: {
        type: "noul",
        instructions: "Is `check` aimed at `criterion`: does it observe the behaviour the criterion describes?",
        criteria: {
          true: "The check exercises and observes what the criterion is about; a terse description of a test file and its assertions counts",
          false: "The check observes something unrelated, or only looks without observing a specific result"
        }
      },
      can_fail: {
        type: "noul",
        instructions: "Would `check` fail on a system where `criterion` does not hold?",
        criteria: {
          true: "Without the change the check would produce a different, failing observation",
          false: "The check would pass on the unchanged system too, so passing tells nothing"
        }
      },
      state_concrete: {
        type: "noul",
        instructions: "Does `state` describe something that has already happened when the check runs — an action taken, data present, a prior step — rather than a fresh start, nothing, or a placeholder?"
      }
    }
  }')

  body=$(jev_call "$request") || jev_unavailable "$ME"

  probs=$(printf '%s' "$body" | jq -r '
    "\(.answers.checks.noul) \(.answers.can_fail.noul) \(.answers.state_concrete.noul)"')
  read -r p_checks p_fail p_state <<EOF
$probs
EOF

  verdict=$(awk -v a="$p_checks" -v b="$p_fail" -v t="$T" 'BEGIN {
    r = ""
    if (a + 0 < t + 0) r = r "does not check it; "
    if (b + 0 < t + 0) r = r "cannot fail; "
    if (r == "") print "ok"; else { sub(/; $/, "", r); print r }
  }')
  [ "$verdict" != ok ] && flagged=$((flagged + 1))

  if [ -n "$state" ]; then
    state_cell=$(printf '%.2f' "$p_state")
  else
    state_cell="—"
  fi

  rows_table+=$(printf '| %d | %.2f | %.2f | %s | %s | %s | %s |' \
    "$i" "$p_checks" "$p_fail" "$state_cell" "$verdict" "$(md_cell "$criterion")" "$(md_cell "$check")")$'\n'
done <<EOF
$ROWS
EOF

rows_total=$i

# ---- 2. Coverage of the acceptance criteria ---------------------------------

if [ $# -eq 2 ]; then
  rows_json=$(printf '%s\n' "$ROWS" | jq -Rn '
    [inputs | select(length > 0) | split("\u001f") | { criterion: .[0], state: .[1], check: .[2] }]')

  coverage_table=""

  # One Choice per criterion over the rows plus "none". Asking a yes/no per
  # row with all rows in the state does not discriminate (every row scores
  # high); a single choice with an explicit "none" option does.
  j=0
  uncovered=0
  while IFS= read -r criterion; do
    [ -n "$criterion" ] || continue
    j=$((j + 1))

    request=$(jq -cn --arg c "$criterion" --argjson rows "$rows_json" '{
      model: "jev-latest",
      state: { criterion: $c, rows: $rows },
      questions: {
        which: {
          type: "choice",
          instructions: "Which verification row, if any, checks `criterion`? Passing that row in its state should show the criterion holds, wholly or in a clearly stated part.",
          criteria: (
            ($rows | to_entries | map({ ("row_\(.key + 1)"): "state: \(.value.state) / check: \(.value.check)" }) | add)
            + { none: "No row checks this criterion" }
          )
        }
      }
    }')

    body=$(jev_call "$request") || jev_unavailable "$ME"

    answer=$(printf '%s' "$body" | jq -r '
      .answers.which | "\(.choice) \(.confidence) \(.probabilities.none)"')
    read -r choice conf p_none <<EOF
$answer
EOF

    if [ "$choice" = none ]; then
      row="—"
      verdict="no row"
      uncovered=$((uncovered + 1))
      flagged=$((flagged + 1))
    else
      row=${choice#row_}
      verdict="ok"
    fi

    coverage_table+=$(printf '| %d | %s | %.2f | %.2f | %s | %s |' \
      "$j" "$row" "$conf" "$p_none" "$verdict" "$(md_cell "$criterion")")$'\n'
  done <<EOF
$CRITERIA
EOF
fi

# ---- 3. Output ----------------------------------------------------------------

echo "## Rows"
echo
echo "| # | checks | can fail | state | verdict | criterion | check |"
echo "| --- | --- | --- | --- | --- | --- | --- |"
printf '%s' "$rows_table"

if [ $# -eq 2 ]; then
  echo
  echo "## Coverage"
  echo
  echo "| # | row | confidence | p(no row) | verdict | acceptance criterion |"
  echo "| --- | --- | --- | --- | --- | --- |"
  printf '%s' "$coverage_table"
  echo
  echo "$rows_total rows, $j criteria, $uncovered without a row, $flagged flagged in total (threshold $T)"
else
  echo
  echo "$rows_total rows, $flagged flagged (threshold $T)"
fi

[ "$flagged" -eq 0 ]
