"""A key or a cookie is good only from the hub's own user (SPEC 9.3).

The server asks who owns a connection once, when it accepts it (`peer.look`), and the handler judges every
request that carries a key or a cookie by that answer, before anything is read or done. These tests hand the
handler connections the server has already looked at, with the answer made on purpose; the last section runs
a real hub over a real socket."""
import http.client
import os

import pytest

from helpers import PLAN, hub_rows
from sheafmd import paths
from sheafmd.hub import peer, server
from sheafmd.hub.core import Hub
from sheafmd.hub.handler import Handler

ME = os.geteuid()
THEM = ME + 1
CLIENT, AT_HUB = ("127.0.0.1", 50000), ("127.0.0.1", 27419)
HTML = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"


def seen(uid=THEM, kind=peer.OTHER_USER, closed=None):
    """A connection the server looked at: the answer it got, and whether the caller has closed by now."""
    no = None if uid == ME else peer.Refusal(kind, "told to no one", f"found uid {uid}", uid if kind == peer.OTHER_USER else None)
    return peer.Conn(CLIENT, AT_HUB, True, no, (lambda: closed) if closed is not None else None)


@pytest.fixture
def handler(hub, work):
    f = work / "plan.md"
    f.write_text(PLAN, encoding="utf-8")
    hub.roots.for_document(f)
    return Handler(hub)


def ask(handler, hub, method, path, conn, how="key", accept=None, body=b""):
    headers = {"Host": f"127.0.0.1:{hub.port}"}
    if how == "key":
        headers["X-Sheaf-Key"] = hub.auth.key
    elif how == "cookie":
        headers["Cookie"] = f"{hub.auth.cookie_name}={hub.auth.cookie_value()}"
        headers["Origin"] = f"http://127.0.0.1:{hub.port}"
    if accept:
        headers["Accept"] = accept
    return handler.handle(method, path, headers, body, conn=conn)


# ── another user is refused ──────────────────────────────────────────────────

@pytest.mark.parametrize("how", ["key", "cookie"])
def test_a_key_or_a_cookie_from_another_user_is_refused_with_a_403_that_names_no_uid(handler, hub, how):
    r = ask(handler, hub, "GET", "/_/index.json", seen(), how)
    assert r.status == 403 and "Set-Cookie" not in r.headers
    said = r.json()["error"]
    assert not any(c.isdigit() for c in said) and "/proc" not in said and "/" not in said


def test_the_refusal_is_a_small_page_for_a_browser(handler, hub):
    r = ask(handler, hub, "GET", "/work/plan.md", seen(), "cookie", accept=HTML)
    assert r.status == 403 and r.headers["Content-Type"].startswith("text/html") and "Set-Cookie" not in r.headers
    assert str(THEM) not in r.text and "another user" in r.text


def test_the_signin_url_key_link_is_checked_too(handler, hub):
    r = ask(handler, hub, "GET", f"/_/open?key={hub.auth.key}&next=/work/plan.md", seen(), how=None, accept=HTML)
    assert r.status == 403 and "Set-Cookie" not in r.headers and "Location" not in r.headers


def test_root_is_not_the_hubs_own_user(handler, hub):
    if ME == 0:
        pytest.skip("root is the hub's own user here")
    assert ask(handler, hub, "GET", "/_/index.json", seen(0), "key").status == 403


def test_a_connection_the_hub_could_not_read_is_refused_not_let_through(handler, hub):
    r = ask(handler, hub, "GET", "/_/index.json", seen(kind=peer.UNKNOWN), "key")
    assert r.status == 403 and "could not tell" in r.json()["error"]


def test_the_row_names_both_uids_and_the_answer_names_neither(handler, hub):
    r = ask(handler, hub, "GET", "/_/index.json", seen(), "key")
    row = hub_rows("peer-refused")[-1]
    assert row["peer_uid"] == THEM and row["hub_uid"] == ME
    assert str(THEM) not in r.text


def test_refusals_in_a_loop_are_one_row_a_minute(handler, hub):
    for _ in range(5):
        assert ask(handler, hub, "GET", "/_/index.json", seen(), "key").status == 403
    assert len(hub_rows("peer-refused")) == 1


@pytest.mark.parametrize("accept", ["TEXT/HTML", "Text/Html;Q=0.5", "application/json, text/html;q=0.1"])
def test_the_refusal_page_goes_to_an_accept_that_names_html_in_any_case(handler, hub, accept):
    r = ask(handler, hub, "GET", "/work/plan.md", seen(), "cookie", accept=accept)
    assert r.status == 403 and r.headers["Content-Type"].startswith("text/html")


@pytest.mark.parametrize("accept", ["text/html;q=0", "text/html; q=0.0, application/json", "xtext/html"])
def test_an_accept_that_refuses_html_gets_the_json_refusal_not_the_page(handler, hub, accept):
    r = ask(handler, hub, "GET", "/work/plan.md", seen(), "cookie", accept=accept)
    assert r.status == 403 and r.headers["Content-Type"].startswith("application/json")


# ── what the check leaves alone ──────────────────────────────────────────────

def test_the_hubs_own_user_is_let_in(handler, hub):
    assert ask(handler, hub, "GET", "/_/index.json", seen(ME), "key").status == 200


def test_health_is_not_looked_up(handler, hub):
    assert ask(handler, hub, "GET", "/_/health", seen(), how=None).status == 200


def test_a_request_with_no_credential_is_the_401_it_always_was(handler, hub):
    assert ask(handler, hub, "GET", "/_/index.json", seen(), how=None).status == 401


def test_a_hub_that_does_not_check_lets_every_user_in_and_the_link_too(handler, hub):
    handler.peer_off = "this system gives the hub no way to see who owns a connection"
    assert ask(handler, hub, "GET", "/_/index.json", seen(), "key").status == 200
    nonce = hub.auth.mint_signin()
    assert ask(handler, hub, "GET", f"/_/open?nonce={nonce}&next=/work/plan.md", seen(), how=None).status == 303


def test_a_used_link_carries_the_limit_notice_when_the_check_is_off_at_start_up(handler, hub):
    from sheafmd.hub.handler import LINK_LIMIT
    handler.peer_off = "the owner of a loopback connection read as [], not the hub's own uid"
    r = ask(handler, hub, "GET", "/_/open?nonce=" + "0" * 32, seen(), how=None, accept="text/html")
    assert r.status == 401 and LINK_LIMIT in r.body.decode()


# ── a caller that closed first ───────────────────────────────────────────────

def test_a_caller_that_closed_before_the_hub_could_say_is_told_to_try_again_and_nothing_is_applied(handler, hub):
    before = len(hub.auth.signins) if hasattr(hub.auth, "signins") else None
    # A suite run as root cannot make a uid-0 caller that is not its own: there the hub could not tell.
    closed_caller = seen(0, closed=True) if ME else seen(kind=peer.UNKNOWN, closed=True)
    r = ask(handler, hub, "POST", "/_/signin", closed_caller, "key", body=b"{}")
    assert r.status == 503 and r.headers["Retry-After"] == "1" and "Set-Cookie" not in r.headers
    assert not hub_rows("peer-refused")
    if before is not None:
        assert len(hub.auth.signins) == before


@pytest.mark.parametrize("hub_uid", [0, 1000])
def test_a_caller_already_closed_when_the_hub_looks_is_never_let_through(monkeypatch, hub_uid):
    # A closed caller's socket is held by no process (inode 0) and reads as uid 0 over sock_diag; where
    # the hub is root, that uid is the hub's own, so the inode decides, not the uid.
    monkeypatch.setattr(os, "geteuid", lambda: hub_uid)
    monkeypatch.setattr(peer, "PLATFORM", "linux")
    monkeypatch.setattr(peer, "sockets", lambda conn: [peer.Socket(0, 0)])
    monkeypatch.setattr(peer, "closed", lambda sock: True)
    conn = peer.look(CLIENT, AT_HUB, object())
    assert conn.refusal is not None and conn.refusal.kind == peer.UNKNOWN and conn.closed()


@pytest.mark.parametrize("hub_uid", [0, 1000])
def test_a_caller_of_the_hubs_own_user_that_half_closes_is_not_turned_away(monkeypatch, hub_uid):
    # `nc -N` and some HTTP clients close their sending end after the request: the hub's socket leaves
    # ESTABLISHED, and the caller's own socket is still held by its owner, root included.
    monkeypatch.setattr(os, "geteuid", lambda: hub_uid)
    monkeypatch.setattr(peer, "PLATFORM", "linux")
    monkeypatch.setattr(peer, "sockets", lambda conn: [peer.Socket(hub_uid, 4242)])
    monkeypatch.setattr(peer, "closed", lambda sock: True)
    assert peer.look(CLIENT, AT_HUB, object()).refusal is None


def test_a_refusal_of_one_kind_does_not_hold_back_the_row_of_the_other(handler, hub):
    # The rows are throttled to one a minute for each kind: an unknown caller first does not hide,
    # for a minute, the row that names another user's uid.
    assert ask(handler, hub, "GET", "/_/index.json", seen(kind=peer.UNKNOWN), "key").status == 403
    assert ask(handler, hub, "GET", "/_/index.json", seen(THEM), "key").status == 403
    assert ask(handler, hub, "GET", "/_/index.json", seen(THEM + 1), "key").status == 403
    rows = hub_rows("peer-refused")
    assert len(rows) == 2 and [r.get("peer_uid") for r in rows] == [None, THEM]


def test_another_user_that_sends_and_closes_is_still_refused_and_leaves_its_row(handler, hub):
    r = ask(handler, hub, "GET", "/_/index.json", seen(THEM, closed=True), "key")
    assert r.status == 403 and "Set-Cookie" not in r.headers
    assert [row["peer_uid"] for row in hub_rows("peer-refused")] == [THEM]


def test_a_caller_still_connected_is_refused_not_told_to_try_again(handler, hub):
    assert ask(handler, hub, "GET", "/_/index.json", seen(closed=False), "key").status == 403


# ── over a real socket ───────────────────────────────────────────────────────

@pytest.fixture
def live(work):
    sock = server.bind(0)
    port = sock.getsockname()[1]
    hub = Hub(port=port, key=paths.ensure_key(), started_by="test")
    srv = server.HubServer(hub, sock)
    srv.start()
    conns = []

    def connect():
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.connect()
        conns.append(c)
        return c
    yield hub, srv, connect
    for c in conns:
        c.close()
    srv.close()


@pytest.mark.skipif(not peer.supported(), reason="the lookup is Linux")
def test_the_hubs_own_user_is_let_in_over_a_real_socket_on_every_request_of_the_connection(live):
    hub, srv, connect = live
    c = connect()
    for _ in range(2):
        c.request("GET", "/_/index.json", headers={"X-Sheaf-Key": hub.auth.key})
        r = c.getresponse()
        r.read()
        assert r.status == 200


@pytest.mark.skipif(not peer.supported(), reason="the lookup is Linux")
def test_the_server_asks_who_owns_a_connection_once_when_it_accepts_it(live, monkeypatch):
    hub, srv, connect = live
    asked = []
    real = peer.check
    monkeypatch.setattr(peer, "check", lambda conn: asked.append(conn) or real(conn))
    c = connect()
    for _ in range(3):
        c.request("GET", "/_/index.json", headers={"X-Sheaf-Key": hub.auth.key})
        c.getresponse().read()
    assert len(asked) == 1


@pytest.mark.skipif(not peer.supported(), reason="the lookup is Linux")
def test_a_socket_whose_caller_closed_reads_as_closed():
    import socket
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    cli = socket.socket()
    cli.connect(srv.getsockname())
    acc, _ = srv.accept()
    try:
        assert not peer.closed(acc)
        cli.close()
        for _ in range(100):
            if peer.closed(acc):
                break
            import time
            time.sleep(0.01)
        assert peer.closed(acc)
    finally:
        acc.close()
        srv.close()


# ── the start-up self-test ───────────────────────────────────────────────────

def test_a_hub_that_cannot_read_its_own_connection_starts_with_the_check_off_and_says_so(hub, monkeypatch, capsys):
    monkeypatch.setattr(peer, "startup", lambda: "the owner of a loopback connection read as [], not the hub's own uid")
    sock = server.bind(0)
    try:
        srv = server.HubServer(Hub(port=sock.getsockname()[1], key=paths.ensure_key(), started_by="test"), sock)
        assert srv.httpd.RequestHandlerClass.handler.peer_off
        assert "loopback" in hub_rows("peer-check-off")[-1]["error"]
        assert "does not check" in capsys.readouterr().err
    finally:
        sock.close()


def test_a_platform_with_no_way_to_read_owners_has_the_check_off(monkeypatch):
    monkeypatch.setattr(peer, "PLATFORM", "darwin")
    assert "darwin" in peer.startup()


def test_where_the_hub_can_read_its_own_connection_the_check_is_on():
    if not peer.supported():
        pytest.skip("Linux only")
    assert peer.startup() is None
