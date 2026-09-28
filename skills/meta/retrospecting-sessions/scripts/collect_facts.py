#!/usr/bin/env python3
# collect_facts.py --session <id> [--days N] [--config-dir DIR]
#
# Reads one or more Claude Code session transcripts (JSONL under
# <config-dir>/projects/*/<session-id>.jsonl) plus the harness materials
# present in the running environment (settings.json, Rules, nested
# CLAUDE.md files) and prints plain facts as Markdown to stdout. It makes
# no judgments and writes nothing anywhere: no file is created or
# modified, on this machine or elsewhere.
#
# --session <id>   the anchor session; with no --days, the only session
#                   covered.
# --days N         also cover every session of the same project whose
#                   transcript's last record falls within the last N days.
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
import shlex
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

HOOK_ERROR_ATTACHMENT_TYPES = ("hook_non_blocking_error", "hook_blocking_error")


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


def parse_ts(s):
    if not s:
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
    except OSError:
        return Path(p)


# ---------------------------------------------------------------------------
# Transcript loading
# ---------------------------------------------------------------------------

def load_jsonl(path):
    records = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def session_span(records):
    parsed = [t for t in (parse_ts(r.get("timestamp")) for r in records) if t]
    if not parsed:
        return None, None
    return min(parsed), max(parsed)


def first_field(records, field):
    for r in records:
        v = r.get(field)
        if v:
            return v
    return None


def last_field(records, field):
    val = None
    for r in records:
        v = r.get(field)
        if v:
            val = v
    return val


def attachment_records(records, atype):
    out = []
    for r in records:
        if r.get("type") == "attachment":
            att = r.get("attachment")
            if isinstance(att, dict) and att.get("type") == atype:
                out.append(r)
    return out


def tool_use_index(records):
    """tool_use_id -> {"name": ..., "input": ...}"""
    idx = {}
    for r in records:
        if r.get("type") != "assistant":
            continue
        content = r.get("message", {}).get("content")
        if not isinstance(content, list):
            continue
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("id"):
                idx[c["id"]] = {"name": c.get("name"), "input": c.get("input", {}) or {}}
    return idx


# ---------------------------------------------------------------------------
# Session discovery
# ---------------------------------------------------------------------------

def find_transcript(config_dir, session_id):
    matches = sorted(config_dir.glob(f"projects/*/{session_id}.jsonl"))
    return matches[0] if matches else None


def discover_session_files(session_dir):
    return sorted(session_dir.glob("*.jsonl"))


def sessions_within_days(session_dir, days, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    ids = []
    for jf in discover_session_files(session_dir):
        records = load_jsonl(jf)
        _, last_ts = session_span(records)
        if last_ts is not None and (now - last_ts) <= datetime.timedelta(days=days):
            ids.append(jf.stem)
    return ids


def find_previous_session(session_dir, current_id, current_first_ts):
    if current_first_ts is None:
        return None
    candidates = []
    for jf in discover_session_files(session_dir):
        if jf.stem == current_id:
            continue
        records = load_jsonl(jf)
        _, last_ts = session_span(records)
        if last_ts is not None and last_ts < current_first_ts:
            candidates.append((last_ts, jf.stem, records))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    last_ts, sid, records = candidates[-1]
    return {"id": sid, "records": records, "last_ts": last_ts}


# ---------------------------------------------------------------------------
# Glob matching (paths: of a Rule) — custom, because fnmatch does not
# distinguish "*" from "**".
# ---------------------------------------------------------------------------

def expand_braces(pattern):
    m = re.search(r"\{([^{}]*)\}", pattern)
    if not m:
        return [pattern]
    before, after = pattern[: m.start()], pattern[m.end():]
    out = []
    for opt in m.group(1).split(","):
        out.extend(expand_braces(before + opt + after))
    return out


def glob_to_regex(pattern):
    i, n = 0, len(pattern)
    out = []
    while i < n:
        c = pattern[i]
        if c == "*":
            if pattern[i : i + 3] == "**/":
                out.append("(?:.*/)?")
                i += 3
                continue
            if pattern[i : i + 2] == "**":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
            i += 1
            continue
        if c == "?":
            out.append("[^/]")
            i += 1
            continue
        out.append(re.escape(c))
        i += 1
    return "^" + "".join(out) + "$"


def compile_patterns(raw_patterns):
    compiled = []
    for p in raw_patterns:
        for expanded in expand_braces(p):
            compiled.append(re.compile(glob_to_regex(expanded)))
    return compiled


def path_matches(relpath_posix, compiled_patterns):
    return any(c.match(relpath_posix) for c in compiled_patterns)


# ---------------------------------------------------------------------------
# Rule / nested CLAUDE.md discovery
# ---------------------------------------------------------------------------

def read_frontmatter(text):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    body = []
    i = 1
    while i < len(lines) and lines[i].strip() != "---":
        body.append(lines[i])
        i += 1
    meta = {}
    j = 0
    while j < len(body):
        line = body[j]
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if val == "":
                items = []
                k = j + 1
                while k < len(body):
                    im = re.match(r"^\s*-\s+(.*)$", body[k])
                    if not im:
                        break
                    items.append(im.group(1).strip())
                    k += 1
                if items:
                    meta[key] = items
                    j = k
                    continue
                meta[key] = val
            else:
                meta[key] = val
        j += 1
    return meta


def parse_paths_value(raw):
    if raw is None:
        return []
    if isinstance(raw, list):
        out = []
        for item in raw:
            out.extend(parse_paths_value(item))
        return out
    s = str(raw).strip()
    if not s:
        return []
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return [s[1:-1]]
    if s.startswith("[") and s.endswith("]"):
        try:
            data = json.loads(s)
            if isinstance(data, list):
                return [str(x) for x in data]
        except (json.JSONDecodeError, ValueError):
            pass
        inner = s[1:-1]
        return [p.strip().strip("\"'") for p in inner.split(",") if p.strip()]
    if "," in s:
        return [p.strip().strip("\"'") for p in s.split(",") if p.strip()]
    return [s]


def find_rule_files(rules_dir):
    if not rules_dir.is_dir():
        return []
    return sorted(rules_dir.rglob("*.md"))


def find_nested_claude_md(project_dir):
    result = []
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in VENDOR_DIR_NAMES and not d.startswith(".")]
        rootp = Path(root)
        if rootp == project_dir:
            continue
        if "CLAUDE.md" in files:
            result.append(rootp / "CLAUDE.md")
    return sorted(result)


def materials_list(config_dir, project_dir):
    materials = []
    for rules_dir in (config_dir / "rules", project_dir / ".claude" / "rules"):
        for f in find_rule_files(rules_dir):
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            meta = read_frontmatter(text)
            patterns = parse_paths_value(meta.get("paths"))
            materials.append({
                "kind": "rule",
                "display": f,
                "path": resolve_best_effort(f),
                "patterns": patterns,
            })
    for f in find_nested_claude_md(project_dir):
        materials.append({
            "kind": "nested_claude",
            "display": f,
            "path": resolve_best_effort(f),
            "dir": resolve_best_effort(f.parent),
        })
    return materials


# ---------------------------------------------------------------------------
# Touched files (what the session read/edited/wrote or shelled into)
# ---------------------------------------------------------------------------

def resolve_relative(fp, project_dir):
    p = Path(fp)
    if not p.is_absolute():
        p = project_dir / p
    return resolve_best_effort(p)


def extract_path_tokens(cmd):
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        tokens = cmd.split()
    return [t for t in tokens if ("/" in t or "." in t) and not t.startswith("-")]


def resolve_existing(tok, project_dir):
    p = Path(tok)
    if not p.is_absolute():
        p = project_dir / p
    try:
        if p.exists():
            return resolve_best_effort(p)
    except OSError:
        pass
    return None


def touched_files(records, project_dir):
    touched = []
    for r in records:
        if r.get("type") != "assistant":
            continue
        content = r.get("message", {}).get("content")
        if not isinstance(content, list):
            continue
        for c in content:
            if not (isinstance(c, dict) and c.get("type") == "tool_use"):
                continue
            name = c.get("name")
            inp = c.get("input", {}) or {}
            if name in ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit"):
                fp = inp.get("file_path") or inp.get("notebook_path")
                if fp:
                    touched.append({
                        "real": resolve_relative(fp, project_dir),
                        "how": f"{name}",
                        "raw": fp,
                    })
            elif name == "Bash":
                cmd = inp.get("command", "")
                for tok in extract_path_tokens(cmd):
                    real = resolve_existing(tok, project_dir)
                    if real:
                        touched.append({
                            "real": real,
                            "how": f"Bash (`{trunc(cmd, 120)}`)",
                            "raw": tok,
                        })
    return touched


def load_record_paths(records):
    paths = set()
    for r in attachment_records(records, "nested_memory"):
        p = r["attachment"].get("path")
        if p:
            paths.add(resolve_best_effort(p))
    for r in attachment_records(records, "instructions"):
        for f in r["attachment"].get("files", []) or []:
            p = f.get("path")
            if p:
                paths.add(resolve_best_effort(p))
    return paths


def expected_not_loaded(records, materials, project_dir):
    loaded = load_record_paths(records)
    touched = touched_files(records, project_dir)
    findings = []
    for mat in materials:
        if mat["path"] in loaded:
            continue
        matches = []
        if mat["kind"] == "rule":
            if not mat["patterns"]:
                continue
            compiled = compile_patterns(mat["patterns"])
            for t in touched:
                try:
                    rel = t["real"].relative_to(project_dir).as_posix()
                except ValueError:
                    continue
                if path_matches(rel, compiled):
                    matches.append(t)
        else:
            dirstr = str(mat["dir"])
            for t in touched:
                ts = str(t["real"])
                if ts == dirstr or ts.startswith(dirstr + os.sep):
                    matches.append(t)
        if matches:
            findings.append({"material": mat, "touches": matches})
    return findings


# ---------------------------------------------------------------------------
# Bash write-command detection
# ---------------------------------------------------------------------------

_WRITE_TOKEN_RE = re.compile(
    r"\bsed\s+-i\b|\bperl\s+-i\b|\btee\b|\bmv\b|\bcp\b|\brm\b|\btouch\b"
)


def has_file_redirect(cmd):
    """True if `cmd` redirects output to a real file (`>`, `>>`, `&>`), as
    opposed to duplicating a file descriptor (`2>&1`, `>&2`) or discarding
    to /dev/null. A bare heredoc (`<<EOF`) is not itself a redirect: it only
    counts here when it appears alongside an actual `>`/`>>` target, e.g.
    `cat > out.txt <<EOF` or `cat <<EOF > out.txt`."""
    for m in re.finditer(r">{1,2}", cmd):
        rest = cmd[m.end():].lstrip()
        if rest.startswith("&") or rest.startswith("/dev/null"):
            continue
        return True
    return False


def is_write_command(cmd):
    if _WRITE_TOKEN_RE.search(cmd):
        return True
    return has_file_redirect(cmd)


def bash_write_commands(records):
    out = []
    for r in records:
        if r.get("type") != "assistant":
            continue
        content = r.get("message", {}).get("content")
        if not isinstance(content, list):
            continue
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "Bash":
                cmd = (c.get("input", {}) or {}).get("command", "")
                if cmd and is_write_command(cmd):
                    out.append({"command": cmd, "timestamp": r.get("timestamp")})
    return out


def tool_use_counts(records):
    counts = {}
    for r in records:
        if r.get("type") != "assistant":
            continue
        content = r.get("message", {}).get("content")
        if not isinstance(content, list):
            continue
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                name = c.get("name", "?")
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
                hooks_cfg = data.get("hooks", {}) or {}
            except (json.JSONDecodeError, OSError):
                hooks_cfg = {}
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
                matcher = m.get("matcher", "") or ""
                for h in m.get("hooks", []) or []:
                    if isinstance(h, dict) and h.get("type") == "command" and h.get("command"):
                        entries.append({
                            "event": event,
                            "matcher": matcher,
                            "command": h["command"],
                            "source": real,
                        })
    return entries


def matcher_covers_write_edit(matcher):
    if matcher in ("", "*", None):
        return True
    try:
        return any(re.search(matcher, name) for name in ("Write", "Edit", "MultiEdit"))
    except re.error:
        return False


def executed_hook_commands(records):
    cmds = set()
    for r in records:
        if r.get("type") == "attachment":
            att = r.get("attachment", {})
            if att.get("type") in ("hook_success",) + HOOK_ERROR_ATTACHMENT_TYPES:
                cmd = att.get("command")
                if cmd:
                    cmds.add(cmd)
        if r.get("type") == "system" and r.get("subtype") == "stop_hook_summary":
            for hi in r.get("hookInfos", []) or []:
                cmd = hi.get("command")
                if cmd:
                    cmds.add(cmd)
    return cmds


def hook_error_records(records):
    errs = []
    for r in records:
        if r.get("type") == "attachment":
            att = r.get("attachment", {})
            t = att.get("type")
            if t == "hook_non_blocking_error":
                errs.append({
                    "hookName": att.get("hookName"),
                    "command": att.get("command"),
                    "event": att.get("hookEvent"),
                    "text": att.get("stderr") or att.get("stdout") or "",
                })
            elif t == "hook_blocking_error":
                errs.append({
                    "hookName": att.get("hookName"),
                    "command": att.get("command"),
                    "event": att.get("hookEvent"),
                    "text": att.get("blockingError") or "",
                })
        if r.get("type") == "system" and r.get("subtype") == "stop_hook_summary":
            for he in r.get("hookErrors", []) or []:
                if isinstance(he, dict):
                    errs.append({
                        "hookName": he.get("hookName") or he.get("command"),
                        "command": he.get("command"),
                        "event": "Stop",
                        "text": he.get("stderr") or he.get("error") or json.dumps(he, ensure_ascii=False),
                    })
                else:
                    errs.append({"hookName": None, "command": None, "event": "Stop", "text": str(he)})
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


def render_overview(session_id, records, project_dir):
    first_ts, last_ts = session_span(records)
    cwd = first_field(records, "cwd")
    entrypoint = first_field(records, "entrypoint")
    lines = ["## Overview", ""]
    lines.append(f"- Session ID: {session_id}")
    lines.append(f"- Start: {fmt_dt(first_ts)}")
    lines.append(f"- End: {fmt_dt(last_ts)}")
    lines.append(f"- cwd: {cwd or 'unknown'}")
    if entrypoint:
        lines.append(f"- Entrypoint: {entrypoint}")
    # version transitions
    versions = []
    prev = None
    for r in records:
        v = r.get("version")
        if v and v != prev:
            versions.append((r.get("timestamp"), v))
            prev = v
    if versions:
        lines.append("- Versions:")
        for ts, v in versions:
            lines.append(f"  - {v} (first seen {fmt_dt(parse_ts(ts))})")
    else:
        lines.append("- Versions: none recorded")
    # auto_mode events
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


def render_drift(records, session_dir, session_id):
    first_ts, _ = session_span(records)
    prev = find_previous_session(session_dir, session_id, first_ts)
    lines = ["## Drift vs previous session", ""]
    if prev is None:
        lines.append("no previous session transcript")
        lines.append("")
        return lines
    prev_records = prev["records"]
    lines.append(f"- Previous session: {prev['id']}")

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
        for f in r["attachment"].get("files", []) or []:
            entries.append((r.get("timestamp"), "instructions", f.get("type", "?"), f.get("path")))
    for r in attachment_records(records, "nested_memory"):
        entries.append((r.get("timestamp"), "nested_memory", "-", r["attachment"].get("path")))
    entries.sort(key=lambda e: e[0] or "")
    if not entries:
        lines.append("- none recorded")
    else:
        for ts, kind, ftype, path in entries:
            lines.append(f"- {fmt_dt(parse_ts(ts))}: {kind} ({ftype}) `{path}`")
    lines.append("")
    return lines


def render_skills_and_commands(records):
    lines = ["## Skills and commands", ""]
    any_found = False
    for r in attachment_records(records, "invoked_skills"):
        for s in r["attachment"].get("skills", []) or []:
            any_found = True
            lines.append(f"- {fmt_dt(parse_ts(r.get('timestamp')))}: invoked_skills `{s.get('name')}` (`{s.get('path')}`)")
    for r in records:
        if r.get("type") != "assistant":
            continue
        content = r.get("message", {}).get("content")
        if not isinstance(content, list):
            continue
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "Skill":
                any_found = True
                inp = c.get("input", {}) or {}
                lines.append(f"- {fmt_dt(parse_ts(r.get('timestamp')))}: Skill tool_use `{inp.get('skill')}` args={json.dumps(inp.get('args', ''), ensure_ascii=False)}")
    for r in records:
        if r.get("type") != "user":
            continue
        content = r.get("message", {}).get("content")
        if not isinstance(content, str):
            continue
        for m in re.finditer(r"<command-name>([^<]*)</command-name>", content):
            any_found = True
            lines.append(f"- {fmt_dt(parse_ts(r.get('timestamp')))}: slash command `{m.group(1).strip()}`")
    if not any_found:
        lines.append("- none recorded")
    lines.append("")
    return lines


def render_tool_use(records):
    lines = ["## Tool use", ""]
    counts = tool_use_counts(records)
    if counts:
        for name in sorted(counts, key=lambda n: (-counts[n], n)):
            lines.append(f"- {name}: {counts[name]}")
    else:
        lines.append("- no tool calls recorded")
    writes = bash_write_commands(records)
    lines.append(f"- Bash write commands: {len(writes)}")
    for w in writes[:20]:
        lines.append(f"  - {fmt_dt(parse_ts(w['timestamp']))}: `{trunc(w['command'], 200)}`")
    if len(writes) > 20:
        lines.append(f"  - … ({len(writes) - 20} more)")
    lines.append("")
    return lines, writes


def render_hooks(records, hook_entries, bash_writes):
    lines = ["## Hooks", ""]
    lines.append("### Configured hooks")
    if hook_entries:
        for h in hook_entries:
            lines.append(f"- {h['event']} matcher=`{h['matcher'] or '(empty)'}` command=`{h['command']}` (`{h['source']}`)")
    else:
        lines.append("- none configured")

    executed = executed_hook_commands(records)

    lines.append("")
    lines.append("### Hooks bypassed by Bash edits")
    bypassed = []
    if bash_writes:
        for h in hook_entries:
            if h["event"] in ("PreToolUse", "PostToolUse") and matcher_covers_write_edit(h["matcher"]):
                bypassed.append(h)
    if bypassed:
        for h in bypassed:
            lines.append(
                f"- Hooks bypassed by Bash edits: command=`{h['command']}` "
                f"(event={h['event']}, matcher=`{h['matcher'] or '(empty)'}`) — "
                f"{len(bash_writes)} Bash write command(s) in this session"
            )
    else:
        lines.append("- none")

    lines.append("")
    lines.append("### Hook errors")
    errs = hook_error_records(records)
    if errs:
        for e in errs:
            label = e.get("command") or e.get("hookName") or "(unknown hook)"
            lines.append(f"- Hook error: `{label}` (event={e.get('event')}) — stderr: \"{trunc(e.get('text', ''), 300)}\"")
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
    return lines, bypassed, errs, no_run


def render_instruction_coverage(records, materials, project_dir):
    lines = ["## Instruction coverage", ""]
    findings = expected_not_loaded(records, materials, project_dir)
    if not materials:
        lines.append("- no Rules or nested CLAUDE.md found")
    else:
        for mat in materials:
            kind = "Rule" if mat["kind"] == "rule" else "nested CLAUDE.md"
            lines.append(f"- {kind}: `{mat['path']}`")
    lines.append("")
    lines.append("### Expected but not loaded")
    if findings:
        for f in findings:
            mat = f["material"]
            kind = "Rule" if mat["kind"] == "rule" else "nested CLAUDE.md"
            lines.append(f"- {kind} `{mat['path']}`: expected but not loaded")
            for t in f["touches"]:
                lines.append(f"  - touched: `{t['raw']}` via {t['how']}")
    else:
        lines.append("- none")
    lines.append("")
    return lines, findings


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
    re.compile(
        r"\s*Read the answers carefully\b.*?actually say\.?\s*$", re.S
    ),
    re.compile(
        r"\s*You can now continue with these answers in mind\.?\s*$", re.S
    ),
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


def render_human_messages(records):
    lines = ["## Human messages", ""]
    tu_idx = tool_use_index(records)
    entries = []
    for r in records:
        if r.get("type") != "user":
            continue
        if r.get("isMeta") or r.get("isCompactSummary"):
            continue
        content = r.get("message", {}).get("content")
        if isinstance(content, str) and "toolUseResult" not in r:
            if is_harness_injected_message(r, content):
                continue
            entries.append((r.get("timestamp"), "human", content))
        elif isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    tu = tu_idx.get(c.get("tool_use_id"), {})
                    if tu.get("name") == "AskUserQuestion":
                        text = c.get("content")
                        if isinstance(text, str):
                            text = strip_askuserquestion_boilerplate(text)
                        entries.append((r.get("timestamp"), "AskUserQuestion answer", text))
    if not entries:
        lines.append("- none recorded")
    else:
        for ts, label, text in entries:
            lines.append(f"- {fmt_dt(parse_ts(ts))} ({label}): {trunc(text, 500)}")
    lines.append("")
    return lines


def render_tool_errors(records):
    lines = ["## Tool errors", ""]
    tu_idx = tool_use_index(records)
    errors = []
    for r in records:
        if r.get("type") != "user":
            continue
        content = r.get("message", {}).get("content")
        if not isinstance(content, list):
            continue
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("is_error"):
                tu = tu_idx.get(c.get("tool_use_id"), {})
                errors.append((r.get("timestamp"), tu.get("name", "?"), c.get("content")))
    lines.append(f"- Total: {len(errors)}")
    for ts, name, content in errors[:20]:
        lines.append(f"  - {fmt_dt(parse_ts(ts))} {name}: {trunc(content, 200)}")
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

def render_session(session_id, records, session_dir, project_dir, hook_entries, materials):
    lines = [f"# Session {session_id}", ""]
    lines += render_overview(session_id, records, project_dir)
    lines += render_drift(records, session_dir, session_id)
    lines += render_loaded_instructions(records)
    lines += render_skills_and_commands(records)
    tool_lines, bash_writes = render_tool_use(records)
    lines += tool_lines
    hook_lines, bypassed, errs, no_run = render_hooks(records, hook_entries, bash_writes)
    lines += hook_lines
    cov_lines, findings = render_instruction_coverage(records, materials, project_dir)
    lines += cov_lines
    lines += render_human_messages(records)
    lines += render_tool_errors(records)
    not_obtained_lines, missing = render_not_obtained(records)
    lines += not_obtained_lines

    facts = {
        "expected_not_loaded": [str(f["material"]["path"]) for f in findings],
        "hooks_bypassed": [b["command"] for b in bypassed],
        "hook_errors": [f"{e.get('command') or e.get('hookName')}|{trunc(e.get('text',''), 60)}" for e in errs],
        "hooks_no_run": [h["command"] for h in no_run],
    }
    return lines, facts


def render_cross_session(session_ids, per_session_facts):
    lines = ["# Cross-session", ""]
    lines.append("- Sessions: " + ", ".join(session_ids))
    lines.append("")

    fact_labels = {
        "expected_not_loaded": "Expected but not loaded",
        "hooks_bypassed": "Hooks bypassed by Bash edits",
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

def parse_args(argv):
    p = argparse.ArgumentParser(
        prog="collect_facts.py",
        description="Extract facts from Claude Code session transcripts for a retrospective.",
    )
    p.add_argument("--session", required=True, help="anchor session ID")
    p.add_argument("--days", type=int, default=None, help="also cover sessions active in the last N days")
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
    project_dir = first_field(anchor_records, "cwd")
    project_dir = Path(project_dir) if project_dir else Path.cwd()

    if args.days is not None:
        session_ids = sessions_within_days(session_dir, args.days)
    else:
        session_ids = [args.session]

    # Load records for every session in scope, keyed by id, sorted by start time.
    sessions = {}
    for sid in session_ids:
        path = session_dir / f"{sid}.jsonl"
        if sid == args.session:
            records = anchor_records
        elif path.is_file():
            records = load_jsonl(path)
        else:
            continue
        sessions[sid] = records
    if args.session not in sessions:
        sessions[args.session] = anchor_records

    ordered_ids = sorted(sessions, key=lambda sid: (session_span(sessions[sid])[0] or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)))

    settings_list = load_settings_files(config_dir, project_dir)
    hook_entries = extract_hook_entries(settings_list)
    materials = materials_list(config_dir, project_dir)

    out = []
    env_lines, _absent = render_environment(config_dir, project_dir)
    out += env_lines

    per_session_facts = {}
    for sid in ordered_ids:
        session_lines, facts = render_session(sid, sessions[sid], session_dir, project_dir, hook_entries, materials)
        out += session_lines
        per_session_facts[sid] = facts

    if len(ordered_ids) > 1:
        out += render_cross_session(ordered_ids, per_session_facts)

    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
