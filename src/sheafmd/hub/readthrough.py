"""sheafmd.hub.readthrough — the agency tiroir reads its client tiroirs through (SPEC 9.9, ticket 23).

    Clients                the agency side: the "Clients" folder, one sub-folder per client tiroir, asked over the channel
    is_clients(address)    whether an address is under the reserved root `Clients`
    fold_rows(client, rows)  a client's rows as the agency's Sheaf draws them under `Clients/<client>`
    member_for(hub, email) the client side: the one member of this hub with that e-mail, else None
    served(hub, email)     that member when they are an agency member: the only ones a client tiroir answers for

The agency hub keeps nothing of a client page: no copy, no cache, no index entry, no line holding an address or a title. It
forwards the signed-in member's request and returns what the client hub says; the client hub does all the judging, as that
member, with the code it already has. The member the client hub answers for is named by `as`, their e-mail, which the agency
hub sets from the signed-in member and never reads from a request. There is no scope that widens beyond that member.

The channel itself (the token, the route, the HTTP client) is ticket 20's; `Clients` takes it as `call(client, verb, body) ->
(status, answer)`, which raises OSError when the client tiroir does not answer.
"""
import json
import re

from . import roots as roots_mod
from . import sheaf_view

ROOT = "Clients"                # the reserved root name of the folder
NOTHING = {"rows": [], "tree": [], "more": {}}      # what a member with nothing to see there is told, and a member with no account


class NotReachable(Exception):
    """A client tiroir that did not answer: the view says so, and serves nothing older."""


class NoEmail(Exception):
    """The signed-in member has no e-mail on this tiroir, so no client tiroir can know who is asking."""


AGENCY_KEPT = ("cache-control", "x-content-type-options", "referrer-policy")    # what the agency lets a client's answer say about itself


def kept_headers(headers) -> dict:
    """The few headers of a client tiroir's answer this hub repeats, by a closed list: the type, the CSP, cookies and redirects are
    this origin's own to say."""
    return {k: v for k, v in (headers or {}).items()
            if isinstance(k, str) and isinstance(v, str) and k.lower() in AGENCY_KEPT and _PLAIN_VALUE.fullmatch(v)}


_PLAIN_VALUE = re.compile(r"[\t\x20-\x7e\x80-\xff]*")          # a header value: no line break, no NUL, and what a latin-1 header line can hold
_SCRIPT_RE = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.S | re.I)
_NONCE_ATTR = re.compile(r'\s+nonce="([^"]*)"')
_META_ATTRS = 'id="rd-edit-meta" type="application/json"'     # the page's data block, as `adopt` keeps it


def adopt(html: str, client_nonce, nonce: str) -> str:
    """A client page as this origin serves it: a script holds only when it is this version's own page script (the one the hub
    renders every page with) or the page's data block, and the first runs under `nonce`, the one this hub drew. Every other
    script of the client's HTML is dropped, whatever nonce it names, so the client tiroir runs no code of its own here."""
    from ..render import page_script
    own = page_script()

    def one(m):
        attrs, body = m.group(1), m.group(2)
        if attrs.strip() == _META_ATTRS:
            return m.group(0)
        if client_nonce and _NONCE_ATTR.fullmatch(attrs) and _NONCE_ATTR.fullmatch(attrs).group(1) == client_nonce and body == own:
            return f'<script nonce="{nonce}">{own}</script>'
        return ""
    return _SCRIPT_RE.sub(one, html)


def is_clients(address) -> bool:
    return isinstance(address, str) and (address == ROOT or address.startswith(ROOT + "/"))


def read_only_doc(got: dict) -> dict:
    """`got`, a `/_/doc` answer for a page read through (9.9), with no agent, no Tell target, no Work and no session byline: the page of
    a client is read and commented on here, and what its client tiroir says of its agents is that tiroir's."""
    return {**{k: v for k, v in got.items() if k not in ("way_back", "work")},
            "target": None, "targets": [], "capabilities": [], "lines": {}, "telling": []}


def agency_config(config: dict, doc: str) -> dict:
    """The meta block of a page read through, or the config of its mount, with what the page script acts on set by this hub:
    the address it reads and writes is `doc`, the one this hub asked for, and it has no actions, no editor and no agent. The
    script runs on this origin with the member's cookie, so a client tiroir that named another address or an action would
    have this hub's page act on them (SPEC 9.9, ticket 190). A session's `work` and `way_back` are dropped, as `read_only_doc` drops
    them from the doc state; the client's own keys the script reads only for drawing are kept."""
    return {**{k: v for k, v in config.items() if k not in ("way_back", "work")}, "doc": doc, "actions": [], "edit": False,
            "editable": [], "agent": None, "can": [], "targets": [], "lines": {}}


def agency_meta(html: str, doc: str) -> str:
    """A client page with its meta block set by this hub (`agency_config`): every script `adopt` keeps as the data block, by
    the same matcher, whatever spelling of the tag the client hub chose. The first is the one the page script reads, and it
    becomes the agency's block in the form the hub writes; the others go. A first block that is no JSON object gives the
    agency's block from nothing (ticket 190, from the review of #655)."""
    first = True

    def one(m):
        nonlocal first
        if m.group(1).strip() != _META_ATTRS:
            return m.group(0)
        if not first:
            return ""
        first = False
        try:
            meta = json.loads(m.group(2))
        except ValueError:
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        return f'<script {_META_ATTRS}>' + json.dumps(agency_config(meta, doc)).replace("<", "\\u003c") + "</script>"
    return _SCRIPT_RE.sub(one, html)


def fold_rows(client: str, rows: list) -> list:
    """The rows `client`'s hub told, drawn under `Clients/<client>`: the address, URL, folder and root carry the prefix. Whose
    rows they are is the client hub's to say, so none of the owner's actions (Share, Keep, Archive, a session's way back)
    survives: the agency member is not the owner of a client page."""
    if not isinstance(rows, list):
        raise NotReachable("the client tiroir answered with rows that are not a list")
    out = []
    for r in rows:
        if not (isinstance(r, dict) and all(isinstance(r.get(k), str) for k in ("doc", "folder", "root"))):
            raise NotReachable("the client tiroir answered with a row that is not one")
        r = {k: v for k, v in r.items() if k != "shared_from"}
        folder = "/".join(p for p in r["folder"].split("/") if p not in ("", ".", ".."))
        doc = "/".join(p for p in r["doc"].split("/") if p not in ("", ".", ".."))
        top = r["root"]
        out.append({**r, "doc": f"{ROOT}/{client}/{doc}", "url": roots_mod.url_path(f"{ROOT}/{client}/{doc}"),
                    "folder": f"{ROOT}/{client}/{folder}", "root": f"{ROOT}/{client}/{top}",
                    "own": False, "can_move": False, "share": "", "kept": False, "archived": False, "session": "", "session_tip": "",
                    "session_link": None, "write": "", "write_tip": ""})
    return out


class Clients:
    """The client tiroirs of an agency tiroir (`[proxy.clients]`), and the one place that asks them."""

    def __init__(self, table: dict, call):
        self._table = dict(table)
        self._call = call

    def names(self) -> list:
        return sorted(self._table, key=str.casefold)

    def has(self, name) -> bool:
        """Whether `name` is, exactly, the name of a configured client tiroir."""
        return isinstance(name, str) and name in self._table

    def split(self, address):
        """(client, address on that hub) of `Clients/<client>/<address>`; None for anything that names no page of a configured client."""
        parts = address.split("/", 2) if isinstance(address, str) else []
        if len(parts) != 3 or parts[0] != ROOT or parts[1] not in self._table or not parts[2] or parts[2].startswith("/"):
            return None
        return parts[1], parts[2]

    def read(self, client: str, member, op: str, **fields) -> dict:
        """What `client`'s hub says to `op` for `member`. `as` is the member's own e-mail and nothing a caller wrote; a field named
        `as` or `role` in `fields` is dropped. No answer is `NotReachable` and nothing is kept for the next time."""
        return self._ask(client, member, "read", {"op": op, **fields})

    def may_open(self, client: str, member, rest: str) -> bool:
        """Whether `member` may open the page at `rest` on `client`'s hub, as that hub says it. A client that does not answer, or
        refuses, is no."""
        try:
            return self.read(client, member, "open", doc=rest).get("open") is True
        except (NotReachable, NoEmail):
            return False

    def relay(self, client: str, member, op: str, doc: str, **fields) -> dict:
        """The envelope `{status, type, body, nonce}` of `client`'s hub for a page route (`page`, `mount`, `doc`, `writes`) run as
        `member`: `doc` is the address on that hub, `mount` the prefix its page is told under."""
        return self._envelope(self._ask(client, member, "read", {"op": op, "doc": doc, **fields}))

    def comment(self, client: str, member, doc: str, request: dict) -> dict:
        """The envelope of `client`'s hub for a comment write (`request` is the page's own body) run as `member`: it signs it."""
        return self._envelope(self._ask(client, member, "comment", {"doc": doc, "request": request}))

    @staticmethod
    def redirect(client: str, headers) -> str:
        """Where a client's 302 sends the browser, under `Clients/<client>`: only a path on that client's hub that is a page there (a
        Forward of the client's own, 9.11). A missing, external or doubled address, a path of the hub's own routes or of a `Clients`
        folder (a second hop) is a client that did not answer as one."""
        where = headers.get("Location") if isinstance(headers, dict) else None
        if (not isinstance(where, str) or not re.fullmatch(r"/[^\s\\?#]*", where) or where.startswith(("//", "/_/"))
                or is_clients(where[1:]) or not where[1:] or not _PLAIN_VALUE.fullmatch(where)):
            raise NotReachable("the client tiroir sent the page somewhere that is not one of its pages")
        return f"/{ROOT}/{client}{where}"

    @staticmethod
    def _envelope(answer: dict) -> dict:
        """`answer` as the envelope it must be (`status` a whole number from 200 to 599 that carries a body, `body` text that encodes, `headers` a table when there are any), or the
        client tiroir did not answer as one."""
        status, body = answer.get("status"), answer.get("body")
        if (not isinstance(status, int) or isinstance(status, bool) or not 200 <= status <= 599 or status in (204, 304) or 300 <= status <= 399 and status != 302
                or not isinstance(body, str) or not isinstance(answer.get("headers", {}), dict) or answer.get("type") not in ("html", "json")):
            raise NotReachable("the client tiroir did not answer as one")
        try:
            body.encode("utf-8")
        except UnicodeEncodeError:
            raise NotReachable("the client tiroir did not answer as one") from None
        return answer

    def _ask(self, client, member, verb, fields) -> dict:
        email = member.email
        if not email:
            raise NoEmail("this tiroir does not know your e-mail address, so a client tiroir cannot tell who is asking")
        body = {"as": email, **{k: v for k, v in fields.items() if k not in ("as", "role", "admin")}}
        try:
            status, answer = self._call(client, verb, body)
        except OSError as e:
            raise NotReachable(f"the client tiroir {client} is not reachable") from e
        if status == 200:
            if not isinstance(answer, dict):
                raise NotReachable(f"the client tiroir {client} did not answer as a channel does")
            return answer
        # Not a 200: the channel refused (a wrong token or source, no `read` scope) or the client failed. Never an empty folder: that
        # is what a member with nothing to see is told, and the client already answers that with a 200 (so no oracle for "has an account").
        raise NotReachable(f"the client tiroir {client} did not answer")


def member_for(hub, email):
    """The one member of `hub` whose e-mail is `email`, ignoring case; None for no e-mail, no member, or two (never the first)."""
    if not isinstance(email, str) or not email.strip() or hub.proxy is None:
        return None
    found = [m for m in hub.proxy.members.values() if m.email and m.email.casefold() == email.strip().casefold()]
    return found[0] if len(found) == 1 else None


def served(hub, email):
    """`member_for`, and only when they are an agency member: a client tiroir answers over the channel for them alone."""
    m = member_for(hub, email)
    return m if m is not None and m.agency else None


def answer(handler, body, gone=None) -> tuple:
    """(status, answer) of this hub, the client tiroir, to a `read` of the channel: `body` is `{as, op, ...}`. `as` is the only
    identity: the member it names, when they are an agency member here, is who the op runs as, through the code a member's own
    request runs. Anything else (no `as`, `*`, no member of that e-mail, two, a client member) is the answer of a member with
    nothing to see, with no status that tells whether an account exists. There is no op, field or scope that widens beyond
    that member. `gone()`, when given, says the agency has closed the connection: the sheaf's data run then ends with `Abandoned`."""
    hub, op = handler.hub, body.get("op")
    member = served(hub, body.get("as"))
    if op == "sheaf":
        if member is None:
            return 200, {k: type(v)() for k, v in NOTHING.items()}
        d = sheaf_view.data(hub, member, handler._titles, gone=gone)
        return 200, {"rows": d["rows"], "tree": d["tree"], "more": d["more"]}
    if op == "open":
        doc = body.get("doc")
        if member is None or not isinstance(doc, str):
            return 200, {"open": False}
        doc = hub.unalias(doc)
        return 200, {"open": bool(hub.member_owns(member, doc) and hub.visible(member, doc))}
    if op in ROUTES:
        return relayed(handler, body)
    return 404, {}


# ── the client tiroir runs a page route as the member the channel names ───────

ROUTES = {"page": ("GET", "_page"), "mount": ("GET", "_mount"), "doc": ("GET", "_doc"), "writes": ("GET", "_writes")}
KEPT = ("Cache-Control", "Content-Security-Policy", "X-Content-Type-Options", "Referrer-Policy")      # the headers a relayed page keeps
SEEN = {"status": 404, "type": "json", "body": '{"error": "no such document"}', "nonce": None}       # a page that is not there, for every cause


def run(handler, member, method: str, route: str, path: str, query: dict, body: dict, mount: str = "") -> dict:
    """Run `handler.<route>` as `member` on a request made here, through the code a member's own request runs (`_unalias` first), and
    say what it answered as an envelope. A refusal 404 is the one `SEEN` for any cause; other refusals (a comment the
    member may not edit, a body that is not a comment) keep their status and sentence."""
    from .handler import Refuse, Req              # the handler imports this module
    req = Req(method, path, dict(query), {}, handler.hub.proxy.host, body=dict(body))
    req.member, req.member_id, req.route, req.via, req.auth, req.mount = member, member.id, route, "proxy", handler.hub.auth, mount
    try:
        handler._unalias(req)
        resp = getattr(handler, route)(req)
    except Refuse as r:
        return dict(SEEN) if r.status == 404 else {"status": r.status, "type": "json", "body": json.dumps({"error": r.message}), "nonce": None}
    kind = "html" if resp.headers.get("Content-Type", "").startswith("text/html") else "json"
    return {"status": resp.status, "type": kind, "body": resp.body.decode("utf-8", "replace"), "nonce": resp.nonce,
            "headers": {k: v for k, v in resp.headers.items() if k in KEPT or (resp.status == 302 and k == "Location")}}


def relayed(handler, body) -> tuple:
    """(200, envelope) of the `read` ops that run a page route (`ROUTES`)."""
    member, op, doc = served(handler.hub, body.get("as")), body.get("op"), body.get("doc")
    if member is None or not isinstance(doc, str) or not isinstance(body.get("mount", ""), str) or is_clients(doc):
        return 200, dict(SEEN)             # a `Clients` address is this hub's own read-through, never passed on to its clients (9.9)
    method, route = ROUTES[op]
    if route == "_page":
        return 200, run(handler, member, method, route, roots_mod.url_path(doc), {}, {}, body.get("mount", ""))
    return 200, run(handler, member, method, route, "/_/" + route[1:], {"doc": doc}, {}, body.get("mount", ""))


def comment_answer(handler, body) -> tuple:
    """(200, envelope) of the `comment` verb: the member's comment written on this hub, signed with their name here."""
    member, request = served(handler.hub, body.get("as")), body.get("request")
    if member is None or not isinstance(request, dict) or not isinstance(body.get("doc"), str) or is_clients(body["doc"]):
        return 200, dict(SEEN)
    if request.get("tell"):               # the channel opens reading and commenting, nothing that asks an agent here
        return 200, {"status": 400, "type": "json", "body": json.dumps({"error": "Tell is not offered on a comment from another tiroir"}),
                     "nonce": None}
    return 200, run(handler, member, "POST", "_comment", "/_/comment", {}, {**request, "doc": body["doc"]})
