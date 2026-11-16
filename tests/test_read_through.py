"""Read-through (SPEC 9.9, ticket 23), on one hub standing in for both sides: the client tiroir answers a `read` for the agency member
the e-mail names, and the agency tiroir draws the "Clients" folder from what its channel brings back. The two-hub tests that
route one handler to the other through the channel come with ticket 20's `two_hubs()`.

Alice and Bob are agency members, Carol is a member of the client. Pages are made through the door as each of their agents."""
import json
import os
import pwd

import pytest
from helpers import FRONT, Front, door, rpc

from sheafmd import comments as rdc
from sheafmd import diagnostics
from sheafmd.source import md_hash
from sheafmd.hub import proxy, readthrough
from sheafmd.hub.state import Tokens

ALICE = "503b2f77-83de-452c-817a-a357faf85929"
BOB = "2b9d7e1c-4a51-4c0e-9d1f-6f0c3a7e8b42"
CAROL = "9a1f3c52-6d0e-4b7a-8c25-1e4f7b3d9a60"
MARKER = "zx-marker-4417"


def members(tmp_path, emails=True):
    def one(name, agency):
        n = name.lower()
        (tmp_path / f"{n}-work").mkdir(exist_ok=True)
        return {"name": name, "short": n, "roots": [str(tmp_path / f"{n}-work")], "tokens": [f"{n}-claude"],
                **({"email": f"{n}@example.com"} if emails else {}), **({"agency": True} if agency else {})}
    return {ALICE: one("Alice", True), BOB: one("Bob", True), CAROL: one("Carol", False)}


@pytest.fixture
def side(hub, browser, tmp_path):
    """One hub as both the client tiroir (`agency` members, a client member) and, with `clients` set, the agency tiroir."""
    tokens = {f"{n}-claude": Tokens().add(f"{n}-claude", client="Claude Code", write=True) for n in ("alice", "bob", "carol")}
    hub.proxy = proxy.parse({"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock", "proxy_user": pwd.getpwuid(os.getuid()).pw_name,
                             "client": True, "clients": {"acme": "https://acme.example.com"}, "members": members(tmp_path)}, "the test")
    front = Front(hub, browser.handler)
    front.tokens, front.door = tokens, browser
    front.asked = []

    def call(client, verb, body):
        front.asked.append((client, verb, body))
        if verb == "comment":
            return readthrough.comment_answer(browser.handler, body)
        return readthrough.answer(browser.handler, body) if verb == "read" else (404, {})
    hub.clients = readthrough.Clients(hub.proxy.clients, call)
    return front


def make(side, who, text, doc="plan.md"):
    res = door(side.door, rpc("tools/call", {"name": "create", "arguments": {"doc": doc, "text": text}}), token=side.tokens[f"{who}-claude"], as_name=None)
    out = res.json()["result"]
    assert not out["isError"], out
    return json.loads(out["content"][0]["text"])["doc"]


def ask(side, **body):
    return readthrough.answer(side.door.handler, body)


# ── the client tiroir answers for the member the e-mail names ────────────────

def test_the_agency_member_sees_the_pages_they_may_open_there(side):
    mine = make(side, "alice", f"# Alice's plan\n\n{MARKER}\n")
    make(side, "bob", "# Bob's page\n")
    status, got = ask(side, **{"as": "alice@example.com"}, op="sheaf")
    assert status == 200 and [r["doc"] for r in got["rows"]] == [mine]


@pytest.mark.parametrize("who", [{}, {"as": "*"}, {"as": ""}, {"as": "nobody@example.com"}, {"as": "carol@example.com"},
                                  {"as": "alice@example.com", "role": "admin", "admin": True}])
def test_anyone_else_is_told_what_a_member_with_nothing_to_see_is(side, who):
    make(side, "alice", "# Alice's plan\n")
    empty = ask(side, **{"as": "bob@example.com"}, op="sheaf")
    status, got = ask(side, op="sheaf", **who)
    if who.get("as") == "alice@example.com":      # a stray field changes nothing: still Alice, only Alice's pages
        assert [r["doc"] for r in got["rows"]] == ["alice-work/plan.md"]
    else:
        assert (status, got) == empty and got == {"rows": [], "tree": [], "more": {}}


def test_a_client_member_is_never_served_even_when_named(side):
    make(side, "carol", "# Carol's page\n")
    assert ask(side, **{"as": "carol@example.com"}, op="sheaf") == (200, {"rows": [], "tree": [], "more": {}})
    assert ask(side, **{"as": "carol@example.com"}, op="open", doc="carol-work/plan.md") == (200, {"open": False})


def test_open_says_whether_the_member_may_open_a_page_and_no_more(side):
    mine, theirs = make(side, "alice", "# A\n"), make(side, "bob", "# B\n")
    assert ask(side, **{"as": "alice@example.com"}, op="open", doc=mine) == (200, {"open": True})
    assert ask(side, **{"as": "alice@example.com"}, op="open", doc=theirs) == (200, {"open": False})
    assert ask(side, **{"as": "alice@example.com"}, op="open", doc=7) == (200, {"open": False})


def test_an_op_this_hub_does_not_have_is_a_route_it_does_not_have(side):
    assert ask(side, **{"as": "alice@example.com"}, op="delete") == (404, {})


# ── the agency tiroir draws the Clients folder ───────────────────────────────

def test_the_sheaf_has_a_clients_node_with_a_child_per_client(side):
    got = side.get("/_/mount?sheaf=1", member=ALICE).json()["sheaf"]
    node = next(n for n in got["tree"] if n["name"] == "Clients")
    assert [c["name"] for c in node["children"]] == ["acme"] and got["clients"] == ["acme"]
    assert side.asked == []                        # lazy: drawing the Sheaf asks no client


def test_a_tiroir_with_no_clients_has_no_clients_node(side):
    side.hub.clients = None
    got = side.get("/_/mount?sheaf=1", member=ALICE).json()["sheaf"]
    assert all(n["name"] != "Clients" for n in got["tree"]) and "clients" not in got


def test_opening_the_node_reads_the_client_through_as_the_signed_in_member(side):
    doc = make(side, "alice", f"# Plan\n\n{MARKER}\n")
    got = side.get("/_/clients/sheaf?client=acme", member=ALICE, headers={"X-Sheaf-As": "bob@example.com"})
    assert got.status == 200 and got.json()["line"] == ""
    assert [r["doc"] for r in got.json()["rows"]] == [f"Clients/acme/{doc}"]
    assert side.asked[-1][2] == {"as": "alice@example.com", "op": "sheaf"}


def test_a_client_that_is_not_configured_is_a_page_that_is_not_there(side):
    assert side.get("/_/clients/sheaf?client=other", member=ALICE).status == 404
    assert side.get("/_/clients/sheaf", member=ALICE).status == 404


def test_a_member_with_no_e_mail_is_told_why_and_nothing_is_asked(side, tmp_path):
    side.hub.proxy = proxy.parse({"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock", "proxy_user": pwd.getpwuid(os.getuid()).pw_name,
                                  "client": True, "clients": {"acme": "https://acme.example.com"}, "members": members(tmp_path, emails=False)}, "the test")
    got = side.get("/_/clients/sheaf?client=acme", member=ALICE).json()
    assert got["rows"] == [] and "e-mail" in got["line"] and side.asked == []


def test_a_client_that_does_not_answer_is_one_line_and_nothing_older(side):
    make(side, "alice", "# Plan\n")
    assert side.get("/_/clients/sheaf?client=acme", member=ALICE).json()["rows"]
    side.hub.clients = readthrough.Clients({"acme": "https://acme.example.com"}, lambda *a: (_ for _ in ()).throw(OSError("down")))
    got = side.get("/_/clients/sheaf?client=acme", member=ALICE).json()
    assert got["rows"] == [] and "not reachable" in got["line"]


def test_the_knock_line_holds_the_client_op_member_and_status_and_no_page(side):
    make(side, "alice", f"# {MARKER} title\n")
    side.get("/_/clients/sheaf?client=acme", member=ALICE)
    lines = [json.loads(l) for l in diagnostics.log_path().read_text(encoding="utf-8").splitlines() if "read-through" in l]
    assert len(lines) == 1 and {k: lines[0][k] for k in ("client", "op", "member", "status")} == {"client": "acme", "op": "sheaf", "member": ALICE, "status": "ok"}
    assert MARKER not in json.dumps(lines) and "plan.md" not in json.dumps(lines)


# ── a client page opened, read and commented through the agency tiroir ────────

def test_alice_opens_a_client_page_and_it_is_told_under_clients(side):
    doc = make(side, "alice", f"# Plan\n\n{MARKER}\n")
    got = side.get(f"/Clients/acme/{doc}", member=ALICE)
    assert got.status == 200 and MARKER in got.text and got.nonce
    assert f'"doc": "Clients/acme/{doc}"' in got.text.replace(" ", " ")


def test_a_page_she_may_not_open_and_a_page_that_is_not_there_are_one_answer(side):
    theirs = make(side, "bob", "# B\n")
    mine = make(side, "alice", "# A\n")
    not_there = side.get("/Clients/acme/alice-work/nothing.md", member=ALICE)
    refused = side.get(f"/Clients/acme/{theirs}", member=ALICE)
    assert (refused.status, refused.body) == (not_there.status, not_there.body) == (404, not_there.body)
    assert side.get(f"/Clients/acme/{mine}", member=ALICE).status == 200


def test_a_client_member_gets_the_answer_of_a_page_that_is_not_there(side):
    doc = make(side, "carol", "# C\n")
    assert side.get(f"/Clients/acme/{doc}", member=CAROL).status == 404


def test_the_doc_state_and_the_mount_come_through(side):
    doc = make(side, "alice", f"# Plan\n\n{MARKER}\n")
    state = side.get(f"/_/doc?doc=Clients/acme/{doc}", member=ALICE)
    assert state.status == 200 and "hash" in state.json()
    mounted = side.get(f"/_/mount?doc=Clients/acme/{doc}", member=ALICE)
    assert mounted.status == 200 and MARKER in mounted.json()["html"]
    assert mounted.json()["config"]["doc"] == f"Clients/acme/{doc}"


def test_a_client_page_is_polled_never_streamed_and_has_no_write_log_here(side):
    doc = make(side, "alice", "# Plan\n")
    assert side.get(f"/_/live?doc=Clients/acme/{doc}", member=ALICE).status == 404
    assert side.get(f"/_/writes?doc=Clients/acme/{doc}", member=ALICE).json()["lines"] == []


def comment_on(side, doc, member, **extra):
    text = side.hub.file(doc).read_text(encoding="utf-8")
    blk, start, end = rdc.find_quote(text, "Plan")
    return side.post("/_/comment", {"doc": f"Clients/acme/{doc}", "op": "add", "hash": md_hash(text), "block": blk, "start": start,
                                    "end": end, "quote": "Plan", "body": "A note.", **extra}, member=member)


def test_a_comment_lands_on_the_client_page_under_the_members_name(side):
    doc = make(side, "alice", "# Plan\n")
    got = comment_on(side, doc, ALICE)
    assert got.status == 200, got.text
    assert "A note." in side.hub.file(doc).read_text(encoding="utf-8") and "Alice" in side.hub.file(doc).read_text(encoding="utf-8")


def test_a_comment_on_a_page_she_may_not_open_is_404_and_writes_nothing(side):
    doc = make(side, "bob", "# Plan\n")
    before = side.hub.file(doc).read_text(encoding="utf-8")
    assert comment_on(side, doc, ALICE).status == 404
    assert side.hub.file(doc).read_text(encoding="utf-8") == before


def test_tell_on_a_client_page_is_refused_and_nothing_is_written(side):
    doc = make(side, "alice", "# Plan\n")
    before = side.hub.file(doc).read_text(encoding="utf-8")
    assert comment_on(side, doc, ALICE, tell=True).status == 400
    assert side.hub.file(doc).read_text(encoding="utf-8") == before


def test_a_client_that_does_not_answer_a_page_is_502_and_serves_nothing(side):
    doc = make(side, "alice", "# Plan\n")
    side.hub.clients = readthrough.Clients({"acme": "https://acme.example.com"}, lambda *a: (_ for _ in ()).throw(OSError("down")))
    assert side.get(f"/Clients/acme/{doc}", member=ALICE).status == 502
    assert side.get(f"/Clients/other/{doc}", member=ALICE).status == 404
