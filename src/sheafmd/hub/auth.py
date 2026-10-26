"""
sheafmd.hub.auth — who may talk to the hub (SPEC 9.2 to 9.5, 21).

Everything the hub decides about a caller lives here, so a sign-in can replace the cookie
swap without touching the handler: the Host and Origin checks, the hub key, the browser
cookie derived from it, the proof a health answer carries, where sign-in may send the
browser, and the Content-Security-Policy of every HTML response.

Pure functions and one small class over the key; no I/O, no HTTP.
"""
import base64
import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from urllib.parse import quote

from ..paths import key_bytes   # noqa: F401  (the key's 32 bytes; every HMAC uses these)

COOKIE_MAX_AGE = 34560000       # 400 days, the longest a browser keeps a cookie
SIGNIN_TTL = 30                 # seconds a sign-in nonce can be redeemed (9.3)

_HOST_RE = re.compile(r"(?:127\.0\.0\.1|localhost):([0-9]{1,5})", re.IGNORECASE)
_NONCE_RE = re.compile(r"[0-9a-f]{16,128}")


def host_ok(host) -> bool:
    """`127.0.0.1:<port>` or `localhost:<port>`, any port (a forwarded hub may be reached on
    another local port). Anything else is a DNS-rebinding attempt or a stranger."""
    m = _HOST_RE.fullmatch(host) if isinstance(host, str) else None
    return bool(m) and 0 < int(m.group(1)) < 65536


def origin_ok(origin, host) -> bool:
    """A POST that the cookie authenticates must come from the hub's own page: its Origin is
    `http://` + the Host it was sent to. Another local program on another port holds the
    cookie too (SameSite sees every port of a host as one site) and fails here."""
    if not isinstance(origin, str) or not isinstance(host, str) or not origin or not host:
        return False
    return origin.lower() == ("http://" + host).lower()


def nonce_ok(nonce) -> bool:
    return isinstance(nonce, str) and bool(_NONCE_RE.fullmatch(nonce))


def safe_next(nxt) -> bool:
    """Where sign-in may send the browser: a path on the hub. Not `//host`, not `/\\host`
    (browsers read both as another site), no backslash anywhere, no control character
    (a line break would split the Location header)."""
    if not isinstance(nxt, str) or not nxt.startswith("/"):
        return False
    if nxt.startswith("//") or nxt.startswith("/\\") or "\\" in nxt:
        return False
    return not any(ord(c) < 32 or ord(c) == 127 for c in nxt)


def location(nxt: str) -> str:
    """`nxt` as a Location header value: ASCII, escapes already in it left as they are."""
    return quote(nxt, safe="/%?=&#:@!$'()*+,;~-._")


def new_nonce() -> str:
    """A fresh script nonce for one HTML response."""
    return base64.b64encode(os.urandom(18)).decode("ascii")


def csp(nonce: str, frame: str = "'none'") -> str:
    """The policy of every HTML answer. `frame` is who may frame it: no one on the loopback port,
    the front's own pages (`'self'`) on the proxy socket (9.5, 9.9)."""
    return (f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'unsafe-inline'; "
            "img-src data:; font-src data:; connect-src 'self'; base-uri 'none'; "
            f"form-action 'none'; frame-ancestors {frame}")


# ── MCP tokens (SPEC 9.7) ────────────────────────────────────────────────────

TOKEN_PREFIX = "sheaf_mcp_"
MAX_TOKEN = 200                  # longer than any token: a header that long is not one
DISPLAY_MAX = 60
_BEARER_RE = re.compile(r"bearer[ \t]+(\S+)", re.IGNORECASE)


def new_token() -> str:
    return TOKEN_PREFIX + base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode("ascii")


def token_hash(token: str) -> str:
    """What tokens.json keeps instead of the token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def bearer(header) -> str | None:
    """The token of an `Authorization: Bearer <token>` header, or None."""
    m = _BEARER_RE.fullmatch(header.strip()) if isinstance(header, str) else None
    return m.group(1) if m else None


def clean_display(name) -> str:
    """The one rule for a display name, whoever gives it: an agent's `X-Sheaf-As` header or
    `--agent`, a person's `sheaf token add --as` (SPEC 12). One line (a run of whitespace is one
    space), printable characters only, at most DISPLAY_MAX; empty when nothing is left, which is
    for the caller to answer: a name is never made up here. What is not printable goes first, so
    that cleaning a name that was cleaned changes nothing."""
    text = name if isinstance(name, str) else ""
    text = "".join(c for c in text if c.isspace() or c.isprintable())
    return " ".join(text.split())[:DISPLAY_MAX].strip()


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _same(a, b) -> bool:
    if not isinstance(a, str) or not isinstance(b, str):
        return False
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


class Auth:
    """The hub's key and what is derived from it. `port` is the hub's own configured
    port, not the one a request came in on: it names the cookie, so a local hub and a
    forwarded one (configured with different ports) do not overwrite each other's."""

    def __init__(self, key: str, port: int):
        self.key, self.port = key, port
        self._bytes = key_bytes(key)
        self.clock = time.monotonic
        self._signins: dict[str, float] = {}      # sha256 of a sign-in nonce -> when it stops working
        self._signins_lock = threading.Lock()

    @property
    def cookie_name(self) -> str:
        return f"sheaf_{self.port}"

    def _hmac(self, message: bytes) -> str:
        return hmac.new(self._bytes, message, hashlib.sha256).hexdigest()

    def cookie_value(self) -> str:
        return self._hmac(b"cookie")

    def proof(self, nonce: str) -> str:
        """What a health answer carries, so a command knows it reached the hub that holds
        this key before it sends the key anywhere (SPEC 9.4)."""
        return self._hmac(b"health:" + nonce.encode("ascii"))

    def key_ok(self, given) -> bool:
        return _same(given, self.key)

    def cookie_ok(self, header) -> bool:
        if not isinstance(header, str):
            return False
        want = self.cookie_value()
        found = False
        for part in header.split(";"):
            name, eq, value = part.strip().partition("=")
            if eq and name == self.cookie_name:
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] == '"':
                    value = value[1:-1]
                found = _same(value, want) or found
        return found

    def mint_signin(self) -> str:
        """A one-time nonce for `/_/open?nonce=`: what `sheaf open` hands the browser instead of the
        key, so the key is never in the launcher's argv (9.3). It lives SIGNIN_TTL seconds and is
        spent by its first use. Only its hash is kept, and a rotation (a new Auth) drops them all."""
        nonce = secrets.token_urlsafe(32)
        now = self.clock()
        with self._signins_lock:
            for d in [d for d, until in self._signins.items() if until <= now]:
                del self._signins[d]
            self._signins[_digest(nonce)] = now + SIGNIN_TTL
        return nonce

    def redeem_signin(self, nonce) -> bool:
        """Whether `nonce` is one this Auth made, not used before and not expired. Asking spends it,
        whatever the answer: the hash of what was sent is looked up, never the nonce compared."""
        if not isinstance(nonce, str):
            return False
        with self._signins_lock:
            until = self._signins.pop(_digest(nonce), None)
        return until is not None and self.clock() < until

    def set_cookie(self) -> str:
        return (f"{self.cookie_name}={self.cookie_value()}; HttpOnly; SameSite=Strict; Path=/; "
                f"Max-Age={COOKIE_MAX_AGE}")
