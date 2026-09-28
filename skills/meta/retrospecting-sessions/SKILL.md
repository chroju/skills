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

2. For every real path the script's output names (a `Loaded instructions`
   entry, a `Hooks` source file, an `Instruction coverage` material, a
   nested CLAUDE.md), read that file's actual content — you need the exact
   wording to quote it and to check whether it sets a response language.
   Never read or assume anything about a material the script's
   `# Environment` section lists as absent from this environment, and never
   base a finding on one.

3. Decide the report's language: if any loaded instruction's text specifies
   a response language, use it — and translate the section names and issue
   labels below into it too. Otherwise use the conversation's language.

4. Turn the facts into findings using the table below. Every finding needs
   evidence: a quoted transcript excerpt or a named record (e.g. "hook_error
   attachment, PostToolUse"). Skip anything you can't ground this way.

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
| Rework | the human had work redone or the approach changed, including the same mistake repeated | quote the point; may be unrelated to any harness material |

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
| Absent materials | <materials the script's # Environment lists as absent, or "none"> |

### Harness
#### <n>. <Label> | confidence: <high|medium|low>
**<one-line summary>**
- Evidence: <quote, or the record it is based on>
- Cause: <why this is happening>
- Target: <real file path (resolved, not a symlink path) | a named non-file location | "none" for a Workflow finding>
- Proposed change: <what to do about it>
- Occurred in: <k>/<total> sessions (<ids>)   ← only in a multi-session report, only when this same finding recurred

### Settings and hooks
### Instructions
### Skills and commands
### Workflow

<one line handing the findings to the user — what to do with them is their call>
<one line offering to turn this into an artifact — only if an artifact-publishing tool is available in this session, and only an offer: never publish unless asked>
```

Section order is fixed (Harness, Settings and hooks, Instructions, Skills
and commands, Workflow); omit a section with no findings. Number findings
sequentially across the whole report. In a multi-session report, order
findings within a section by session count descending, then confidence
descending.

Example of a translated header (loaded instructions specify Japanese):
Harness → ハーネス本体, Settings and hooks → 設定・フック,
Instructions → Rules・CLAUDE.md, Skills and commands → スキル・コマンド,
Workflow → 作業手順; Non-application → 未適用, Non-compliance → 不遵守,
Drift → 仕様変化, Wording → 記述不備, Opportunity → 改善余地,
Rework → 手戻り.
