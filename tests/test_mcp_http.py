"""The MCP door over HTTP, in memory: `POST /_/mcp` through the handler, no socket (SPEC 12, 9.7).

Protocol and authentication here; the four tools are in test_mcp_tools.py, the stdio transport in
test_mcp_stdio.py."""
import json

import pytest

import sheafmd.comments as rdc
from helpers import comment, door, rpc
from sheafmd import __version__, diagnostics
from sheafmd.hub import auth
from sheafmd.hub.handler import MAX_BODY
from sheafmd.hub.state import Tokens

INSTRUCTIONS = (
    "sheaf keeps comment threads inside markdown files. Use `threads` to read what was asked on "
    "a document, `reply` to answer (role `action` after you acted on a Tell, `answer` when you "
    "only answer), and `resolve` when a thread is done. A Tell from sheaf names the document and "
    "the comment id. Where you may work on pages, `read` gives a document's text and its hash, "
    "`create` makes a new page and `update` replaces the text of one, given the hash you read it "
    "with; keep every comment in the text you send.")


def result(res):
    assert res.status == 200, res.text
    assert res.headers["Content-Type"] == "application/json"
    got = res.json()
    assert got["jsonrpc"] == "2.0" and "error" not in got, got
    return got["result"]


def error(res, status, code):
    assert res.status == status, res.text
    got = res.json()
    assert got["jsonrpc"] == "2.0" and got["error"]["code"] == code, got
    assert isinstance(got["error"]["message"], str) and got["error"]["message"]
    return got


@pytest.fixture
def token(hub):
    return Tokens().add("codex", "Codex")


# ── initialize, ping, notifications ──────────────────────────────────────────

@pytest.mark.parametrize("asked", ["2025-06-18", "2025-03-26", "2024-11-05"])
def test_initialize_answers_the_version_the_client_asked_when_it_is_one_we_speak(browser, asked):
    got = result(door(browser, rpc("initialize", {"protocolVersion": asked, "capabilities": {},
                                                  "clientInfo": {"name": "x", "version": "1"}})))
    assert got["protocolVersion"] == asked
    assert got["capabilities"] == {"tools": {}}
    assert got["serverInfo"] == {"name": "sheaf", "version": __version__}
    assert got["instructions"] == INSTRUCTIONS


@pytest.mark.parametrize("params", [{"protocolVersion": "2030-01-01"}, {"protocolVersion": 5},
                                    {}, None])
def test_initialize_answers_the_newest_version_for_any_other_ask(browser, params):
    got = result(door(browser, rpc("initialize", params)))
    assert got["protocolVersion"] == "2025-06-18"


def test_ping_answers_an_empty_result_and_keeps_the_id(browser):
    res = door(browser, rpc("ping", id="abc"))
    assert result(res) == {} and res.json()["id"] == "abc"


@pytest.mark.parametrize("message", [
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 3}},
    {"jsonrpc": "2.0", "method": "no/such/notification"},
    {"jsonrpc": "2.0", "id": 4, "result": {}},                       # a reply to nothing we sent
    {"jsonrpc": "2.0", "id": 5, "error": {"code": -32601, "message": "no"}},
])
def test_a_message_with_nothing_to_answer_gets_202_and_no_body(browser, message):
    res = door(browser, message)
    assert res.status == 202 and res.body == b""


def test_the_asked_for_event_stream_is_ignored(browser):
    res = door(browser, rpc("ping"), headers={"Accept": "text/event-stream"})
    assert result(res) == {} and res.stream is None


# ── tools/list ───────────────────────────────────────────────────────────────

def test_tools_list_names_the_seven_tools_each_with_a_schema(browser):
    tools = {t["name"]: t for t in result(door(browser, rpc("tools/list")))["tools"]}
    assert sorted(tools) == ["create", "documents", "read", "reply", "resolve", "threads", "update"]
    for t in tools.values():
        assert t["description"] and t["inputSchema"]["type"] == "object"
        assert t["inputSchema"]["additionalProperties"] is False
    req = {n: sorted(t["inputSchema"].get("required", [])) for n, t in tools.items()}
    assert req == {"documents": [], "threads": ["doc"], "reply": ["doc", "id", "text"],
                   "resolve": ["doc", "id"], "read": ["doc"], "create": ["doc", "text"],
                   "update": ["doc", "expected_hash", "text"]}
    props = tools["reply"]["inputSchema"]["properties"]
    assert props["role"]["enum"] == ["answer", "action"] and props["resolve"]["type"] == "boolean"
    assert tools["threads"]["inputSchema"]["properties"]["status"]["enum"] == ["open", "resolved", "all"]
    assert tools["documents"]["inputSchema"]["properties"]["open_only"]["type"] == "boolean"


def test_the_three_tools_that_only_read_say_so_and_the_four_that_write_say_nothing(browser):
    tools = {t["name"]: t for t in result(door(browser, rpc("tools/list")))["tools"]}
    assert {n: t.get("annotations") for n, t in tools.items()} == {
        "documents": {"readOnlyHint": True}, "threads": {"readOnlyHint": True},
        "read": {"readOnlyHint": True}, "reply": None, "resolve": None, "create": None, "update": None}


def test_a_tool_the_door_does_not_have_is_an_invalid_params_error(browser):
    error(door(browser, rpc("tools/call", {"name": "save", "arguments": {}})), 200, -32602)


def test_that_error_says_what_the_door_has_and_calls_it_the_door_not_a_server(browser):
    """GLOSSARY: MCP door, avoid "MCP server"; the agent reads this message."""
    message = error(door(browser, rpc("tools/call", {"name": "save", "arguments": {}})),
                    200, -32602)["error"]["message"]
    assert all(tool in message for tool in ("documents", "threads", "reply", "resolve"))
    assert "server" not in message.lower()


@pytest.mark.parametrize("params", [None, {}, {"name": 5}, []])
def test_a_call_without_a_tool_name_is_an_invalid_params_error(browser, params):
    error(door(browser, rpc("tools/call", params)), 200, -32602)


def test_an_unknown_method_keeps_the_id(browser):
    got = error(door(browser, rpc("resources/list", id=9)), 200, -32601)
    assert got["id"] == 9


# ── what is not a message ────────────────────────────────────────────────────

def test_a_batch_is_an_invalid_request(browser):
    got = error(door(browser, [rpc("ping", id=1), rpc("ping", id=2)]), 400, -32600)
    assert got["id"] is None


@pytest.mark.parametrize("message", [5, "ping", None, {"method": "ping", "id": 1},
                                     {"jsonrpc": "1.0", "method": "ping", "id": 1},
                                     {"jsonrpc": "2.0", "method": 7, "id": 1},
                                     {"jsonrpc": "2.0", "method": "ping", "id": [1]},
                                     {"jsonrpc": "2.0", "method": "ping", "params": 5, "id": 1}])
def test_a_message_that_is_not_json_rpc_is_an_invalid_request(browser, message):
    error(door(browser, raw=json.dumps(message).encode()), 400, -32600)


@pytest.mark.parametrize("raw", [b"{", b"not json", b"\xff\xfe"])
def test_text_that_is_not_json_is_a_parse_error(browser, raw):
    error(door(browser, raw=raw), 400, -32700)


def test_an_empty_body_is_a_parse_error(browser):
    error(door(browser, raw=b" "), 400, -32700)


def test_a_body_over_the_limit_is_413(browser):
    assert door(browser, raw=b'{"jsonrpc": "2.0", "method": "' + b"x" * (MAX_BODY + 1) + b'"}').status == 413


def test_get_is_405_and_says_post(browser):
    res = browser.request("GET", "/_/mcp", key=True, cookie=False)
    assert res.status == 405 and res.headers["Allow"] == "POST"


def test_get_with_a_token_is_405_and_says_post(browser, token):
    res = browser.request("GET", "/_/mcp", key=False, cookie=False,
                          headers={"Authorization": f"Bearer {token}"})
    assert res.status == 405 and res.headers["Allow"] == "POST"


@pytest.mark.parametrize("method,path", [("GET", "/_/mcp"), ("PUT", "/_/mcp"), ("DELETE", "/_/mcp"),
                                         ("GET", "/_/save"), ("POST", "/_/nothing")])
def test_a_caller_with_no_credential_is_401_before_any_405_or_404(browser, method, path):
    res = browser.request(method, path, key=False, cookie=False)
    assert res.status == 401 and "Allow" not in res.headers
    assert res.json() == {"ok": False, "error": "not signed in"}


# ── who may call (9.3, 9.7) ──────────────────────────────────────────────────

def test_the_key_with_a_name_opens_the_door(browser):
    assert result(door(browser, rpc("ping"), as_name="Claude")) == {}


def test_a_token_opens_the_door(browser, token):
    assert result(door(browser, rpc("ping"), token=token)) == {}


def reply_as(browser, **kw):
    """The `reply` tool on c1 of plan.md, through `door` (its keywords say who calls)."""
    return door(browser, rpc("tools/call", {"name": "reply", "arguments": {
        "doc": "work/plan.md", "id": "c1", "text": "Done."}}), **kw)


def signed(plan):
    return rdc.parse(plan.read_text(encoding="utf-8")).by_id("c1").replies[-1].by


@pytest.mark.parametrize("why,name", [
    ("no header", None), ("an empty one", ""), ("blanks only", "   "),
    ("encoded blanks only", "%20%09"), ("control characters only", "%00%07"),
])
def test_the_key_without_a_name_is_refused_and_nothing_is_signed(browser, plan, why, name):
    comment(plan)
    before = plan.read_bytes()
    res = reply_as(browser, as_name=name)
    assert res.status == 400, why
    got = res.json()
    assert got["ok"] is False and "X-Sheaf-As" in got["error"]
    assert plan.read_bytes() == before


def test_the_key_without_a_name_is_refused_before_its_body_is_read(browser):
    read = []
    head = {"Host": f"127.0.0.1:{browser.hub.port}", "X-Sheaf-Key": browser.hub.auth.key,
            "Content-Length": "30"}
    res = browser.handler.handle("POST", "/_/mcp", head, lambda: read.append(1) or b"{}")
    assert res.status == 400 and "X-Sheaf-As" in res.json()["error"] and not read


@pytest.mark.parametrize("sent,want", [
    ("Claude Code", "Claude Code"), ("Claude%20Code", "Claude Code"), ("Cl%C3%A4ude", "Cläude"),
    ("%41", "A"), ("100%25", "100%"), ("%2541", "%41"),
])
def test_the_name_header_is_percent_encoded_utf8_and_the_hub_decodes_it_once(browser, plan, sent, want):
    comment(plan)
    assert reply_as(browser, as_name=sent).status == 200
    assert signed(plan) == want


@pytest.mark.parametrize("sent", ["%FF", "%C3", "ab%E2%82"])
def test_a_name_that_is_not_utf8_once_decoded_is_refused(browser, plan, sent):
    comment(plan)
    before = plan.read_bytes()
    res = reply_as(browser, as_name=sent)
    assert res.status == 400 and "X-Sheaf-As" in res.json()["error"]
    assert plan.read_bytes() == before


@pytest.mark.parametrize("why,headers", [
    ("no credential at all", {}),
    ("a token that was never made", {"Authorization": "Bearer sheaf_mcp_" + "A" * 43}),
    ("a header that is not a bearer", {"Authorization": "Basic Zm9vOmJhcg=="}),
    ("a wrong key", {"X-Sheaf-Key": "nope"}),
])
def test_without_a_credential_that_works_the_door_is_401(browser, why, headers):
    res = door(browser, rpc("ping"), key=False, headers=headers)
    assert res.status == 401, why
    assert res.json() == {"ok": False, "error": "not signed in"}
    assert res.headers["WWW-Authenticate"] == "Bearer"


def test_only_a_401_of_the_door_names_a_scheme(browser, token):
    bearer = {"Authorization": f"Bearer {token}"}
    for want, res in (
            (401, browser.request("POST", "/_/save", body={}, key=False, cookie=False)),
            (403, door(browser, rpc("ping"), key=False, cookie=True)),
            (405, browser.request("GET", "/_/mcp", key=False, cookie=False, headers=bearer))):
        assert res.status == want and "WWW-Authenticate" not in res.headers


def test_a_revoked_token_is_401_on_the_very_next_call(browser, token):
    assert result(door(browser, rpc("ping"), token=token)) == {}
    Tokens().revoke("codex")
    assert door(browser, rpc("ping"), token=token).status == 401


def test_the_browser_cookie_does_not_open_the_door(browser):
    assert door(browser, rpc("ping"), key=False, cookie=True).status == 403


def test_a_token_signs_with_its_own_display_name_whatever_the_name_header_says(browser, plan, token):
    comment(plan)
    assert reply_as(browser, token=token, as_name="Someone Else").status == 200
    assert signed(plan) == "Codex"


def test_a_token_next_to_the_key_is_the_key(browser):
    h = {"X-Sheaf-As": "Claude"}
    assert result(door(browser, rpc("ping"), key=True, headers={**h, "Authorization": "Bearer nope"})) == {}


def test_a_wrong_token_is_not_rescued_by_a_cookie(browser):
    res = door(browser, rpc("ping"), key=False, cookie=True,
               headers={"Authorization": "Bearer sheaf_mcp_" + "A" * 43})
    assert res.status == 403            # the cookie is who they are, and the cookie has no door


# ── a token reaches /_/mcp and nothing else (9.7) ────────────────────────────

PAGE_AND_API = [
    ("GET", "/_/health"), ("GET", "/_/live"), ("GET", "/_/live?doc=work/plan.md"),
    ("GET", "/_/doc?doc=work/plan.md"), ("GET", "/_/jobs"), ("GET", "/work/plan.md"), ("GET", "/"),
    ("POST", "/_/save"), ("POST", "/_/comment"), ("POST", "/_/ask"), ("POST", "/_/tell"),
    ("POST", "/_/jump"), ("POST", "/_/cancel"), ("POST", "/_/seen"), ("POST", "/_/export"), ("POST", "/_/diag"),
    ("POST", "/_/render"), ("POST", "/_/stop"), ("POST", "/_/rotate"), ("POST", "/_/nothing"),
]


@pytest.mark.parametrize("method,path", [mp for mp in PAGE_AND_API if mp[1] != "/_/health"])
def test_a_token_is_refused_on_every_other_route(browser, plan, token, method, path):
    before = plan.read_bytes()
    roots = sorted(r.name for r in browser.hub.roots.all())
    body = {"doc": "work/plan.md", "hash": "x", "edits": [], "op": "add", "path": str(plan),
            "settings": {}, "reason": "stop", "kind": "html", "what": "ask", "id": "c1", "count": 1}
    res = browser.request(method, path, body=body if method == "POST" else None, cookie=False,
                          headers={"Authorization": f"Bearer {token}"}, origin=False)
    assert res.status in (401, 403, 404), (method, path, res.status)
    assert plan.read_bytes() == before
    assert sorted(r.name for r in browser.hub.roots.all()) == roots
    assert not browser.hub.stop_requested


def test_a_token_that_registers_no_root_through_render_leaves_the_registry_alone(browser, work, token):
    other = work / "elsewhere"
    other.mkdir()
    (other / "x.md").write_text("# x\n", encoding="utf-8")
    res = browser.post("/_/render", {"path": str(other / "x.md"), "settings": {}}, cookie=False,
                       headers={"Authorization": f"Bearer {token}"}, origin=False)
    assert res.status == 401
    assert browser.hub.roots.all() == []


# ── the token is never written down ──────────────────────────────────────────

def test_no_token_value_is_in_a_response_or_the_diagnostics_log(browser, plan, token):
    wrong = "sheaf_mcp_" + "Z" * 43
    texts = []
    for t, route in ((token, "/_/mcp"), (wrong, "/_/mcp"), (token, "/_/save"), (wrong, "/_/save"),
                     (token, "/_/nothing"), (token, "/work/plan.md")):
        res = browser.request("POST" if route.startswith("/_/") else "GET", route,
                              body={} if route.startswith("/_/") else None, cookie=False,
                              headers={"Authorization": f"Bearer {t}"}, origin=False)
        texts.append(res.text + json.dumps(dict(res.headers)))
    texts.append(door(browser, rpc("tools/call", {"name": "save", "arguments": {}}), token=token).text)
    Tokens().revoke("codex")
    texts.append(door(browser, rpc("ping"), token=token).text)
    rows = json.dumps(diagnostics.read())
    for text in (*texts, rows):
        assert token not in text and wrong not in text
        assert auth.token_hash(token) not in text and auth.token_hash(wrong) not in text
    assert any(r["kind"] == "mcp-401" for r in diagnostics.read())


def test_a_wrong_token_of_any_shape_is_not_echoed_back_or_logged(browser):
    weird = "sheaf_mcp_" + "../" * 5
    res = door(browser, rpc("ping"), key=False, headers={"Authorization": f"Bearer {weird}"})
    assert res.status == 401 and weird not in res.text + json.dumps(diagnostics.read())
