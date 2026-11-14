"""
sheafmd.hub.transcribe — the dictation relay (SPEC 8.5, 9.16): the hub sends the audio a page recorded to a
provider of the standard speech-to-text API (`POST <url>/audio/transcriptions`), so the key never reaches a page.

    load()                 the `[transcribe]` table of config.toml, checked; None without one
    parse(table, where)    the same for a table already read (the tests build one)
    Relay(cfg)             .available() (no request is made) and .transcribe(audio, ext)

The key is read from `key_file` at each call and goes to the host of `url` only: no redirect is followed and
no proxy of the environment is used. It is never written to a row or an answer.
"""
import http.client
import json
import os
import re
import secrets
import socket
import ssl
import stat
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .. import config, paths

KEYS = {"url": str, "model": str, "key_file": str, "key_name": str, "per_minute": int, "per_hour": int}
KEPT = 30            # seconds dictation stays off after no answer or a 503
TIMEOUT = 30         # seconds the provider has to transcribe
KEY_FILE_MAX = 65536    # characters read from the key file: a key file is a few lines
MODEL = re.compile(r"[A-Za-z0-9._:/-]{1,100}")
MIME = {"webm": "audio/webm", "mp4": "audio/mp4", "ogg": "audio/ogg"}


class Called(Exception):
    """What the relay raises: `status` is the provider's answer (0 for none), absent when no call was made."""
    status: int | None = None


class TranscribeError(Exception):
    """A `[transcribe]` table that cannot be used. The message names the file."""


class Busy(Called):
    """Another relay is running, the budget is spent, or the provider said 429: a 429."""


class Unavailable(Called):
    """Dictation is off or the provider failed to answer: a 503."""


class Failed(Called):
    """The provider answered and the answer is no text: a 502."""


@dataclass(frozen=True)
class Config:
    url: str
    model: str
    key_file: Path
    key_name: str = "TRANSCRIBE_API_KEY"
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
    for key in ("url", "model", "key_file"):
        if key not in t:
            hint = " (since 2026-11 `url` is the base ending in /v1, and `model` is required)" if key == "model" else ""
            raise TranscribeError(f"'{key}' is missing from {here}{hint}")
    u = urlparse(t["url"])
    try:
        explicit = (u.scheme in ("http", "https") and bool(u.hostname) and u.username is None and u.port != 0
                    and not u.query and not u.fragment)
    except ValueError:
        explicit = False
    if not explicit:
        raise TranscribeError(f"'url' must be http:// or https:// with a host, no login, no query and no fragment, in {here}: {t['url']!r}")
    if not MODEL.fullmatch(t["model"]):
        raise TranscribeError(f"'model' must be 1 to 100 letters, digits or . _ : / -, in {here}: {t['model']!r}")
    key_file = Path(t["key_file"]).expanduser()
    if not key_file.is_absolute():
        raise TranscribeError(f"'key_file' must be an absolute path, in {here}: {t['key_file']!r}")
    name = t.get("key_name", "TRANSCRIBE_API_KEY")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise TranscribeError(f"'key_name' must be the name of a variable, in {here}: {name!r}")
    cfg = Config(t["url"].rstrip("/"), t["model"], key_file, name, t.get("per_minute", 12), t.get("per_hour", 120))
    if cfg.per_minute < 1 or cfg.per_hour < 1:
        raise TranscribeError(f"'per_minute' and 'per_hour' must be at least 1, in {here}")
    return cfg


def _resolve(host, port):
    """The addresses of `host`, or [] when the name does not resolve (the caller then has none to try)."""
    try:
        return socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return []


def _call(method, url, headers, body=None, timeout=TIMEOUT) -> tuple[int, bytes]:
    """(status, body); a connection that fails is a 0. A 3xx is an answer, not a road: http.client follows no
    redirect and reads no proxy variable. `timeout` bounds the whole call, name lookup and connection included, not
    each step: at that moment a timer shuts the socket down, so a service that answers a byte at a time ends there.
    The lookup runs on a thread of its own that holds the host name only; if the resolver never answers, that
    thread outlives the call (nothing else can stop `getaddrinfo`), but it holds neither key nor body. When the
    call returns, the timer is done: `_call` waits for a cut already begun."""
    u = urlparse(url)
    if u.scheme == "https":                                   # the context is ours: the default of http.client is a global that any library can loosen
        conn = http.client.HTTPSConnection(u.hostname, u.port, timeout=timeout, context=ssl.create_default_context())
    else:
        conn = http.client.HTTPConnection(u.hostname, u.port, timeout=timeout)
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


def _with(error: Called, status: int) -> Called:
    error.status = status
    return error


class Relay:
    def __init__(self, cfg: Config, clock=time.monotonic, record=lambda kind, **detail: None):
        self.cfg, self.clock, self.record = cfg, clock, record
        self._state = threading.Lock()
        self._busy = threading.Lock()
        self._off_until = 0.0                                # no answer or a 503: off until then
        self._stay_off: tuple | None = None                  # a 401, 403 or 404: off while the key file is this one
        self._said: set[int] = set()                         # the refusals already written down
        self._used: deque = deque()                          # when each relay started
        self._refused = False                                # the open key file has been said once

    def _refuse(self, why: str):
        """Said once per hub, in the diagnostics log; dictation stays off."""
        if not self._refused:
            self._refused = True
            self.record("transcribe-key-file", reason=why)

    @staticmethod
    def _mine(st) -> bool:
        return stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid() and not st.st_mode & 0o077

    def _key(self) -> tuple[str, tuple] | None:
        """The key with the stamp of its file (mtime_ns, ctime_ns, size, inode), or None: a file that is not a regular
        file of the hub's account with mode 0600, that has no such line, or whose key a header cannot carry (not
        latin-1: said in the log without the key), or that is over KEY_FILE_MAX characters, is not used. The mode and
        the owner are checked again after each read. The stamp is the one of the file the key was read
        from: a file that changes during the read is read again, and one that keeps changing is not used this time.
        Opened without blocking (a FIFO would hang the open) and never through a symlink."""
        try:
            fd = os.open(self.cfg.key_file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError as e:
            self._refuse(f"the key file cannot be opened ({e.strerror})")
            return None
        try:                                                 # the descriptor is closed here, once, whatever happens below
            st = os.fstat(fd)
            if not self._mine(st):
                self._refuse("the key file is not a regular file of the hub's account with mode 0600")
                return None
            stamp = (st.st_mtime_ns, st.st_ctime_ns, st.st_size, st.st_ino)
            f = os.fdopen(os.dup(fd), "r", encoding="utf-8", errors="replace")      # fdopen owns the copy, whether it closes it on failure or not
            with f:
                for _ in range(3):
                    text = f.read(KEY_FILE_MAX + 1)
                    if len(text) > KEY_FILE_MAX:
                        self._refuse(f"the key file is too large (over {KEY_FILE_MAX} characters)")
                        return None
                    st = os.fstat(f.fileno())
                    if not self._mine(st):                   # a chmod during the read: the key of this pass is not used
                        self._refuse("the key file is not a regular file of the hub's account with mode 0600")
                        return None
                    after = (st.st_mtime_ns, st.st_ctime_ns, st.st_size, st.st_ino)
                    if after == stamp:
                        break
                    stamp = after                            # a writer finished during the read: the text may be either
                    f.seek(0)
                else:
                    return None                              # still changing; the next call reads it again
                for line in text.splitlines():
                    m = re.fullmatch(rf"\s*(?:export\s+)?{re.escape(self.cfg.key_name)}\s*=\s*(.*?)\s*", line)
                    if m:
                        value = m.group(1).strip("\"'")
                        if not value:
                            return None
                        try:
                            value.encode("latin-1")
                        except UnicodeEncodeError:
                            self._refuse("the key in the key file has a character an HTTP header cannot carry (it must be latin-1)")
                            return None
                        return value, stamp
        except OSError as e:
            self._refuse(f"the key file cannot be read ({e.strerror})")
        finally:
            try:
                os.close(fd)
            except OSError:
                pass                                         # a close that fails (a FUSE flush) has released the descriptor all the same
        return None

    def available(self) -> bool:
        """Whether dictation can be offered now: the table is there and the key file is usable. No request is made.
        Off for 30 seconds after no answer or a 503, and after a 401, 403 or 404 for as long as the key file is the
        one that was refused (a new key at the same path is noticed; a changed table needs the hub's restart). Any
        change of the file's stamp counts, a chmod or a touch with the same key too: that lifts the stop for one
        more request to the host of `url`, spent from the budget like any other."""
        with self._state:
            read = self._key()
            if read is None:
                return False
            if self._stay_off is not None:
                if self._stay_off == read[1]:
                    return False
                self._stay_off = None
            return self.clock() >= self._off_until

    def _failed(self, status: int, stamp: tuple):
        """Write down the status of a call that is a setup error, once per code and hub, and turn dictation off."""
        with self._state:
            if status in (401, 403, 404):
                self._stay_off = stamp
                if status not in self._said:
                    self._said.add(status)
                    self.record("transcribe-refused", status=status)
            else:
                self._off_until = self.clock() + KEPT

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
            if not self.available():                         # again, under the lock: a dictation ahead of this one may have been refused
                raise Unavailable("dictation is not available")
            self._spend()
            read = self._key()
            if read is None:
                raise Unavailable("dictation is not available")
            key, stamp = read
            edge = secrets.token_hex(16)
            body = (f'--{edge}\r\nContent-Disposition: form-data; name="model"\r\n\r\n{self.cfg.model}\r\n'
                    f'--{edge}\r\nContent-Disposition: form-data; name="file"; filename="dictee.{ext}"\r\n'
                    f"Content-Type: {MIME[ext]}\r\n\r\n").encode() + audio + f"\r\n--{edge}--\r\n".encode()
            status, reply = _call("POST", f"{self.cfg.url}/audio/transcriptions",
                                  {"Authorization": f"Bearer {key}",
                                   "Content-Type": f"multipart/form-data; boundary={edge}"}, body, TIMEOUT)
            if status in (0, 401, 403, 404, 503):             # no answer, a refused key, no such route or a service that is down
                self._failed(status, stamp)
                raise _with(Unavailable("dictation is not available"), status)
            if status == 429:
                raise _with(Busy("too many dictations; try again in a minute"), status)
            try:
                got = json.loads(reply)
                text, error = got["text"].strip(), got.get("error")
            except (ValueError, KeyError, TypeError, AttributeError):
                raise _with(Failed("the transcription did not work"), status) from None
            if status != 200 or error or not text:
                raise _with(Failed("the transcription did not work"), status)
            return text
        finally:
            self._busy.release()
