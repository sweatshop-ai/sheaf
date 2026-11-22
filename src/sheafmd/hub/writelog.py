"""The Write log: the hub's own record of the writes to its pages, one line per write whatever the path (a door write, a
page save, a pull of a repo clone, a file written on disk and seen). Not the Diagnostics log, which records what went
wrong: this one is where a row of the Sheaf gets its last write and its last agent session.

A line holds the address, the time, who wrote (a member, or an agent's `<client> (<member>)`), the place class, how the
write came (`create`, `update`, `save`, `pull`, `disk`) and what the writer declared: session, machine, Remote Control link
and chat id. What a writer declares is kept as declared and never verified; it never opens a transcript."""
import contextlib
import json
import os
import threading
from collections import Counter, deque
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path

from .. import paths

KEEP = 200                  # lines kept in memory per address
MAX_BYTES = 10 * 1024 * 1024
RENAMED = "renamed"        # the marker line of `WriteLog.rename`: `writer` is the address the lines went to
RETRACTED = "retracted"    # the marker line of `WriteLog.restore`: the lines the file holds for `address` before it are taken back
NAME, ROTATED = "write-log.jsonl", "write-log.1.jsonl"
MAX_SESSION = 100
MAX_DECLARED = 200


def valid_session(session) -> bool:
    """A session id the Tells long-poll may name: one line, at most MAX_SESSION characters."""
    return isinstance(session, str) and 0 < len(session) <= MAX_SESSION and "\n" not in session


@dataclass(frozen=True)
class Line:
    address: str
    time: str
    writer: str
    place: str
    via: str
    session: str = ""
    host: str = ""
    link: str = ""
    chat: str = ""


def log_path() -> Path:
    return paths.state_dir() / NAME


def clean(value, limit: int = MAX_DECLARED) -> str:
    """A declared value as the log keeps it: text, control characters a space, cut to `limit`."""
    if not isinstance(value, str):
        return ""
    return "".join(" " if not c.isprintable() else c for c in value).strip()[:limit]


def declared_link(value) -> str:
    """A declared Remote Control link, only when it is a web address: the row will make it a link, so nothing else is kept."""
    v = clean(value, 500)
    return v if v.startswith(("https://", "http://")) and " " not in v else ""


class _Own:
    """The lines one landing added (`lines`) and, per address, what the address held before the landing's first (`before`)."""

    def __init__(self):
        self.lines: list[Line] = []
        self.before: dict[str, list[Line]] = {}


class WriteLog:
    def __init__(self, keep: int = KEEP, now=None):
        from time import strftime

        from ..source import STAMP_FORMAT
        self._keep = keep
        self._now = now or (lambda: strftime(STAMP_FORMAT))
        self._lock = threading.Lock()
        self._lines: dict[str, deque] = {}
        self._pulling: set[str] = set()
        self._left: dict[str, str] = {}
        self._own: dict[str, str] = {}
        self._mine = threading.local()      # `own`: what the calling thread is adding under `own_lines`
        self._load()

    def _load(self):
        try:
            rows = log_path().read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        names = {f.name for f in fields(Line)}
        for row in rows:
            try:
                got = json.loads(row)
                line = Line(**{k: v for k, v in got.items() if k in names})
            except (ValueError, TypeError):
                continue
            if line.via == RETRACTED:
                self._lines.pop(line.address, None)
                continue
            if line.via == RENAMED:
                self._carry(line.address, line.writer)
                continue
            self._lines.setdefault(line.address, deque(maxlen=self._keep)).append(line)

    def _carry(self, old: str, new: str):
        kept = self._lines.pop(old, None)
        if kept:
            self._lines.setdefault(new, deque(maxlen=self._keep)).extend(kept)

    def rename(self, old: str, new: str):
        """The lines of the page at `old` are those of the page at `new`, a page that moved (9.11). A line of its own,
        `renamed`, tells a restart where they went: it keeps no line of its own and is never shown."""
        with self._lock:
            if old not in self._lines:
                return
            self._carry(old, new)
            self._append(Line(address=old, time=self._now(), writer=new, place="", via=RENAMED))

    def add(self, address: str, writer: str, place: str, via: str, **declared) -> Line:
        """One line, the time now. Never raises: a log that cannot be written must not break the write it records."""
        line = Line(address=address, time=self._now(), writer=clean(writer), place=place, via=via,
                    session=clean(declared.get("session"), MAX_SESSION), host=clean(declared.get("host")),
                    link=declared_link(declared.get("link")), chat=clean(declared.get("chat")))
        with self._lock:
            self._noted(line)
            self._lines.setdefault(address, deque(maxlen=self._keep)).append(line)
            self._append(line)
        return line

    def _noted(self, line: Line):
        """Under the lock, before `line` is added: the calling thread's landing notes it, and the lines its address held before the
        landing's first one."""
        own = getattr(self._mine, "own", None)
        if own is not None:
            own.before.setdefault(line.address, list(self._lines.get(line.address, ())))
            own.lines.append(line)

    def carry(self, address: str, lines: list, came_from: str, by: str) -> int:
        """The Write log lines of a page moved here (ticket 20), as they were, under its new `address`, each kept as the log
        keeps one (cleaned); then one line of this tiroir's own that says it came by transfer, from `came_from`. Never raises, as
        `add` does not. Returns how many of the carried lines were kept."""
        n = 0
        with self._lock:
            held = Counter(self._lines.get(address, ()))      # what the address kept before this call: a carried line matches one of these, once
        for got in lines:
            if not isinstance(got, dict):
                continue
            line = Line(address=address, time=clean(got.get("time"), 40), writer=clean(got.get("writer")),
                        place=clean(got.get("place"), 40), via=clean(got.get("via"), 40),
                        session=clean(got.get("session"), MAX_SESSION), host=clean(got.get("host")),
                        link=declared_link(got.get("link")), chat=clean(got.get("chat")))
            with self._lock:
                kept = self._lines.setdefault(address, deque(maxlen=self._keep))
                if held[line] > 0:      # a page that came back brings the lines this address kept when it left: each is kept once
                    held[line] -= 1
                    continue
                self._noted(line)
                kept.append(line)
                self._append(line)
            n += 1
        self.add(address, by, "tiroir", "transfer", host=came_from)
        return n

    @staticmethod
    def _append(*lines: Line):
        try:
            log = log_path()
            paths.private_dir(log.parent)
            try:
                if log.stat().st_size >= MAX_BYTES:
                    os.replace(log, log.with_name(ROTATED))
            except OSError:
                pass
            fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(fd, "".join(json.dumps(asdict(line), ensure_ascii=False) + "\n" for line in lines).encode("utf-8"))
            finally:
                os.close(fd)
        except Exception:
            pass

    def lines(self, address: str) -> list[Line]:
        """The kept lines of `address`, oldest first."""
        with self._lock:
            return list(self._lines.get(address, ()))

    def last(self, address: str) -> Line | None:
        got = self.lines(address)
        return got[-1] if got else None

    def last_session(self, address: str) -> Line | None:
        """The last line that named an agent session."""
        return next((l for l in reversed(self.lines(address)) if l.session), None)

    def last_way_back(self, address: str) -> Line | None:
        """The last line that named an agent session or an Open WebUI chat: the one the row's session name follows."""
        return next((l for l in reversed(self.lines(address)) if l.session or l.chat), None)

    # A pull writes files the hub then sees change. While it is under way, what a page sees of them is the pull's; when it
    # ends, the file it left is known by its hash, and the next change a page sees is the pull's only if it is that text.
    # A record no change ever matches is dropped by the next change that does not: nothing waits to swallow a later line.
    def expect_pull(self, address: str):
        with self._lock:
            self._pulling.add(address)

    def end_pull(self, address: str, left: str | None):
        with self._lock:
            self._pulling.discard(address)
            if left:
                self._left[address] = left
            else:
                self._left.pop(address, None)

    def is_pull(self, address: str, hash_: str) -> bool:
        """Whether a change a page just saw, to the text of `hash_`, is a pull's."""
        with self._lock:
            return address in self._pulling or self._left.pop(address, None) == hash_

    # A write of the door puts its text on disk before the hub is told of it; a look at the file between the two sees a
    # change that is the door's own. Its hash is kept from before the write: the first look that finds it is the door's, a
    # look that finds another text drops it, so it never swallows a later write.
    def expect_own(self, address: str, hash_: str):
        with self._lock:
            self._own[address] = hash_

    def is_own(self, address: str, hash_: str) -> bool:
        """Whether a change a page just saw, to the text of `hash_`, is a door write's own."""
        with self._lock:
            return self._own.pop(address, None) == hash_

    @contextlib.contextmanager
    def own_lines(self):
        """What the calling thread adds to the log inside the block, as an `_Own` that fills while it runs: a landing holds no
        writer lock, so what it wrote is told apart from what another writer wrote at the address meanwhile, and `undo` takes
        back the landing's own and no more."""
        own, outer = _Own(), getattr(self._mine, "own", None)
        self._mine.own = own
        try:
            yield own
        finally:
            self._mine.own = outer

    def undo(self, address: str, own: "_Own") -> None:
        """Take back what `own` added at `address`. The lines are those it held before the landing (a landing can push the oldest
        out of the `KEEP` the address holds: they come back) then those another writer added meanwhile. Written as `restore`
        writes: one append, a `retracted` line and the lines that remain."""
        with self._lock:
            before = own.before.get(address)
            if before is None:
                return
            left = list(self._lines.get(address, ()))
            for line in (*own.lines, *before):
                if line in left:
                    left.remove(line)
            kept = [replace(line, address=address) for line in (*before, *left)]     # a line carried by a rename is kept under the address it is at
            self._append(Line(address=address, time=self._now(), writer="", place="", via=RETRACTED), *kept)
            if kept:
                self._lines[address] = deque(kept, maxlen=self._keep)
            else:
                self._lines.pop(address, None)
            self._own.pop(address, None)

    def restore(self, address: str, kept: list) -> None:
        """The lines of `address` are `kept`, as `lines` gave them: a landing that wrote some and did not land takes back those, and
        no more. The file is append-only: a `retracted` line takes back what it holds for `address`, then `kept` is written again."""
        with self._lock:
            marker = Line(address=address, time=self._now(), writer="", place="", via=RETRACTED)
            # one write: a cut one leaves the file as it was, never the retraction without the lines it keeps; a line carried by a
            # rename is written under the address it is kept at
            relabelled = [replace(line, address=address) for line in kept]
            self._append(marker, *relabelled)
            if kept:
                self._lines[address] = deque(relabelled, maxlen=self._keep)
            else:
                self._lines.pop(address, None)
            self._own.pop(address, None)

    def told(self, address: str):
        """The hub has been told of the door's write: nothing of it is left to expect."""
        with self._lock:
            self._own.pop(address, None)
