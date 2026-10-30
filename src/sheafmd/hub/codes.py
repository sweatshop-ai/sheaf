"""
sheafmd.hub.codes — the sign-in codes of `tiroir work` (SPEC 9.13): short-lived, used once, good for one member,
one sheaf and its one transcript, kept in the hub's memory only.

    Codes()                         the hub's codes; a restart drops them all
    .issue(member, doc, session)    (the code, its Code), or TooMany past the member's 20 an hour
    .find(sha256)                   (the Code, None) for a live one, else (the Code or None, why it is no good)
    .serve(code)                    whether the code may answer its GET: True once, set before a byte is sent
    .spend(code)                    the code has done its work; it stays known, as spent, until it expires
    .unknown()                      the count of made-up codes to write in a row now, or 0 within the minute

The verifier hands the hub the code's hex sha256 (`X-Sheaf-Code`) and never the code; the hub keys its codes by
that hash, so it never holds a code it was sent. Neither is ever written down: a row carries the code id.
"""
import hashlib
import re
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass

PREFIX = "sheaf_code_"
CODE_RE = re.compile(PREFIX + r"[A-Za-z0-9_-]{43}")
HASH_RE = re.compile(r"[0-9a-f]{64}")
TTL = 600                       # seconds from issue, never extended by use (decision 2)
PER_HOUR = 20                   # codes a member may ask for in a rolling hour: bounds the hub's memory
NO_GOOD = "This sign-in code is no good: get a new one from Work on this."
NOT_OPEN = "This sheaf is not open to you with this code: get a code from this sheaf's Work on this."
TOO_MANY = "Too many sign-in codes: wait a few minutes."
_clock = time.time


class TooMany(Exception):
    pass


@dataclass
class Code:
    id: str                     # 8 hex characters, for the rows
    member: str                 # the front's id of the member who asked
    doc: str                    # the sheaf's address
    session: str                # the session it serves: the sheaf's forkable one when it was made
    expires: float
    served: bool = False        # its GET answered
    spent: bool = False         # its POST answered, or its session moved on

    @property
    def expires_text(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.expires))


def digest(code: str) -> str:
    return hashlib.sha256(code.encode("ascii")).hexdigest()


class Codes:
    def __init__(self):
        self._lock = threading.Lock()
        self._codes: dict = {}              # sha256 -> Code
        self._asked: dict = {}              # member -> deque of the times they were issued one
        self._unknown = [None, 0]           # when the last `unknown` row was written, the count since

    def _purge(self, now: float):
        # A code is kept past its expiry for one more TTL, so a late try is told `expired`, not `unknown`.
        for h in [h for h, c in self._codes.items() if c.expires + TTL <= now]:
            del self._codes[h]

    def issue(self, member: str, doc: str, session: str) -> tuple[str, Code]:
        now = _clock()
        with self._lock:
            self._purge(now)
            asked = self._asked.setdefault(member, deque())
            while asked and asked[0] <= now - 3600:
                asked.popleft()
            if len(asked) >= PER_HOUR:
                raise TooMany(TOO_MANY)
            asked.append(now)
            while True:
                code = PREFIX + secrets.token_urlsafe(32)
                h = digest(code)
                if h not in self._codes:
                    break
            c = Code(secrets.token_hex(4), member, doc, session, now + TTL)
            self._codes[h] = c
            return code, c

    def find(self, sha256: str) -> tuple[Code | None, str | None]:
        if not HASH_RE.fullmatch(sha256 or ""):
            return None, "unknown"
        now = _clock()
        with self._lock:
            self._purge(now)
            c = self._codes.get(sha256)
        if c is None:
            return None, "unknown"
        if c.expires <= now:
            return c, "expired"
        if c.spent:
            return c, "used"
        return c, None

    def serve(self, code: Code) -> bool:
        with self._lock:
            if code.served or code.spent or code.expires <= _clock():
                return False
            code.served = True
            return True

    def spend(self, code: Code):
        with self._lock:
            code.spent = True

    def unknown(self) -> int:
        """One more made-up code: the count to write in a row now (the first of a minute, with those since the
        last row), or 0 while a row was written within the minute."""
        now = _clock()
        with self._lock:
            self._unknown[1] += 1
            if self._unknown[0] is not None and now - self._unknown[0] < 60:
                return 0
            n, self._unknown = self._unknown[1], [now, 0]
            return n
