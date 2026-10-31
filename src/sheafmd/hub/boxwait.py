"""
sheafmd.hub.boxwait — the wait of each Ask and Tell the hub drops for James's window (SPEC 9.12, sheaf#115). The
hub runs no session for it, so nothing tells it the drop was taken: it keeps the drop open on the sheaf's page
until a reply lands in its thread, or until the Tell wait has passed. In memory: a restart forgets it.

    BoxWaits(clock)
    .add(doc, thread, kind, replies)   a drop of `kind` ("ask" or "tell") on `thread`, which held `replies` replies
    .open(doc, text)                   [{id, kind}] of the sheaf's drops with no reply since, in its text `text`;
                                       the others end
    .expire(wait)                      take off every drop older than `wait` seconds: [(doc, Wait)]
"""
import threading
from dataclasses import dataclass
from typing import Callable

from .. import comments as rdc


@dataclass
class Wait:
    thread: str
    kind: str
    replies: int
    at: float


class BoxWaits:
    def __init__(self, clock: Callable[[], float]):
        self._clock = clock
        self._lock = threading.Lock()
        self._waits: dict[str, dict[str, Wait]] = {}       # {doc: {thread: Wait}}

    def add(self, doc: str, thread: str, kind: str, replies: int):
        with self._lock:
            self._waits.setdefault(doc, {})[thread] = Wait(thread, kind, replies, self._clock())

    def open(self, doc: str, text: str) -> list:
        with self._lock:
            waits = self._waits.get(doc)
            if not waits:
                return []
            parsed = rdc.parse(text)
            for thread, w in list(waits.items()):
                c = parsed.by_id(thread)
                if c is None or len(c.replies) > w.replies:
                    del waits[thread]
            if not waits:
                del self._waits[doc]
            return [{"id": w.thread, "kind": w.kind} for w in (waits or {}).values()]

    def expire(self, wait: int) -> list:
        now, out = self._clock(), []
        with self._lock:
            for doc, waits in list(self._waits.items()):
                for thread, w in list(waits.items()):
                    if now - w.at > wait:
                        del waits[thread]
                        out.append((doc, w))
                if not waits:
                    del self._waits[doc]
        return out
