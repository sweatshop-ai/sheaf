"""A test-only checker of the hub's lock order (SPEC 9.11, "One lock order"; `sheafmd.hub.lockorder.ORDER`).

`install()` wraps each lock of the hub in a recording one: the moves' lock, the admission lock, a name's lock and a
project's folders' lock, the hub's lock, a document's lock, a file lock (flock), a repo's commit lock, the stop lock, and
the state stores' thread locks. Each thread keeps the stack of what it holds; an acquisition of a lock whose place in
the order is before one the thread holds is a violation. It is recorded (a worker thread's exception may be swallowed)
and raised at the acquire, so the test that did it fails, and `check()` fails the test once more at its end.

Not wrapped: the flocks of `state.file_locked` (named files of the state folder, always innermost) and the
`Condition` of the session Tells' store, whose lock the condition holds."""
import contextlib
import threading
import traceback

from sheafmd.hub import lockorder

_HELD = threading.local()
VIOLATIONS: list = []


class LockOrderViolation(AssertionError):
    pass


def _stack() -> list:
    if not hasattr(_HELD, "stack"):
        _HELD.stack = []
    return _HELD.stack


def _before(held: list, kind: str, key, label: str):
    new = lockorder.ORDER.index(kind)
    for h_kind, h_key, h_label in held:
        old = lockorder.ORDER.index(h_kind)
        if (h_kind, h_key) == (kind, key):
            return              # the same lock again: re-entrant
        bad = old > new
        if old == new and kind == "name":
            # more than one name at once: only under the moves' lock, else in ascending order
            bad = not any(k == "moves" for k, _, _ in held) and key < h_key
        if bad:
            where = "".join(traceback.format_stack(limit=18)[:-4])
            msg = (f"lock order: {label} ({kind}) taken while holding {h_label} ({h_kind}); "
                   f"the order is {' < '.join(lockorder.ORDER)}\n{where}")
            VIOLATIONS.append(msg)
            raise LockOrderViolation(msg)


class Checked:
    """A lock that records its holder. `inner` is the real lock; `kind` a name in `lockorder.ORDER`."""

    def __init__(self, inner, kind: str, label: str = ""):
        self.inner, self.kind, self.label = inner, kind, label or kind
        self.key = id(inner)

    def acquire(self, blocking=True, timeout=-1):
        _before(_stack(), self.kind, self.key, self.label)
        got = self.inner.acquire(blocking, timeout)
        if got:
            _stack().append((self.kind, self.key, self.label))
        return got

    def release(self):
        s = _stack()
        for i in range(len(s) - 1, -1, -1):
            if s[i][:2] == (self.kind, self.key):
                del s[i]
                break
        self.inner.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *a):
        self.release()

    def locked(self):
        return self.inner.locked()

    def __getattr__(self, name):
        return getattr(self.inner, name)


@contextlib.contextmanager
def _recorded(kind: str, key, label: str):
    _before(_stack(), kind, key, label)
    _stack().append((kind, key, label))
    try:
        yield
    finally:
        s = _stack()
        for i in range(len(s) - 1, -1, -1):
            if s[i][:2] == (kind, key):
                del s[i]
                break


def install(monkeypatch):
    from sheafmd import source
    from sheafmd.hub import commits, core, live, moves, place, state

    VIOLATIONS.clear()
    monkeypatch.setattr(moves, "_LOCK", Checked(moves._LOCK, "moves", "the moves' lock"))

    real_locked = place._locked

    @contextlib.contextmanager
    def locked(key):
        kind = "folders" if key[1].endswith("/") else "name"
        with _recorded(kind, key, f"the {kind} lock {key[1]}"), real_locked(key):
            yield
    monkeypatch.setattr(place, "_locked", locked)

    real_enter, real_exit = source.file_lock.__enter__, source.file_lock.__exit__

    def enter(self):
        _before(_stack(), "file", str(self.paths[0]), f"the file lock {self.paths[0].name}")
        got = real_enter(self)
        _stack().append(("file", str(self.paths[0]), f"the file lock {self.paths[0].name}"))
        return got

    def exit_(self, *a):
        s = _stack()
        for i in range(len(s) - 1, -1, -1):
            if s[i][:2] == ("file", str(self.paths[0])):
                del s[i]
                break
        return real_exit(self, *a)
    monkeypatch.setattr(source.file_lock, "__enter__", enter)
    monkeypatch.setattr(source.file_lock, "__exit__", exit_)

    real_hub_init = core.Hub.__init__

    def hub_init(self, *a, **k):
        real_hub_init(self, *a, **k)
        self.admit = Checked(self.admit, "admit", "the admission lock")
        self._lock = Checked(self._lock, "hub", "the hub's lock")
        self._stop_lock = Checked(self._stop_lock, "stop", "the stop lock")
        for name in ("forwards", "waiting_tells"):
            store = getattr(self, name, None)
            if store is not None and hasattr(store, "_lock"):
                store._lock = Checked(store._lock, "store", f"the {name} lock")
    monkeypatch.setattr(core.Hub, "__init__", hub_init)

    real_live_init = live.LiveDocument.__init__ if hasattr(live, "LiveDocument") else None
    if real_live_init is not None:
        def live_init(self, *a, **k):
            real_live_init(self, *a, **k)
            self._lock = Checked(self._lock, "doc", "the document's lock")
        monkeypatch.setattr(live.LiveDocument, "__init__", live_init)

    real_repo_lock = commits.Commits._repo_lock if hasattr(commits, "Commits") else None
    if real_repo_lock is not None:
        wrapped: dict = {}

        def repo_lock(self, folder):
            lock = real_repo_lock(self, folder)
            return wrapped.setdefault(id(lock), Checked(lock, "commit", "a repo's commit lock"))
        monkeypatch.setattr(commits.Commits, "_repo_lock", repo_lock)
    del state


def check():
    assert not VIOLATIONS, "\n\n".join(VIOLATIONS)
