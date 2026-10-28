"""
sheafmd.hub.work — Work on this (SPEC 9.12): a sheaf's sessions, the transcript of a box-hosted one, and the
file Ask and Tell drop for James's window.

    sessions(fm)                    the items of the front matter's `sessions`, newest first, that parse
    with_session(text, item)        the text with `item` as the first of `sessions`, the rest as written
    open_transcript(folder, id)     the bytes of `<folder>/<one folder>/<id>.jsonl`, or None
    drop(folder, project, data)     a file in `folder` for the box's supervisor: "written" or why not

A session item is one YAML flow mapping on one line, `{id: <uuid>, host: <host>, member: <who>, date: <UTC>}`.
An item that does not match that exactly is skipped, never guessed at: the front matter is written by hand
and by James, and the hub serves a file by what it names.
"""
import json
import os
import re
import stat
import time
from pathlib import Path

from .visibility import _end, _lines

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
MACHINE_RE = re.compile(r"[A-Za-z0-9._-]{1,63}")
_MEMBER = r"[^\s,{}\[\]:#\"'][^,{}\[\]:#\"'\n]{0,62}?"
_ITEM_RE = re.compile(r"\{id: (" + UUID_RE.pattern + r"), host: ([A-Za-z0-9._-]{1,63}), member: (" + _MEMBER
                      + r"), date: ([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z)\}")
_KEY_LINE_RE = re.compile(r"sessions:\s*")
_LIST_ITEM_RE = re.compile(r"\s+-\s+.*")
ISO = "%Y-%m-%dT%H:%M:%SZ"


def sessions(fm: dict) -> list:
    """The sessions of the front matter `fm` (visibility.front_matter), as dicts of id, host, member and date,
    in the order written: the first is the sheaf's live session."""
    v = fm.get("sessions", ())
    out = []
    for item in (v,) if isinstance(v, str) else v if isinstance(v, tuple) else ():
        if m := _ITEM_RE.fullmatch(item):
            out.append(dict(zip(("id", "host", "member", "date"), m.groups())))
    return out


def member_word(member) -> str:
    """How a session item and a row name a member: their short name, else their name, in the characters a
    flow mapping holds unquoted."""
    word = member.short or member.name
    return re.sub(r"[,{}\[\]:#\"'\n]", "-", word).strip() or "member"


def item(id: str, host: str, member: str, date: str) -> str:
    return f"{{id: {id}, host: {host}, member: {member}, date: {date}}}"


def with_session(text: str, line: str, id: str) -> str:
    """`text` with `line` (an `item`) as the first item of `sessions`. An item of the same `id` is taken out,
    so a session is listed once; every other line of the file stays as written. A text with no front matter
    gets one."""
    lines = _lines(text)
    nl = "\r\n" if text.split("\n", 1)[0].endswith("\r") else "\n"
    end = _end(lines)
    if end < 0:
        return nl.join(["---", "sessions:", f"  - {line}", "---"]) + nl + text
    head = lines[:end]
    at = next((n for n in range(1, end) if _KEY_LINE_RE.fullmatch(head[n])), None)
    if at is None:
        head = head + ["sessions:", f"  - {line}"]
    else:
        items, n = [], at + 1
        while n < end and _LIST_ITEM_RE.fullmatch(head[n]):
            items.append(head[n])
            n += 1
        kept = [x for x in items if not ((m := _ITEM_RE.search(x)) and m.group(1) == id)]
        head = head[:at + 1] + [f"  - {line}"] + kept + head[n:]
    return nl.join(head + lines[end:])


def open_transcript(folder: Path, id: str) -> bytes | None:
    """The transcript `<folder>/<one folder>/<id>.jsonl`: a regular file, no link, whose real path is inside
    `folder`. None when there is none. `id` is a UUID already (UUID_RE), so it names no other path."""
    if not UUID_RE.fullmatch(id):
        return None
    top = os.path.realpath(folder)
    try:
        subs = sorted(e.name for e in os.scandir(top) if e.is_dir(follow_symlinks=False))
    except OSError:
        return None
    for sub in subs:
        path = os.path.join(top, sub, f"{id}.jsonl")
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError:
            continue
        try:
            st = os.fstat(fd)
            real = os.path.realpath(path)
            if not stat.S_ISREG(st.st_mode) or not real.startswith(top.rstrip("/") + "/"):
                continue
            chunks = []
            while chunk := os.read(fd, 1 << 20):
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(fd)
    return None


def drop(folder: Path | None, project: str, data: dict, missing: str) -> str:
    """Write `data` as JSON to a new file of `folder`, named `<client>--<project>-<UTC stamp>` (and `-<n>`
    when that is taken): written as `.<name>`, mode 0640 whatever the hub's umask, then renamed, so the
    box's supervisor never reads half a file. "written", or why nothing was."""
    if folder is None:
        return missing
    if not folder.is_dir():
        return f"{folder} is not a folder"
    base = f"{project.replace('/', '--')}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    body = json.dumps(data).encode("utf-8")
    for n in range(100):
        name = base if n == 0 else f"{base}-{n}"
        tmp, final = folder / f".{name}", folder / name
        if final.exists() or tmp.exists():
            continue
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
        except FileExistsError:
            continue
        except OSError as ex:
            return f"failed: {ex.strerror or ex}"
        try:
            try:
                os.fchmod(fd, 0o640)
                os.write(fd, body)
            finally:
                os.close(fd)
            if final.exists():
                tmp.unlink(missing_ok=True)
                continue
            os.replace(tmp, final)
            return "written"
        except OSError as ex:
            tmp.unlink(missing_ok=True)
            return f"failed: {ex.strerror or ex}"
    return "failed: every name of this second is taken"
