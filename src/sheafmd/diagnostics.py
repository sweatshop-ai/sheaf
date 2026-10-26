"""The diagnostics log: what goes wrong is written down where it happens.

Races between a save and an outside write, a hub that died under an open tab, a
Tell that never reached the session, a comment wait that never ended: each of
these used to be seen once, in a toast or a session's scrollback, and then lost.
This module appends one JSON line per event to a single file for the whole
machine, so a later cleanup session, or a bug report, works from a list.

Four sources write here:
  hub     the hub: refused or failed requests, swallowed errors, failed jobs,
          merged saves, why it exited
  page    the browser: every error toast, JS errors, a hub lost
  cli     `sheaf` on the command line (a failed comment write)
  agent   a session, by hand: `sheaf diag note "..."`, for what only it can see

The log never leaves the machine. Logging must never be the thing that breaks a
save, so every write swallows its own errors.
"""
import json
import os
import time
from collections import Counter
from pathlib import Path

from . import paths
from .source import STAMP_FORMAT
from .agents.detect import session_id

# A tab stuck in a loop must not fill the disk: one field is capped, and so is
# the detail a page can send. The file is capped too: past MAX_BYTES it becomes
# diagnostics.1.jsonl, replacing the previous one.
MAX_FIELD = 2000
MAX_BYTES = 10 * 1024 * 1024
NAME, ROTATED = "diagnostics.jsonl", "diagnostics.1.jsonl"


def log_path() -> Path:
    return paths.state_dir() / NAME


def _clip(v):
    if isinstance(v, str):
        # Bytes that are not UTF-8 (a file name, a mail header) reach Python as a lone surrogate,
        # which the line cannot be encoded with: it is written as the text of its escape, so the
        # row is kept.
        v = v.encode("utf-8", "backslashreplace").decode("utf-8")
        if len(v) > MAX_FIELD:
            return v[:MAX_FIELD] + "…"
    return v


def _rotate(log: Path):
    # Two writers that cross the limit in the same instant can both rotate and the
    # second drops the older file. That costs a diagnostics file, nothing else.
    try:
        if log.stat().st_size >= MAX_BYTES:
            os.replace(log, log.with_name(ROTATED))
    except OSError:
        pass


def record(source: str, kind: str, doc=None, **detail) -> bool:
    """Append one row. Never raises: True when the row was written, False when it was
    not (the caller that must tell a person, `sheaf diag note`, reads it; the others
    ignore it).

    The fixed fields win over a detail of the same name: a page cannot say it
    is the hub."""
    try:
        row = {"at": time.strftime(STAMP_FORMAT), "source": source, "kind": kind,
               "doc": str(doc) if doc else None, "pid": os.getpid(),
               "session": session_id()}
        for k, v in detail.items():
            if v not in (None, ""):
                row.setdefault(k, v)
        line = json.dumps({k: _clip(v) for k, v in row.items()}, ensure_ascii=False) + "\n"
        log = log_path()
        paths.private_dir(log.parent)
        _rotate(log)
        # One os.write of one line on an O_APPEND file: lines from concurrent
        # processes do not interleave, however long the line is.
        fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
        return True
    except Exception:
        return False


def read(since_days=None):
    """Every row of the rotated file, then of the current one, oldest first."""
    log = log_path()
    cutoff = ""
    if since_days:
        try:
            cutoff = time.strftime("%Y-%m-%dT%H:%M:%S",
                                   time.localtime(time.time() - since_days * 86400))
        except (OverflowError, ValueError, OSError):      # further back than a clock goes: all of it
            pass
    rows = []
    for f in (log.with_name(ROTATED), log):
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for ln in lines:
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if isinstance(r, dict) and str(r.get("at", ""))[:19] >= cutoff:
                rows.append(r)
    return rows


def report(since_days=None, as_json=False) -> str:
    rows = read(since_days)
    if as_json:
        return json.dumps(rows, indent=2, ensure_ascii=False)
    if not rows:
        return f"  nothing logged{' in the last %g days' % since_days if since_days else ''} ({log_path()})"
    out = [f"{len(rows)} row(s) in {log_path()}", ""]
    by = Counter((str(r.get("source", "?")), str(r.get("kind", "?"))) for r in rows)
    out.append("By kind:")
    for (src, kind), n in by.most_common():
        out.append(f"  {n:4d}  {src:8s} {kind}")
    out += ["", "Latest 40:"]
    for r in rows[-40:]:
        what = r.get("error") or r.get("note") or r.get("message") or r.get("reason") or ""
        doc = Path(str(r["doc"])).name if r.get("doc") else "-"
        out.append(f"  {str(r.get('at', ''))[:19]}  {str(r.get('source', '?')):7s} "
                   f"{str(r.get('kind', '?')):18s} {doc:34s} {what}"[:220])
    return "\n".join(out)
