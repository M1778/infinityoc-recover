#!/usr/bin/env python3
"""
infinityoc-recover — recover the full context of an OpenCode session in one shot.

Reads OpenCode's own storage (via `opencode session export`) and writes a compact
markdown transcript containing every user message, assistant text, reasoning and
tool call of the session. Follows child (subagent) sessions when present.

Usage:
    python3 recover.py <session-id-or-prefix> [more-ids...] [--out FILE]
                       [--max-output N] [--max-reasoning N]

    --out FILE         write everything into one file instead of per-session files
    --max-output N     cap each tool output at N chars (0 = unlimited, default)
    --max-reasoning N  cap each reasoning block at N chars (0 = unlimited, default)

Parts of the demoted session that were truncated when OpenCode stored them are
marked in the transcript; the raw export JSON is saved next to the transcript
for byte-perfect access.
"""

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SES_RE = re.compile(r"ses_[A-Za-z0-9]{10,}")
SKIP_PARTS = {"step-start", "step-finish", "snapshot"}
TRUNCATION_NOTE = "[this output had already been truncated when OpenCode stored it]"


# ---------------------------------------------------------------- paths / db

def data_dirs():
    home = Path.home()
    cands = [
        os.environ.get("OPENCODE_DATA_HOME"),
        os.environ.get("XDG_DATA_HOME") and Path(os.environ["XDG_DATA_HOME"]) / "opencode",
        home / ".local" / "share" / "opencode",
        home / "Library" / "Application Support" / "opencode",
        home / "AppData" / "Local" / "opencode",
        home / "AppData" / "Roaming" / "opencode",
    ]
    return [c for c in cands if c]


def find_db():
    for d in data_dirs():
        db = d / "opencode.db"
        if db.exists():
            return db
    return None


def open_db_ro(db):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


# ------------------------------------------------------------- id resolution

def list_all_sessions():
    """[(id, title, created_ms)], newest first — from db, falling back to CLI."""
    db = find_db()
    if db:
        try:
            con = open_db_ro(db)
            rows = con.execute(
                "SELECT id, title, time_created FROM session_v2 ORDER BY time_created DESC"
            ).fetchall()
            if rows:
                return [(r["id"], r["title"] or "", r["time_created"] or 0) for r in rows]
        except Exception:
            pass
    out = subprocess.run(
        ["opencode", "session", "list"], capture_output=True, text=True
    )
    if out.returncode != 0:
        die("cannot list sessions: `opencode session list` failed", out.stderr)
    rows = []
    for line in out.stdout.splitlines():
        parts = [p.strip() for p in line.split("\t")]
        if parts and parts[0].startswith("ses_"):
            title = parts[1] if len(parts) > 1 else ""
            created = 0
            for fmt in ("%m/%d/%Y, %I:%M:%S AM", "%m/%d/%Y, %I:%M:%S PM"):
                try:
                    created = datetime.strptime(parts[2], fmt).replace(
                        tzinfo=timezone.utc).timestamp() * 1000
                    break
                except Exception:
                    pass
            rows.append((parts[0], title, created))
    return rows


def fmt_date(ms):
    if not ms:
        return "?"
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def resolve_ids(args):
    sessions = list_all_sessions()
    ids = []
    for arg in args:
        if arg in {s[0] for s in sessions}:
            ids.append(arg)
            continue
        needle = arg[4:] if arg.startswith("ses_") else arg
        cands = [
            s for s in sessions
            if s[0][4:].startswith(needle) or s[0].endswith(needle) or needle in s[0][4:]
        ]
        if not cands:
            die(f"no session matches '{arg}' (searched {len(sessions)} sessions)")
        if len(cands) > 1:
            lines = "\n".join(
                f"  {c[0]}  {fmt_date(c[2])}  {c[1][:60]}" for c in cands[:10]
            )
            die(f"'{arg}' matches {len(cands)} sessions — be more specific:\n{lines}")
        ids.append(cands[0][0])
    seen, uniq = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            uniq.append(i)
    return uniq


def children_of(sid):
    db = find_db()
    if not db:
        return {}
    try:
        con = open_db_ro(db)
        rows = con.execute(
            "SELECT id FROM session_v2 WHERE parent_id = ?", (sid,)
        ).fetchall()
        return {r["id"] for r in rows}
    except Exception:
        return set()


# ------------------------------------------------------------------- export

def export_session(sid, outdir):
    raw = outdir / f"{sid}.json"
    # pipe stdout is capped at 256 KiB by the opencode CLI; a real file is not
    with open(raw, "wb") as fh:
        r = subprocess.run([opencode_bin(), "session", "export", sid],
                           stdout=fh, stderr=subprocess.PIPE)
    if r.returncode != 0 or raw.stat().st_size == 0:
        err = r.stderr.decode("utf-8", "replace").strip() or "empty export"
        return None, err
    try:
        return json.loads(raw.read_text(encoding="utf-8")), None
    except json.JSONDecodeError as e:
        return None, f"export is not valid JSON ({e})"


def opencode_bin():
    for name in ("opencode", "opencode.cmd", "opencode.exe"):
        path = shutil.which(name)
        if path:
            return path
    return "opencode"


def die(msg, detail=""):
    print(f"error: {msg}", file=sys.stderr)
    if detail:
        print(detail, file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------- rendering

def ts(ms):
    if not ms:
        return ""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def cap(text, limit, label):
    if limit and limit > 0 and len(text) > limit:
        return text[:limit] + f"\n[{label} cut at {limit}/{len(text)} chars — raise --max-output/--max-reasoning]"
    return text


def clean(obj, drop=("time", "native", "id", "snapshot")):
    if isinstance(obj, dict):
        return {k: clean(v, drop) if isinstance(v, (dict, list)) else v
                for k, v in obj.items() if k not in drop}
    if isinstance(obj, list):
        return [clean(i, drop) for i in obj]
    return obj


def render_message(m, opts, out):
    kind = m.get("type") or "?"
    who = {"user": "USER", "assistant": "ASSISTANT"}.get(kind, kind.upper())
    head = []
    if m.get("agent") and m.get("agent") != "build":
        head.append(m["agent"])
    head_line = f"## {who}" + (f" ({', '.join(head)})" if head else "")
    out.append(head_line)

    parts = m.get("content")
    if parts is None:
        text = m.get("text") or ""
        if text:
            out.append(text)
        if m.get("files"):
            out.append(f"[files attached: {json.dumps(m['files'], ensure_ascii=False)}]")
        if m.get("agents"):
            out.append(f"[agents: {json.dumps(m['agents'], ensure_ascii=False)}]")
        if not text and not m.get("files") and not m.get("agents"):
            out.append(json.dumps(clean(m), ensure_ascii=False))
        out.append("")
        return

    for p in parts:
        t = p.get("type")
        if t in SKIP_PARTS:
            continue
        if t == "text":
            txt = p.get("text") or p.get("content") or ""
            out.append(str(txt))
        elif t == "reasoning":
            txt = cap(str(p.get("text") or ""), opts.max_reasoning, "reasoning")
            if txt.strip():
                out.append("<thinking>")
                out.append(txt)
                out.append("</thinking>")
        elif t == "tool":
            st = p.get("state") or {}
            status = st.get("status") or p.get("status") or "?"
            out.append(f"**tool: {p.get('name') or p.get('tool') or '?'} ({status})**")
            inp = st.get("input") or {}
            if inp:
                out.append("```json")
                out.append(cap(json.dumps(inp, ensure_ascii=False,
                                          separators=(",", ":")), opts.max_output, "input"))
                out.append("```")
            blocks = st.get("content") or []
            texts = [b.get("text", "") for b in blocks if isinstance(b, dict)]
            body = "\n".join(x for x in texts if x)
            if body:
                out.append("```")
                out.append(cap(body, opts.max_output, "output"))
                out.append("```")
            meta = (p.get("state") or {}).get("metadata") or {}
            if meta.get("truncated"):
                out.append(TRUNCATION_NOTE)
        else:
            out.append(f"<part type={t}>")
            out.append(cap(json.dumps(clean(p), ensure_ascii=False), opts.max_output, "part"))
            out.append("</part>")
    out.append("")


def collect_child_hits(doc):
    """Map child session ids to the tool call that spawned them, in order."""
    hits = []
    seen = set()
    main = {doc.get("info", {}).get("id")}
    for m in doc.get("messages", []):
        parts = m.get("content") or []
        for p in parts:
            if p.get("type") != "tool":
                continue
            blob = json.dumps(p, ensure_ascii=False, default=str)
            found = SES_RE.findall(blob)
            if not found:
                continue
            call = f"{(p.get('name') or '?')} — {json.dumps((p.get('state') or {}).get('input') or {}, ensure_ascii=False)[:200]}"
            for sid in found:
                if sid in seen or sid in main:
                    continue
                seen.add(sid)
                hits.append((sid, call))
    return hits


def render_session(doc, opts):
    info = doc.get("info") or {}
    out = []
    out.append(f"# Recovered session: {info.get('title') or info.get('id')}")
    out.append(f"- id: {info.get('id')}")
    if info.get("title"):
        out.append(f"- title: {info['title']}")
    model = info.get("model") or {}
    if model.get("providerID") or model.get("id"):
        out.append(f"- model: {model.get('providerID')}/{model.get('id')}" +
                   (f" ({model['variant']})" if model.get("variant") else ""))
    if info.get("agent"):
        out.append(f"- agent: {info['agent']}")
    loc = info.get("location") or {}
    if loc.get("directory"):
        out.append(f"- directory: {loc['directory']}")
    t = (info.get("time") or {})
    if t.get("created"):
        out.append(f"- created: {ts(t['created'])}  last activity: {ts(t.get('updated'))}")
    toks = info.get("tokens") or {}
    if toks:
        out.append(f"- tokens while active: in={toks.get('input')} out={toks.get('output')}"
                   f" reasoning={toks.get('reasoning')} cache_read={toks.get('cache', {}).get('read')}")
    out.append("")
    msgs = doc.get("messages") or []
    for m in msgs:
        render_message(m, opts, out)
    if not msgs:
        out.append("(no messages in export)")
        out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(add_help=True, description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sessions", nargs="*", help="session id, ses_ prefix, or id fragment")
    ap.add_argument("--out", help="write all output to this one .md file")
    ap.add_argument("--max-output", type=int, default=0,
                    help="cap tool inputs/outputs at N chars (0 = unlimited)")
    ap.add_argument("--max-reasoning", type=int, default=0,
                    help="cap each reasoning block at N chars (0 = unlimited)")
    ap.add_argument("--no-children", action="store_true",
                    help="do not follow child (subagent) sessions")
    ap.add_argument("--plain", action="store_true",
                    help="print transcript to stdout instead of writing files")
    opts = ap.parse_args()
    if not opts.sessions:
        ap.print_help()
        sys.exit(1)

    wanted = resolve_ids(opts.sessions)
    data = find_db()
    base = (data.parent / "recovered") if data else Path(tempfile.gettempdir()) / "openidoc-recover"
    base.mkdir(parents=True, exist_ok=True)

    total_out, cout_errors = [], []

    for i, sid in enumerate(wanted):
        doc, err = export_session(sid, base)
        if doc is None:
            die(f"cannot export session {sid}", err)

        # child sessions spawn order: as referenced in the parent transcript
        child_ids, child_calls, per_child = [], {}, []
        if not opts.no_children:
            db_children = children_of(sid)
            for csid, call in collect_child_hits(doc):
                if csid in db_children:
                    child_ids.append(csid)
                    child_calls[csid] = call
            for csid in sorted(db_children):
                if csid not in child_ids:
                    child_ids.append(csid)

        md = render_session(doc, opts)
        if opts.out or opts.plain:
            total_out.append(md)
        else:
            path = base / f"{sid}.md"
            path.write_text(md, encoding="utf-8")
            nmsg = len(doc.get("messages") or [])
            print(f"{sid}: {nmsg} messages -> {path}  (raw export: {base / (sid + '.json')})")

        for csid in child_ids:
            cdoc, cerr = export_session(csid, base)
            if cdoc is None:
                cout_errors.append(f"child {csid}: {cerr}")
                continue
            block = render_session(cdoc, opts)
            header = f"\n\n# CHILD SESSION {csid}" + (
                f"\n(spawned by: {child_calls.get(csid, 'unknown tool call')})"
                if child_calls.get(csid) else "")
            if opts.out or opts.plain:
                total_out.append(header + "\n\n" + block)
            else:
                cpath = base / f"{csid}.md"
                cpath.write_text(header + "\n\n" + block, encoding="utf-8")
                print(f"  child {csid}: {len(cdoc.get('messages') or [])} messages -> {cpath}")

    if opts.out:
        text = "\n\n".join(total_out)
        Path(opts.out).write_text(text, encoding="utf-8")
        print(f"transcript ({len(text)} chars) -> {opts.out}")
    elif opts.plain:
        print("\n\n".join(total_out))

    if cout_errors:
        print("child export failures:\n  " + "\n  ".join(cout_errors), file=sys.stderr)


if __name__ == "__main__":
    main()
