---
name: retrospecting-sessions
description: Produces a numbered, evidence-based retrospective of Claude Code session transcripts — non-applied or non-complied-with instructions, harness drift (version/auto-mode/system prompt), wording problems in CLAUDE.md/Rules/Skills, missed opportunities, and rework — grounded in the running environment's actual harness materials. Reports only; it never edits files or posts anywhere. Invoke with /retrospecting-sessions to cover only the current session, or /retrospecting-sessions <days> to also cover every session of the current project active in that many days.
license: MIT
argument-hint: '[days]'
disable-model-invocation: true
---

# Retrospecting Sessions

## Steps

1. Run the fact-extraction script:

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/collect_facts.py" --session "${CLAUDE_SESSION_ID}"
   ```

   If `$ARGUMENTS` is a positive integer, append `--days "$ARGUMENTS"` to also
   cover every session of the current project active in the last that many
   days. If `python3` is unavailable or the command exits non-zero, tell the
   user why and stop there — do not retry, work around it, or fall back to
   reading the transcript some other way.

2. The script's output is your primary evidence — quote it directly
   wherever it already gives you the text you need (a human message, a
   hook's stderr, a rule's touched-file list). Read a real file only to
   fill a specific gap the output points at but doesn't fully quote: a
   loaded instruction's or Rule's full wording (the output gives its
   path), or — when that path no longer exists on disk — the matching
   `instructions`/`nested_memory` record in the transcript itself, at the
   transcript path the output prints, using the path and timestamp the
   output gave you to find it (its `content` field carries the text that
   was actually loaded, even after the file is gone; say the file is gone
   in the finding, don't say the text "could not be checked"). Do not
   otherwise open the raw transcript to go looking for context the output
   doesn't already point you at. Never read or assume anything about a
   material the output's `# Environment` section lists as absent from this
   environment, and never base a finding on one — copy its listed paths
   verbatim into the report, don't paraphrase them.

3. Decide the report's language: if any loaded instruction's text
   specifies a response language, use it for the *whole* report — every
   table header, field label, and fixed phrase, not just section and
   issue-label names (see the translation example below). Otherwise use
   the conversation's language. A quoted excerpt (Evidence, a "current
   text"/"proposed text" pair) keeps its original wording either way —
   translate the report around the quote, never the quote itself.

4. Turn the facts into findings using the table below. Every finding needs
   evidence: a quoted transcript excerpt or a named record (e.g. "hook_error
   attachment, PostToolUse"). Skip anything you can't ground this way. For
   Rework in particular, report *every* distinct point in the session where
   work was redone or the approach changed — one finding per point, or one
   finding quoting each — don't stop at the first one you find.

5. Print the report below, then stop — do not write it to a file, open an
   editor, or post it anywhere.

## Finding labels

| Label | Grounds it in | Notes |
|---|---|---|
| Non-application | facts' `Expected but not loaded`, `Hooks bypassed by Bash edits`, `Hook errors`, `Configured hooks with no run record` | name the hook command / material and the count where the facts give one |
| Non-compliance | a human message that corrects the assistant on something a loaded instruction already covered | quote the instruction text and the human message |
| Drift | a version, auto-mode-flag, or system-prompt difference — within the session, or vs. the previous session (facts' `Drift vs previous session`) | if there is no previous session transcript, say so instead of a finding |
| Wording | another finding's root cause is how an instruction is phrased (ambiguous, contradicts another instruction, buried, missing an example, a weak Skill description) | Evidence quotes the current text verbatim; Proposed change quotes the full replacement text verbatim |
| Opportunity | repeated manual work, repeated permission waits, or a material that went unused or is redundant | |
| Rework | the human had work redone or the approach changed, including the same mistake repeated | quote the point; may be unrelated to any harness material; report every such point in the session, not only the first |

**Target** is the exact thing **Proposed change** would edit or act on —
never a file the change doesn't actually touch. Use a real file path
(resolved past any symlink) only when the proposed change is a text edit
to that file. Otherwise name the non-file thing precisely: e.g. "Claude
Code itself (release 2.1.283)" for a version or model-behavior issue,
"network egress allowlist of this environment" for a blocked domain, "the
assistant's own behavior in this conversation" for a plain slip with
nothing else to point at. `none` is reserved for a Workflow finding —
every Harness, Settings and hooks, Instructions, and Skills and commands
finding must name a real target.

## Report format

```
## Session retrospective

| Item | Value |
| --- | --- |
| Sessions | <id> (<start> – <end> UTC, <cwd>) — one line per session |
| Claude Code | <version, or "X → Y (changed during session)"> |
| Auto mode | <summary of the recorded flags, or "not recorded"> |
| Comparison | <what could be compared against the previous session, or "no previous session transcript"> |
| Not obtained | <record kinds the transcript lacked, or "none"> |
| Absent materials | <the exact paths the script's # Environment section lists as absent, copied verbatim, or "none"> |

### Harness
#### <n>. <Label> | confidence: <high|medium|low>
**<one-line summary>**
- Evidence: <quote, or the record it is based on>
- Cause: <why this is happening>
- Target: <real file path, or a named non-file location — never "none" outside Workflow>
- Proposed change: <what to do about it>
- Occurred in: <k>/<total> sessions (<ids>)   ← only in a multi-session report, only when this same finding recurred
```

The other four sections — Settings and hooks, Instructions, Skills and
commands, Workflow — use the same `#### <n>. <Label> | confidence: ...`
block shown above for Harness. Section order is always Harness, Settings
and hooks, Instructions, Skills and commands, Workflow; print a heading
only for a section that has at least one finding — a run with findings in
two sections prints exactly those two headings, not all five. Workflow is
the only section whose Target may be `none`. Number findings sequentially
across the whole report. In a multi-session report, order findings within
a section by session count descending, then confidence descending.

The report always ends with exactly one or two lines — never more, never
different ones, even when there are no findings:

```
<one line handing the findings to the user — what to do with them is their call>
<one line offering to turn this into an artifact — only if an artifact-publishing tool is available in this session, and only an offer: never publish unless asked>
```

Never replace the handoff line with something else (a suggestion to rerun
with a longer `--days`, to check back later, and so on) — it is always
this handoff, whether or not there were findings.

If nothing meets the evidence bar, the report is still the header table
plus these closing lines — no section headings, and no finding invented to
fill the gap:

```
## Session retrospective

| Item | Value |
| --- | --- |
| ... |

No findings met the evidence bar for <this session | these N sessions>.

<handoff line>
<artifact-offer line, only if available>
```

Example translation (loaded instructions specify Japanese) — translate
everything below, not only section and issue-label names:

| English | Japanese |
| --- | --- |
| Item / Value | 項目 / 値 |
| Sessions | セッション |
| Auto mode | 自動モード |
| Comparison | 比較 |
| Not obtained | 取得できなかった項目 |
| Absent materials | 環境に存在しない材料 |
| Evidence / Cause / Target / Proposed change | 根拠 / 原因 / 対象 / 提案する変更 |
| Occurred in / confidence | 発生セッション数 / 確信度 |
| Harness / Settings and hooks / Instructions / Skills and commands / Workflow | ハーネス本体 / 設定・フック / Rules・CLAUDE.md / スキル・コマンド / 作業手順 |
| Non-application / Non-compliance / Drift / Wording / Opportunity / Rework | 未適用 / 不遵守 / 仕様変化 / 記述不備 / 改善余地 / 手戻り |
| "not recorded" / "no previous session transcript" / "changed during session" | 「記録なし」/「直前のセッションの記録なし」/「セッション中に変化」 |
