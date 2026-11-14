"""The Tells that wait for an agent (SPEC 9.8, D26): `tells.json`, listed by the door's `documents`.

A Tell to an agent (ChatGPT, Claude.ai) cannot be pushed: it waits on the document until that agent next
calls `documents`. A row is kept with the token's stable `id` (`tid`) beside its name, so a token revoked and
made again under the same name never receives the old Tell. Every change of state (queued, seen, ended) is
made inside `Waiting._change`, under one thread lock and the flock `tells.lock`; the page's events and the
diagnostics rows of a change go out inside it too, once the file is written (a change that raises or cannot be
written sends and logs nothing), so the page, `documents` and the log agree on which state won.
A row names the token and the thread, never the Tell's text: the message is built when it is listed.

    queue(address, cid, row, by, member, thread)   put a Tell in the file; raises Refused
    take(address, row, got, message)        the Tells listed to `row` for this document, `message(c, t)` their words; the first listing marks them seen
    pending(row)                            the documents where `row` has a Tell waiting
    end(address, cid, how, ...)             a Tell ends: done, cancelled
    waits(address, member)                  what the page is told: [{id, to, state}] of the reader's own
    sweep()                                 the Tells of a token no longer there end as cancelled
    watch()                                 the watcher's pass: sweep, and a thread closed from outside ends its Tell
    end_root(name, reason)                  every Tell on the documents of a root ends as cancelled (the root was forgotten)
"""
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from .. import comments as rdc
from .. import paths
from . import targets
from .roots import Address
from .state import STAMP_FORMAT, TokenRow, file_locked, read_json, write_json

HAS_IT = "{agent} has this comment waiting already: cancel it first, or reply in the thread."
GONE = targets.REVOKED


REREAD = 0.1          # seconds between the two reads of a document where a thread looks gone

EVENTS = ("tell-queued", "tell-seen", "tell-done", "tell-cancelled")


class Owned(dict):
    """An event's data that remembers whose Tell it is (`member`: a member's id, None for the hub person), so a
    stream tells a page of its own reader's Tells only. It is a dict in every other way."""

    def __init__(self, data: dict, member):
        super().__init__(data)
        self.member = member


class Refused(Exception):
    """A Tell that cannot wait: one sentence and the HTTP status."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _stale(t: dict, c) -> bool:
    """The thread is gone or closed, or it is another comment now: the Tell has nothing left to say."""
    return c is None or c.status != "open" or _recycled(t, c)


def _recycled(t: dict, c) -> bool:
    """The row remembers whose comment it was told about and when it was written (`thread_by`, `thread_at`, `thread_quote`: `at` is to the minute, so the quote tells two comments of one author apart): a
    thread id the file hands out again (`next_id` is the highest plus one) is another comment, and the old Tell
    is not its Tell. A row from before those two keys has nothing to compare and stays as it was."""
    return "thread_at" in t and (t.get("thread_by"), t["thread_at"], t.get("thread_quote")) != (c.by, c.at, c.quote)


def belongs(t: dict, row: TokenRow) -> bool:
    """The Tell's row is for this token (`TokenRow.is_pair`): a row with no `tid` matches no token that has an id."""
    return row.is_pair(t.get("token"), t.get("tid"))


def _file() -> Path:
    return paths.state_dir() / "tells.json"


class Waiting:
    def __init__(self, hub):
        self.hub = hub
        self._lock = threading.RLock()
        self._held = None            # the events and log rows of the change under way, sent once the file holds it (`_change`)

    def _change(self, change):
        """`change(rows)` on the file as it is now, under both locks; it returns `(result, save)`. The page's events
        of the change are held and sent after the write, still under the locks, so a snapshot (`waits`, which reads
        under the thread lock) never shows a state older than an event the page has heard."""
        with self._lock, file_locked("tells.lock"):
            rows = [r for r in read_json(_file(), []) if isinstance(r, dict)]
            filled = self._name_old_rows(rows)
            outer, held = self._held, []
            self._held = held
            try:
                result, save = change(rows)
                if save:
                    write_json(_file(), rows)
                elif filled:                       # the names only: a disk that will not take them fails no pass
                    try:
                        write_json(_file(), rows)
                    except OSError:
                        pass
            finally:
                self._held = outer
            for go in held:
                go()
            return result

    def _name_old_rows(self, rows: list) -> bool:
        """A row written before `agent` was kept (SPEC 9.8) has none: it takes the signed name its token has now, the one
        its page was told if the name has not changed since, and keeps it when the token goes (SPEC 9.8). An `agent` that is
        empty is as good as none. Nothing is written here: `_change` writes the names when it writes, or on its own once."""
        filled = False
        tokens = None
        for t in rows:
            if not t.get("agent"):
                tokens = self.hub.tokens.list() if tokens is None else tokens
                row = next((r for r in tokens if belongs(t, r)), None)
                if row is not None:
                    t["agent"] = row.signed(self.hub.person, self.hub.proxy)
                    filled = True
        return filled

    # ── what ends and what shows ─────────────────────────────────────────────
    def _live(self) -> list:
        return [r for r in self.hub.tokens.list() if r.client is not None and not r.invalid]

    def _name(self, t: dict) -> str:
        """The agent as the page was told at `tell-queued`: the name kept in the row, whatever the token or the person
        is called now. A row with none (its token was gone before the first pass that names it) has the token's name."""
        return str(t.get("agent") or t.get("token", ""))

    def _emit(self, address: str, name: str, data: dict, member=None):
        self._after(lambda: self._send(address, name, data, member))

    def _record(self, kind: str, address: str, **fields):
        self._after(lambda: self.hub.record(kind, address, **fields))

    def _after(self, go):
        """Inside `_change`, `go()` waits until the file holds the change; outside it, it runs at once."""
        if self._held is not None:
            self._held.append(go)
        else:
            go()

    def _send(self, address: str, name: str, data: dict, member=None):
        e = self.hub.entries.get(address)
        if e is not None:
            e.bus.publish(name, Owned(data, member))

    def _end(self, rows: list, gone: list, how: str, **extra):
        """Inside `_change`: take `gone` out of `rows`, and tell the page and the log of each."""
        for t in gone:
            rows.remove(t)
            data = {"id": t["thread"], **({"seen": bool(t["seen"])} if how == "cancelled" else {}), **extra,
                    "agent": self._name(t)}
            self._emit(t["doc"], f"tell-{how}", data, t.get("member"))
            self._record(f"tell-{how}", t["doc"], thread=t["thread"], token=t["token"], tid=t["tid"],
                            **{k: v for k, v in extra.items() if k == "reason"})

    def _revoked(self, rows: list):
        live = self._live()
        self._end(rows, [t for t in rows if not any(belongs(t, r) for r in live)], "cancelled", reason="revoked")

    def sweep(self):
        def change(rows):
            n = len(rows)
            self._revoked(rows)
            return None, len(rows) != n
        self._change(change)

    def watch(self):
        """One look of the watcher (8.9): a token revoked by the CLI, and a thread resolved or deleted from outside
        (the CLI, a hand edit), end their Tells now, so a page that stays open stops saying it waits. A document the
        hub holds no entry for, one that cannot be read and one that changes between two reads (a save under way) are left
        alone: the next pass or listing (`take`) judges them."""
        rows = [t for t in read_json(_file(), [], aside=False) if isinstance(t, dict)]
        if not rows:
            return
        # Each document is read under its Live Document's locks (the name's, 9.11, and its own) before `_change` takes
        # `tells.lock`, so no lock is asked for while that one is held. An editor outside the hub holds none of our locks,
        # so a thread that looks gone is read for again before it ends anything (`_judged_read`). Only rows there when
        # a document was read are judged from that read.
        got = {}
        for address in {t["doc"] for t in rows}:
            e = self.hub.entries.get(address)
            try:
                got[address] = None if e is None else self._judged_read(e, [t for t in rows if t["doc"] == address])
            except Exception:
                got[address] = None
        ids = {t["id"] for t in rows}

        def change(rows):
            n = len(rows)
            self._revoked(rows)
            for t in [t for t in rows if t["id"] in ids]:
                parsed = got.get(t["doc"])
                if parsed is not None and _stale(t, parsed.by_id(t["thread"])):
                    self._end(rows, [t], "cancelled", reason="closed")
            return None, len(rows) != n
        self._change(change)

    def _judged_read(self, e, rows: list):
        """The document's comments, parsed, or None when nothing may be ended from this read. A thread that looks
        gone is read again after `REREAD` seconds, and ends only if the text is the same both times: an outside
        editor's save, caught part way or between its truncate and its write, is not the same file a moment later; a file
        left empty for good is."""
        text = e.live.read_now()
        got = rdc.parse(text)
        if any(_stale(t, got.by_id(t["thread"])) for t in rows):
            self._pause()
            if e.live.read_now() != text:
                return None
        return got

    def _pause(self):
        time.sleep(REREAD)

    # ── queued ───────────────────────────────────────────────────────────────
    def queue(self, address: str, cid: str, row: TokenRow, by: str, member, thread) -> dict:
        """The Tell waits for `row`'s agent. A second one for the thread and the agent is refused 409. `thread` is
        the comment it is about: its author and time are kept in the row (see `_recycled`)."""
        def change(rows):
            self._revoked(rows)
            if not any(r.is_pair(row.name, row.id) for r in self.hub.tokens.list()):
                raise Refused(409, GONE.format(agent=row.signed(self.hub.person, self.hub.proxy)))
            if self.hub.roots.get(Address.parse(address).root) is None:      # forgotten meanwhile: `end_root` came first
                raise Refused(409, "The folder of this document was forgotten.")
            name = row.signed(self.hub.person, self.hub.proxy)
            had = next((t for t in rows if t["doc"] == address and t["thread"] == cid and belongs(t, row)), None)
            if had is not None:
                raise Refused(409, HAS_IT.format(agent=self._name(had)))      # as its page's line names it
            t = {"id": str(uuid.uuid4()), "doc": address, "thread": cid, "token": row.name, "tid": row.id,
                 "by": by, "at": time.strftime(STAMP_FORMAT), "seen": None,
                 "agent": name}              # the name the page was told, the one every event and snapshot of the Tell uses (9.8)
            if thread is not None:
                t["thread_by"], t["thread_at"], t["thread_quote"] = thread.by, thread.at, thread.quote
            if member is not None:
                t["member"] = member.id
            rows.append(t)
            self._emit(address, "tell-queued", {"id": cid, "agent": name}, t.get("member"))
            self._record("tell-queued", address, thread=cid, token=row.name, tid=row.id, by=by)
            return t, True
        return self._change(change)

    # ── listed ───────────────────────────────────────────────────────────────
    def pending(self, row: TokenRow) -> set:
        """The addresses where `row` has a Tell waiting (a look, nothing changes)."""
        return {t["doc"] for t in read_json(_file(), [], aside=False)
                if isinstance(t, dict) and belongs(t, row)}

    def take(self, address: str, row: TokenRow, got, message) -> list:
        """The Tells listed to `row` on `address`; `got` is the document's parsed comments and `message(c, t)`
        the words of a Tell. A thread no longer open ends the Tell. The first listing marks it seen."""
        def change(rows):
            self._revoked(rows)
            out, save = [], False
            for t in [t for t in rows if t["doc"] == address and belongs(t, row)]:
                c = got.by_id(t["thread"])
                if _stale(t, c):
                    self._end(rows, [t], "cancelled", reason="closed")
                    save = True
                    continue
                if t["seen"] is None:
                    t["seen"] = time.strftime(STAMP_FORMAT)
                    self._emit(address, "tell-seen", {"id": t["thread"], "agent": self._name(t)}, t.get("member"))
                    self._record("tell-seen", address, thread=t["thread"], token=t["token"], tid=t["tid"])
                    save = True
                out.append({"id": t["id"], "thread": t["thread"], "message": message(c, t), "by": t["by"],
                            "at": t["at"]})
            return out, save
        return self._change(change)

    # ── ended ────────────────────────────────────────────────────────────────
    def end(self, address: str, cid: str, how: str, *, row: TokenRow | None = None, member=None, reason=None,
            only_member: bool = False) -> list:
        """The Tells of this thread end (`how`: done, cancelled). `row`: only that token's (an action reply
        ends its own agent's Tell, no other). `only_member`: only the reader's own (`member` None is the hub
        person), for a Cancel from a page. The Tells ended, as they were."""
        def change(rows):
            gone = [t for t in rows if t["doc"] == address and t["thread"] == cid
                    and (row is None or belongs(t, row))
                    and (not only_member or t.get("member") == (member.id if member else None))]
            extra = {"reason": reason} if reason else {}      # `seen` is each row's own, set in `_end` (24)
            self._end(rows, gone, how, **extra)
            return gone, bool(gone)
        return self._change(change)

    def end_root(self, name: str, reason: str):
        """Every Tell on the documents of the root `name` ends as cancelled (its folder was forgotten), whether the
        hub still holds an entry for the document or not; the other roots' Tells, of any token, stay."""
        prefix = Address.prefix(name)

        def change(rows):
            gone = [t for t in rows if t["doc"].startswith(prefix)]
            self._end(rows, gone, "cancelled", reason=reason)
            return gone, bool(gone)
        self._change(change)

    # ── the page ─────────────────────────────────────────────────────────────
    def waits(self, address: str, member=None, sweep: bool = True) -> list:
        """`[{id, to, state}]` of the reader's own Tells on this document: `queued`, or `seen`. `sweep` False is a
        look that changes nothing, for a caller that holds a document's lock."""
        if sweep:
            self.sweep()
        mine = member.id if member else None
        with self._lock:                                  # not the document's lock: a change holds this one while it writes
            rows = [r for r in read_json(_file(), [], aside=False) if isinstance(r, dict)]
            self._name_old_rows(rows)                     # in the answer only, so an old row has its signed name before the first pass
        return [{"id": t["thread"], "to": self._name(t), "state": "queued" if t["seen"] is None else "seen"}
                for t in rows if t.get("doc") == address and t.get("member") == mine]
