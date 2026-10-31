"""
sheafmd.hub.boxwait — the wait of each Ask and Tell the hub drops for James's window (SPEC 9.12, sheaf#115). The
hub runs no session for it: it keeps the drop open on the sheaf's page until a reply lands in its thread, or until
the Tell wait has passed, and reads what the box's supervisor says of it in `<drop>.status` beside it (sheaf#139).
In memory: a restart forgets it.

    BoxWaits(clock)
    .add(doc, thread, kind, text, name)   a drop of `kind` ("ask" or "tell") on `thread`, the sheaf's text `text`
                                          then, written as the file `name` of `tell_dir`
    .pending(doc, text)                   [{id, kind, state}] of the sheaf's drops with no reply in its text `text`;
                                          the drops answered there end
    .expire(wait, text_of)                end every drop answered in `text_of(doc)` (None: not read), then take off
                                          every drop older than `wait` seconds: [(doc, thread, Drop)]
    .drops()                              [(doc, thread, Drop)] of every open drop
    .working(doc)                         whether James's session works on a drop of the sheaf: one `delivered`
    .end(doc, thread)                     take one off: whether it was open
    read_status(folder, name)             what `<name>.status` in `folder` says: None when there is none, BAD when
                                          it is not one regular file of the contract, else (state, error)
"""
import json
import os
import stat
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .. import comments as rdc

STATES = ("picked-up", "delivered", "failed")      # what the supervisor writes (thinkingtoo/tt-tiroir#251)
ERROR_MAX = 200
STATUS_MAX = 4096           # bytes: a status is one small object
BAD = "bad"


@dataclass
class Drop:
    kind: str
    replies: int                # the thread's replies when it was dropped: one more is the answer
    at: float
    name: str | None = None     # its file in `tell_dir`
    state: str = "sent"         # the supervisor's last word on it, read by the hub: "sent" until it says one
    ignored: bool = False       # a status of another shape was written down once


class BoxWaits:
    def __init__(self, clock: Callable[[], float]):
        self._clock = clock
        self._lock = threading.Lock()
        self._drops: dict[str, dict[str, Drop]] = {}       # {doc: {thread: Drop}}

    def add(self, doc: str, thread: str, kind: str, text: str, name: str | None = None):
        c = rdc.parse(text).by_id(thread)
        if c is None:
            return
        with self._lock:
            self._drops.setdefault(doc, {})[thread] = Drop(kind, len(c.replies), self._clock(), name)

    def pending(self, doc: str, text: str) -> list:
        with self._lock:
            self._settle(doc, text)
            return [{"id": thread, "kind": d.kind, "state": d.state}
                    for thread, d in self._drops.get(doc, {}).items()]

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

    def drops(self) -> list:
        with self._lock:
            return [(doc, thread, d) for doc, drops in self._drops.items() for thread, d in drops.items()]

    def working(self, doc: str) -> bool:
        with self._lock:
            return any(d.state == "delivered" for d in self._drops.get(doc, {}).values())

    def end(self, doc: str, thread: str) -> bool:
        with self._lock:
            drops = self._drops.get(doc, {})
            gone = drops.pop(thread, None) is not None
            if not drops:
                self._drops.pop(doc, None)
            return gone

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


def read_status(folder: Path, name: str):
    """`<name>.status` in `folder`, opened without following a link: None when there is none, BAD when it is not
    one regular file holding `{"state": <one of STATES>, "error"?: <text>}`, else (state, error), `error` one line
    of at most ERROR_MAX characters and only for `failed`. Keys it does not know are left alone."""
    try:
        fd = os.open(folder / f"{name}.status", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError:
        return BAD                  # a link (ELOOP), a file the hub may not read
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > STATUS_MAX:
            return BAD
        raw = os.read(fd, STATUS_MAX + 1)
    except OSError:
        return BAD
    finally:
        os.close(fd)
    try:
        got = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return BAD
    if not isinstance(got, dict) or got.get("state") not in STATES:
        return BAD
    error = got.get("error")
    if got["state"] != "failed" or not isinstance(error, str):
        return got["state"], ""
    return got["state"], " ".join(error.split())[:ERROR_MAX]
