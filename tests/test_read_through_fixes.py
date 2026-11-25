"""The fix round over the first review of the read-through (SPEC 9.9, ticket 23): what a hostile or broken client tiroir can make the
agency hub serve, record or fail on, and what a peer's `comment` may carry. Same two hubs as `test_read_through_two_hubs.py`."""
import http.client
import json

import pytest
from test_read_through_two_hubs import (AG_ALICE, AG_BOB, CLIENT_ORIGIN, MARKER, agency_and_client, comment)  # noqa: F401  (fixture)

import importlib

from sheafmd import comments as rdc
from sheafmd import diagnostics
from sheafmd.hub import outgoing, readthrough
from sheafmd.source import md_hash

EVIL = "evil-nonce-1234567890abcdef"


def speaks(agency, envelope):
    """The agency's client tiroir now answers every `read` with `envelope`, whatever was asked."""
    agency.hub.clients = readthrough.Clients(agency.hub.proxy.clients, lambda client, verb, body: (200, envelope))


def hostile_page(**extra):
    return {"status": 200, "type": "html", "nonce": EVIL, "headers": {}, **extra,
            "body": (f'<html><body>x<script nonce="{EVIL}">window.stolen = 1</script>'
                     f'<script id="rd-edit-meta" type="application/json">{{}}</script>'
                     f'<script src="https://evil.example.com/x.js" nonce="{EVIL}"></script></body></html>')}


def csp_nonce(got):
    return got.headers["Content-Security-Policy"].split("'nonce-")[1].split("'")[0]


# ── 1: the client's nonce and scripts are never the agency's ─────────────────

def test_a_client_page_is_served_under_a_nonce_the_agency_drew(agency_and_client):
    agency, client = agency_and_client
    speaks(agency, hostile_page())
    got = agency.get("/Clients/acme/work/x.md", member=AG_ALICE)
    assert got.status == 200
    assert EVIL not in got.headers["Content-Security-Policy"] and EVIL not in got.text


def test_a_script_of_the_client_that_is_not_the_pages_own_is_dropped(agency_and_client):
    agency, client = agency_and_client
    speaks(agency, hostile_page())
    got = agency.get("/Clients/acme/work/x.md", member=AG_ALICE)
    assert "window.stolen" not in got.text and "evil.example.com" not in got.text
    assert 'id="rd-edit-meta"' in got.text                                       # the page's data block stays


def test_a_real_client_page_keeps_its_own_script_under_the_agencys_nonce(agency_and_client):
    agency, client = agency_and_client
    doc = client.make("alice", f"# Plan\n\n{MARKER}\n")
    got = agency.get(f"/Clients/acme/{doc}", member=AG_ALICE)
    own = importlib.import_module("sheafmd.render").page_script()
    assert got.status == 200 and f'<script nonce="{csp_nonce(got)}">{own}</script>' in got.text


# ── 2: the client's headers are an allow-list on the agency side ─────────────

BAD_HEADERS = {"Set-Cookie": "sid=1", "Location": "https://evil.example.com", "Access-Control-Allow-Origin": "*",
               "Content-Type": "text/html", "Content-Security-Policy": "default-src *"}


def test_a_client_cannot_set_headers_on_a_json_answer(agency_and_client):
    agency, client = agency_and_client
    speaks(agency, {"status": 200, "type": "json", "nonce": None, "body": '{"ok": true}', "headers": BAD_HEADERS})
    got = agency.get("/_/doc?doc=Clients/acme/work/x.md", member=AG_ALICE)
    assert got.headers["Content-Type"] == "application/json"
    for k in ("Set-Cookie", "Location", "Access-Control-Allow-Origin", "Content-Security-Policy"):
        assert k not in got.headers


def test_a_client_cannot_set_headers_on_a_page(agency_and_client):
    agency, client = agency_and_client
    speaks(agency, hostile_page(headers=BAD_HEADERS))
    got = agency.get("/Clients/acme/work/x.md", member=AG_ALICE)
    for k in ("Set-Cookie", "Location", "Access-Control-Allow-Origin"):
        assert k not in got.headers
    assert got.headers["Content-Type"].startswith("text/html") and "default-src *" not in got.headers["Content-Security-Policy"]


# ── 3: no client address in the agency's diagnostics, on the error paths too ─

def agency_log(agency):
    with agency.inside():
        path = diagnostics.log_path()
        return path.read_text(encoding="utf-8") if path.exists() else ""


def test_an_error_answer_on_a_client_page_leaves_no_address_in_the_log(agency_and_client):
    agency, client = agency_and_client
    doc = client.make("alice", f"# {MARKER}\n")
    name = doc.split("/")[-1]
    assert agency.get("/Clients/acme/alice-work/none.md", member=AG_ALICE).status == 404                 # the client says no
    assert agency.get(f"/_/doc?doc=Clients/acme/{doc}x", member=AG_ALICE).status == 404
    assert agency.post("/_/comment", {"doc": f"Clients/acme/{doc}x", "op": "add", "quote": "q", "body": "b", "side": "client"}, member=AG_ALICE).status == 404
    agency.link.mode = "down"
    assert agency.get(f"/Clients/acme/{doc}", member=AG_ALICE).status == 502
    assert agency.post("/_/comment", {"doc": f"Clients/acme/{doc}", "op": "add", "quote": "q", "body": "b", "side": "client"}, member=AG_ALICE).status == 502
    log = agency_log(agency)
    assert log and "read-through" in log
    for told in ("Clients/acme", "none.md", name, "alice-work", MARKER):
        assert told not in log, told


# ── 4: the client query is a configured name, exactly ────────────────────────

@pytest.mark.parametrize("name", ["acme/zzz", "acme%2Fzzz", "acme/", "ACME", "nobody", ""])
def test_a_client_query_that_is_not_a_configured_name_is_a_missing_page_and_asks_no_one(agency_and_client, name):
    agency, client = agency_and_client
    asked = len(agency.link.asked)
    got = agency.get(f"/_/clients/sheaf?client={name}", member=AG_ALICE)
    assert got.status == 404 and len(agency.link.asked) == asked
    assert name not in agency_log(agency) or name == ""


# ── 5: an answer that is not one is the line of a client that does not answer ─

BAD_ROWS = [["not", "a", "dict"], {"rows": "no"}, {"rows": [{"doc": "a.md"}]}, {"rows": [["x"]]},
            {"rows": [{"doc": 3, "folder": "f", "root": "r"}]}, "text", None]


@pytest.mark.parametrize("answer", BAD_ROWS)
def test_a_client_answer_of_the_wrong_shape_is_told_as_not_reachable(agency_and_client, answer):
    agency, client = agency_and_client
    agency.hub.clients = readthrough.Clients(agency.hub.proxy.clients, lambda c, v, b: (200, answer))
    got = agency.get("/_/clients/sheaf?client=acme", member=AG_ALICE)
    assert got.status == 200 and got.json()["rows"] == [] and "not reachable" in got.json()["line"]


@pytest.mark.parametrize("answer", [["x"], "text", None, {"status": "200"}, {"status": 200, "body": 3}])
def test_a_client_envelope_of_the_wrong_shape_is_a_502_on_a_page(agency_and_client, answer):
    agency, client = agency_and_client
    speaks(agency, answer)
    assert agency.get("/Clients/acme/work/x.md", member=AG_ALICE).status == 502
    assert agency.get("/_/doc?doc=Clients/acme/work/x.md", member=AG_ALICE).status == 502


@pytest.mark.parametrize("raised", [http.client.IncompleteRead(b"x"), http.client.RemoteDisconnected("gone")])
def test_a_reply_cut_short_is_an_oserror(monkeypatch, raised):
    from sheafmd import connect

    class Cut:
        def open(self, req, timeout=None):
            raise raised
    monkeypatch.setattr(connect, "peer_token_for", lambda origin: "t")
    monkeypatch.setattr(connect, "_NO_REDIRECT", Cut())
    with pytest.raises(OSError):
        outgoing.call(CLIENT_ORIGIN, "read", {})


# ── 7: the client refuses what a relayed comment must not carry ──────────────

@pytest.mark.parametrize("extra", [{"tell": True}, {"tell": "claude"}])
def test_the_client_refuses_a_tell_in_a_relayed_comment_whatever_the_agency_did(agency_and_client, extra):
    agency, client = agency_and_client
    doc = client.make("alice", "# Plan\n")
    text = client.text(doc)
    blk, start, end = rdc.find_quote(text, "Plan")
    request = {"op": "add", "hash": md_hash(text), "block": blk, "start": start, "end": end, "quote": "Plan", "body": "b", **extra}
    status, answer = agency.link("acme", "comment", {"as": "alice@example.com", "doc": doc, "request": request})
    assert status == 200 and answer["status"] == 400 and "Tell" in answer["body"]
    assert client.text(doc) == text


# ── round 2 (review of the fixes): a client envelope is validated as a whole ─

def json_env(**kw):
    return {"status": 200, "type": "json", "nonce": None, "headers": {}, "body": "{}", **kw}


@pytest.mark.parametrize("value", ["no-store\r\nSet-Cookie: sid=1\r\n\r\n<script>x</script>", "no-store\nX: y", "a\x00b", "€"])
def test_a_header_value_with_a_line_break_a_nul_or_a_non_latin1_character_is_dropped(agency_and_client, value):
    agency, client = agency_and_client
    speaks(agency, json_env(headers={"Cache-Control": value}))
    got = agency.get("/_/doc?doc=Clients/acme/work/x.md", member=AG_ALICE)
    assert got.status == 200 and "Set-Cookie" not in got.headers
    assert all(not any(c in v for c in "\r\n\x00") and v.isascii() or v == "no-store" for v in got.headers.values())
    assert got.headers.get("Cache-Control") == "no-store"                      # the hub's own default, not the client's


@pytest.mark.parametrize("status", [100, 101, 199, 204, 304, 600, 99, 0, -1, True])
def test_a_status_that_cannot_carry_a_body_or_is_not_one_is_a_client_that_does_not_answer(agency_and_client, status):
    agency, client = agency_and_client
    speaks(agency, json_env(status=status, body="HTTP/1.1 200 OK\r\n\r\n<script>x</script>"))
    assert agency.get("/_/doc?doc=Clients/acme/work/x.md", member=AG_ALICE).status == 502


@pytest.mark.parametrize("type_", ["json", "html"])
def test_a_body_that_cannot_be_encoded_is_a_client_that_does_not_answer(agency_and_client, type_):
    agency, client = agency_and_client
    speaks(agency, json_env(type=type_, body="\ud800"))
    assert agency.get("/_/doc?doc=Clients/acme/work/x.md", member=AG_ALICE).status == 502


def test_a_client_error_sentence_never_reaches_the_agency_log_and_a_body_that_is_not_an_object_does_not_crash(agency_and_client):
    agency, client = agency_and_client
    speaks(agency, json_env(status=403, body=json.dumps({"error": "Clients/acme/secret-merger.md"})))
    assert agency.get("/_/doc?doc=Clients/acme/work/x.md", member=AG_ALICE).status == 403
    for body in ("[1]", "3", "null", "not json"):
        speaks(agency, json_env(status=403, body=body))
        assert agency.get("/_/doc?doc=Clients/acme/work/x.md", member=AG_ALICE).status == 403, body
    assert "secret-merger" not in agency_log(agency)


def test_a_client_row_never_offers_move_here():
    row = {"doc": "work/a.md", "url": "/work/a.md", "folder": "work", "root": "work", "title": "A", "can_move": True, "own": True}
    [out] = readthrough.fold_rows("acme", [row])
    assert out["can_move"] is False and out["own"] is False


# ── round 3 (second review): what the agency does with a client page's mount, redirect and status ─

def asked_clients_of(site):
    """The `[proxy.clients]` of `site` answers every call with a line that is counted."""
    calls = []
    site.hub.clients = readthrough.Clients({"beta": "https://beta.example.com"}, lambda *a: calls.append(a) or (200, {}))
    return calls


def test_a_client_on_another_build_mounts_with_the_agencys_own_version_script_and_assets(agency_and_client):
    agency, client = agency_and_client
    other = {"kind": "doc", "title": "T", "html": "<main>x</main>", "config": {}, "css": "", "version": "client-build",
             "script": "client-mount.js", "assets": {"mount.js": "client-tag"}}
    speaks(agency, json_env(body=json.dumps(other)))
    got = agency.get("/_/mount?doc=Clients/acme/work/x.md", member=AG_ALICE).json()
    assert got["version"] == agency.hub.version and got["version"] != "client-build"
    assert {k: got[k] for k in ("script", "assets")} == agency.hub.mount_fields()
    assert got["html"] == "<main>x</main>"                                     # the page itself is the client's


def redirect(location, **kw):
    return {"status": 302, "type": "json", "nonce": None, "body": "", "headers": {} if location is None else {"Location": location}, **kw}


def test_a_client_redirect_to_a_page_of_that_client_is_sent_on_under_the_clients_prefix(agency_and_client):
    agency, client = agency_and_client
    speaks(agency, redirect("/alice-work/new.md"))
    got = agency.get("/Clients/acme/alice-work/old.md", member=AG_ALICE)
    assert got.status == 302 and got.headers["Location"] == "/Clients/acme/alice-work/new.md"


@pytest.mark.parametrize("location", [None, "", "https://evil.example.com/x", "//evil.example.com/x", "/Clients/beta/x.md", "/_/doc?doc=x",
                                      "work/new.md", "/work/a\r\nSet-Cookie: x=1", "/work\\..\\x", "javascript:alert(1)"])
def test_a_client_redirect_that_is_not_a_page_of_that_client_is_a_client_that_does_not_answer(agency_and_client, location):
    agency, client = agency_and_client
    speaks(agency, redirect(location))
    got = agency.get("/Clients/acme/work/old.md", member=AG_ALICE)
    assert got.status == 502 and "Location" not in got.headers


@pytest.mark.parametrize("status", [301, 303, 307, 308])
def test_only_a_302_is_a_redirect_the_agency_sends_on(agency_and_client, status):
    agency, client = agency_and_client
    speaks(agency, redirect("/work/new.md", status=status))
    assert agency.get("/Clients/acme/work/old.md", member=AG_ALICE).status == 502


def test_a_moved_client_page_opens_through_the_agency_by_the_clients_own_forward(agency_and_client):
    agency, client = agency_and_client
    new = client.make("alice", f"# Plan\n\n{MARKER}\n")
    old = new.rsplit("/", 1)[0] + "/old.md"
    with client.inside():
        client.hub.forwards.add(old, new, "alice")
    got = agency.get(f"/Clients/acme/{old}", member=AG_ALICE)
    assert got.status == 302 and got.headers["Location"] == f"/Clients/acme/{new}"


@pytest.mark.parametrize("op", ["page", "doc", "mount", "writes"])
def test_a_client_that_also_has_clients_never_passes_a_clients_address_on(agency_and_client, op):
    agency, client = agency_and_client
    calls = asked_clients_of(client)
    status, got = agency.link("acme", "read", {"as": "alice@example.com", "op": op, "doc": "Clients/beta/x.md"})
    assert status == 200 and got["status"] == 404 and calls == []


def test_a_client_that_also_has_clients_never_passes_a_comment_on(agency_and_client):
    agency, client = agency_and_client
    calls = asked_clients_of(client)
    status, got = agency.link("acme", "comment", {"as": "alice@example.com", "doc": "Clients/beta/x.md",
                                                  "request": {"op": "add", "quote": "q", "body": "b"}})
    assert status == 200 and got["status"] == 404 and calls == []


def test_two_tiroirs_that_list_each_other_make_one_call_not_a_chain(agency_and_client):
    agency, client = agency_and_client
    client.hub.clients = readthrough.Clients({"agency": "https://tt.example.com"}, lambda c, v, b: agency.link("acme", v, b))
    agency_calls = len(agency.link.asked)
    assert agency.get("/Clients/acme/Clients/agency/x.md", member=AG_ALICE).status == 404
    assert len(agency.link.asked) == agency_calls + 1


@pytest.mark.parametrize("status", [404, 401, 403, 500, 502])
def test_a_channel_that_does_not_answer_200_is_a_client_that_is_not_reachable(agency_and_client, status):
    agency, client = agency_and_client
    agency.hub.clients = readthrough.Clients(agency.hub.proxy.clients, lambda c, v, b: (status, {}))
    got = agency.get("/_/clients/sheaf?client=acme", member=AG_ALICE).json()
    assert got["rows"] == [] and "not reachable" in got["line"]
    assert agency.get("/Clients/acme/work/x.md", member=AG_ALICE).status == 502


def test_a_token_without_the_read_scope_is_a_client_that_is_not_reachable(agency_and_client):
    agency, client = agency_and_client
    from two_hubs import Link
    agency.hub.clients = readthrough.Clients(agency.hub.proxy.clients, Link(client, client.peer_token("https://tt.example.com", ["transfer"], name="no-read")))
    got = agency.get("/_/clients/sheaf?client=acme", member=AG_ALICE).json()
    assert got["rows"] == [] and "not reachable" in got["line"]


def test_a_500_from_the_client_is_not_a_page_that_is_not_there(agency_and_client):
    agency, client = agency_and_client
    agency.hub.clients = readthrough.Clients(agency.hub.proxy.clients, lambda c, v, b: (500, {}))
    got = agency.get("/Clients/acme/work/x.md", member=AG_ALICE)
    assert got.status == 502 and "not reachable" in got.text


# ── round 4 (third review): a client page is read, not edited, and its address is not a diagnostics line ─

def test_a_relayed_client_page_offers_no_editor_no_actions_and_no_agent(agency_and_client):
    agency, client = agency_and_client
    doc = client.make("alice", f"# Plan\n\n{MARKER}\n")
    config = agency.get(f"/_/mount?doc=Clients/acme/{doc}", member=AG_ALICE).json()["config"]
    assert config["edit"] is False and config["actions"] == [] and config["targets"] == [] and config["can"] == []
    assert "work" not in config and "way_back" not in config and not config.get("readonly")      # a read-only page cannot be commented on


@pytest.mark.parametrize("path,extra", [("/_/save", {"hash": "h", "edits": []}), ("/_/tick", {}), ("/_/share", {}), ("/_/pin", {}), ("/_/tell", {})])
def test_a_write_to_a_client_page_other_than_a_comment_is_refused_with_a_sentence_that_says_so(agency_and_client, path, extra):
    agency, client = agency_and_client
    doc = client.make("alice", f"# Plan\n\n{MARKER}\n")
    got = agency.post(path, {"doc": f"Clients/acme/{doc}", **extra}, member=AG_ALICE)
    assert got.status == 403 and "client" in got.text and "no such document" not in got.text
    assert client.text(doc) == f"# Plan\n\n{MARKER}\n"


def test_a_diagnostic_about_a_client_page_records_the_kind_and_nothing_else(agency_and_client):
    agency, client = agency_and_client
    got = agency.post("/_/diag", {"kind": "toast-red", "doc": "Clients/acme/alice-work/secret-merger.md", "message": "secret-merger failed",
                                  "where": "Clients/acme"}, member=AG_ALICE)
    assert got.status == 204
    log = agency_log(agency)
    assert "toast-red" in log
    for told in ("Clients/acme", "secret-merger", "alice-work"):
        assert told not in log, told


def test_a_diagnostic_about_a_page_of_this_tiroir_still_keeps_its_address(agency_and_client):
    agency, client = agency_and_client
    assert agency.post("/_/diag", {"kind": "toast-red", "doc": "alice-work/own-page.md", "message": "m"}, member=AG_ALICE).status == 204
    assert "alice-work/own-page.md" in agency_log(agency)


# ── round 5 (fourth review): the `/_/doc` answer of a client page carries no agent, no Tell target, no Work ─

AGENT_FIELDS = {"target": {"agent": "claude", "display": "Claude"}, "targets": [{"id": "agent:x"}], "capabilities": ["deliver"],
                "lines": {"tell": "Tell Claude"}, "way_back": {"session": "s1"}, "work": {"sessions": []}, "telling": [{"id": "c1"}]}


def assert_no_agent(got):
    assert got["target"] is None and got["targets"] == [] and got["capabilities"] == [] and got["lines"] == {} and got["telling"] == []
    assert "way_back" not in got and "work" not in got


def test_the_client_answers_doc_for_a_relayed_page_with_no_agent_target_or_work(agency_and_client):
    agency, client = agency_and_client
    doc = client.make("alice", f"# Plan\n\n{MARKER}\n")
    status, env = agency.link("acme", "read", {"as": "alice@example.com", "op": "doc", "doc": doc, "mount": "Clients/acme"})
    assert status == 200 and env["status"] == 200
    got = json.loads(env["body"])
    assert_no_agent(got) and got["hash"]


def test_the_agency_strips_them_from_the_doc_answer_of_an_older_client_that_still_sends_them(agency_and_client):
    agency, client = agency_and_client
    speaks(agency, json_env(body=json.dumps({"ok": True, "hash": "h1", **AGENT_FIELDS})))
    got = agency.get("/_/doc?doc=Clients/acme/work/x.md", member=AG_ALICE).json()
    assert_no_agent(got) and got["hash"] == "h1"


def test_a_doc_answer_that_is_not_an_object_is_a_client_that_does_not_answer(agency_and_client):
    agency, client = agency_and_client
    speaks(agency, json_env(body="[1]"))
    assert agency.get("/_/doc?doc=Clients/acme/work/x.md", member=AG_ALICE).status == 502


# ── ticket 202 A (Codex on #655): the drafts of a page read through are kept under this hub's member, never the client's say ─

CLIENT_SAYS = {"proxy": False, "member": "one-for-everyone"}


def page_meta(got):
    return json.loads(got.text.split(f"<script {readthrough._META_ATTRS}>")[1].split("</script>")[0])


def test_a_client_page_names_the_signed_in_agency_member_whatever_its_meta_block_says(agency_and_client):
    agency, client = agency_and_client
    speaks(agency, {**hostile_page(), "body": f'<html><body><script {readthrough._META_ATTRS}>{json.dumps(CLIENT_SAYS)}</script></body></html>'})
    metas = [page_meta(agency.get("/Clients/acme/work/x.md", member=m)) for m in (AG_ALICE, AG_BOB)]
    assert [(m["proxy"], m["member"]) for m in metas] == [(True, AG_ALICE), (True, AG_BOB)]


def test_a_client_mount_names_the_signed_in_agency_member_whatever_its_config_says(agency_and_client):
    agency, client = agency_and_client
    speaks(agency, json_env(body=json.dumps({"kind": "doc", "title": "T", "html": "<main>x</main>", "config": CLIENT_SAYS, "css": ""})))
    configs = [agency.get("/_/mount?doc=Clients/acme/work/x.md", member=m).json()["config"] for m in (AG_ALICE, AG_BOB)]
    assert [(c["proxy"], c["member"]) for c in configs] == [(True, AG_ALICE), (True, AG_BOB)]


def test_a_real_client_page_names_the_agency_member_not_the_clients_account_of_them(agency_and_client):
    agency, client = agency_and_client
    doc = client.make("alice", f"# Plan\n\n{MARKER}\n")
    meta = page_meta(agency.get(f"/Clients/acme/{doc}", member=AG_ALICE))
    assert (meta["proxy"], meta["member"]) == (True, AG_ALICE)
