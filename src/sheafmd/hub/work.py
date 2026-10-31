"""
sheafmd.hub.work — Work on this (SPEC 9.12): a sheaf's sessions, the transcript of a box-hosted one, and the
file Ask, Tell and Stop James drop for James's window.

    state(hub, address, text)       a sheaf's sessions and where its live session runs; None for another page
    sessions(fm)                    the items of the front matter's `sessions` that parse, as written (newest first)
    code_session(st, recorded)      the session a sign-in code serves (9.13): made, downloaded and forked by one rule
    with_session(text, line, id)    the text with `line` as the first of `sessions`, the rest as written
    open_transcript(folder, id)     the bytes of `<folder>/<one folder>/<id>.jsonl`, or None
    james_has(cfg, project, id)     whether the copy holds `id` as James's session of `project` (None: not yet)
    drop(folder, project, body, missing)  a file in `folder` for the box's supervisor: "written" or why not

A session item is one YAML flow mapping on one line, `{id: <uuid>, host: <host>, member: <who>, date: <UTC>}`.
An item that does not match that exactly is skipped, never guessed at: the hub serves a file by what it names.
Only the hub writes `sessions`: a fork reported by the signed-in member, and James's session, which the hub
takes from his own door write once its copy shows that session is his in the project. A door write or a save
that would change it is refused.
"""
import json
import os
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from .roots import Address
from .visibility import _end, _lines, _uncomment, front_matter

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
MACHINE_RE = re.compile(r"[A-Za-z0-9._-]{1,63}")
_MEMBER = r"[^\s,{}\[\]:#\"'][^,{}\[\]:#\"'\n]{0,62}?"
_ITEM_RE = re.compile(r"\{id: (" + UUID_RE.pattern + r"), host: ([A-Za-z0-9._-]{1,63}), member: (" + _MEMBER
                      + r"), date: ([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z)\}")
_KEY_LINE_RE = re.compile(r"sessions:(.*)")
_LIST_ITEM_RE = re.compile(r"(\s*-\s+)(.*?)\s*")
TEXT_MAX = 3000                 # characters of a comment's text dropped for James's window (Zara's contract)
# The laptop client of the fork (github.com/tiroir/tiroir-client), run from PyPI by uv: a member needs uv and
# Claude Code, nothing installed. One exact version: the copied command runs code that holds the member's sign-in,
# so a newer upload runs only when this line changes (tt-tiroir#170).
FORK_CLIENT = "tiroir==0.2.0"


class NotRewritten(ValueError):
    """The front matter's `sessions` is in a shape the hub does not rewrite: on its key's line, or twice."""
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
    james: bool = False         # the sheaf's `assistant` is James
    relay: bool = False         # a relay of the live session, a member's fork, has its stream open (9.14)

    @property
    def box(self) -> list:
        """The ids of the sessions that ran on the box, whose transcripts the hub serves, newest first."""
        return [s["id"] for s in self.sessions if self.cfg.box and s["host"] == self.cfg.box]

    @property
    def forkable(self) -> str | None:
        """The id of the session a fork starts from: the live one, while it runs on the box. None while it runs
        on a laptop, whose transcript the hub never holds: a box session's older copy would start a second line
        of work beside the live one."""
        return self.sessions[0]["id"] if self.live == "box" else None

    @property
    def can(self) -> list:
        """The page's `can` (10.1): Ask and Tell go to James's window while the live session is on the box,
        or on a sheaf of James with no session yet (the hub records his when it finds it), and `[list]`
        names the box and the folder to drop them in; Tell goes to a fork's connected relay."""
        to_james = self.live == "box" or (self.live == "" and self.james)
        if to_james and self.cfg.box and self.cfg.tell_dir is not None:
            return ["box-ask", "box-tell"]
        # Tell, never Ask, goes to a member's fork through its relay while that relay is connected (9.14).
        return ["relay-tell"] if self.live == "laptop" and self.relay else []


def code_session(st: State | None, recorded: str | None = None) -> str | None:
    """The session a sign-in code serves on the sheaf whose state is `st` (9.13), the one rule of its making, its
    GET and its POST: the sheaf's forkable session, while the hub keeps the copy that serves it. Asked with no
    `recorded`, the id a new code records; asked with a code's `recorded` id, that id while it is still the
    forkable one, else None: a newer live session, James's or a member's fork, needs a new code."""
    sid = st.forkable if st is not None and st.cfg.sessions_dir is not None else None
    return sid if sid is not None and recorded in (None, sid) else None


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
    fm = front_matter(text)
    items = sessions(fm)
    live = ""
    if items:
        live = "box" if cfg.box and items[0]["host"] == cfg.box else "laptop"
    assistant = fm.get("assistant", "")
    relays = getattr(hub, "relays", None)
    relay = live == "laptop" and relays is not None and relays.connected(address, items[0]["id"])
    return State(items, live, cfg, isinstance(assistant, str) and assistant.casefold() == "james", relay)


def member_word(member) -> str:
    """How a session item and a row name a member: their short name, else their name, in the characters a
    flow mapping holds unquoted."""
    word = re.sub(r"[,{}\[\]:#\"'\n]", "-", member.short or member.name).strip()
    # A plain YAML scalar does not open with an indicator (an anchor, a tag, a block, a list item...).
    return re.sub(r"^[-?&*!|>%@`\s]+", "", word) or "member"


def item(id: str, host: str, member: str, date: str) -> str:
    return f"{{id: {id}, host: {host}, member: {member}, date: {date}}}"


def with_session(text: str, line: str, id: str) -> str:
    """`with_session`, refused (NotRewritten) unless the list read back is `line` and the items read before
    but `id`: a rewrite never makes a session of a line the reader skipped (one under `sessions: []`)."""
    new = _with_session(text, line, id)
    want = sessions({"sessions": (line,)}) + [s for s in sessions(front_matter(text)) if s["id"] != id]
    if sessions(front_matter(new)) != want:
        raise NotRewritten("sessions has lines the hub does not read as its items: write it as one item per line")
    return new


def _with_session(text: str, line: str, id: str) -> str:
    """`text` with `line` (an `item`) as the first item of `sessions`. An item of the same `id` is taken out,
    so a session is listed once; every other line of the file stays as written, its line ending too. A text
    with no front matter gets one. NotRewritten for a list on the key's line or a key written twice."""
    raw = text.split("\n")                      # each line keeps its own "\r"
    lines = _lines(text)
    end = _end(lines)
    if end < 0:
        cr = "\r" if raw[0].endswith("\r") else ""
        bom = "\ufeff" if text.startswith("\ufeff") else ""      # stays first, or the heading reads as a paragraph
        return bom + "\n".join(["---" + cr, "sessions:" + cr, f"  - {line}" + cr, "---" + cr]) + "\n" + text[len(bom):]
    keys = [n for n in range(1, end) if _KEY_LINE_RE.fullmatch(lines[n])]
    if len(keys) > 1:
        raise NotRewritten("sessions is written twice in the front matter: keep one list")
    if not keys:
        cr = "\r" if raw[end].endswith("\r") else ""
        return "\n".join(raw[:end] + ["sessions:" + cr, f"  - {line}" + cr] + raw[end:])
    at = keys[0]
    cr = "\r" if raw[at].endswith("\r") else ""
    value = _uncomment(_KEY_LINE_RE.fullmatch(lines[at]).group(1))
    if value not in ("", "[]"):
        raise NotRewritten("sessions is written on one line: write it as one item per line")
    # The list runs, as the reader reads it, over its `- ` lines, indented or not, and the blank and comment
    # lines between them; the fork takes the indent of its first item. Only an item of `id` is taken out.
    n, lead, kept = at + 1, None, []
    while n < end and (_LIST_ITEM_RE.fullmatch(lines[n]) or not lines[n].strip() or lines[n].lstrip().startswith("#")):
        item = _LIST_ITEM_RE.fullmatch(lines[n]) if not lines[n].lstrip().startswith("#") else None
        if item and lead is None:
            lead = item.group(1)
        if not (item and (m := _ITEM_RE.fullmatch(item.group(2))) and m.group(1) == id):
            kept.append(raw[n])
        n += 1
    key = raw[at]
    if value == "[]":                                   # a comment after `[]` stays on the key's line
        rest = raw[at].removesuffix("\r").split("[]", 1)[1].strip()
        key = "sessions:" + (" " + rest if rest else "") + cr
    return "\n".join(raw[:at] + [key, (lead or "  - ") + line + cr] + kept + raw[n:])


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


def james_has(cfg, project: str, id: str) -> bool | None:
    """Whether the copy of James's transcripts holds `id` as a session of `project`: `<id>.jsonl` in the folder Claude
    names after `<work_dir>/<project>`, a regular file and no link, whose first `cwd` is that very path and whose
    `sessionId` is `id` (Claude's folder name is lossy: `a-b/c` and `a/b-c` share one). None when the file is not there (yet: the copy is a minute
    behind), False when it is there and is not that, or when the copy or `work_dir` is not set."""
    if cfg.sessions_dir is None or cfg.work_dir is None or not UUID_RE.fullmatch(id):
        return False
    cwd = os.path.join(cfg.work_dir, project)
    try:
        top = os.open(cfg.sessions_dir, os.O_RDONLY | os.O_DIRECTORY)
        try:
            dfd = os.open(re.sub(r"[^A-Za-z0-9]", "-", cwd), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=top)
        finally:
            os.close(top)
    except FileNotFoundError:
        return None
    except OSError:
        return False
    try:
        try:
            os.stat(f"{id}.jsonl", dir_fd=dfd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        return _first_cwd(dfd, f"{id}.jsonl") == (cwd, id)
    except OSError:
        return False
    finally:
        os.close(dfd)


def _first_cwd(dfd: int, name: str, most: int = 1 << 20):
    """(cwd, sessionId) of the first line of the transcript `name` in the folder `dfd` that names a cwd,
    within its first `most` bytes; None when it is not a regular file or names none."""
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        head = os.read(fd, most)
    except OSError:
        return None
    finally:
        os.close(fd)
    for line in head.split(b"\n"):
        try:
            row = json.loads(line)
        except (ValueError, RecursionError):           # a line nested past the parser's depth is no row either
            continue
        if isinstance(row, dict) and "cwd" in row:
            return row.get("cwd"), row.get("sessionId")
    return None


def drop(folder: Path | None, project: str, body: bytes, missing: str) -> str:
    """Write `body` to a new file of `folder`, named `<client>--<project>-<UTC stamp>` (and `-<n>`
    when that is taken): written as `.<name>`, mode 0640 whatever the hub's umask, then renamed, so the
    box's supervisor never reads half a file. "written", or why nothing was."""
    if folder is None:
        return missing
    if not folder.is_dir():
        return f"{folder} is not a folder"
    base = f"{project.replace('/', '--')}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
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
