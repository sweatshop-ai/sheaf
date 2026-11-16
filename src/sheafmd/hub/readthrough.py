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

from . import roots as roots_mod
from . import sheaf_view

ROOT = "Clients"                # the reserved root name of the folder
NOTHING = {"rows": [], "tree": [], "more": {}}      # what a member with nothing to see there is told, and a member with no account


class NotReachable(Exception):
    """A client tiroir that did not answer: the view says so, and serves nothing older."""


class NoEmail(Exception):
    """The signed-in member has no e-mail on this tiroir, so no client tiroir can know who is asking."""


class Missing(Exception):
    """The client tiroir has no such page for this member: told as a page that is not there."""


def is_clients(address) -> bool:
    return isinstance(address, str) and (address == ROOT or address.startswith(ROOT + "/"))


def fold_rows(client: str, rows: list) -> list:
    """The rows `client`'s hub told, drawn under `Clients/<client>`: the address, URL, folder and root carry the prefix. Whose
    rows they are is the client hub's to say, so none of the owner's actions (Share, Keep, Archive, a session's way back)
    survives: the agency member is not the owner of a client page."""
    out = []
    for r in rows:
        r = {k: v for k, v in r.items() if k != "shared_from"}
        folder = "/".join(p for p in r["folder"].split("/") if p not in ("", ".", ".."))
        doc = "/".join(p for p in r["doc"].split("/") if p not in ("", ".", ".."))
        top = r["root"]
        out.append({**r, "doc": f"{ROOT}/{client}/{doc}", "url": roots_mod.url_path(f"{ROOT}/{client}/{doc}"),
                    "folder": f"{ROOT}/{client}/{folder}", "root": f"{ROOT}/{client}/{top}",
                    "own": False, "share": "", "kept": False, "archived": False, "session": "", "session_tip": "",
                    "session_link": None, "write": "", "write_tip": ""})
    return out


class Clients:
    """The client tiroirs of an agency tiroir (`[proxy.clients]`), and the one place that asks them."""

    def __init__(self, table: dict, call):
        self._table = dict(table)
        self._call = call

    def names(self) -> list:
        return sorted(self._table, key=str.casefold)

    def split(self, address):
        """(client, address on that hub) of `Clients/<client>/<address>`; None for anything that names no page of a configured client."""
        parts = address.split("/", 2) if isinstance(address, str) else []
        if len(parts) != 3 or parts[0] != ROOT or parts[1] not in self._table or not parts[2] or parts[2].startswith("/"):
            return None
        return parts[1], parts[2]

    def read(self, client: str, member, op: str, **fields) -> dict:
        """What `client`'s hub says to `op` for `member`. `as` is the member's own e-mail and nothing a caller wrote; a field named
        `as` or `role` in `fields` is dropped. No answer is `NotReachable` and nothing is kept for the next time."""
        return self._ask(client, member, "read", {"op": op, **fields}, op == "sheaf")

    def may_open(self, client: str, member, rest: str) -> bool:
        """Whether `member` may open the page at `rest` on `client`'s hub, as that hub says it. A client that does not answer, or
        refuses, is no."""
        try:
            return self.read(client, member, "open", doc=rest).get("open") is True
        except (NotReachable, NoEmail, Missing):
            return False

    def relay(self, client: str, member, op: str, doc: str, **fields) -> dict:
        """The envelope `{status, type, body, nonce}` of `client`'s hub for a page route (`page`, `mount`, `doc`, `writes`) run as
        `member`: `doc` is the address on that hub, `mount` the prefix its page is told under."""
        return self._ask(client, member, "read", {"op": op, "doc": doc, **fields}, False)

    def comment(self, client: str, member, doc: str, request: dict) -> dict:
        """The envelope of `client`'s hub for a comment write (`request` is the page's own body) run as `member`: it signs it."""
        return self._ask(client, member, "comment", {"doc": doc, "request": request}, False)

    def _ask(self, client, member, verb, fields, soft) -> dict:
        email = member.email
        if not email:
            raise NoEmail("this tiroir does not know your e-mail address, so a client tiroir cannot tell who is asking")
        body = {"as": email, **{k: v for k, v in fields.items() if k not in ("as", "role", "admin")}}
        try:
            status, answer = self._call(client, verb, body)
        except OSError as e:
            raise NotReachable(f"the client tiroir {client} is not reachable") from e
        if status == 200:
            return answer
        if soft:                 # a refusal is the answer of a member with nothing to see: no oracle for "has an account"
            return {k: type(v)() for k, v in NOTHING.items()}
        raise Missing("no such page")


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


def answer(handler, body) -> tuple:
    """(status, answer) of this hub, the client tiroir, to a `read` of the channel: `body` is `{as, op, ...}`. `as` is the only
    identity: the member it names, when they are an agency member here, is who the op runs as, through the code a member's own
    request runs. Anything else (no `as`, `*`, no member of that e-mail, two, a client member) is the answer of a member with
    nothing to see, with no status that tells whether an account exists. There is no op, field or scope that widens beyond
    that member."""
    hub, op = handler.hub, body.get("op")
    member = served(hub, body.get("as"))
    if op == "sheaf":
        if member is None:
            return 200, {k: type(v)() for k, v in NOTHING.items()}
        d = sheaf_view.data(hub, member, handler._titles)
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
            "headers": {k: v for k, v in resp.headers.items() if k in KEPT}}


def relayed(handler, body) -> tuple:
    """(200, envelope) of the `read` ops that run a page route (`ROUTES`)."""
    member, op, doc = served(handler.hub, body.get("as")), body.get("op"), body.get("doc")
    if member is None or not isinstance(doc, str) or not isinstance(body.get("mount", ""), str):
        return 200, dict(SEEN)
    method, route = ROUTES[op]
    if route == "_page":
        return 200, run(handler, member, method, route, roots_mod.url_path(doc), {}, {}, body.get("mount", ""))
    return 200, run(handler, member, method, route, "/_/" + route[1:], {"doc": doc}, {}, body.get("mount", ""))


def comment_answer(handler, body) -> tuple:
    """(200, envelope) of the `comment` verb: the member's comment written on this hub, signed with their name here."""
    member, request = served(handler.hub, body.get("as")), body.get("request")
    if member is None or not isinstance(request, dict) or not isinstance(body.get("doc"), str):
        return 200, dict(SEEN)
    return 200, run(handler, member, "POST", "_comment", "/_/comment", {}, {**request, "doc": body["doc"]})
