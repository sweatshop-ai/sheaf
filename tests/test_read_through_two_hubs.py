"""Read-through between two hubs (SPEC 9.9, ticket 23): an agency tiroir reads a client tiroir through the channel, on behalf of the
member who asks. Each hub has its own state, roots and e-mail table; the only thing between them is `Link`, a POST of
`/_/tiroir/read` or `/_/tiroir/comment` on the client's handler with a peer token of scope `read`.

Agency: Alice, Bob, Dana. Client: Alice and Bob (agency members there), Carol (a client member). Dana has no account on the client."""
import json

import pytest
from two_hubs import TAILNET, Link, Site

from sheafmd import comments as rdc
from sheafmd import diagnostics
from sheafmd.hub import readthrough
from sheafmd.source import md_hash

CLIENT_ORIGIN = "https://acme.example.com"
AG_ALICE, AG_BOB, AG_DANA = ("a1000000-0000-4000-8000-00000000000%d" % n for n in (1, 2, 3))
CL_ALICE, CL_BOB, CL_CAROL = ("c1000000-0000-4000-8000-00000000000%d" % n for n in (1, 2, 3))
MARKER = "zx-marker-4417"
NOTE = "yq-note-9082"


@pytest.fixture
def agency_and_client(tmp_path):
    client = Site(tmp_path, "client", 27421, CLIENT_ORIGIN, {
        CL_ALICE: ("Alice", "alice@example.com", True), CL_BOB: ("Bob", "bob@example.com", True),
        CL_CAROL: ("Carol", "carol@acme.example.com", False)}, client=True)
    agency = Site(tmp_path, "agency", 27422, "https://tt.example.com", {
        AG_ALICE: ("Alice", "alice@example.com", False), AG_BOB: ("Bob", "bob@example.com", False),
        AG_DANA: ("Dana", "dana@example.com", False)}, clients={"acme": CLIENT_ORIGIN})
    link = Link(client, client.peer_token("https://tt.example.com", ["read"], name="agency-link"))
    agency.hub.clients = readthrough.Clients(agency.hub.proxy.clients, link)
    agency.link = link
    return agency, client


def rows(agency, member):
    got = agency.get("/_/clients/sheaf?client=acme", member=member)
    assert got.status == 200, got.text
    return got


def test_clients_folder_lists_what_alice_may_open(agency_and_client):
    agency, client = agency_and_client
    mine = client.make("alice", f"# Alice's plan\n\n{MARKER}\n")
    client.make("bob", "# Bob's page\n")
    client.make("carol", "# Carol's private page\n")
    assert [r["doc"] for r in rows(agency, AG_ALICE).json()["rows"]] == [f"Clients/acme/{mine}"]


def test_member_without_account_gets_nothing_and_the_answer_is_one_an_empty_root_gives(agency_and_client):
    agency, client = agency_and_client
    client.make("alice", f"# Alice's plan\n\n{MARKER}\n")
    dana, bob = rows(agency, AG_DANA), rows(agency, AG_BOB)           # Bob has an account there and no page: an empty root
    assert dana.json()["rows"] == [] and dana.body == bob.body
    assert MARKER not in dana.text


def test_client_member_email_is_never_served(agency_and_client):
    agency, client = agency_and_client
    client.make("carol", f"# Carol's page\n\n{MARKER}\n")
    got = agency.link("acme", "read", {"as": "carol@acme.example.com", "op": "sheaf"})
    assert got == (200, {"rows": [], "tree": [], "more": {}})


def test_open_a_client_page_through_the_agency_and_a_refused_page_is_a_missing_one(agency_and_client):
    agency, client = agency_and_client
    mine, theirs = client.make("alice", f"# Plan\n\n{MARKER}\n"), client.make("bob", "# B\n")
    got = agency.get(f"/Clients/acme/{mine}", member=AG_ALICE)
    assert got.status == 200 and MARKER in got.text
    refused, missing = agency.get(f"/Clients/acme/{theirs}", member=AG_ALICE), agency.get("/Clients/acme/alice-work/none.md", member=AG_ALICE)
    assert (refused.status, refused.body) == (missing.status, missing.body) and refused.status == 404


def test_the_channel_has_no_admin_scope(agency_and_client):
    agency, client = agency_and_client
    mine = client.make("alice", "# Plan\n")
    bob = agency.link("acme", "read", {"as": "bob@example.com", "op": "sheaf"})
    for extra in ({}, {"as": "*"}, {"as": ""}, {"as": "bob@example.com", "role": "admin", "admin": True}):
        body = {"op": "sheaf", **({"as": "bob@example.com"} if not extra else extra)}
        assert agency.link("acme", "read", body) == bob == (200, {"rows": [], "tree": [], "more": {}}), extra
    assert [r["doc"] for r in agency.link("acme", "read", {"as": "alice@example.com", "op": "sheaf", "admin": True})[1]["rows"]] == [mine]
    transfer_only = client.peer_token("https://other.example.com", ["transfer"])
    for headers in ({"Authorization": f"Bearer {transfer_only}"}, {}):
        got = client.post("/_/tiroir/read", {"as": "alice@example.com", "op": "sheaf"}, member=None, headers={**TAILNET, **headers})
        assert got.status == 404
    assert client.post("/_/tiroir/read", {"as": "alice@example.com", "op": "sheaf"}, member=None,
                       headers={**TAILNET, "Authorization": f"Bearer {agency.link.token}", "X-Sheaf-Member": CL_CAROL}).status == 200


def test_a_revoked_peer_token_gets_the_answer_of_no_route_and_the_agency_reads_nothing(agency_and_client):
    agency, client = agency_and_client
    client.make("alice", f"# Plan\n\n{MARKER}\n")
    assert rows(agency, AG_ALICE).json()["rows"]
    assert client.revoke("agency-link")
    got = client.post("/_/tiroir/read", {"as": "alice@example.com", "op": "sheaf"}, member=None,
                      headers={**TAILNET, "Authorization": f"Bearer {agency.link.token}"})
    assert got.status == 404
    assert rows(agency, AG_ALICE).json()["rows"] == []


def test_browser_cannot_choose_who_it_reads_as(agency_and_client):
    agency, client = agency_and_client
    client.make("alice", "# Plan\n")
    got = agency.get("/_/clients/sheaf?client=acme&as=alice@example.com", member=AG_BOB, headers={"X-Sheaf-As": "alice@example.com"})
    assert got.json()["rows"] == [] and agency.link.asked[-1][2] == {"as": "bob@example.com", "op": "sheaf"}


def comment(agency, client, doc, member, **extra):
    text = client.text(doc)
    blk, start, end = rdc.find_quote(text, "Plan")
    return agency.post("/_/comment", {"doc": f"Clients/acme/{doc}", "op": "add", "hash": md_hash(text), "block": blk, "start": start,
                                      "end": end, "quote": "Plan", "body": NOTE, "side": "client", **extra}, member=member)


def test_agency_disk_holds_no_client_page(agency_and_client):
    agency, client = agency_and_client
    doc = client.make("alice", f"# Plan {MARKER}\n\n{MARKER}\n")
    rows(agency, AG_ALICE)
    assert agency.get(f"/Clients/acme/{doc}", member=AG_ALICE).status == 200
    assert agency.get(f"/_/doc?doc=Clients/acme/{doc}", member=AG_ALICE).status == 200
    assert agency.get(f"/_/mount?doc=Clients/acme/{doc}", member=AG_ALICE).status == 200
    got = comment(agency, client, doc, AG_ALICE)
    assert got.status == 200, got.text
    seen = [(f, needle) for f, data in agency.files() for needle in (MARKER, NOTE, doc.split("/")[-1], "Alice's") if needle.encode() in data]
    assert seen == []


def test_unreachable_client_serves_nothing_old(agency_and_client):
    agency, client = agency_and_client
    doc = client.make("alice", f"# Plan\n\n{MARKER}\n")
    assert rows(agency, AG_ALICE).json()["rows"]
    agency.link.mode = "down"
    again = rows(agency, AG_ALICE).json()
    assert again["rows"] == [] and "not reachable" in again["line"]
    assert agency.get(f"/Clients/acme/{doc}", member=AG_ALICE).status == 502
    agency.link.mode = "broken"
    assert rows(agency, AG_ALICE).json()["rows"] == []


def test_knock_diagnostics_hold_no_address(agency_and_client):
    agency, client = agency_and_client
    doc = client.make("alice", f"# {MARKER}\n")
    rows(agency, AG_ALICE)
    agency.get(f"/Clients/acme/{doc}", member=AG_ALICE)
    with agency.inside():
        lines = [json.loads(line) for line in diagnostics.log_path().read_text(encoding="utf-8").splitlines() if "read-through" in line]
    assert lines and all({"client", "op", "member", "status"} <= set(line) for line in lines)
    assert MARKER not in json.dumps(lines) and doc.split("/")[-1] not in json.dumps(lines)


def test_alice_comment_lands_on_the_client_hub_under_her_name(agency_and_client):
    agency, client = agency_and_client
    doc = client.make("alice", "# Plan\n")
    got = comment(agency, client, doc, AG_ALICE)
    assert got.status == 200, got.text
    assert NOTE in client.text(doc) and "Alice" in client.text(doc)
    assert [f for f, data in agency.files() if NOTE.encode() in data] == []


def test_comment_on_a_page_alice_may_not_open_is_404_and_writes_nothing(agency_and_client):
    agency, client = agency_and_client
    doc = client.make("carol", "# Plan\n")
    before = client.text(doc)
    assert comment(agency, client, doc, AG_ALICE).status == 404
    assert client.text(doc) == before


def test_tell_on_a_client_page_is_refused_and_nothing_is_written(agency_and_client):
    agency, client = agency_and_client
    doc = client.make("alice", "# Plan\n")
    before = client.text(doc)
    assert comment(agency, client, doc, AG_ALICE, tell=True).status == 400
    assert client.text(doc) == before


FORGED = {"doc": "loose-alice/agency-secret.md", "actions": [{"id": "x", "label": "Go"}], "edit": True, "editable": [0],
          "agent": {"kind": "agent", "token": "t", "display": "D"}, "can": ["deliver"], "targets": [{"target": "x"}],
          "lines": {"tell": "x"}, "work": {"fork": "x", "attach": "x"}, "way_back": {"link": "https://elsewhere.example/"}}
_META = r'(<script id="rd-edit-meta" type="application/json">)(.*?)(</script>)'


def _forging(agency, monkeypatch):
    """The client hub answers with a meta block (page) or config (mount) that names what the agency page acts on."""
    import re
    relay = agency.hub.clients.relay

    def forged(*a, **k):
        env = relay(*a, **k)
        if env["status"] != 200:
            return env
        if env.get("type") == "html":
            body = re.sub(_META, lambda m: m.group(1) + json.dumps({**json.loads(m.group(2)), **FORGED}) + m.group(3),
                          env["body"], count=1, flags=re.S)
        else:
            got = json.loads(env["body"])
            got["config"] = {**got.get("config", {}), **FORGED}
            body = json.dumps(got)
        return {**env, "body": body}
    monkeypatch.setattr(agency.hub.clients, "relay", forged)


def test_the_agency_sets_what_a_client_page_acts_on_whatever_the_client_tiroir_says(agency_and_client, monkeypatch):
    # Ticket 190 F: the page script runs on the agency's origin with the member's cookie, so the address it reads and writes,
    # its actions and its agent are the agency's to say, never the client hub's.
    import re
    agency, client = agency_and_client
    mine = client.make("alice", f"# Alice's plan\n\n{MARKER}\n")
    _forging(agency, monkeypatch)
    page = agency.get(f"/Clients/acme/{mine}", member=AG_ALICE)
    assert page.status == 200
    meta = json.loads(re.search(_META, page.text, re.S).group(2))
    config = agency.get(f"/_/mount?doc=Clients/acme/{mine}", member=AG_ALICE).json()["config"]
    for got in (meta, config):
        assert got["doc"] == f"Clients/acme/{mine}"
        assert got["actions"] == [] and got["edit"] is False and got["editable"] == []
        assert got["agent"] is None and got["can"] == [] and got["targets"] == [] and got["lines"] == {}
        assert "work" not in got and "way_back" not in got
