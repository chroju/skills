#!/usr/bin/env python3
# collect_facts.py --session <id> [--days N] [--config-dir DIR]
#
# Reads one or more Claude Code session transcripts (JSONL under
# <config-dir>/projects/*/<session-id>.jsonl, plus that session's own
# <session-id>/subagents/*.jsonl if present) and the harness materials
# present in the running environment (settings.json, Rules, nested
# CLAUDE.md files) and prints plain facts as Markdown to stdout. It makes
# no judgments and writes nothing anywhere: no file is created or
# modified, on this machine or elsewhere.
#
# --session <id>   the anchor session (matched literally, not as a glob);
#                   with no --days, the only session covered.
# --days N         a positive integer. Also cover every session of the
#                   same project whose transcript's last record falls
#                   within the last N days.
# --config-dir DIR overrides $CLAUDE_CONFIG_DIR / ~/.claude.
#
# Exit codes: 0 success / 2 usage error / 3 transcript not found.

import argparse
import datetime
import difflib
import hashlib
import json
import os
import re
import sys
from pathlib import Path

# Nothing about this script should ever write a .pyc or any other file.
sys.dont_write_bytecode = True

VENDOR_DIR_NAMES = {
    ".git", "node_modules", "dist", "build", ".venv", "venv", "vendor",
    "target", "__pycache__", ".next", ".cache", "coverage", ".tox",
    ".mypy_cache", ".pytest_cache", "site-packages",
}

USED_RECORD_KINDS = ["instructions", "auto_mode", "prompt_snapshot"]


# ---------------------------------------------------------------------------
# Small generic helpers
# ---------------------------------------------------------------------------

def eprint(*a, **kw):
    print(*a, file=sys.stderr, **kw)


def trunc(value, limit):
    s = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if len(s) <= limit:
        return s
    return s[:limit] + "…"


def single_line(value):
    """Collapse any embedded newlines so a printed excerpt can never start a
    line with `#` (or anything else) that would read as one of this
    script's own Markdown headings — a heredoc body is the common source."""
    s = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    return " ⏎ ".join(s.split("\n"))


def line_excerpt(value, limit):
    """A truncated, single-line excerpt safe to embed in a bullet line."""
    return single_line(trunc(value, limit))


def parse_ts(s):
    if not isinstance(s, str) or not s:
        return None
    text = s[:-1] + "+00:00" if s.endswith("Z") else s
    try:
        dt = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def fmt_dt(dt):
    if dt is None:
        return "unknown"
    dt = dt.astimezone(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_best_effort(p):
    try:
        return Path(p).resolve()
    except (OSError, RuntimeError):
        # RuntimeError: a symlink loop under Path.resolve()'s loop detection.
        return Path(p)


def subagent_suffix(marker):
    return f" (subagent: {marker})" if marker else ""


# ---------------------------------------------------------------------------
# Record access — tolerant of any valid-JSON shape a line might hold
# ---------------------------------------------------------------------------

def message_content(r):
    msg = r.get("message")
    if not isinstance(msg, dict):
        return None
    return msg.get("content")


def tool_input(c):
    """Normalize a tool_use content item's `input` to a dict, tolerating a
    malformed record where it is missing or not a dict (e.g. a string)."""
    inp = c.get("input")
    return inp if isinstance(inp, dict) else {}


def iter_tool_uses(records):
    """Yield (record, item) for every well-formed assistant tool_use
    content item across `records`. The one iterator every tool-use-reading
    fact (counts, touched files, Skill calls) is built on."""
    for r in records:
        if not isinstance(r, dict) or r.get("type") != "assistant":
            continue
        content = message_content(r)
        if not isinstance(content, list):
            continue
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                yield r, c


def attachment_records(records, atype):
    out = []
    for r in records:
        if not isinstance(r, dict) or r.get("type") != "attachment":
            continue
        att = r.get("attachment")
        if isinstance(att, dict) and att.get("type") == atype:
            out.append(r)
    return out


def tool_use_index(records):
    """tool_use_id -> {"name": ..., "input": ...}"""
    idx = {}
    for r, c in iter_tool_uses(records):
        tid = c.get("id")
        if isinstance(tid, str) and tid:
            idx[tid] = {"name": c.get("name"), "input": tool_input(c)}
    return idx


def tool_use_lookup(tu_idx, c):
    """tu_idx.get(c["tool_use_id"]), tolerating a malformed record where
    tool_use_id is not a string (e.g. a list — unhashable, so a plain
    dict.get() would raise)."""
    tid = c.get("tool_use_id")
    if not isinstance(tid, str):
        return {}
    return tu_idx.get(tid, {})


def first_field(records, field):
    for r in records:
        if not isinstance(r, dict):
            continue
        v = r.get(field)
        if v:
            return v
    return None


def last_field(records, field):
    val = None
    for r in records:
        if not isinstance(r, dict):
            continue
        v = r.get(field)
        if v:
            val = v
    return val


def first_string_field(records, field):
    """Like first_field, but skips a record where the field is present
    with a non-string value (a malformed `"cwd": 123`, say) instead of
    handing the caller a type it can't use as a path."""
    for r in records:
        if not isinstance(r, dict):
            continue
        v = r.get(field)
        if isinstance(v, str) and v:
            return v
    return None


# ---------------------------------------------------------------------------
# Transcript loading
# ---------------------------------------------------------------------------

def load_jsonl(path):
    """Every line that parses as JSON but is not an object (null, a list,
    a number, ...) is skipped: this script only ever deals in records."""
    records = []
    try:
        fh = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return records
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                records.append(rec)
    return records


def session_bounds(path):
    """First/last record timestamp, read without keeping the parsed
    records — the cheap pass used to scope --days and find a previous
    session across possibly many sibling transcripts."""
    first_ts = None
    last_ts = None
    try:
        fh = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return None, None
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            ts = parse_ts(rec.get("timestamp"))
            if ts is None:
                continue
            if first_ts is None or ts < first_ts:
                first_ts = ts
            if last_ts is None or ts > last_ts:
                last_ts = ts
    return first_ts, last_ts


def session_span(records):
    parsed = [t for t in (parse_ts(r.get("timestamp")) for r in records if isinstance(r, dict)) if t]
    if not parsed:
        return None, None
    return min(parsed), max(parsed)


def load_subagent_records(session_dir, session_id):
    """Records from <session_dir>/<session_id>/subagents/*.jsonl, each
    tagged with the subagent file's name so downstream facts can mark
    where they came from."""
    subdir = session_dir / session_id / "subagents"
    if not subdir.is_dir():
        return []
    out = []
    try:
        files = sorted(subdir.glob("*.jsonl"))
    except OSError:
        return []
    for f in files:
        for r in load_jsonl(f):
            r["_subagent"] = f.stem
            out.append(r)
    return out


# ---------------------------------------------------------------------------
# Session discovery
# ---------------------------------------------------------------------------

def find_transcript(config_dir, session_id):
    """Literal match only — session_id is never treated as a glob."""
    projects_dir = config_dir / "projects"
    if not projects_dir.is_dir():
        return None
    try:
        project_subdirs = sorted(p for p in projects_dir.iterdir() if p.is_dir())
    except OSError:
        return None
    for proj_dir in project_subdirs:
        candidate = proj_dir / f"{session_id}.jsonl"
        if candidate.is_file():
            return candidate
    return None


def discover_session_files(session_dir):
    try:
        return sorted(session_dir.glob("*.jsonl"))
    except OSError:
        return []


def build_session_index(session_dir):
    """One lightweight pass per sibling transcript: {id: {path, first,
    last}}. Never holds more than one file's parsed records at a time."""
    index = {}
    for jf in discover_session_files(session_dir):
        first_ts, last_ts = session_bounds(jf)
        index[jf.stem] = {"path": jf, "first": first_ts, "last": last_ts}
    return index


def previous_session_id(index, current_id, current_first_ts):
    """The id of the sibling with the latest last-record timestamp that is
    still before current_first_ts — computed from the lightweight index
    alone, no file re-parsed."""
    if current_first_ts is None:
        return None
    best_id, best_last = None, None
    for sid, info in index.items():
        if sid == current_id:
            continue
        last = info.get("last")
        if last is not None and last < current_first_ts:
            if best_last is None or last > best_last:
                best_last = last
                best_id = sid
    return best_id


# ---------------------------------------------------------------------------
# Rule / nested CLAUDE.md discovery — followlinks, loop-guarded (a symlinked
# rules subdirectory, or a symlinked nested project directory, is common)
# ---------------------------------------------------------------------------

def walk_files_followlinks(base_dir, suffix):
    """os.walk(followlinks=True) with a real-path loop guard, yielding
    Path objects for every file under base_dir ending in `suffix`."""
    if not base_dir.is_dir():
        return []
    found = []
    visited_real_dirs = set()
    for root, dirs, files in os.walk(base_dir, followlinks=True):
        rootp = Path(root)
        real_root = resolve_best_effort(rootp)
        if real_root in visited_real_dirs:
            dirs[:] = []
            continue
        visited_real_dirs.add(real_root)
        for f in files:
            if f.endswith(suffix):
                found.append(rootp / f)
    return sorted(found)


def raw_paths_text(text):
    """The `paths:` frontmatter value exactly as written — a same-line
    scalar/list/string, or block-list items joined with ", " — or None if
    the key is absent (a rule with no `paths:` loads unconditionally at
    startup). Not parsed or interpreted: what the model sees is what the
    file says."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    body = []
    i = 1
    while i < len(lines) and lines[i].strip() != "---":
        body.append(lines[i])
        i += 1
    j = 0
    while j < len(body):
        m = re.match(r"^paths:\s*(.*)$", body[j])
        if m:
            val = m.group(1).strip()
            if val:
                return val
            items = []
            k = j + 1
            while k < len(body):
                stripped = body[k].strip()
                if stripped == "" or stripped.startswith("#"):
                    k += 1
                    continue
                im = re.match(r"^\s*-\s+(.*)$", body[k])
                if not im:
                    break
                items.append(im.group(1).strip())
                k += 1
            return ", ".join(items) if items else None
        j += 1
    return None


def find_rule_files(rules_dir):
    return walk_files_followlinks(rules_dir, ".md")


def find_nested_claude_md(project_dir):
    result = []
    if not project_dir.is_dir():
        return result
    visited_real_dirs = set()
    for root, dirs, files in os.walk(project_dir, followlinks=True):
        dirs[:] = [d for d in dirs if d not in VENDOR_DIR_NAMES and not d.startswith(".")]
        rootp = Path(root)
        real_root = resolve_best_effort(rootp)
        if real_root in visited_real_dirs:
            dirs[:] = []
            continue
        visited_real_dirs.add(real_root)
        if rootp == project_dir:
            continue
        if "CLAUDE.md" in files:
            result.append(rootp / "CLAUDE.md")
    return sorted(result)


def rules_list(config_dir, project_dir):
    """Every Rule file found under either rules dir, with its `paths:`
    value verbatim and, when the file was reached through a symlink, the
    path it was discovered at alongside the resolved real path."""
    rules = []
    for rules_dir in (config_dir / "rules", project_dir / ".claude" / "rules"):
        for f in find_rule_files(rules_dir):
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            real = resolve_best_effort(f)
            rules.append({
                "path": real,
                "raw_paths": raw_paths_text(text),
                "link_note": f" (link: {f})" if str(real) != str(f) else "",
            })
    return rules


# ---------------------------------------------------------------------------
# Touched files (what the session read/edited/wrote or shelled into)
# ---------------------------------------------------------------------------

def resolve_relative(fp, project_dir):
    p = Path(fp)
    if not p.is_absolute():
        p = project_dir / p
    return resolve_best_effort(p)


def touched_files(records, project_dir):
    """Files reached via Read/Edit/Write/MultiEdit/NotebookEdit — the
    tools that trigger nested-instruction loading. Bash is not inspected:
    the raw commands are listed separately (### Bash commands) and it is
    the model's job to judge whether any of them touched a covered path."""
    touched = []
    for r, c in iter_tool_uses(records):
        name = c.get("name")
        if name not in ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit"):
            continue
        inp = tool_input(c)
        fp = inp.get("file_path") or inp.get("notebook_path")
        if isinstance(fp, str) and fp:
            touched.append({
                "real": resolve_relative(fp, project_dir),
                "how": name,
                "subagent": r.get("_subagent"),
            })
    return touched


def claude_md_up_from(start_dir, stop_dirs):
    """CLAUDE.md files found walking up from start_dir (inclusive) until,
    but not including, any directory in stop_dirs."""
    found = []
    seen = set()
    cur = resolve_best_effort(start_dir)
    while cur not in seen:
        seen.add(cur)
        if cur in stop_dirs:
            break
        candidate = cur / "CLAUDE.md"
        if candidate.is_file():
            found.append(resolve_best_effort(candidate))
        parent = cur.parent
        if parent == cur:
            break  # filesystem root
        cur = parent
    return found


def claude_md_files_for(touched, project_dir, config_dir):
    """Nested CLAUDE.md under the project dir, plus CLAUDE.md in the
    ancestor directories of touched (tool-reached) files, up to but not
    including the user's home directory or the filesystem root — never
    the config dir's own CLAUDE.md (user memory, not a project material).
    Each is labelled inside or outside the project dir."""
    config_claude_md = resolve_best_effort(config_dir / "CLAUDE.md")
    stop_dirs = {resolve_best_effort(Path.home()), Path(project_dir.anchor)}
    all_paths = set(resolve_best_effort(f) for f in find_nested_claude_md(project_dir))
    for t in touched:
        all_paths.update(claude_md_up_from(t["real"].parent, stop_dirs))
    all_paths.discard(config_claude_md)
    result = []
    for real in sorted(all_paths, key=str):
        try:
            real.relative_to(project_dir)
            location = "inside project"
        except ValueError:
            location = "outside project dir"
        result.append({"path": real, "location": location})
    return result


def bash_commands_list(records):
    """Every Bash command, verbatim — no extraction or interpretation.
    Judging whether one touched a covered path is the model's job."""
    out = []
    for r, c in iter_tool_uses(records):
        if c.get("name") != "Bash":
            continue
        cmd = tool_input(c).get("command")
        if isinstance(cmd, str) and cmd:
            out.append({"command": cmd, "timestamp": r.get("timestamp"), "subagent": r.get("_subagent")})
    return out


def tool_use_counts(records):
    counts = {}
    for r, c in iter_tool_uses(records):
        name = c.get("name")
        if not isinstance(name, str) or not name:
            name = "?"
        counts[name] = counts.get(name, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Hooks (settings.json)
# ---------------------------------------------------------------------------

def load_settings_files(config_dir, project_dir):
    candidates = [
        config_dir / "settings.json",
        project_dir / ".claude" / "settings.json",
        project_dir / ".claude" / "settings.local.json",
    ]
    out = []
    for p in candidates:
        exists = p.is_file()
        hooks_cfg = {}
        if exists:
            try:
                data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            except (json.JSONDecodeError, OSError):
                data = None
            if isinstance(data, dict):
                raw_hooks = data.get("hooks")
                if isinstance(raw_hooks, dict):
                    hooks_cfg = raw_hooks
        out.append({"path": p, "exists": exists, "hooks": hooks_cfg})
    return out


def extract_hook_entries(settings_list):
    entries = []
    for s in settings_list:
        if not s["exists"]:
            continue
        real = resolve_best_effort(s["path"])
        for event, matcher_list in s["hooks"].items():
            if not isinstance(matcher_list, list):
                continue
            for m in matcher_list:
                if not isinstance(m, dict):
                    continue
                matcher = m.get("matcher")
                matcher = matcher if isinstance(matcher, str) else ""
                hooks = m.get("hooks")
                if not isinstance(hooks, list):
                    continue
                for h in hooks:
                    if not isinstance(h, dict) or h.get("type") != "command":
                        continue
                    command = h.get("command")
                    if isinstance(command, str) and command:
                        entries.append({
                            "event": event,
                            "matcher": matcher,
                            "command": command,
                            "source": real,
                        })
    return entries


def matcher_covers_tool(matcher, tool_name):
    if matcher in ("", "*", None):
        return True
    try:
        return re.search(matcher, tool_name) is not None
    except re.error:
        return False


def derive_hook_command(hook_name, hook_event, hook_entries):
    """A hook error record often carries no usable command directly (the
    real hook_non_blocking_error shape has none at all). Recover it by
    matching hookEvent, and — when hookName embeds the tool as
    `Event:Tool` — the tool, against the configured hooks."""
    tool_name = None
    if isinstance(hook_name, str) and ":" in hook_name:
        tool_name = hook_name.rsplit(":", 1)[-1]
    candidates = [h for h in hook_entries if h["event"] == hook_event]
    if tool_name:
        for h in candidates:
            if matcher_covers_tool(h["matcher"], tool_name):
                return h["command"]
    if len(candidates) == 1:
        return candidates[0]["command"]
    return None


def executed_hook_commands(records):
    cmds = set()
    for r in records:
        if not isinstance(r, dict):
            continue
        if r.get("type") == "attachment":
            att = r.get("attachment")
            if isinstance(att, dict) and att.get("type") == "hook_success":
                cmd = att.get("command")
                if isinstance(cmd, str) and cmd:
                    cmds.add(cmd)
        if r.get("type") == "system" and r.get("subtype") == "stop_hook_summary":
            hook_infos = r.get("hookInfos")
            if isinstance(hook_infos, list):
                for hi in hook_infos:
                    if isinstance(hi, dict):
                        cmd = hi.get("command")
                        if isinstance(cmd, str) and cmd:
                            cmds.add(cmd)
    return cmds


def hook_error_records(records, hook_entries):
    """Real shapes: hook_non_blocking_error = {hookName, toolUseID,
    hookEvent, stderr, stdout, exitCode} (no command); hook_blocking_error
    = {hookName, toolUseID, hookEvent, blockingError: {blockingError,
    command}}. A hook that errored counts as having run."""
    errs = []
    for r in records:
        if not isinstance(r, dict):
            continue
        subagent = r.get("_subagent")
        if r.get("type") == "attachment":
            att = r.get("attachment")
            if not isinstance(att, dict):
                continue
            t = att.get("type")
            if t == "hook_non_blocking_error":
                hook_name = att.get("hookName")
                event = att.get("hookEvent")
                command = derive_hook_command(hook_name, event, hook_entries)
                text = att.get("stderr") or att.get("stdout") or ""
                errs.append({
                    "hookName": hook_name, "command": command, "event": event,
                    "text": text if isinstance(text, str) else "", "subagent": subagent,
                })
            elif t == "hook_blocking_error":
                hook_name = att.get("hookName")
                event = att.get("hookEvent")
                be = att.get("blockingError")
                command = None
                text = ""
                if isinstance(be, dict):
                    command = be.get("command")
                    text = be.get("blockingError") or ""
                elif isinstance(be, str):
                    text = be
                if not isinstance(command, str) or not command:
                    command = derive_hook_command(hook_name, event, hook_entries)
                errs.append({
                    "hookName": hook_name, "command": command, "event": event,
                    "text": text if isinstance(text, str) else "", "subagent": subagent,
                })
        if r.get("type") == "system" and r.get("subtype") == "stop_hook_summary":
            hook_errors = r.get("hookErrors")
            if not isinstance(hook_errors, list):
                continue
            for he in hook_errors:
                if isinstance(he, dict):
                    errs.append({
                        "hookName": he.get("hookName") or he.get("command"),
                        "command": he.get("command"),
                        "event": "Stop",
                        "text": he.get("stderr") or he.get("error") or json.dumps(he, ensure_ascii=False),
                        "subagent": subagent,
                    })
                else:
                    errs.append({"hookName": None, "command": None, "event": "Stop", "text": str(he), "subagent": subagent})
    return errs


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------

def render_environment(config_dir, project_dir):
    checks = [
        config_dir / "settings.json",
        project_dir / ".claude" / "settings.json",
        project_dir / ".claude" / "settings.local.json",
        config_dir / "rules",
        project_dir / ".claude" / "rules",
    ]
    absent = [p for p in checks if not p.exists()]
    lines = ["# Environment", ""]
    if absent:
        for p in absent:
            lines.append(f"- `{p}`: absent from this environment")
    else:
        lines.append("- none absent")
    lines.append("")
    return lines, set(absent)


def render_overview(session_id, records, transcript_path):
    first_ts, last_ts = session_span(records)
    cwd = first_string_field(records, "cwd")
    entrypoint = first_field(records, "entrypoint")
    lines = ["## Overview", ""]
    lines.append(f"- Session ID: {session_id}")
    lines.append(f"- Transcript: {resolve_best_effort(transcript_path)}")
    lines.append(f"- Start: {fmt_dt(first_ts)}")
    lines.append(f"- End: {fmt_dt(last_ts)}")
    lines.append(f"- cwd: {cwd or 'unknown'}")
    if isinstance(cwd, str) and cwd:
        try:
            runtime_cwd = os.getcwd()
        except OSError:
            runtime_cwd = None
        if runtime_cwd and cwd != runtime_cwd:
            lines.append(f"- Note: recorded cwd differs from this run's cwd (`{runtime_cwd}`)")
    if entrypoint:
        lines.append(f"- Entrypoint: {entrypoint}")
    versions = []
    prev = None
    for r in records:
        v = r.get("version")
        if isinstance(v, str) and v and v != prev:
            versions.append((r.get("timestamp"), v))
            prev = v
    if versions:
        lines.append("- Versions:")
        for ts, v in versions:
            lines.append(f"  - {v} (first seen {fmt_dt(parse_ts(ts))})")
    else:
        lines.append("- Versions: none recorded")
    ams = attachment_records(records, "auto_mode")
    if ams:
        lines.append("- Auto mode:")
        for r in ams:
            att = {k: v for k, v in r["attachment"].items() if k != "type"}
            lines.append(f"  - {fmt_dt(parse_ts(r.get('timestamp')))}: {json.dumps(att, ensure_ascii=False, sort_keys=True)}")
    else:
        lines.append("- Auto mode: none recorded")
    lines.append("")
    return lines


def render_drift(records, prev_id, prev_records):
    lines = ["## Drift vs previous session", ""]
    if prev_id is None or prev_records is None:
        lines.append("no previous session transcript")
        lines.append("")
        return lines
    lines.append(f"- Previous session: {prev_id}")

    cur_version = last_field(records, "version")
    prev_version = last_field(prev_records, "version")
    if cur_version != prev_version:
        lines.append(f"- Version: {prev_version} -> {cur_version}")

    def _auto(rs):
        ams = attachment_records(rs, "auto_mode")
        if not ams:
            return None
        return {k: v for k, v in ams[-1]["attachment"].items() if k != "type"}

    cur_auto = _auto(records)
    prev_auto = _auto(prev_records)
    if cur_auto != prev_auto:
        keys = set((cur_auto or {}).keys()) | set((prev_auto or {}).keys())
        diffs = [k for k in sorted(keys) if (cur_auto or {}).get(k) != (prev_auto or {}).get(k)]
        if diffs:
            lines.append(f"- Auto mode fields changed: {', '.join(diffs)}")
            lines.append(f"  - previous: {json.dumps(prev_auto, ensure_ascii=False, sort_keys=True)}")
            lines.append(f"  - current: {json.dumps(cur_auto, ensure_ascii=False, sort_keys=True)}")

    def _snapshot(rs):
        snaps = attachment_records(rs, "prompt_snapshot")
        if not snaps:
            return None
        sp = snaps[-1]["attachment"].get("systemPrompt", [])
        if isinstance(sp, list):
            return "\n".join(str(x) for x in sp)
        return str(sp)

    cur_sp = _snapshot(records)
    prev_sp = _snapshot(prev_records)
    if cur_sp is not None and prev_sp is not None and cur_sp != prev_sp:
        cur_hash = hashlib.sha256(cur_sp.encode("utf-8")).hexdigest()
        prev_hash = hashlib.sha256(prev_sp.encode("utf-8")).hexdigest()
        lines.append(f"- System prompt sha256: {prev_hash} -> {cur_hash}")
        diff = list(
            difflib.unified_diff(
                prev_sp.splitlines(),
                cur_sp.splitlines(),
                fromfile="previous system prompt",
                tofile="current system prompt",
                lineterm="",
            )
        )
        if diff:
            lines.append("  ```diff")
            for line in diff[:80]:
                lines.append(f"  {line}")
            if len(diff) > 80:
                lines.append(f"  … ({len(diff) - 80} more lines)")
            lines.append("  ```")

    if len(lines) == 2:
        lines.append("- no drift detected")
    lines.append("")
    return lines


def render_loaded_instructions(records):
    lines = ["## Loaded instructions", ""]
    entries = []
    for r in attachment_records(records, "instructions"):
        files = r["attachment"].get("files")
        if isinstance(files, list):
            for f in files:
                if isinstance(f, dict):
                    entries.append((r.get("timestamp"), "instructions", f.get("type", "?"), f.get("path")))
    for r in attachment_records(records, "nested_memory"):
        entries.append((r.get("timestamp"), "nested_memory", "-", r["attachment"].get("path")))
    # Sort by parsed timestamp, not the raw field: a mix of numeric and
    # string `timestamp` values across records is not otherwise orderable.
    entries.sort(key=lambda e: parse_ts(e[0]) or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc))
    if not entries:
        lines.append("- none recorded")
    else:
        for ts, kind, ftype, path in entries:
            if isinstance(path, str) and path:
                real = resolve_best_effort(path)
                shown = f"`{real}`" if str(real) == path else f"`{real}` (recorded as `{path}`)"
            else:
                shown = f"`{path}`"
            lines.append(f"- {fmt_dt(parse_ts(ts))}: {kind} ({ftype}) {shown}")
    lines.append("")
    return lines


def render_skills_and_commands(records):
    lines = ["## Skills and commands", ""]
    any_found = False
    for r in attachment_records(records, "invoked_skills"):
        skills = r["attachment"].get("skills")
        if isinstance(skills, list):
            for s in skills:
                if isinstance(s, dict):
                    any_found = True
                    lines.append(f"- {fmt_dt(parse_ts(r.get('timestamp')))}: invoked_skills `{s.get('name')}` (`{s.get('path')}`)")
    for r, c in iter_tool_uses(records):
        if c.get("name") == "Skill":
            any_found = True
            inp = tool_input(c)
            lines.append(f"- {fmt_dt(parse_ts(r.get('timestamp')))}: Skill tool_use `{inp.get('skill')}` args={json.dumps(inp.get('args', ''), ensure_ascii=False)}")
    for r in records:
        if r.get("type") != "user":
            continue
        content = message_content(r)
        if not isinstance(content, str):
            continue
        for m in re.finditer(r"<command-name>([^<]*)</command-name>", content):
            any_found = True
            lines.append(f"- {fmt_dt(parse_ts(r.get('timestamp')))}: slash command `{m.group(1).strip()}`")
    if not any_found:
        lines.append("- none recorded")
    lines.append("")
    return lines


def render_tool_use(combined_records):
    lines = ["## Tool use", ""]
    counts = tool_use_counts(combined_records)
    if counts:
        for name in sorted(counts, key=lambda n: (-counts[n], n)):
            lines.append(f"- {name}: {counts[name]}")
    else:
        lines.append("- no tool calls recorded")
    lines.append("")
    return lines


def render_hooks(combined_records, hook_entries):
    lines = ["## Hooks", ""]
    lines.append("### Configured hooks")
    if hook_entries:
        for h in hook_entries:
            lines.append(f"- {h['event']} matcher=`{h['matcher'] or '(empty)'}` command=`{h['command']}` (`{h['source']}`)")
    else:
        lines.append("- none configured")

    errs = hook_error_records(combined_records, hook_entries)
    executed = executed_hook_commands(combined_records) | {e["command"] for e in errs if e.get("command")}

    lines.append("")
    lines.append("### Hook errors")
    if errs:
        for e in errs:
            label = e.get("command") or e.get("hookName") or "(unknown hook)"
            lines.append(
                f"- Hook error: `{label}` (event={e.get('event')}) — "
                f"stderr: \"{line_excerpt(e.get('text', ''), 300)}\"{subagent_suffix(e.get('subagent'))}"
            )
    else:
        lines.append("- none recorded")

    lines.append("")
    lines.append("### Configured hooks with no run record")
    no_run = [h for h in hook_entries if h["command"] not in executed]
    if no_run:
        for h in no_run:
            lines.append(f"- `{h['command']}` (event={h['event']}, matcher=`{h['matcher'] or '(empty)'}`)")
    else:
        lines.append("- none" if hook_entries else "- none configured")
    lines.append("")
    return lines, errs, no_run


def render_instruction_materials(combined_records, rules, project_dir, config_dir):
    """The raw material a model needs to judge instruction coverage
    itself — this script makes no judgment: no matching, no "not
    loaded" verdict. See design.md, "Shrink"."""
    lines = ["## Instruction materials", ""]

    lines.append("### Rules")
    if rules:
        for r in rules:
            paths_text = r["raw_paths"] if r["raw_paths"] else "none (loads at startup)"
            lines.append(f"- `{r['path']}`{r['link_note']} — paths: {line_excerpt(paths_text, 300)}")
    else:
        lines.append("- none")
    lines.append("")

    touched = touched_files(combined_records, project_dir)

    lines.append("### CLAUDE.md files")
    claude_files = claude_md_files_for(touched, project_dir, config_dir)
    if claude_files:
        for cf in claude_files:
            lines.append(f"- `{cf['path']}` ({cf['location']})")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("### Touched files")
    if touched:
        for t in touched:
            lines.append(f"- `{t['real']}` via {t['how']}{subagent_suffix(t.get('subagent'))}")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("### Bash commands")
    bash_cmds = bash_commands_list(combined_records)
    if bash_cmds:
        for b in bash_cmds:
            lines.append(f"- {fmt_dt(parse_ts(b['timestamp']))}: `{line_excerpt(b['command'], 200)}`{subagent_suffix(b.get('subagent'))}")
    else:
        lines.append("- none")
    lines.append("")

    return lines


# Whole-message harness tags: a `type:"user"` string record made up only of
# one of these blocks is injected by the harness, not typed by a person.
_HARNESS_ONLY_TAGS = (
    "task-notification",
    "system-reminder",
    "local-command-stdout",
    "local-command-stderr",
)
_HARNESS_TAG_RES = [
    re.compile(rf"^<{tag}>.*</{tag}>$", re.S) for tag in _HARNESS_ONLY_TAGS
]
_COMMAND_MARKUP_RE = re.compile(
    r"<command-(?:message|name|args)>.*?</command-(?:message|name|args)>", re.S
)
_COMMAND_MARKUP_PRESENT_RE = re.compile(r"<command-(?:message|name|args)>")

# The harness appends one of these fixed sentences after an AskUserQuestion
# answer; they are boilerplate, not part of what the user said.
_ASKUSERQUESTION_BOILERPLATE_RES = [
    re.compile(r"\s*Read the answers carefully\b.*?actually say\.?\s*$", re.S),
    re.compile(r"\s*You can now continue with these answers in mind\.?\s*$", re.S),
]


def is_harness_injected_message(record, content):
    """True for a `type:"user"` string-content record that is harness
    plumbing rather than something a person typed: a record whose
    `origin.kind` is set to something other than "human" (task
    notifications, peer-session messages, ...), or whose entire text is one
    of the harness tag blocks, or pure slash-command markup with no other
    text."""
    origin = record.get("origin")
    origin_kind = origin.get("kind") if isinstance(origin, dict) else None
    if origin_kind is not None and origin_kind != "human":
        return True
    text = content.strip()
    if not text:
        return False
    for pat in _HARNESS_TAG_RES:
        if pat.match(text):
            return True
    if _COMMAND_MARKUP_PRESENT_RE.search(text):
        if _COMMAND_MARKUP_RE.sub("", text).strip() == "":
            return True
    return False


def strip_askuserquestion_boilerplate(text):
    for pat in _ASKUSERQUESTION_BOILERPLATE_RES:
        text = pat.sub("", text)
    return text.strip()


def last_assistant_text(content):
    if not isinstance(content, list):
        return None
    texts = [
        c.get("text") for c in content
        if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str) and c.get("text")
    ]
    return texts[-1] if texts else None


def render_human_messages(records):
    lines = ["## Human messages", ""]
    tu_idx = tool_use_index(records)
    entries = []
    after_assistant = None
    # Assistant tool_use counts since the last entry was recorded (reset
    # each time one is), so consecutive human messages with nothing done
    # between them read "none" rather than looking like two separate
    # points needing a "redo" invented between them.
    tool_counts_since = {}

    def _record_entry(ts, label, text):
        nonlocal tool_counts_since
        entries.append((ts, label, text, after_assistant, tool_counts_since))
        tool_counts_since = {}

    for r in records:
        if not isinstance(r, dict):
            continue
        if r.get("type") == "assistant":
            content = message_content(r)
            text = last_assistant_text(content)
            if text:
                after_assistant = text
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "tool_use":
                        name = c.get("name")
                        if not isinstance(name, str) or not name:
                            name = "?"
                        tool_counts_since[name] = tool_counts_since.get(name, 0) + 1
            continue
        if r.get("type") != "user":
            continue
        if r.get("isMeta") or r.get("isCompactSummary"):
            continue
        origin = r.get("origin")
        origin_kind = origin.get("kind") if isinstance(origin, dict) else None
        has_tool_use_result = "toolUseResult" in r
        content = message_content(r)
        if isinstance(content, str):
            if is_harness_injected_message(r, content):
                continue
            _record_entry(r.get("timestamp"), "human", content)
        elif isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    tu = tool_use_lookup(tu_idx, c)
                    if tu.get("name") == "AskUserQuestion":
                        text = c.get("content")
                        if isinstance(text, str):
                            text = strip_askuserquestion_boilerplate(text)
                        _record_entry(r.get("timestamp"), "AskUserQuestion answer", text)
            if origin_kind == "human" or not has_tool_use_result:
                texts = [
                    c.get("text") for c in content
                    if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str) and c.get("text")
                ]
                joined = "\n".join(texts).strip()
                if joined:
                    _record_entry(r.get("timestamp"), "human", joined)
    if not entries:
        lines.append("- none recorded")
    else:
        for ts, label, text, prior_assistant, tool_counts in entries:
            lines.append(f"- {fmt_dt(parse_ts(ts))} ({label}): {line_excerpt(text, 500)}")
            if prior_assistant:
                lines.append(f"  after assistant: {line_excerpt(prior_assistant, 300)}")
            if tool_counts:
                summary = ", ".join(
                    f"{name}×{count}"
                    for name, count in sorted(tool_counts.items(), key=lambda kv: (-kv[1], kv[0]))
                )
            else:
                summary = "none"
            lines.append(f"  tool uses since previous human message: {summary}")
    lines.append("")
    return lines


def render_tool_errors(records):
    lines = ["## Tool errors", ""]
    tu_idx = tool_use_index(records)
    errors = []
    for r in records:
        if r.get("type") != "user":
            continue
        content = message_content(r)
        if not isinstance(content, list):
            continue
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("is_error"):
                tu = tool_use_lookup(tu_idx, c)
                errors.append((r.get("timestamp"), tu.get("name", "?"), c.get("content")))
    lines.append(f"- Total: {len(errors)}")
    for ts, name, content in errors[:20]:
        lines.append(f"  - {fmt_dt(parse_ts(ts))} {name}: {line_excerpt(content, 200)}")
    if len(errors) > 20:
        lines.append(f"  - … ({len(errors) - 20} more)")
    lines.append("")
    return lines


def render_not_obtained(records):
    lines = ["## Not obtained", ""]
    missing = [k for k in USED_RECORD_KINDS if not attachment_records(records, k)]
    if missing:
        for k in missing:
            lines.append(f"- {k}")
    else:
        lines.append("- none")
    lines.append("")
    return lines, missing


# ---------------------------------------------------------------------------
# Session rendering
# ---------------------------------------------------------------------------

def render_session(session_id, records, transcript_path, session_dir, project_dir, config_dir,
                    hook_entries, rules, prev_id, prev_records):
    subagent_records = load_subagent_records(session_dir, session_id)
    combined = records + subagent_records

    lines = [f"# Session {session_id}", ""]
    lines += render_overview(session_id, records, transcript_path)
    lines += render_drift(records, prev_id, prev_records)
    lines += render_loaded_instructions(records)
    lines += render_skills_and_commands(records)
    lines += render_tool_use(combined)
    hook_lines, errs, no_run = render_hooks(combined, hook_entries)
    lines += hook_lines
    lines += render_instruction_materials(combined, rules, project_dir, config_dir)
    lines += render_human_messages(records)
    lines += render_tool_errors(records)
    not_obtained_lines, missing = render_not_obtained(records)
    lines += not_obtained_lines

    facts = {
        "hook_errors": [single_line(f"{e.get('command') or e.get('hookName')}|{e.get('event')}") for e in errs],
        "hooks_no_run": [h["command"] for h in no_run],
    }
    return lines, facts


def render_cross_session(session_ids, per_session_facts):
    lines = ["# Cross-session", ""]
    lines.append("- Sessions: " + ", ".join(session_ids))
    lines.append("")

    fact_labels = {
        "hook_errors": "Hook error",
        "hooks_no_run": "Configured hooks with no run record",
    }
    agg = {}  # (category, key) -> set of session ids
    for sid, facts in per_session_facts.items():
        for cat, keys in facts.items():
            for k in keys:
                agg.setdefault((cat, k), set()).add(sid)

    repeated = {k: v for k, v in agg.items() if len(v) >= 2}
    if not repeated:
        lines.append("- no fact repeated across sessions")
        lines.append("")
        return lines

    for (cat, key), sids in sorted(repeated.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        ordered = [s for s in session_ids if s in sids]
        lines.append(
            f"- {fact_labels[cat]}: `{key}` — {len(ordered)}/{len(session_ids)} sessions ({', '.join(ordered)})"
        )
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def positive_int(s):
    try:
        v = int(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"--days must be a positive integer, got {s!r}")
    if v <= 0:
        raise argparse.ArgumentTypeError(f"--days must be a positive integer, got {s!r}")
    return v


def parse_args(argv):
    p = argparse.ArgumentParser(
        prog="collect_facts.py",
        description="Extract facts from Claude Code session transcripts for a retrospective.",
    )
    p.add_argument("--session", required=True, help="anchor session ID (matched literally)")
    p.add_argument("--days", type=positive_int, default=None, help="also cover sessions active in the last N days")
    p.add_argument("--config-dir", default=None, help="override the Claude config directory")
    return p.parse_args(argv)


def resolve_config_dir(args):
    if args.config_dir:
        return Path(args.config_dir).expanduser()
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".claude"


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)

    config_dir = resolve_config_dir(args)
    transcript_path = find_transcript(config_dir, args.session)
    if transcript_path is None:
        eprint(f"collect_facts.py: no transcript found for session {args.session} under {config_dir}")
        return 3

    anchor_records = load_jsonl(transcript_path)
    session_dir = transcript_path.parent
    recorded_cwd = first_string_field(anchor_records, "cwd")
    project_dir_raw = Path(recorded_cwd) if recorded_cwd else Path.cwd()
    project_dir = resolve_best_effort(project_dir_raw)  # compare touches against the real, symlink-resolved path

    # One lightweight pass over every sibling transcript: never loads a
    # sibling's full records just to learn its time span.
    index = build_session_index(session_dir)
    if args.session not in index:
        index[args.session] = {"path": transcript_path, "first": None, "last": None}
    anchor_first, anchor_last = session_span(anchor_records)
    index[args.session] = {"path": transcript_path, "first": anchor_first, "last": anchor_last}

    if args.days is not None:
        now = datetime.datetime.now(datetime.timezone.utc)
        window = datetime.timedelta(days=args.days)
        session_ids = [sid for sid, info in index.items() if info["last"] is not None and (now - info["last"]) <= window]
        if args.session not in session_ids:
            session_ids.append(args.session)
    else:
        session_ids = [args.session]

    # Each transcript is parsed in full at most once per run, and only for
    # a session that ends up analyzed (in scope, or needed as someone's
    # previous session) — never for the whole sibling set up front.
    records_cache = {args.session: anchor_records}

    def get_records(sid):
        if sid not in records_cache:
            path = index.get(sid, {}).get("path") or (session_dir / f"{sid}.jsonl")
            records_cache[sid] = load_jsonl(path) if path.is_file() else []
        return records_cache[sid]

    ordered_ids = sorted(
        session_ids,
        key=lambda sid: index.get(sid, {}).get("first") or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc),
    )

    settings_list = load_settings_files(config_dir, project_dir)
    hook_entries = extract_hook_entries(settings_list)
    rules = rules_list(config_dir, project_dir)

    out = []
    env_lines, _absent = render_environment(config_dir, project_dir)
    out += env_lines

    per_session_facts = {}
    for sid in ordered_ids:
        records = get_records(sid)
        first_ts = index.get(sid, {}).get("first")
        prev_id = previous_session_id(index, sid, first_ts)
        prev_records = get_records(prev_id) if prev_id else None
        path = index.get(sid, {}).get("path") or (session_dir / f"{sid}.jsonl")
        session_lines, facts = render_session(
            sid, records, path, session_dir, project_dir, config_dir,
            hook_entries, rules, prev_id, prev_records,
        )
        out += session_lines
        per_session_facts[sid] = facts

    if len(ordered_ids) > 1:
        out += render_cross_session(ordered_ids, per_session_facts)

    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
