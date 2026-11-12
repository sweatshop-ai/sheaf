"""
sheafmd.hub.transcribe — the dictation relay (SPEC 8.5, 9.5): the hub asks t-compute whether it can transcribe,
and (a later change) sends it the audio a page recorded, so the key never reaches a page.

    load()                 the `[transcribe]` table of config.toml, checked; None without one
    parse(table, where)    the same for a table already read (the tests build one)
    Relay(cfg)             .available(), kept 30 s

The key is read from `key_file` at each call and goes to the host of `url` only: no redirect is followed and
no proxy of the environment is used. It is never written to a row or an answer.
"""
import json
import os
import re
import stat
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .. import config, paths

KEYS = {"url": str, "key_file": str, "key_name": str}
KEPT = 30            # seconds an availability answer is kept
CHECK_TIMEOUT = 3


class TranscribeError(Exception):
    """A `[transcribe]` table that cannot be used. The message names the file."""


@dataclass(frozen=True)
class Config:
    url: str
    key_file: Path
    key_name: str = "RAG_API_KEY"


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
    return Config(t["url"].rstrip("/"), key_file, name)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def _call(method, url, headers) -> tuple[int, bytes]:
    """(status, body); a connection that fails is a 0. A 3xx is an answer, not a road."""
    req = urllib.request.Request(url, headers=headers, method=method)
    try:
        with _OPENER.open(req, timeout=CHECK_TIMEOUT) as r:
            return r.status, r.read(1 << 20)
    except urllib.error.HTTPError as e:
        return e.code, b""
    except (OSError, ValueError):
        return 0, b""


class Relay:
    def __init__(self, cfg: Config, clock=time.time, record=lambda kind, **detail: None):
        self.cfg, self.clock, self.record = cfg, clock, record
        self._state = threading.Lock()
        self._known: tuple[bool, float] | None = None        # (available, when it was found)
        self._refused = False                                # the open key file has been said once

    def _key(self) -> str | None:
        """The key, or None: a file that is not the owner's alone, or has no such line, is not used."""
        try:
            fd = os.open(self.cfg.key_file, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError:
            return None
        with os.fdopen(fd, "r", encoding="utf-8", errors="replace") as f:
            st = os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
                if not self._refused:
                    self._refused = True
                    self.record("transcribe-key-file", reason="the key file is not the owner's alone (mode 0600)")
                return None
            for line in f.read().splitlines():
                m = re.fullmatch(rf"\s*(?:export\s+)?{re.escape(self.cfg.key_name)}\s*=\s*(.*?)\s*", line)
                if m:
                    return m.group(1).strip("\"'") or None
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
