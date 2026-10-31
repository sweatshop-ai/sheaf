"""
sheafmd.hub.boxwait — the wait of each Ask and Tell the hub drops for James's window (SPEC 9.12, sheaf#115). The
hub runs no session for it, so nothing tells it the drop was taken: it keeps the drop open on the sheaf's page
until a reply lands in its thread, or until the Tell wait has passed. In memory: a restart forgets it.

    BoxWaits(clock)
    .add(doc, thread, kind, text)   a drop of `kind` ("ask" or "tell") on `thread`, the sheaf's text `text` then
    .pending(doc, text)             [{id, kind}] of the sheaf's drops with no reply in its text `text`; the drops
                                    answered there end
    .expire(wait, text_of)          end every drop answered in `text_of(doc)` (None: not read), then take off
                                    every drop older than `wait` seconds: [(doc, thread, Drop)]
"""
import threading
from dataclasses import dataclass
from typing import Callable

from .. import comments as rdc


@dataclass
class Drop:
    kind: str
    replies: int                # the thread's replies when it was dropped: one more is the answer
    at: float


class BoxWaits:
    def __init__(self, clock: Callable[[], float]):
        self._clock = clock
        self._lock = threading.Lock()
        self._drops: dict[str, dict[str, Drop]] = {}       # {doc: {thread: Drop}}

    def add(self, doc: str, thread: str, kind: str, text: str):
        c = rdc.parse(text).by_id(thread)
        if c is None:
            return
        with self._lock:
            self._drops.setdefault(doc, {})[thread] = Drop(kind, len(c.replies), self._clock())

    def pending(self, doc: str, text: str) -> list:
        with self._lock:
            self._settle(doc, text)
            return [{"id": thread, "kind": d.kind} for thread, d in self._drops.get(doc, {}).items()]

    def expire(self, wait: int, text_of: Callable[[str], str | None]) -> list:
        with self._lock:
            docs = list(self._drops)
        texts = {doc: text_of(doc) for doc in docs}         # read outside the lock: a read may wait on a write
        now, out = self._clock(), []
        with self._lock:
            for doc in docs:
                if texts[doc] is not None:
                    self._settle(doc, texts[doc])
                drops = self._drops.get(doc, {})
                for thread, d in list(drops.items()):
                    if now - d.at > wait:
                        del drops[thread]
                        out.append((doc, thread, d))
                if not drops:
                    self._drops.pop(doc, None)
        return out

    def _settle(self, doc: str, text: str):
        """End the drops of `doc` whose thread has a reply in `text`, or is gone from it. Under the lock."""
        drops = self._drops.get(doc)
        if not drops:
            return
        parsed = rdc.parse(text)
        for thread, d in list(drops.items()):
            c = parsed.by_id(thread)
            if c is None or len(c.replies) > d.replies:
                del drops[thread]
        if not drops:
            del self._drops[doc]
