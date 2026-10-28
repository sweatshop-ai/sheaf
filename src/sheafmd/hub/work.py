"""
sheafmd.hub.work — Work on this (SPEC 9.12): a sheaf's sessions, the transcript of a box-hosted one, and the
file Ask and Tell drop for James's window.

    state(hub, address, text)       a sheaf's sessions and where its live session runs; None for another page
    sessions(fm)                    the items of the front matter's `sessions` that parse, as written (newest first)
    with_session(text, line, id)    the text with `line` as the first of `sessions`, the rest as written
    open_transcript(folder, id)     the bytes of `<folder>/<one folder>/<id>.jsonl`, or None
    drop(folder, project, data, missing)  a file in `folder` for the box's supervisor: "written" or why not

A session item is one YAML flow mapping on one line, `{id: <uuid>, host: <host>, member: <who>, date: <UTC>}`.
An item that does not match that exactly is skipped, never guessed at: the front matter is written by hand
and by James, and the hub serves a file by what it names.
"""
import json
import os
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from .roots import Address
from .visibility import _end, _lines, front_matter

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
MACHINE_RE = re.compile(r"[A-Za-z0-9._-]{1,63}")
_MEMBER = r"[^\s,{}\[\]:#\"'][^,{}\[\]:#\"'\n]{0,62}?"
_ITEM_RE = re.compile(r"\{id: (" + UUID_RE.pattern + r"), host: ([A-Za-z0-9._-]{1,63}), member: (" + _MEMBER
                      + r"), date: ([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z)\}")
_KEY_LINE_RE = re.compile(r"sessions:(.*)")
_LIST_ITEM_RE = re.compile(r"(\s*-\s+).*")
TEXT_MAX = 3000                 # characters of a comment's text dropped for James's window (Zara's contract)


class NotOneItemPerLine(ValueError):
    """The front matter's `sessions` is written on its key's line: the hub does not rewrite such a list."""
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


@dataclass(frozen=True)
class State:
    sessions: list              # the items of `sessions` as written, which is newest first
    live: str                   # "box" when the first runs on `[list]`'s box, "laptop" on another host, "" none
    cfg: object                 # the list's the_list.ListConfig

    @property
    def box(self) -> list:
        """The ids of the sessions that ran on the box, whose transcripts the hub serves, newest first."""
        return [s["id"] for s in self.sessions if self.cfg.box and s["host"] == self.cfg.box]

    @property
    def can(self) -> list:
        """The page's `can` (10.1): Ask and Tell go to James's window while the live session is on the box
        and `[list]` names the folder to drop them in."""
        return ["box-ask", "box-tell"] if self.live == "box" and self.cfg.tell_dir is not None else []


def is_sheaf(hub, address: str) -> bool:
    """Whether `address` names a sheaf of the list's root, at `<client>/<project>/<file>.md`."""
    at = Address.parse(address)
    return hub.the_list is not None and hub.the_list.serves(at.root) and at.rel.count("/") == 2


def state(hub, address: str, text: str) -> State | None:
    """The sessions of the sheaf at `address` whose text is `text`, when it is a sheaf of the list's root at
    `<client>/<project>/<file>.md`; None for any other document, which has no Work on this."""
    if not is_sheaf(hub, address):
        return None
    cfg = hub.the_list.cfg
    items = sessions(front_matter(text))
    live = ""
    if items:
        live = "box" if cfg.box and items[0]["host"] == cfg.box else "laptop"
    return State(items, live, cfg)


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
        if _KEY_LINE_RE.fullmatch(head[at]).group(1).strip() not in ("", "[]"):
            raise NotOneItemPerLine("sessions is written on one line: write it as one item per line")
        # The list runs, as the reader reads it, over its `- ` lines, indented or not, and the blank and
        # comment lines between them; the fork takes the indent of its first item.
        rest, n, lead = [], at + 1, "  - "
        while n < end and (_LIST_ITEM_RE.fullmatch(head[n]) or not head[n].strip()
                           or head[n].lstrip().startswith("#")):
            if (m := _LIST_ITEM_RE.fullmatch(head[n])) and not any(_LIST_ITEM_RE.fullmatch(x) for x in rest):
                lead = m.group(1)
            rest.append(head[n])
            n += 1
        kept = [x for x in rest if not ((m := _ITEM_RE.search(x)) and m.group(1) == id)]
        head = head[:at] + ["sessions:", lead + line] + kept + head[n:]
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
                view = memoryview(body)
                while view:
                    view = view[os.write(fd, view):]
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
