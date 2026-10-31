"""
sheafmd.hub.relay — the relay of a forked session (SPEC 9.14, sheaf#117): a Tell pressed on a sheaf whose live
session runs on a member's machine reaches that session through `sheaf relay`, which the member runs beside it.

    Relays()                        the hub's relays: the tokens on disk, the queue and the open streams in memory
    .issue(member, doc, session)    a new relay token for that one fork, which ends the sheaf's older ones
    .find(sha256)                   the row of a token the hub holds, else None
    .revoke(doc)                    end every token of the sheaf: how many there were
    .put(doc, session, tell)        queue a Tell for the fork, or Full past QUEUE_MAX open on the sheaf: the Tells
                                    of another session it took off the queue, [(doc, Tell)]
    .open(doc, session)             the Tells queued for that fork and not yet acked, oldest first
    .ack(doc, id)                   take one off the queue: the Tell, or None when it is not queued
    .expire()                       take off every Tell queued TTL seconds ago or more: [(doc, Tell)]
    .drop(doc)                      take every Tell of the sheaf off the queue, its fork no longer live: [(doc, Tell)]
    .connect(doc, session, accept)  a stream for the relay, in the connected set until it closes
    .connected(doc, session)        the token's member while a relay of that fork has a stream open, or closed one
                                    less than GRACE seconds ago (it is reconnecting), else None
    .lapsed()                       the forks whose last stream closed GRACE seconds ago or more: [(doc, session)]
    .end(doc, but)                  tell every stream of the sheaf (but the session `but`) it is `gone`
    .unknown()                      the count of made-up tokens to write in a row now, or 0 within the minute

A relay token is `sheaf_relay_` and 43 base64url characters. The verifier hands the hub its hex sha256
(`X-Sheaf-Relay`), never the token; `relays.json` beside `tokens.json` (0600) keeps that hash, so a restart
does not cut the fork off. Neither the token nor its hash is ever written in a row: a row carries the relay id.
"""
import hashlib
import hmac
import re
import secrets
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .. import paths
from . import events
from .state import file_locked, read_json, write_json

PREFIX = "sheaf_relay_"
HASH_RE = re.compile(r"[0-9a-f]{64}")
QUEUE_MAX = 20                  # Tells open on one sheaf at a time: bounds the hub's memory
TTL = 3600                      # seconds a Tell waits for its ack before it is dropped
GRACE = 30                      # seconds a relay whose stream closed still counts as connected: its reconnect
NO_GOOD = "This relay token is no good: fork the session again."
FULL = "Twenty Tells on this sheaf are waiting for the session on the member's machine: wait for them first."
EXPIRED = "The session on the member's machine did not take this Tell within an hour; the comment is written."
_clock = time.time


class Full(Exception):
    pass


@dataclass
class Tell:
    id: str                     # a UUID: the envelope's msg_id, the same on every delivery of this Tell
    thread: str                 # the comment's thread
    message: str                # prompts.tell's text, built when the Tell was pressed
    by: str                     # who pressed it, as a row names them
    queued: float = 0.0


def digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


class _Stream(events.Subscription):
    """A relay's stream: it leaves the connected set when the server closes it."""
    def __init__(self, relays, key, accept):
        super().__init__(relays._bus, accept)
        self._relays, self.key = relays, key
        self.on_close = None
        self.fresh = False              # set by Relays.connect: the first stream of its fork, no reconnect

    def close(self):
        was = self.closed
        super().close()
        if not was:
            self._relays._left(self)
            if self.on_close is not None:
                self.on_close()


class Relays:
    def __init__(self):
        self._lock = threading.Lock()
        self._queues: dict = {}             # doc -> {session, tells: {id: Tell}}
        self._streams: dict = {}            # (doc, session) -> set of _Stream
        self._gaps: dict = {}               # (doc, session) -> when its last stream closed, for GRACE seconds
        self._bus = events.Bus()            # the streams' own bus: never a document's, which tabs share
        self._unknown = [None, 0]

    # ── the tokens ──────────────────────────────────────────────────────────
    @staticmethod
    def path() -> Path:
        return paths.state_dir() / "relays.json"

    @contextmanager
    def _locked(self):
        with file_locked("relays.lock"):
            yield

    def _rows(self) -> list:
        return [r for r in read_json(self.path(), []) if isinstance(r, dict)]

    def issue(self, member: str, doc: str, session: str) -> tuple[str, str]:
        """(the token, its relay id). The sheaf's older tokens go: one fork is live at a time."""
        token = PREFIX + secrets.token_urlsafe(32)
        rid = secrets.token_hex(4)
        with self._locked():
            rows = [r for r in self._rows() if r.get("doc") != doc]
            rows.append({"id": rid, "sha256": digest(token), "member": member, "doc": doc, "session": session,
                         "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(_clock()))})
            write_json(self.path(), rows)
        self.end(doc, but=session)
        return token, rid

    def find(self, sha256) -> dict | None:
        if not isinstance(sha256, str) or not HASH_RE.fullmatch(sha256):
            return None
        want = sha256.encode("ascii")
        found = None
        for r in self._rows():          # every row compared, so the time taken does not say which matched
            if isinstance(r.get("sha256"), str) and hmac.compare_digest(r["sha256"].encode("utf-8"), want):
                found = r
        if found is None or not all(isinstance(found.get(k), str) for k in ("id", "member", "doc", "session")):
            return None
        return found

    def revoke(self, doc: str) -> int:
        with self._locked():
            rows = self._rows()
            kept = [r for r in rows if r.get("doc") != doc]
            if len(kept) != len(rows):
                write_json(self.path(), kept)
        self.end(doc)
        return len(rows) - len(kept)

    # ── the queue ───────────────────────────────────────────────────────────
    def put(self, doc: str, session: str, tell: Tell) -> list:
        """Queue `tell` for the fork `session`. The Tells queued for another session of the sheaf (its live session
        changed without a fork report, by hand) leave the queue and are given back, [(doc, Tell)], to be dropped."""
        with self._lock:
            q = self._queues.get(doc)
            old = []
            if q is None or q["session"] != session:
                old = [(doc, t) for t in q["tells"].values()] if q else []
                q = self._queues[doc] = {"session": session, "tells": {}}
            if len(q["tells"]) >= QUEUE_MAX:
                raise Full(FULL)
            tell.queued = _clock()
            q["tells"][tell.id] = tell
            subs = list(self._streams.get((doc, session), ()))
        for s in subs:
            s.put("tell", {"id": tell.id, "message": tell.message})
        return old

    def open(self, doc: str, session: str) -> list:
        with self._lock:
            q = self._queues.get(doc)
            return list(q["tells"].values()) if q and q["session"] == session else []

    def ack(self, doc: str, id: str) -> Tell | None:
        with self._lock:
            q = self._queues.get(doc)
            return q["tells"].pop(id, None) if q else None

    def expire(self) -> list:
        now = _clock()
        out = []
        with self._lock:
            for doc, q in self._queues.items():
                for id in [i for i, t in q["tells"].items() if t.queued + TTL <= now]:
                    out.append((doc, q["tells"].pop(id)))
        return out

    def drop(self, doc: str) -> list:
        """Take every Tell of the sheaf off the queue: its fork is no longer live. [(doc, Tell)]."""
        with self._lock:
            q = self._queues.pop(doc, None)
        return [(doc, t) for t in q["tells"].values()] if q else []

    # ── the streams ─────────────────────────────────────────────────────────
    def connect(self, doc: str, session: str, accept=None) -> _Stream:
        """A stream that holds `hello` and every Tell still queued for the fork, then what is put after."""
        s = _Stream(self, (doc, session), accept)
        with self._lock:
            # New to the page: no stream of the fork open, and none closed within the grace (a reconnect).
            s.fresh = not self._streams.get((doc, session)) and self._gaps.pop((doc, session), None) is None
            self._streams.setdefault((doc, session), set()).add(s)
            q = self._queues.get(doc)
            queued = list(q["tells"].values()) if q and q["session"] == session else []
        s.put("hello", {"doc": doc, "session": session})
        for t in queued:
            s.put("tell", {"id": t.id, "message": t.message})
        return s

    def _left(self, s: _Stream):
        with self._lock:
            subs = self._streams.get(s.key)
            if subs is not None:
                subs.discard(s)
                if not subs:
                    del self._streams[s.key]
                    self._gaps[s.key] = _clock()

    def connected(self, doc: str, session: str) -> str | None:
        """The member of the fork's token while a relay of it has a stream open and the token is on disk, else None.
        A stream stays open after `sheaf relay revoke` in another process until its next event, so the disk says."""
        with self._lock:
            gap = self._gaps.get((doc, session))
            if not self._streams.get((doc, session)) and (gap is None or _clock() - gap >= GRACE):
                return None
        row = next((r for r in self._rows() if r.get("doc") == doc and r.get("session") == session), None)
        return row["member"] if row is not None and isinstance(row.get("member"), str) else None

    def lapsed(self) -> list:
        """The forks whose relay has had no stream for GRACE seconds: [(doc, session)], each given once."""
        now = _clock()
        with self._lock:
            out = [k for k, t in self._gaps.items() if now - t >= GRACE]
            for k in out:
                del self._gaps[k]
        return out

    def end(self, doc: str, but: str | None = None):
        with self._lock:
            subs = [s for (d, sid), ss in self._streams.items() if d == doc and sid != but for s in ss]
        for s in subs:
            s.put("gone", {"doc": doc})

    def unknown(self) -> int:
        now = _clock()
        with self._lock:
            self._unknown[1] += 1
            if self._unknown[0] is not None and now - self._unknown[0] < 60:
                return 0
            n, self._unknown = self._unknown[1], [now, 0]
            return n
