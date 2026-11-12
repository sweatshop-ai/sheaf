"""Who may call a route, and the token row.

The route table says what each route accepts (a cookie, the key, an MCP token, a raw body); the
handler holds no path or kind of its own beside it. These tests state that, and pin what a caller
is told when it is refused, so a change to the table cannot change who is let in."""
import json

import pytest

from helpers import door, rpc
from sheafmd import paths
from sheafmd.hub import auth
from sheafmd.hub.handler import COOKIE, EITHER, KEY, DOOR, OPEN, Handler
from sheafmd.hub.state import TokenError, TokenRow, Tokens


@pytest.fixture
def token(hub):
    return Tokens().add("codex", "Codex")


# ── the table ────────────────────────────────────────────────────────────────

def all_routes(handler):
    return [(m, p, name, who) for p, methods in handler.routes.items()
            for m, (name, who, _fn) in methods.items()]


def test_only_the_door_accepts_a_token_and_reads_its_own_body(browser):
    door_routes = [(m, p) for m, p, _, who in all_routes(browser.handler)
                   if who is not OPEN and (who.token or who.raw_body)]
    assert door_routes == [("POST", "/_/mcp")]
    who = browser.handler.routes["/_/mcp"]["POST"][1]
    assert who is DOOR and who.token and who.raw_body


def test_the_other_kinds_take_no_token_and_no_raw_body():
    for who in (COOKIE, EITHER, KEY):
        assert not who.token and not who.raw_body
    assert "token" not in COOKIE and "token" not in EITHER and "token" not in KEY


def test_each_kind_names_the_credentials_it_accepts():
    assert "cookie" in COOKIE and "key" not in COOKIE
    assert "cookie" in EITHER and "key" in EITHER
    assert "key" in KEY and "cookie" not in KEY
    assert "key" in DOOR and "token" in DOOR and "cookie" not in DOOR


def test_a_member_of_the_proxy_socket_is_offered_the_cookie_routes_only():
    assert Handler._for_members(("seen", COOKIE, None)) is True
    assert Handler._for_members(("doc", EITHER, None)) is True
    assert Handler._for_members(("jobs", KEY, None)) is False
    assert Handler._for_members(("mcp", DOOR, None)) is False


# ── what a refused caller is told ────────────────────────────────────────────

def test_a_route_of_the_key_tells_a_cookie_it_needs_the_key(browser):
    res = browser.request("POST", "/_/stop", body={}, key=False, cookie=True)
    assert res.status == 403
    assert res.json() == {"ok": False, "error": "this needs the hub key"}


def test_the_door_tells_a_cookie_it_needs_the_key_or_a_token(browser):
    res = door(browser, rpc("ping"), key=False, cookie=True)
    assert res.status == 403
    assert res.json() == {"ok": False, "error": "this needs the hub key or an MCP token"}


def test_a_route_of_the_cookie_tells_the_key_it_needs_a_signed_in_browser(browser):
    res = browser.request("POST", "/_/seen", body={}, key=True, cookie=False)
    assert res.status == 403
    assert res.json() == {"ok": False, "error": "this needs a browser that is signed in to the hub"}


def test_a_token_on_a_route_of_the_key_is_401_and_names_no_scheme(browser, token):
    res = browser.request("GET", "/_/jobs", key=False, cookie=False,
                          headers={"Authorization": f"Bearer {token}"})
    assert res.status == 401 and "WWW-Authenticate" not in res.headers
    assert res.json() == {"ok": False, "error": "not signed in"}


@pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH"])
def test_a_good_token_on_a_method_the_door_lacks_is_405_with_allow(browser, token, method):
    res = browser.request(method, "/_/mcp", key=False, cookie=False,
                          headers={"Authorization": f"Bearer {token}"})
    assert res.status == 405 and res.headers["Allow"] == "POST"


def test_a_bad_token_on_a_method_the_door_lacks_is_401_naming_the_scheme(browser):
    res = browser.request("PUT", "/_/mcp", key=False, cookie=False,
                          headers={"Authorization": "Bearer sheaf_mcp_" + "A" * 43})
    assert res.status == 401 and res.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("row", [{}, {"name": None}, {"name": 7}, {"name": ["codex"]},
                                 {"name": ""}, {"name": " "}, {"name": " \t\n"},
                                 {"name": "\u200b"}, {"name": "\ufeff"}, {"name": "a b"}, {"name": " codex"},
                                 {"name": "codex\n"}, {"name": "caf\u00e9"}, {"name": "x" * 41}],
                         ids=["no-name", "null", "number", "list", "empty", "space", "whitespace",
                              "zero-width", "bom", "inner-space", "leading-space", "trailing-newline",
                              "non-ascii", "41-chars"])
def test_a_row_with_the_right_hash_and_no_usable_name_is_refused_like_an_unknown_token(browser, row):
    secret = "sheaf_mcp_" + "C" * 43
    entry = {"sha256": auth.token_hash(secret), "display": "Codex",
             "created": "2026-10-22T00:00:00+0000", "last_used": None, "write": False, **row}
    (paths.state_dir() / "tokens.json").write_text(json.dumps([entry]), encoding="utf-8")
    assert Tokens().verify(secret) is None
    res = door(browser, rpc("ping"), token=secret)
    unknown_res = door(browser, rpc("ping"), token="sheaf_mcp_" + "D" * 43)
    assert res.status == unknown_res.status == 401
    assert res.headers.get("WWW-Authenticate") == unknown_res.headers.get("WWW-Authenticate")
    assert res.body == unknown_res.body


@pytest.mark.parametrize("name", ["", " ", "\t", "\n", " a", "a b"],
                         ids=["empty", "space", "tab", "newline", "leading-space", "inner-space"])
def test_add_cannot_make_a_token_with_an_empty_or_blank_name(hub, name):
    with pytest.raises(TokenError):
        Tokens().add(name)
    assert Tokens().list() == []


# ── the token row ────────────────────────────────────────────────────────────

def test_verify_hands_back_a_token_row_without_its_hash(hub):
    t = Tokens()
    token = t.add("writer", "Writer", write=True)
    got = t.verify(token)
    assert isinstance(got, TokenRow)
    assert (got.name, got.display, got.write) == ("writer", "Writer", True)
    assert not hasattr(got, "sha256")


def test_list_hands_back_token_rows_with_their_stamps(hub):
    t = Tokens()
    t.add("codex")
    [row] = t.list()
    assert isinstance(row, TokenRow)
    assert (row.name, row.display, row.write, row.last_used) == ("codex", "codex", False, None)
    assert len(row.created_text) == 16 and row.created_text == row.created[:16]
    assert row.last_used_text == "never"


def test_a_used_token_shows_when_it_was_last_used(hub):
    t = Tokens()
    token = t.add("codex")
    t.verify(token)
    [row] = t.list()
    assert row.last_used_text == row.last_used[:16] != "never"


def test_a_token_row_is_frozen():
    row = TokenRow("codex", "Codex", False, "2026-10-22T09:00:00+0200", None)
    with pytest.raises(AttributeError):
        row.write = True


@pytest.mark.parametrize("entry", [None, 5, "codex", ["codex"], {"display": "x"}, {"name": 7}])
def test_an_entry_that_is_not_a_named_token_is_no_row(entry):
    assert TokenRow.of(entry) is None
