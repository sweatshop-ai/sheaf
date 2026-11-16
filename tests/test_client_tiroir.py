"""The rules of a client tiroir (SPEC 9.11): a hub whose `[proxy]` says `client = true`. Its agency members (`agency = true`)
are the only members an agent may Share with, and only on `create`; a plain Share is the member's own act from the page or the
Sheaf; no role the front might send opens another member's page. Two agency members, Alice and Bob, and one member of the
client, Carol, through the handler as the proxy sets it (`Front`) and through the door."""
import json
import os
import pwd

import pytest
from helpers import FRONT, Front, door, rpc

from test_share import (ALICE, BOB, CAROL, NAMED, PRIVATE, SHARED, call, doc_of, made, page, read, shared_rows, tick, told)
from sheafmd.hub import proxy
from sheafmd.hub.state import Tokens
from sheafmd.source import md_hash


def build(hub, browser, tmp_path, client):
    for n in ("alice", "bob", "carol"):
        (tmp_path / f"{n}-work").mkdir()
    tokens = {f"{n}-claude": Tokens().add(f"{n}-claude", client="Claude Code", write=True) for n in ("alice", "bob", "carol")}

    def member(name, agency):
        n = name.lower()
        return {"name": name, "short": n, "roots": [str(tmp_path / f"{n}-work")], "tokens": [f"{n}-claude"],
                **({"agency": True} if agency else {})}
    table = {"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock", "proxy_user": pwd.getpwuid(os.getuid()).pw_name,
             "members": {ALICE: member("Alice", True), BOB: member("Bob", True), CAROL: member("Carol", False)}}
    if client is not None:
        table["client"] = client
    hub.proxy = proxy.parse(table, "the test")
    front = Front(hub, browser.handler)
    front.tokens, front.door = tokens, browser
    return front


@pytest.fixture
def agency(hub, browser, tmp_path):
    return build(hub, browser, tmp_path, True)


@pytest.fixture
def plain(hub, browser, tmp_path):
    return build(hub, browser, tmp_path, None)


TICKED = SHARED.replace("[ ]", "[x]")
NAMED_TICKED = NAMED.replace("[ ]", "[x]")


def share(team, member, doc, **extra):
    return team.post("/_/share", {"doc": doc, "hash": md_hash(read(team, doc)), **extra}, member=member)


# ── an agent on `create` ─────────────────────────────────────────────────────

def test_an_agents_plain_share_on_create_is_refused_and_nothing_is_written(agency, tmp_path):
    bad, why = call(agency, "alice", "create", doc="plan.md", text=TICKED)
    assert bad and "agency" in why, why
    assert doc_of(agency, ALICE) == [] and not list(tmp_path.rglob("plan.md"))


def test_an_agents_share_with_an_agency_member_is_accepted(agency):
    doc = made(agency, "alice", NAMED_TICKED)["doc"]
    assert page(agency, BOB, doc).status == 200 and page(agency, CAROL, doc).status == 404
    assert shared_rows(agency, BOB)["rows"][0]["shared_by"] == "Claude Code (Alice)"


@pytest.mark.parametrize("line", ["Share with carol", "Share with bob, carol"])
def test_an_agents_share_naming_a_member_of_the_client_is_refused(agency, line):
    bad, why = call(agency, "alice", "create", doc="plan.md", text=f"# Plan\n\n- [x] {line}\n")
    assert bad and "agency" in why, why
    assert doc_of(agency, CAROL) == [] and doc_of(agency, ALICE) == []


def test_the_clients_own_agent_may_not_share_plain_either(agency):
    bad, why = call(agency, "carol", "create", doc="plan.md", text=TICKED)
    assert bad and "agency" in why, why


def test_an_unticked_share_line_on_create_is_no_share(agency):
    doc = made(agency, "alice", "# Plan\n\n- [ ] Share\n")["doc"]
    assert page(agency, CAROL, doc).status == 404


def test_without_the_flag_an_agent_shares_as_before(plain):
    assert not plain.hub.proxy.client
    doc = made(plain, "alice", TICKED)["doc"]
    assert page(plain, CAROL, doc).status == 200
    other = made(plain, "alice", "# Other\n\n- [x] Share with carol\n", doc="other.md")["doc"]
    assert page(plain, CAROL, other).status == 200


# ── an agent on `update` ─────────────────────────────────────────────────────

def test_an_update_that_returns_the_share_line_unchanged_is_written(agency):
    out = made(agency, "alice", NAMED_TICKED)
    bad, why = call(agency, "alice", "update", doc=out["doc"], text="# Alice's plan\n\n- [x] Share with bob\n\nMore.\n",
                    expected_hash=out["hash"])
    assert not bad, why
    assert "More." in read(agency, out["doc"])


def test_an_update_that_widens_the_names_is_refused(agency):
    out = made(agency, "alice", NAMED_TICKED)
    bad, why = call(agency, "alice", "update", doc=out["doc"], text="# Alice's plan\n\n- [x] Share with bob, carol\n",
                    expected_hash=out["hash"])
    assert bad, why
    assert page(agency, CAROL, out["doc"]).status == 404


@pytest.mark.parametrize("added", ["- [x] Share", "- [ ] Share", "- [x] Share with bob", "- [ ] Share with bob"])
def test_an_update_that_adds_a_share_line_is_refused(agency, added):
    out = made(agency, "alice", PRIVATE)
    bad, why = call(agency, "alice", "update", doc=out["doc"], text=PRIVATE + f"\n{added}\n", expected_hash=out["hash"])
    assert bad and "share" in why.lower(), why
    assert read(agency, out["doc"]) == PRIVATE


def test_an_update_that_ticks_an_unticked_share_line_is_refused(agency):
    out = made(agency, "alice", NAMED)
    bad, why = call(agency, "alice", "update", doc=out["doc"], text=NAMED_TICKED, expected_hash=out["hash"])
    assert bad, why
    assert page(agency, BOB, out["doc"]).status == 404


def test_an_update_that_adds_a_second_unticked_share_line_to_a_shared_page_is_refused(agency):
    out = made(agency, "alice", "# Plan\n\n- [x] Share with bob\n")
    bad, why = call(agency, "alice", "update", doc=out["doc"], text="# Plan\n\n- [x] Share with bob\n- [ ] Share with carol\n",
                    expected_hash=out["hash"])
    assert bad, why


# ── the member's own act ─────────────────────────────────────────────────────

def test_an_agency_members_row_button_shares_plain_to_the_client(agency):
    doc = made(agency, "alice", PRIVATE)["doc"]
    got = share(agency, ALICE, doc)
    assert got.status == 200, got.text
    assert page(agency, CAROL, doc).status == 200 and page(agency, BOB, doc).status == 200


def test_an_agency_members_tick_in_the_page_shares_plain_to_the_client(agency):
    doc = ((_ := made(agency, "alice", "# Plan\n\n- [ ] Share\n"))["doc"])
    assert tick(agency, ALICE, doc, "Share").status == 200
    assert page(agency, CAROL, doc).status == 200


# ── no admin override ────────────────────────────────────────────────────────

@pytest.mark.parametrize("header", [{"X-Sheaf-Role": "admin"}, {"X-Sheaf-Admin": "1"}, {"X-Sheaf-Roles": "admin,user"}])
def test_a_role_the_front_sends_opens_no_page_of_another_member(agency, header):
    doc = made(agency, "carol", PRIVATE)["doc"]
    gone = page(agency, ALICE, "loose-carol/nothing.md")
    got = agency.get(f"/{doc}", member=ALICE, headers=header)
    assert got.status == 404 and got.body == gone.body
    assert agency.get("/_/mount?sheaf=1", member=ALICE, headers=header).json()["sheaf"]["rows"] == []


def test_an_agency_member_lists_what_was_shared_with_them_and_nothing_else(agency):
    shared = made(agency, "carol", "# For the agency\n\n- [x] Share with alice\n", doc="for.md")["doc"]
    made(agency, "carol", "# Private\n\nNot for the agency.\n", doc="mine.md")
    got = shared_rows(agency, ALICE)
    assert [r["doc"] for r in got["rows"]] == [told(agency, ALICE, shared)]
    assert "Private" not in json.dumps(got) and "mine" not in json.dumps(got)


def test_a_page_that_exists_and_one_that_does_not_are_answered_alike(agency):
    doc = made(agency, "carol", PRIVATE)["doc"]
    a, b = page(agency, ALICE, doc), page(agency, ALICE, "loose-carol/never-written.md")
    assert a.status == b.status == 404 and a.body == b.body
