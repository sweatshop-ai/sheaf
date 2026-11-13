"""
sheafmd.hub.transcribe — the dictation relay (SPEC 8.5, 9.5): the hub asks t-compute whether it can transcribe,
and sends it the audio a page recorded, so the key never reaches a page.

    load()                 the `[transcribe]` table of config.toml, checked; None without one
    parse(table, where)    the same for a table already read (the tests build one)
    Relay(cfg)             .available() (kept 30 s) and .transcribe(audio, ext)

The key is read from `key_file` at each call and goes to the host of `url` only: no redirect is followed and
no proxy of the environment is used. It is never written to a row or an answer.
"""
import http.client
import json
import os
import re
import secrets
import socket
import stat
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .. import config, paths

KEYS = {"url": str, "key_file": str, "key_name": str, "per_minute": int, "per_hour": int}
KEPT = 30            # seconds an availability answer is kept
TIMEOUT = 30         # seconds t-compute has to transcribe
CHECK_TIMEOUT = 3
MIME = {"webm": "audio/webm", "mp4": "audio/mp4", "ogg": "audio/ogg"}


class TranscribeError(Exception):
    """A `[transcribe]` table that cannot be used. The message names the file."""


class Busy(Exception):
    """Another relay is running, or the budget is spent: a 429."""


class Unavailable(Exception):
    """Dictation is off or t-compute failed to answer: a 503."""


class Failed(Exception):
    """t-compute answered and the answer is no text: a 502."""


@dataclass(frozen=True)
class Config:
    url: str
    key_file: Path
    key_name: str = "RAG_API_KEY"
    per_minute: int = 12
    per_hour: int = 120


def load() -> Config | None:
    try:
        data = config.read_toml(paths.config_file(), config.USER_KEYS, warn=lambda line: None)
    except config.ConfigError as e:
        raise TranscribeError(str(e)) from None
    return parse(data["transcribe"], paths.config_file()) if "transcribe" in data else None


def parse(t: dict, where) -> Config:
    here = f"[transcribe] of {where}"
    for key, value in t.items():
        if key not in KEYS:
            raise TranscribeError(f"unknown key '{key}' in {here}")
        if not isinstance(value, KEYS[key]) or isinstance(value, bool):
            raise TranscribeError(f"'{key}' must be {'a number' if KEYS[key] is int else 'text'}, not {value!r}, in {here}")
    for key in ("url", "key_file"):
        if key not in t:
            raise TranscribeError(f"'{key}' is missing from {here}")
    u = urlparse(t["url"])
    try:
        explicit = u.scheme in ("http", "https") and bool(u.hostname) and u.username is None and u.port != 0
    except ValueError:
        explicit = False
    if not explicit:
        raise TranscribeError(f"'url' must be http:// or https:// with a host and no login, in {here}: {t['url']!r}")
    key_file = Path(t["key_file"]).expanduser()
    if not key_file.is_absolute():
        raise TranscribeError(f"'key_file' must be an absolute path, in {here}: {t['key_file']!r}")
    name = t.get("key_name", "RAG_API_KEY")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise TranscribeError(f"'key_name' must be the name of a variable, in {here}: {name!r}")
    cfg = Config(t["url"].rstrip("/"), key_file, name, t.get("per_minute", 12), t.get("per_hour", 120))
    if cfg.per_minute < 1 or cfg.per_hour < 1:
        raise TranscribeError(f"'per_minute' and 'per_hour' must be at least 1, in {here}")
    return cfg


def _resolve(host, port):
    """The addresses of `host`, or [] when the name does not resolve (the caller then has none to try)."""
    try:
        return socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return []


def _call(method, url, headers, body=None, timeout=CHECK_TIMEOUT) -> tuple[int, bytes]:
    """(status, body); a connection that fails is a 0. A 3xx is an answer, not a road: http.client follows no
    redirect and reads no proxy variable. `timeout` bounds the whole call, name lookup and connection included, not
    each step: at that moment a timer shuts the socket down, so a service that answers a byte at a time ends there.
    The lookup runs on a thread of its own that holds the host name only; if the resolver never answers, that
    thread outlives the call (nothing else can stop `getaddrinfo`), but it holds neither key nor body. When the
    call returns, the timer is done: `_call` waits for a cut already begun."""
    u = urlparse(url)
    make = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
    conn = make(u.hostname, u.port, timeout=timeout)
    expired, held = threading.Event(), []                     # `held`: a handle on the socket, taken before it connects
    deadline = time.monotonic() + timeout

    def cut():
        expired.set()
        for sock in list(held):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def connect(address, _timeout, source_address=None):
        """`socket.create_connection` with one deadline for the lookup and every address, and a handle in `held`
        from the first moment, so that the timer can cut a connection or a TLS handshake that is still waiting."""
        found = []
        looking = threading.Thread(target=lambda: found.append(_resolve(*address)), daemon=True)
        looking.start()
        looking.join(max(0.0, deadline - time.monotonic()))
        if not found:
            raise TimeoutError("the name did not resolve in time")
        error = OSError("the name has no address")
        for family, kind, proto, _, target in found[0]:
            left = deadline - time.monotonic()
            if left <= 0 or expired.is_set():
                break
            sock = socket.socket(family, kind, proto)
            held.append(sock.dup())
            try:
                sock.settimeout(left)
                sock.connect(target)
                return sock
            except OSError as e:
                sock.close()
                error = e
        raise error

    conn._create_connection = connect                         # the hook http.client.connect() dials through (3.11 to 3.14)
    timer = threading.Timer(timeout, cut)
    timer.start()
    try:
        conn.connect()
        if expired.is_set():
            return 0, b""
        conn.request(method, (u.path or "/") + (f"?{u.query}" if u.query else ""), body, headers)
        r = conn.getresponse()
        data = r.read(1 << 20) if r.status < 300 else b""
        return (0, b"") if expired.is_set() else (r.status, data)
    except (OSError, ValueError, http.client.HTTPException):     # IncompleteRead and the like are no answer either
        return 0, b""
    finally:
        timer.cancel()
        timer.join()
        conn.close()
        for sock in held:
            sock.close()


class Relay:
    def __init__(self, cfg: Config, clock=time.monotonic, record=lambda kind, **detail: None):
        self.cfg, self.clock, self.record = cfg, clock, record
        self._state = threading.Lock()
        self._busy = threading.Lock()
        self._known: tuple[bool, float] | None = None        # (available, when it was found)
        self._used: deque = deque()                          # when each relay started
        self._refused = False                                # the open key file has been said once

    def _refuse(self, why: str):
        """Said once per hub, in the diagnostics log; dictation stays off."""
        if not self._refused:
            self._refused = True
            self.record("transcribe-key-file", reason=why)

    def _key(self) -> str | None:
        """The key, or None: a file that is not a regular file of the hub's account with mode 0600, or that has no
        such line, is not used. Opened without blocking (a FIFO would hang the open) and never through a symlink."""
        try:
            fd = os.open(self.cfg.key_file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError as e:
            self._refuse(f"the key file cannot be opened ({e.strerror})")
            return None
        wrapped = False                                      # once fdopen has the descriptor, or the refusal below has closed it, closing it again is not our job
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
                wrapped = True                               # before the close: it may raise, and the descriptor is gone either way
                os.close(fd)
                self._refuse("the key file is not a regular file of the hub's account with mode 0600")
                return None
            f = os.fdopen(fd, "r", encoding="utf-8", errors="replace")
            wrapped = True
            with f:
                for line in f.read().splitlines():
                    m = re.fullmatch(rf"\s*(?:export\s+)?{re.escape(self.cfg.key_name)}\s*=\s*(.*?)\s*", line)
                    if m:
                        return m.group(1).strip("\"'") or None
        except OSError as e:
            if not wrapped:
                os.close(fd)
            self._refuse(f"the key file cannot be read ({e.strerror})")
        return None

    def _check(self) -> bool:
        key = self._key()
        if key is None:
            return False
        status, body = _call("GET", f"{self.cfg.url}/status", {})
        try:
            ready = status == 200 and json.loads(body)["whisper"]["ready"] is True
        except (ValueError, KeyError, TypeError):
            return False
        return ready and _call("GET", f"{self.cfg.url}/audio/gpu-status", {"X-API-Key": key})[0] == 200

    def available(self) -> bool:
        """Whether dictation can be offered now; asked of t-compute at most once in 30 seconds."""
        with self._state:
            now = self.clock()
            if self._known is None or now - self._known[1] >= KEPT:
                self._known = (self._check(), now)
            return self._known[0]

    def _unavailable(self):
        with self._state:
            self._known = (False, self.clock())

    def _spend(self):
        """One relay of the budget, or Busy."""
        with self._state:
            now = self.clock()
            while self._used and now - self._used[0] >= 3600:
                self._used.popleft()
            if len(self._used) >= self.cfg.per_hour or sum(1 for t in self._used if now - t < 60) >= self.cfg.per_minute:
                raise Busy("too many dictations; try again in a minute")
            self._used.append(now)

    def transcribe(self, audio: bytes, ext: str) -> str:
        """The text of `audio`, a recording named `dictee.<ext>`. Busy, Unavailable or Failed, each with a
        sentence that is safe to show."""
        if not self.available():
            raise Unavailable("dictation is not available")
        if not self._busy.acquire(blocking=False):
            raise Busy("a dictation is already being transcribed")
        try:
            self._spend()
            key = self._key()
            if key is None:
                raise Unavailable("dictation is not available")
            edge = secrets.token_hex(16)
            body = (f'--{edge}\r\nContent-Disposition: form-data; name="file"; filename="dictee.{ext}"\r\n'
                    f"Content-Type: {MIME[ext]}\r\n\r\n").encode() + audio + f"\r\n--{edge}--\r\n".encode()
            status, reply = _call("POST", f"{self.cfg.url}/audio/transcribe",
                                  {"X-API-Key": key, "X-Priority": "high",
                                   "Content-Type": f"multipart/form-data; boundary={edge}"}, body, TIMEOUT)
            if status in (0, 401, 403, 503):                  # no answer, a refused key or a model that is down
                self._unavailable()
                raise Unavailable("dictation is not available")
            try:
                got = json.loads(reply)
                text, error = got["text"].strip(), got.get("error")
            except (ValueError, KeyError, TypeError, AttributeError):
                raise Failed("the transcription did not work") from None
            if status != 200 or error or not text:
                raise Failed("the transcription did not work")
            return text
        finally:
            self._busy.release()
