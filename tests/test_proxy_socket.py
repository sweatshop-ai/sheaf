"""The proxy socket's answers, through the handler in memory (SPEC 9.9 "Two listeners", "The member",
"Host and Origin", "The credential"; 18 Proxy mode). The proxy stands in as `front`: a request from
the proxy's account with `X-Sheaf-Member` set, as after a 2xx of the verifier. The same hub's
loopback port is `browser`, which never reads the member header."""
import pwd
import re

import pytest
from helpers import BEA, FRONT, hub_rows, page_meta
from sheafmd.source import md_hash

DOC = "work/plan.md"
URL = "/work/plan.md"
NOBODY = pwd.getpwnam("nobody").pw_uid

MEMBER_ROUTES = [("GET", URL), ("GET", "/work/"), ("GET", f"/_/live?doc={DOC}"), ("GET", f"/_/doc?doc={DOC}"),
                 ("GET", "/_/index.json"), ("POST", "/_/save"), ("POST", "/_/comment"), ("POST", "/_/seen"),
                 ("POST", "/_/export"), ("POST", "/_/diag"), ("POST", "/_/pin")]
NOT_HERE = [("GET", "/_/health"), ("GET", "/_/open?key=x&next=/"), ("GET", "/_/open?nonce=ab&next=/"),
            ("POST", "/_/mcp"), ("GET", "/_/mcp"), ("POST", "/_/ask"), ("POST", "/_/tell"), ("POST", "/_/cancel"),
            ("POST", "/_/jump"), ("GET", "/_/jobs"), ("POST", "/_/render"), ("POST", "/_/forget"), ("POST", "/_/stop"),
            ("POST", "/_/rotate"), ("POST", "/_/signin"), ("POST", "/_/restarting"), ("DELETE", "/_/restarting"),
            ("GET", "/_/nothing")]
EVERY = MEMBER_ROUTES + NOT_HERE


def body_for(method):
    return {"doc": DOC} if method == "POST" else None


# ── the connection: only the proxy's account (9.9 "Two listeners") ───────────

@pytest.mark.parametrize("method,path", EVERY)
def test_a_connection_of_another_account_gets_403_and_a_proxy_peer_row(front, plan, method, path):
    r = front.request(method, path, uid=NOBODY, body=body_for(method))
    assert r.status == 403 and r.json()["ok"] is False
    rows = hub_rows("proxy-peer")
    assert len(rows) == 1 and rows[0]["uid"] == NOBODY and rows[0]["endpoint"] == path.partition("?")[0]


def test_a_request_with_no_connection_to_read_is_refused_as_another_accounts(front, plan):
    assert front.get(URL, conn=False).status == 403
    assert hub_rows("proxy-peer")[0].get("uid") is None


def test_a_refused_connection_names_no_member_and_has_no_body_read(front, plan):
    read = []
    r = front.handler.handle("POST", "/_/save", {"Host": front.hub.proxy.host, "X-Sheaf-Member": BEA,
                                                 "Origin": FRONT, "Content-Length": "2"},
                             lambda: read.append(1) or b"{}", conn=None, via="proxy")
    assert r.status == 403 and read == []
    assert "member" not in hub_rows("proxy-peer")[0]


# ── Host and Origin, in place of 9.2 ─────────────────────────────────────────

@pytest.mark.parametrize("method,path", EVERY)
@pytest.mark.parametrize("host", ["127.0.0.1:27419", "chat.example.com:443", "chat.example.com.evil.example", ""])
def test_a_host_that_is_not_the_fronts_is_403_on_every_route(front, plan, method, path, host):
    r = front.request(method, path, host=host, body=body_for(method))
    assert r.status == 403


def test_the_row_of_a_wrong_host_names_the_member(front, plan):
    assert front.get(URL, host="other.example.com").status == 403
    assert [r.get("member") for r in hub_rows()] == [BEA]


def test_the_host_is_compared_without_case(front, plan):
    assert front.get(URL, host="Chat.Example.COM").status == 200


@pytest.mark.parametrize("method,path", [r for r in MEMBER_ROUTES if r[0] == "POST"])
@pytest.mark.parametrize("origin", [False, "null", "http://chat.example.com", "https://chat.example.com:8443",
                                    "https://other.example.com", "https://evil.chat.example.com",
                                    "http://127.0.0.1:27419", "https://chat.example.com/"])
def test_every_post_without_the_fronts_origin_is_403(front, plan, method, path, origin):
    before = plan.read_text()
    r = front.post(path, {"doc": DOC, "hash": "x", "edits": []}, origin=origin)
    assert r.status == 403
    assert plan.read_text() == before


def test_a_post_with_the_fronts_origin_passes(front, plan):
    assert front.post("/_/seen", {"doc": DOC, "id": "c1", "count": 1}).status == 200


# ── the member header (9.9 "The member", 9.3's order) ────────────────────────

@pytest.mark.parametrize("method,path", EVERY)
def test_no_member_header_is_401_before_the_route_and_the_method(front, plan, method, path):
    r = front.request(method, path, member="", body=body_for(method))
    assert r.status == 401


def test_a_page_without_a_member_says_to_sign_in_to_the_front_again(front, plan):
    r = front.get(URL, member="")
    assert r.status == 401 and r.headers["Content-Type"].startswith("text/html")
    assert "Sign in to this site again" in r.text and "sheaf open" not in r.text and "signin-url" not in r.text
    api = front.get(f"/_/doc?doc={DOC}", member="")
    assert api.headers["Content-Type"] == "application/json" and api.json()["error"] == "not signed in"


@pytest.mark.parametrize("method,path", EVERY)
def test_a_member_not_in_the_table_is_403_before_the_route(front, plan, method, path):
    r = front.request(method, path, member="1b4e28ba-2fa1-11d2-883f-0016d3cca427", body=body_for(method))
    assert r.status == 403


def test_a_member_not_in_the_table_gets_the_small_page_or_its_sentence(front, plan):
    stranger = "1b4e28ba-2fa1-11d2-883f-0016d3cca427"
    page = front.get(URL, member=stranger)
    assert page.headers["Content-Type"].startswith("text/html")
    assert "This account has no documents on this hub." in page.text
    api = front.get(f"/_/doc?doc={DOC}", member=stranger)
    assert api.json()["error"] == "This account has no documents on this hub."
    assert {r.get("member") for r in hub_rows()} == {stranger}


def test_the_hub_cookie_and_the_key_are_no_credential_on_the_socket(front, plan):
    auth = front.hub.auth
    signed = {"Cookie": f"{auth.cookie_name}={auth.cookie_value()}", "X-Sheaf-Key": auth.key}
    assert front.get(URL, member="", headers=signed).status == 401
    assert front.get("/_/jobs", headers=signed).status == 404
    assert front.post("/_/render", {"path": str(plan)}, headers=signed).status == 404


# ── the routes a member has ──────────────────────────────────────────────────

@pytest.mark.parametrize("method,path", NOT_HERE)
def test_health_open_mcp_ask_tell_cancel_and_the_key_routes_are_404_on_the_socket(front, plan, method, path):
    r = front.request(method, path, body=body_for(method))
    assert r.status == 404 and r.json()["ok"] is False


def test_a_member_route_with_another_method_is_405(front, plan):
    r = front.post(f"/_/doc?doc={DOC}", {})
    assert r.status == 405 and r.headers["Allow"] == "GET"
    assert front.request("PUT", URL).status == 405


def test_a_member_gets_their_page(front, plan):
    r = front.get(URL)
    assert r.status == 200 and "Plan" in r.text


def test_a_member_pins_the_version_their_page_holds_as_the_hubs_person_does(front, plan):
    """A member's page holds a reload for a form as any page does, and saves and replies after it (7.4)."""
    assert front.post("/_/pin", {"doc": DOC, "hash": md_hash(plan.read_text(encoding="utf-8"))}).status == 200
    assert front.post("/_/pin", {"doc": DOC, "hash": "0" * 16}).status == 409


@pytest.mark.parametrize("method,path", MEMBER_ROUTES + NOT_HERE)
def test_no_answer_on_the_socket_sets_a_cookie(front, plan, method, path):
    for member in (BEA, "", "1b4e28ba-2fa1-11d2-883f-0016d3cca427"):
        r = front.request(method, path, member=member, body=body_for(method))
        assert "Set-Cookie" not in r.headers


def test_frame_ancestors_is_self_on_the_socket_and_none_on_the_port(front, browser, plan):
    on_socket = front.get(URL).headers["Content-Security-Policy"]
    on_port = browser.get(URL).headers["Content-Security-Policy"]
    assert on_socket.endswith("frame-ancestors 'self'") and on_port.endswith("frame-ancestors 'none'")
    rest = lambda csp: re.sub(r"'nonce-[^']+'", "", csp).rpartition(";")[0]
    assert rest(on_socket) == rest(on_port)                  # the rest of 9.5 holds there as written
    assert front.get(URL, member="").headers["Content-Security-Policy"].endswith("frame-ancestors 'self'")


def test_every_row_a_socket_request_writes_names_the_member(front, plan):
    front.get("/_/nothing")
    front.post("/_/diag", {"kind": "js-error", "doc": DOC, "member": "someone else"})
    rows = [r for r in __import__("sheafmd").diagnostics.read() if r["kind"] in ("unknown-404", "js-error")]
    assert [(r["source"], r["member"]) for r in rows] == [("hub", BEA), ("page", BEA)]


# ── the loopback port never reads the member header ──────────────────────────

def test_the_loopback_port_never_reads_the_member_header(front, browser, plan):
    with_header = browser.get(URL, headers={"X-Sheaf-Member": BEA})
    assert with_header.status == 200
    assert page_meta(with_header.text)["me"] == page_meta(browser.get(URL).text)["me"] == "Ada"
    assert browser.get(URL, cookie=False, headers={"X-Sheaf-Member": BEA}).status == 401
    browser.post("/_/diag", {"kind": "js-error", "doc": DOC, "member": BEA})
    assert "member" not in [r for r in __import__("sheafmd").diagnostics.read() if r["kind"] == "js-error"][0]
