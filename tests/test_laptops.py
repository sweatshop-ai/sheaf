"""Connect a laptop (SPEC 9.7, 9.12): a member names a laptop and the hub makes an agent token for that laptop and
that member, shows the one line that connects it, lists the member's laptops and revokes one by name. The hub checks
the token on every request (tokens.json is read afresh), so a revoked token is refused at once and a token never sees
more than its member does. In memory through the handler in proxy mode (`front`)."""
import json
import re

import pytest
from helpers import BEA, CAL, FRONT, call, door, refused, rpc

from sheafmd.hub.state import Tokens

TOKEN = re.compile(r"sheaf_mcp_[A-Za-z0-9_-]{43}")


@pytest.fixture
def mine(front, plan, other):
    """Bea's `work/plan.md` and Cal's `other/notes.md`, both registered."""
    from helpers import PLAN
    (other / "notes.md").write_text(PLAN, encoding="utf-8")
    front.hub.roots.for_document(other / "notes.md")
    return front


def connect(front, name="Work MacBook", member=BEA):
    got = front.post("/_/laptops", {"name": name}, member=member)
    assert got.status == 200, got.text
    return got.json()


def read_as(browser, token, doc):
    res = door(browser, rpc("tools/call", {"name": "read", "arguments": {"doc": doc}}), token=token, as_name=None)
    return res


def test_connect_a_laptop_returns_one_line_that_holds_the_front_and_the_token(mine):
    made = connect(mine)
    [token] = set(TOKEN.findall(json.dumps(made)))
    assert made["command"] == f"sheaf connect {FRONT} {token}"
    assert made["name"] == "Work MacBook"


def test_the_token_opens_the_door_for_its_member_and_signs_as_the_client(mine, browser):
    token = connect(mine)["token"]
    is_error, got = call(browser, "read", token=token, doc="work/plan.md")
    assert not is_error and got["doc"] == "work/plan.md"
    row = Tokens().verify(token)
    assert row.client == "Claude Code" and row.member == BEA and row.laptop == "Work MacBook"
    assert row.signed("hub", mine.hub.proxy) == "Claude Code (Bea)"


def test_the_token_never_exceeds_its_members_access(mine, browser):
    token = connect(mine)["token"]
    assert refused(browser, "read", token=token, doc="other/notes.md")
    cal = connect(mine, "Cal's laptop", member=CAL)["token"]
    assert call(browser, "read", token=cal, doc="other/notes.md")[0] is False
    assert refused(browser, "read", token=cal, doc="work/plan.md")


def test_revoke_by_name_and_the_next_call_gets_401(mine, browser):
    token = connect(mine)["token"]
    assert read_as(browser, token, "work/plan.md").status == 200
    got = mine.post("/_/laptops/revoke", {"name": "Work MacBook"})
    assert got.status == 200
    assert read_as(browser, token, "work/plan.md").status == 401


def test_a_member_revokes_only_their_own_laptops(mine, browser):
    token = connect(mine)["token"]
    got = mine.post("/_/laptops/revoke", {"name": "Work MacBook"}, member=CAL)
    assert got.status == 404
    assert read_as(browser, token, "work/plan.md").status == 200


def test_the_list_names_the_laptops_of_the_member_and_never_a_token(mine):
    connect(mine, "Work MacBook")
    connect(mine, "Home desktop")
    connect(mine, "Cal's laptop", member=CAL)
    got = mine.get("/_/laptops")
    assert got.status == 200
    names = [x["name"] for x in got.json()["laptops"]]
    assert sorted(names) == ["Home desktop", "Work MacBook"]
    assert "sheaf_mcp_" not in got.text
    assert all(x["created"] for x in got.json()["laptops"])


def test_a_laptop_name_is_unique_for_the_member_and_free_for_another(mine):
    connect(mine)
    again = mine.post("/_/laptops", {"name": "work macbook"})
    assert again.status == 409
    assert connect(mine, "Work MacBook", member=CAL)


@pytest.mark.parametrize("name", ["", "   ", "a" * 61, "x\x00y", 5, None])
def test_a_laptop_name_is_a_short_line_of_text(mine, name):
    assert mine.post("/_/laptops", {"name": name}).status == 400
    assert mine.get("/_/laptops").json()["laptops"] == []


def test_a_revoked_name_can_be_used_again_and_the_old_token_stays_dead(mine, browser):
    old = connect(mine)["token"]
    mine.post("/_/laptops/revoke", {"name": "Work MacBook"})
    new = connect(mine)["token"]
    assert read_as(browser, old, "work/plan.md").status == 401
    assert read_as(browser, new, "work/plan.md").status == 200


def test_a_laptop_route_is_the_proxy_sockets_alone(mine, browser):
    assert browser.request("POST", "/_/laptops", body={"name": "x"}, key=True).status == 404
    assert browser.request("GET", "/_/laptops", key=True).status == 404


def test_two_laptops_of_a_member_sign_alike_and_the_hub_still_starts(mine):
    from sheafmd.hub import proxy
    connect(mine, "Work MacBook")
    connect(mine, "Home desktop")
    connect(mine, "Cal's laptop", member=CAL)
    rows = mine.hub.tokens.list()
    assert {r.signed("hub", mine.hub.proxy) for r in rows} == {"Claude Code (Bea)", "Claude Code (Cal)"}
    proxy.check_start_names(mine.hub.proxy, "hub", rows)       # no TokenNamesError: the hub starts


def test_a_laptop_that_would_sign_as_another_token_already_does_is_refused_not_left_to_stop_the_hub(mine, browser):
    """A configured token of Bea's for the same client signs `Claude Code (Bea)` already: the second would stop the
    hub at its next start (9.7), so the make is refused and says why."""
    import dataclasses
    mine.hub.tokens.add("bea-claude", client="Claude Code")
    members = {k: (dataclasses.replace(m, tokens=("bea-claude",)) if k == BEA else m) for k, m in mine.hub.proxy.members.items()}
    mine.hub.proxy = dataclasses.replace(mine.hub.proxy, members=members)
    got = mine.post("/_/laptops", {"name": "Work MacBook"})
    assert got.status == 409 and "Claude Code (Bea)" in got.text
    assert mine.get("/_/laptops").json()["laptops"] == []


def test_the_token_is_nowhere_in_the_state_folder_the_log_or_the_list(mine):
    from sheafmd import paths
    token = connect(mine)["token"]
    mine.get("/_/laptops")
    mine.post("/_/laptops/revoke", {"name": "Work MacBook"})
    for f in paths.state_dir().rglob("*"):
        if f.is_file():
            assert token.encode() not in f.read_bytes(), f


def test_whoami_names_the_member_of_a_token_and_nothing_else(mine, browser):
    """What a door in front of the hub asks to route a laptop's bearer: the member it was made for."""
    token = connect(mine)["token"]
    got = browser.request("GET", "/_/whoami", cookie=False, headers={"Authorization": f"Bearer {token}"})
    assert got.status == 200 and got.json() == {"member": BEA, "name": "Bea"}
    mine.post("/_/laptops/revoke", {"name": "Work MacBook"})
    assert browser.request("GET", "/_/whoami", cookie=False, headers={"Authorization": f"Bearer {token}"}).status == 401


def test_whoami_is_not_for_the_key_a_cookie_or_a_token_bound_to_no_member(mine, browser):
    assert browser.request("GET", "/_/whoami", cookie=False, key=True).status == 403
    assert browser.request("GET", "/_/whoami").status == 403
    free = mine.hub.tokens.add("free", client="Claude Code", write=True)
    assert browser.request("GET", "/_/whoami", cookie=False, headers={"Authorization": f"Bearer {free}"}).status == 404


def test_a_token_whose_member_the_table_no_longer_names_is_refused_not_read_as_unbound(mine, browser):
    token = connect(mine)["token"]
    assert read_as(browser, token, "work/plan.md").status == 200
    del mine.hub.proxy.members[BEA]
    assert read_as(browser, token, "work/plan.md").status == 401


def test_laptops_of_members_the_table_no_longer_names_do_not_stop_the_hub_from_starting(mine):
    from sheafmd.hub import proxy
    connect(mine, "Work MacBook")
    connect(mine, "Cal's laptop", member=CAL)
    rows = mine.hub.tokens.list()
    del mine.hub.proxy.members[BEA]
    del mine.hub.proxy.members[CAL]
    proxy.check_start_names(mine.hub.proxy, "hub", rows)       # both laptops sign the hub's person: left out, no clash
    proxy.check_start_names(None, "hub", rows)                 # proxy mode off: the same


def test_a_members_laptops_are_told_apart_in_the_tell_choices(mine):
    from sheafmd.hub import targets
    connect(mine, "Work MacBook")
    connect(mine, "Home desktop")
    member = mine.hub.proxy.members[BEA]
    labels = [c["label"] for c in targets.choices(mine.hub, "x", member)]
    assert sorted(labels) == ["Claude Code (Bea) · Home desktop", "Claude Code (Bea) · Work MacBook"]


def test_a_laptop_of_a_member_the_table_no_longer_names_is_not_counted_among_the_names_others_sign(mine):
    from sheafmd import cli
    connect(mine, "Work MacBook")
    rows = mine.hub.tokens.list()
    assert cli._signed_by_others(rows, mine.hub.proxy, "hub") == ["Claude Code (Bea)"]
    del mine.hub.proxy.members[BEA]
    assert cli._signed_by_others(rows, mine.hub.proxy, "hub") == []
