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
    fact (counts, Bash writes, touched files, Skill calls) is built on."""
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
# Glob / gitignore-style matching (paths: of a Rule)
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


def split_top_level(s, sep=","):
    """Split on `sep`, but never inside a {brace} group."""
    parts = []
    depth = 0
    cur = []
    for ch in s:
        if ch == "{":
            depth += 1
            cur.append(ch)
        elif ch == "}":
            depth = max(0, depth - 1)
            cur.append(ch)
        elif ch == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


def strip_trailing_comment(s):
    """Drop a ` # comment` that starts outside any quoted span (so a `#`
    that is part of quoted pattern text, or that sits before a quote's own
    closing character, is never mistaken for one)."""
    in_quote = None
    for i, ch in enumerate(s):
        if in_quote:
            if ch == in_quote:
                in_quote = None
            continue
        if ch in ("'", '"'):
            in_quote = ch
            continue
        if ch == "#" and (i == 0 or s[i - 1].isspace()):
            return s[:i].rstrip()
    return s


def clean_path_item(raw):
    """One `paths:` entry: a quoted entry (`"a/**"  # c`, `'a/**' # c`)
    keeps only its quoted content, discarding anything — comment or not —
    after the closing quote; an unquoted entry has a trailing ` #
    comment` stripped. Either way, a trailing `/**` is then dropped."""
    s = raw.strip()
    if not s:
        return None
    if s[0] in ('"', "'"):
        quote = s[0]
        end = s.find(quote, 1)
        if end != -1:
            s = s[1:end]
    else:
        s = strip_trailing_comment(s)
    s = s.strip()
    if s.endswith("/**"):
        s = s[:-3]
    return s or None


def parse_paths_value(raw):
    """A Rule's `paths:` frontmatter value into glob patterns: a YAML list
    (items unquoted or quoted) or a comma-separated string (commas inside
    {brace} groups do not split), each cleaned via clean_path_item()."""
    if raw is None:
        return []
    if isinstance(raw, list):
        out = []
        for item in raw:
            out.extend(parse_paths_value(item))
        return out
    s = strip_trailing_comment(str(raw).strip())
    if not s:
        return []
    if s.startswith("[") and s.endswith("]"):
        try:
            data = json.loads(s)
        except (json.JSONDecodeError, ValueError):
            data = None
        if isinstance(data, list):
            out = []
            for item in data:
                cleaned = clean_path_item(str(item))
                if cleaned:
                    out.append(cleaned)
            return out
        s = s[1:-1]
    elif len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        # The whole value is one quoted scalar (`paths: "a/**, b/**"`):
        # strip its outer quotes before splitting, so an embedded comma
        # list survives instead of leaving stray quote characters behind.
        s = s[1:-1]
    out = []
    for part in split_top_level(s, ","):
        cleaned = clean_path_item(part)
        if cleaned:
            out.append(cleaned)
    return out


def glob_core_regex(pattern):
    """Translate one glob segment string (no surrounding ^…$) to regex
    source, supporting `**`, `*`, `?` and `[...]` character classes."""
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
        if c == "[":
            j = i + 1
            neg = False
            if j < n and pattern[j] in "!^":
                neg = True
                j += 1
            start_content = j
            if j < n and pattern[j] == "]":
                j += 1
            while j < n and pattern[j] != "]":
                j += 1
            if j >= n:
                out.append(re.escape(c))
                i += 1
                continue
            content = pattern[start_content:j].replace("\\", "\\\\")
            out.append("[" + ("^" if neg else "") + content + "]")
            i = j + 1
            continue
        out.append(re.escape(c))
        i += 1
    return "".join(out)


def pattern_to_regex(pattern):
    """gitignore-style semantics: a pattern without a slash matches at any
    depth; a bare literal name (no wildcard) also matches everything below
    it, like a directory; a leading `/` anchors to the project root."""
    anchored = pattern.startswith("/")
    core = pattern[1:] if anchored else pattern
    is_dir_pattern = core.endswith("/")
    if is_dir_pattern:
        core = core[:-1]
    literal_no_wildcards = not any(ch in core for ch in "*?[")
    body_has_slash = "/" in core
    prefix = "" if (anchored or body_has_slash) else "(?:.*/)?"
    core_regex = glob_core_regex(core)
    if literal_no_wildcards or is_dir_pattern:
        return f"^{prefix}{core_regex}(?:/.*)?$"
    return f"^{prefix}{core_regex}$"


def compile_patterns(raw_patterns):
    compiled = []
    for p in raw_patterns:
        for expanded in expand_braces(p):
            try:
                compiled.append(re.compile(pattern_to_regex(expanded)))
            except re.error:
                continue
    return compiled


def path_matches(relpath_posix, compiled_patterns):
    return any(c.match(relpath_posix) for c in compiled_patterns)


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
                    stripped = body[k].strip()
                    if stripped == "" or stripped.startswith("#"):
                        k += 1
                        continue
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


def resolve_existing(tok, base_dir):
    p = Path(tok)
    if not p.is_absolute():
        p = base_dir / p
    try:
        if p.exists():
            return resolve_best_effort(p)
    except OSError:
        pass
    return None


def _parse_leading_cd_target(cmd):
    """The directory argument of a leading `cd <dir> &&`/`cd <dir> ;`,
    handling a quoted directory name (`cd "my dir" && ...`), or None."""
    m = re.match(r"^\s*cd\s+", cmd)
    if not m:
        return None
    rest = cmd[m.end():]
    if rest[:1] in ("'", '"'):
        quote = rest[0]
        end = rest.find(quote, 1)
        if end == -1:
            return None
        target = rest[1:end]
        after = rest[end + 1 :].lstrip()
    else:
        # Stop at whitespace or a separator glued directly onto the
        # target with no space (`cd dir;cmd`, `cd dir&&cmd`).
        mm = re.match(r"([^\s;&|]+)", rest)
        if not mm:
            return None
        target = mm.group(1)
        after = rest[mm.end() :].lstrip()
    if not (after.startswith("&&") or after.startswith(";")):
        return None
    return target


def bash_effective_base_dir(cmd, project_dir):
    """The directory a Bash command's relative paths resolve against: the
    project dir, unless the command starts with `cd <dir> &&`/`cd <dir> ;`
    (dir absolute, `~`-expanded, quoted, or itself relative to the
    project dir), in which case it is that target."""
    target = _parse_leading_cd_target(cmd)
    if target is None:
        return project_dir
    target = os.path.expanduser(target)
    p = Path(target)
    if not p.is_absolute():
        p = project_dir / p
    return p


def touched_files(records, project_dir):
    touched = []
    for r, c in iter_tool_uses(records):
        name = c.get("name")
        inp = tool_input(c)
        subagent = r.get("_subagent")
        if name in ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit"):
            fp = inp.get("file_path") or inp.get("notebook_path")
            if isinstance(fp, str) and fp:
                touched.append({
                    "real": resolve_relative(fp, project_dir),
                    "how": f"{name}",
                    "raw": fp,
                    "subagent": subagent,
                })
        elif name == "Bash":
            cmd = inp.get("command")
            if not isinstance(cmd, str):
                continue
            base_dir = bash_effective_base_dir(cmd, project_dir)
            for tok in extract_path_tokens(cmd):
                real = resolve_existing(tok, base_dir)
                if real:
                    touched.append({
                        "real": real,
                        "how": f"Bash (`{line_excerpt(cmd, 120)}`)",
                        "raw": tok,
                        "subagent": subagent,
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


def external_claude_md_materials(touched, project_dir, config_dir):
    """Nested-CLAUDE.md-style materials for touched files that fall
    outside project_dir (already resolved): walk each one's directory
    chain up to (not including) the user's home directory or the
    filesystem root, skipping the config dir's own CLAUDE.md (user
    memory, not a project material)."""
    config_claude_md = resolve_best_effort(config_dir / "CLAUDE.md")
    stop_dirs = {resolve_best_effort(Path.home()), Path(project_dir.anchor)}
    seen_paths = set()
    materials = []
    for t in touched:
        real = t["real"]
        try:
            real.relative_to(project_dir)
            continue  # inside the project dir; handled by materials_list()
        except ValueError:
            pass
        for cand in claude_md_up_from(real.parent, stop_dirs):
            if cand == config_claude_md or cand in seen_paths:
                continue
            seen_paths.add(cand)
            materials.append({
                "kind": "nested_claude",
                "display": cand,
                "path": cand,
                "dir": cand.parent,
                "outside_project": True,
            })
    return materials


def load_record_paths(records):
    paths = set()
    for r in attachment_records(records, "nested_memory"):
        p = r["attachment"].get("path")
        if isinstance(p, str) and p:
            paths.add(resolve_best_effort(p))
    for r in attachment_records(records, "instructions"):
        files = r["attachment"].get("files")
        if not isinstance(files, list):
            continue
        for f in files:
            if not isinstance(f, dict):
                continue
            p = f.get("path")
            if isinstance(p, str) and p:
                paths.add(resolve_best_effort(p))
    return paths


def expected_not_loaded(main_records, combined_records, materials, project_dir, config_dir):
    """main_records decides what was loaded (instructions/nested_memory);
    combined_records (main session + any subagents) decides what was
    touched — project_dir must already be resolved (item 9)."""
    loaded = load_record_paths(main_records)
    touched = touched_files(combined_records, project_dir)
    all_materials = materials + external_claude_md_materials(touched, project_dir, config_dir)
    findings = []
    for mat in all_materials:
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
# Bash write-command detection — counts only commands that create or
# modify file *contents*: redirects to a file, tee, sed/perl in-place
# edits, heredocs redirected to a file, cp/mv targets, touch. Ignores `>`
# and command-name-shaped words inside quotes or heredoc bodies.
# ---------------------------------------------------------------------------

_HEREDOC_START_RE = re.compile(r"<<-?~?\s*(['\"]?)(\w+)\1")
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||[|;\n]")


def strip_heredoc_bodies(cmd):
    """Remove heredoc body lines (and the closing delimiter line), keeping
    the initiating line (which may itself carry a `>` redirect target)."""
    lines = cmd.split("\n")
    out = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        out.append(line)
        m = _HEREDOC_START_RE.search(line)
        if m:
            delim = m.group(2)
            i += 1
            while i < n and lines[i].strip() != delim:
                i += 1
            if i < n:
                i += 1  # skip the delimiter line itself
            continue
        i += 1
    return "\n".join(out)


def mask_quotes(s):
    """Replace the interior of every quoted string with 'x's, keeping the
    quote characters, so a later scan for `>`/command names never matches
    inside quoted text (`awk '$1 > 5'`, `grep -n 'touch' f`)."""
    out = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c in ("'", '"'):
            quote = c
            out.append(c)
            i += 1
            start = i
            while i < n and s[i] != quote:
                if quote == '"' and s[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                i += 1
            out.append("x" * (i - start))
            if i < n:
                out.append(s[i])
                i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def has_file_redirect(cmd):
    """True if `cmd` redirects output to a real file (`>`, `>>`, `&>`), as
    opposed to duplicating a file descriptor (`2>&1`, `>&2`) or discarding
    to /dev/null."""
    for m in re.finditer(r">{1,2}", cmd):
        rest = cmd[m.end():].lstrip()
        if rest.startswith("&") or rest.startswith("/dev/null"):
            continue
        return True
    return False


def _segment_tokens(segment):
    try:
        return shlex.split(segment)
    except ValueError:
        return segment.split()


# Combinable short-flag clusters that legitimately include `i`: sed's
# -Ei/-ni, perl's -pi/-pie. A flag using an unrelated letter that happens
# to spell "i" as a *substring of its own attached argument* (perl's -I<dir>,
# -M<module>) must never match — that argument is not a flag cluster.
_SED_CLUSTER_CHARS = set("Eni")
_PERL_CLUSTER_CHARS = set("pnie")

# Tokens that introduce the real command rather than being one themselves;
# the search for a write-shaped program name continues past them. `env`
# and `xargs` additionally swallow their own following assignments/flags.
_WRAPPER_KEYWORDS = {
    "do", "then", "else", "elif", "if", "while", "until",
    "sudo", "time", "nohup", "command", "exec",
}


def _has_inplace_flag(tokens, prog):
    """sed: -i, -i.bak, --in-place, --in-place=..., or a short-flag
    cluster made *only* of E/n/i (e.g. -Ei, -ni). perl: -i, -i.bak, or a
    cluster made only of p/n/i/e (-pi, -pie). A cluster containing any
    other letter (perl's -Ilib, -MList::Util=sum) is a different flag
    with an attached argument, not an in-place toggle."""
    allowed = _SED_CLUSTER_CHARS if prog == "sed" else _PERL_CLUSTER_CHARS
    for t in tokens:
        if not t.startswith("-"):
            continue
        if t.startswith("--"):
            if t == "--in-place" or t.startswith("--in-place="):
                return True
            continue
        core = t[1:].split(".", 1)[0]
        if core and "i" in core and all(ch in allowed for ch in core):
            return True
    return False


def _skip_leading_wrappers(tokens):
    """Index of the first token that is the actual command name, skipping
    a leading run of shell keywords/prefixes (`do`, `sudo`, `time`, ...),
    plain VAR=value assignments, and `env`/`xargs`'s own flags/assignments
    (`env FOO=1 cp a b`, `xargs -n1 sed -i ...`)."""
    idx, n = 0, len(tokens)
    while idx < n:
        t = tokens[idx]
        if _ENV_ASSIGN_RE.match(t):
            idx += 1
            continue
        if t in _WRAPPER_KEYWORDS:
            idx += 1
            continue
        if t in ("env", "xargs"):
            idx += 1
            while idx < n and (tokens[idx].startswith("-") or _ENV_ASSIGN_RE.match(tokens[idx])):
                idx += 1
            continue
        break
    return idx


def _is_write_prog(prog, rest):
    if prog in ("tee", "touch", "cp", "mv"):
        return True
    if prog in ("sed", "perl") and _has_inplace_flag(rest, prog):
        return True
    return False


def _find_exec_is_write(cleaned):
    """`find ... -exec <command> {} +`/`\\;`: the exec'd command is what
    matters, not `find` itself. Tokenized once over the whole (cleaned)
    command so an escaped `\\;` terminator (which shlex unescapes to a
    plain `;` token) is never mistaken for a shell command separator."""
    try:
        tokens = shlex.split(cleaned)
    except ValueError:
        return False
    n = len(tokens)
    for i, t in enumerate(tokens):
        if t != "-exec":
            continue
        j = i + 1
        sub = []
        while j < n and tokens[j] not in ("+", ";"):
            sub.append(tokens[j])
            j += 1
        if not sub:
            continue
        if _is_write_prog(os.path.basename(sub[0]), sub[1:]):
            return True
    return False


def is_write_command(cmd):
    if not isinstance(cmd, str) or not cmd:
        return False
    cleaned = mask_quotes(strip_heredoc_bodies(cmd))
    if has_file_redirect(cleaned):
        return True
    if _find_exec_is_write(cleaned):
        return True
    for seg in _SEGMENT_SPLIT_RE.split(cleaned):
        tokens = _segment_tokens(seg)
        idx = _skip_leading_wrappers(tokens)
        if idx >= len(tokens):
            continue
        prog = os.path.basename(tokens[idx])
        rest = tokens[idx + 1 :]
        if _is_write_prog(prog, rest):
            return True
    return False


def bash_write_commands(records):
    out = []
    for r, c in iter_tool_uses(records):
        if c.get("name") != "Bash":
            continue
        cmd = tool_input(c).get("command")
        if isinstance(cmd, str) and cmd and is_write_command(cmd):
            out.append({
                "command": cmd,
                "timestamp": r.get("timestamp"),
                "subagent": r.get("_subagent"),
            })
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


def matcher_covers_write_edit(matcher):
    if matcher in ("", "*", None):
        return True
    try:
        return any(re.search(matcher, name) for name in ("Write", "Edit", "MultiEdit"))
    except re.error:
        return False


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
    writes = bash_write_commands(combined_records)
    lines.append(f"- Bash write commands: {len(writes)}")
    for w in writes[:20]:
        lines.append(f"  - {fmt_dt(parse_ts(w['timestamp']))}: `{line_excerpt(w['command'], 200)}`{subagent_suffix(w.get('subagent'))}")
    if len(writes) > 20:
        lines.append(f"  - … ({len(writes) - 20} more)")
    lines.append("")
    return lines, writes


def render_hooks(combined_records, hook_entries, bash_writes):
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
    lines.append("### Hooks bypassed by Bash edits")
    bypassed = []
    if bash_writes:
        for h in hook_entries:
            if h["event"] not in ("PreToolUse", "PostToolUse") or not matcher_covers_write_edit(h["matcher"]):
                continue
            if h["matcher"] in ("", "*", None) and h["command"] in executed:
                # An unrestricted matcher also covers Bash itself: a run
                # record means it fired, so nothing was bypassed.
                continue
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
    return lines, bypassed, errs, no_run


def render_instruction_coverage(records, combined_records, materials, project_dir, config_dir):
    lines = ["## Instruction coverage", ""]
    findings = expected_not_loaded(records, combined_records, materials, project_dir, config_dir)
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
            suffix = " (outside project dir)" if mat.get("outside_project") else ""
            lines.append(f"- {kind} `{mat['path']}`{suffix}: expected but not loaded")
            for t in f["touches"]:
                lines.append(f"  - touched: `{line_excerpt(t['raw'], 200)}` via {t['how']}{subagent_suffix(t.get('subagent'))}")
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
    for r in records:
        if not isinstance(r, dict):
            continue
        if r.get("type") == "assistant":
            text = last_assistant_text(message_content(r))
            if text:
                after_assistant = text
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
            entries.append((r.get("timestamp"), "human", content, after_assistant))
        elif isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    tu = tool_use_lookup(tu_idx, c)
                    if tu.get("name") == "AskUserQuestion":
                        text = c.get("content")
                        if isinstance(text, str):
                            text = strip_askuserquestion_boilerplate(text)
                        entries.append((r.get("timestamp"), "AskUserQuestion answer", text, after_assistant))
            if origin_kind == "human" or not has_tool_use_result:
                texts = [
                    c.get("text") for c in content
                    if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str) and c.get("text")
                ]
                joined = "\n".join(texts).strip()
                if joined:
                    entries.append((r.get("timestamp"), "human", joined, after_assistant))
    if not entries:
        lines.append("- none recorded")
    else:
        for ts, label, text, prior_assistant in entries:
            lines.append(f"- {fmt_dt(parse_ts(ts))} ({label}): {line_excerpt(text, 500)}")
            if prior_assistant:
                lines.append(f"  after assistant: {line_excerpt(prior_assistant, 300)}")
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
                    hook_entries, materials, prev_id, prev_records):
    subagent_records = load_subagent_records(session_dir, session_id)
    combined = records + subagent_records

    lines = [f"# Session {session_id}", ""]
    lines += render_overview(session_id, records, transcript_path)
    lines += render_drift(records, prev_id, prev_records)
    lines += render_loaded_instructions(records)
    lines += render_skills_and_commands(records)
    tool_lines, bash_writes = render_tool_use(combined)
    lines += tool_lines
    hook_lines, bypassed, errs, no_run = render_hooks(combined, hook_entries, bash_writes)
    lines += hook_lines
    cov_lines, findings = render_instruction_coverage(records, combined, materials, project_dir, config_dir)
    lines += cov_lines
    lines += render_human_messages(records)
    lines += render_tool_errors(records)
    not_obtained_lines, missing = render_not_obtained(records)
    lines += not_obtained_lines

    facts = {
        "expected_not_loaded": [str(f["material"]["path"]) for f in findings],
        "hooks_bypassed": [b["command"] for b in bypassed],
        "hook_errors": [single_line(f"{e.get('command') or e.get('hookName')}|{e.get('event')}") for e in errs],
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
    project_dir = resolve_best_effort(project_dir_raw)  # item 9: compare touches against the real path

    # One lightweight pass over every sibling transcript (item 14): never
    # loads a sibling's full records just to learn its time span.
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
    materials = materials_list(config_dir, project_dir)

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
            hook_entries, materials, prev_id, prev_records,
        )
        out += session_lines
        per_session_facts[sid] = facts

    if len(ordered_ids) > 1:
        out += render_cross_session(ordered_ids, per_session_facts)

    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
