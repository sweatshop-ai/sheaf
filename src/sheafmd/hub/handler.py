"""
sheafmd.hub.handler — request routing, with no socket (SPEC 8.5, 9, 3.1).

`Handler(hub).handle(method, target, headers, body, conn, via)` takes what the server read from the wire
(`conn`: the connection it came in on; `via`: the listener, the loopback port or the proxy socket) and
returns a `Response`; server.py only moves bytes in and out. So every route and every 4xx
runs in a test, in memory, without a subprocess.

The order of every request: the Host check, then who the caller is (the key header, the cookie
or, at the door, an MCP token), then the route, then (for a POST the cookie authenticated) the Origin
check, then the body. A caller that is refused earlier never has its body read at all.

On the proxy socket (9.9) the order is the same with other checks: the uid at the other end of the
connection, the Host of the front, the member header, the route (a member's routes only), the
Origin of every POST, then the body. No cookie and no key is read there.
"""
import contextlib
import json
import os
import re
import stat
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote

from .. import comments as rdc
from .. import beneath, diagnostics, pdf
from ..agents import prompts
from ..agents.base import Target
from ..config import ConfigError
from ..edit import EditError
from ..mcp import Caller, Door
from ..render import RenderError
from ..source import StaleError, md_hash
from . import archive as archive_mod
from . import auth, boxwait, channel, codes, events, incoming, laptops, loose, moves, outgoing, peer, place, proxy, readthrough, sheaf_view, targets, team as team_mod, the_list, transcribe, visibility, work
from . import waiting as waiting_mod
from .core import _META_RE
from .tell import NO_AGENT, JobRefused
from .index import Status
from ..source import STAMP_FORMAT
from .live import UNKNOWN, NotAuthor
from .roots import Address, NotFound, address_of_url, root_of_url, url_path
from .state import TokenRow

MAX_BODY = 8 * 1024 * 1024
MAX_AUDIO = 2 * 1024 * 1024
DICTATION_FILE = re.compile(r"dictee\.(webm|mp4|ogg)")
OPS = ("add", "reply", "status", "edit", "delete")
# A page's save or tick whose root was forgotten, and its name maybe taken, before its file moved (8.2, 8.11).
FOLDER_REPLACED = "This page's folder was forgotten or replaced while it was saved. Nothing was written."
SIGN_IN = ("This browser is not signed in to your sheaf hub. On the machine that runs the hub, "
           "run <code>sheaf open &lt;this url&gt;</code>. If the hub runs on another machine, "
           "run <code>sheaf signin-url</code> there and open what it prints in this browser.")
LINK_USED = (f"A sign-in link from <code>sheaf open</code> works once, for {auth.SIGNIN_TTL} seconds: "
             "this one was used already, has run out or is not from this hub. On the machine that runs the hub, run "
             "<code>sheaf open &lt;the document&gt;</code> again.")
# Only where the hub cannot check who follows a link: where it checks, another user could not have
# used the link, so there is nothing to rotate for (ticket 99).
LINK_ROTATE = ("If you did not use the link twice yourself, someone else on that machine may have used it "
               "first: run <code>sheaf rotate</code> to sign every browser out, then <code>sheaf open</code> again.")
LINK_LIMIT = ("This hub cannot check which user of this machine follows a link (this system gives it no way "
              "to see who owns a connection), so on a machine that other people use, someone who read the "
              "link while it lasted could have used it first.")
LINK_OTHER_USER = ("The hub did not sign this browser in, and the link is spent: the connection comes from "
                   "another user of this machine than the one that runs the hub. A sign-in link works only "
                   "in a browser of the hub's own user. On the machine that runs the hub, run "
                   "<code>sheaf open &lt;the document&gt;</code> again, as that user.")
LINK_UNTESTED = ("When it started, the hub could not test whether it can see which user of this machine is at the "
                 "other end of a connection, and it could not tell who followed this link, so it signed no one in, "
                 "and the link is spent. On the machine that runs the hub, run <code>sheaf signin-url</code> and "
                 "open what it prints in this browser; <code>sheaf diag</code> shows the "
                 "<code>peer-selftest-failed</code> row.")
LINK_UNKNOWN = ("The hub could not tell which user of this machine followed this link, so it signed no one in, "
                "and the link is spent. On the machine that runs the hub, run "
                "<code>sheaf open &lt;the document&gt;</code> again. If it keeps happening, run "
                "<code>sheaf diag</code> and look at the <code>open-401</code> rows, or run "
                "<code>sheaf signin-url</code> and open what it prints in this browser.")
REQUEST_OTHER_USER = ("This hub answers only to the user of this machine that runs it, and this connection comes from "
                      "another user. If you are that user, run <code>sheaf open &lt;the document&gt;</code> in your "
                      "own session.")
REQUEST_UNKNOWN = ("The hub could not tell which user of this machine sent this request, so it did not answer it. "
                   "Try again; if it keeps happening, run <code>sheaf diag</code> and look at the "
                   "<code>peer-refused</code> rows.")
PEER_ROW_SECONDS = 60                # `peer-refused` is written at most this often: the rest are not written
PROXY_SIGN_IN = ("This browser is not signed in to this site, or its sign-in has ended. Sign in to this "
                 "site again, then reload this page.")
WRONG_KEY = ("This link does not hold this hub's key. On the machine that runs the hub, run "
             "<code>sheaf signin-url</code> again and open what it prints in this browser.")
SETTING_TYPES = {"title": str, "toc": str, "max_image_width": int, "by": str, "for": str,
                 "theme": str, "credit": bool}
_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")
_RID_RE = re.compile(r"[A-Za-z0-9_-]{16,64}")     # a page's request id (/_/comment, /_/save)
ASK_RETIRED = f"{prompts.ASK_RETIRED_HEAD}: use Tell, or reply."
_RESERVED = {"kind", "source", "doc", "at", "pid", "session", "member"}


PENDING_S = 300  # how long a session James named waits for the copy before it is said (9.12)
_clock = time.monotonic


def _split_unquoted(value: str, sep: str) -> list:
    """`value` cut at each `sep` that is outside a quoted string, where a backslash escapes the next character."""
    parts, start, quoted, escaped = [], 0, False, False
    for i, ch in enumerate(value):
        if escaped:
            escaped = False
        elif quoted and ch == "\\":
            escaped = True
        elif ch == '"':
            quoted = not quoted
        elif ch == sep and not quoted:
            parts.append(value[start:i])
            start = i + 1
    parts.append(value[start:])
    return parts


def _asks_for_html(accept: str) -> bool:
    """Whether an `Accept` header names `text/html` with a weight above zero (RFC 9110 12.5.1): the
    media types are compared whatever their case, and `text/html;q=0` is a refusal. A wildcard
    does not count: a command that sends `*/*` still reads JSON. A `,` or `;` inside a quoted parameter value
    (RFC 9110 5.6.4) ends neither the item nor the parameter."""
    for item in _split_unquoted(accept, ","):
        media, *params = (part.strip() for part in _split_unquoted(item, ";"))
        if media.lower() != "text/html":
            continue
        weight = 1.0
        for param in params:
            name, _, value = param.partition("=")
            if name.strip().lower() == "q":
                try:
                    weight = float(value.strip())
                except ValueError:
                    weight = 0.0
        if weight > 0:
            return True
    return False


@dataclass
class Response:
    status: int
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    stream: object = None            # an events.Subscription: the server turns it into a stream
    nonce: str | None = None
    error: str | None = None         # why a page refused, for the row: a JSON answer carries its own
    row: str | None = None           # the kind of the row a refusal writes, when not `<route>-<status>`
    fields: dict = field(default_factory=dict)   # more for that row

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.body)


class Refuse(Exception):
    def __init__(self, status: int, message: str, headers: dict | None = None, page: str | None = None,
                 detail: str | None = None, row: str | None = None, fields: dict | None = None,
                 answer: dict | None = None):
        super().__init__(message)
        self.status, self.message, self.headers = status, message, headers or {}
        self.page = page                 # what a browser is told when the refusal is of its sign-in link
        self.detail = detail             # more than any caller is told, for the row of the log
        self.row, self.fields = row, fields or {}
        self.answer = answer or {}       # more fields of the JSON answer, beside `error`


@dataclass
class Req:
    method: str
    path: str
    query: dict
    headers: dict
    host: str
    kind: str | None = None          # "key", "cookie" or "token": how the caller proved itself
    body: dict = field(default_factory=dict)
    raw: bytes = b""                 # the body as it came, for the door (it reads its own JSON-RPC)
    token: TokenRow | None = None    # the MCP token that opened the door
    display: str = ""                # the name a key signs the door's replies with (`X-Sheaf-As`)
    auth: object = None              # the Auth that judged this request: a rotation may swap the hub's own mid-way
    route: str = "unknown"
    conn: object = None              # the peer.Conn (proxy.Peer on the proxy socket) it came in on; None where nothing is behind it (a test)
    via: str = "port"                # "port" or "proxy": the listener it came in on (9.9)
    member: object = None            # the proxy.Member the proxy socket let in
    member_id: str = ""              # the member header, once the connection is the proxy's: every row names it
    code: object = None              # the codes.Code that let the request in, instead of the member header (9.13)
    mount: str = ""                  # read-through: the prefix a page is told under, `Clients/<client>` (9.9); "" on every other request
    gone: object = None              # `gone()`: whether the caller closed the connection (a poll that waits asks it); None in a test
    arrived: float = field(default_factory=time.monotonic)      # when the request came in: a transfer's deadline counts from here


@dataclass(frozen=True)
class Who:
    """Who may call a route (8.5, 9.3, 9.7): the credentials it takes, and what the caller is told
    when it holds none of them. A route that `token`s also takes an MCP token, nowhere else is one
    looked at; one that reads its own `raw_body` is sent the bytes as they came, and its key
    caller must name itself (the door reads its own JSON-RPC and signs its replies)."""
    kinds: frozenset[str]
    refusal: str
    raw_body: bool = False
    proxy: bool = True               # False: never offered on the proxy socket, though it takes the same credentials as a kind that is

    def __contains__(self, kind) -> bool:
        return kind in self.kinds

    @property
    def token(self) -> bool:
        return "token" in self.kinds


_BROWSER = "this needs a browser that is signed in to the hub"
OPEN = None
COOKIE = Who(frozenset({"cookie"}), _BROWSER)
EITHER = Who(frozenset({"cookie", "key"}), _BROWSER)
KEY = Who(frozenset({"key"}), "this needs the hub key")
# The dictation relay (8.5): a browser's own, never a member's, whose page speaks to its host (9.9). `Who` compares by
# value, so `proxy=False` is what keeps `_for_members` from admitting it as it would a plain `COOKIE`.
DICTATION = Who(frozenset({"cookie"}), _BROWSER, proxy=False)
AUDIO = Who(frozenset({"cookie"}), _BROWSER, raw_body=True, proxy=False)     # the same, for the recording itself
TOKEN_ONLY = Who(frozenset({"token"}), "this needs an MCP token")
DOOR = Who(frozenset({"key", "token"}), "this needs the hub key or an MCP token", raw_body=True)
# A member's alone, on the proxy socket (9.12): the loopback port answers 404, as for a route it has not.
MEMBER = Who(frozenset({"member"}), "no such route")
# A sign-in code is asked for by a member on the proxy socket, or with the key on the loopback port (9.13).
MINT = Who(frozenset({"member", "key"}), "this needs the hub key")
# What a sign-in code opens (9.13): the transcript and the fork, nothing else.
CODE_ROUTES = {("GET", "/_/session"): "session", ("POST", "/_/sessions"): "sessions"}
LISTED = "That session is already listed on this rectoverso"


def _json(status: int, obj: dict, headers: dict | None = None) -> Response:
    return Response(status, {"Content-Type": "application/json", **(headers or {})},
                    json.dumps(obj).encode("utf-8"))


def _line(line, told=None) -> dict | None:
    """A Write log line as a dict, its `address` as `told` names it when the caller is told of the page under another name."""
    if line is None:
        return None
    out = asdict(line)
    if told is None:
        return out
    return {**out, "address": told, "session": "", "host": "", "link": "", "chat": ""} if told != line.address else out


def _ok(**fields) -> Response:
    return _json(200, {"ok": True, **fields})


class _SharedStream(events.Shared):
    """A shared stream that leaves the handler's list of them when its connection ends."""
    def __init__(self, handler, sid: str, owner):
        super().__init__(owner)
        self._handler, self._sid = handler, sid
        self.seq = 0                     # set when it is listed: a newer stream has a higher one
        self.had: set = set()            # every key joined here, left or not: an older stream takes none of them

    def close(self):
        super().close()
        self._handler._shared_closed(self._sid, self)


def _stream(sub) -> Response:
    return Response(200, {"Content-Type": "text/event-stream", "Connection": "close"}, stream=sub)


def _html(status: int, html: str, nonce: str | None = None, headers: dict | None = None) -> Response:
    nonce = nonce or auth.new_nonce()
    return Response(status, {"Content-Type": "text/html; charset=utf-8", **(headers or {})},
                    html.encode("utf-8"), nonce=nonce)


def _disposition(name: str) -> str:
    plain = re.sub(r"[^A-Za-z0-9._ -]", "_", name)
    out = f'attachment; filename="{plain}"'
    if plain != name:
        out += f"; filename*=UTF-8''{quote(name, safe='')}"
    return out


def _sign_in_page(title: str, html: str) -> str:
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>"
            f"{title}</title><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<style>body{font:16px/1.5 system-ui,sans-serif;max-width:34rem;margin:4rem auto;"
            "padding:0 1rem;color:#222}code{background:#eee;padding:.1em .3em;border-radius:3px}"
            f"</style></head><body><h1>{title}</h1><p>{html}</p></body></html>")


def _signed_out_page() -> str:
    return _sign_in_page("Not signed in", SIGN_IN)


def _shape(cond, message: str):
    if not cond:
        raise Refuse(400, message)


def _document_events(name: str, data):
    """What a member's document stream is sent (9.9): the events of `proxy.DOCUMENT_EVENTS` only,
    and in them nothing of the hub account's agent session. So no Tell of it, no thread told
    to it, no question it put to its person, and no `signed-out`, since `sheaf rotate` does not
    touch a member."""
    if name not in proxy.DOCUMENT_EVENTS:
        return None
    return proxy.for_member(data) if isinstance(data, dict) else data


class Handler:
    def __init__(self, hub, peer_check=peer.check):
        self.hub = hub
        self.peer_check = peer_check
        self.peer_off: str | None = None    # why the hub does not check who owns a connection (`peer.startup`), once it knows
        self.peer_selftest_raised: str | None = None  # why the start-up self-test raised: the check stays on (ticket 178)
        self._peer_row_times = {}           # when `peer-refused` was last written, for each kind of refusal
        self._peer_row_lock = threading.Lock()
        self.door = Door(hub)
        self._titles = sheaf_view.Titles()
        self.door.called = self._james_called
        self._pending_members: dict = {}    # address -> the member whose James wrote the waiting session: his copy is looked in
        self._pending_sessions: dict = {}   # address -> (James's session it waits for, since, its write's seq) (9.12)
        self._session_seqs: dict = {}       # address -> the seq of James's latest write to it: the newest one wins
        self._pending_lock = threading.Lock()
        self.codes = codes.Codes()          # the sign-in codes, in memory only: a restart drops them (9.13)
        self._shared: dict = {}             # id -> the events.Shared stream a browser opened under it (ticket 160)
        self._shared_lock = threading.Lock()
        self._shared_opened = 0             # how many were opened: a stream's `seq`, so the newer of two is known
        self._join_lock = threading.Lock()  # a key's place is looked up and taken in one step (ticket 181 D)
        # path -> method -> (route name, who may call it, function)
        self.routes: dict = {}
        for method, path, name, who, fn in (
            ("GET", "/_/health", "health", OPEN, self._health),
            ("GET", "/_/open", "open", OPEN, self._open),
            ("GET", "/_/live", "live", COOKIE, self._live),
            ("POST", "/_/live/join", "live-join", COOKIE, self._live_join),
            ("POST", "/_/live/leave", "live-leave", COOKIE, self._live_leave),
            ("GET", "/_/doc", "doc", EITHER, self._doc),
            ("GET", "/_/writes", "writes", EITHER, self._writes),
            ("GET", "/_/mount", "mount", EITHER, self._mount),
            ("GET", "/_/clients/sheaf", "clients-sheaf", MEMBER, self._clients_sheaf),
            ("GET", "/_/mount.js", "mount-js", OPEN, lambda req: self._mount_asset(req, "mount.js", "text/javascript; charset=utf-8")),
            ("GET", "/_/mount.css", "mount-css", OPEN, lambda req: self._mount_asset(req, "mount.css", "text/css; charset=utf-8")),
            ("GET", "/_/index.json", "index", EITHER, self._index_json),
            ("GET", "/_/jobs", "jobs", KEY, self._jobs),
            ("POST", "/_/save", "save", COOKIE, self._save),
            ("POST", "/_/pin", "pin", COOKIE, self._pin),
            ("POST", "/_/tick", "tick", COOKIE, self._tick),
            ("POST", "/_/share", "share", COOKIE, self._share),
            ("POST", "/_/move", "move", COOKIE, self._move),
            ("POST", "/_/move-folder", "move-folder", COOKIE, self._move_folder),
            ("POST", "/_/move-tiroir", "move-tiroir", COOKIE, self._move_tiroir),
            ("POST", "/_/archive", "archive", COOKIE, self._archive),
            ("POST", "/_/restore", "restore", COOKIE, self._restore),
            ("POST", "/_/keep", "keep", COOKIE, self._keep),
            ("POST", "/_/delete", "delete", COOKIE, self._delete),
            ("POST", "/_/restore-trash", "restore-trash", COOKIE, self._restore_trash),
            ("GET", "/_/session", "session", MEMBER, self._session),
            ("POST", "/_/sessions", "sessions", MEMBER, self._sessions),
            ("GET", "/_/laptops", "laptops", MEMBER, self._laptops),
            ("GET", "/_/whoami", "whoami", TOKEN_ONLY, self._whoami),
            ("POST", "/_/laptops", "laptop-make", MEMBER, self._laptop_make),
            ("POST", "/_/laptops/revoke", "laptop-revoke", MEMBER, self._laptop_revoke),
            ("POST", "/_/code", "code", MINT, self._code),
            ("POST", "/_/comment", "comment", COOKIE, self._comment),
            ("GET", "/_/team", "team", COOKIE, self._team),
            ("POST", "/_/team", "team-write", COOKIE, self._team_write),
            ("POST", "/_/tell", "tell", COOKIE, self._tell),
            ("POST", "/_/target", "target", COOKIE, self._target),
            ("POST", "/_/cancel", "cancel", COOKIE, self._cancel),
            ("POST", "/_/retarget", "retarget", COOKIE, self._retarget),
            ("POST", "/_/jump", "jump", COOKIE, self._jump),
            ("POST", "/_/seen", "seen", COOKIE, self._seen),
            ("POST", "/_/export", "export", COOKIE, self._export),
            ("GET", "/_/transcribe", "transcribe-ask", DICTATION, self._transcribe_ask),
            ("POST", "/_/transcribe", "transcribe", AUDIO, self._transcribe),
            ("POST", "/_/diag", "diag", COOKIE, self._diag),
            ("POST", "/_/render", "render", KEY, self._render),
            ("POST", "/_/forget", "forget", KEY, self._forget),
            ("POST", "/_/stop", "stop", KEY, self._stop),
            ("POST", "/_/rotate", "rotate", KEY, self._rotate),
            ("POST", "/_/signin", "signin", KEY, self._signin),
            ("POST", "/_/restarting", "restarting", KEY, self._restarting),
            ("DELETE", "/_/restarting", "restarting", KEY, self._forget_restart),
            ("POST", "/_/mcp", "mcp", DOOR, self._mcp),
        ):
            self.routes.setdefault(path, {})[method] = (name, who, fn)

    # ── the front door ───────────────────────────────────────────────────────
    def handle(self, method: str, target: str, headers: dict, body=b"", conn=None, via="port", gone=None) -> Response:
        """`body` is the bytes, or a function that reads them off the wire: it is called only for
        a POST that has passed the Host, credential and Origin checks. `conn` is the connection
        the request came in on (a `peer.Conn`): the sign-in link looks up who owns it (9.3). `via`
        is the listener: "proxy" for the proxy socket (9.9), where `conn` is a `proxy.Peer`."""
        req = None
        try:
            headers = {str(k).lower(): str(v) for k, v in headers.items()}
            path, _, qs = target.partition("?")
            req = Req(method, path, {k: v[0] for k, v in parse_qs(qs, keep_blank_values=True).items()},
                      headers, headers.get("host", ""), conn=conn, via=via, gone=gone)
            res = self._route_proxy(req, body) if via == "proxy" else self._route(req, body)
        except Refuse as r:
            res = self._refusal(req, r)
        except (FileNotFoundError, NotFound) as e:
            if req is not None and (doc := self._doc_hint(req)) and self._page_gone(doc):
                res = self._refusal(req, Refuse(404, "no such document"))      # a writer that waited for a Delete's lock finds no page
            else:
                res = self._failed(req, e, method)
        except Exception as e:
            res = self._failed(req, e, method)
        return self._finish(req, res)

    def _page_gone(self, doc: str) -> bool:
        """Whether the page `doc` names is not a file any more."""
        try:
            return not self.hub.file(doc).exists()
        except (NotFound, OSError):
            return True
        except Exception:
            return False

    def _failed(self, req, e, method) -> Response:
        if req is not None:
            seen = self._on_clients(req)          # no client page address on this disk (9.9)
            self.hub.record_exception("request-failed", None if seen else self._doc_hint(req),
                                      **({} if seen else {"endpoint": req.path}), method=method, **self._who(req))
        return _json(500, {"ok": False, "error": f"the hub failed on this request "
                           f"({type(e).__name__}); the details are in `sheaf diag`"})

    def _refusal(self, req, r: Refuse) -> Response:
        res = self._refusal_answer(req, r)
        res.row, res.fields = r.row, r.fields
        return res

    def _refusal_answer(self, req, r: Refuse) -> Response:
        if req is not None and req.via == "proxy":
            # A person's browser that asks for a page gets a page: to sign in to the front again,
            # or that this account has nothing here. Everything else gets the JSON.
            if r.page and req.method == "GET" and not req.path.startswith("/_/"):
                title = "Not signed in" if r.status == 401 else "No documents"
                res = _html(r.status, _sign_in_page(title, r.page), headers=r.headers)
                res.error = r.detail or r.message
                return res
        elif req is not None and r.status == 401 and req.method == "GET":
            if not req.path.startswith("/_/"):
                return _html(401, _signed_out_page(), headers=r.headers)
            # The link of `sheaf open` is the one `/_/` route a person's browser follows: it asks
            # for a page, so it gets one, not the JSON that a command reads.
            if req.path == "/_/open" and r.page and _asks_for_html(req.headers.get("accept", "")):
                res = _html(401, _sign_in_page("This sign-in link did not work", r.page), headers=r.headers)
                res.error = r.detail or r.message
                return res
        elif req is not None and r.status == 403 and r.page and req.method == "GET" \
                and _asks_for_html(req.headers.get("accept", "")):
            res = _html(403, _sign_in_page("Not your hub", r.page), headers=r.headers)
            res.error = r.detail or r.message
            return res
        res = _json(r.status, {"ok": False, "error": r.message, **r.answer}, r.headers)
        res.error = r.detail
        return res

    def _finish(self, req, res: Response) -> Response:
        """The headers every answer carries, the CSP on every HTML one, and a row for each
        refusal and failure."""
        h = res.headers
        h.setdefault("Cache-Control", "no-store")
        h.setdefault("Referrer-Policy", "no-referrer")
        h.setdefault("X-Content-Type-Options", "nosniff")
        if h.get("Content-Type", "").startswith("text/html"):
            res.nonce = res.nonce or auth.new_nonce()
            framed = req is not None and req.via == "proxy"     # the front's own pages may frame it (9.5)
            h["Content-Security-Policy"] = auth.csp(res.nonce, "'self'" if framed else "'none'")
            h["Permissions-Policy"] = "microphone=(self), camera=(), geolocation=()"
        if res.status >= 400 and req is not None and res.row is not False:     # False: counted, not written
            error = res.error or ""
            seen = self._on_clients(req)          # what a client page is called is the client's: no address on this disk (9.9)
            if not error and not seen and h.get("Content-Type") == "application/json":
                try:
                    got = json.loads(res.body)
                    error = got.get("error", "") if isinstance(got, dict) else ""
                except ValueError:
                    pass
            self.hub.record(res.row or f"{req.route}-{res.status}", None if seen else self._doc_hint(req),
                            **({} if seen else {"endpoint": req.path}), error=None if seen else (error or None), **self._who(req), **res.fields)
        return res

    @staticmethod
    def _on_clients(req) -> bool:
        """Whether the request names a page under `Clients/` (9.9), by its path or by the `doc` it carries."""
        body = req.body if isinstance(req.body, dict) else {}
        d = req.query.get("doc") or body.get("doc")
        return readthrough.is_clients(d) or readthrough.is_clients(address_of_url(req.path))

    @staticmethod
    def _who(req) -> dict:
        """What every row a request of the proxy socket writes carries: the member (15)."""
        return {"member": req.member_id} if req is not None and req.member_id else {}

    @staticmethod
    def _doc_hint(req) -> str | None:
        d = req.query.get("doc") or req.body.get("doc")
        return d if isinstance(d, str) else None

    def _route(self, req: Req, raw: bytes) -> Response:
        hub = self.hub
        req.auth = hub.auth
        if not auth.host_ok(req.host):
            raise Refuse(403, "this hub answers only to 127.0.0.1 and localhost")
        if not req.path.startswith("/"):
            raise Refuse(400, "bad request target")
        methods = self.routes.get(req.path) if req.path.startswith("/_/") else None
        found = methods.get(req.method) if methods else None
        if found:
            req.route = found[0]
        elif not req.path.startswith("/_/"):
            req.route = "page"
        if found and found[1] is OPEN:
            return found[2](req)
        # Everything else needs the key header or the cookie, whatever the path is; a route that
        # says so also takes an MCP token (9.3, 9.7), whatever the method. Nowhere else is a token
        # looked at.
        takes_token = any(w is not OPEN and w.token for _, w, _ in (methods or {}).values())
        if req.auth.key_ok(req.headers.get("x-sheaf-key")):
            req.kind = "key"
        elif req.auth.cookie_ok(req.headers.get("cookie")):
            req.kind = "cookie"
        elif takes_token and self._token(req):
            req.kind = "token"
        else:
            # Only a route that takes a token has a 401 that names the scheme to try.
            raise Refuse(401, "not signed in", {"WWW-Authenticate": "Bearer"} if takes_token else None)
        if req.kind in ("key", "cookie"):
            self._gate(req)
        if req.path.startswith("/_/"):
            if methods is None:
                raise Refuse(404, "no such route")
            # A member route is no route of this port, for any method: not a 405 that names it (9.12).
            if any(w is MEMBER for _, w, _ in methods.values()):
                raise Refuse(404, "no such route")
            if found is None:
                raise Refuse(405, "method not allowed", {"Allow": ", ".join(sorted(methods))})
            _, who, fn = found
        else:
            if req.method != "GET":
                raise Refuse(405, "method not allowed", {"Allow": "GET"})
            who, fn = COOKIE, self._page
        if req.kind not in who:
            raise Refuse(403, who.refusal)
        if req.method == "POST" and req.kind == "cookie" \
                and not auth.origin_ok(req.headers.get("origin"), req.host):
            raise Refuse(403, "this request did not come from the hub's own page")
        if req.method == "POST" and who.raw_body:
            if req.kind == "key":
                req.display = self._door_name(req)
            req.raw = self._body(req, raw, MAX_AUDIO if who is AUDIO else MAX_BODY)
        elif req.method == "POST":
            self._read_body(req, self._body(req, raw))
        return fn(req)

    # ── the proxy socket (9.9) ───────────────────────────────────────────────
    def _index_events(self, member):
        """What a member's index stream is sent (9.9): a `status` only for a document of theirs
        whose file moved, naming nothing but the document (the page asks for its own index
        again, with their own dots), and no `signed-out`. Judged on the stream's own thread
        (`events.Subscription`): a failure to judge one is written down, and they are told nothing
        of it."""
        def accept(name: str, data):
            if name == "signed-out":
                return None
            if name == "status":
                doc = data.get("doc") if isinstance(data, Status) and data.files else None
                if not isinstance(doc, str):
                    return None
                try:
                    theirs = self.hub.member_owns(member, doc) and self.hub.visible(member, doc, never_read=False)
                except Exception:
                    self.hub.record_exception("status-failed", doc)
                    return None
                return {"doc": self.hub.alias(member, doc), "root": data.get("root")} if theirs else None
            return data
        return accept

    @staticmethod
    def _for_members(found) -> bool:
        """A route a member may use: one 8.5 marks `cookie` or `cookie or key`, but not Tell,
        which a member uses only for an agent of theirs (_tell); and the two open files the front mounts a page from (#116)."""
        name, who, _ = found
        if name in ("mount-js", "mount-css"):
            return True
        return who in (COOKIE, EITHER, MEMBER, MINT) and who.proxy and name != "jump"

    def _route_proxy(self, req: Req, raw: bytes) -> Response:
        cfg = self.hub.proxy
        req.auth = self.hub.auth
        uid = req.conn.uid if isinstance(req.conn, proxy.Peer) else None
        if cfg is None or uid is None or uid != cfg.uid:
            raise Refuse(403, "this socket serves only the proxy's account", row="proxy-peer",
                         fields={"uid": uid}, detail=f"a connection of uid {uid}; the proxy's account is "
                         f"{cfg.proxy_user if cfg else None} (uid {cfg.uid if cfg else None})")
        # The proxy set the member header (9.9), so from here on every row names it (15).
        req.member_id = req.headers.get("x-sheaf-member", "")
        if req.host.lower() != cfg.host:
            raise Refuse(403, "this hub answers on its proxy socket only to its front's host")
        if not req.path.startswith("/"):
            raise Refuse(400, "bad request target")
        # The hub-to-hub channel, the one prefix with no member: a peer tiroir's token and nothing else decides (ticket 20).
        if req.path.startswith("/_/tiroir/"):
            return self._route_channel(req, raw)
        # A sign-in code the verifier let in, judged before the route, the method and the body (9.13).
        if req.headers.get("x-sheaf-code"):            # an empty one is none, as an empty member header
            return self._route_code(req, raw)
        # The member header alone says who asks, before the route and the method (9.3, 9.9).
        if not req.member_id:
            raise Refuse(401, "not signed in", page=PROXY_SIGN_IN)
        req.member = cfg.members.get(req.member_id)
        if req.member is None:
            raise Refuse(403, proxy.NO_DOCUMENTS, page=proxy.NO_DOCUMENTS)
        if req.path.startswith("/_/"):
            allowed = {m: f for m, f in (self.routes.get(req.path) or {}).items() if self._for_members(f)}
            if not allowed:
                raise Refuse(404, "no such route")
            found = allowed.get(req.method)
            if found is None:
                raise Refuse(405, "method not allowed", {"Allow": ", ".join(sorted(allowed))})
            req.route, _, fn = found
        else:
            req.route, fn = "page", self._page
            if req.method != "GET":
                raise Refuse(405, "method not allowed", {"Allow": "GET"})
        # Every POST, since the member header is the only credential here: a page of another name
        # of the same site can make the browser send the front's cookie (9.9, Host and Origin).
        if req.method == "POST" and req.headers.get("origin", "").lower() != cfg.origin:
            raise Refuse(403, "this request did not come from the front's own page")
        if req.method == "POST":
            self._read_body(req, self._body(req, raw))
        self._unalias(req)
        return fn(req)

    def _route_channel(self, req: Req, raw: bytes) -> Response:
        """`/_/tiroir/<verb>` (ticket 20): a peer tiroir's POST, let in by its peer token from the tailnet. Every refusal is the answer of
        a route this hub does not have, so the caller cannot tell a wrong source from a wrong token; the row says which. The
        member header and a sign-in code are not read: a person's credential opens nothing here."""
        req.member_id, req.route = "", "tiroir"
        row, why = channel.peer_for(self.hub, req)
        if row is None:
            raise Refuse(404, "no such route", row="peer-refused", fields={"reason": why})
        req.token = row
        verb = req.path.removeprefix("/_/tiroir/")
        self._read_body(req, self._body(req, raw, channel.MAX_TRANSFER if verb == "transfer" else channel.MAX_ASK))
        return getattr(self, f"_peer_{verb}")(req)

    def _peer_resolve(self, req: Req) -> Response:
        """Whether this tiroir has a member for the e-mail: asked before a page is bundled; `transfer` asks again."""
        owner, why = incoming.owner_for(self.hub, req.body.get("owner_email"))
        return _json(200, {"ok": True}) if owner is not None else _json(409, {"ok": False, "why": why})

    def _peer_transfer(self, req: Req) -> Response:
        """Land a page moved here (ticket 20): `incoming.land`. Whatever fails after the page was made takes it back and is a 500
        the sender reads as a failed transfer, so it keeps its page."""
        try:
            status, answer = incoming.land(self.hub, self.door, req.body, peer=req.token.peer, deadline=req.arrived + channel.SECONDS)
        except ValueError as e:
            raise Refuse(400, str(e)) from None
        return _json(status, answer)

    def _peer_read(self, req: Req) -> Response:
        """A page route of a client's member run here, the client tiroir (ticket 23): `readthrough.answer` says who and what."""
        try:
            return _json(*readthrough.answer(self, req.body, gone=req.gone))
        except sheaf_view.Abandoned:
            raise Refuse(499, "the caller closed the connection") from None

    def _peer_comment(self, req: Req) -> Response:
        """A comment of an agency member written here under their name (ticket 23)."""
        return _json(*readthrough.comment_answer(self, req.body))

    def _unalias(self, req: Req) -> None:
        """A page Shared with the member is told to them under an opaque name (`Hub.alias`, 9.11): the one they send back, in
        the path, the query or the body, is read as the page's own address before any route looks at it."""
        hub = self.hub
        if not req.path.startswith("/_/") and (address := address_of_url(req.path)) is not None:
            req.path = url_path(hub.unalias(address))
        for fields in (req.query, req.body if isinstance(req.body, dict) else {}):
            if isinstance(fields.get("doc"), str):
                fields["doc"] = hub.unalias(fields["doc"])

    def _route_code(self, req: Req, raw: bytes) -> Response:
        """A request the verifier let in with a sign-in code (9.13): `X-Sheaf-Code` is the code's sha256, and Caddy
        sends no member header with it. The code says who asks, and opens the transcript and the fork of its one
        sheaf, the POST's Origin checked as every proxy POST's. Any answer to a POST spends the code."""
        cfg = self.hub.proxy
        req.route = CODE_ROUTES.get((req.method, req.path), req.path)
        if req.member_id:
            raise self._code_refused(req, None, "two-credentials")
        code, why = self.codes.find(req.headers["x-sheaf-code"])
        if why is None and code.member not in cfg.members:
            why = "member"
        if why is not None:
            raise self._code_refused(req, code, why)
        req.code, req.member, req.member_id = code, cfg.members[code.member], code.member
        try:
            if (req.method, req.path) not in CODE_ROUTES:
                raise self._code_refused(req, code, "route", 404, "no such route")
            if req.method == "POST":
                if req.headers.get("origin", "").lower() != cfg.origin:
                    raise Refuse(403, "this request did not come from the front's own page")
                self._read_body(req, self._body(req, raw))
            return self._session(req) if req.method == "GET" else self._sessions(req)
        finally:
            if req.method == "POST":
                self.codes.spend(code)

    def _code_refused(self, req: Req, code, reason: str, status: int = 401, message: str = codes.NO_GOOD) -> Refuse:
        """The refusal of a sign-in code and its `code-refused` row (15), which names the code by its id. One
        sentence answers every 401, so a guesser learns nothing; made-up codes are counted, one row a minute."""
        fields = {"reason": reason, "route": req.route}
        if code is not None:
            fields["code"] = code.id
        if reason == "unknown":
            n = self.codes.unknown()
            if not n:
                return Refuse(status, message, row=False)
            fields["count"] = n
        return Refuse(status, message, row="code-refused", fields=fields)

    def _token(self, req: Req) -> bool:
        """Whether the request carries an MCP token that is good now; its owner is on `req.token`."""
        row = self.hub.tokens.verify(auth.bearer(req.headers.get("authorization")))      # never a peer's token: that opens the channel only
        if row is not None and row.member is not None:
            # a laptop's token acts for its member: one the table no longer names is refused, never read as unbound
            cfg = self.hub.proxy
            if cfg is None or row.member not in cfg.members:
                row = None
        req.token = row
        return row is not None

    @staticmethod
    def _door_name(req: Req) -> str:
        """The name the door's replies are signed with, for a caller that holds the key: the
        `X-Sheaf-As` header, percent-encoded UTF-8 (SPEC 12), then made one safe line. A token has
        its own name; the key has only this one, so a request without it is refused."""
        header = req.headers.get("x-sheaf-as", "")
        try:
            if not header.isascii():       # a raw byte above U+007F arrives as Latin-1: refused, never guessed
                raise UnicodeDecodeError("ascii", b"", 0, 1, "raw byte above U+007F")
            name = auth.clean_display(unquote(header, errors="strict"))
        except UnicodeDecodeError:
            raise Refuse(400, "X-Sheaf-As is not percent-encoded UTF-8") from None
        if not name:
            raise Refuse(400, "a request with the hub key needs X-Sheaf-As, the name its reply is signed with")
        return name

    def _body(self, req: Req, raw, limit: int = MAX_BODY) -> bytes:
        """The body, now that the caller is known to be let in: refused by its header when it is
        over the limit, before a byte of it is read."""
        try:
            n = int(req.headers.get("content-length") or (0 if callable(raw) else len(raw)))
        except ValueError:
            raise Refuse(400, "bad Content-Length") from None
        if n > limit:
            raise Refuse(413, "the request is too large")
        raw = raw() if callable(raw) else raw
        if len(raw) > limit:
            raise Refuse(413, "the request is too large")
        return raw

    def _read_body(self, req: Req, raw: bytes):
        try:
            body = json.loads(raw.decode("utf-8") if raw.strip() else "{}")
        except (ValueError, UnicodeDecodeError):
            raise Refuse(400, "the body is not JSON") from None
        _shape(isinstance(body, dict), "the body is not a JSON object")
        req.body = body

    # ── helpers for the routes ───────────────────────────────────────────────
    def _owned(self, req: Req, doc, never_read: bool = True):
        """The address `doc` names, once the request may name it: text, and for a member one of their
        own roots and none whose visibility is its owner's alone when they are not the owner (9.11). Reads
        no more than the front matter, so it holds for a document that is gone. `never_read` is what a gone file the
        hub never read is judged as (`Hub.visible`)."""
        _shape(isinstance(doc, str), "doc is missing")
        if req.member is not None and not (self.hub.member_owns(req.member, doc)
                                           and self.hub.visible(req.member, doc, **({} if never_read else {"never_read": False}))):
            raise Refuse(404, "no such document")
        return doc

    def _reading(self, doc):
        """The lock of the rectoverso's name `doc` (9.11), held by a read from the check of its visibility to the page
        or text sent: no write or move of its file comes between."""
        return place.held(self.hub, doc) if isinstance(doc, str) else contextlib.nullcontext()

    def _entry_to_write(self, req: Req, doc):
        """`_entry` for a route that writes: a clone that sleeps wakes first, once the caller may see the document."""
        if readthrough.is_clients(doc):          # a client page is read through (9.9): only its comments are relayed
            raise Refuse(403, "A client page is read here: comment on it, or edit it on the client tiroir.")
        self._owned(req, doc)
        self.hub.wake_for_write(doc, visibility.owner_key(req.member) if req.member is not None else None)
        return self._entry(req, doc)

    def _entry(self, req: Req, doc):
        """The document `doc` names. A member of proxy mode is told of no document of another
        root, nor of a root nested inside one of theirs: the same 404 as for one that does not
        exist, before anything is made or rendered for it (9.9)."""
        if readthrough.is_clients(doc):          # a client page is read through (9.9): only its comments are relayed
            raise Refuse(403, "A client page is read here: comment on it, or edit it on the client tiroir.")
        self._owned(req, doc)
        try:
            return self.hub.entry(doc)
        except NotFound:
            raise Refuse(404, "no such document") from None

    # ── who is at the other end (9.3) ────────────────────────────────────────
    def _owner(self, req: Req):
        """Why the connection of `req` is no one's to redeem a link: the answer the server got when it accepted
        it, else a lookup now (a test hands the handler a connection it did not look at). None where the
        hub's own user is at its other end, or where the hub does not check."""
        if self.peer_off:
            return None
        conn = req.conn
        if getattr(conn, "looked", False):
            return self._judged(conn)
        return self.peer_check(conn)

    def _judged(self, conn):
        """The refusal the server found for `conn`, or None. A connection read as the hub's own user shows that
        lookups work, so a self-test that raised at start was a passing failure: its leniency ends (ticket 178)."""
        if conn.refusal is None and self.peer_selftest_raised:
            self.peer_selftest_raised = None
        return conn.refusal

    def _checks_peer(self) -> bool:
        """Whether this hub judges a sign-in link, a cookie and the key by the user of the connection:
        not on a platform that gives it no way, nor where its start-up self-test turned the check off.
        Told to `sheaf open` in the answers of `/_/render` and `/_/signin` as `peer_check`, so that the
        command can say so (ticket 99); never in `/_/health`, which another user may read."""
        return peer.supported() and not self.peer_off

    def _gate(self, req: Req):
        """A key or a cookie is good only from the hub's own user (9.3): a caller whose connection the hub
        looked at when it accepted it, and found owned by another user or by no one it could name, is
        refused before anything is read or done. A caller that closed its connection before the hub
        could say is told to try again, never that it was refused: its write is not applied. After a start-up
        self-test that raised, a connection read as no one's is let in until one is read as the hub's own."""
        conn = req.conn
        if self.peer_off or not getattr(conn, "looked", False) or self._judged(conn) is None:
            return
        # A closed caller reads as no one's (uid 0), so only an answer that could be that is a "try again";
        # another user's uid stays a refusal, with its row, whether or not the caller has closed since.
        no = conn.refusal
        if conn.closed is not None and conn.closed() and (no.kind != peer.OTHER_USER or no.uid == 0):
            raise Refuse(503, "try again: the connection closed before the hub could tell who sent this",
                         {"Retry-After": "1"}, row=False)
        if self.peer_selftest_raised and no.kind != peer.OTHER_USER:
            # The self-test raised, so a lookup that fails may fail every time: the key and the cookie, which
            # no other user can read, are let through then; only the nonce, on a command line, fails closed.
            return
        no, mine = conn.refusal, os.geteuid()
        other = no.kind == peer.OTHER_USER
        row = "peer-refused"
        with self._peer_row_lock:        # threads refused together write one row, not one each
            # One row a minute for each kind, so an unknown caller hides no other user's uid.
            if time.monotonic() - self._peer_row_times.get(no.kind, float("-inf")) < PEER_ROW_SECONDS:
                row = False              # not written: a loop of refused requests is one row a minute
            else:
                self._peer_row_times[no.kind] = time.monotonic()
        detail = no.detail
        if other:
            detail = f"a request from another user of this machine (uid {no.uid}); the hub runs as uid {mine}"
        raise Refuse(403, "this hub answers only to the user that runs it" if other
                     else "the hub could not tell which user of this machine sent this request",
                     page=REQUEST_OTHER_USER if other else REQUEST_UNKNOWN, detail=detail, row=row,
                     fields={"peer_uid": no.uid, "hub_uid": mine} if other else {})

    # ── open routes ──────────────────────────────────────────────────────────
    def _health(self, req: Req) -> Response:
        hub = self.hub
        out = {"app": "sheaf", "version": hub.version, "boot": hub.boot, "service": hub.service}
        if "nonce" in req.query:
            nonce = req.query["nonce"]
            _shape(auth.nonce_ok(nonce), "nonce must be 16 to 128 lowercase hex characters")
            out["proof"] = hub.auth.proof(nonce)
        return _ok(**out)

    def _open(self, req: Req) -> Response:
        if "nonce" in req.query:
            # Asking spends the link, whatever the answer. Only then is the caller looked at: a link
            # that was read from a command line is good for the user who runs the hub, not for another (9.1).
            if not req.auth.redeem_signin(req.query["nonce"]):
                raise Refuse(401, "that sign-in link was used already, has expired or is not this hub's",
                             page=LINK_USED if self._checks_peer()
                             else f"{LINK_USED} {LINK_ROTATE} {LINK_LIMIT}")
            no = self._owner(req)
            if no is not None:
                page = (LINK_OTHER_USER if no.kind == peer.OTHER_USER
                        else LINK_UNTESTED if self.peer_selftest_raised else LINK_UNKNOWN)
                raise Refuse(401, no.message, page=page, detail=no.detail)
        elif not req.auth.key_ok(req.query.get("key")):
            raise Refuse(401, "that is not this hub's key", page=WRONG_KEY)
        else:
            self._gate(req)
        nxt = req.query.get("next", "/")
        _shape(auth.safe_next(nxt), "next must be a path on this hub")
        return Response(303, {"Location": auth.location(nxt), "Set-Cookie": req.auth.set_cookie()})

    def _signin(self, req: Req) -> Response:
        """A one-time sign-in nonce for the caller that holds the key (`sheaf open`, 9.3)."""
        return _ok(nonce=req.auth.mint_signin(), expires=auth.SIGNIN_TTL, peer_check=self._checks_peer())

    # ── the page and its streams ─────────────────────────────────────────────
    def _page(self, req: Req) -> Response:
        nonce = auth.new_nonce()
        if req.path == "/":
            return _html(200, self.hub.index.page(nonce, member=req.member), nonce)
        address = address_of_url(req.path)
        if address is None:
            # `/<root>` with no slash after it names the root's page, where the browser is sent.
            bare = req.path.count("/") == 1
            name = root_of_url(req.path + "/" if bare else req.path)
            if name is None:
                raise Refuse(404, "no such page")
            root = self.hub.roots.get(name)
            if root is None or (req.member is not None and not self.hub.owns(req.member, root)):
                raise Refuse(404, "no such root")
            # The list's root: its page is the list, at `/<root>` itself, for a member (9.10).
            the_list = self.hub.the_list
            if req.member is not None and the_list is not None and the_list.serves(name):
                return _html(200, the_list.page(req.member, req.query.get("show", ""), nonce), nonce)
            if bare:
                return Response(301, {"Location": req.path + "/"})
            return _html(200, self.hub.index.page(nonce, only=name, member=req.member), nonce)
        if not address.endswith(".md"):
            raise Refuse(404, "no such page")
        if readthrough.is_clients(address):
            return self._relay(req, address, "page")
        if (to := self._forwarded(req, address)) is not None:
            # 302 and never 301, and never cached: the page can move back, and a browser that kept a 301 from A to B
            # would then loop between the two. "For ever" is the Forward's, not the redirect's.
            return Response(302, {"Location": to, "Cache-Control": "no-store"})
        if not self._has_file(address) and (asleep := self._asleep(req, address)) is not None:
            return asleep
        with self._reading(address):
            e = self._entry(req, address)
            self.hub.catch_up(e)
            return _html(200, self.hub.page(e, nonce, member=req.member, mount=req.mount), nonce)

    def _asleep(self, req: Req, address: str) -> Response | None:
        """A page of a clone that sleeps has no file (SPEC 13): the clone wakes for the page's owner, who is then served the
        page, and anyone else who may see it reads a page that says it sleeps and what wakes it, not a 404 for a page that
        exists. Any other missing page is left to `_entry`'s 404."""
        self._owned(req, address)
        key = visibility.owner_key(req.member) if req.member is not None else None
        self.hub.wake_for_write(address, key)
        repo = self.hub.clone_of(address)
        if repo and not self._has_file(address) and self.hub.repos.sleeping(repo) and self.hub.judged(address) is not None:
            line = escape(self.hub.read_only_line(address))
            res = _html(503, _sign_in_page("This repo's clone is asleep", line))
            res.error = "clone asleep"
            return res
        return None

    def _forwarded(self, req: Req, address: str) -> str | None:
        """The place (a path here, a full address on another tiroir) where the old address `address` of a page now leads, for the one who
        may be led there: the page's owner, or the hub's person. None for everyone else, and for an address a page stands at: the
        answer is then the one of an address never used, so no one learns that a page once was there (9.11)."""
        hub, member = self.hub, req.member
        to = hub.forwards.follow(address)
        if to is None or self._has_file(address):
            return None
        if (far := hub.forwards.remote(address)) is not None:
            # The page went to another tiroir (ticket 20). Its owner is the one who may be told; the other tiroir asks for its own
            # sign-in and answers what the visitor may open.
            if member is not None and hub.loose_owner(address) != member.id:
                return None
            hub.record("moved-knock", address, via="browser", place="", member=member.short if member else "", to=far["origin"])
            return far["origin"] + url_path(to)
        if member is not None and not (hub.loose_owner(to) == member.id and hub.member_owns(member, to)
                                       and hub.visible(member, to)):
            return None
        return url_path(to)

    def _has_file(self, address: str) -> bool:
        try:
            self.hub.roots.document(address)
        except NotFound:
            return False
        return True

    def _live(self, req: Req) -> Response:
        if "shared" in req.query:
            return self._shared_stream(req)
        if readthrough.is_clients(req.query.get("doc")):         # a client page is polled through `/_/doc`, never streamed (9.9)
            raise Refuse(404, "no such document")
        if "doc" not in req.query:
            return _stream(self._index_sub(req))
        with self._reading(req.query.get("doc")):
            return self._document_stream(req)

    def _index_sub(self, req: Req):
        hub, member = self.hub, req.member
        sub = hub.open_index_stream(lambda _: {"boot": hub.boot, "version": hub.version,
                                               "service": hub.service},
                                    self._index_events(member) if member else None)
        if member is None and hub.auth is not req.auth:   # a rotation overtook this request, after it told the open streams
            sub.put("signed-out", {})
        return sub

    # ── one stream for every tab of a browser (ticket 160) ───────────────────
    # A browser opens six connections to a host at most, and each tab held one. One tab of the
    # browser now opens `/_/live?shared=ID` and joins the streams of all of them to it, each the
    # Subscription its own `/_/live` would have been: the same Bus counts it as an open tab.
    # The cap is soft by a few: the count and the add are not atomic.
    SHARED_MAX = 200         # streams on one connection: far more tabs than a browser holds

    def _shared_stream(self, req: Req) -> Response:
        sid = req.query.get("shared", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", sid):
            raise Refuse(400, "a shared stream needs an id of 16 to 64 letters, digits, - or _")
        owner = req.member.id if req.member is not None else None
        stream = _SharedStream(self, sid, owner)
        with self._shared_lock:
            old = self._shared.get(sid)
            if old is not None and old.owner != owner:
                raise Refuse(409, "that stream id is someone else's")   # an id read from a log closes no one's tabs
            self._shared[sid] = stream
            self._shared_opened += 1
            stream.seq = self._shared_opened
        if old is not None:
            old.close()                  # the same browser came back before the old connection was seen to close
        return _stream(stream)

    def _shared_of(self, req: Req) -> "events.Shared":
        sid = req.body.get("stream")
        with self._shared_lock:
            stream = self._shared.get(sid) if isinstance(sid, str) else None
        owner = req.member.id if req.member is not None else None
        if stream is None or stream.closed or stream.owner != owner:
            raise Refuse(404, "no such stream")
        return stream

    def _live_join(self, req: Req) -> Response:
        """Adds a tab's stream to a shared one: `key` names it there, `doc` is its document, "" the index."""
        stream = self._shared_of(req)
        key, doc = req.body.get("key"), req.body.get("doc", "")
        if not isinstance(key, str) or not key or len(key) > 128 or not isinstance(doc, str):
            raise Refuse(400, "join needs a key and a doc")
        if key not in stream.keys() and len(stream.keys()) >= self.SHARED_MAX:
            raise Refuse(429, "too many streams on this connection")
        sub = self._joined_sub(req, doc)
        # A key names one tab. After a leader hand-over the tab joins the new connection while the old one, whose tab
        # closed, is still open here until a write to it fails: drop the key there, or the hub counts the tab twice.
        # The old leader's own join of the key can reach the hub after that (ticket 181 D): once a newer connection
        # had the key, held still or left since, the late join is dropped.
        with self._join_lock:
            with self._shared_lock:
                others = [s for s in self._shared.values() if s is not stream and s.owner == stream.owner]
            if not any(s.seq > stream.seq and key in s.had for s in others):
                stream.had.add(key)
                stream.join(key, sub)
                for other in others:
                    other.leave(key)
                return _ok()
        if not isinstance(sub, int):
            sub.close()
        return _ok()

    def _joined_sub(self, req: Req, doc: str):
        """The Subscription a tab's own `/_/live` would have been given, or the status it would have been refused with."""
        if not doc:
            return self._index_sub(req)
        if readthrough.is_clients(doc):
            return 404
        one = replace(req, query={"doc": doc})
        try:
            with self._reading(doc):
                return self._document_stream(one).stream
        except Refuse as r:
            return r.status
        except (FileNotFoundError, NotFound):
            return 404

    def _live_leave(self, req: Req) -> Response:
        stream = self._shared_of(req)
        key = req.body.get("key")
        if isinstance(key, str):
            stream.leave(key)
        return _ok()

    def _shared_closed(self, sid: str, stream):
        with self._shared_lock:
            if self._shared.get(sid) is stream:
                del self._shared[sid]

    def _document_stream(self, req: Req) -> Response:
        hub, member = self.hub, req.member
        e = self._entry(req, req.query.get("doc"))
        def for_member(name, data):
            if name == "moved":      # the page went elsewhere (9.11): told to its owner alone, where it went
                to = data.get("to") if isinstance(data, dict) else None
                if isinstance(data, dict) and isinstance(data.get("origin"), str):     # to another tiroir (ticket 20): only its owner is led
                    if hub.loose_owner(data["doc"]) == member.id:
                        return {"doc": data["doc"], "to": data["to"], "origin": data["origin"]}
                    opaque = data.get("opaque")     # made before the page left, as the recipient's tab holds it: none is made now
                    return events.Renamed("gone", {"doc": f"{data['doc'].split('/', 1)[0]}/{opaque}.md"}) if isinstance(opaque, str) else None
                if isinstance(to, str) and hub.loose_owner(to) == member.id and hub.visible(member, to):
                    return {"doc": data["doc"], "to": to}
                if isinstance(to, str) and hub.visible(member, to):     # a recipient is never led: the page is gone from here, told as it is told them
                    return events.Renamed("gone", {"doc": hub.alias(member, to)})
                return None
            # Asked at each event: a write that makes the rectoverso its owner's alone silences a stream
            # opened before it (9.11). A change of `projects.toml` that shuts the member out is told `gone`, with
            # why (8.12): that alone, never a file of the rectoverso that cannot be read for a moment.
            # `member_owns` as well, but for `gone`: a Share edited down or withdrawn (9.11) closes the page for the member it
            # no longer names, and a root that is forgotten (no root to own it) is still told.
            if hub.visible(member, e.address) and (name == "gone" or hub.member_owns(member, e.address)):
                if name in waiting_mod.EVENTS:      # a Tell that waits for an agent: the member's own, and no other's (9.9)
                    return dict(data) if getattr(data, "member", None) == member.id else None
                data = _document_events(name, data)
                if name == "gone" and isinstance(data, dict) and isinstance(data.get("doc"), str):
                    data = {**data, "doc": hub.alias(member, data["doc"])}      # told as the page is told (9.11), never the owner's folders
                if name == "changed" and isinstance(data, dict) and "telling" in data:     # their own, not the hub person's (9.9)
                    data = {**data, "telling": self._member_telling(e.address, member, sweep=False, comments=data.get("comments"))}
                return data
            if name == "grants" and not hub.granted(member, e.address):
                return events.Renamed("gone", {"doc": hub.alias(member, e.address), "why": "access"})
            return None
        def for_person(name, data):
            # The hub person's page is not told of a member's Tell, nor of the agent it waits for (9.8, 9.9).
            return None if name in waiting_mod.EVENTS and getattr(data, "member", None) is not None else data
        sub = e.bus.subscribe(lambda tabs: {"boot": hub.boot, "version": hub.version,
                                            "service": hub.service, "tabs": tabs},
                              for_member if member else for_person)
        if member is None and hub.auth is not req.auth:       # a rotation overtook this request, after it told the open streams
            sub.put("signed-out", {})
        if hub.entries.get(e.address) is not e:               # a forget overtook this request, after it told the open streams
            sub.put("gone", {"doc": hub.alias(member, e.address)})
        e.opened = True
        return _stream(sub)

    def _root_id(self, req: Req, address: str) -> str | None:
        """The id of the root that holds the name `address` starts with now (8.2), which a page whose
        stream comes back compares with the one it was served from (10.7); None when no root holds it. A
        member is told it only of a root of theirs: of another's None, as of a name no root holds, so they
        are never told that another root exists (9.9)."""
        root = self.hub.roots.get(Address.parse(address).root)
        if root is None or (req.member is not None and not self.hub.owns(req.member, root)):
            return None
        return root.id

    def _page_wrote(self, req: Req, e, via: str):
        """The Write log's line of a write from a page or its row: the member's name, else the hub's person."""
        self.hub.writes.add(e.address, req.member.name if req.member else self.hub.person, "page", via)

    def _writes(self, req: Req) -> Response:
        """The Write log of one rectoverso: its lines, the last write and the last line that named an agent session. A
        member reads the lines of a document they may name, no other (9.9)."""
        if readthrough.is_clients(req.query.get("doc")):         # the client tiroir's Write log is the client's: this hub keeps none of it
            return _ok(lines=[], last=None, last_session=None)
        doc = self._owned(req, req.query.get("doc"), never_read=False)     # the lines outlive a restart, whom the page was visible to does not
        log = self.hub.writes
        told = self.hub.alias(req.member, doc)         # a Shared page is told under its opaque name (9.11), never the owner's folders
        return _ok(lines=[_line(l, told) for l in log.lines(doc)], last=_line(log.last(doc), told),
                   last_session=_line(log.last_session(doc), told))

    def _doc(self, req: Req) -> Response:
        if readthrough.is_clients(req.query.get("doc")):
            return self._relay(req, req.query["doc"], "doc")
        with self._reading(req.query.get("doc")):
            return self._doc_state(req)

    def _doc_state(self, req: Req) -> Response:
        doc = req.query.get("doc")
        try:
            e = self._entry(req, doc)
        except Refuse as r:
            if r.status == 404:         # a file gone from its root, or a root gone from its name (10.7)
                r.answer = {"root": self._root_id(req, doc)}
            raise
        self.hub.waiting_tells.sweep()      # a revoked token's Tells end here (9.8), before they are named
        snap = e.live.snapshot()
        snap["root"] = self._root_id(req, e.address)
        snap["rids"] = e.live.taken_rids()
        if req.member is not None:
            # Their own seen state, and nothing of the hub account's agent session (9.9).
            # A rectoverso's Work on this and its Tell for James's window are refreshed as the meta's (9.12).
            self.hub.opened_by(req.member, e.address)
            work, can = self.hub.member_work(e, req.member)
            extra = {} if work is None else {"work": work}
            mt = self.hub.member_target(e.address, req.member, can)
            got = {**proxy.for_member(snap), "telling": self._member_telling(e.address, req.member, text=e.live.current()[1]),
                   "seen": self.hub.member_seen.get(req.member.id, e.address),
                   "question": "", "target": mt.agent, "targets": mt.picks, "capabilities": mt.can, "lines": mt.lines,
                   "way_back": sheaf_view.byline(self.hub, e.address, req.member),
                   "sent": self.hub.box_waits.pending(e.address, e.live.current()[1]), **extra}
            return _ok(**(readthrough.read_only_doc(got) if req.mount else got))
        v = self.hub.tell.view(e.address)
        return _ok(**snap, seen=self.hub.seen.get(e.address),
                   question=e.live.session_question(), target=v.agent(),
                   targets=targets.choices(self.hub, e.address),
                   capabilities=sorted(v.caps), lines=v.lines)

    def _member_telling(self, address, member, sweep=True, comments=None, text=None) -> list:
        """A member's `telling` (9.9): their own Tells that wait for an agent (9.8) and their own drops for
        James's window (9.12), and nothing of the hub account's session or of another member's."""
        return (self.hub.waiting_tells.waits(address, member, sweep=sweep)
                + self.hub.session_tells.waits(address, member)
                + self.hub.box_waits.telling(address, member.id, comments=comments, text=text))

    def _mount(self, req: Req) -> Response:
        """The rectoverso as JSON for the front's loader to mount (#116): the body through the sanitiser's mount mode and the
        meta block the page route sends. The same gate as the page: a member sees what they could open. With `list=`
        instead of `doc=`, the list."""
        if "list" in req.query:
            return self._mount_list(req)
        if "sheaf" in req.query:
            return self._mount_sheaf(req)
        doc = req.query.get("doc")
        _shape(isinstance(doc, str) and doc.endswith(".md"), "doc must be the address of a rectoverso")
        if readthrough.is_clients(doc):
            return self._relay(req, doc, "mount")
        with self._reading(doc):
            e = self._entry(req, doc)
            self.hub.catch_up(e)
            try:
                got = self.hub.mount_doc(e, req.member, req.mount)
            except RenderError as ex:
                raise Refuse(500, f"the page could not be rendered: {ex}") from None
            return _json(200, got, {"X-Content-Type-Options": "nosniff"})

    def _mount_list(self, req: Req) -> Response:
        """The list (9.10) as data for the front to mount (#116): its rows as the page at `/<root>` shows them to the
        member, every title and name as text, never markup. A member's alone, of the root the list is, as that page is."""
        name, the = req.query.get("list"), self.hub.the_list
        root = self.hub.roots.get(name) if isinstance(name, str) else None
        if req.member is None or the is None or root is None or not self.hub.owns(req.member, root) or not the.serves(name):
            raise Refuse(404, "no such list")
        return _json(200, {"kind": "list", "title": "Actions", "version": self.hub.version,
                           **self.hub.mount_fields(),
                           "list": the.data(req.member, req.query.get("show", ""))},
                     {"X-Content-Type-Options": "nosniff"})

    def _mount_sheaf(self, req: Req) -> Response:
        """The Sheaf (8.6) as data for the front to mount: a member's tree of folders and table of rectoversos, every title
        and name as text, never markup. A member's alone, as the index is; the hub's own person has the index page."""
        if req.member is None:
            raise Refuse(404, "no such page")
        try:
            sheaf = sheaf_view.data(self.hub, req.member, self._titles, req.query.get("view", ""), gone=req.gone)
        except sheaf_view.Abandoned:
            raise Refuse(499, "the caller closed the connection") from None
        if self.hub.clients is not None:
            sheaf = sheaf_view.with_clients(sheaf, self.hub.clients.names(), req.member.email)
        return _json(200, {"kind": "sheaf", "title": "Sheaf", "version": self.hub.version, **self.hub.mount_fields(), "sheaf": sheaf},
                     {"X-Content-Type-Options": "nosniff"})

    def _clients_sheaf(self, req: Req) -> Response:
        """The rows of one client tiroir under "Clients" (9.9), read through when the node is opened and kept nowhere: the client
        hub tells what this member may open there, and a client that does not answer is told as one line, never as rows from
        an earlier read."""
        clients, name = self.hub.clients, req.query.get("client")
        if req.member is None or clients is None or not isinstance(name, str) or not clients.has(name):
            raise Refuse(404, "no such page")
        try:
            rows = readthrough.fold_rows(name, clients.read(name, req.member, "sheaf").get("rows", []))
        except readthrough.NoEmail as e:
            return _json(200, {"client": name, "rows": [], "tree": [], "line": str(e)})
        except readthrough.NotReachable:
            self._knock(req, name, "sheaf", "unreachable")
            return _json(200, {"client": name, "rows": [], "tree": [], "line": "This client tiroir is not reachable now."})
        self._knock(req, name, "sheaf", "ok")
        return _json(200, {"client": name, "rows": rows, "tree": sheaf_view.tree(rows), "line": ""}, {"X-Content-Type-Options": "nosniff"})

    def _relay(self, req: Req, address: str, op: str) -> Response:
        """A page route on an address under `Clients/` (9.9): the client tiroir runs it for this member and this hub sends the answer
        on, text as it came, with the client's own headers and nonce. This hub reads no file and keeps nothing of it."""
        clients, found = self.hub.clients, None
        if clients is not None and req.member is not None:
            found = clients.split(address)
        if found is None:
            raise Refuse(404, "no such document")
        client, rest = found
        return self._relayed(req, client, op, lambda: clients.relay(client, req.member, op, rest, mount=f"Clients/{client}"), address)

    @staticmethod
    def _side(b: dict) -> str:
        """Whose verso a comment on a client page is for (9.11): `team` stays on this hub, `client` goes to the client's hub. A write
        on a comment names its side by its id (`tN` is a Team comment); an add must name its side."""
        side = b.get("side")
        _shape("side" not in b or side in ("team", "client"), "side must be team or client")
        if b.get("op") == "add":
            _shape("side" in b, "choose team or client: a comment on a client page names its side")
            return side
        cid = b.get("id")
        mine = "team" if isinstance(cid, str) and team_mod.ID_RE.fullmatch(cid) else "client"
        _shape(side in (None, mine), f"that comment is a {mine} comment: side must be {mine}")
        return mine

    def _relay_comment(self, req: Req) -> Response:
        clients, found = self.hub.clients, None
        if clients is not None and req.member is not None:
            found = clients.split(req.body["doc"])
        if found is None:
            raise Refuse(404, "no such document")
        _shape(not req.body.get("tell"), "Tell is not offered on a client page")
        client, rest = found
        request = {k: v for k, v in req.body.items() if k not in ("doc", "as", "role", "side")}
        return self._relayed(req, client, "comment", lambda: clients.comment(client, req.member, rest, request))

    def _with_team(self, op: str, body: str, doc: str, me: str) -> str:
        """The page's Team comments (9.11) told beside the client's own `comments`: in the doc state, in the mount's config and in the
        meta block of the page, never merged into the client's list. The client hub's 200 is the gate: the member may open it. `team_me` is the
        member's name on this hub, which signs a Team comment: the page's own `me` is the one the client tiroir gave."""
        team = self.hub.team.list(doc)
        if op == "page":
            def with_team(m):
                try:
                    meta = json.loads(m.group(2))
                except ValueError:
                    return m.group(0)       # as the doc and mount branches leave a body they cannot read
                if not isinstance(meta, dict):
                    return m.group(0)       # valid JSON that is not an object (183 AL): left as one that does not parse
                return m.group(1) + json.dumps({**meta, "team": team, "team_me": me}).replace("<", "\\u003c") + m.group(3)
            return _META_RE.sub(with_team, body)
        try:
            got = json.loads(body)
        except ValueError:
            return body
        into = got.get("config") if op == "mount" and isinstance(got, dict) else got
        if not isinstance(into, dict):
            return body                     # valid JSON the list cannot join (183 AL): left as a body that does not parse
        into.update(team=team, team_me=me)
        return json.dumps(got)

    def _relayed(self, req: Req, client: str, op: str, ask, doc: str | None = None) -> Response:
        try:
            env = ask()
        except readthrough.NoEmail as e:
            raise Refuse(403, str(e)) from None
        except readthrough.NotReachable:
            self._knock(req, client, op, "unreachable")
            raise Refuse(502, "This client tiroir is not reachable now.") from None
        self._knock(req, client, op, str(env.get("status")))
        status, body, kept = env["status"], env["body"], readthrough.kept_headers(env.get("headers"))
        if status == 302:                    # the client's own Forward: the browser asks this hub for the new address
            try:
                return Response(302, {"Location": readthrough.Clients.redirect(client, env.get("headers")), "Cache-Control": "no-store"})
            except readthrough.NotReachable:
                self._knock(req, client, op, "unreachable")
                raise Refuse(502, "This client tiroir is not reachable now.") from None
        if op == "mount" and status == 200:   # the front compares these with its own: the client's build is not this hub's
            body = self._own_build(body)
        if op == "doc" and status == 200:     # what an older client tiroir still says of its agents is not shown here (9.9)
            body = self._read_only_doc(body)
        if status == 200 and doc is not None and self.hub.team is not None:
            body = self._with_team(op, body, doc, req.member.name)
        if env.get("type") == "html":
            own = auth.new_nonce()           # the client's nonce is never this origin's: only its own page script runs here
            return _html(status, readthrough.adopt(body, env.get("nonce"), own), own, kept)
        return Response(status, {"Content-Type": "application/json", **kept}, body.encode("utf-8"))

    @staticmethod
    def _read_only_doc(body: str) -> str:
        try:
            got = json.loads(body)
        except ValueError:
            got = None
        if not isinstance(got, dict):
            raise Refuse(502, "This client tiroir is not reachable now.")
        return json.dumps(readthrough.read_only_doc(got))

    def _own_build(self, body: str) -> str:
        try:
            got = json.loads(body)
        except ValueError:
            got = None
        if not isinstance(got, dict):
            raise Refuse(502, "This client tiroir is not reachable now.")
        return json.dumps({**got, "version": self.hub.version, **self.hub.mount_fields()})

    def _knock(self, req: Req, client: str, op: str, status: str) -> None:
        """One diagnostics line per call to a client tiroir: the client, the op, the member's id and the status. Never an address, a
        title or a body: what a client page is called is the client's, and stays off the agency's disk (9.9)."""
        diagnostics.record("hub", "read-through", client=client, op=op, member=req.member.id, status=status)

    def _mount_asset(self, req: Req, name: str, kind: str) -> Response:
        """The loader's script and the page's style, the hub's own files as it read them at start (assets.py). A request
        that names this body (`?v=<tag>`) may be kept for a year: another body is another name. Any other is asked
        again each time."""
        asset = self.hub.assets[name]
        named = req.query.get("v") == asset.tag
        return Response(200, {"Content-Type": kind, "X-Content-Type-Options": "nosniff",
                              "Cache-Control": "public, max-age=31536000, immutable" if named else "no-store"},
                        asset.body)

    def _index_json(self, req: Req) -> Response:
        rendered = req.query.get("rendered", "0")
        _shape(rendered in ("0", "1"), "rendered must be 0 or 1")
        return _ok(**self.hub.index.told(req.member, rendered=rendered == "1"))

    def _jobs(self, req: Req) -> Response:
        return _ok(**self.hub.jobs())

    # ── save and comment ─────────────────────────────────────────────────────
    def _writable(self, address: str):
        """Refuse a write to a page the tiroir may not save (a repo's clone with no save branch, SPEC 14): nothing is
        written, comments included; the line says which `.sheaf.toml` line would change that."""
        if line := self.hub.read_only_line(address):
            raise Refuse(403, line)

    def _text_writable(self, req: Req, address: str, endpoint: str):
        """Refuse a write to the text of a generated page (SPEC 7.2): 403 with the page's sentence, and a diagnostics row
        naming the endpoint and `generated`, never the text. Comments, replies and resolve do not pass here."""
        if line := self.hub.generated_line(address):
            self.hub.record("generated-refused", address, endpoint=endpoint, why="generated", **self._who(req))
            raise Refuse(403, line)

    def _read_on(self, address: str, given) -> str:
        """The branch a save of a repo clone's page was read on, as the page's meta gave it; "" for any other page. A save of
        a clone page names it (SPEC 14): without it the hub cannot tell a save of this branch from one of another."""
        if not self.hub.clone_of(address):
            return ""
        _shape(isinstance(given, str) and given != "", "branch must be the branch the page was read on")
        return given

    def _on_branch(self, address: str, read_on: str, guard):
        """`guard` and, under the page's lock, the refusal of a save read on a branch the clone has left: answered as a
        read-only page is (403), and nothing is merged into the new branch's text."""
        if not read_on:
            return guard
        repo = self.hub.clone_of(address)

        def on_branch(text, new, toggled):
            on = self.hub.repos.head_of(repo)
            if on != read_on:
                raise Refuse(403, f"The clone of {repo} moved from {read_on} to {on or 'no branch'} since this page was read, "
                                  "so the save is not made: reload the page.")
            return guard(text, new, toggled)
        return on_branch

    def _save(self, req: Req) -> Response:
        b = req.body
        e = self._entry_to_write(req, b.get("doc"))
        self._text_writable(req, e.address, "/_/save")    # the page's own reason first, with its row (183 AV)
        self._writable(e.address)
        h, edits = b.get("hash"), b.get("edits")
        _shape(isinstance(h, str) and h != "", "hash must be the hash of the version the edits were made against")
        _shape(isinstance(edits, list), "edits must be a list")
        for x in edits:
            _shape(isinstance(x, dict) and type(x.get("i")) is int and isinstance(x.get("html"), str)
                   and isinstance(x.get("saved", ""), str), "each edit is {i, html} or {i, html, saved}")
        rid = b.get("rid")
        _shape(rid is None or (isinstance(rid, str) and _RID_RE.fullmatch(rid)), "rid is not a request id")
        # The name's lock (9.11) from the guard's judging of the rectoverso's home to the commit: move, write, render,
        # commit, one operation.
        read_on = self._read_on(e.address, b.get("branch"))
        with place.held(self.hub, e.address):
            guard, ticked = self._ticks(req, e, "/_/save")
            guard = self._on_branch(e.address, read_on, guard)
            move, moved = self._mover(e, ticked)
            with self._moved_committed(e, req.member, "edit", moved):
                try:
                    got = e.live.save(h, edits, rid=rid, guard=guard, move=move)
                except (EditError, StaleError) as ex:
                    raise Refuse(409, str(ex)) from None
                except UnicodeEncodeError:
                    raise Refuse(400, "the text holds a character that cannot be written to the .md "
                                      "(half of a pair, such as half an emoji)") from None
                self.hub.index.touch(e.address)
                gone = moved[0] if moved else self._placed(e, ticked)
                if got["changed"] and not got.get("again"):
                    moved.clear()
                    self.hub.committed(e.address, req.member, "edit", gone=gone, root_id=e.root_id)
                    self._page_wrote(req, e, "save")
                # The buttons of the text written, under its lock (10.11): the page numbers its presses by them.
                h, text = e.live.current()
                try:
                    actions = self.hub.actions(e, req.member, text) if h == got["hash"] else None
                except Exception:
                    # The save is written: a reading of its buttons that fails leaves the page's, which the hub
                    # still judges at the press (a hash it no longer holds is refused), never a 500 for it.
                    actions = None
        if "Stop James" in ticked:
            self._stop_james(req, e)
        if actions is not None:
            got = {**got, "actions": actions}
        if got["merged"] and not got.get("again"):
            # Not a failure, but the thing this log exists to measure: how often the page and
            # an agent write at the same time.
            self.hub.record("save-merged", e.address,
                            conflicts=json.dumps(got["conflicts"]) if got["conflicts"] else None,
                            **self._who(req))
        return _ok(**got)

    def _tick(self, req: Req) -> Response:
        """The list's row, or the rectoverso's own page (10.11, `where`), ticks the rectoverso's action (9.10): saved as the
        page saves a tick, so the file, the commit and the open tabs see what a tick in the page makes them see."""
        b = req.body
        e = self._entry_to_write(req, b.get("doc"))
        self._text_writable(req, e.address, "/_/tick")    # the page's own reason first, with its row (183 AV)
        self._writable(e.address)
        n, word, read, release = b.get("action"), b.get("word"), b.get("hash"), b.get("release", False)
        where = b.get("where", "list")
        _shape(where in ("list", "page"), "where must be list or page")
        _shape(type(n) is int and n >= 0, "action must be the number of the rectoverso's action, from 0")
        _shape(isinstance(word, str) and word != "", "word must be the action's word")
        _shape(isinstance(read, str) and read != "", "hash must be the hash of the rectoverso the list read")
        _shape(type(release) is bool, "release must be true or false")
        if release and word not in the_list.TOGGLES:
            # Only a toggle is released (#110): a one-off stays pressed (#108).
            raise Refuse(409, f"{word} is pressed once: its tick cannot be taken back.")
        # The edit is built from the text the list read, never from an older copy the hub holds: the watcher does not
        # refresh a page no tab has open, and a merge of an edit of that copy can tick another box of the word.
        self.hub.catch_up(e)
        h, text = e.live.current()
        if h != read:
            # A write of the same size in the same clock tick leaves the (mtime, size) catch_up compares: the file once.
            with contextlib.suppress(Exception):
                self.hub._refreshed(e)          # as a page view takes in a write: the Write log hears of it
            h, text = e.live.current()
        if h != read:
            raise Refuse(409, f"the rectoverso changed since the {where} read it ({word}): reload the {where}")
        edit = the_list.tick_edit(text, n, word, release)
        if edit is None:
            raise Refuse(409, f"the rectoverso no longer holds that action ({word}): reload the {where}")
        with place.held(self.hub, e.address):
            guard, ticked = self._ticks(req, e, "/_/tick")

            def as_read(text, new, toggled):
                # The row names its action by place and word: on another text than the list read, another
                # action may sit there with the same word. Judged on the file under its lock.
                if md_hash(text) != read:
                    raise EditError(f"the rectoverso changed since the {where} read it ({word}): reload the {where}")
                return guard(text, new, toggled)
            move, moved = self._mover(e, ticked)
            with self._moved_committed(e, req.member, "tick", moved):
                try:
                    got = e.live.save(h, [edit], guard=as_read, move=move)
                except (EditError, StaleError) as ex:
                    raise Refuse(409, str(ex)) from None
                if not got["changed"]:
                    raise Refuse(409, f"the rectoverso no longer holds that action ({word}): reload the {where}")
                self.hub.index.touch(e.address)
                gone = moved[0] if moved else self._placed(e, ticked)
                moved.clear()
                self.hub.committed(e.address, req.member, "untick" if release else "tick", gone=gone, root_id=e.root_id)
                self._page_wrote(req, e, "tick")
        if "Stop James" in ticked:
            self._stop_james(req, e)
        if self.hub.the_list is not None and not release:     # a release answers nothing: the row stays where it is
            self.hub.the_list.ticked(e.address)
        return _ok(hash=got["hash"])

    def _move(self, req: Req) -> Response:
        """The row's Move (9.11): the owner puts a loose page in another folder of their root, named by its path in the
        dialog. The old address forwards to the new one, and everything the hub keeps of the page goes along."""
        b = req.body
        doc = self._owned(req, b.get("doc"))
        try:
            new = moves.move_page(self.hub, req.member, doc, b.get("folder"))
        except moves.Refused as r:
            raise Refuse(r.status, r.message) from None
        self.hub.writes.add(new, req.member.name, "page", "move")
        return _ok(doc=new, url=url_path(new), moved_from=doc)

    def _move_tiroir(self, req: Req) -> Response:
        """The row's "Move to another tiroir…" (ticket 20): the owner of a loose page sends it to the tiroir at `tiroir`, where they
        have an account. A page that is not theirs is answered as a page that is not there, before anything is sent."""
        b = req.body
        try:
            doc = self._owned(req, b.get("doc"))
        except Refuse as r:
            raise Refuse(r.status, r.message, answer={"say": r.message}) from None
        _shape(isinstance(b.get("tiroir"), str) and b["tiroir"] != "", "tiroir is missing")
        try:
            got = outgoing.move_to_tiroir(self.hub, req.member, doc, b["tiroir"])
        except outgoing.Refusal as r:
            raise Refuse(r.status, r.say, answer={"why": r.why, "say": r.say}) from None
        return _ok(**got)

    def _move_folder(self, req: Req) -> Response:
        """Renaming a folder of the member's loose root moves each page in it, each with its own Forward (9.11)."""
        b = req.body
        try:
            done = moves.move_folder(self.hub, req.member, b.get("folder"), b.get("to"))
        except moves.Refused as r:
            raise Refuse(r.status, r.message) from None
        for _, new in done:
            self.hub.writes.add(new, req.member.name, "page", "move")
        return _ok(moved=[{"doc": new, "moved_from": old} for old, new in done])

    def _share(self, req: Req) -> Response:
        """The row's Share button (9.11): the page's owner writes the page's Share line, `Share` or `Share with <names>`,
        and ticks it in the same request, as a tick of the page does. The line is appended in one write against the hash the
        row read, then ticked through `_save`, so the guard, the move to the page's home, the commit and the Write log are
        the page's own. A page with an unticked Share line has it ticked, and no second line is added."""
        b = req.body
        e = self._entry_to_write(req, b.get("doc"))
        self._text_writable(req, e.address, "/_/share")   # the page's own reason first, with its row (183 AV)
        self._writable(e.address)           # before the first write: the Share line is committed before its tick is saved
        read, names = b.get("hash"), b.get("with", [])
        _shape(isinstance(read, str) and read != "", "hash must be the hash of the version the row read")
        _shape(names == [] or visibility.valid_names(names), "with must be a list of short names")
        self.hub.catch_up(e)
        with place.held(self.hub, e.address):
            original, written = [], []

            def change(text):
                # Who may open the page is judged before anything is said about its text, so a hash that does not
                # match never tells a member that cannot open the page that it is there.
                fm = visibility.front_matter(text)
                m = req.member
                if m is None:
                    raise Refuse(403, "Only a signed-in member can share a page.")
                if not self.hub.may_open(m, e.address, fm):
                    raise Refuse(404, "no such document")
                self._text_writable(req, e.address, "/_/share")     # a mark a door write set since the first look (182 G)
                if not self.hub.is_owner(m, e.address, fm):
                    raise Refuse(409, "Only the owner of this rectoverso can share it.")
                if md_hash(text) != read:
                    raise Refuse(409, "the page changed since the row read it: reload the Sheaf")
                if visibility.audience(text) is not None:
                    raise Refuse(409, "the page is already shared")
                if visibility.unticked_share_line(text) is not None:
                    if names:
                        raise Refuse(409, "the page already has a Share line: tick it, or edit its names")
                    written.append(text)        # its own box is ticked below
                    return text
                original.append(text)
                written.append(visibility.with_share_line(text, names))
                return written[-1]
            try:
                after = e.live.rewrite(change)
            except UnicodeEncodeError:
                raise Refuse(400, "the text holds a character that cannot be written to the .md") from None
            if after != read:               # an unticked line of the page's own wrote nothing here
                self.hub.index.touch(e.address)
                self.hub.committed(e.address, req.member, "edit", root_id=e.root_id)
                self._page_wrote(req, e, "share")
        try:
            edit = the_list.share_edit(written[-1])
            _shape(edit is not None, "the Share line was not written")
            return self._save(replace(req, body={"doc": b.get("doc"), "hash": after, "edits": [edit]}))
        except Refuse:
            if original:
                self._unwrite_share_line(req, e, original[0], after)
            raise

    def _own_loose(self, req: Req, doc):
        """(root, rel, address) of a page of the signed-in member's own loose root that is there, for Archive, Keep and
        Delete (8.6): the owner's alone. Anything else, a recipient, a repo page, a page of a registered root, a page that is
        not there, is the answer for a page that is not there."""
        _shape(isinstance(doc, str), "doc is missing")
        m = req.member
        try:
            at = Address.parse(doc)
        except Exception:
            raise Refuse(404, "no such document") from None
        root = self.hub.roots.get(at.root)
        # The owner's own page is theirs to archive, keep or delete whatever its front matter says and even when it cannot be
        # read as text (`visible` says no to that): a page nobody can open is the one a member wants gone.
        if m is None or root is None or self.hub.loose.owner_of(root) != m.id \
                or not (self.hub.holds_loose(m, doc) or self.hub.visible(m, doc)):
            raise Refuse(404, "no such document")
        try:
            mtime = self.hub.file(doc).stat().st_mtime
        except (OSError, NotFound):
            raise Refuse(404, "no such document") from None
        return root, at.rel, mtime

    def _acting(self, req: Req, act):
        # The moves' lock first (the hub's lock order), from the read of the path to the write of the mark: a move comes before
        # the read or after the write, so its `marks_moved` carries this mark and none is left at the old path. Then the page's
        # name lock (`place.held`), and the act's own locks inside it. The path is not read again under the name lock.
        with moves._LOCK:
            root, rel, mtime = self._own_loose(req, req.body.get("doc"))
            try:
                with place.held(self.hub, req.body["doc"]):
                    act(root, rel, mtime)
            except loose.Refused as e:
                raise Refuse(409, str(e)) from None
        self.hub.index.touch(req.body["doc"])
        return _ok()

    def _archive(self, req: Req) -> Response:
        """Archive now (8.6): the owner's own act, on a page of their loose root."""
        return self._acting(req, lambda root, rel, mtime: self.hub.archive.archive_now(root, rel, mtime))

    def _restore(self, req: Req) -> Response:
        return self._acting(req, lambda root, rel, mtime: self.hub.archive.restore(root, rel))

    def _keep(self, req: Req) -> Response:
        on = req.body.get("on", True)
        _shape(isinstance(on, bool), "on must be true or false")
        return self._acting(req, lambda root, rel, mtime: self.hub.archive.keep(root, rel, on, mtime))

    def _delete(self, req: Req) -> Response:
        """Delete (8.6): the owner's page goes into its root's trash for thirty days. Never through the door."""
        doc = req.body.get("doc")
        self._own_loose(req, doc)
        # The moves' lock first (the hub's lock order): a move is between its link and its unlink or it is not, never under the
        # trash's move. Then the name, the page's lock, and the file's lock in `trash`.
        with moves._LOCK, place.held(self.hub, doc):
            try:
                # _own_loose runs under the moves' lock here: a throughput cost that is accepted.
                root, rel, _ = self._own_loose(req, doc)
                with self.hub.page_lock(doc):       # a save in the middle of its write finishes first, one after it finds the page gone
                    self.hub.archive.trash(root, rel)
            except archive_mod.Gone:
                raise Refuse(404, "no such document") from None    # gone since the look of _own_loose (183 BK)
            except (loose.Refused, OSError) as e:
                raise Refuse(409, str(e) if isinstance(e, loose.Refused) else "the page could not be moved to the trash") from None
            # A Forward that led to this address is no one's now (SPEC 9.11 words nothing for a delete): else the old address
            # of the page would lead to whatever comes to this one. Under the moves' lock, as a move adds a Forward. The page is
            # in the trash by now: a Forward that cannot be written is a row in the diagnostics log, never a refusal.
            try:
                self.hub.forwards.drop_leading_to(doc)
            except Exception:
                self.hub.record_exception("delete-forward-failed", doc)
        self.hub.forget_document(doc)
        self.hub.index.touch(doc)
        return _ok()

    def _restore_trash(self, req: Req) -> Response:
        """Put a trashed page of the member's own loose root back where it was; never over a page that is there."""
        m, ident = req.member, req.body.get("id")
        _shape(isinstance(ident, str), "id is missing")
        folder = self.hub.loose.known(m) if m is not None else None
        if folder is None:
            raise Refuse(404, "no such page in the trash")
        root = self.hub.archive.own_root(folder)
        if root is None:
            raise Refuse(404, "no such page in the trash")
        stamp, _, wanted = ident.partition("/")
        doc = str(Address(root.name, wanted))
        try:
            # The moves' lock first, as a delete takes it: a move adds its Forward under it, so the look at `forwards.json` and the
            # put back are one step against a move.
            with moves._LOCK, place.held(self.hub, doc), self.hub.page_lock(doc):
                if self.hub.forwards.follow(doc) is not None:
                    raise Refuse(409, "that address is taken: a page that was there moved away, and its old address leads to it, so "
                                      "this page is not put back there")
                rel = self.hub.archive.restore_trash(root, ident)
        except archive_mod.Taken:
            raise Refuse(409, "a page of that name is there already: it is not overwritten") from None
        except KeyError:
            raise Refuse(404, "no such page in the trash") from None
        except loose.Refused as e:
            raise Refuse(409, str(e)) from None
        self.hub.index.touch(doc)
        return _ok(doc=doc)

    def _unwrite_share_line(self, req: Req, e, text: str, written: str) -> None:
        """The tick of a Share line this request appended was refused (another writer came between the two writes): the
        line goes again, so a page is never left with an unticked Share line the person did not write. Only when the
        file still holds what this request wrote; a file that moved on is the other writer's, and stays."""
        undone = []

        def undo(now):
            if md_hash(now) != written:
                return now
            undone.append(True)
            return text
        with place.held(self.hub, e.address):
            e.live.rewrite(undo)
        if not undone:
            return
        self.hub.index.touch(e.address)
        self.hub.committed(e.address, req.member, "edit", root_id=e.root_id)
        self._page_wrote(req, e, "share")

    def _mover(self, e, ticked):
        """(the `move` of a save, the list it puts the path the file left in): a write that shares the rectoverso or
        withdraws its Share moves the file to the home of its new text before it writes it (9.11), so the text is
        written and rendered in its new folder. `ticked` is filled by the save's guard before the move is asked."""
        moved = []

        def move(text, new):
            if not ({"Share", "Unshare"} & ticked):
                return None
            try:
                # Only in the root the save found its file in (8.11): one that took its name since is never moved in.
                gone = place.ahead(self.hub, e.address, text, new, root_id=e.root_id)
            except place.Refused as ex:
                # The write would leave the rectoverso where it may not stay (9.11): nothing is written.
                raise EditError(f"This rectoverso cannot go to its home: {ex.why}. Nothing was written.") from None
            except NotFound:
                raise EditError(FOLDER_REPLACED) from None
            if gone is None:
                return None
            moved.append(gone)
            try:
                return self.hub.file(e.address, placed=True, bound=e.file_root, root_id=e.root_id)
            except NotFound:
                # The root went once the file moved: the move stays in it, its commit refused (8.11), and nothing is written.
                raise EditError(FOLDER_REPLACED) from None
        return move, moved

    @contextlib.contextmanager
    def _moved_committed(self, e, member, what: str, moved: list):
        """Under the name's lock, around a write whose `move` may move the file (9.11): a move that was made and that
        the write did not commit (a render that failed after it, a write that raised) is committed all the same as
        the request leaves, so git never keeps the file at the path it left. The writer empties `moved` when it
        commits."""
        try:
            yield
        finally:
            if moved:
                self.hub.committed(e.address, member, what, gone=moved.pop(), root_id=e.root_id)

    def _placed(self, e, ticked) -> str | None:
        """After a write that shared the rectoverso or withdrew its Share, under the lock of its name, its file goes to
        its home (9.11) if the write did not take it there (a text that changed meanwhile): the path in the root
        it left, None when it stayed. The caller commits the write and the move as one; the rectoverso's address
        stays. Only in the root the save found its file in (8.11): None when another root took its name since."""
        if not ({"Share", "Unshare"} & ticked):
            return None
        return place.place(self.hub, e.address, commit=False, root_id=e.root_id)

    def _ticks(self, req: Req, e, endpoint: str):
        """The guard of a save (live.save) for the actions the hub judges: a one-off is never unticked and a rectoverso
        answers Belongs to once (9.10), and the two it acts on (9.11); and the set it fills with the words the save
        ticked. Share is its owner's alone: ticked by anyone else, nothing is written; ticked by the owner, the same
        write opens the rectoverso to the project. Who ticked is the signed-in member, never a name the request carries."""
        ticked = set()

        def guard(text, new, toggled):
            m = req.member
            if m is not None:
                # The gate (_owned) read the file before the lock: a write that closed the rectoverso since is
                # seen here, on the text the save would write over.
                fm = visibility.front_matter(text)
                if not self.hub.may_open(m, e.address, fm):
                    raise Refuse(404, "no such document")
            # The look before the locks let the write in; a door write that marked the page generated since did so under
            # this file's lock, so it is seen here (182 G), before any refusal of what the edit holds.
            self._text_writable(req, e.address, endpoint)
            if m is not None:
                # The page cannot edit a front matter (5): paragraphs of `---` would write one, and its
                # `sessions` would serve any transcript (9.12), its `visibility` open the rectoverso.
                if visibility.front_matter(new) != visibility.front_matter(text):
                    raise EditError("A save cannot change the front matter: change it in the file.")
            if (word := the_list.unticks_one_off(text, new)) is not None:
                # A one-off action stays pressed (9.10, #108), for every person and by whatever edit: the deployment's
                # routine has acted on its tick, and an untick would move nothing back.
                raise EditError(f"{word} is pressed once: its tick cannot be taken back.")
            if (slug := the_list.ticks_another_move(text, new)) is not None:
                # A thread moves to one client (9.10, #109): a rectoverso answers Belongs to once, by whatever edit.
                raise EditError(f"This thread belongs to one place: Belongs to {slug} is ticked.")
            words = visibility.newly_ticked(toggled)
            if visibility.audience(new) is True and isinstance(visibility.audience(text), frozenset):
                # A box that stays ticked while its words change (`Share with bob` into `Share`) opens the page to more
                # members as a new tick does, so the owner's save writes the same front matter (9.11).
                words.add("Share")
            if m is not None and visibility.share_lines(text) != visibility.share_lines(new) \
                    and not visibility.withdraws_share(text, new) and not self.hub.is_owner(m, e.address, fm):
                # Who a page is Shared with is its owner's alone, by whatever edit adds, moves, ticks or removes any Share line or
                # its names, whatever audience they compute (a `Share with carol` behind a plain Share leaves it `True`) (9.11);
                # an untick of the one ticked box has its own refusal below.
                raise EditError("Only the owner of this rectoverso can change who it is shared with.")
            if visibility.withdraws_share(text, new):
                # Withdrawing a Share is its owner's alone, as giving it is (#40), by whatever edit unticks the box:
                # anyone else's writes nothing; the owner's closes the rectoverso again in the same write. The hub's own
                # person (no member: the loopback port or the key) reads every file, and withdraws it as an owner.
                fm = visibility.front_matter(text)
                if m is not None and not self.hub.is_owner(m, e.address, fm):
                    raise EditError("Only the owner of this rectoverso can withdraw its Share.")
                new = visibility.unshare(new)
                if visibility.front_matter(new).get("sessions", "") != fm.get("sessions", ""):
                    raise EditError("A save cannot change the front matter: change it in the file.")
                words.add("Unshare")
            elif visibility.narrows(visibility.audience(text), visibility.audience(new)) and self.hub.loose_owner(e.address) is None:
                # Naming fewer members closes the page at once to every member no longer named (9.11): the front matter
                # goes to the names-only form, which `Hub.opened_by_line` reads, and a `visibility: project` no longer lets them in.
                # A loose page needs none: its audience is read from the file each time.
                new = visibility.names_only(new)
                if visibility.front_matter(new).get("sessions", "") != visibility.front_matter(text).get("sessions", ""):
                    raise EditError("A save cannot change the front matter: change it in the file.")
            if "Share" in words:
                if m is not None and not self.hub.is_owner(m, e.address, fm):
                    raise EditError("Only the owner of this rectoverso can share it.")
                # `Share with <names>` on a page of a shared root opens it to those members only: the front matter stays
                # as it is and `Hub.opened_by_line` judges who reads (9.11); only a plain Share writes `visibility: project`.
                names = isinstance(visibility.audience(new), frozenset) and self.hub.loose_owner(e.address) is None
                if visibility.effective(visibility.front_matter(new)) == "owner" and names:
                    by = (m.short or m.name) if m is not None else self.hub.person
                    new = visibility.set_keys(new, {"visibility": "owner", "shared": f"{by} {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"})
                    if visibility.front_matter(new).get("sessions", "") != visibility.front_matter(text).get("sessions", ""):
                        raise EditError("A save cannot change the front matter: change it in the file.")
                elif visibility.effective(visibility.front_matter(new)) == "owner":
                    by = (m.short or m.name) if m is not None else self.hub.person
                    new = visibility.share(new, by, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
                    # Share rewrites the front matter: a line it takes out must not join a skipped one to `sessions`.
                    if visibility.front_matter(new).get("sessions", "") != visibility.front_matter(text).get("sessions", ""):
                        raise EditError("A save cannot change the front matter: change it in the file.")
            elif (visibility.audience(text) is None and visibility.audience(new) is not None
                  and visibility.effective(visibility.front_matter(new)) == "owner" and self.hub.loose_owner(e.address) is None):
                # A line that became a ticked Share or `Share with <names>` by an edit that is not the owner's tick of it (a box
                # renamed and ticked in one save) shares nothing on a page of a shared root: it is left unticked, as a door create
                # leaves it, so the box does not say the page is shared when it is not (9.11). A loose page is Shared by the line
                # itself.
                new = visibility.without_ticked_share(new)
            ticked.clear()
            ticked.update(words)
            return new
        return guard, ticked

    def _stop_james(self, req: Req, e):
        """A member ticked Stop James (9.11): a `stop-james` row, and for a rectoverso of James a file in the
        `[list]`'s `stop_dir` that the box's supervisor of James reads to end his window for the project.
        The hub kills nothing itself."""
        rel = Address.parse(e.address).rel
        project = "/".join(rel.split("/")[:2]) if rel.count("/") >= 2 else ""
        try:
            fm = visibility.front_matter(e.read())
        except (OSError, UnicodeDecodeError):
            fm = {}
        assistant = visibility.text(fm, "assistant")
        m = req.member
        the = self.hub.the_list
        if assistant.casefold() != "james":
            drop = "not a rectoverso of James"
        elif not project:
            drop = "the rectoverso is in no <client>/<project> folder"
        else:
            if the is not None and the.serves(Address.parse(e.address).root):
                self._stop_tells(project, m)
            # The box's supervisor reads the line as `<client>/<project>` (agency-tiroir routines/james, stops).
            # The Stop goes to the James of the member who ticked it, as their Tells do (`member_dirs`).
            drop = work.drop(the.cfg.dirs_for(m).stop_dir if the is not None else None, project,
                             (project + "\n").encode("utf-8"), "no stop_dir in [list]")
        self.hub.record("stop-james", e.address, project=project, assistant=assistant,
                        by=(m.short or m.name) if m is not None else self.hub.person, drop=drop)

    STOPPED = "Stopped before delivery: Stop James closed this project's window before James took this."

    def _stop_tells(self, project: str, member):
        """Every Tell for `project` still waiting in `tell_dir` for James's window, removed before the Stop
        is dropped, and a reply in each one's thread, signed by the member who stopped him, saying it never reached
        him (9.12): a Stop ends the work, and none of it goes on unseen. A `tell-stopped` row for each, without
        its text. The box's supervisor clears what is left of the project's the same way (agency-tiroir #136)."""
        folder = self.hub.the_list.cfg.dirs_for(member).tell_dir
        by = work.member_word(member) if member is not None else self.hub.person
        if folder is None:
            return
        try:
            names = sorted(f.name for f in folder.iterdir()
                           if not f.name.startswith(".") and f.name.startswith(project.replace("/", "--") + "-"))
        except OSError:
            return
        for name in names:
            f = folder / name
            try:
                fd = os.open(f, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd, "rb") as fh:
                    if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
                        continue
                    tell = json.loads(fh.read(64 * 1024).decode("utf-8"))
            except (OSError, ValueError, RecursionError):
                continue
            if not isinstance(tell, dict) or tell.get("project") != project:
                continue
            try:
                f.unlink()
            except FileNotFoundError:
                continue                                # the supervisor took it meanwhile: it reached James
            except OSError:
                continue
            rectoverso, thread = tell.get("sheaf"), tell.get("thread")
            if not (isinstance(rectoverso, str) and isinstance(thread, str)):
                said = "no thread in the drop"
            elif not self._of_project(rectoverso, project):
                said = "the drop names a rectoverso of another root or project"
            else:
                said = self._say_stopped(rectoverso, thread, member)
            self.hub.record("tell-stopped", rectoverso if isinstance(rectoverso, str) else None, project=project,
                            thread=thread if isinstance(thread, str) else None, what=tell.get("kind"), by=by,
                            said=said)

    def _of_project(self, rectoverso: str, project: str) -> bool:
        """Whether `rectoverso` is a rectoverso of `project` on the list's root, where a drop's rectoverso always is (9.12)."""
        at = Address.parse(rectoverso)
        return self.hub.the_list.serves(at.root) and at.rel.startswith(project + "/") and at.rel.count("/") == 2

    def _say_stopped(self, rectoverso: str, thread: str, member) -> str:
        """The STOPPED reply in `thread` of `rectoverso`: "written", or why not."""
        name = (member.name if member is not None else self.hub.person) or "sheaf"
        try:
            e = self.hub.entry(rectoverso)
            if member is not None and not self.hub.may_open(member, e.address,
                                                             visibility.front_matter(e.live.current()[1])):
                return "the member who stopped cannot open the rectoverso"
            with place.held(self.hub, e.address):       # the write and its commit, one step (9.11)
                e.live.comment("reply", {"id": thread, "body": self.STOPPED}, None, by=name, announce=True)
                self.hub.index.touch(e.address)
                self.hub.committed(e.address, member, "comment", root_id=e.root_id)
        except NotFound:
            return "the rectoverso is gone"
        except (rdc.AnchorError, rdc.NoComment, KeyError, ValueError) as ex:
            return f"not written: {ex}"
        except Exception:                               # the Stop is dropped whatever becomes of the reply
            self.hub.record_exception("tell-stopped-reply-failed", rectoverso)
            return "not written: the hub failed on it (sheaf diag)"
        return "written"

    # ── Work on this (9.12) ──────────────────────────────────────────────────
    def _sheaf(self, req: Req, doc):
        """The address `doc` names, its file's front matter and its work.State, once it is a rectoverso the member may
        open (9.11) of the list's root, at `<client>/<project>/<file>.md`. Else the 404 of a document that is not
        there."""
        with self._reading(doc):
            address = self._owned(req, doc)
            if not work.is_rectoverso(self.hub, address):
                raise Refuse(404, "no such document")
            try:
                top, rel = self.hub.where(address)
                with beneath.open_beneath(top, rel) as op:      # judged on what was opened (9.11, rule A)
                    text = op.text()
                    private = place.opened_private(self.hub, op)
                if private is not None and private != getattr(req.member, "id", None):
                    raise Refuse(404, "no such document")
            except (NotFound, OSError, UnicodeDecodeError):
                raise Refuse(404, "no such document") from None
        return address, visibility.front_matter(text), work.state(self.hub, address, text, req.member)

    def _code_rectoverso(self, req: Req, doc):
        """`_sheaf` for a request of a sign-in code (9.13): the code's own rectoverso, open to its member, else the 404
        that names neither, since the laptop cannot tell the two apart and neither can a guesser."""
        try:
            if doc != req.code.doc:
                raise Refuse(404, "another rectoverso")
            return self._sheaf(req, doc)
        except Refuse as r:
            if r.status != 404:
                raise
            raise self._code_refused(req, req.code, "doc", 404, codes.NOT_OPEN) from None

    def _code_moved(self, req: Req):
        """The code's session is no longer the rectoverso's forkable one: the code is spent (9.13)."""
        self.codes.spend(req.code)
        return self._code_refused(req, req.code, "moved", 404, codes.NOT_OPEN)

    def _code(self, req: Req) -> Response:
        """A sign-in code for `tiroir work` on one rectoverso (9.13): for the member who asks in its Work on this, or,
        with the key, for the member the body names (`sheaf code issue`). Made only while the rectoverso has a session to
        fork; shown once, and never again."""
        b = req.body
        if req.kind == "key":
            mid = b.get("member")
            _shape(isinstance(mid, str), "member must be the front's id of a member")
            req.member = self.hub.proxy.members.get(mid) if self.hub.proxy is not None else None
            if req.member is None:
                raise Refuse(404, "no member of [proxy] has that id")
            req.member_id = mid
        address, _, st = self._sheaf(req, b.get("doc"))
        sid = work.code_session(st)
        if sid is None:
            raise Refuse(404, "this rectoverso has no live session on the box to fork")
        try:
            code, c = self.codes.issue(req.member.id, address, sid)
        except codes.TooMany as ex:
            raise Refuse(429, str(ex)) from None
        self.hub.record("code-issued", address, by=work.member_word(req.member), code=c.id, expires=c.expires_text,
                        via="cli" if req.kind == "key" else "popover", **self._who(req))
        return _ok(code=code, expires=c.expires_text, id=c.id)

    def _session(self, req: Req) -> Response:
        """The transcript of one of the rectoverso's box-hosted sessions, the live one without `id`, from the copy of
        James's transcripts (9.12). It names only a file the front matter lists, of the box, in the project's folder
        of `sessions_dir` (#146).
        A sign-in code (9.13) takes no `id`: it serves the session it was made for, once, while that is the
        sheaf's forkable one."""
        code = req.code
        if code is not None:
            _shape("id" not in req.query, "a sign-in code serves the session it was made for: send no id")
            if code.served:
                raise self._code_refused(req, code, "used")
            address, fm, st = self._code_rectoverso(req, req.query.get("doc"))
            if work.code_session(st, code.session) is None:
                raise self._code_moved(req)
            body = work.open_transcript(st.cfg, "/".join(Address.parse(address).rel.split("/")[:2]), code.session, req.member)
            if body is None:
                raise Refuse(404, "this rectoverso has no such session on the box")
            if not self.codes.serve(code):                  # one of two racing GETs: the flag is set before a byte
                raise self._code_refused(req, code, "used")
            self.hub.record("code-used", address, code=code.id, route="session", **self._who(req))
            return self._transcript(req, address, fm, code.session, body, via="code", code=code.id)
        address, fm, st = self._sheaf(req, req.query.get("doc"))
        sid = req.query.get("id")
        _shape(sid is None or work.UUID_RE.fullmatch(sid), "id must be a session id (a lowercase UUID)")
        if sid is None:
            sid = st.forkable           # a live session on a laptop: none, never an older box copy to fork
        if sid not in st.box or not work.serves(st.cfg, req.member):
            raise Refuse(404, "this rectoverso has no such session on the box")
        body = work.open_transcript(st.cfg, "/".join(Address.parse(address).rel.split("/")[:2]), sid, req.member)
        if body is None:
            raise Refuse(404, "this rectoverso has no such session on the box")
        return self._transcript(req, address, fm, sid, body)

    def _transcript(self, req: Req, address: str, fm, sid: str, body: bytes, **via) -> Response:
        self.hub.record("transcript-downloaded", address, transcript=sid, by=work.member_word(req.member),
                        issue=visibility.text(fm, "issue"), **via, **self._who(req))
        return Response(200, {"Content-Type": "application/x-ndjson", "Content-Disposition": _disposition(f"{sid}.jsonl"),
                              "Cache-Control": "no-store", "X-Sheaf-Session": sid}, body)

    def _drop_for_james(self, req: Req, e, body: str, thread: str) -> tuple[str, str | None]:
        """The file a Tell drops in `[list]`'s `tell_dir` for the box's supervisor to hand to James's session
        for the project with `sheaf deliver`, and its `tell-dropped` row. The hub runs no agent of its own for it.
        A Tell carries its id and the words of a local Tell (`message`), so every path says the same (9.12).
        (`written` or why not, the file's name when written)."""
        project = "/".join(Address.parse(e.address).rel.split("/")[:2])
        by = work.member_word(req.member)
        out = {"project": project, "member": by, "sheaf": e.address, "text": body[:work.TEXT_MAX], "kind": boxwait.KIND,
               "thread": thread, "address": e.address, "abs_path": str(e.path),
               "id": str(uuid.uuid4()), "message": self._tell_message(req, e, thread)}
        drop, name = work.drop_named(self.hub.the_list.cfg.dirs_for(req.member).tell_dir, project, json.dumps(out).encode("utf-8"),
                                     "no tell_dir in [list]")
        self.hub.record("tell-dropped", e.address, what=boxwait.KIND, project=project, by=by, drop=drop,
                        tell=out["id"])
        return drop, name

    def _tell_message(self, req: Req, e, thread: str) -> str:
        """What a member's Tell on the thread `thread` says to the session, in the words of a local Tell (11.3)."""
        c = rdc.parse(e.live.current()[1]).by_id(thread)
        return prompts.tell(e.address, str(e.path), req.member.name, c, self.hub.tell.links(e.address))

    def _work_route(self, address: str, text: str, member=None) -> str | None:
        """Where a member's Tell goes on the rectoverso whose text is `text` (9.12): "box" to James's
        window, None nowhere."""
        st = work.state(self.hub, address, text, member)
        can = st.can if st is not None else []
        return "box" if "box-tell" in can else None

    def _james_called(self, caller, address):
        """A door call of James's session (9.12): a write to a rectoverso of James makes the session it names the rectoverso's
        live one, once the copy holds it; one the copy does not hold yet waits, the newest per rectoverso, and is looked
        for again at his next call. The session is never the request's to choose: only an id whose transcript is
        James's in that project's folder is taken."""
        sid = caller.session
        if not caller.own_session:       # the copy holds the own window's transcripts only (9.12)
            return
        if not work.UUID_RE.fullmatch(sid or ""):
            return
        with self._pending_lock:
            waiting = [(at, w) for at, w in self._pending_sessions.items() if at != address]
            if address is not None:
                seq = self._session_seqs.get(address, 0) + 1
                self._session_seqs[address] = seq
                old = self._pending_sessions.get(address)
                since = old[1] if old and old[0] == sid else _clock()     # the same session keeps its clock
                self._pending_sessions[address] = (sid, since, seq)
                self._pending_members[address] = self._token_member(caller)
            members = {at: self._pending_members.get(at) for at, _ in waiting}
        for at, (wanted, since_, seq_) in waiting:
            try:
                self._record_james(at, wanted, caller, since_, seq_, members[at])
            except Exception:                           # one rectoverso's failure never stops the others nor this write
                self._drop_waiting(at, seq_)
                self.hub.record_exception("session-hook-failed", at)
        if address is not None:
            self._record_james(address, sid, caller, since, seq, self._token_member(caller))

    def _token_member(self, caller):
        """The member the door token of `caller` acts for: whose James wrote, so whose copy holds his session."""
        proxy = self.hub.proxy
        return proxy.member_of_row(caller.token) if proxy is not None and caller.token is not None else None

    def _latest(self, address: str, seq: int) -> bool:
        """Whether `seq` is still James's latest write to `address`: an older session never replaces a newer one."""
        with self._pending_lock:
            return self._session_seqs.get(address) == seq

    def _drop_waiting(self, address: str, seq: int) -> bool:
        """The waiting session of `address` forgotten, when it is the one of write `seq`; whether it was."""
        with self._pending_lock:
            if self._pending_sessions.get(address, (None, None, None))[2] != seq:
                return False
            del self._pending_sessions[address]
            self._pending_members.pop(address, None)
            return True

    def _record_james(self, address: str, sid: str, caller, since: float, seq: int, member=None):
        """James's session `sid`, named by his write `seq` to `address`, becomes the rectoverso's live session, the first of
        `sessions`, when it is a rectoverso of James on the list's root, `[list]` names a box, and the copy holds `sid` as a
        session of its project. The hub is the only writer of `sessions` (9.12). Nothing when it is the live one
        already, a member's fork is, or James wrote to the rectoverso again since."""
        the = self.hub.the_list
        try:
            e = self.hub.entry(address)
        except NotFound:
            self._drop_waiting(address, seq)
            return
        text = e.live.current()[1]
        state = work.state(self.hub, address, text)
        if the is None or not the.cfg.box or state is None or not state.james \
                or not self._james_may_take(text, sid):
            self._drop_waiting(address, seq)                  # an item names the box: without one there is nothing to write
            return
        project = "/".join(Address.parse(address).rel.split("/")[:2])
        # The copy of the James that wrote: the member its token acts for, none for a token bound to nobody.
        found = work.james_has(the.cfg, project, sid, member)
        if found is None and _clock() - since < PENDING_S:
            return                                      # it waits for the copy
        if not found:
            if self._drop_waiting(address, seq):
                self.hub.record("session-not-recorded", address, transcript=sid,
                                reason=f"not in the copy {PENDING_S} s after James's write" if found is None
                                else "not a transcript of James's in the project's folder of the copy")
            return
        line = work.item(sid, the.cfg.box, "james", time.strftime(work.ISO, time.gmtime()))
        moved = []

        def change(text):
            # Under the lock again: a fork reported meanwhile keeps the session it made live, and a newer write of
            # James's to the rectoverso keeps the session it names.
            if not self._latest(address, seq) or not self._james_may_take(text, sid):
                return text
            moved.append(sid)
            return work.with_session(text, line, sid)
        with place.held(self.hub, address):             # the write and its commit, one step (9.11)
            try:
                e.live.rewrite(change)
            except work.NotRewritten as ex:
                if self._drop_waiting(address, seq):        # said once: the list stays as it is written
                    self.hub.record("session-not-recorded", address, transcript=sid, reason=str(ex))
                return
            if moved:
                self.hub.index.touch(address)
                self.hub.committed(address, by=caller.display, what="session", root_id=e.root_id)
        self._drop_waiting(address, seq)
        if moved:
            self.hub.record("session-recorded", address, transcript=sid, by="james")

    def _james_may_take(self, text: str, sid: str) -> bool:
        """Whether James's session `sid` becomes the live one of the rectoverso whose text is `text`: the live one is
        James's on the box, another than `sid`, or there is none yet. Never over a member's fork on a laptop."""
        items = work.sessions(visibility.front_matter(text))
        return not items or (items[0]["host"] == self.hub.the_list.cfg.box and items[0]["id"] != sid)

    def _laptops(self, req: Req) -> Response:
        """The member's laptops, by name: never a token (9.7)."""
        rows = laptops.of(self.hub, req.member.id)
        return _json(200, {"laptops": [{"name": r.laptop, "created": r.created, "last_used": r.last_used} for r in rows]})

    def _whoami(self, req: Req) -> Response:
        """The member a token acts for (their id, and their name for the CLI's second line), for a door in front of the hub that has to route the token's calls (9.7). A
        token bound to no member is told it is no route: it has no member to name."""
        member = self.hub.proxy.member_of_row(req.token) if self.hub.proxy is not None else None
        if member is None:
            raise Refuse(404, "no such route")
        return _json(200, {"member": member.id, "name": member.name})

    def _laptop_make(self, req: Req) -> Response:
        """"Connect a laptop": a token for the named laptop and the signed-in member, shown once with the line that
        connects it (9.7)."""
        try:
            token, row = laptops.make(self.hub, req.member.id, req.body.get("name"))
        except laptops.LaptopError as e:
            raise Refuse(e.status, str(e)) from None
        self.hub.record("laptop-connected", "", laptop=row.laptop, **self._who(req))
        return _json(200, {"name": row.laptop, "token": token, "command": f"sheaf connect {self.hub.proxy.origin} {token}"},
                     {"Cache-Control": "no-store"})

    def _laptop_revoke(self, req: Req) -> Response:
        try:
            laptops.revoke(self.hub, req.member.id, req.body.get("name"))
        except laptops.LaptopError as e:
            raise Refuse(e.status, str(e)) from None
        self.hub.record("laptop-revoked", "", laptop=req.body.get("name"), **self._who(req))
        return _ok()

    def _sessions(self, req: Req) -> Response:
        """A member forked one of the rectoverso's sessions on their machine (9.12): the fork becomes the rectoverso's live
        session, the first item of `sessions`, under the signed-in member's name whatever the body says."""
        b = req.body
        code = req.code
        if code is not None:
            # A code reports the fork of the transcript it downloaded: never before, and once (9.13).
            if code.served is False:
                raise self._code_refused(req, code, "order")
            address, fm, _ = self._code_rectoverso(req, b.get("doc"))
        else:
            address, fm, _ = self._sheaf(req, b.get("doc"))
        self._text_writable(req, address, "/_/sessions")    # a rebuild would drop the session line (SPEC 7.2)
        self._writable(address)                             # after the page's own reason, as save, tick and share (183 BE)
        sid, machine = b.get("id"), b.get("machine")
        _shape(isinstance(sid, str) and work.UUID_RE.fullmatch(sid), "id must be a session id (a lowercase UUID)")
        _shape(isinstance(machine, str) and work.MACHINE_RE.fullmatch(machine),
               "machine must be a host name: 1 to 63 letters, digits, dots, dashes or underscores")
        # A fork runs on the member's machine; one named after the box would make its id a box transcript.
        _shape(machine.lower() != (self.hub.the_list.cfg.box or "").lower(), "machine cannot be the box")
        e = self._entry(req, address)
        by = work.member_word(req.member)
        line = work.item(sid, machine, by, time.strftime(work.ISO, time.gmtime()))
        def change(text):
            # The gate (_sheaf) read the file before the lock: a write that closed the rectoverso since is seen here.
            fm = visibility.front_matter(text)
            if not self.hub.may_open(req.member, e.address, fm):
                raise Refuse(404, "no such document")
            # A door write that marked the page generated since the first look did so under this file's lock (183 BE).
            self._text_writable(req, e.address, "/_/sessions")
            if code is not None:
                # Under the lock, where the fork is written: the code's session still the forkable one, an id
                # that is no box session's to push out, and one fork of two racing POSTs.
                if work.code_session(work.state(self.hub, e.address, text, req.member), code.session) is None:
                    raise self._code_moved(req)
                if any(s["id"] == sid for s in work.sessions(fm)):
                    raise self._code_refused(req, code, "listed", 409, LISTED)
                if code.spent:
                    raise self._code_refused(req, code, "used")
                self.codes.spend(code)
            return work.with_session(text, line, sid)
        with place.held(self.hub, e.address):           # the write and its commit, one step (9.11)
            try:
                h = e.live.rewrite(change)
            except work.NotRewritten as ex:
                raise Refuse(409, str(ex)) from None
            self.hub.index.touch(e.address)
            self.hub.committed(e.address, req.member, "fork", root_id=e.root_id)
        via = {"via": "code", "code": code.id} if code is not None else {}
        if code is not None:
            self.hub.record("code-used", address, code=code.id, route="sessions", **self._who(req))
        self.hub.record("session-forked", address, transcript=sid, by=by, machine=machine,
                        issue=visibility.text(fm, "issue"), **via, **self._who(req))
        return _ok(hash=h)

    def _pin(self, req: Req) -> Response:
        """The page keeps the version it holds past a change of the file, while a form holds the reload
        that change needs: the hub keeps it too, beside the newest (7.4)."""
        b = req.body
        e = self._entry(req, b.get("doc"))
        h = b.get("hash")
        _shape(isinstance(h, str) and h != "", "hash must be the hash of the version the page holds")
        if not e.live.pin(h, req.member_id):           # the cap is per member (7.4); the hub's person's id is ""
            raise Refuse(409, UNKNOWN)
        return _ok()

    def _comment(self, req: Req) -> Response:
        b = req.body
        if readthrough.is_clients(b.get("doc")):
            return self._team_write(req) if self._side(b) == "team" else self._relay_comment(req)
        e = self._entry_to_write(req, b.get("doc"))
        self._writable(e.address)
        op = b.get("op")
        _shape(op in OPS, f"op must be one of {', '.join(OPS)}")
        _shape(not (op in ("add", "reply") and "ask" in b), ASK_RETIRED)
        h = self._page_hash(req)
        for k in ("id", "body", "quote", "status"):
            _shape(k not in b or isinstance(b[k], str), f"{k} must be text")
        rid = b.get("rid")
        _shape(rid is None or (isinstance(rid, str) and _RID_RE.fullmatch(rid)), "rid is not a request id")
        if op in ("add", "reply", "edit"):
            _shape(isinstance(b.get("body"), str) and b["body"].strip(), "the comment is empty")
        if op == "add":
            for k in ("block", "start", "end"):
                _shape(type(b.get(k)) is int, f"{k} must be a whole number")
        member = req.member
        starts = op in ("add", "reply")
        # Tell runs the hub account's own session, which a member is not (9.9); on a rectoverso whose live
        # session is James's on the box it goes to his window instead, by a file the hub drops (9.12).
        route = None
        if member is not None and starts and b.get("tell"):
            route = self._work_route(e.address, e.live.current()[1], req.member)     # James's window comes first (9.8)
        # An agent that is the reader's target (SPEC 9.8) is not reached: the Tell waits for it, after the write,
        # on every rectoverso where the box does not take it.
        to_agent = (starts and bool(b.get("tell")) and route is None
                    and targets.live(self.hub, targets.stored(self.hub, e.address, member), member) is not None)
        if member is not None and b.get("tell") and not to_agent:
            _shape(route is not None, proxy.PROXY_LINE)     # a member's Tell goes to the box or an agent, or is refused
        tell = starts and bool(b.get("tell")) and route is None and not to_agent
        # A Tell that cannot go out still writes the comment, and then starts no wait. A reply
        # sent with Tell to a thread that is being told is such a Tell: the wait the first one
        # began stays as it is (SPEC 11.3).
        tell_line = self.hub.tell.refusal(e.address) if tell else None
        if tell and tell_line is None and op == "reply":
            tell_line = self.hub.tell.telling_line(e.address, b.get("id", ""))
        can_tell = tell and tell_line is None
        signed = {"by": member.name, "author": member.name} if member else {}
        if member is not None:
            def still_visible(text, opened=None):
                # The gate (_entry) read the file before the lock: a write that closed the rectoverso since is seen here,
                # and a live session that moved since keeps Tell from the window it no longer is.
                fm = visibility.front_matter(text)
                seen = place.UNJUDGED if opened is None else place.opened_private(self.hub, opened)
                if not self.hub.may_open(member, e.address, fm, seen):
                    raise Refuse(404, "no such document")
                if (route or to_agent) and self._work_route(e.address, text, req.member) != route:
                    raise Refuse(400, proxy.PROXY_LINE)
            signed["guard"] = still_visible
        with place.held(self.hub, e.address):           # the write and its commit, one step (9.11)
            try:
                snap = e.live.comment(op, b, h, await_action=can_tell, rid=rid, **signed)
            except NotAuthor as ex:
                raise Refuse(403, str(ex)) from None
            except StaleError as ex:
                raise Refuse(409, str(ex), answer={"code": ex.code} if ex.code else None) from None
            except KeyError as ex:
                raise Refuse(400, f"missing field {ex}") from None
            except rdc.NoComment as ex:
                # Deleted while the page's request was out, often before the page has heard of it.
                raise Refuse(410, str(ex)) from None
            except (rdc.AnchorError, ValueError, TypeError) as ex:
                raise Refuse(400, str(ex)) from None
            self.hub.index.touch(e.address)
            if not snap.get("again") and snap.pop("wrote", True):   # a write that changed nothing commits nothing
                self.hub.committed(e.address, member, "comment", root_id=e.root_id)
        if not snap.get("again") and (op == "delete" or (op == "status" and b.get("status") == "resolved")
                                      or (op == "reply" and b.get("resolve"))):
            self.hub.waiting_tells.end(e.address, b["id"], "cancelled", reason="closed")   # nothing left to answer (9.8)
            self.hub.session_tells.end(e.address, b["id"], "cancelled", reason="closed")
        if snap.get("again"):
            # Taken before under this request id: what the first request started (a Tell's wait)
            # is running or done, and the page hears of it by its events.
            tell = False
            route = to_agent = None
        if to_agent:
            try:
                self.hub.tell.queue_agent(e.address, snap["id"], member)
            except JobRefused as r:
                snap["tellError"] = r.message
        elif route == "box":
            drop, name = self._drop_for_james(req, e, b["body"], snap["id"])
            if drop != "written":
                snap["tellError"] = "The hub could not send this to James's window; the comment is written."
            else:
                # Open on the rectoverso's pages until a reply lands in the thread, or past the Tell wait (#115).
                self.hub.box_waits.add(e.address, snap["id"], e.live.current()[1], name,
                                       self.hub.the_list.cfg.dirs_for(req.member).tell_dir, req.member.id)
        # The job looks the document up again when it starts: it names its thread in the text the
        # comment was just written in, so a forget in between, and another folder that takes the name,
        # cannot hand it that folder's thread of the same id (SPEC 7.3). A forget that leaves no folder
        # under the name, or a file gone meanwhile, is refused as well: the comment is still answered.
        if tell:
            try:
                if not can_tell:
                    raise JobRefused(409, tell_line or NO_AGENT)
                self.hub.tell.start_tell(e.address, snap["id"], waiting=True, held=snap["hash"])
            except JobRefused as r:
                if can_tell and not r.leaves_wait:   # a wait this request began, and no other
                    e.live.stop_waiting(snap["id"])
                snap["tellError"] = r.message
        self.hub.waiting_tells.sweep()
        snap["telling"] = e.live.telling()
        if member:      # only their own Tells that wait for an agent (9.8, 9.9)
            snap = {**proxy.for_member(snap), "telling": self._member_telling(e.address, member, comments=snap.get("comments"))}
        return _ok(**snap)

    @staticmethod
    def _page_hash(req: Req):
        """The version of the document the page holds (`hash`), or None when the request sends none."""
        h = req.body.get("hash")
        _shape(h is None or isinstance(h, str), "hash must be text")
        return h

    def _thread_job(self, req: Req):
        """The document and thread a job names. Nothing else in the body is read: a request
        never names a session, a socket or a command."""
        e = self._entry(req, req.body.get("doc"))
        return e, self._comment_id(req)

    @staticmethod
    def _comment_id(req: Req):
        cid = req.body.get("id")
        _shape(isinstance(cid, str) and _ID_RE.fullmatch(cid), "id is not a comment id")
        return cid

    # ── Team comments (9.11): the agency's own verso on a client page, kept on this hub alone ──
    def _team_page(self, req: Req, doc) -> str:
        """The client page `doc` names, when this hub keeps Team comments and the member may open it: otherwise the answer
        of a page that is not there, so what a member may not open is not told apart from what is missing."""
        hub, member = self.hub, req.member
        if (hub.team is None or member is None or not isinstance(doc, str) or not doc.startswith("Clients/")
                or not hub.team_gate(member, doc)):
            raise Refuse(404, "no such document")
        return doc

    def _team(self, req: Req) -> Response:
        doc = self._team_page(req, req.query.get("doc"))
        return _ok(team=self.hub.team.list(doc))

    def _team_write(self, req: Req) -> Response:
        b = req.body
        doc = self._team_page(req, b.get("doc"))
        op = b.get("op")
        _shape(op in OPS, f"op must be one of {', '.join(OPS)}")
        for k in ("id", "body", "quote", "status", "hash", "side"):
            _shape(k not in b or isinstance(b[k], str), f"{k} must be text")
        rid = b.get("rid")
        _shape(rid is None or (isinstance(rid, str) and _RID_RE.fullmatch(rid)), "rid is not a request id")
        _shape(not b.get("tell"), "Tell is not for a Team comment: it stays on this tiroir and no agent is asked")
        _shape(b.get("side", "team") == "team", "this route writes Team comments only")
        store, name, cid = self.hub.team, req.member.name, b.get("id", "")
        if op != "add":
            _shape(team_mod.ID_RE.fullmatch(cid), "id is not a Team comment id")
        if op in ("add", "reply", "edit"):
            _shape(b.get("body", "").strip(), "the comment is empty")
        if op == "add":
            _shape(b.get("quote", "").strip(), "a Team comment is on a quote: select the text first")
        at = time.strftime(STAMP_FORMAT)
        try:
            if op == "add":
                store.add(doc, name, b["quote"], b["body"], b.get("hash", ""), at, rid)
            elif op == "reply":
                store.reply(doc, cid, name, b["body"], at)
            elif op == "status":
                store.status(doc, cid, b.get("status"))
            elif op == "edit":
                store.edit(doc, cid, name, b["body"])
            else:
                store.delete(doc, cid, name)
        except NotAuthor as ex:
            raise Refuse(403, str(ex)) from None
        except team_mod.NoComment:
            raise Refuse(410, "that comment is gone") from None
        except ValueError as ex:
            raise Refuse(400, str(ex)) from None
        return _ok(team=store.list(doc))

    def _tell(self, req: Req) -> Response:
        e, cid = self._thread_job(req)
        try:
            if req.member is not None:      # the hub account's session is off for them: only an agent of theirs (9.9)
                if (targets.live(self.hub, targets.stored(self.hub, e.address, req.member), req.member) is None
                        or self._work_route(e.address, e.live.current()[1], req.member) is not None):    # the box comes first
                    raise Refuse(400, proxy.PROXY_LINE)
                self.hub.tell.start_member_tell(e.address, cid, req.member, held=self._page_hash(req))
                return _ok()
            self.hub.tell.start_tell(e.address, cid, held=self._page_hash(req))
        except JobRefused as r:
            raise Refuse(r.status, r.message) from None
        return _ok()

    def _target(self, req: Req) -> Response:
        """Change the target of a Tell (SPEC 9.8): `session`, `agent:<token name>` or `none`. A member picks
        only one of their own agents; the hub account's session is not theirs to take. The answer is the target
        and what the reader may pick, as /_/doc gives them."""
        with self._reading(req.body.get("doc")):        # the rectoverso is judged and the target stored in one step (9.11)
            e = self._entry(req, req.body.get("doc"))
            try:
                targets.pick(self.hub, e.address, req.member, req.body.get("target"))
            except targets.Refused as r:
                raise Refuse(400, str(r)) from None
        if req.member is not None:
            can = self.hub.member_work(e, req.member)[1]
            mt = self.hub.member_target(e.address, req.member, can)
            return _ok(target=mt.agent, targets=mt.picks)
        return _ok(target=self.hub.tell.view(e.address).agent(), targets=targets.choices(self.hub, e.address))

    def _jump(self, req: Req) -> Response:
        """Bring the session's terminal forward by the command of config.toml (SPEC 4.3, 8.5). The body
        names a document; which command runs, and for which session, is not the request's to say."""
        e = self._entry(req, req.body.get("doc"))
        try:
            self.hub.tell.jump(e.address)
        except JobRefused as r:
            raise Refuse(r.status, r.message) from None
        return _ok()

    def _cancel(self, req: Req) -> Response:
        """A cancel stops what runs and clears the page, and asks nothing of the file: a document
        that is gone, or whose root was forgotten and taken by no folder, has nothing left to stop, and the
        answer is ok. A page of another root than the one that holds the name now is refused."""
        doc = self._owned(req, req.body.get("doc"))
        cid = self._comment_id(req)
        # A page sends the id of the root it was served from; a folder that took the name after a forget has
        # another, and its thread of the same id is not this page's to stop. A root that holds no name now, and
        # a caller with no page (the CLI, the door), are never refused (SPEC 7.3).
        sent_root = req.body.get("root")
        # The compare and the cancel are one step (182 H): a forget takes the moves' lock (`Hub.forget_root`), so the
        # root that holds the name is the one compared until the cancel is over, and a folder that takes the name after a
        # forget never has its Tell of the same id ended by a page of the forgotten root. Not held for the wait on the
        # document's lock (`finish`), which a render holds for up to 120 s: a move or an agent's Tell would wait with it.
        finish = None
        with moves.exclusive():
            # Compared with the root the registry holds, not `_root_id`, whose None also stands for a root the member
            # reaches but does not own (a clone the tiroir serves, a loose page Shared with them).
            holder = self.hub.roots.get(Address.parse(doc).root)
            if isinstance(sent_root, str) and (holder is None or holder.id != sent_root):
                held_root = self._root_id(req, doc)
                if held_root is not None:
                    raise Refuse(409, "another folder now holds this document's name: reload the page", answer={"root": held_root})
                # The page's root was forgotten, and its forget ended its Tells and stopped its jobs. A folder that took
                # the name, or takes it now (a root is added under no lock of the cancel's), is not this page's to stop,
                # and a member who does not own it is not told it exists (9.9): ok, and nothing to do. A job registered on
                # a popped entry after the forget's `cancel_under` never runs its work (`_is_current`), and the runner,
                # keyed by address, could stop the other folder's job of the same id here.
                return _ok()
            # A Tell that waits for an agent ends here, the reader's own and no other's (9.8). A member has no
            # session to stop: theirs is only a waiting Tell.
            self.hub.waiting_tells.end(doc, cid, "cancelled", member=req.member, only_member=True)
            self.hub.session_tells.end(doc, cid, "cancelled", member=req.member, only_member=True)
            if req.member is None:
                finish = self.hub.tell.cancel(doc, cid)
        if finish is not None:
            finish()
        return _ok()

    def _retarget(self, req: Req) -> Response:
        """A member's Tell that waits for a laptop session goes to one of their own agents instead (SPEC 9.8): the waiting
        Tell is cancelled, the target becomes that agent and the Tell is queued for it. The reader's own, and no one else's."""
        if req.member is None:
            raise Refuse(400, "Only a member's Tell waits for a laptop session.")
        cid, target = self._comment_id(req), req.body.get("target")
        with self._reading(req.body.get("doc")):        # judged and stored in one step, as `_target` does (9.11)
            e = self._entry(req, req.body.get("doc"))
            if not any(t["id"] == cid for t in self.hub.session_tells.waits(e.address, req.member)):
                raise Refuse(409, "No Tell of yours waits for a session on this comment.")
            if self._work_route(e.address, e.live.current()[1], req.member) is not None:    # the box comes first
                raise Refuse(400, proxy.PROXY_LINE)
            was = targets.stored(self.hub, e.address, req.member)
            try:
                kind, _ = targets.parse(target)
                if kind != "agent":
                    raise targets.Refused("Pick one of your own agents.")
                targets.pick(self.hub, e.address, req.member, target)
            except targets.Refused as r:
                raise Refuse(400, str(r)) from None
        try:                                    # queued first: a refused one leaves the Tell where it waits, and the target as it was
            self.hub.tell.start_member_tell(e.address, cid, req.member, held=self._page_hash(req))
        except JobRefused as r:
            targets.restore(self.hub, e.address, req.member, was)
            raise Refuse(r.status, r.message) from None
        self.hub.session_tells.end(e.address, cid, "cancelled", member=req.member, only_member=True, reason="retargeted")
        return _ok()

    def _seen(self, req: Req) -> Response:
        b = req.body
        e = self._entry(req, b.get("doc"))
        cid, n = b.get("id"), b.get("count")
        _shape(isinstance(cid, str) and _ID_RE.fullmatch(cid), "id is not a comment id")
        _shape(type(n) is int and 0 <= n <= 100000, "count must be a number of messages")
        if req.member is not None:
            self.hub.member_seen.mark(req.member.id, e.address, cid, n)
        else:
            self.hub.seen.mark(e.address, cid, n)
        self.hub.index.touch(e.address)
        return _ok()

    # ── export, diagnostics ──────────────────────────────────────────────────
    def _export(self, req: Req) -> Response:
        kind = req.body.get("kind")
        _shape(kind in ("html", "pdf"), "kind must be html or pdf")
        with self._reading(req.body.get("doc")):
            e = self._entry(req, req.body.get("doc"))
            try:
                html = self.hub.share_copy(e)
            except RenderError as ex:
                raise Refuse(409, str(ex)) from None
        stem = Path(e.address).stem
        if kind == "html":
            return Response(200, {"Content-Type": "text/html; charset=utf-8",
                                  "Content-Disposition": _disposition(stem + ".html")},
                            html.encode("utf-8"))
        # Serialised: two clicks would otherwise have two Chromes at once.
        with self.hub.pdf_lock, tempfile.TemporaryDirectory(prefix="sheaf-pdf-") as d:
            out = Path(d) / "share.pdf"
            try:
                pdf.write_pdf(html, out)
                data = out.read_bytes()
            except pdf.PdfError as ex:
                # One line, because it lands in a toast and the useful half of "Chrome is not
                # installed / apt install ..." is the half after the newline.
                raise Refuse(503, " ".join(str(ex).split())) from None
        return Response(200, {"Content-Type": "application/pdf",
                              "Content-Disposition": _disposition(stem + ".pdf")}, data)

    def _transcribe_ask(self, req: Req) -> Response:
        asked = self.hub.transcribe
        return _ok(available=asked is not None and asked.available())

    def _transcribe(self, req: Req) -> Response:
        """Dictation: the recording a page made, sent to the provider of `[transcribe]`, the text back. The sound is not kept and the
        text is not written down; a refusal says only what the page needs to tell a person."""
        name = req.headers.get("x-filename", "")
        ctype = req.headers.get("content-type", "").lower()
        if not DICTATION_FILE.fullmatch(name) or not ctype.startswith("audio/"):
            raise Refuse(415, "send audio as dictee.webm, dictee.mp4 or dictee.ogg")
        _shape(req.raw, "the recording is empty")
        if len(req.raw) > MAX_AUDIO:
            raise Refuse(413, "the recording is too large")
        asked, began, result, status = self.hub.transcribe, time.monotonic(), "ok", {}
        try:
            if asked is None:
                raise transcribe.Unavailable("dictation is not available")
            text = asked.transcribe(req.raw, name[7:])
            status = {"status": 200}
        except (transcribe.Busy, transcribe.Unavailable, transcribe.Failed) as e:
            result = type(e).__name__.lower()
            status = {} if e.status is None else {"status": e.status}
            raise Refuse({transcribe.Busy: 429, transcribe.Unavailable: 503, transcribe.Failed: 502}[type(e)], str(e)) from None
        finally:
            self.hub.record("transcribe", None, bytes=len(req.raw), ms=round((time.monotonic() - began) * 1000),
                            result=result, by=self.hub.person, **status)
        return _ok(text=text)

    def _diag(self, req: Req) -> Response:
        b = req.body
        kind = b.get("kind")
        _shape(isinstance(kind, str) and kind.strip(), "kind is missing")
        doc = b.get("doc") if isinstance(b.get("doc"), str) else None
        if readthrough.is_clients(doc):          # what a client page is called, and what went wrong on it, stays off this disk (9.9)
            diagnostics.record("page", kind.strip()[:40], None, **self._who(req))
            return Response(204)
        detail = {str(k)[:40]: str(v) for k, v in list(b.items())[:40] if k not in _RESERVED}
        diagnostics.record("page", kind.strip()[:40], doc, **detail, **self._who(req))
        return Response(204)

    # ── the MCP door (the key and a name, or a token) ────────────────────────
    @staticmethod
    def _declared(req: Req) -> dict:
        """What a door caller says of itself in its headers, for the Write log: kept as declared, never verified (SPEC 12)."""
        h = req.headers
        return {"session": h.get("x-sheaf-session", ""), "host": h.get("x-sheaf-host", ""),
                "link": h.get("x-sheaf-link", ""), "chat": h.get("x-sheaf-chat", "")}

    def _mcp(self, req: Req) -> Response:
        if req.token:
            the = self.hub.the_list
            names = the.cfg.james_tokens if the is not None else ()
            own = the.cfg.own_token if the is not None else ""
            james = req.token.name in names
            caller = Caller(req.token.signed(self.hub.person, self.hub.proxy), req.token,
                            session=req.headers.get("x-james-session", "") if james else None,
                            own_session=bool(own) and req.token.name == own, declared=self._declared(req), gone=req.gone)
        else:
            caller = Caller(req.display, declared=self._declared(req), gone=req.gone)
        status, answer = self.door.handle(req.raw, caller)
        return _json(status, answer) if answer is not None else Response(status)

    # ── the CLI's routes (the key) ───────────────────────────────────────────
    def _render(self, req: Req) -> Response:
        b = req.body
        path, settings, target = b.get("path"), b.get("settings", {}), b.get("target")
        _shape(isinstance(path, str) and Path(path).is_absolute(), "path must be absolute")
        md = Path(path)
        _shape(path.endswith(".md") and md.is_file(), "path must be an existing .md file")
        _shape(isinstance(settings, dict), "settings must be an object")
        for k, want in SETTING_TYPES.items():
            v = settings.get(k)
            _shape(v is None or (type(v) is want), f"{k} must be {want.__name__}")
        _shape(settings.get("toc") in (None, "always", "auto", "never"),
               "toc must be always, auto or never")
        _shape(settings.get("max_image_width") is None or settings["max_image_width"] > 0,
               "max_image_width must be positive")
        _shape(target is None or isinstance(target, dict), "target must be an object or null")
        if target is not None and target.get("agent") != "none":
            try:
                target = Target.from_dict(target).as_dict()
            except ValueError as ex:
                raise Refuse(400, str(ex)) from None
        elif target is not None:
            target = {"agent": "none"}
        try:
            return _ok(**self.hub.render(md, settings, target), peer_check=self._checks_peer())
        except (RenderError, ConfigError) as ex:
            raise Refuse(422, str(ex)) from None

    def _forget(self, req: Req) -> Response:
        name = req.body.get("name")
        _shape(isinstance(name, str) and name != "", "name must be the name of a root")
        root = self.hub.forget_root(name)
        if root is None:
            raise Refuse(404, "no such root")
        return _ok(name=root.name, path=str(root.path))

    def _rotate(self, req: Req) -> Response:
        self.hub.rotate()
        return _ok()                       # never the key: the caller reads the file it owns

    def _restarting(self, req: Req) -> Response:
        return _ok(token=self.hub.expect_restart())

    def _forget_restart(self, req: Req) -> Response:
        token = req.query.get("token")
        if token is not None:
            # ASCII digits only: `str.isdigit` takes '²' (which `int` refuses) and '٣' (which it reads as 3)
            _shape(re.fullmatch(r"[0-9]+", token) is not None, "token must be the number the announcement returned")
        self.hub.forget_restart(None if token is None else int(token))
        return _ok()

    def _stop(self, req: Req) -> Response:
        reason, force = req.body.get("reason"), req.body.get("force", False)
        _shape(reason in ("stop", "upgrade"), "reason must be stop or upgrade")
        _shape(isinstance(force, bool), "force must be true or false")
        if not self.hub.request_stop(reason, force):
            raise Refuse(409, "a Tell is running, so the hub was not stopped for the upgrade")
        return _ok(reason=self.hub.stop_requested)         # the one in force: a stop under way is not turned into an upgrade (8.4)
