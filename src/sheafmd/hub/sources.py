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

from .. import config
from ..remote import RemoteSource, SourceError, VersionMismatch

RETRY_AFTER = 5.0       # seconds before an unreachable service is asked again


class Source:
    def __init__(self, name: str, decl: config.SourceDecl | None):
        self.name = name
        self.decl = decl
        self.client: RemoteSource | None = None
        self.error = ""                 # why it is unserved; "" when it is served
        self.sticky = False             # unserved until the hub restarts (a version mismatch, a declaration that is wrong)
        self.checked = 0.0

    @property
    def served(self) -> bool:
        return not self.error and self.client is not None

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
            s.error, s.sticky = why, True

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
            with self._lock:
                s.error, s.sticky, s.client = why, True, None

    def ensure(self, name: str) -> Source | None:
        """The source `name`, its service asked its `info` first when it never was, or could not be reached the last time and a
        little while has passed. A hub that is not a tiroir's serves no source."""
        s = self._by.get(name)
        if s is None or s.served:
            return s
        if not self.serves():
            with self._lock:
                s.error = (f"source {name!r} is declared here, but a source is served by the hub of the tiroir that owns it, "
                           "never by a laptop's hub")
            return s
        if not s.sticky and (s.checked == 0.0 or self._clock() - s.checked >= RETRY_AFTER):
            self._check(s)
        return s

    def _check(self, s: Source) -> None:
        with self._lock:
            if s.sticky or s.decl is None:
                return
            s.checked = self._clock()
            try:
                bearer = config.read_bearer(s.decl)
                client = self._make(s.name, s.decl.url, bearer)
            except (config.ConfigError, ValueError) as e:
                s.error, s.sticky, s.client = str(e), True, None
                return
            try:
                client.info()
            except VersionMismatch as e:
                s.error, s.sticky, s.client = e.message, True, None
            except SourceError as e:          # Unreachable too: asked again later
                s.error, s.client = e.message, None
            else:
                s.error, s.client = "", client
