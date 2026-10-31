"""
sheafmd.hub.index — the index: every document of every root with its dot (SPEC 8.6, 8.7).

The data is `/_/index.json`, and the page and `sheaf list` are made from it. A document's dot
comes from three things: what its file holds (parsed once per `(mtime_ns, size)`), what the hub's
person has seen of it (`seen.json`), and what the hub knows is running on it (a Tell waiting for
its reply, a session waiting on the person). A document that nobody has opened is never rendered
for this: the index reads files, it does not start pages.
"""
import contextlib
import html
import os
import threading
import time
from collections import deque
from importlib import resources
from pathlib import Path
from typing import NamedTuple
from urllib.parse import quote

from .. import comments as rdc
from . import place
from . import roots as roots_mod

DOTS = ("red", "orange", "blue", "green")          # most urgent first
RANK = {d: i for i, d in enumerate(DOTS)}
SWEEP_SECONDS = 5               # how often every listed file is looked at while an index is open


class Summary(NamedTuple):
    """What a file's comments come to, apart from who has read them."""
    open: int                   # open comments (malformed and foreign ones never count)
    threads: tuple              # (id, messages, author of the last message) of each open thread


EMPTY = Summary(0, ())
# What the board holds for a document whose event was not sent: the open indexes may still show an
# older row of it. It equals no row, so the next look or sweep tells the document as it is then,
# and a sweep that finds it gone says so.
UNTOLD = (None, None, None, None)


class Queued(NamedTuple):
    at: int                     # the number of the last look when the board took it
    sweep: bool                 # queued by a sweep, whose thread sends it
    sig: tuple | None           # what the board took for the document (None: that it is gone)
    event: "Status"


class Status(dict):
    """The data of a `status` event (8.8), marked with whether the file itself moved: the
    document came or went, or its open comments or its last change differ. The mark is not
    sent (`json.dumps` reads only the items). A member's index stream is sent only these: a dot
    that moved alone says what the hub's person read, or that the hub account's Ask or Tell
    started or ended (9.9)."""
    def __init__(self, data: dict, files: bool, at: int | None = None, sig: tuple | None = None,
                 members_only: bool = False):
        super().__init__(data)
        self.files = files
        self.members_only = members_only    # a dot only a member's index shows moved (9.15): not the hub's person's
        self.at = at                # the number of the last look when the board took it (None: not the board's)
        self.sig = sig              # what the board took for the document


def summarize(text: str) -> Summary:
    if not rdc.COMMENT_RE.search(text):             # most documents hold none: no parse for them
        return EMPTY
    threads = tuple((c.id, 1 + len(c.replies), c.replies[-1].by if c.replies else c.by)
                    for c in rdc.parse(text).comments if c.status == "open")
    return Summary(len(threads), threads)


def worst(dots) -> str | None:
    return min(dots, key=RANK.__getitem__, default=None)


# ── the words of the page ────────────────────────────────────────────────────

MONTH = 30 * 86400
CREDIT = "Made by tiroir. A hosted version is coming."


def ago(sec: float) -> str:
    """"4 min ago": the last change of a document, as the page says it. page/index.js says
    the same words between two refreshes."""
    if sec < 45:
        return "just now"
    if sec < 3600:
        return f"{max(1, int(sec // 60))} min ago"
    if sec < 86400:
        return f"{int(sec // 3600)} h ago"
    days = int(sec // 86400)
    return f"{days} day ago" if days == 1 else f"{days} days ago"


def when(mtime: float, now: float) -> str:
    """`ago`, and a date once it is over a month: a date does not age."""
    if now - mtime < MONTH:
        return ago(now - mtime)
    return time.strftime("%Y-%m-%d", time.localtime(mtime))


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _dot(dot: str, label: str, count: int | None = None) -> str:
    glyph = "✓" if dot == "green" else str(count) if dot == "blue" and count else ""
    return f'<span class="dot {dot}" role="img" aria-label="{html.escape(label)}">{glyph}</span>'


def _row_html(d: dict, now: float) -> str:
    address = d["doc"]
    rel = roots_mod.Address.parse(address).rel
    if d["dot"] == "red":
        label = (f"{_plural(d['unread'], 'thread')} with a message you have not read"
                 if d["unread"] else "a session is waiting for you")
    else:
        label = {"orange": "an Ask or Tell is running", "green": "no open comments"}.get(
            d["dot"]) or f"{_plural(d['open'], 'open comment')}"
    count = ""
    if d["open"]:
        text = f"{d['open']} open" + (f", {d['unread']} unread" if d["unread"] else "")
        count = f'<span class="n">{text}</span>'
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(d["mtime"]))
    return (f'<li class="doc" data-doc="{html.escape(address)}" data-dot="{d["dot"]}">'
            f'{_dot(d["dot"], label, d["open"])}'
            f'<a href="{html.escape(roots_mod.url_path(address))}">{html.escape(rel)}</a>{count}'
            f'<time data-mtime="{d["mtime"]:.3f}" title="{stamp}">{when(d["mtime"], now)}</time></li>')


_ROOT_DOT = {"red": "something in this root needs you", "orange": "something in this root is running",
             "blue": "this root has open comments", "green": "no open comments in this root"}


def _section(r: dict, more: dict, now: float) -> str:
    name = r["name"]
    head = (_dot(r["dot"], _ROOT_DOT[r["dot"]]) if r["dot"] else "")
    folder = f'<span class="path">{html.escape(r["path"])}</span>' if "path" in r else ""    # a member's has none (9.9)
    out = [f'<section class="root" data-root="{html.escape(name)}"><h2>{head}'
           f'<a href="/{quote(name, safe="")}/">{html.escape(name)}</a>{folder}</h2>']
    if r["missing"]:
        out.append(f'<p class="missing">folder missing: <code>sheaf roots forget {html.escape(name)}</code></p>')
    elif r["closed"]:
        out.append(f'<p class="closed">folder cannot be entered: {html.escape(r["closed"])}</p>')
    elif not r["docs"]:
        out.append('<p class="empty">No markdown files in this folder.</p>')
    else:
        out.append('<ul class="docs">' + "".join(_row_html(d, now) for d in r["docs"]) + "</ul>")
    if n := more.get(name):
        # The listing stops counting at COUNT_LIMIT: "100000+" is that many or more.
        out.append(f'<p class="more">and {n}{"+" if n >= roots_mod.COUNT_LIMIT else ""} more</p>')
    return "".join(out) + "</section>"


def _asset(name: str) -> str:
    return (resources.files("sheafmd") / "page" / name).read_text(encoding="utf-8")


def render_page(data: dict, *, version: str, port: int, only: str | None, nonce: str,
                now: float, origin: str | None = None) -> str:
    """The index page for `data` (what `Index.data` returns). The script only refreshes it:
    every row and every word in it is written here, escaped. With `origin` (a member's, 9.9) the
    header names the front's origin, not the hub's port."""
    legend = "".join(f'<span>{_dot(d, t)} {t}</span>' for d, t in (
        ("red", "needs you"), ("orange", "running"), ("blue", "open comments"), ("green", "none open")))
    if data["roots"]:
        body = "".join(_section(r, data["more"], now) for r in data["roots"])
    else:
        body = ('<p class="empty">No documents yet. <code>sheaf open FILE.md</code> adds one.</p>')
    back = '<a class="back" href="/">all roots</a>' if only else ""
    where = html.escape(origin) if origin else f"port {port}"
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>sheaf</title><style>{_asset("index.css")}</style></head><body>'
            f'<header><h1>sheaf</h1><span class="meta">{html.escape(version)} · {where}</span>{back}</header>'
            f'<div class="legend-bar">'
            f'<p class="legend">{legend}</p><p id="live" hidden></p></div>'
            f'<main id="roots" data-only="{html.escape(only or "")}">{body}</main>'
            f'<footer>{CREDIT}</footer>'
            f'<script nonce="{html.escape(nonce)}">{_asset("index.js")}</script></body></html>')


class Index:
    def __init__(self, hub):
        self.hub = hub
        self._lock = threading.Lock()
        self._cache: dict[str, tuple] = {}          # path -> ((mtime_ns, size), Summary)
        # What the open indexes were last told, per document: (dot, open, unread, mtime). Only
        # kept up while an index stream is open; the first one that opens starts it afresh.
        self._board: dict[str, tuple] = {}
        self._swept = 0.0
        # A sweep runs on a thread of its own, one at a time: listing a root can take git up to
        # 20 s, and the watcher's pass must go on meanwhile (8.9). Every look at a document outside
        # a sweep takes the next number, and a sweep says nothing of a document looked at after it
        # began: the row it holds was read before that look, maybe long before. Neither a sweep nor a
        # look says anything of a root forgotten after it began. `_forgot_at` holds one number per root
        # name for as long as the hub runs: a look may still be reading a row while a sweep ends or a
        # first stream starts the board afresh.
        self._sweeping = False
        self._last_look = 0
        self._looked_at: dict[str, int] = {}        # address -> the number of its last look
        self._forgot_at: dict[str, int] = {}        # root name -> the number of the look its forget took
        self._fresh_at = 0                          # the number the board was last started afresh at
        # The events go out in the order the board took them, by one thread at a time: each is
        # queued under the lock as the board takes it, and sent outside it. Sending hands the event
        # to each stream and no more: a member's stream asks whether the document is theirs, which
        # can ask git, when it reads the event, on its own thread (`events.Subscription`). One
        # forgotten or started afresh since is not sent.
        self._outbox: deque[Queued] = deque()
        self._sending = threading.Lock()

    # ── one file ─────────────────────────────────────────────────────────────
    def summary(self, address: str, path: Path, st: os.stat_result) -> Summary:
        """The comments of a file, parsed again only when its `(mtime_ns, size)` moved."""
        key, stamp = str(path), (st.st_mtime_ns, st.st_size)
        with self._lock:
            hit = self._cache.get(key)
        if hit and hit[0] == stamp:
            return hit[1]
        try:
            got = summarize(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):               # unreadable, or not text: listed, no comments
            got = EMPTY
        except Exception:
            self.hub.record_exception("status-failed", address)
            got = EMPTY
        with self._lock:
            self._cache[key] = (stamp, got)
        return got

    def _live_state(self, only: str | None = None) -> tuple[set, set]:
        """The documents whose session waits on the person, and those a job runs on; `only` names the
        one document that is asked about."""
        waiting, running = set(), {doc for doc, _ in self.hub.jobs_asking() if only in (None, doc)}
        entries = self.hub.entries
        for address, e in (list(entries.items()) if only is None else [(only, entries.get(only))]):
            if e is None:
                continue
            telling, question = e.live.peek()
            if telling:
                running.add(address)
            if question:
                waiting.add(address)
        return waiting, running

    def _row(self, address: str, path: Path, st: os.stat_result, waiting: set, running: set,
             member=None) -> dict:
        hub = self.hub
        s = self.summary(address, path, st)
        seen = hub.member_seen.get(member.id, address) if member else hub.seen.get(address)
        me = member.name if member else hub.person
        # SPEC 8.7: unread is an open thread whose last message is not the person's and that has
        # more messages than they have seen. A member is the person of their own index (9.9), and
        # is told nothing of the hub account's agent session: neither that it waits on its person
        # nor that an Ask or a Tell of it runs.
        unread = sum(1 for cid, n, by in s.threads if by != me and n > seen.get(cid, 0))
        sees_session = member is None
        # A member's orange is James's session working on a drop of theirs, by its supervisor's word (9.15).
        works = (sees_session and address in running) or (member is not None and hub.box_waits.working(address))
        dot = ("red" if (sees_session and address in waiting) or unread else
               "orange" if works else "blue" if s.open else "green")
        e = hub.entries.get(address)
        url = roots_mod.url_path(address) if member else hub.url(address)     # the front's origin (9.9)
        return {"doc": address, "url": url, "dot": dot, "open": s.open,
                "unread": unread, "mtime": st.st_mtime, "tabs": e.bus.count() if e else 0,
                "opened": bool(e and e.opened), "rendered": bool(e and e.rendered)}

    def page(self, nonce: str, only: str | None = None, member=None) -> str:
        return render_page(self.data(only, member=member), version=self.hub.version, port=self.hub.port,
                           only=only, nonce=nonce, now=self.hub.clock(),
                           origin=self.hub.proxy.origin if member else None)

    # ── the index stream (SPEC 8.6, 8.8) ─────────────────────────────────────
    @staticmethod
    def _sig(row: dict) -> tuple:
        return (row["dot"], row["open"], row["unread"], row["mtime"])

    @staticmethod
    def _event(address: str, got, files: bool, at: int, sig: tuple | None) -> Status:
        root, row = got if got else (roots_mod.Address.parse(address).root, None)
        return Status({"doc": address, "root": root, "dot": row and row["dot"],
                       "open": row["open"] if row else 0, "changed": row and row["mtime"]}, files, at, sig)

    def _rows(self) -> dict:
        return {d["doc"]: (r["name"], d) for r in self.data()["roots"] for d in r["docs"]}

    def arm(self):
        """The first index stream is opening: take the index as it stands and say nothing about
        it. What happened while nobody was looking is on the page the stream belongs to."""
        rows = self._rows()
        with self._lock:
            self._board = {a: self._sig(row) for a, (_, row) in rows.items()}
            self._swept = self.hub.clock()
            self._last_look += 1
            self._fresh_at, self._looked_at = self._last_look, {}

    def _queue(self, found: dict, sweep: bool = False):
        """Queue the events for what `found` ({address: (root, row), or None for a document that
        is gone}) says against what the open indexes were told, which the board then holds. With
        the lock held."""
        board, at = self._board, self._last_look
        for address, got in found.items():
            if got is None:
                if board.get(address) is not None:
                    event = self._event(address, None, True, at, None)
                    del board[address]
                    self._outbox.append(Queued(at, sweep, None, event))
            elif (old := board.get(address)) != (sig := self._sig(got[1])):
                files = old is None or (old[1], old[3]) != (sig[1], sig[3])    # open, mtime
                event = self._event(address, got, files, at, sig)      # before the board takes it
                board[address] = sig
                self._outbox.append(Queued(at, sweep, sig, event))

    def _forgotten_since(self, since: int) -> tuple:
        """`<root>/` of each root forgotten after the look numbered `since`. With the lock held."""
        return tuple(roots_mod.Address.prefix(n) for n, at in self._forgot_at.items() if at > since)

    def _queue_look(self, found: dict, since: int):
        """Queue the events of a look at a few documents begun when the last look had the number
        `since`, which takes the next number. It says nothing of a document whose root was forgotten
        since it began: the row it read is the old folder's, under a name another folder may hold by
        then."""
        with self._lock:
            self._last_look += 1
            forgotten = self._forgotten_since(since)
            found = {a: got for a, got in found.items() if not a.startswith(forgotten)}
            self._looked_at.update(dict.fromkeys(found, self._last_look))
            self._queue(found)

    def forgot(self, name: str):
        """The root `name` was forgotten (`Hub.forget_root`): a look at all of it, which takes the next
        number. A sweep begun before read the rows of its old folder, which another folder may
        already have taken the name of."""
        with self._lock:
            self._last_look += 1
            self._forgot_at[name] = self._last_look

    def _queue_sweep(self, found: dict, since: int):
        """Queue the events of a sweep begun when the last look had the number `since`. It also finds
        the documents that are no longer there at all. It says nothing of a document looked at since
        it began, nor of a root forgotten since, nor anything once the board was started afresh."""
        with self._lock:
            if self._fresh_at > since:
                return
            forgotten = self._forgotten_since(since)

            def may_tell(address: str) -> bool:
                return self._looked_at.get(address, 0) <= since and not address.startswith(forgotten)
            found = {a: got for a, got in found.items() if may_tell(a)}
            gone = [a for a in set(self._board) - set(found) if may_tell(a)]
            self._queue({**found, **dict.fromkeys(gone)}, sweep=True)
            self._looked_at = {a: n for a, n in self._looked_at.items() if n > since}

    def _publish(self, sweep: bool = False):
        """Send what the board queued, oldest first, so no event overtakes one the board took before
        it. A look that finds another caller sending leaves its events to it. The sweep's thread
        waits its turn and sends its own events: a look that is sending stops at them, so neither the
        watcher's pass nor a request sends a sweep's events. A failure is written down, and the
        next event goes."""
        wait = sweep
        while self._sending.acquire(blocking=wait):
            wait = False
            try:
                while (ev := self._next_to_send(sweep)) is not None:
                    try:
                        self.hub.index_bus.publish("status", ev)
                    except Exception:
                        self.hub.record_exception("status-failed", ev["doc"])
                        self._untell(ev)
            finally:
                self._sending.release()
            with self._lock:                        # what was queued while the last one went out
                if not self._outbox or (self._outbox[0].sweep and not sweep):
                    return                          # nothing, or the sweep's, which its thread sends

    def _untell(self, ev: Status):
        """The send of `ev` failed, so no stream was told what the board took. Unless the board was
        started afresh since (its page never listed the document), the board holds the document as
        UNTOLD and the next look or sweep tells it as it is then (a sweep that finds it gone says
        so). That is when the board still holds what `ev` took, or a deletion that nothing took
        again. It is also when `ev` told the file moved and a later event took the board on: a
        member's stream is sent only the events of a file that moved, and the later one may not be."""
        with self._lock:
            if self._fresh_at > ev.at:
                return
            doc, held = ev["doc"], self._board.get(ev["doc"])
            if held == ev.sig or (ev.files and held is not None):
                self._board[doc] = UNTOLD

    def _next_to_send(self, sweep: bool):
        """The oldest queued event that may still be sent, or None; None too at a sweep's event,
        unless the sweep's own thread asks. One that the board took before it was started afresh is
        not sent: the board was taken again after it. Nor one of a root forgotten since
        (`_forgotten_event`)."""
        with self._lock:
            while self._outbox:
                q = self._outbox[0]
                if q.sweep and not sweep:
                    return None
                self._outbox.popleft()
                if self._fresh_at > q.at:
                    continue
                if self._forgotten_event(q.event):
                    continue
                return q.event
            return None

    def _forgotten_event(self, ev: Status) -> bool:
        """Whether the root of `ev` was forgotten after the board took it, which makes its row the old
        folder's, under a name another folder may hold by then. With the lock held. The open
        indexes may still show an older row of that document, so unless a later look or sweep has
        taken it since, the board holds it as UNTOLD."""
        if self._forgot_at.get(ev["root"], 0) <= ev.at:
            return False
        if ev["doc"] in self._board and self._board[ev["doc"]] == ev.sig:
            self._board[ev["doc"]] = UNTOLD
        return True

    def _stream_may_take(self, ev: Status) -> bool:
        """Whether a stream that takes `ev` now may be sent it: not after a forget of its root since the
        board took it (the event was handed to the streams one by one, and a member's stream judges it
        when it reads it)."""
        if ev.at is None:
            return True
        with self._lock:
            return not self._forgotten_event(ev)

    def accepting(self, accept=None):
        """`accept` of a stream (`events.Subscription`), with `_stream_may_take` asked before it and
        again after it: a member's judgement can ask git, and a forget can come meanwhile."""
        def forgotten(name: str, data) -> bool:
            return name == "status" and isinstance(data, Status) and not self._stream_may_take(data)

        def accepting(name: str, data):
            if forgotten(name, data) or (accept is None and isinstance(data, Status) and data.members_only):
                return None
            told = accept(name, data) if accept else data
            return None if told is not None and forgotten(name, data) else told
        return accepting

    def sweep(self):
        """Look at every listed file, and tell the open indexes what moved."""
        with self._lock:
            since = self._last_look
        try:
            self._queue_sweep(self._rows(), since)
        finally:                                    # what it queued before it raised is the head
            self._publish(sweep=True)               # the looks wait for

    def _sweep_apart(self):
        """The sweep, on its own thread. A failure is written down; the next one is tried as usual."""
        try:
            self.sweep()
        except Exception:
            self.hub.record_exception("status-failed")
        finally:
            self._sweeping = False

    def _start_sweep(self, run):
        """Test seam: where a sweep runs."""
        threading.Thread(target=run, name="sheaf-sweep", daemon=True).start()

    def _stat_of(self, root, address: str):
        """`(path, stat)` of the document the hub would serve at `address`, or None when `resolve`
        refuses it or the file cannot be statted. A sheaf's name in the list's root is its file's, wherever
        that is (9.11)."""
        try:
            self.hub.roots.resolve(address)
            path = self.hub.file(address)
            return path, os.stat(path)
        except (roots_mod.NotFound, OSError):
            return None

    def touch(self, address: str):
        """Look at one document and tell the open indexes if it moved. Every write path calls
        this (a save, a thread opened, a comment, a seen mark, a render), and so does the hold on
        a document that is open. A document the index does not know is left to the next sweep,
        unless it was rendered: the listing leaves out what git ignores, and a page opened by
        its address is not on it."""
        hub = self.hub
        if not hub.index_bus.count():
            return
        e = hub.entries.get(address)
        with self._lock:
            known, since = address in self._board, self._last_look
        if not known and not (e and e.rendered):
            return
        at = roots_mod.Address.parse(address)
        root, got = hub.roots.get(at.root), None
        with place.held(hub, address):              # every read of a sheaf's file holds its name's lock (9.11)
            if root is not None and (found := self._stat_of(root, address)):
                path, st = found
                waiting, running = self._live_state(address)
                got = (at.root, self._row(address, path, st, waiting, running))
        self._queue_look({address: got}, since)
        self._publish()

    def moved_for_members(self, address: str):
        """A dot only a member's index shows moved: a drop for James's window began or ended its work (9.15).
        Their index streams are told the document, and ask for their index again; the hub's person's board and
        stream are left as they are."""
        if self.hub.index_bus.count():
            root = roots_mod.Address.parse(address).root
            self.hub.index_bus.publish("status", Status({"doc": address, "root": root}, files=True,
                                                        members_only=True))

    def tick(self, now: float):
        """The watcher's step for the index (every second). While an index stream is open:
        every SWEEP_SECONDS a look at every listed file, which is what moves the dot of a
        document nobody has open, started on its own thread unless one still runs; in between,
        a look at the documents the hub holds, which a Tell or a tab can move."""
        if not self.hub.index_bus.count():
            return
        if now - self._swept >= SWEEP_SECONDS and not self._sweeping:
            self._swept, self._sweeping = now, True
            try:
                self._start_sweep(self._sweep_apart)
            except BaseException:
                self._sweeping = False          # no thread: the next one is tried as usual
                raise
            return
        for address in list(self.hub.entries):
            self.touch(address)

    # ── the whole index ──────────────────────────────────────────────────────
    def data(self, only: str | None = None, rendered: bool = False, member=None) -> dict:
        """`{roots: [{name, path, missing, closed, dot, docs: [...]}], more: {root: n}}` (SPEC 8.5).
        Roots go by their most recently changed document; documents by dot, then last change.
        `only` limits it to one root. A document rendered since the hub started is listed even
        when the listing leaves it out (a gitignored file the person named). `rendered` lists
        only those, with no listing of any folder: what `sheaf list` asks for. For a `member` of
        proxy mode, only their roots, and in them only their documents: a root nested inside one
        of theirs is another root (9.9), and a sheaf that is another member's alone is none (9.11)."""
        hub = self.hub
        waiting, running = self._live_state()
        named = {a for a, e in list(hub.entries.items()) if e.rendered}
        out, more, keys = [], {}, set()
        theirs: dict = {}                           # (root, folder) -> whether 8.2 gives its documents that root

        def shown(root, path) -> bool:
            if member is None:
                return True
            # A nested root's folder is walked under both roots; a link is judged where it points,
            # as lookup judges it.
            key = (root.name, path.resolve().parent)
            if key not in theirs:
                theirs[key] = hub.roots.lookup(path) == root
            return theirs[key]

        for root in hub.roots.all():
            if only is not None and root.name != only:
                continue
            if member is not None and not hub.owns(member, root):
                continue
            listing = roots_mod.Listing([], 0) if rendered else roots_mod.list_documents(root)
            if not rendered:
                hub.check_projects(root, (f.rel for f in listing.docs))
            rows, have = [], set()
            placed = not rendered and place.applies(hub, root.name)
            top = Path(os.path.realpath(root.path))
            for f in listing.docs:
                # A sheaf of the list's root is listed by its name (9.11); a private path is none. Each file is
                # read under its name's lock, as every read.
                logical = place.logical(f.rel) if placed else None
                with place.held(hub, f"{root.name}/{logical}") if logical else contextlib.nullcontext():
                    rel = place.named(hub, root, top, f.rel) if placed else f.rel
                    if rel is None:
                        continue
                    address, path = str(roots_mod.Address(root.name, rel)), root.path / f.rel
                    keys.add(str(path))
                    have.add(address)
                    if shown(root, path) and (member is None or hub.visible(member, address)):
                        rows.append(self._row(address, path, f.stat, waiting, running, member))
            for address in sorted(a for a in named - have if a.startswith(roots_mod.Address.prefix(root.name))):
                with place.held(hub, address):          # every read of a sheaf's file holds its name's lock (9.11)
                    if not (found := self._stat_of(root, address)):
                        continue
                    path, st = found
                    keys.add(str(path))
                    if shown(root, path) and (member is None or hub.visible(member, address)):
                        rows.append(self._row(address, path, st, waiting, running, member))
            if rendered and not rows:
                continue
            rows.sort(key=lambda r: (RANK[r["dot"]], -r["mtime"], r["doc"]))
            if listing.more:
                more[root.name] = listing.more
            # A member is told the root's name, never its folder on the hub's disk (9.9).
            folder = {"path": str(root.path)} if member is None else {}
            out.append({"name": root.name, **folder, "missing": root.missing(), "closed": root.closed(),
                        "dot": worst(r["dot"] for r in rows), "docs": rows})
        out.sort(key=lambda r: (-max((d["mtime"] for d in r["docs"]), default=0), r["name"]))
        if only is None and member is None and not rendered:
            with self._lock:                        # files that are gone, roots that were forgotten
                self._cache = {k: v for k, v in self._cache.items() if k in keys}
        return {"roots": out, "more": more}
