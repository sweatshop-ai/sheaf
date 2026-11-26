"""
sheafmd.hub.sources — the sources this hub serves as roots, each through its Source service (ADR 0006, ticket 21).

A source is declared in `config.toml` as `[sources.<name>]` (`config.load_sources`) and is a root of the hub like a folder: its
documents are listed under its name and a page of it is `/<name>/<document>`. The hub holds, for each, the service's URL, the
hub's bearer for it and the name of a Theme. It holds no key to the site: the service does.

A source is `served`, or `unserved` with the words that say why. A service that reports another interface version is unserved
until the hub restarts, its error naming both versions; one that cannot be reached is asked again at the next call (the
outage cache and the write queue are ticket 22's). One source being unserved touches no other root.

Only the hub of the tiroir that owns a source serves it: on any other hub every declared source is unserved, with an error
that says so.
"""
import threading
import time
from dataclasses import dataclass

from .. import adapter as rda
from .. import config
from ..remote import RemoteSource, SourceError, VersionMismatch

RETRY_AFTER = 5.0       # seconds before an unreachable service is asked again

IDLE, PROBING, SERVED, FAILED, REFUSED = "idle", "probing", "served", "failed", "refused"


@dataclass(frozen=True)
class State:
    """Where a source stands: never asked (idle), its `info` call out (probing, holding that call's token), served, unreachable
    for now (failed, since `at`, asked again after RETRY_AFTER) or refused until the hub restarts."""
    kind: str = IDLE
    token: object = None
    client: RemoteSource | None = None
    error: str = ""                 # why it is unserved; "" when it is served
    shown: str = ""                 # what a member is told of it: never a path or an OS error
    at: float = 0.0


class Source:
    def __init__(self, name: str, decl: config.SourceDecl | None):
        self.name = name
        self.decl = decl
        self.state = State()            # read as it is, changed only by `Sources._move`, under its lock

    @property
    def served(self) -> bool:
        return self.state.kind == SERVED

    @property
    def client(self) -> RemoteSource | None:
        return self.state.client

    @property
    def error(self) -> str:
        return self.state.error

    @property
    def shown(self) -> str:
        return self.state.shown

    @property
    def sticky(self) -> bool:
        return self.state.kind == REFUSED

    @property
    def probing(self):
        return self.state.token if self.state.kind == PROBING else None

    @property
    def theme(self) -> str | None:
        return self.decl.theme if self.decl else None


class Sources:
    def __init__(self, declared=(), problems=None, *, serves=lambda: True, clock=time.monotonic, make=RemoteSource):
        self._lock = threading.Lock()
        self._clock, self._make = clock, make
        self._by: dict[str, Source] = {}
        self.serves = serves          # a callable: the hub learns whether it is a tiroir's after it is built
        for decl in declared:
            self._by[decl.name] = Source(decl.name, decl)
        for name, why in (problems or {}).items():
            s = self._by.setdefault(name, Source(name, None))
            s.state = State(REFUSED, error=why, shown=f"source {name!r} is not set up correctly: ask the owner of this hub")

    @classmethod
    def load(cls, *, serves, warn=None) -> "Sources":
        try:
            declared, problems = config.load_sources(warn or (lambda _line: None))    # the user config warns of its own unknown keys once
        except config.ConfigError:
            declared, problems = [], {}       # the config file as a whole is the user config's to report
        return cls(declared, problems, serves=serves)

    def names(self) -> list[str]:
        return sorted(self._by)

    def get(self, name: str) -> Source | None:
        return self._by.get(name)

    def refuse(self, name: str, why: str) -> None:
        """Leave the source `name` unserved until the hub restarts (its name is held by a folder root)."""
        s = self._by.get(name)
        if s is not None:
            self._move(s, REFUSED, error=why, shown=why)

    def ensure(self, name: str) -> Source | None:
        """The source `name`, its service asked its `info` first when it never was, or could not be reached the last time and a
        little while has passed. A hub that is not a tiroir's serves no source."""
        s = self._by.get(name)
        if s is None or s.served:
            return s
        if not self.serves():
            why = (f"source {name!r} is declared here, but a source is served by the hub of the tiroir that owns it, "
                   "never by a laptop's hub")
            self._move(s, FAILED, error=why, shown=why)
            return s
        self._check(s)
        return s

    def _move(self, s: Source, to: str, *, token=None, **fields) -> State | None:
        """The one place a source changes state, decided on the state it has at that moment, under the lock; None when the move
        is not allowed. A probe starts only from idle, or from failed once RETRY_AFTER has passed. A probe's result (it holds
        the token) is written only while that probe is the one the state names: a refusal, or a later probe, outlives it, and a
        served source is never touched by a result. A refusal by the hub is allowed at any time; a source this hub may not serve
        is failed only while it is not served."""
        with self._lock:
            cur, now = s.state, self._clock()
            if to == PROBING:
                if s.decl is None or not (cur.kind == IDLE or (cur.kind == FAILED and now - cur.at >= RETRY_AFTER)):
                    return None
                token, fields = object(), {"error": cur.error, "shown": cur.shown}
                at = cur.at
            else:
                if token is not None:
                    allowed = cur.kind == PROBING and cur.token is token
                elif to == REFUSED:
                    allowed = True
                else:
                    allowed = cur.kind in (IDLE, FAILED)
                if not allowed:
                    return None
                at = now
            s.state = State(to, token if to == PROBING else None, at=at, **fields)
            return s.state

    def _check(self, s: Source) -> None:
        began = self._move(s, PROBING)
        if began is None:
            return
        try:
            self._probe(s, s.decl, began.token)
        finally:                          # whatever was raised: a probe that has not settled the source leaves it asked again later
            self._move(s, FAILED, token=began.token, error="the check did not finish", shown=f"source {s.name!r} cannot be reached just now")

    def _probe(self, s: Source, decl, token) -> None:
        try:
            client = self._make(s.name, decl.url, config.read_bearer(decl))
        except (config.ConfigError, ValueError) as e:
            self._move(s, REFUSED, token=token, error=str(e), shown=f"source {s.name!r} is not set up correctly: ask the owner of this hub")
            return
        try:
            client.info()                 # the network call is made without the lock: one slow service holds up no other
        except VersionMismatch as e:
            self._move(s, REFUSED, token=token, error=e.message, shown=e.message)
        except SourceError as e:          # Unreachable too: asked again later; the service's `version` code is a mismatch
            if getattr(e, "code", "") == "version":
                self._move(s, REFUSED, token=token, error=e.message,
                           shown=f"source {s.name!r} speaks another interface version, this hub speaks {rda.INTERFACE_VERSION}")
            else:
                self._move(s, FAILED, token=token, error=e.message, shown=f"source {s.name!r} cannot be reached just now")
        else:
            self._move(s, SERVED, token=token, client=client)
