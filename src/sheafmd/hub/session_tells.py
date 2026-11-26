"""The Tells that wait for a laptop session (SPEC 9.8): `session-tells.json`, answered by the door's `tells` long-poll.

A member's Tell on a page served by the tiroir whose target is a session on their laptop waits here until that
session asks for it. A session id is declared by the caller and never verified, so a row is bound to the token that
declared the session (its name and stable `id`, as a Tell to an agent is) and to the session id, both together: another
member's token, another laptop of the same member and a replayed id get nothing, a session resumed under the same id
from the same laptop gets it. No Tell expires; the member cancels it or retargets it to their own agent.

A row names the token, the session and the thread, never the Tell's text: the message is built when it is listed.

    queue(address, cid, row, session, by, member, thread)   put a Tell in the file; raises Refused
    take(row, session, wait, message)       long-poll: the Tells for this token and session, the first listing marks them seen
    end(address, cid, how, ...)             a Tell ends: done, cancelled
    waits(address, member)                  what the page is told: [{id, to, state, laptop}], state queued, waiting or seen
"""
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from .. import paths
from .state import STAMP_FORMAT, file_locked, read_json, write_json
from .waiting import Owned, Refused, belongs
from .writelog import MAX_SESSION, valid_session

MAX_WAIT = 25.0           # seconds a long-poll holds (the mods' call limit is 30)
LISTENING = 60.0          # seconds after its last poll a session still counts as listening
POLLS_PER_TOKEN = 2       # long-polls one token may hold at once (a session, and its resume overlapping it)
BUSY = "This token already holds {n} Tell polls. Wait for one to return, and ask again no sooner than {s:g} seconds."
RETRY_AFTER = 5.0
NOT_ONE = "A session id is one line of at most {n} characters."


def _file() -> Path:
    return paths.state_dir() / "session-tells.json"


def _bound(t: dict, row, session: str) -> bool:
    """The row is this token's and this session's, both together."""
    return belongs(t, row) and t.get("session") == session


class SessionTells:
    def __init__(self, hub, now=time.monotonic):
        self.hub = hub
        self._now = now
        self._lock = threading.RLock()
        self._wake = threading.Condition(self._lock)
        self._polling: dict = {}      # (token name, tid) -> long-polls held now
        self._heard: dict = {}        # (token name, tid, session) -> when it last polled, `_now()`
        self._logged: dict = {}       # the same key -> when a `tells-poll` row was last written for it

    # ── what the page and the log are told ───────────────────────────────────
    def _name(self, t: dict) -> str:
        """The name a Tell goes by on the page, in its rows and its events alike: the agent and the session."""
        return f"{t.get('agent') or t.get('token', '')} · {str(t.get('session', ''))[:8]}"

    def _send(self, address: str, name: str, data: dict, member=None):
        e = self.hub.entries.get(address)
        if e is not None:
            e.bus.publish(name, Owned(data, member))

    def _end(self, rows: list, gone: list, how: str, held: list, **extra):
        for t in gone:
            rows.remove(t)
            data = {"id": t["thread"], **({"seen": bool(t["seen"])} if how == "cancelled" else {}), **extra,
                    "agent": self._name(t)}
            held.append(lambda t=t, data=data: self._send(t["doc"], f"tell-{how}", data, t.get("member")))
            held.append(lambda t=t, how=how, extra=extra: self.hub.record(
                f"tell-{how}", t["doc"], thread=t["thread"], token=t["token"], tid=t["tid"], session=t["session"],
                **{k: v for k, v in extra.items() if k == "reason"}))

    def _change(self, change):
        """`change(rows, held)` on the file as it is now, under the thread lock and the flock; it returns `(result, save)`.
        What `held` holds (events, log rows) goes out once the file has the change."""
        with self._lock, file_locked("session-tells.lock"):
            rows = [r for r in read_json(_file(), []) if isinstance(r, dict)]
            held: list = []
            result, save = change(rows, held)
            if save:
                write_json(_file(), rows)
            for go in held:
                try:
                    go()
                except Exception:
                    self.hub.record_exception("session-tell-event-failed", None)
            if save:
                self._wake.notify_all()
            return result

    def _live(self) -> list:
        return [r for r in self.hub.tokens.list() if r.client is not None and not r.invalid]

    # ── queued ───────────────────────────────────────────────────────────────
    def queue(self, address: str, cid: str, row, session: str, by: str, member, thread) -> dict:
        """The Tell waits for `session` of `row`'s laptop. A second one for the thread and the session is refused 409."""
        def change(rows, held):
            if not any(r.is_pair(row.name, row.id) for r in self.hub.tokens.list()):
                raise Refused(409, "This laptop can no longer reach this hub: its token was revoked. Pick another target.")
            name = row.signed(self.hub.person, self.hub.proxy)
            if next((t for t in rows if t["doc"] == address and t["thread"] == cid and _bound(t, row, session)), None):
                raise Refused(409, f"{name} has this comment waiting already: cancel it first, or reply in the thread.")
            t = {"id": str(uuid.uuid4()), "doc": address, "thread": cid, "token": row.name, "tid": row.id,
                 "session": session, "by": by, "at": time.strftime(STAMP_FORMAT), "seen": None, "agent": name}
            if thread is not None:
                t["thread_by"], t["thread_at"], t["thread_quote"] = thread.by, thread.at, thread.quote
            if member is not None:
                t["member"] = member.id
            rows.append(t)
            state = "queued" if self.listening(t) else "waiting"
            held.append(lambda: self._send(address, "tell-queued", {"id": cid, "agent": self._name(t), "state": state, "laptop": True},
                                           t.get("member")))
            held.append(lambda: self.hub.record("tell-queued", address, thread=cid, token=row.name, tid=row.id,
                                                session=session, by=by))
            return t, True
        return self._change(change)

    # ── listed: the long-poll ────────────────────────────────────────────────
    def take(self, row, session: str, wait: float, message, gone=None) -> list:
        """The Tells waiting for this token's `session`, as they are listed to it: each marked seen at its first listing.
        With none, holds up to `wait` seconds (at most MAX_WAIT) for one. `message(t)` builds a Tell's words, None for
        a thread that is no longer open (the Tell then ends as cancelled), False for a page it cannot read now (it stays). `gone()` says the caller closed the connection: the poll then returns at once and
        frees its slot, so a reconnect is not refused for the rest of the wait. Raises Refused 429 past POLLS_PER_TOKEN."""
        if not valid_session(session):
            raise Refused(400, NOT_ONE.format(n=MAX_SESSION))
        key = (row.name, row.id)
        with self._lock:
            if self._polling.get(key, 0) >= POLLS_PER_TOKEN:
                raise Refused(429, BUSY.format(n=POLLS_PER_TOKEN, s=RETRY_AFTER))
            self._polling[key] = self._polling.get(key, 0) + 1
        try:
            end = self._now() + min(max(wait, 0.0), MAX_WAIT)
            while True:
                with self._lock:
                    now = self._now()
                    for k in [k for k, at in self._heard.items() if now - at >= LISTENING]:
                        del self._heard[k]              # no longer counts as listening: nothing to remember
                    self._heard[(*key, session)] = now
                    for k in [k for k, at in self._logged.items() if now - at >= LISTENING]:
                        del self._logged[k]
                    first = (*key, session) not in self._logged
                    if first:
                        self._logged[(*key, session)] = now
                if first:       # once a minute per session: whether a laptop session listens can be read from the log (9.8)
                    self.hub.record("tells-poll", token=row.name, tid=row.id, laptop_session=session)
                got = self._listed(row, session, message)
                left = end - self._now()
                if got or left <= 0 or (gone is not None and gone()):
                    return got
                with self._wake:                            # asleep until a Tell is queued (`_change` wakes it) or the time is up
                    self._wake.wait(min(left, 0.25 if gone is not None else 1.0))
        finally:
            with self._lock:
                self._polling[key] -= 1
                if not self._polling[key]:
                    del self._polling[key]

    def _listed(self, row, session: str, message) -> list:
        # The words are read outside the session lock (a page is read under its name's lock, which is taken first, 9.11),
        # then the file is changed under the lock for the Tells that are still there.
        with self._lock:
            mine = [t for t in read_json(_file(), [], aside=False) if isinstance(t, dict) and _bound(t, row, session)]
        said = {t["id"]: message(t) for t in mine}

        def change(rows, held):
            out, save = [], False
            for t in [t for t in rows if _bound(t, row, session) and t["id"] in said]:
                words = said[t["id"]]
                if words is False:
                    continue
                if words is None:
                    self._end(rows, [t], "cancelled", held, reason="closed")
                    save = True
                    continue
                if t["seen"] is None:
                    t["seen"] = time.strftime(STAMP_FORMAT)
                    held.append(lambda t=t: self._send(t["doc"], "tell-seen", {"id": t["thread"], "agent": self._name(t)},
                                                       t.get("member")))
                    held.append(lambda t=t: self.hub.record("tell-seen", t["doc"], thread=t["thread"], token=t["token"],
                                                            tid=t["tid"], session=session))
                    save = True
                out.append({"id": t["id"], "doc": t["doc"], "thread": t["thread"], "message": words, "by": t["by"],
                            "at": t["at"]})
            return out, save
        return self._change(change)

    # ── ended ────────────────────────────────────────────────────────────────
    def end(self, address: str, cid: str, how: str, *, row=None, session: str | None = None, member=None, reason=None,
            only_member: bool = False) -> list:
        """The Tells of this thread end (`how`: done, cancelled). `row` and `session`: only the Tells of that token's
        session (an action reply ends its own session's Tell, no other's). `only_member`: only the reader's own."""
        def change(rows, held):
            gone = [t for t in rows if t["doc"] == address and t["thread"] == cid
                    and (row is None or (belongs(t, row) and (session is None or t["session"] == session)))
                    and (not only_member or t.get("member") == (member.id if member else None))]
            self._end(rows, gone, how, held, **({"reason": reason} if reason else {}))
            return gone, bool(gone)
        return self._change(change)

    def rename(self, old: str, new: str):
        """The Tells to a laptop session on the page at `old` are on the page at `new`: a page that moved (9.11)."""
        def change(rows, held):
            hit = [t for t in rows if t["doc"] == old]
            for t in hit:
                t["doc"] = new
            return None, bool(hit)
        self._change(change)

    def end_page(self, address: str, reason: str):
        """Every Tell on the page at `address` ends as cancelled: the page is gone from here (it went to another tiroir)."""
        def change(rows, held):
            gone = [t for t in rows if t["doc"] == address]
            self._end(rows, gone, "cancelled", held, reason=reason)
            return gone, bool(gone)
        self._change(change)

    def end_root(self, name: str, reason: str):
        from .roots import Address
        prefix = Address.prefix(name)

        def change(rows, held):
            gone = [t for t in rows if t["doc"].startswith(prefix)]
            self._end(rows, gone, "cancelled", held, reason=reason)
            return gone, bool(gone)
        self._change(change)

    # ── the page ─────────────────────────────────────────────────────────────
    def listening(self, t: dict) -> bool:
        with self._lock:
            at = self._heard.get((t["token"], t["tid"], t["session"]))
        return at is not None and self._now() - at < LISTENING

    def waits(self, address: str, member=None) -> list:
        """`[{id, to, state, laptop}]` of the reader's own Tells to a session on this document. `queued` while the session listens,
        `waiting` while it does not ("waiting for <session>": it ended, or the laptop is off), `seen` once it took it."""
        mine = member.id if member else None
        with self._lock:
            rows = [r for r in read_json(_file(), [], aside=False) if isinstance(r, dict)]
        return [{"id": t["thread"], "to": self._name(t),
                 "state": "seen" if t["seen"] else ("queued" if self.listening(t) else "waiting"), "laptop": True}
                for t in rows if t.get("doc") == address and t.get("member") == mine]
