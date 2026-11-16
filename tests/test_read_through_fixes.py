"""The fix round over the first review of the read-through (SPEC 9.9, ticket 23): what a hostile or broken client tiroir can make the
agency hub serve, record or fail on, and what a peer's `comment` may carry. Same two hubs as `test_read_through_two_hubs.py`."""
import http.client
import json

import pytest
from test_read_through_two_hubs import (AG_ALICE, CLIENT_ORIGIN, MARKER, agency_and_client, comment)  # noqa: F401  (fixture)

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
    own = importlib.import_module("sheafmd.render")._page_asset("page.js")
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
    assert agency.post("/_/comment", {"doc": f"Clients/acme/{doc}x", "op": "add", "quote": "q", "body": "b"}, member=AG_ALICE).status == 404
    agency.link.mode = "down"
    assert agency.get(f"/Clients/acme/{doc}", member=AG_ALICE).status == 502
    assert agency.post("/_/comment", {"doc": f"Clients/acme/{doc}", "op": "add", "quote": "q", "body": "b"}, member=AG_ALICE).status == 502
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
