"""
sheafmd.hub.events — the event streams to the open tabs (SPEC 8.8).

A Bus belongs to one document. A tab that opens `/_/live?doc=` gets a Subscription: a queue
that holds `hello` first and then only what was published after it connected. The handler
returns the Subscription; the server turns it into `text/event-stream` bytes (`frame`),
with `retry: 2000` first and a `: keepalive` comment every 25 s. Tests read the queue
directly, no socket.
"""
import json
import queue
import threading
import time

from .. import diagnostics

RETRY_MS = 2000
KEEPALIVE_SECONDS = 25


def frame(name: str, data) -> bytes:
    """One event as the bytes of an event stream. `data` is one line of JSON."""
    return f"event: {name}\ndata: {json.dumps(data)}\n\n".encode("utf-8")


PREAMBLE = f"retry: {RETRY_MS}\n\n".encode("ascii")
KEEPALIVE = b": keepalive\n\n"


ENDS = ("hub-stopping", "signed-out", "gone")     # the last event of a tab's stream (8.8): nothing is queued after one


class Renamed:
    """What `accept` returns to send another event in place of the one read: `gone` to a member who can no longer
    open the document (8.12)."""
    def __init__(self, name: str, data):
        self.name, self.data = name, data


class Subscription:
    def __init__(self, bus: "Bus", accept=None):
        """`accept(name, data)` returns what this stream is sent of an event, or None to send it
        nothing: a member of proxy mode is told less than the hub's person (9.9). It runs when the
        stream reads the event, on the stream's own thread, never on the one that publishes: a
        member's stream asks whether the document is theirs, which can ask git, and the thread that
        publishes hands the event to every stream."""
        self._bus = bus
        self._q: queue.Queue = queue.Queue()
        self._accept = accept
        self.closed = False
        self.ended = False       # it was sent one of `ENDS`, the last event of its stream (8.8): it gives nothing more
        self.on_put = None       # called after every event queued: a `Shared` wakes its writer with it

    def put(self, name: str, data):
        if not (self.closed or self.ended):
            self._q.put((name, data))
            on_put = self.on_put     # read once: a leave on another thread can clear it between a check and a call
            if on_put is not None:
                on_put()

    def get(self, timeout: float | None = 0):
        """The next (name, data) this stream is sent, or None when none arrived within `timeout`
        seconds. An event `accept` refuses is skipped, and the wait goes on to the next. Once it has given one of `ENDS`,
        it gives nothing more, whatever was queued behind it: a publisher that held the document's entry from before its
        `gone` (`_tell_grants`, a waiting Tell) reaches no tab after it (ticket 212 A). The end is the event the stream
        is sent, as `accept` answers it, never the one published: a member's stream refuses `signed-out`, and goes on."""
        if self.ended:
            return None
        deadline = time.monotonic() + timeout if timeout else None
        while True:
            try:
                if deadline is None:
                    name, data = self._q.get_nowait()
                else:
                    name, data = self._q.get(timeout=max(0.0, deadline - time.monotonic()))
            except queue.Empty:
                return None
            if self._accept is not None:
                data = self._accept(name, data)
                if data is None:
                    continue
                if isinstance(data, Renamed):
                    name, data = data.name, data.data
            self.ended = name in ENDS
            return name, data

    def drain(self) -> list:
        """Everything waiting now, oldest first."""
        out = []
        while (e := self.get(0)) is not None:
            out.append(e)
        return out

    def close(self):
        if not self.closed:
            self.closed = True
            self._bus._drop(self)


class Bus:
    def __init__(self, on_open=None):
        self._lock = threading.Lock()
        self._subs: set[Subscription] = set()
        self._on_open = on_open

    def subscribe(self, hello=None, accept=None) -> Subscription:
        """A new stream. `hello` is called with the tab count including this one and returns
        the data of the first event; it is queued before anything else can be. `accept`: see
        Subscription."""
        sub = Subscription(self, accept)
        with self._lock:
            self._subs.add(sub)
            if hello is not None:
                sub.put("hello", hello(len(self._subs)))
        if self._on_open:
            self._on_open()
        return sub

    def publish(self, name: str, data):
        with self._lock:
            subs = list(self._subs)
        for s in subs:
            try:
                s.put(name, data)
            except Exception as e:   # one stream's failure is that stream's: the others still get the event
                diagnostics.record("hub", "publish-failed", event=name, error=str(e)[:300] or type(e).__name__)

    def _drop(self, sub: Subscription):
        with self._lock:
            self._subs.discard(sub)

    def count(self) -> int:
        with self._lock:
            return len(self._subs)


class Shared:
    """The streams of every tab of one browser over one connection (ticket 160). A browser opens
    at most six HTTP/1.1 connections to a host, and every open page held one: with six tabs, the
    seventh page and every request after it waited for ever. One tab of the browser now holds
    `/_/live?shared=` for all of them (page/live.js) and adds and drops the others' streams with
    `/_/live/join` and `/_/live/leave`.

    A tab's stream is a Subscription on its own Bus, as it was: the Bus still counts the tab.
    What it is sent goes out as the event `m`, `{"k": key, "e": name, "d": data}`: `open` when it
    is joined (or `refused` with the status a stream of its own was answered with), then its own
    events. Its last event (`ENDS`) drops it from here; the connection stays open, for the others."""
    ENDS = ENDS                      # the name page/live.js points to

    def __init__(self, owner=None):
        self.owner = owner               # the member id the stream was opened by: no other may join it
        self._lock = threading.Lock()
        self._subs: dict = {}            # key -> Subscription
        self._out: queue.Queue = queue.Queue()
        self._last = None                # the key served last: the next look starts after it
        self._wake = threading.Condition()
        self._news = 0                   # counts what was queued, so a look that missed one is not waited out
        self.closed = False

    def _told(self):
        with self._wake:
            self._news += 1
            self._wake.notify_all()

    def join(self, key: str, sub) -> bool:
        """Adds the stream `sub` under `key`, or the refusal status a stream of its own was answered
        with. A key joined again replaces its stream. False when this stream is closed: `sub` is
        closed and nothing was added."""
        with self._lock:
            old = self._subs.pop(key, None)
            if self.closed:
                if not isinstance(sub, int):
                    sub.close()
                return False
            if isinstance(sub, int):
                self._out.put(("m", {"k": key, "e": "refused", "d": {"status": sub}}))
            else:
                self._out.put(("m", {"k": key, "e": "open", "d": {}}))
                self._subs[key] = sub
                sub.on_put = self._told
        self._told()                     # the events the stream holds already (its `hello`) are waiting too
        if old is not None:
            old.on_put = None
            old.close()
        return True

    def leave(self, key: str):
        with self._lock:
            sub = self._subs.pop(key, None)
        if sub is not None:
            sub.on_put = None
            sub.close()

    def keys(self) -> list:
        with self._lock:
            return list(self._subs)

    def _poll(self):
        try:
            return self._out.get_nowait()
        except queue.Empty:
            pass
        with self._lock:
            subs = list(self._subs.items())
        # Start after the tab served last, so one that receives events faster than they go out does not keep the
        # tabs behind it waiting.
        at = next((i + 1 for i, (key, _) in enumerate(subs) if key == self._last), 0)
        for key, sub in subs[at:] + subs[:at]:
            got = sub.get(0)
            if got is None:
                continue
            name, data = got
            if name in ENDS:
                with self._lock:
                    if self._subs.get(key) is sub:
                        del self._subs[key]
                sub.close()
            self._last = key
            return "m", {"k": key, "e": name, "d": data}
        return None

    def get(self, timeout: float | None = 0):
        deadline = time.monotonic() + (timeout or 0)
        while True:
            with self._wake:
                seen = self._news
            got = self._poll()
            if got is not None or time.monotonic() >= deadline:
                return got
            with self._wake:
                # Nothing is looked at again until a stream queues something: an event queued since `seen` was
                # counted skips the wait.
                self._wake.wait_for(lambda: self._news != seen, max(0.0, deadline - time.monotonic()))

    def drain(self) -> list:
        out = []
        while (e := self._poll()) is not None:
            out.append(e)
        return out

    def close(self):
        with self._lock:
            if self.closed:
                return
            self.closed = True
            subs, self._subs = list(self._subs.values()), {}
        for sub in subs:
            sub.on_put = None
            sub.close()
        self._told()                     # a writer waiting on it looks once more
