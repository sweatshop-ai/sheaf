"""Team comments hooked to the read-through (SPEC 9.9, 9.10b; tickets 23 and 24): the agency hub keeps Team comments when it has client
tiroirs, the client tiroir's own answer is the gate, and a comment written on a client page says its side.

DRAFT, not pushed: it needs `tests/two_hubs.py` and `Hub.clients` of the read-through branch (#415), so it runs once that is merged
here. Same fixture as `test_read_through_two_hubs.py`."""
import json

import pytest
from two_hubs import Link, Site

from sheafmd.hub import readthrough

CLIENT_ORIGIN = "https://acme.example.com"
AG_ALICE, AG_DANA = ("a1000000-0000-4000-8000-00000000000%d" % n for n in (1, 3))
CL_ALICE, CL_CAROL = ("c1000000-0000-4000-8000-00000000000%d" % n for n in (1, 3))
NOTE = "team-note-5531"


@pytest.fixture
def agency_and_client(tmp_path):
    client = Site(tmp_path, "client", 27421, CLIENT_ORIGIN, {
        CL_ALICE: ("Alice", "alice@example.com", True), CL_CAROL: ("Carol", "carol@acme.example.com", False)}, client=True)
    agency = Site(tmp_path, "agency", 27422, "https://tt.example.com", {
        AG_ALICE: ("Alice", "alice@example.com", False), AG_DANA: ("Dana", "dana@example.com", False)},
        clients={"acme": CLIENT_ORIGIN})
    agency.link = Link(client, client.peer_token("https://tt.example.com", ["read"], name="agency-link"))
    with agency.inside():
        agency.hub.clients = readthrough.Clients(agency.hub.proxy.clients, agency.link)
        agency.hub.keep_team()               # what Hub.__init__ does when [proxy.clients] is set
    return agency, client


def team_post(agency, doc, **body):
    return agency.post("/_/comment", {"doc": f"Clients/acme/{doc}", "op": "add", "quote": "q", "body": NOTE, "side": "team", **body},
                       member=AG_ALICE)


# ── step 1: the store is kept at start, and the client tiroir is the gate ────

def test_a_hub_with_client_tiroirs_keeps_team_comments_in_its_state_folder(agency_and_client):
    agency, _ = agency_and_client
    assert agency.hub.team is not None and agency.hub.team.path.name == "team-comments.json"
    assert agency.hub.team.path.parent == agency.home or agency.home in agency.hub.team.path.parents


def test_a_hub_with_no_client_tiroirs_keeps_none(tmp_path):
    plain = Site(tmp_path, "plain", 27423, "https://p.example.com", {AG_ALICE: ("Alice", "alice@example.com", False)})
    assert plain.hub.team is None


def test_the_gate_is_what_the_client_tiroir_says_the_member_may_open(agency_and_client):
    agency, client = agency_and_client
    mine = client.make("alice", "# Plan\n")
    gate = agency.hub.team_gate
    assert gate(agency.hub.proxy.members[AG_ALICE], f"Clients/acme/{mine}") is True
    assert gate(agency.hub.proxy.members[AG_DANA], f"Clients/acme/{mine}") is False          # no account there
    assert gate(agency.hub.proxy.members[AG_ALICE], "Clients/acme/alice-work/none.md") is False
    assert gate(agency.hub.proxy.members[AG_ALICE], "Clients/nobody/x.md") is False         # not a configured client


def test_a_client_that_does_not_answer_is_a_gate_that_says_no(agency_and_client):
    agency, client = agency_and_client
    mine = client.make("alice", "# Plan\n")
    agency.link.mode = "down"
    assert agency.hub.team_gate(agency.hub.proxy.members[AG_ALICE], f"Clients/acme/{mine}") is False


# ── step 2: the side of a comment written on a client page ───────────────────

def test_a_team_side_comment_stays_on_the_agency_hub_and_no_call_reaches_the_client(agency_and_client):
    agency, client = agency_and_client
    mine = client.make("alice", "# Plan\n")
    before, asked = client.text(mine), len(agency.link.asked)
    got = team_post(agency, mine)
    assert got.status == 200, got.text
    assert [c["body"] for c in agency.hub.team.list(f"Clients/acme/{mine}")] == [NOTE]
    assert [v for _, v, _ in agency.link.asked[asked:]] == ["read"]                 # the gate's `open`, never a `comment`
    assert client.text(mine) == before and not any(NOTE.encode() in data for _, data in client.files())


def test_a_client_side_comment_is_written_on_the_client_hub_under_the_members_name(agency_and_client):
    agency, client = agency_and_client
    mine = client.make("alice", "# Plan\n\nsome words here\n")
    got = agency.post("/_/comment", {"doc": f"Clients/acme/{mine}", "op": "add", "quote": "some words", "body": NOTE, "side": "client"},
                      member=AG_ALICE)
    assert got.status == 200, got.text
    assert NOTE in client.text(mine) and agency.hub.team.list(f"Clients/acme/{mine}") == []


def test_no_side_is_the_client_side_as_before(agency_and_client):
    agency, client = agency_and_client
    mine = client.make("alice", "# Plan\n\nsome words here\n")
    got = agency.post("/_/comment", {"doc": f"Clients/acme/{mine}", "op": "add", "quote": "some words", "body": NOTE}, member=AG_ALICE)
    assert got.status == 200 and NOTE in client.text(mine)


@pytest.mark.parametrize("side", ["both", "", "Team", 3, None])
def test_a_side_that_is_not_team_or_client_is_refused_and_writes_nothing(agency_and_client, side):
    agency, client = agency_and_client
    mine = client.make("alice", "# Plan\n\nsome words here\n")
    got = agency.post("/_/comment", {"doc": f"Clients/acme/{mine}", "op": "add", "quote": "some words", "body": NOTE, "side": side},
                      member=AG_ALICE)
    assert got.status == 400
    assert NOTE not in client.text(mine) and agency.hub.team.list(f"Clients/acme/{mine}") == []


def test_a_team_comment_on_a_page_the_member_may_not_open_is_a_missing_page(agency_and_client):
    agency, client = agency_and_client
    mine = client.make("alice", "# Plan\n")
    got = agency.post("/_/comment", {"doc": f"Clients/acme/{mine}", "op": "add", "quote": "q", "body": NOTE, "side": "team"},
                      member=AG_DANA)
    assert got.status == 404 and agency.hub.team.list(f"Clients/acme/{mine}") == []


def test_a_team_id_is_never_sent_to_the_client_and_a_client_id_never_reaches_the_team_store(agency_and_client):
    agency, client = agency_and_client
    mine = client.make("alice", "# Plan\n")
    team_post(agency, mine)
    asked = len(agency.link.asked)
    got = agency.post("/_/comment", {"doc": f"Clients/acme/{mine}", "op": "reply", "id": "t1", "body": "r", "side": "team"}, member=AG_ALICE)
    assert got.status == 200 and [v for _, v, _ in agency.link.asked[asked:]] == ["read"]
    wrong = agency.post("/_/comment", {"doc": f"Clients/acme/{mine}", "op": "reply", "id": "c1", "body": "r", "side": "team"}, member=AG_ALICE)
    assert wrong.status == 400
