"""The Tells that wait for an agent (SPEC 9.8, D26): `tells.json`, listed by the door's `documents`.

A Tell to an agent (ChatGPT, Claude.ai) cannot be pushed: it waits on the document until that agent next
calls `documents`. A row is kept with the token's stable `id` (`tid`) beside its name, so a token revoked and
made again under the same name never receives the old Tell. Every change of state (queued, seen, ended) is
made inside `Waiting._change`, under one thread lock and the flock `tells.lock`; the page's events and the
diagnostics rows of a change go out inside it too, so the page, `documents` and the log agree on which state won.
A row names the token and the thread, never the Tell's text: the message is built when it is listed.

    queue(address, cid, row, by, member)   put a Tell in the file; raises Refused
    take(address, row, got)                 the Tells listed to `row` for this document; the first listing marks them seen
    pending(row)                            the documents where `row` has a Tell waiting
    end(address, cid, how, ...)             a Tell ends: done, cancelled
    waits(address, member)                  what the page is told: [{id, to, state}] of the reader's own
    sweep()                                 the Tells of a token no longer there end as cancelled
"""
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from .. import paths
from .state import STAMP_FORMAT, TokenRow, file_locked, read_json, write_json

HAS_IT = "{agent} has this comment waiting already: cancel it first, or reply in the thread."
GONE = "{agent} can no longer reach this hub: its token was revoked. Pick another target."


class Refused(Exception):
    """A Tell that cannot wait: one sentence and the HTTP status."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _file() -> Path:
    return paths.state_dir() / "tells.json"


class Waiting:
    def __init__(self, hub):
        self.hub = hub
        self._lock = threading.RLock()

    def _change(self, change):
        """`change(rows)` on the file as it is now, under both locks; it returns `(result, save)`."""
        with self._lock, file_locked("tells.lock"):
            rows = [r for r in read_json(_file(), []) if isinstance(r, dict)]
            result, save = change(rows)
            if save:
                write_json(_file(), rows)
            return result

    # ── what ends and what shows ─────────────────────────────────────────────
    def _live_ids(self) -> set:
        return {(r.name, r.id) for r in self.hub.tokens.list() if r.client is not None and not r.invalid}

    def _name(self, t: dict) -> str:
        row = next((r for r in self.hub.tokens.list() if r.name == t.get("token") and r.id == t.get("tid")), None)
        return row.signed(self.hub.person, self.hub.proxy) if row is not None else str(t.get("token", ""))

    def _emit(self, address: str, name: str, data: dict):
        e = self.hub.entries.get(address)
        if e is not None:
            e.bus.publish(name, data)

    def _end(self, rows: list, gone: list, how: str, **extra):
        """Inside `_change`: take `gone` out of `rows`, and tell the page and the log of each."""
        for t in gone:
            rows.remove(t)
            data = {"id": t["thread"], **extra}
            self._emit(t["doc"], f"tell-{how}", data)
            self.hub.record(f"tell-{how}", t["doc"], thread=t["thread"], token=t["token"], tid=t["tid"],
                            **{k: v for k, v in extra.items() if k == "reason"})

    def _revoked(self, rows: list):
        live = self._live_ids()
        self._end(rows, [t for t in rows if (t.get("token"), t.get("tid")) not in live], "cancelled",
                  reason="revoked")

    def sweep(self):
        def change(rows):
            n = len(rows)
            self._revoked(rows)
            return None, len(rows) != n
        self._change(change)

    # ── queued ───────────────────────────────────────────────────────────────
    def queue(self, address: str, cid: str, row: TokenRow, by: str, member=None) -> dict:
        """The Tell waits for `row`'s agent. A second one for the thread and the agent is refused 409."""
        def change(rows):
            self._revoked(rows)
            if not any((r.name, r.id) == (row.name, row.id) for r in self.hub.tokens.list()):
                raise Refused(409, GONE.format(agent=row.signed(self.hub.person, self.hub.proxy)))
            name = row.signed(self.hub.person, self.hub.proxy)
            if any(t["doc"] == address and t["thread"] == cid and t["tid"] == row.id for t in rows):
                raise Refused(409, HAS_IT.format(agent=name))
            t = {"id": str(uuid.uuid4()), "doc": address, "thread": cid, "token": row.name, "tid": row.id,
                 "by": by, "at": time.strftime(STAMP_FORMAT), "seen": None}
            if member is not None:
                t["member"] = member.id
            rows.append(t)
            self._emit(address, "tell-queued", {"id": cid, "agent": name})
            self.hub.record("tell-queued", address, thread=cid, token=row.name, tid=row.id, by=by)
            return t, True
        return self._change(change)

    # ── listed ───────────────────────────────────────────────────────────────
    def pending(self, row: TokenRow) -> set:
        """The addresses where `row` has a Tell waiting (a look, nothing changes)."""
        return {t["doc"] for t in read_json(_file(), [], aside=False)
                if isinstance(t, dict) and t.get("tid") == row.id and t.get("token") == row.name}

    def take(self, address: str, row: TokenRow, got, message) -> list:
        """The Tells listed to `row` on `address`; `got` is the document's parsed comments and `message(c, t)`
        the words of a Tell. A thread no longer open ends the Tell. The first listing marks it seen."""
        def change(rows):
            self._revoked(rows)
            out, save = [], False
            for t in [t for t in rows if t["doc"] == address and t["tid"] == row.id and t["token"] == row.name]:
                c = got.by_id(t["thread"])
                if c is None or c.status != "open":
                    self._end(rows, [t], "cancelled", reason="closed")
                    save = True
                    continue
                if t["seen"] is None:
                    t["seen"] = time.strftime(STAMP_FORMAT)
                    self._emit(address, "tell-seen", {"id": t["thread"]})
                    self.hub.record("tell-seen", address, thread=t["thread"], token=t["token"], tid=t["tid"])
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
                    and (row is None or (t["tid"], t["token"]) == (row.id, row.name))
                    and (not only_member or t.get("member") == (member.id if member else None))]
            extra = {"seen": any(t["seen"] for t in gone)} if how == "cancelled" else {}
            if reason:
                extra["reason"] = reason
            self._end(rows, gone, how, **extra)
            return gone, bool(gone)
        return self._change(change)

    def end_document(self, address: str, reason: str):
        """Every Tell of a document ends as cancelled (its folder was forgotten)."""
        def change(rows):
            gone = [t for t in rows if t["doc"] == address]
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
        return [{"id": t["thread"], "to": self._name(t), "state": "queued" if t["seen"] is None else "seen"}
                for t in read_json(_file(), [], aside=False)
                if isinstance(t, dict) and t.get("doc") == address and t.get("member") == mine]
