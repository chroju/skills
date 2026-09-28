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

3. If the output has a `### Bash write candidates (unclassified)` section
   (the classifier was unavailable when the script ran), classify those
   commands yourself before judging Non-application: with an Agent/Task
   subagent tool, launch exactly one subagent (`model: "haiku"`), giving it
   only the candidate commands, and ask for each: "Does this command
   create, overwrite, append to, or modify the contents of a file on disk?
   (deleting files, writing only to /dev/null or a pipe = no)" — a yes/no
   per command. With no subagent tool available, answer that same question
   yourself instead. Count only the "yes" answers as Bash writes when
   judging "Hooks bypassed by Bash edits" (a Write/Edit-matching hook with
   ≥1 Bash write), and say in that finding's Evidence whether the count
   came from the script's own classifier (a `### Bash write commands`
   section) or this fallback.

4. Decide the report's language: if any loaded instruction's text
   specifies a response language, use it for the *whole* report — the
   title, every table header, field label, and fixed phrase, not just
   section and issue-label names (see the translation example below).
   Otherwise use the conversation's language.

5. Turn the facts into findings using the table below. Every finding needs
   evidence: a quoted transcript excerpt or a named record (e.g. "hook_error
   attachment, PostToolUse"). Skip anything you can't ground this way.

6. Print the report below, then stop — do not write it to a file, open an
   editor, or post it anywhere.

## Finding labels

| Label | Grounds it in | Notes |
|---|---|---|
| Non-application | facts' `Expected but not loaded`, `Hooks bypassed by Bash edits`, `Hook errors`, `Configured hooks with no run record` | name the hook command / material and the count where the facts give one |
| Non-compliance | a human message that corrects the assistant on something a loaded instruction already covered | |
| Drift | a version, auto-mode-flag, or system-prompt difference — within the session, or vs. the previous session (facts' `Drift vs previous session`) | |
| Wording | another finding's root cause is how an instruction is phrased (ambiguous, contradicts another instruction, buried, missing an example, a weak Skill description) | Evidence quotes the current text verbatim; Proposed change quotes the full replacement text verbatim |
| Opportunity | repeated manual work, repeated permission waits, or a material that went unused or is redundant | |
| Rework | the human had work redone or the approach changed, including the same mistake repeated | quote the point; may be unrelated to any harness material; human messages with no assistant tool use or reply between them are one point, however different their wording — only messages the assistant actually acted or replied between are separate points; cap at 5, the ones that caused the most rework — see Report format for the overflow line |

A **Rework** point is any human message — including an AskUserQuestion
answer, whose preceding assistant text the facts show — that rejects,
replaces, or declines what the assistant just proposed or did: an explicit
correction, a counter-proposal, picking a non-recommended option, or
asking to reconsider, after which the assistant redid or re-proposed.
Describe only the redo the facts actually show — never invent a
reimplementation, edit, or reply that isn't in them. Like every finding,
a Rework finding still fills in all of summary, Evidence, Cause, Target,
Proposed change, and confidence — Target is usually `none`, but Cause
(why the redo happened) is never blank.

**Target** is the harness material the finding is about — the resolved
real path the facts already give for it (a CLAUDE.md, a Rule, a Skill's
SKILL.md, a hook's settings file), or, only when no such material exists,
a named non-file location, written in the report's language like every
other value (e.g. "Claude Code itself (release 2.1.283)", "this
environment's network egress allowlist" — see the translation example for
their Japanese form); `none` only for a Workflow finding. Target names the
material even when the fix itself is behavioral — e.g. a Non-compliance
finding about a Rule that never loaded targets that Rule's file, never
"the assistant's own behavior."

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
#### <n>. <Label> | <Confidence>: <level>
**<one-line summary>**
- Evidence: <quote, or the record it is based on>
- Cause: <why this is happening>
- Target: <real file path, or a named non-file location — never "none" outside Workflow>
- Proposed change: <what to do about it>
- Occurred in: <k>/<total> sessions (<ids>)   ← only in a multi-session report, only when this same finding recurred
```

`<Confidence>: <level>` is a placeholder like the rest of the block, not
literal English to copy verbatim — translate it the same as every field
label (see the translation example below). The other four sections —
Settings and hooks, Instructions, Skills and commands, Workflow — use the
same block shown above for Harness. Section order is always Harness,
Settings and hooks, Instructions, Skills and commands, Workflow; print a
heading only for a section that has at least one finding — a run with
findings in two sections prints exactly those two headings, not all five.
Workflow is the only section whose Target may be `none`. Number findings
sequentially across the whole report. Right after Workflow's findings, add
one more line before the closing lines, but only when Workflow was capped
at 5 Rework findings and further redo/redirect points exist:

```
<only when more than 5 Rework points exist: one line — "N more redo/redirect points: <timestamps>">
```

The report always ends with exactly one or two lines — never more, never
different ones, even when there are no findings:

```
<one line handing this off to the user, worded so it reads naturally with zero findings too — e.g. "What happens next, if anything, is your call.">
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
| ## Session retrospective (title) | ## セッションの振り返り |
| Item / Value | 項目 / 値 |
| Sessions | セッション |
| Auto mode | 自動モード |
| Comparison | 比較 |
| Not obtained | 取得できなかった項目 |
| Absent materials | 環境に存在しない材料 |
| Evidence / Cause / Target / Proposed change | 根拠 / 原因 / 対象 / 提案する変更 |
| Occurred in | 発生セッション数 |
| confidence: high / medium / low | 確信度: 高 / 中 / 低 |
| Harness / Settings and hooks / Instructions / Skills and commands / Workflow | ハーネス本体 / 設定・フック / Rules・CLAUDE.md / スキル・コマンド / 作業手順 |
| Non-application / Non-compliance / Drift / Wording / Opportunity / Rework | 未適用 / 不遵守 / 仕様変化 / 記述不備 / 改善余地 / 手戻り |
| "not recorded" / "no previous session transcript" / "changed during session" | 「記録なし」/「直前のセッションの記録なし」/「セッション中に変化」 |
| none (a field's value, e.g. Target for a Workflow finding) | なし |
| "Claude Code itself (release 2.1.283)" (example named Target) | 「Claude Code 本体（リリース 2.1.283）」 |
| "this environment's network egress allowlist" (example named Target) | 「この環境のネットワーク egress 許可リスト」 |
