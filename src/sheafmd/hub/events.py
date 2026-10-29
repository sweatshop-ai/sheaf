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

RETRY_MS = 2000
KEEPALIVE_SECONDS = 25


def frame(name: str, data) -> bytes:
    """One event as the bytes of an event stream. `data` is one line of JSON."""
    return f"event: {name}\ndata: {json.dumps(data)}\n\n".encode("utf-8")


PREAMBLE = f"retry: {RETRY_MS}\n\n".encode("ascii")
KEEPALIVE = b": keepalive\n\n"


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

    def put(self, name: str, data):
        if not self.closed:
            self._q.put((name, data))

    def get(self, timeout: float | None = 0):
        """The next (name, data) this stream is sent, or None when none arrived within `timeout`
        seconds. An event `accept` refuses is skipped, and the wait goes on to the next."""
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
                    return data.name, data.data
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
            s.put(name, data)

    def _drop(self, sub: Subscription):
        with self._lock:
            self._subs.discard(sub)

    def count(self) -> int:
        with self._lock:
            return len(self._subs)
