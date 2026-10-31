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
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote

from .. import comments as rdc
from .. import diagnostics, pdf
from ..agents import prompts
from ..agents.base import Target
from ..config import ConfigError
from ..edit import EditError
from ..mcp import Caller, Door
from ..render import RenderError
from ..source import StaleError, md_hash
from . import auth, codes, events, peer, place, proxy, relay, the_list, visibility, work
from .asktell import NO_AGENT, JobRefused
from .index import Status
from .live import UNKNOWN, NotAuthor
from .roots import Address, NotFound, address_of_url, root_of_url
from .state import TokenRow

MAX_BODY = 8 * 1024 * 1024
OPS = ("add", "reply", "status", "edit", "delete")
SIGN_IN = ("This browser is not signed in to your sheaf hub. On the machine that runs the hub, "
           "run <code>sheaf open &lt;this url&gt;</code>. If the hub runs on another machine, "
           "run <code>sheaf signin-url</code> there and open what it prints in this browser.")
LINK_USED = (f"A sign-in link from <code>sheaf open</code> works once, for {auth.SIGNIN_TTL} seconds: "
             "this one was used already, has run out or is not from this hub. On the machine that runs the hub, run "
             "<code>sheaf open &lt;the document&gt;</code> again. If you did not use the link twice "
             "yourself, someone else on that machine may have used it first: run "
             "<code>sheaf rotate</code> to sign every browser out, then <code>sheaf open</code> again.")
LINK_LIMIT = ("This hub cannot check which user of this machine follows a link (this system gives it no way "
              "to see who owns a connection), so on a machine that other people use, someone who read the "
              "link while it lasted could have used it first.")
LINK_OTHER_USER = ("The hub did not sign this browser in, and the link is spent: the connection comes from "
                   "another user of this machine than the one that runs the hub. A sign-in link works only "
                   "in a browser of the hub's own user. On the machine that runs the hub, run "
                   "<code>sheaf open &lt;the document&gt;</code> again, as that user.")
LINK_UNKNOWN = ("The hub could not tell which user of this machine followed this link, so it signed no one in, "
                "and the link is spent. On the machine that runs the hub, run "
                "<code>sheaf open &lt;the document&gt;</code> again. If it keeps happening, run "
                "<code>sheaf diag</code> and look at the <code>open-401</code> rows, or run "
                "<code>sheaf signin-url</code> and open what it prints in this browser.")
PROXY_SIGN_IN = ("This browser is not signed in to this site, or its sign-in has ended. Sign in to this "
                 "site again, then reload this page.")
WRONG_KEY = ("This link does not hold this hub's key. On the machine that runs the hub, run "
             "<code>sheaf signin-url</code> again and open what it prints in this browser.")
SETTING_TYPES = {"title": str, "toc": str, "max_image_width": int, "by": str, "for": str,
                 "theme": str, "credit": bool}
_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")
_RID_RE = re.compile(r"[A-Za-z0-9_-]{16,64}")     # a page's request id (/_/comment, /_/save)
_RESERVED = {"kind", "source", "doc", "at", "pid", "session", "member"}


PENDING_S = 300  # how long a session James named waits for the copy before it is said (9.12)
_clock = time.monotonic


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
    relay: dict | None = None        # the relays.json row of the relay token that let the request in (9.14)


@dataclass(frozen=True)
class Who:
    """Who may call a route (8.5, 9.3, 9.7): the credentials it takes, and what the caller is told
    when it holds none of them. A route that `token`s also takes an MCP token, nowhere else is one
    looked at; one that reads its own `raw_body` is sent the bytes as they came, and its key
    caller must name itself (the door reads its own JSON-RPC and signs its replies)."""
    kinds: frozenset[str]
    refusal: str
    raw_body: bool = False

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
DOOR = Who(frozenset({"key", "token"}), "this needs the hub key or an MCP token", raw_body=True)
# A member's alone, on the proxy socket (9.12): the loopback port answers 404, as for a route it has not.
MEMBER = Who(frozenset({"member"}), "no such route")
# A sign-in code is asked for by a member on the proxy socket, or with the key on the loopback port (9.13).
MINT = Who(frozenset({"member", "key"}), "this needs the hub key")
# What a sign-in code opens (9.13): the transcript and the fork, nothing else.
CODE_ROUTES = {("GET", "/_/session"): "session", ("POST", "/_/sessions"): "sessions"}
LISTED = "That session is already listed on this sheaf"
# What a relay token opens (9.14): its fork's stream of Tells and their acks, nothing else.
RELAY_ROUTES = {("GET", "/_/relay"): "relay", ("POST", "/_/relay"): "relay-ack"}
RELAY_OUTCOMES = ("delivered", "failed")
RELAY_MOVED = "The session on the member's machine is no longer this sheaf's live session; the comment is written."


def _json(status: int, obj: dict, headers: dict | None = None) -> Response:
    return Response(status, {"Content-Type": "application/json", **(headers or {})},
                    json.dumps(obj).encode("utf-8"))


def _ok(**fields) -> Response:
    return _json(200, {"ok": True, **fields})


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
    and in them nothing of the hub account's agent session. So no Ask or Tell of it, no thread told
    to it, no question it put to its person, and no `signed-out`, since `sheaf rotate` does not
    touch a member."""
    if name not in proxy.DOCUMENT_EVENTS:
        return None
    return proxy.for_member(data) if isinstance(data, dict) else data


class Handler:
    def __init__(self, hub, peer_check=peer.check):
        self.hub = hub
        self.peer_check = peer_check
        self.door = Door(hub)
        self.door.called = self._james_called
        self._pending_sessions: dict = {}   # address -> (James's session it waits for, since, its write's seq) (9.12)
        self._session_seqs: dict = {}       # address -> the seq of James's latest write to it: the newest one wins
        self._pending_lock = threading.Lock()
        self.codes = codes.Codes()          # the sign-in codes, in memory only: a restart drops them (9.13)
        self.relays = hub.relays            # the relay tokens on disk, and the Tells and streams of the forks (9.14)
        # path -> method -> (route name, who may call it, function)
        self.routes: dict = {}
        for method, path, name, who, fn in (
            ("GET", "/_/health", "health", OPEN, self._health),
            ("GET", "/_/open", "open", OPEN, self._open),
            ("GET", "/_/live", "live", COOKIE, self._live),
            ("GET", "/_/doc", "doc", EITHER, self._doc),
            ("GET", "/_/mount", "mount", EITHER, self._mount),
            ("GET", "/_/mount.js", "mount-js", OPEN, lambda req: self._mount_asset(req, "mount.js", "text/javascript; charset=utf-8")),
            ("GET", "/_/mount.css", "mount-css", OPEN, lambda req: self._mount_asset(req, "mount.css", "text/css; charset=utf-8")),
            ("GET", "/_/index.json", "index", EITHER, self._index_json),
            ("GET", "/_/jobs", "jobs", KEY, self._jobs),
            ("POST", "/_/save", "save", COOKIE, self._save),
            ("POST", "/_/pin", "pin", COOKIE, self._pin),
            ("POST", "/_/tick", "tick", COOKIE, self._tick),
            ("GET", "/_/session", "session", MEMBER, self._session),
            ("POST", "/_/sessions", "sessions", MEMBER, self._sessions),
            ("POST", "/_/code", "code", MINT, self._code),
            ("POST", "/_/comment", "comment", COOKIE, self._comment),
            ("POST", "/_/ask", "ask", COOKIE, self._ask),
            ("POST", "/_/tell", "tell", COOKIE, self._tell),
            ("POST", "/_/cancel", "cancel", COOKIE, self._cancel),
            ("POST", "/_/jump", "jump", COOKIE, self._jump),
            ("POST", "/_/seen", "seen", COOKIE, self._seen),
            ("POST", "/_/export", "export", COOKIE, self._export),
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
    def handle(self, method: str, target: str, headers: dict, body=b"", conn=None, via="port") -> Response:
        """`body` is the bytes, or a function that reads them off the wire: it is called only for
        a POST that has passed the Host, credential and Origin checks. `conn` is the connection
        the request came in on (a `peer.Conn`): the sign-in link looks up who owns it (9.3). `via`
        is the listener: "proxy" for the proxy socket (9.9), where `conn` is a `proxy.Peer`."""
        req = None
        try:
            headers = {str(k).lower(): str(v) for k, v in headers.items()}
            path, _, qs = target.partition("?")
            req = Req(method, path, {k: v[0] for k, v in parse_qs(qs, keep_blank_values=True).items()},
                      headers, headers.get("host", ""), conn=conn, via=via)
            res = self._route_proxy(req, body) if via == "proxy" else self._route(req, body)
        except Refuse as r:
            res = self._refusal(req, r)
        except Exception as e:
            if req is not None:
                self.hub.record_exception("request-failed", self._doc_hint(req),
                                          endpoint=req.path, method=method, **self._who(req))
            res = _json(500, {"ok": False, "error": f"the hub failed on this request "
                              f"({type(e).__name__}); the details are in `sheaf diag`"})
        return self._finish(req, res)

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
            if req.path == "/_/open" and r.page and "text/html" in req.headers.get("accept", ""):
                res = _html(401, _sign_in_page("This sign-in link did not work", r.page), headers=r.headers)
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
        if res.status >= 400 and req is not None and res.row is not False:     # False: counted, not written
            error = res.error or ""
            if not error and h.get("Content-Type") == "application/json":
                try:
                    error = json.loads(res.body).get("error", "")
                except ValueError:
                    pass
            self.hub.record(res.row or f"{req.route}-{res.status}", self._doc_hint(req), endpoint=req.path,
                            error=error or None, **self._who(req), **res.fields)
        return res

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
            req.raw = self._body(req, raw)
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
                return {"doc": doc, "root": data.get("root")} if theirs else None
            return data
        return accept

    @staticmethod
    def _for_members(found) -> bool:
        """A route a member may use: one 8.5 marks `cookie` or `cookie or key`, but not Ask and
        Tell, which run the hub account's own agent session."""
        name, who, _ = found
        return who in (COOKIE, EITHER, MEMBER, MINT) and name not in ("ask", "tell", "cancel", "jump")

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
        # A relay token the verifier let in, judged as a code is, before anything else (9.14).
        if req.headers.get("x-sheaf-relay"):
            return self._route_relay(req, raw)
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
        return fn(req)

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

    def _route_relay(self, req: Req, raw: bytes) -> Response:
        """A request the verifier let in with a relay token (9.14): `X-Sheaf-Relay` is the token's sha256, with no
        member header. The token says who asks, and opens its fork's stream and acks on its one sheaf, while that
        fork is the sheaf's live session and its member is in `[proxy.members]`."""
        cfg = self.hub.proxy
        req.route = RELAY_ROUTES.get((req.method, req.path), req.path)
        if req.member_id or req.headers.get("x-sheaf-code"):
            raise self._relay_refused(req, None, "two-credentials")
        row = self.relays.find(req.headers["x-sheaf-relay"])
        if row is None:
            raise self._relay_refused(req, None, "unknown")
        if row["member"] not in cfg.members:
            raise self._relay_refused(req, row, "member")
        req.relay, req.member, req.member_id = row, cfg.members[row["member"]], row["member"]
        if (req.method, req.path) not in RELAY_ROUTES:
            raise self._relay_refused(req, row, "route", 404, "no such route")
        if req.method == "POST":
            if req.headers.get("origin", "").lower() != cfg.origin:
                raise Refuse(403, "this request did not come from the front's own page")
            self._read_body(req, self._body(req, raw))
        doc = req.query.get("doc") if req.method == "GET" else req.body.get("doc")
        if doc != row["doc"]:
            raise self._relay_refused(req, row, "doc", 404, "no such document")
        _, _, st = self._sheaf(req, doc)
        if not self._relay_live(row, st):
            raise self._relay_refused(req, row, "moved")
        self._expire_relayed()
        return self._relay_stream(req) if req.method == "GET" else self._relay_ack(req)

    @staticmethod
    def _relay_live(row: dict, st) -> bool:
        """Whether the fork of the relay row `row` is the live session of the sheaf whose state is `st`."""
        return st is not None and st.live == "laptop" and st.sessions[0]["id"] == row["session"]

    def _relay_refused(self, req: Req, row, reason: str, status: int = 401, message: str = relay.NO_GOOD) -> Refuse:
        """The refusal of a relay token and its `relay-refused` row (15): the relay id when the hub knows the token,
        never the token or its hash. Made-up tokens are counted, one row a minute, as codes are."""
        fields = {"reason": reason, "route": req.route}
        if row is not None:
            fields["relay"] = row["id"]
        if reason == "unknown":
            n = self.relays.unknown()
            if not n:
                return Refuse(status, message, row=False)
            fields["count"] = n
        return Refuse(status, message, row="relay-refused", fields=fields)

    def _relay_stream(self, req: Req) -> Response:
        """`GET /_/relay`: `hello`, every Tell queued for the fork and not acked, then each new one, and `gone` once
        the token or its fork is no longer good. Each event asks again, so a token revoked by `sheaf relay revoke`
        in another process, or a member taken out, ends the stream at its next event."""
        row, hub = req.relay, self.hub
        hashed = req.headers["x-sheaf-relay"]

        def still_good(name, data):
            if name == "gone":
                return data
            now = self.relays.find(hashed)
            good = now is not None and now["id"] == row["id"] and row["member"] in hub.proxy.members
            if good:
                try:
                    e = hub.entry(row["doc"])
                    good = self._relay_live(row, work.state(hub, row["doc"], e.live.current()[1]))
                except NotFound:
                    good = False
            return data if good else events.Renamed("gone", {"doc": row["doc"]})
        sub = self.relays.connect(row["doc"], row["session"], still_good)
        who = {"relay": row["id"], "transcript": row["session"], **self._who(req)}
        sub.on_close = lambda: hub.record("relay-closed", row["doc"], **who)
        hub.record("relay-connected", row["doc"], **who)
        return _stream(sub)

    def _relay_ack(self, req: Req) -> Response:
        """`POST /_/relay {doc, id, outcome, error?}`: the relay delivered one Tell, or could not."""
        b, row = req.body, req.relay
        tid, outcome, error = b.get("id"), b.get("outcome"), b.get("error")
        _shape(isinstance(tid, str) and work.UUID_RE.fullmatch(tid), "id must be the Tell's id")
        _shape(outcome in RELAY_OUTCOMES, f"outcome must be one of {', '.join(RELAY_OUTCOMES)}")
        _shape(error is None or (isinstance(error, str) and len(error) <= 500), "error must be text of 500 characters at most")
        t = self.relays.ack(row["doc"], tid)
        if t is None:
            raise Refuse(404, "no such Tell is waiting for this session")
        if outcome == "delivered":
            self.hub.record("tell-delivered", row["doc"], tell=t.id, thread=t.thread, relay=row["id"], **self._who(req))
        else:
            line = " ".join((error or "the relay could not deliver it").split())
            self._relay_failed(row["doc"], t, "tell-relay-failed", line, relay=row["id"], **self._who(req))
        return _ok()

    def _relay_failed(self, address: str, t, kind: str, error: str, **fields):
        """A relayed Tell that will not be delivered: its row, and the page's `tellError` by its event."""
        self.hub.record(kind, address, tell=t.id, thread=t.thread, error=error, **fields)
        e = self.hub.entries.get(address)
        if e is not None:
            e.bus.publish("tell-relay-failed", {"id": t.thread, "error": error})

    def _expire_relayed(self):
        """Drop every relayed Tell queued an hour ago or more: asked by each relay request, each relayed Tell and
        each page's /_/doc, so one waits at most the 5 minutes of a relay's stream past its hour (9.14)."""
        for address, t in self.relays.expire():
            self._relay_failed(address, t, "tell-expired", relay.EXPIRED)

    def _relay_moved(self, address: str):
        """The sheaf's live session changed: its relay streams end and the Tells queued for the old one are dropped."""
        self.relays.end(address)
        for _, t in self.relays.drop(address):
            self._relay_failed(address, t, "tell-relay-failed", RELAY_MOVED)

    def _token(self, req: Req) -> bool:
        """Whether the request carries an MCP token that is good now; its owner is on `req.token`."""
        req.token = self.hub.tokens.verify(auth.bearer(req.headers.get("authorization")))
        return req.token is not None

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

    def _body(self, req: Req, raw) -> bytes:
        """The body, now that the caller is known to be let in: refused by its header when it is
        over the limit, before a byte of it is read."""
        try:
            n = int(req.headers.get("content-length") or (0 if callable(raw) else len(raw)))
        except ValueError:
            raise Refuse(400, "bad Content-Length") from None
        if n > MAX_BODY:
            raise Refuse(413, "the request is too large")
        raw = raw() if callable(raw) else raw
        if len(raw) > MAX_BODY:
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
    def _owned(self, req: Req, doc):
        """The address `doc` names, once the request may name it: text, and for a member one of their
        own roots and none whose visibility is its owner's alone when they are not the owner (9.11). Reads
        no more than the front matter, so it holds for a document that is gone."""
        _shape(isinstance(doc, str), "doc is missing")
        if req.member is not None and not (self.hub.member_owns(req.member, doc)
                                           and self.hub.visible(req.member, doc)):
            raise Refuse(404, "no such document")
        return doc

    def _reading(self, doc):
        """The lock of the sheaf's name `doc` (9.11), held by a read from the check of its visibility to the page
        or text sent: no write or move of its file comes between."""
        return place.held(self.hub, doc) if isinstance(doc, str) else contextlib.nullcontext()

    def _entry(self, req: Req, doc):
        """The document `doc` names. A member of proxy mode is told of no document of another
        root, nor of a root nested inside one of theirs: the same 404 as for one that does not
        exist, before anything is made or rendered for it (9.9)."""
        self._owned(req, doc)
        try:
            return self.hub.entry(doc)
        except NotFound:
            raise Refuse(404, "no such document") from None

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
                             page=LINK_USED if peer.supported() else f"{LINK_USED} {LINK_LIMIT}")
            no = self.peer_check(req.conn)
            if no is not None:
                raise Refuse(401, no.message, page=LINK_OTHER_USER if no.kind == peer.OTHER_USER else LINK_UNKNOWN,
                             detail=no.detail)
        elif not req.auth.key_ok(req.query.get("key")):
            raise Refuse(401, "that is not this hub's key", page=WRONG_KEY)
        nxt = req.query.get("next", "/")
        _shape(auth.safe_next(nxt), "next must be a path on this hub")
        return Response(303, {"Location": auth.location(nxt), "Set-Cookie": req.auth.set_cookie()})

    def _signin(self, req: Req) -> Response:
        """A one-time sign-in nonce for the caller that holds the key (`sheaf open`, 9.3)."""
        return _ok(nonce=req.auth.mint_signin(), expires=auth.SIGNIN_TTL)

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
        with self._reading(address):
            e = self._entry(req, address)
            self.hub.catch_up(e)
            return _html(200, self.hub.page(e, nonce, member=req.member), nonce)

    def _live(self, req: Req) -> Response:
        hub, member = self.hub, req.member
        if "doc" not in req.query:
            sub = hub.open_index_stream(lambda _: {"boot": hub.boot, "version": hub.version,
                                                   "service": hub.service},
                                        self._index_events(member) if member else None)
            if member is None and hub.auth is not req.auth:   # a rotation overtook this request, after it told the open streams
                sub.put("signed-out", {})
            return _stream(sub)
        with self._reading(req.query.get("doc")):
            return self._document_stream(req)

    def _document_stream(self, req: Req) -> Response:
        hub, member = self.hub, req.member
        e = self._entry(req, req.query.get("doc"))
        def for_member(name, data):
            # Asked at each event: a write that makes the sheaf its owner's alone silences a stream
            # opened before it (9.11). A change of `projects.toml` that shuts the member out is told `gone`, with
            # why (8.12): that alone, never a file of the sheaf that cannot be read for a moment.
            if hub.visible(member, e.address):
                return _document_events(name, data)
            if name == "grants" and not hub.granted(member, e.address):
                return events.Renamed("gone", {"doc": e.address, "why": "access"})
            return None
        sub = e.bus.subscribe(lambda tabs: {"boot": hub.boot, "version": hub.version,
                                            "service": hub.service, "tabs": tabs},
                              for_member if member else None)
        if member is None and hub.auth is not req.auth:       # a rotation overtook this request, after it told the open streams
            sub.put("signed-out", {})
        if hub.entries.get(e.address) is not e:               # a forget overtook this request, after it told the open streams
            sub.put("gone", {"doc": e.address})
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

    def _doc(self, req: Req) -> Response:
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
        snap = e.live.snapshot()
        snap["root"] = self._root_id(req, e.address)
        snap["rids"] = e.live.taken_rids()
        if req.member is not None:
            # Their own seen state, and nothing of the hub account's agent session (9.9).
            # A sheaf's Work on this and its Ask and Tell for James's window are refreshed as the meta's (9.12).
            self._expire_relayed()
            work, can = self.hub.member_work(e, req.member)
            extra = {} if work is None else {"work": work}
            return _ok(**proxy.for_member(snap), seen=self.hub.member_seen.get(req.member.id, e.address),
                       asking=[], question="", target=None, capabilities=can, lines=proxy.member_lines(), **extra)
        v = self.hub.asktell.view(e.address)
        return _ok(**snap, seen=self.hub.seen.get(e.address),
                   asking=self.hub.runner.active("ask", e.address),
                   question=e.live.session_question(), target=v.agent(),
                   capabilities=sorted(v.caps), lines=v.lines)

    def _mount(self, req: Req) -> Response:
        """The sheaf as JSON for the front's loader to mount (#116): the body through the sanitiser's mount mode and the
        meta block the page route sends. The same gate as the page: a member sees what they could open."""
        doc = req.query.get("doc")
        _shape(isinstance(doc, str) and doc.endswith(".md"), "doc must be the address of a sheaf")
        with self._reading(doc):
            e = self._entry(req, doc)
            self.hub.catch_up(e)
            try:
                got = self.hub.mount_doc(e, req.member)
            except RenderError as ex:
                raise Refuse(500, f"the page could not be rendered: {ex}") from None
            return _json(200, got, {"X-Content-Type-Options": "nosniff"})

    def _mount_asset(self, req: Req, name: str, kind: str) -> Response:
        """The loader's script and the page's style, the hub's own files. A request that names this hub's version
        (`?v=`) may be kept for a year: a new version is a new address. Any other is asked again each time."""
        body = (resources.files("sheafmd") / "page" / name).read_bytes()
        named = req.query.get("v") == self.hub.version
        return Response(200, {"Content-Type": kind, "X-Content-Type-Options": "nosniff",
                              "Cache-Control": "public, max-age=31536000, immutable" if named else "no-store"}, body)

    def _index_json(self, req: Req) -> Response:
        rendered = req.query.get("rendered", "0")
        _shape(rendered in ("0", "1"), "rendered must be 0 or 1")
        return _ok(**self.hub.index.data(rendered=rendered == "1", member=req.member))

    def _jobs(self, req: Req) -> Response:
        return _ok(**self.hub.jobs())

    # ── save and comment ─────────────────────────────────────────────────────
    def _save(self, req: Req) -> Response:
        b = req.body
        e = self._entry(req, b.get("doc"))
        h, edits = b.get("hash"), b.get("edits")
        _shape(isinstance(h, str) and h != "", "hash must be the hash of the version the edits were made against")
        _shape(isinstance(edits, list), "edits must be a list")
        for x in edits:
            _shape(isinstance(x, dict) and type(x.get("i")) is int and isinstance(x.get("html"), str)
                   and isinstance(x.get("saved", ""), str), "each edit is {i, html} or {i, html, saved}")
        rid = b.get("rid")
        _shape(rid is None or (isinstance(rid, str) and _RID_RE.fullmatch(rid)), "rid is not a request id")
        # The name's lock (9.11) from the guard's judging of the sheaf's home to the commit: move, write, render,
        # commit, one operation.
        with place.held(self.hub, e.address):
            guard, ticked = self._ticks(req, e)
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
                    self.hub.committed(e.address, req.member, "edit", gone=gone)
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
        """The list's row, or the sheaf's own page (10.11, `where`), ticks the sheaf's action (9.10): saved as the
        page saves a tick, so the file, the commit and the open tabs see what a tick in the page makes them see."""
        b = req.body
        e = self._entry(req, b.get("doc"))
        n, word, read, release = b.get("action"), b.get("word"), b.get("hash"), b.get("release", False)
        where = b.get("where", "list")
        _shape(where in ("list", "page"), "where must be list or page")
        _shape(type(n) is int and n >= 0, "action must be the number of the sheaf's action, from 0")
        _shape(isinstance(word, str) and word != "", "word must be the action's word")
        _shape(isinstance(read, str) and read != "", "hash must be the hash of the sheaf the list read")
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
                e.live.refresh()
            h, text = e.live.current()
        if h != read:
            raise Refuse(409, f"the sheaf changed since the {where} read it ({word}): reload the {where}")
        edit = the_list.tick_edit(text, n, word, release)
        if edit is None:
            raise Refuse(409, f"the sheaf no longer holds that action ({word}): reload the {where}")
        with place.held(self.hub, e.address):
            guard, ticked = self._ticks(req, e)

            def as_read(text, new, toggled):
                # The row names its action by place and word: on another text than the list read, another
                # action may sit there with the same word. Judged on the file under its lock.
                if md_hash(text) != read:
                    raise EditError(f"the sheaf changed since the {where} read it ({word}): reload the {where}")
                return guard(text, new, toggled)
            move, moved = self._mover(e, ticked)
            with self._moved_committed(e, req.member, "tick", moved):
                try:
                    got = e.live.save(h, [edit], guard=as_read, move=move)
                except (EditError, StaleError) as ex:
                    raise Refuse(409, str(ex)) from None
                if not got["changed"]:
                    raise Refuse(409, f"the sheaf no longer holds that action ({word}): reload the {where}")
                self.hub.index.touch(e.address)
                gone = moved[0] if moved else self._placed(e, ticked)
                moved.clear()
                self.hub.committed(e.address, req.member, "untick" if release else "tick", gone=gone)
        if "Stop James" in ticked:
            self._stop_james(req, e)
        if self.hub.the_list is not None and not release:     # a release answers nothing: the row stays where it is
            self.hub.the_list.ticked(e.address)
        return _ok(hash=got["hash"])

    def _mover(self, e, ticked):
        """(the `move` of a save, the list it puts the path the file left in): a write that shares the sheaf or
        withdraws its Share moves the file to the home of its new text before it writes it (9.11), so the text is
        written and rendered in its new folder. `ticked` is filled by the save's guard before the move is asked."""
        moved = []

        def move(text, new):
            if not ({"Share", "Unshare"} & ticked):
                return None
            try:
                gone = place.ahead(self.hub, e.address, text, new)
            except place.Refused as ex:
                # The write would leave the sheaf where it may not stay (9.11): nothing is written.
                raise EditError(f"This sheaf cannot go to its home: {ex.why}. Nothing was written.") from None
            if gone is None:
                return None
            moved.append(gone)
            return self.hub.file(e.address, placed=True)
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
                self.hub.committed(e.address, member, what, gone=moved.pop())

    def _placed(self, e, ticked) -> str | None:
        """After a write that shared the sheaf or withdrew its Share, under the lock of its name, its file goes to
        its home (9.11) if the write did not take it there (a text that changed meanwhile): the path in the root
        it left, None when it stayed. The caller commits the write and the move as one; the sheaf's address
        stays."""
        if not ({"Share", "Unshare"} & ticked):
            return None
        return place.place(self.hub, e.address, commit=False)

    def _ticks(self, req: Req, e):
        """The guard of a save (live.save) for the actions the hub judges: a one-off is never unticked and a sheaf
        answers Move to once (9.10), and the two it acts on (9.11); and the set it fills with the words the save
        ticked. Share is its owner's alone: ticked by anyone else, nothing is written; ticked by the owner, the same
        write opens the sheaf to the project. Who ticked is the signed-in member, never a name the request carries."""
        ticked = set()

        def guard(text, new, toggled):
            m = req.member
            if m is not None:
                # The gate (_owned) read the file before the lock: a write that closed the sheaf since is
                # seen here, on the text the save would write over.
                fm = visibility.front_matter(text)
                if not self.hub.may_open(m, e.address, fm):
                    raise Refuse(404, "no such document")
                # The page cannot edit a front matter (5): paragraphs of `---` would write one, and its
                # `sessions` would serve any transcript (9.12), its `visibility` open the sheaf.
                if visibility.front_matter(new) != fm:
                    raise EditError("A save cannot change the front matter: change it in the file.")
            if (word := the_list.unticks_one_off(text, new)) is not None:
                # A one-off action stays pressed (9.10, #108), for every person and by whatever edit: the deployment's
                # routine has acted on its tick, and an untick would move nothing back.
                raise EditError(f"{word} is pressed once: its tick cannot be taken back.")
            if (slug := the_list.ticks_another_move(text, new)) is not None:
                # A thread moves to one client (9.10, #109): a sheaf answers Move to once, by whatever edit.
                raise EditError(f"This thread moves to one client: Move to {slug} is ticked.")
            words = visibility.newly_ticked(toggled)
            if visibility.withdraws_share(text, new):
                # Withdrawing a Share is its owner's alone, as giving it is (#40), by whatever edit unticks the box:
                # anyone else's writes nothing; the owner's closes the sheaf again in the same write. The hub's own
                # person (no member: the loopback port or the key) reads every file, and withdraws it as an owner.
                fm = visibility.front_matter(text)
                if m is not None and not visibility.owner_of(fm, [m], self.hub.assignees(e.address, fm)):
                    raise EditError("Only the owner of this sheaf can withdraw its Share.")
                new = visibility.unshare(new)
                if visibility.front_matter(new).get("sessions", "") != fm.get("sessions", ""):
                    raise EditError("A save cannot change the front matter: change it in the file.")
                words.add("Unshare")
            if "Share" in words:
                if m is not None and not visibility.owner_of(fm, [m], self.hub.assignees(e.address, fm)):
                    raise EditError("Only the owner of this sheaf can share it.")
                if visibility.effective(visibility.front_matter(new)) == "owner":
                    by = (m.short or m.name) if m is not None else self.hub.person
                    new = visibility.share(new, by, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
                    # Share rewrites the front matter: a line it takes out must not join a skipped one to `sessions`.
                    if visibility.front_matter(new).get("sessions", "") != visibility.front_matter(text).get("sessions", ""):
                        raise EditError("A save cannot change the front matter: change it in the file.")
            ticked.clear()
            ticked.update(words)
            return new
        return guard, ticked

    def _stop_james(self, req: Req, e):
        """A member ticked Stop James (9.11): a `stop-james` row, and for a sheaf of James a file in the
        `[list]`'s `stop_dir` that the box's supervisor of James reads to end his window for the project.
        The hub kills nothing itself."""
        rel = Address.parse(e.address).rel
        project = "/".join(rel.split("/")[:2]) if rel.count("/") >= 2 else ""
        try:
            fm = visibility.front_matter((e.path).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            fm = {}
        assistant = visibility.text(fm, "assistant")
        m = req.member
        the = self.hub.the_list
        if assistant.casefold() != "james":
            drop = "not a sheaf of James"
        elif not project:
            drop = "the sheaf is in no <client>/<project> folder"
        else:
            if the is not None and the.serves(Address.parse(e.address).root):
                self._stop_tells(project, m)
            # The box's supervisor reads the line as `<client>/<project>` (tt-tiroir routines/james, stops).
            drop = work.drop(the.cfg.stop_dir if the is not None else None, project,
                             (project + "\n").encode("utf-8"), "no stop_dir in [list]")
        self.hub.record("stop-james", e.address, project=project, assistant=assistant,
                        by=(m.short or m.name) if m is not None else self.hub.person, drop=drop)

    STOPPED = "Stopped before delivery: Stop James closed this project's window before James took this."

    def _stop_tells(self, project: str, member):
        """Every Ask and Tell for `project` still waiting in `tell_dir` for James's window, removed before the Stop
        is dropped, and a reply in each one's thread, signed by the member who stopped him, saying it never reached
        him (9.12): a Stop ends the work, and none of it goes on unseen. A `tell-stopped` row for each, without
        its text. The box's supervisor clears what is left of the project's the same way (tt-tiroir #136)."""
        folder = self.hub.the_list.cfg.tell_dir
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
            sheaf, thread = tell.get("sheaf"), tell.get("thread")
            if not (isinstance(sheaf, str) and isinstance(thread, str)):
                said = "no thread in the drop"
            elif not self._of_project(sheaf, project):
                said = "the drop names a sheaf of another root or project"
            else:
                said = self._say_stopped(sheaf, thread, member)
            self.hub.record("tell-stopped", sheaf if isinstance(sheaf, str) else None, project=project,
                            thread=thread if isinstance(thread, str) else None, what=tell.get("kind"), by=by,
                            said=said)

    def _of_project(self, sheaf: str, project: str) -> bool:
        """Whether `sheaf` is a sheaf of `project` on the list's root, where a drop's sheaf always is (9.12)."""
        at = Address.parse(sheaf)
        return self.hub.the_list.serves(at.root) and at.rel.startswith(project + "/") and at.rel.count("/") == 2

    def _say_stopped(self, sheaf: str, thread: str, member) -> str:
        """The STOPPED reply in `thread` of `sheaf`: "written", or why not."""
        name = (member.name if member is not None else self.hub.person) or "sheaf"
        try:
            e = self.hub.entry(sheaf)
            if member is not None and not self.hub.may_open(member, e.address,
                                                             visibility.front_matter(e.live.current()[1])):
                return "the member who stopped cannot open the sheaf"
            with place.held(self.hub, e.address):       # the write and its commit, one step (9.11)
                e.live.comment("reply", {"id": thread, "body": self.STOPPED}, None, by=name, announce=True)
                self.hub.index.touch(e.address)
                self.hub.committed(e.address, member, "comment")
        except NotFound:
            return "the sheaf is gone"
        except (rdc.AnchorError, rdc.NoComment, KeyError, ValueError) as ex:
            return f"not written: {ex}"
        except Exception:                               # the Stop is dropped whatever becomes of the reply
            self.hub.record_exception("tell-stopped-reply-failed", sheaf)
            return "not written: the hub failed on it (sheaf diag)"
        return "written"

    # ── Work on this (9.12) ──────────────────────────────────────────────────
    def _sheaf(self, req: Req, doc):
        """The address `doc` names, its file's front matter and its work.State, once it is a sheaf the member may
        open (9.11) of the list's root, at `<client>/<project>/<file>.md`. Else the 404 of a document that is not
        there."""
        with self._reading(doc):
            address = self._owned(req, doc)
            if not work.is_sheaf(self.hub, address):
                raise Refuse(404, "no such document")
            try:
                text = self.hub.roots.document(address).read_text(encoding="utf-8")
            except (NotFound, OSError, UnicodeDecodeError):
                raise Refuse(404, "no such document") from None
        return address, visibility.front_matter(text), work.state(self.hub, address, text)

    def _code_sheaf(self, req: Req, doc):
        """`_sheaf` for a request of a sign-in code (9.13): the code's own sheaf, open to its member, else the 404
        that names neither, since the laptop cannot tell the two apart and neither can a guesser."""
        try:
            if doc != req.code.doc:
                raise Refuse(404, "another sheaf")
            return self._sheaf(req, doc)
        except Refuse as r:
            if r.status != 404:
                raise
            raise self._code_refused(req, req.code, "doc", 404, codes.NOT_OPEN) from None

    def _code_moved(self, req: Req):
        """The code's session is no longer the sheaf's forkable one: the code is spent (9.13)."""
        self.codes.spend(req.code)
        return self._code_refused(req, req.code, "moved", 404, codes.NOT_OPEN)

    def _code(self, req: Req) -> Response:
        """A sign-in code for `tiroir work` on one sheaf (9.13): for the member who asks in its Work on this, or,
        with the key, for the member the body names (`sheaf code issue`). Made only while the sheaf has a session to
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
            raise Refuse(404, "this sheaf has no live session on the box to fork")
        try:
            code, c = self.codes.issue(req.member.id, address, sid)
        except codes.TooMany as ex:
            raise Refuse(429, str(ex)) from None
        self.hub.record("code-issued", address, by=work.member_word(req.member), code=c.id, expires=c.expires_text,
                        via="cli" if req.kind == "key" else "popover", **self._who(req))
        return _ok(code=code, expires=c.expires_text, id=c.id)

    def _session(self, req: Req) -> Response:
        """The transcript of one of the sheaf's box-hosted sessions, the live one without `id`, from the copy of
        James's transcripts (9.12). It names only a file the front matter lists, of the box, in `sessions_dir`.
        A sign-in code (9.13) takes no `id`: it serves the session it was made for, once, while that is the
        sheaf's forkable one."""
        code = req.code
        if code is not None:
            _shape("id" not in req.query, "a sign-in code serves the session it was made for: send no id")
            if code.served:
                raise self._code_refused(req, code, "used")
            address, fm, st = self._code_sheaf(req, req.query.get("doc"))
            if work.code_session(st, code.session) is None:
                raise self._code_moved(req)
            body = work.open_transcript(st.cfg.sessions_dir, code.session)
            if body is None:
                raise Refuse(404, "this sheaf has no such session on the box")
            if not self.codes.serve(code):                  # one of two racing GETs: the flag is set before a byte
                raise self._code_refused(req, code, "used")
            self.hub.record("code-used", address, code=code.id, route="session", **self._who(req))
            return self._transcript(req, address, fm, code.session, body, via="code", code=code.id)
        address, fm, st = self._sheaf(req, req.query.get("doc"))
        sid = req.query.get("id")
        _shape(sid is None or work.UUID_RE.fullmatch(sid), "id must be a session id (a lowercase UUID)")
        if sid is None:
            sid = st.forkable           # a live session on a laptop: none, never an older box copy to fork
        if sid not in st.box or st.cfg.sessions_dir is None:
            raise Refuse(404, "this sheaf has no such session on the box")
        body = work.open_transcript(st.cfg.sessions_dir, sid)
        if body is None:
            raise Refuse(404, "this sheaf has no such session on the box")
        return self._transcript(req, address, fm, sid, body)

    def _transcript(self, req: Req, address: str, fm, sid: str, body: bytes, **via) -> Response:
        self.hub.record("transcript-downloaded", address, transcript=sid, by=work.member_word(req.member),
                        issue=visibility.text(fm, "issue"), **via, **self._who(req))
        return Response(200, {"Content-Type": "application/x-ndjson", "Content-Disposition": _disposition(f"{sid}.jsonl"),
                              "Cache-Control": "no-store", "X-Sheaf-Session": sid}, body)

    def _drop_for_james(self, req: Req, e, kind: str, body: str, thread: str) -> str:
        """The file Ask or Tell drops in `[list]`'s `tell_dir` for the box's supervisor to hand to James's session
        for the project with `sheaf deliver`, and its `tell-dropped` row. The hub runs no agent of its own for it.
        A Tell carries its id and the words of a local Tell (`message`), so every path says the same (9.12)."""
        project = "/".join(Address.parse(e.address).rel.split("/")[:2])
        by = work.member_word(req.member)
        out = {"project": project, "member": by, "sheaf": e.address, "text": body[:work.TEXT_MAX], "kind": kind,
               "thread": thread, "address": e.address, "abs_path": str(e.path)}
        if kind == "tell":
            out.update(id=str(uuid.uuid4()), message=self._tell_message(req, e, thread))
        drop = work.drop(self.hub.the_list.cfg.tell_dir, project, json.dumps(out).encode("utf-8"),
                         "no tell_dir in [list]")
        self.hub.record("tell-dropped", e.address, what=kind, project=project, by=by, drop=drop,
                        **({"tell": out["id"]} if "id" in out else {}))
        return drop

    def _tell_message(self, req: Req, e, thread: str) -> str:
        """What a member's Tell on the thread `thread` says to the session, in the words of a local Tell (11.3)."""
        c = rdc.parse(e.live.current()[1]).by_id(thread)
        return prompts.tell(e.address, str(e.path), req.member.name, c, self.hub.asktell.links(e.address))

    def _work_route(self, address: str, text: str, kind: str) -> str | None:
        """Where a member's Ask or Tell goes on the sheaf whose text is `text` (9.12, 9.14): "box" to James's
        window, "relay" to the fork's relay (a Tell only), None nowhere."""
        st = work.state(self.hub, address, text)
        can = st.can if st is not None else []
        if f"box-{kind}" in can:
            return "box"
        return "relay" if kind == "tell" and "relay-tell" in can else None

    def _relay_tell(self, req: Req, e, thread: str) -> str | None:
        """Queue a member's Tell for the fork's relay and write `tell-relayed`; the page's `tellError`, or None."""
        st = work.state(self.hub, e.address, e.live.current()[1])
        if st is None or st.live != "laptop":
            return RELAY_MOVED
        t = relay.Tell(str(uuid.uuid4()), thread, self._tell_message(req, e, thread), work.member_word(req.member))
        self._expire_relayed()
        try:
            self.relays.put(e.address, st.sessions[0]["id"], t)
        except relay.Full as ex:
            return str(ex)
        self.hub.record("tell-relayed", e.address, tell=t.id, thread=thread, by=t.by,
                        transcript=st.sessions[0]["id"], **self._who(req))
        return None

    def _james_called(self, caller, address):
        """A door call of James's session (9.12): a write to a sheaf of James makes the session it names the sheaf's
        live one, once the copy holds it; one the copy does not hold yet waits, the newest per sheaf, and is looked
        for again at his next call. The session is never the request's to choose: only an id whose transcript is
        James's in that project's folder is taken."""
        sid = caller.session
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
        for at, (wanted, since_, seq_) in waiting:
            try:
                self._record_james(at, wanted, caller, since_, seq_)
            except Exception:                           # one sheaf's failure never stops the others nor this write
                self._drop_waiting(at, seq_)
                self.hub.record_exception("session-hook-failed", at)
        if address is not None:
            self._record_james(address, sid, caller, since, seq)

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
            return True

    def _record_james(self, address: str, sid: str, caller, since: float, seq: int):
        """James's session `sid`, named by his write `seq` to `address`, becomes the sheaf's live session, the first of
        `sessions`, when it is a sheaf of James on the list's root, `[list]` names a box, and the copy holds `sid` as a
        session of its project. The hub is the only writer of `sessions` (9.12). Nothing when it is the live one
        already, a member's fork is, or James wrote to the sheaf again since."""
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
        found = work.james_has(the.cfg, project, sid)
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
            # James's to the sheaf keeps the session it names.
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
                self.hub.committed(address, by=caller.display, what="session")
        self._drop_waiting(address, seq)
        if moved:
            self._relay_moved(address)
            self.hub.record("session-recorded", address, transcript=sid, by="james")

    def _james_may_take(self, text: str, sid: str) -> bool:
        """Whether James's session `sid` becomes the live one of the sheaf whose text is `text`: the live one is
        James's on the box, another than `sid`, or there is none yet. Never over a member's fork on a laptop."""
        items = work.sessions(visibility.front_matter(text))
        return not items or (items[0]["host"] == self.hub.the_list.cfg.box and items[0]["id"] != sid)

    def _sessions(self, req: Req) -> Response:
        """A member forked one of the sheaf's sessions on their machine (9.12): the fork becomes the sheaf's live
        session, the first item of `sessions`, under the signed-in member's name whatever the body says."""
        b = req.body
        code = req.code
        if code is not None:
            # A code reports the fork of the transcript it downloaded: never before, and once (9.13).
            if code.served is False:
                raise self._code_refused(req, code, "order")
            address, fm, _ = self._code_sheaf(req, b.get("doc"))
        else:
            address, fm, _ = self._sheaf(req, b.get("doc"))
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
            # The gate (_sheaf) read the file before the lock: a write that closed the sheaf since is seen here.
            fm = visibility.front_matter(text)
            if not self.hub.may_open(req.member, e.address, fm):
                raise Refuse(404, "no such document")
            if code is not None:
                # Under the lock, where the fork is written: the code's session still the forkable one, an id
                # that is no box session's to push out, and one fork of two racing POSTs.
                if work.code_session(work.state(self.hub, e.address, text), code.session) is None:
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
            self.hub.committed(e.address, req.member, "fork")
        # The fork is the live session now: the relay of the one before ends, and this one gets its own (9.14).
        self._relay_moved(address)
        token, rid = self.relays.issue(req.member_id, address, sid)
        via = {"via": "code", "code": code.id} if code is not None else {}
        if code is not None:
            self.hub.record("code-used", address, code=code.id, route="sessions", **self._who(req))
        self.hub.record("session-forked", address, transcript=sid, by=by, machine=machine,
                        issue=visibility.text(fm, "issue"), relay=rid, **via, **self._who(req))
        return _ok(hash=h, relay=token)

    def _pin(self, req: Req) -> Response:
        """The page keeps the version it holds past a change of the file, while a form holds the reload
        that change needs: the hub keeps it too, beside the newest (7.4)."""
        b = req.body
        e = self._entry(req, b.get("doc"))
        h = b.get("hash")
        _shape(isinstance(h, str) and h != "", "hash must be the hash of the version the page holds")
        if not e.live.pin(h):
            raise Refuse(409, UNKNOWN)
        return _ok()

    def _comment(self, req: Req) -> Response:
        b = req.body
        e = self._entry(req, b.get("doc"))
        op = b.get("op")
        _shape(op in OPS, f"op must be one of {', '.join(OPS)}")
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
        # Ask and Tell run the hub account's own session, which a member is not (9.9); on a sheaf whose live
        # session is James's on the box they go to his window instead, by a file the hub drops (9.12), and a Tell
        # on a sheaf whose live session is a member's fork goes to that fork's relay while it is connected (9.14).
        to_box = route = None
        if member is not None and (b.get("ask") or b.get("tell")):
            _shape(not (b.get("ask") and b.get("tell")), "a comment is sent with Ask or with Tell, not both")
            to_box = "ask" if b.get("ask") else "tell"
            route = self._work_route(e.address, e.live.current()[1], to_box) if starts else None
            _shape(route is not None, proxy.PROXY_LINE)
        ask, tell = starts and bool(b.get("ask")) and not to_box, starts and bool(b.get("tell")) and not to_box
        # A Tell that cannot go out still writes the comment, and then starts no wait. A reply
        # sent with Tell to a thread that is being told is such a Tell: the wait the first one
        # began stays as it is (SPEC 11.3).
        tell_line = self.hub.asktell.refusal(e.address, "tell") if tell else None
        if tell and tell_line is None and op == "reply":
            tell_line = self.hub.asktell.telling_line(e.address, b.get("id", ""))
        can_tell = tell and tell_line is None
        signed = {"by": member.name, "author": member.name} if member else {}
        if member is not None:
            def still_visible(text):
                # The gate (_entry) read the file before the lock: a write that closed the sheaf since is seen here,
                # and a live session that moved since keeps Ask and Tell from the window or relay it no longer is.
                fm = visibility.front_matter(text)
                if not self.hub.may_open(member, e.address, fm):
                    raise Refuse(404, "no such document")
                if to_box and self._work_route(e.address, text, to_box) != route:
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
            if not snap.get("again"):
                self.hub.committed(e.address, member, "comment")
        if snap.get("again"):
            # Taken before under this request id: what the first request started (an Ask, a Tell's wait)
            # is running or done, and the page hears of it by its events.
            ask = tell = False
            to_box = None
        if to_box and route == "relay":
            if (line := self._relay_tell(req, e, snap["id"])) is not None:
                snap["tellError"] = line
        elif to_box:
            drop = self._drop_for_james(req, e, to_box, b["body"], snap["id"])
            if drop != "written":
                snap[f"{to_box}Error"] = "The hub could not send this to James's window; the comment is written."
        # The job looks the document up again when it starts: it names its thread in the text the
        # comment was just written in, so a forget in between, and another folder that takes the name,
        # cannot hand it that folder's thread of the same id (SPEC 7.3). A forget that leaves no folder
        # under the name, or a file gone meanwhile, is refused as well: the comment is still answered.
        if ask:
            try:
                self.hub.asktell.start_ask(e.address, snap["id"], held=snap["hash"])
            except JobRefused as r:
                snap["askError"] = r.message
        if tell:
            try:
                if not can_tell:
                    raise JobRefused(409, tell_line or NO_AGENT)
                self.hub.asktell.start_tell(e.address, snap["id"], waiting=True, held=snap["hash"])
            except JobRefused as r:
                if can_tell and not r.leaves_wait:   # a wait this request began, and no other
                    e.live.stop_waiting(snap["id"])
                snap["tellError"] = r.message
            snap["telling"] = e.live.waiting()
        return _ok(**(proxy.for_member(snap) if member else snap))

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

    def _ask(self, req: Req) -> Response:
        e, cid = self._thread_job(req)
        try:
            self.hub.asktell.start_ask(e.address, cid, held=self._page_hash(req))
        except JobRefused as r:
            raise Refuse(r.status, r.message) from None
        return _ok()

    def _tell(self, req: Req) -> Response:
        e, cid = self._thread_job(req)
        try:
            self.hub.asktell.start_tell(e.address, cid, held=self._page_hash(req))
        except JobRefused as r:
            raise Refuse(r.status, r.message) from None
        return _ok()

    def _jump(self, req: Req) -> Response:
        """Bring the session's terminal forward by the command of config.toml (SPEC 4.3, 8.5). The body
        names a document; which command runs, and for which session, is not the request's to say."""
        e = self._entry(req, req.body.get("doc"))
        try:
            self.hub.asktell.jump(e.address)
        except JobRefused as r:
            raise Refuse(r.status, r.message) from None
        return _ok()

    def _cancel(self, req: Req) -> Response:
        """A cancel stops what runs and clears the page, and asks nothing of the file: a document
        that is gone, or whose root was forgotten, has nothing left to stop, and the answer is ok."""
        doc = self._owned(req, req.body.get("doc"))
        cid = self._comment_id(req)
        what = req.body.get("what")
        _shape(what in ("ask", "tell"), "what must be ask or tell")
        self.hub.asktell.cancel(doc, cid, what)
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

    def _diag(self, req: Req) -> Response:
        b = req.body
        kind = b.get("kind")
        _shape(isinstance(kind, str) and kind.strip(), "kind is missing")
        doc = b.get("doc") if isinstance(b.get("doc"), str) else None
        detail = {str(k)[:40]: str(v) for k, v in list(b.items())[:40] if k not in _RESERVED}
        diagnostics.record("page", kind.strip()[:40], doc, **detail, **self._who(req))
        return Response(204)

    # ── the MCP door (the key and a name, or a token) ────────────────────────
    def _mcp(self, req: Req) -> Response:
        if req.token:
            the = self.hub.the_list
            james = the is not None and the.cfg.james_token and req.token.name == the.cfg.james_token
            caller = Caller(req.token.display, req.token,
                            session=req.headers.get("x-james-session", "") if james else None)
        else:
            caller = Caller(req.display)
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
            return _ok(**self.hub.render(md, settings, target))
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
        self.hub.expect_restart()
        return _ok()

    def _forget_restart(self, req: Req) -> Response:
        self.hub.forget_restart()
        return _ok()

    def _stop(self, req: Req) -> Response:
        reason, force = req.body.get("reason"), req.body.get("force", False)
        _shape(reason in ("stop", "upgrade"), "reason must be stop or upgrade")
        _shape(isinstance(force, bool), "force must be true or false")
        if not self.hub.request_stop(reason, force):
            raise Refuse(409, "an Ask or Tell is running, so the hub was not stopped for the upgrade")
        return _ok()
