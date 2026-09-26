#!/bin/bash
# check-criteria.sh <requirements.md>
#
# Reads each acceptance criterion with jev, an outside reader that has not
# seen the conversation, and asks three yes/no questions:
#   checkable   — could a stranger check it with a command, test or procedure?
#   impl detail — does it say how the change is built instead of what is seen?
#   vague       — does unmeasurable wording carry the requirement?
# Prints a markdown table with the probabilities and a verdict per criterion.
#
# Exit codes: 0 nothing flagged · 1 some criteria flagged · 2 usage error ·
#             3 jev unavailable (reason on stderr; apply the tests by hand).
# CHECK_THRESHOLD (default 0.5) is the probability at which a question flags.
set -u

HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=jev.sh
. "$HERE/jev.sh"

T="${CHECK_THRESHOLD:-0.5}"
ME=$(basename "$0")

if [ $# -ne 1 ] || [ ! -f "$1" ]; then
  echo "usage: $ME <requirements.md>" >&2
  exit 2
fi

CRITERIA=$(extract_criteria "$1")
if [ -z "$CRITERIA" ]; then
  echo "$ME: no acceptance criteria found in $1" >&2
  exit 2
fi

# The table is printed at the end, so an exit 3 midway leaves stdout empty.
table=""
i=0
flagged=0
while IFS= read -r criterion; do
  [ -n "$criterion" ] || continue
  i=$((i + 1))

  request=$(jq -cn --arg c "$criterion" '{
    model: "jev-latest",
    state: { criterion: $c },
    questions: {
      checkable: {
        type: "noul",
        instructions: "Could a person who did not write the code check `criterion` by running a command, a test, or a written procedure, without being told how the change was implemented?",
        criteria: {
          true: "It names an observable condition and an observable result that a stranger could reproduce and see",
          false: "Checking it would need knowledge of the implementation, or there is nothing concrete to observe"
        }
      },
      implementation_detail: {
        type: "noul",
        instructions: "Does `criterion` describe how the change is built rather than what can be observed from outside?",
        criteria: {
          true: "It names internal code structure: functions, classes, variables, private modules, algorithms, storage layout",
          false: "It names only behaviour, interfaces, commands, files, screens or outputs that a user or operator can see"
        }
      },
      vague: {
        type: "noul",
        instructions: "Does `criterion` rely on unmeasurable wording instead of stating the observable condition?",
        criteria: {
          true: "Phrases such as works correctly, is fast, handles properly, as expected carry the requirement",
          false: "The condition and the expected result are stated concretely"
        }
      }
    }
  }')

  body=$(jev_call "$request") || jev_unavailable "$ME"

  probs=$(printf '%s' "$body" | jq -r '
    "\(.answers.checkable.noul) \(.answers.implementation_detail.noul) \(.answers.vague.noul)"')
  read -r p_check p_impl p_vague <<EOF
$probs
EOF

  verdict=$(awk -v a="$p_check" -v b="$p_impl" -v c="$p_vague" -v t="$T" 'BEGIN {
    r = ""
    if (a + 0 < t + 0)  r = r "not checkable; "
    if (b + 0 >= t + 0) r = r "implementation detail; "
    if (c + 0 >= t + 0) r = r "vague; "
    if (r == "") print "ok"; else { sub(/; $/, "", r); print r }
  }')
  [ "$verdict" != ok ] && flagged=$((flagged + 1))

  table+=$(printf '| %d | %.2f | %.2f | %.2f | %s | %s |' \
    "$i" "$p_check" "$p_impl" "$p_vague" "$verdict" "$(md_cell "$criterion")")$'\n'
done <<EOF
$CRITERIA
EOF

echo "| # | checkable | impl detail | vague | verdict | criterion |"
echo "| --- | --- | --- | --- | --- | --- |"
printf '%s' "$table"
echo
echo "$i criteria, $flagged flagged (threshold $T)"
[ "$flagged" -eq 0 ]
