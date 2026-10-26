"""The contract of proxy mode end to end (SPEC 9.9 "The proxy's part", "The verifier"; 18 Proxy mode):
a stub proxy and a stub verifier, each a small HTTP server on a loopback port, in front of a hub
on a real proxy socket. The proxy removes the browser's `X-Sheaf-Member`, asks the verifier, sets
the header only from its 2xx, removes `Cookie` and `Authorization`, and passes `Host` and `Origin`
on; the verifier reads the front's session from the `token` cookie only. The other proxy tests
stand in for both at the handler's edge (`front`); these show that a proxy and a verifier that
keep 9.9 give the hub that header and nothing else. A browser here is http.client on the stub
proxy's port, sending the front's Host, as a browser on the front's origin does."""
import base64
import http.client
import json
import re
import threading
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from helpers import BEA, CAL, FRONT, UnixHTTP, hub_rows

import sheafmd.comments as rdc
from sheafmd.hub import handler
from sheafmd.source import md_hash

DOC = "work/plan.md"
JWT = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


def jwt(sub: str) -> str:
    """A value of the shape of the front's session token: three base64url parts."""
    part = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f'{part({"alg": "HS256", "typ": "JWT"})}.{part({"id": sub})}.c2lnbmF0dXJl'


@dataclass
class StubFront:
    """What the verifier asks: the front's users (id -> role) and its sessions (token -> id)."""
    users: dict = field(default_factory=lambda: {BEA: "user", CAL: "user"})
    sessions: dict = field(default_factory=lambda: {jwt("bea"): BEA, jwt("cal"): CAL})
    up: bool = True


def verifier(front: StubFront):
    """9.9 "The verifier": the session from the `token` cookie only; an `sk-` key or a value that is
    not a JWT, an unknown session and a `pending` user get 401; a front that cannot be asked, 503.
    It keeps no answers, so a session the front has ended is refused at its next request."""
    class Verifier(BaseHTTPRequestHandler):
        def do_GET(self):
            jar = SimpleCookie(self.headers.get("Cookie", ""))
            token = jar["token"].value if "token" in jar else ""
            if not token or token.startswith("sk-") or not JWT.fullmatch(token):
                return self._answer(401)
            if not front.up:
                return self._answer(503)
            who = front.sessions.get(token)
            if who is None or front.users.get(who) in (None, "pending"):
                return self._answer(401)
            self._answer(200, who)

        def _answer(self, status, member=None):
            body = f"the verifier: {status}".encode()
            self.send_response(status)
            if member:
                self.send_header("X-Sheaf-Member", member)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    return Verifier


def proxy(verifier_port: int, socket_path):
    """9.9 "The proxy's part", in Caddy's order inside one `route`: `request_header -X-Sheaf-Member`,
    `forward_auth` with `copy_headers X-Sheaf-Member`, then `reverse_proxy` to the proxy socket
    with `header_up -Cookie` and `header_up -Authorization`; Host and Origin as the browser sent them."""
    class Proxy(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            self._pass()

        def do_POST(self):
            self._pass()

        def _pass(self):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            sent = {k: v for k, v in self.headers.items() if k.lower() != "x-sheaf-member"}
            ask = http.client.HTTPConnection("127.0.0.1", verifier_port, timeout=10)
            ask.request("GET", "/verify", headers={**sent, "X-Forwarded-Method": self.command,
                                                   "X-Forwarded-Uri": self.path})
            said = ask.getresponse()
            if not 200 <= said.status < 300:      # any other answer goes back; the hub never sees it
                return self._answer(said.status, said.getheaders(), said.read())
            member = said.getheader("X-Sheaf-Member")
            ask.close()
            if member:
                sent["X-Sheaf-Member"] = member
            sent = {k: v for k, v in sent.items() if k.lower() not in ("cookie", "authorization")}
            hub = UnixHTTP(socket_path, timeout=30)
            hub.request(self.command, self.path, body=body or None, headers=sent)
            got = hub.getresponse()
            self._answer(got.status, got.getheaders(), got.read())
            hub.close()

        def _answer(self, status, headers, body):
            self.send_response(status)
            for k, v in headers:
                if k.lower() not in ("content-length", "transfer-encoding", "connection"):
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    return Proxy


@dataclass
class Answer:
    status: int
    headers: http.client.HTTPMessage
    body: bytes

    def json(self):
        return json.loads(self.body)


class Edge:
    """The browser's side: requests to the stub proxy with the front's Host, and what the hub got."""

    def __init__(self, hub, port, front, seen):
        self.hub, self.port, self.front, self.seen = hub, port, front, seen

    def request(self, method, path, *, session=None, body=None, headers=None, origin=FRONT):
        h = {"Host": self.hub.proxy.host}
        if session:
            h["Cookie"] = f"theme=dark; token={session}"
        if method == "POST" and origin:
            h["Origin"] = origin
        data = None if body is None else json.dumps(body).encode()
        if data is not None:
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        out = Answer(r.status, r.headers, r.read())
        c.close()
        return out


@pytest.fixture
def edge(proxy_served, monkeypatch):
    """A stub verifier and a stub proxy in front of `proxy_served`'s hub; `edge.seen` holds the
    headers of each request the hub was handed on its proxy socket."""
    hub = proxy_served
    seen = []
    handle = handler.Handler.handle

    def spy(self, method, target, headers, body=b"", conn=None, via="port"):
        if via == "proxy":
            seen.append((method, target, {str(k).lower(): str(v) for k, v in headers.items()}))
        return handle(self, method, target, headers, body, conn=conn, via=via)

    monkeypatch.setattr(handler.Handler, "handle", spy)
    front = StubFront()
    servers = [ThreadingHTTPServer(("127.0.0.1", 0), verifier(front))]
    servers.append(ThreadingHTTPServer(("127.0.0.1", 0), proxy(servers[0].server_address[1], hub.proxy.socket)))
    for s in servers:
        s.daemon_threads = True
        threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()
    yield Edge(hub, servers[1].server_address[1], front, seen)
    for s in servers:
        s.shutdown()
        s.server_close()


def comment(edge, session, **kw):
    md = edge.hub.roots.resolve(DOC).read_text(encoding="utf-8")
    blk, s, e = rdc.find_quote(md, "Second paragraph")
    return edge.request("POST", "/_/comment", session=session, **kw, body={
        "doc": DOC, "op": "add", "hash": md_hash(md), "block": blk, "start": s, "end": e,
        "quote": "Second paragraph", "body": "Why pears?"})


def test_a_signed_in_browser_gets_its_page_and_its_comment_is_signed_with_the_members_name(edge, plan):
    page = edge.request("GET", f"/{DOC}", session=jwt("bea"))
    assert page.status == 200 and page.headers["Content-Type"].startswith("text/html")
    r = comment(edge, jwt("bea"))
    assert r.status == 200
    assert [c.by for c in rdc.parse(plan.read_text(encoding="utf-8")).comments] == ["Bea"]
    assert page.headers.get("Set-Cookie") is None and r.headers.get("Set-Cookie") is None
    # What the hub was handed: the verifier's member, the browser's Host and Origin, no session.
    assert [(m, h["x-sheaf-member"], h["host"], h.get("origin")) for m, _, h in edge.seen] == [
        ("GET", BEA, "chat.example.com", None), ("POST", BEA, "chat.example.com", FRONT)]
    assert not any("cookie" in h or "authorization" in h for _, _, h in edge.seen)


def test_a_member_header_the_browser_sends_is_replaced_by_the_verifiers(edge, plan, other):
    (other / "notes.md").write_text("# Notes\n", encoding="utf-8")
    edge.hub.roots.for_document(other / "notes.md")
    got = edge.request("GET", f"/{DOC}", session=jwt("cal"), headers={"X-Sheaf-Member": BEA})
    assert got.status == 404                      # Cal's session; Bea's document is not Cal's
    assert edge.request("GET", "/other/notes.md", session=jwt("cal"), headers={"X-Sheaf-Member": BEA}).status == 200
    assert [h["x-sheaf-member"] for _, _, h in edge.seen] == [CAL, CAL]


@pytest.mark.parametrize("case", ["no session", "an sk- key", "not a JWT", "a session the front does not know",
                                  "a pending user", "the session in Authorization only"])
def test_a_browser_the_verifier_refuses_gets_its_401_and_the_hub_sees_nothing(edge, plan, case):
    session, headers = {
        "no session": (None, {}),
        "an sk- key": ("sk-0123456789abcdef", {}),
        "not a JWT": ("opaque-session-value", {}),
        "a session the front does not know": (jwt("eve"), {}),
        "a pending user": (jwt("bea"), {}),
        "the session in Authorization only": (None, {"Authorization": f"Bearer {jwt('bea')}"}),
    }[case]
    if case == "a pending user":
        edge.front.users[BEA] = "pending"
    rows = len(hub_rows())
    before = plan.read_text(encoding="utf-8")
    headers = {"X-Sheaf-Member": BEA, **headers}          # and it names a member itself
    for method, path in (("GET", f"/{DOC}"), ("POST", "/_/comment")):
        r = edge.request(method, path, session=session, headers=headers, body={"doc": DOC} if method == "POST" else None)
        assert (r.status, r.body) == (401, b"the verifier: 401")
    assert edge.seen == [] and len(hub_rows()) == rows
    assert plan.read_text(encoding="utf-8") == before


def test_a_session_the_front_has_ended_is_refused_at_its_next_request(edge, plan):
    assert edge.request("GET", f"/{DOC}", session=jwt("bea")).status == 200
    del edge.front.sessions[jwt("bea")]                  # signed out at the front
    assert edge.request("GET", f"/{DOC}", session=jwt("bea")).status == 401
    assert len(edge.seen) == 1


def test_when_the_front_cannot_be_asked_the_browser_gets_503_and_the_hub_sees_nothing(edge, plan):
    edge.front.up = False
    r = edge.request("GET", f"/{DOC}", session=jwt("bea"), headers={"X-Sheaf-Member": BEA})
    assert (r.status, r.body) == (503, b"the verifier: 503") and r.headers.get("X-Sheaf-Member") is None
    assert edge.seen == []


@pytest.mark.parametrize("origin", ["https://notes.example.com", "http://chat.example.com", None])
def test_a_post_from_another_origin_gets_the_hubs_403_and_writes_nothing(edge, plan, origin):
    before = plan.read_text(encoding="utf-8")
    r = comment(edge, jwt("bea"), origin=origin)
    assert r.status == 403 and r.json()["error"] == "this request did not come from the front's own page"
    assert plan.read_text(encoding="utf-8") == before
    assert [h["x-sheaf-member"] for _, _, h in edge.seen] == [BEA]
    assert hub_rows()[-1]["member"] == BEA
