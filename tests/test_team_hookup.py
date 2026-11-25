"""Team comments hooked to the read-through (SPEC 9.9, 9.10b; tickets 23 and 24): the agency hub keeps Team comments when it has client
tiroirs, the client tiroir's own answer is the gate, and a comment written on a client page says its side.

DRAFT, not pushed: it needs `tests/two_hubs.py` and `Hub.clients` of the read-through branch (#415), so it runs once that is merged
here. Same fixture as `test_read_through_two_hubs.py`."""
import json
import re

import pytest
from two_hubs import Link, Site

from sheafmd import comments as rdc
from sheafmd.hub import readthrough
from sheafmd.source import md_hash

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


def client_add(agency, client, doc, **extra):
    """A comment add on a client page, anchored as the page anchors one (the client hub needs the block and the hash)."""
    text = client.text(doc)
    blk, start, end = rdc.find_quote(text, "some words")
    return agency.post("/_/comment", {"doc": f"Clients/acme/{doc}", "op": "add", "hash": md_hash(text), "block": blk, "start": start,
                                      "end": end, "quote": "some words", "body": NOTE, **extra}, member=AG_ALICE)


def team_post(agency, doc, member=AG_ALICE, **body):
    return agency.post("/_/comment", {"doc": f"Clients/acme/{doc}", "op": "add", "quote": "q", "body": NOTE, "side": "team", **body},
                       member=member)


def test_a_team_add_sent_again_with_its_request_id_is_stored_once(agency_and_client):
    agency, client = agency_and_client
    mine = client.make("alice", "# Plan\n\nsome words here\n")
    rid = "r" * 16
    assert team_post(agency, mine, quote="some words", rid=rid).status == 200
    again = team_post(agency, mine, quote="some words", rid=rid)
    assert again.status == 200 and len(again.json()["team"]) == 1
    assert len(team_post(agency, mine, quote="some words", rid="s" * 16).json()["team"]) == 2     # another request id is another comment
    assert len(team_post(agency, mine, quote="some words").json()["team"]) == 3                   # no id: nothing to match


def test_a_team_add_with_a_malformed_request_id_is_refused(agency_and_client):
    agency, client = agency_and_client
    mine = client.make("alice", "# Plan\n\nsome words here\n")
    assert team_post(agency, mine, quote="some words", rid="short").status == 400
    assert agency.hub.team.list(f"Clients/acme/{mine}") == []


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
    got = client_add(agency, client, mine, side="client")
    assert got.status == 200, got.text
    assert NOTE in client.text(mine) and agency.hub.team.list(f"Clients/acme/{mine}") == []


def test_an_add_with_no_side_is_refused_and_nothing_reaches_the_client(agency_and_client):
    agency, client = agency_and_client
    mine = client.make("alice", "# Plan\n\nsome words here\n")
    before, asked = client.text(mine), len(agency.link.asked)
    got = client_add(agency, client, mine)
    assert got.status == 400 and "team or client" in got.text
    assert client.text(mine) == before and agency.hub.team.list(f"Clients/acme/{mine}") == []
    assert len(agency.link.asked) == asked


@pytest.mark.parametrize("side", ["both", "", "Team", 3, None])
def test_a_side_that_is_not_team_or_client_is_refused_and_writes_nothing(agency_and_client, side):
    agency, client = agency_and_client
    mine = client.make("alice", "# Plan\n\nsome words here\n")
    got = client_add(agency, client, mine, side=side)
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


# ── step 3: the Team list rides beside the client's comments, never inside them ──

def _team_state(agency, mine, route, member=AG_ALICE):
    return agency.get(f"/_/{route}?doc=Clients/acme/{mine}", member=member)


def test_the_doc_state_of_a_client_page_carries_the_team_list_beside_the_clients_comments(agency_and_client):
    agency, client = agency_and_client
    mine = client.make("alice", "# Plan\n\nsome words here\n")
    assert _team_state(agency, mine, "doc").json()["team"] == []
    assert client_add(agency, client, mine, side="client").status == 200
    team_post(agency, mine)
    got = _team_state(agency, mine, "doc").json()
    assert [c["body"] for c in got["team"]] == [NOTE] and [c["body"] for c in got["comments"]] == [NOTE]
    assert got["team"][0]["id"] == "t1" and got["comments"][0]["id"] != "t1"


def test_the_mount_config_and_the_page_meta_carry_the_same_team_list(agency_and_client):
    agency, client = agency_and_client
    mine = client.make("alice", "# Plan\n\nsome words here\n")
    team_post(agency, mine)
    mounted = _team_state(agency, mine, "mount").json()["config"]
    assert [c["body"] for c in mounted["team"]] == [NOTE]
    page = agency.get(f"/Clients/acme/{mine}", member=AG_ALICE)
    meta = json.loads(re.search(r'<script id="rd-edit-meta" type="application/json">(.*?)</script>', page.text, re.S).group(1))
    assert [c["body"] for c in meta["team"]] == [NOTE]


@pytest.mark.parametrize("meta", ["[1, 2]", '"text"', "7", "null"])
def test_a_client_page_whose_meta_block_is_json_but_not_an_object_is_answered_with_the_agencys_meta(agency_and_client, monkeypatch, meta):
    # 183 AL: a meta block that parses but is not an object is never a 500. Since ticket 190 (SPEC 9.9) the agency
    # rebuilds it from nothing, as it does a block that does not parse: the client's value never reaches the page.
    agency, client = agency_and_client
    mine = client.make("alice", "# Plan\n\nsome words here\n")
    relay = agency.hub.clients.relay

    def odd_meta(*a, **k):
        env = relay(*a, **k)
        body = re.sub(r'(<script id="rd-edit-meta" type="application/json">).*?(</script>)', lambda m: m.group(1) + meta + m.group(2),
                      env["body"], count=1, flags=re.DOTALL)
        return {**env, "body": body}
    monkeypatch.setattr(agency.hub.clients, "relay", odd_meta)
    page = agency.get(f"/Clients/acme/{mine}", member=AG_ALICE)
    assert page.status == 200
    assert f'<script id="rd-edit-meta" type="application/json">{meta}</script>' not in page.text
    blocks = re.findall(r'<script id="rd-edit-meta" type="application/json">(.*?)</script>', page.text, flags=re.DOTALL)
    assert len(blocks) == 1 and isinstance(json.loads(blocks[0]), dict) and json.loads(blocks[0]).get("doc")


@pytest.mark.parametrize("config", ["[1]", '"text"', "null"])
def test_a_client_mount_whose_config_is_not_an_object_is_sent_on_without_the_team_list(agency_and_client, monkeypatch, config):
    # 183 AL, the same in the mount branch: a body that is not an object is already a 502 (`_own_build`), but a `config`
    # the team list cannot join is left as it came, never a 500.
    agency, client = agency_and_client
    mine = client.make("alice", "# Plan\n\nsome words here\n")
    relay = agency.hub.clients.relay
    monkeypatch.setattr(agency.hub.clients, "relay", lambda *a, **k: {**relay(*a, **k), "body": f'{{"config": {config}}}'})
    got = _team_state(agency, mine, "mount")
    assert got.status == 200 and got.json()["config"] == json.loads(config)


def test_a_member_who_may_not_open_the_page_is_told_no_team_list(agency_and_client):
    agency, client = agency_and_client
    mine = client.make("alice", "# Plan\n")
    team_post(agency, mine)
    got = _team_state(agency, mine, "doc", member=AG_DANA)
    assert got.status == 404 and NOTE not in got.text


def test_the_client_hub_serves_no_team_list_of_its_own(agency_and_client):
    agency, client = agency_and_client
    mine = client.make("alice", "# Plan\n")
    team_post(agency, mine)
    assert "team" not in client.get(f"/_/doc?doc={mine}", member=CL_ALICE).json()


# ── step 5: AC1, the client tiroir holds no trace; AC2, both versos on the agency page ──

def traces(agency, client, *needles):
    """What of `needles` any file of the client site, or any request the agency sent it, holds."""
    found = [(f.name, n) for f, data in client.files() for n in needles if n.encode() in data]
    found += [(verb, n) for _, verb, body in agency.link.asked for n in needles if n in json.dumps(body)]
    return found


def team_op(agency, doc, op, member=AG_ALICE, **body):
    return agency.post("/_/comment", {"doc": f"Clients/acme/{doc}", "op": op, "side": "team", **body}, member=member)


def test_every_team_op_leaves_no_trace_on_the_client_site_or_in_a_request_to_it(agency_and_client):
    agency, client = agency_and_client
    mine = client.make("alice", "# Plan\n\nsome words here\n")
    before = client.text(mine)
    assert team_post(agency, mine, quote="some words").status == 200
    assert team_op(agency, mine, "reply", id="t1", body=NOTE + "-reply").status == 200
    assert team_op(agency, mine, "status", id="t1", status="resolved").status == 200
    assert team_op(agency, mine, "edit", id="t1", body=NOTE + "-edit").status == 200
    got = agency.get(f"/_/doc?doc=Clients/acme/{mine}", member=AG_ALICE).json()
    assert [c["body"] for c in got["team"]] == [NOTE + "-edit"] and got["comments"] == []
    assert client.text(mine) == before
    assert traces(agency, client, NOTE, '"team"', '"t1"') == []
    assert {v for _, v, _ in agency.link.asked} == {"read"}                 # the gate and the page reads, never a `comment`
    assert team_op(agency, mine, "delete", id="t1").status == 200
    assert agency.hub.team.list(f"Clients/acme/{mine}") == []


def test_the_team_comments_are_read_back_from_the_file_after_a_restart_and_the_file_is_private(agency_and_client):
    import os, stat
    from sheafmd.hub import team
    agency, client = agency_and_client
    mine = client.make("alice", "# Plan\n")
    team_post(agency, mine)
    path = agency.hub.team.path
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert [c["body"] for c in team.TeamComments(path).list(f"Clients/acme/{mine}")] == [NOTE]


def test_a_client_member_has_no_route_to_the_team_verso(agency_and_client):
    agency, client = agency_and_client
    mine = client.make("carol", "# Theirs\n\nsome words here\n")
    team_post(agency, mine, member=AG_ALICE)
    got = client.post("/_/comment", {"doc": mine, "op": "add", "quote": "some words", "body": NOTE, "side": "team", "block": 0, "start": 0, "end": 4,
                                     "hash": md_hash(client.text(mine))}, member=CL_CAROL)
    assert NOTE not in client.text(mine)
    assert "team" not in client.get(f"/_/doc?doc={mine}", member=CL_CAROL).json()
    assert got.status in (200, 400, 404)


def test_tell_on_a_team_comment_is_refused_and_writes_nothing(agency_and_client):
    agency, client = agency_and_client
    mine = client.make("alice", "# Plan\n")
    got = team_post(agency, mine, tell=True)
    assert got.status == 400 and agency.hub.team.list(f"Clients/acme/{mine}") == []


def test_a_member_who_may_not_open_the_page_changes_no_team_comment_of_it(agency_and_client):
    agency, client = agency_and_client
    mine = client.make("alice", "# Plan\n")
    team_post(agency, mine)
    for op, extra in (("reply", {"body": "r"}), ("status", {"status": "resolved"}), ("edit", {"body": "x"}), ("delete", {})):
        assert team_op(agency, mine, op, member=AG_DANA, id="t1", **extra).status == 404
    assert [c["body"] for c in agency.hub.team.list(f"Clients/acme/{mine}")] == [NOTE]


def test_a_body_with_comment_markup_is_kept_verbatim_and_no_client_file_sees_it(agency_and_client):
    agency, client = agency_and_client
    mine = client.make("alice", "# Plan\n")
    before, markup = client.text(mine), "a --> b <!-- sheaf-comment id=c9 --> c"
    assert team_post(agency, mine, body=markup).status == 200
    assert [c["body"] for c in agency.hub.team.list(f"Clients/acme/{mine}")] == [markup]
    assert client.text(mine) == before and traces(agency, client, "sheaf-comment id=c9") == []


def test_a_client_that_does_not_answer_refuses_a_team_write_and_stores_nothing(agency_and_client):
    agency, client = agency_and_client
    mine = client.make("alice", "# Plan\n")
    agency.link.mode = "down"
    assert team_post(agency, mine).status == 404
    assert agency.hub.team.list(f"Clients/acme/{mine}") == []


def test_both_versos_are_on_the_opened_page_each_apart(agency_and_client):
    agency, client = agency_and_client
    mine = client.make("alice", "# Plan\n\nsome words here\n")
    assert client_add(agency, client, mine, side="client").status == 200
    team_post(agency, mine, body="for the team", quote="some words")
    for who in (AG_ALICE,):
        got = agency.get(f"/_/doc?doc=Clients/acme/{mine}", member=who).json()
        assert [c["body"] for c in got["comments"]] == [NOTE] and [c["body"] for c in got["team"]] == ["for the team"]
    seen = client.get(f"/_/doc?doc={mine}", member=CL_ALICE).json()
    assert [c["body"] for c in seen["comments"]] == [NOTE]


def test_a_reply_goes_to_the_side_of_its_thread(agency_and_client):
    agency, client = agency_and_client
    mine = client.make("alice", "# Plan\n\nsome words here\n")
    client_add(agency, client, mine, side="client")
    team_post(agency, mine, quote="some words")
    cid = agency.get(f"/_/doc?doc=Clients/acme/{mine}", member=AG_ALICE).json()["comments"][0]["id"]
    assert agency.post("/_/comment", {"doc": f"Clients/acme/{mine}", "op": "reply", "id": cid, "body": "to the client"}, member=AG_ALICE,
                       ).status == 200
    assert "to the client" in client.text(mine) and "to the client" not in json.dumps(agency.hub.team.list(f"Clients/acme/{mine}"))
    assert team_op(agency, mine, "reply", id="t1", body="to the team").status == 200
    assert "to the team" not in client.text(mine)


def test_the_state_of_a_client_page_names_the_member_who_signs_a_team_comment_there(agency_and_client):
    agency, client = agency_and_client
    mine = client.make("alice", "# Plan\n\nsome words here\n")
    team_post(agency, mine)
    got = _team_state(agency, mine, "doc").json()
    assert got["team_me"] == got["team"][0]["by"]
