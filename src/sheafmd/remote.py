"""The remote adapter (ADR 0006): the client of a Source service, and what the hub knows of one.

A Source service is a program the source's owner runs beside the source. The hub speaks to it in JSON over HTTPS or a Unix
socket, every request a `POST` that carries `Authorization: Bearer <the hub's bearer for that service>`. The hub holds that one
bearer and never a key to the site (the service holds those).

    info()                                    -> {"interface": int, "name": text, "publish": bool}
    documents(cursor)                         -> {"documents": [{"name": text}], "next": cursor | None}   at most 500 a page
    read(document)                            -> {"tree": {"text": text}, "base": text}
    write(document, tree, base, author, note) -> one of the three outcomes of `adapter.py`
    publish(document, note)                   only where `info` says `publish`

An error is `{"error": {"code": text, "message": text}}` with one of `CODES`. `unknown_author` is an ordinary answer, not a
transport failure: the write comes back as the outcome `refused`, with the code. Everything else that is an error raises
`SourceError`; a timeout, a refused connection, `unavailable` and HTTP 5xx raise `Unreachable`.

The URL of a source is `https://host/...` or `unix:///absolute/path.sock`; plain `http://` is accepted for a loopback address only,
so that a bearer never crosses a network in the clear. Timeouts: 5 s to connect, 30 s for a request.
"""
import http.client
import json
import re
import socket
import threading
import ssl
import time
from collections.abc import Iterator
from urllib.parse import urlsplit

from . import adapter as rda

CONNECT_TIMEOUT = 5.0
REQUEST_TIMEOUT = 30.0
PAGE_MAX = 500                 # documents in one page of `documents`
BODY_MAX = 32 * 1024 * 1024    # the largest answer the hub reads
CODES = ("unauthorized", "not_found", "bad_request", "unknown_author", "version", "unavailable")
_LOOPBACK = ("127.0.0.1", "::1", "localhost")
_STATUS = {"unauthorized": 401, "not_found": 404, "bad_request": 400, "unknown_author": 403, "version": 409,
           "unavailable": 503}


class SourceError(Exception):
    """An answer of the service that is an error, or a service the hub cannot use. `code` is one of `CODES`, or
    `unreachable` for a service that did not answer and `protocol` for one that answered what is not the protocol."""

    def __init__(self, code: str, message: str, status: int | None = None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status      # `status`: the HTTP status of the answer, when there was one


class Unreachable(SourceError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__("unreachable", message, status)


class VersionMismatch(SourceError):
    def __init__(self, name: str, theirs, ours: int):
        super().__init__("version", f"source {name!r} speaks interface version {theirs}, this hub speaks {ours}")
        self.theirs, self.ours = theirs, ours


class BadUrl(ValueError):
    """A source URL the hub will not use."""


def check_url(url: str) -> str:
    """`url` if it is one a bearer may be sent to: `https://`, `unix:///path`, or `http://` to a loopback address. A URL
    that carries a user name or password is refused: a credential never sits in the config."""
    try:
        parts = urlsplit(url)
        host, port = parts.hostname, parts.port
    except ValueError:
        raise BadUrl("is not a URL") from None
    if parts.username is not None or parts.password is not None:
        raise BadUrl("must not carry a user name or a password: the hub's bearer goes in the secrets file")
    if parts.query or parts.fragment:
        raise BadUrl("must not have a query or a fragment")
    if parts.scheme == "unix":
        if parts.netloc or not parts.path.startswith("/") or "\0" in parts.path:
            raise BadUrl("a unix URL is written unix:///absolute/path.sock")
        return url
    if parts.scheme == "https" and host:
        return url
    if parts.scheme == "http" and host in _LOOPBACK:
        return url
    if parts.scheme == "http":
        raise BadUrl("is plain http to a host that is not this machine: use https, or a unix socket")
    raise BadUrl("must be https://host, or unix:///path/to.sock")


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        try:
            s.connect(self._path)
        except BaseException:
            s.close()
            raise
        self.sock = s


def _bounded_connect(address, end: float, total_end: float):
    """A socket connected to `address` (host, port), or `TimeoutError`/`OSError`: the name lookup and every address tried
    are inside one budget that ends at `end` (the connect limit), never past `total_end` (the request's deadline). A name that
    does not resolve cannot be interrupted, so the lookup runs in a thread of its own that the caller stops waiting for."""
    host, port = address
    end = min(end, total_end)
    outcome, done, cancelled = {}, threading.Event(), threading.Event()

    def work():
        try:
            last = None
            for family, kind, proto, _name, where in socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM):
                left = end - time.monotonic()
                if left <= 0 or cancelled.is_set():
                    break
                s = socket.socket(family, kind, proto)
                s.settimeout(left)
                try:
                    s.connect(where)
                except OSError as e:
                    s.close()
                    last = e
                    continue
                if cancelled.is_set():
                    s.close()
                    return
                outcome["sock"] = s
                return
            outcome["error"] = last or TimeoutError("timed out")
        except BaseException as e:          # the thread has no one to raise to
            outcome["error"] = e
        finally:
            done.set()

    threading.Thread(target=work, daemon=True).start()
    if not done.wait(max(0.0, end - time.monotonic())):
        cancelled.set()
        if "sock" in outcome:               # connected in the instant the wait ran out
            outcome["sock"].close()
        raise TimeoutError("timed out")
    if "sock" not in outcome:
        raise outcome["error"]
    s = outcome["sock"]
    s.settimeout(max(0.05, total_end - time.monotonic()))
    return s


class RemoteSource:
    """One Source service, as the hub sees it. `bearer` is the hub's bearer for it: held here, sent in a header, and never in a
    message, a log or a repr."""

    def __init__(self, name: str, url: str, bearer: str, *, connect_timeout: float = CONNECT_TIMEOUT,
                 timeout: float = REQUEST_TIMEOUT, tls: ssl.SSLContext | None = None):
        self.name, self.url = name, check_url(url)
        if not isinstance(bearer, str) or not bearer.isascii() or not bearer.isprintable() or "\n" in bearer:
            raise ValueError(f"the bearer for source {name!r} must be printable ASCII on one line")
        self._bearer = bearer
        self._connect, self._timeout, self._tls = connect_timeout, timeout, tls
        self._parts = urlsplit(self.url)
        self.display = ""
        self.publishes = False

    def __repr__(self):
        return f"RemoteSource({self.name!r}, {self.url!r})"

    # ── transport ───────────────────────────────────────────────────────────
    def _connection(self, deadline: float | None = None):
        p = self._parts
        if p.scheme == "unix":
            return _UnixConnection(p.path, min(self._connect, self._timeout))
        if p.scheme == "https":
            conn = http.client.HTTPSConnection(p.hostname, p.port, timeout=self._connect, context=self._tls)
        else:
            conn = http.client.HTTPConnection(p.hostname, p.port, timeout=self._connect)
        started = time.monotonic()
        deadline = started + self._timeout if deadline is None else deadline
        conn._create_connection = lambda address, timeout=None, source_address=None: _bounded_connect(
            address, started + self._connect, deadline)       # the lookup and each attempt share the connect limit, all of it the request's
        return conn

    def call(self, verb: str, body: dict | None = None) -> tuple[int, dict]:
        """`(status, answer)` of one request. Raises `Unreachable` for a service that does not answer in time or at all,
        `SourceError("protocol", ...)` for an answer that is no JSON object. The request has a deadline of `timeout` seconds in all."""
        deadline = time.monotonic() + self._timeout
        raw = json.dumps(body or {}).encode("utf-8")
        base = self._parts.path.rstrip("/") if self._parts.scheme != "unix" else ""
        conn = self._connection(deadline)
        expired, late = threading.Event(), None
        try:
            try:
                conn.connect()
                sock = conn.sock                  # `getresponse` lets go of `conn.sock` on a `Connection: close` answer
                late = threading.Timer(max(0.05, deadline - time.monotonic()), _cut, (sock, expired))   # the one deadline of the whole call
                late.daemon = True
                late.start()
                sock.settimeout(max(0.05, deadline - time.monotonic()))
                conn.request("POST", f"{base}/{verb}", raw, {"Authorization": f"Bearer {self._bearer}",
                                                              "Content-Type": "application/json",
                                                              "Content-Length": str(len(raw)),
                                                              "Accept": "application/json"})
                sock.settimeout(max(0.05, deadline - time.monotonic()))
                res = conn.getresponse()
                chunks, size = [], 0
                while not res.isclosed():          # a `Connection: close` answer closes its socket with its last byte
                    sock.settimeout(max(0.05, deadline - time.monotonic()))
                    piece = res.read1(65536)
                    if not piece:
                        break
                    chunks.append(piece)
                    size += len(piece)
                    if size > BODY_MAX or time.monotonic() > deadline:
                        raise Unreachable(f"source {self.name!r} answered too much or too slowly")
                if expired.is_set():              # the deadline shut the socket: what was read is not the whole answer
                    raise Unreachable(f"source {self.name!r} answered too much or too slowly")
            except Unreachable:
                raise
            except (OSError, http.client.HTTPException) as e:
                if expired.is_set():
                    raise Unreachable(f"source {self.name!r} answered too much or too slowly") from None        # TimeoutError, ConnectionError, ssl.SSLError, a torn answer
                raise Unreachable(f"source {self.name!r} cannot be reached ({type(e).__name__})") from None
        finally:
            if late is not None:
                late.cancel()
            conn.close()
        try:
            data = json.loads(b"".join(chunks).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            data = None
        if res.status >= 500 and not (isinstance(data, dict) and "error" in data):
            raise Unreachable(f"source {self.name!r} answered HTTP {res.status}")
        if not isinstance(data, dict):
            raise SourceError("protocol", f"source {self.name!r} answered what is not a JSON object (HTTP {res.status})")
        return res.status, data

    def ask(self, verb: str, body: dict | None = None) -> dict:
        """The answer of `verb`, or an error raised: `Unreachable` for `unavailable` and a 5xx, `SourceError` with the
        service's code for any other error body. `unknown_author` is raised too: `write` turns it into an outcome."""
        status, data = self.call(verb, body)
        err = data.get("error")
        if err is None:
            if status >= 500:
                raise Unreachable(f"source {self.name!r} answered HTTP {status}", status)
            if status >= 400:
                raise SourceError("protocol", f"source {self.name!r} answered HTTP {status} with no error", status)
            return data
        code = err.get("code") if isinstance(err, dict) else None
        message = err.get("message") if isinstance(err, dict) else None
        code = code if code in CODES else "protocol"
        message = redact(message, self._bearer) if isinstance(message, str) and message else code      # the service's words are never trusted not to echo
        if code == "unavailable" or status >= 500:
            raise Unreachable(f"source {self.name!r} is unavailable: {message}", status)
        raise SourceError(code, f"source {self.name!r}: {message}", status)

    # ── the protocol ────────────────────────────────────────────────────────
    def info(self) -> dict:
        """The service's `info`, with its interface version checked: `VersionMismatch` names both versions."""
        got = self.ask("info", {"interface": rda.INTERFACE_VERSION})
        theirs = got.get("interface")
        if type(theirs) is not int or theirs != rda.INTERFACE_VERSION:       # JSON 1.0 and true equal 1: the type is the rule
            raise VersionMismatch(self.name, theirs if type(theirs) is int else "unknown",
                                  rda.INTERFACE_VERSION)
        name = got.get("name")
        self.display = name if isinstance(name, str) else ""
        self.publishes = got.get("publish") is True
        return got

    def documents(self) -> Iterator[str]:
        """The names of every document the service lists, page after page."""
        cursor, seen = None, set()
        while True:
            got = self.ask("documents", {} if cursor is None else {"cursor": cursor})
            rows = got.get("documents")
            if not isinstance(rows, list) or len(rows) > PAGE_MAX:
                raise SourceError("protocol", f"source {self.name!r} listed documents in a shape or a page size it must not")
            for row in rows:
                name = row.get("name") if isinstance(row, dict) else None
                if not isinstance(name, str) or not name:
                    raise SourceError("protocol", f"source {self.name!r} listed a document with no name")
                yield name
            cursor = got.get("next")
            if cursor is None:
                return
            if not isinstance(cursor, str) or cursor in seen:
                raise SourceError("protocol", f"source {self.name!r} gave a cursor that does not move")
            seen.add(cursor)

    def adapter(self, document: str) -> "RemoteAdapter":
        return RemoteAdapter(self, document)


def _cut(sock, expired) -> None:
    """The deadline of a call has passed: its socket is shut, so a read that was waiting on a slow service fails at once."""
    expired.set()
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


def redact(text: str, bearer: str = "") -> str:
    """`text` with the bearer, and any `Bearer ...` or `Authorization: ...` it holds, taken out: for the hub's log, never for a member."""
    if bearer:
        text = text.replace(bearer, "[bearer]")
    text = re.sub(r"(?i)bearer\s+\S+", "Bearer [redacted]", text)
    return re.sub(r"(?i)(authorization\s*[:=]\s*)\S+(\s+\S+)?", r"\1[redacted]", text)


class RemoteAdapter:
    """The Source adapter interface of `adapter.py` for one document of a Source service."""
    interface = rda.INTERFACE_VERSION

    def __init__(self, source: RemoteSource, document: str):
        self.source, self.document = source, document

    @staticmethod
    def accepts(name) -> bool:
        return True        # what the service keeps is the service's to judge

    def read(self):
        got = self.source.ask("read", {"document": self.document})
        tree, base = got.get("tree"), got.get("base")
        text = tree.get("text") if isinstance(tree, dict) else None
        if not isinstance(text, str) or not isinstance(base, str) or not base:
            raise SourceError("protocol", f"source {self.source.name!r} read {self.document!r} in a shape it must not")
        return rda.Tree(text), base

    def write(self, tree, base: str, author: str = "", note: str = "", move=None, via: str = "") -> dict:
        """`via` is the name of the agent token the write came through: the note then ends `via <token name>`, so the commit says
        which agent wrote it for the member."""
        note = with_via(note, via)
        try:
            got = self.source.ask("write", {"document": self.document, "tree": {"text": tree.text}, "base": base,
                                            "author": author, "note": note})
        except SourceError as e:
            if e.code == "unknown_author":
                out = rda.refused(e.message)
                out["code"] = "unknown_author"
                return out
            raise
        kind = got.get("outcome")
        if kind == "written" and isinstance(got.get("base"), str):
            return rda.written(got["base"])
        if kind == "conflict" and isinstance(got.get("base"), str):
            return rda.conflict(got["base"], got.get("blocks") or [])
        if kind == "refused" and isinstance(got.get("reason"), str):
            return rda.refused(got["reason"], got.get("block") or "")
        raise SourceError("protocol", f"source {self.source.name!r} answered a write with no outcome")

    def publish(self, note: str = "") -> dict:
        if not self.source.publishes:
            raise SourceError("bad_request", f"source {self.source.name!r} does not publish")
        return self.source.ask("publish", {"document": self.document, "note": note})


def with_via(note: str, via: str = "") -> str:
    """`note`, ending `via <token name>` for a write made through an agent token. The name is one line of text."""
    via = " ".join(str(via or "").split())
    if not via:
        return note
    return f"{note.strip()} via {via}".strip()


_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def valid_name(name: str) -> bool:
    return bool(_NAME.fullmatch(name))


def status_of(code: str) -> int:
    return _STATUS.get(code, 400)
