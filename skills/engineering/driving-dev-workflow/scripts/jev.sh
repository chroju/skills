#!/bin/bash
# Shared helpers for the jev checks in this skill. Source it; do not run it.
#
# jev is TypeSafe's System One model (https://docs.typesafe.ai): it answers
# typed yes/no questions about a piece of state with a probability, and does
# not generate text. The scripts here use it as an outside reader of the
# requirements and design documents.
#
# Needs: TYPESAFE_API_KEY in the environment, curl, jq.
# Optional: TYPESAFE_API_URL (default https://api.typesafe.ai/v1/systemone).

JEV_API_URL="${TYPESAFE_API_URL:-https://api.typesafe.ai/v1/systemone}"

# jev_call REQUEST_JSON
#   Prints the response body and returns 0. Returns 3 when jev cannot be used
#   (no key, network failure, non-200 answer), after writing the reason to
#   stderr — callers run this in a subshell, so a variable would not survive.
jev_call() {
  local request=$1 response rc http body
  if [ -z "${TYPESAFE_API_KEY:-}" ]; then
    echo "jev unavailable: TYPESAFE_API_KEY is not set" >&2
    return 3
  fi
  response=$(curl -sS --max-time 20 -w '\n%{http_code}' "$JEV_API_URL" \
    -H "Authorization: Bearer $TYPESAFE_API_KEY" \
    -H 'Content-Type: application/json' \
    --data "$request" 2>&1)
  rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "jev unavailable: curl failed ($rc): ${response%%$'\n'*}" >&2
    return 3
  fi
  http=${response##*$'\n'}
  body=${response%$'\n'*}
  if [ "$http" != 200 ]; then
    echo "jev unavailable: HTTP $http: $(printf '%s' "$body" | head -c 200)" >&2
    return 3
  fi
  printf '%s' "$body"
}

# jev_unavailable SCRIPT_NAME
#   Exits 3 after jev_call reported why jev could not be used. The
#   orchestrator then applies the same tests itself, as the workflow did
#   before these scripts existed.
jev_unavailable() {
  printf '%s: apply the checks yourself, as before.\n' "$1" >&2
  exit 3
}

# extract_criteria FILE
#   Prints one acceptance criterion per line: the top-level list items under
#   the "Acceptance criteria" heading (English or Japanese). Indented lines —
#   continuation text, nested bullets, tables — are joined to their item;
#   template comments are skipped.
extract_criteria() {
  awk '
    /<!--/ { in_comment = 1 }
    in_comment { if ($0 ~ /-->/) in_comment = 0; next }
    /^#+[[:space:]]/ {
      # The section ends at the next heading of the same or a higher level;
      # deeper headings (sub-groups of criteria) stay inside it.
      match($0, /^#+/); lvl = RLENGTH
      if ($0 ~ /^#+[[:space:]]*Acceptance criteria/ || $0 ~ /受け入れ基準/) { in_sec = 1; sec_lvl = lvl }
      else if (in_sec && lvl <= sec_lvl) in_sec = 0
      next
    }
    !in_sec { next }
    /^([-*]|[0-9]+\.)[[:space:]]+/ {
      if (cur != "") print cur
      cur = $0
      sub(/^([-*]|[0-9]+\.)[[:space:]]+/, "", cur)
      next
    }
    /^[[:space:]]+[^[:space:]]/ {
      if (cur != "") { line = $0; sub(/^[[:space:]]+/, "", line); cur = cur " " line }
      next
    }
    END { if (cur != "") print cur }
  ' "$1"
}

# extract_verification_rows FILE
#   Prints the body rows of the "Verification plan" table as
#   criterion<US>state<US>check (US = 0x1f, which unlike TAB keeps an empty
#   state cell in place for `read`), header and separator dropped.
extract_verification_rows() {
  awk -F'|' '
    /^#+[[:space:]]/ {
      match($0, /^#+/); lvl = RLENGTH
      if ($0 ~ /^#+[[:space:]]*Verification plan/ || $0 ~ /検証計画/) { in_sec = 1; sec_lvl = lvl; n = 0 }
      else if (in_sec && lvl <= sec_lvl) in_sec = 0
      next
    }
    !in_sec { next }
    /^[[:space:]]*\|/ {
      if ($0 ~ /^[|[:space:]:-]+$/) next
      n++
      # Header row: remember whether the table has the "state" column
      # (criterion | state | check) or the older two-column shape (criterion | check).
      if (n == 1) { ncols = NF - 2; next }
      for (i = 2; i < NF; i++) { gsub(/^[[:space:]]+|[[:space:]]+$/, "", $i) }
      if (ncols == 2) printf "%s\037%s\037%s\n", $2, "", $3
      else printf "%s\037%s\037%s\n", $2, $3, $4
    }
  ' "$1"
}

# md_cell TEXT — escape a value for a markdown table cell
md_cell() {
  local s=$1
  s=${s//|/\\|}
  printf '%s' "$s"
}
