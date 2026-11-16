"""Share and Share with on a loose page (SPEC 9.11), and "Shared with me" in the Sheaf view (8.6). Three members of one
tiroir, Alice, Bob and Carol, each with a door token, through the handler as the proxy sets it after the verifier's 2xx
(`Front`: `X-Sheaf-Member` from the verifier, never from the browser) and through the door. Visibility is the risk: a
Share reaches the named member only, a withdrawn Share removes access at once, and a member never sees another's
private page, nor the name of its folder."""
import json
import os
import pwd

import pytest
from helpers import FRONT, Front, door, rpc

import sheafmd.comments as rdc
from sheafmd.edit import ticked_html
from sheafmd.blocks import split_md_blocks
from sheafmd.hub import proxy, the_list
from sheafmd.hub.state import Tokens
from sheafmd.hub.visibility import audience
from sheafmd.source import md_hash

ALICE = "503b2f77-83de-452c-817a-a357faf85929"
BOB = "2b9d7e1c-4a51-4c0e-9d1f-6f0c3a7e8b42"
CAROL = "9a1f3c52-6d0e-4b7a-8c25-1e4f7b3d9a60"
OUTSIDER = "d41d8cd9-8f00-4b20-8e98-0998ecf8427e"            # a user the front knows, who is no member of this tiroir

PRIVATE = "# Alice's notes\n\nNothing for anyone else.\n"
SHARED = "# Alice's plan\n\n- [ ] Share\n\nA plan.\n"
NAMED = "# Alice's plan\n\n- [ ] Share with bob\n\nA plan.\n"


@pytest.fixture
def team(hub, browser, tmp_path):
    for n in ("alice", "bob", "carol"):
        (tmp_path / f"{n}-work").mkdir()
    tokens = {f"{n}-claude": Tokens().add(f"{n}-claude", client="Claude Code", write=True)
              for n in ("alice", "bob", "carol")}
    hub.proxy = proxy.parse({"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock",
                             "proxy_user": pwd.getpwuid(os.getuid()).pw_name,
                             "members": {ALICE: {"name": "Alice", "short": "alice", "roots": [str(tmp_path / "alice-work")], "tokens": ["alice-claude"]},
                                         BOB: {"name": "Bob", "short": "bob", "roots": [str(tmp_path / "bob-work")], "tokens": ["bob-claude"]},
                                         CAROL: {"name": "Carol", "short": "carol", "roots": [str(tmp_path / "carol-work")], "tokens": ["carol-claude"]}}},
                            "the test")
    front = Front(hub, browser.handler)
    front.tokens, front.door = tokens, browser
    return front


def call(team, who, tool, **args):
    res = door(team.door, rpc("tools/call", {"name": tool, "arguments": args}), token=team.tokens[f"{who}-claude"], as_name=None)
    assert res.status == 200, res.text
    out = res.json()["result"]
    return out["isError"], out["content"][0]["text"]


def made(team, who, text, doc="plan.md"):
    bad, out = call(team, who, "create", doc=doc, text=text)
    assert not bad, out
    return json.loads(out)


def told(team, member, doc):
    """The name under which the hub tells `member` of the page `doc` (9.11)."""
    return team.hub.alias(team.hub.proxy.members[member], doc)


def page(team, member, doc):
    return team.get(f"/{doc}", member=member)


def read(team, doc):
    return team.hub.file(doc).read_text(encoding="utf-8")


def line_edit(text, prefix, tick=True):
    """The page's edit that ticks (unticks) the box of the line that starts with `prefix`."""
    lines = text.split("\n")
    labels = [ln.lstrip("-*+ ").lstrip("[xX ]").lstrip() for ln in lines]
    n = next((i for i, ln in enumerate(labels) if ln == prefix), None)
    if n is None:
        n = next(i for i, ln in enumerate(labels) if ln.startswith(prefix + " "))
    at = the_list._place(text, n, split_md_blocks(text))
    return {"i": at[0], "html": ticked_html(split_md_blocks(text)[at[0]], at[1], tick=tick, at=at[2])}


def tick(team, member, doc, prefix, release=False):
    text = read(team, doc)
    return team.post("/_/save", {"doc": doc, "hash": md_hash(text), "edits": [line_edit(text, prefix, not release)]},
                     member=member)


def shared_rows(team, member):
    got = team.get("/_/mount?sheaf=1", member=member)
    assert got.status == 200, got.text
    return got.json()["sheaf"]


def doc_of(team, member):
    return [r["doc"] for r in shared_rows(team, member)["rows"]]


# ── nothing is Shared until the owner says so ────────────────────────────────

def test_a_loose_page_is_its_owners_alone(team):
    doc = made(team, "alice", PRIVATE)["doc"]
    assert page(team, ALICE, doc).status == 200
    gone = page(team, BOB, "loose-alice/nothing.md")
    got = page(team, BOB, doc)
    assert got.status == 404 and got.body == gone.body
    assert doc_of(team, BOB) == [] and shared_rows(team, BOB)["tree"] == []


def test_a_sign_in_the_tiroir_does_not_know_reaches_nothing(team):
    doc = made(team, "alice", SHARED)["doc"]
    assert tick(team, ALICE, doc, "Share").status == 200
    assert page(team, OUTSIDER, doc).status in (401, 403, 404)
    assert page(team, None, doc).status in (401, 403, 404)


# ── Share and Share with ─────────────────────────────────────────────────────

def test_share_opens_a_loose_page_to_every_member_of_the_tiroir(team):
    doc = made(team, "alice", SHARED)["doc"]
    assert tick(team, ALICE, doc, "Share").status == 200
    assert "- [x] Share" in read(team, doc)
    assert page(team, BOB, doc).status == 200 and page(team, CAROL, doc).status == 200


def test_share_with_opens_it_to_the_named_members_only(team):
    doc = made(team, "alice", NAMED)["doc"]
    assert page(team, BOB, doc).status == 404
    assert tick(team, ALICE, doc, "Share with").status == 200
    assert page(team, BOB, doc).status == 200
    assert page(team, CAROL, doc).status == 404


def test_a_member_who_is_not_named_sees_neither_the_page_nor_the_folder_name(team):
    doc = made(team, "alice", NAMED.replace("Alice's plan", "Quiet plan"))["doc"]
    tick(team, ALICE, doc, "Share with")
    got = shared_rows(team, CAROL)
    assert got["rows"] == [] and got["tree"] == []
    assert "alice" not in json.dumps(got) and "Quiet plan" not in json.dumps(got)
    assert doc not in team.get("/_/index.json", member=CAROL).text
    assert "alice" not in team.get("/_/index.json", member=CAROL).text


def test_the_recipient_finds_it_in_shared_with_me_under_the_owner(team):
    doc = made(team, "alice", NAMED)["doc"]
    tick(team, ALICE, doc, "Share with")
    got = shared_rows(team, BOB)
    assert [n["name"] for n in got["tree"]] == ["Shared with me"]
    assert [n["name"] for n in got["tree"][0]["children"]] == ["alice"]
    row = got["rows"][0]
    assert row["doc"] == told(team, BOB, doc) != doc and row["folder"] == "Shared with me/alice" and row["title"] == "Alice's plan"
    assert row["root"] == "Shared with me"


def test_a_shared_page_is_new_until_the_recipient_opens_it_and_new_again_when_it_changes(team):
    doc = made(team, "alice", NAMED)["doc"]
    tick(team, ALICE, doc, "Share with")
    assert shared_rows(team, BOB)["rows"][0]["new"] is True
    assert team.get(f"/_/doc?doc={doc}", member=BOB).status == 200
    assert shared_rows(team, BOB)["rows"][0]["new"] is False
    os.utime(team.hub.file(doc), (1, 1_900_000_000))
    assert shared_rows(team, BOB)["rows"][0]["new"] is True


def test_the_owners_folder_names_are_not_in_what_the_recipient_sees(team):
    bad, out = call(team, "alice", "create", doc="plan.md", text=NAMED, folder="private-matters/deep")
    doc = json.loads(out)["doc"]
    tick(team, ALICE, doc, "Share with")
    tree = shared_rows(team, BOB)["tree"]
    assert "private-matters" not in json.dumps(tree) and "deep" not in json.dumps(tree)
    assert [r["folder"] for r in shared_rows(team, BOB)["rows"]] == ["Shared with me/alice"]


def test_the_owners_other_pages_stay_hidden_from_the_recipient(team):
    mine = made(team, "alice", PRIVATE, doc="mine.md")["doc"]
    doc = made(team, "alice", NAMED)["doc"]
    tick(team, ALICE, doc, "Share with")
    assert doc_of(team, BOB) == [told(team, BOB, doc)]
    assert page(team, BOB, mine).status == 404


def test_withdrawing_the_share_removes_access_at_once(team):
    doc = made(team, "alice", NAMED)["doc"]
    tick(team, ALICE, doc, "Share with")
    assert page(team, BOB, doc).status == 200
    assert tick(team, ALICE, doc, "Share with", release=True).status == 200
    assert page(team, BOB, doc).status == 404 and doc_of(team, BOB) == []


def test_editing_the_names_off_the_line_removes_access_at_once(team):
    doc = made(team, "alice", NAMED)["doc"]
    tick(team, ALICE, doc, "Share with")
    team.hub.file(doc).write_text(read(team, doc).replace("Share with bob", "Share with carol"), encoding="utf-8")
    assert page(team, BOB, doc).status == 404 and page(team, CAROL, doc).status == 200


# ── what a recipient may do, and may not ─────────────────────────────────────

def test_a_recipient_comments_and_saves_on_a_shared_page(team):
    doc = made(team, "alice", NAMED + "\nA paragraph.\n")["doc"]
    tick(team, ALICE, doc, "Share with")
    text = read(team, doc)
    blocks = split_md_blocks(text)
    i = next(n for n, b in enumerate(blocks) if b.content.strip() == "A paragraph.")
    got = team.post("/_/save", {"doc": doc, "hash": md_hash(text), "edits": [{"i": i, "html": "<p>A paragraph, edited.</p>"}]},
                    member=BOB)
    assert got.status == 200 and "A paragraph, edited." in read(team, doc)


def test_a_recipient_cannot_withdraw_the_share(team):
    doc = made(team, "alice", NAMED)["doc"]
    tick(team, ALICE, doc, "Share with")
    got = tick(team, BOB, doc, "Share with", release=True)
    assert got.status == 409 and "owner" in got.text
    assert "- [x] Share with bob" in read(team, doc)


def test_a_recipient_cannot_widen_the_share_by_editing_the_names(team):
    doc = made(team, "alice", NAMED)["doc"]
    tick(team, ALICE, doc, "Share with")
    text = read(team, doc)
    i = next(n for n, b in enumerate(split_md_blocks(text)) if "Share with" in b.content)
    got = team.post("/_/save", {"doc": doc, "hash": md_hash(text),
                                "edits": [{"i": i, "html": '<ul class="task-list"><li><input type="checkbox" checked disabled>'
                                                           ' Share with bob, carol</li></ul>'}]}, member=BOB)
    assert got.status == 409, got.text
    assert audience(read(team, doc)) == frozenset({"bob"})
    assert page(team, CAROL, doc).status == 404


def test_a_recipient_cannot_tick_share_on_a_page_they_were_given(team):
    doc = made(team, "alice", NAMED + "\n- [ ] Share\n")["doc"]
    tick(team, ALICE, doc, "Share with")
    got = tick(team, BOB, doc, "Share")
    assert got.status == 409 and page(team, CAROL, doc).status == 404


def test_a_recipient_cannot_write_a_new_page_into_the_owners_root(team):
    doc = made(team, "alice", NAMED)["doc"]
    tick(team, ALICE, doc, "Share with")
    bad, why = call(team, "bob", "create", doc="loose-alice/2026-11/bobs.md", text="# Bob\n")
    assert bad, why
    assert not os.path.exists(team.hub.file(doc).parent / "bobs.md")


def test_a_recipients_agent_sees_the_shared_page_through_the_door(team):
    doc = made(team, "alice", NAMED)["doc"]
    bad, why = call(team, "bob", "read", doc=doc)
    assert bad, "not shared yet"
    tick(team, ALICE, doc, "Share with")
    bad, out = call(team, "bob", "read", doc=doc)
    assert not bad and "Alice's plan" in out
    bad, listing = call(team, "bob", "documents", open_only=False)
    assert told(team, BOB, doc) in listing and doc not in listing
    bad, why = call(team, "carol", "read", doc=doc)
    assert bad
    bad, listing = call(team, "carol", "documents", open_only=False)
    assert doc not in listing and "alice" not in listing


# ── the agent's Share: only on create ────────────────────────────────────────

def test_an_agent_create_with_a_ticked_share_line_shares_and_the_row_says_by_whom(team):
    doc = made(team, "alice", "# Agent page\n\n- [x] Share with bob\n")["doc"]
    assert page(team, BOB, doc).status == 200 and page(team, CAROL, doc).status == 404
    row = shared_rows(team, BOB)["rows"][0]
    assert row["shared_by"] == "Claude Code (Alice)"


def test_an_agent_update_that_adds_a_share_line_is_refused(team):
    out = made(team, "alice", PRIVATE)
    bad, why = call(team, "alice", "update", doc=out["doc"], text=PRIVATE + "\n- [x] Share with bob\n", expected_hash=out["hash"])
    assert bad, why
    assert read(team, out["doc"]) == PRIVATE and page(team, BOB, out["doc"]).status == 404


def test_an_agent_update_that_widens_the_names_is_refused(team):
    out = made(team, "alice", "# Agent page\n\n- [x] Share with bob\n")
    bad, why = call(team, "alice", "update", doc=out["doc"], text="# Agent page\n\n- [x] Share\n", expected_hash=out["hash"])
    assert bad, why
    assert page(team, CAROL, out["doc"]).status == 404


def test_a_recipients_agent_cannot_change_the_share_line(team):
    doc = made(team, "alice", "# Agent page\n\n- [x] Share with bob\n")
    bad, why = call(team, "bob", "update", doc=doc["doc"], text="# Agent page\n\n- [x] Share with bob, carol\n",
                    expected_hash=doc["hash"])
    assert bad, why
    assert page(team, CAROL, doc["doc"]).status == 404


def test_an_agent_update_that_leaves_the_share_line_alone_is_written(team):
    out = made(team, "alice", "# Agent page\n\n- [x] Share with bob\n")
    bad, why = call(team, "alice", "update", doc=out["doc"], text="# Agent page\n\n- [x] Share with bob\n\nMore.\n",
                    expected_hash=out["hash"])
    assert not bad, why
    assert "More." in read(team, out["doc"])


def test_an_agent_update_that_names_fewer_members_is_written(team):
    out = made(team, "alice", "# Agent page\n\n- [x] Share with bob, carol\n")
    bad, why = call(team, "alice", "update", doc=out["doc"], text="# Agent page\n\n- [x] Share with bob\n",
                    expected_hash=out["hash"])
    assert not bad, why
    assert page(team, CAROL, out["doc"]).status == 404 and page(team, BOB, out["doc"]).status == 200


def test_widens_says_when_a_page_is_opened_to_more_members():
    from sheafmd.hub.visibility import widens
    names = frozenset
    assert widens(None, True) and widens(None, names({"bob"})) and widens(names({"bob"}), True)
    assert widens(names({"bob"}), names({"bob", "carol"}))
    assert not widens(True, True) and not widens(True, names({"bob"})) and not widens(None, None)
    assert not widens(names({"bob", "carol"}), names({"bob"})) and not widens(True, None)


# ── the Share line itself ────────────────────────────────────────────────────

def test_audience_reads_the_ticked_share_lines_only():
    assert audience("# x\n\n- [ ] Share\n") is None
    assert audience("# x\n\n- [x] Share\n") is True
    assert audience("# x\n\n- [x] Share with Bob, carol\n") == frozenset({"bob", "carol"})
    assert audience("# x\n\n- [x] Share with bob\n- [x] Share\n") is True
    assert audience("# x\n\n```\n- [x] Share\n```\n") is None
    assert audience("# x\n\n- [ ] Share with bob\n") is None
    assert audience("# x\n\nShare with bob\n") is None


# ── the row's Share button: POST /_/share writes the line ────────────────────

def share(team, member, doc, **extra):
    return team.post("/_/share", {"doc": doc, "hash": md_hash(read(team, doc)), **extra}, member=member)


def test_the_row_button_appends_a_share_line_and_opens_the_page_to_every_member(team):
    doc = made(team, "alice", PRIVATE)["doc"]
    got = share(team, ALICE, doc)
    assert got.status == 200, got.text
    assert "- [x] Share\n" in read(team, doc)
    assert audience(read(team, doc)) is True
    assert page(team, BOB, doc).status == 200 and page(team, CAROL, doc).status == 200


def test_the_row_button_with_names_opens_the_page_to_those_members_only(team):
    doc = made(team, "alice", PRIVATE)["doc"]
    assert share(team, ALICE, doc, **{"with": ["bob"]}).status == 200
    assert "- [x] Share with bob" in read(team, doc)
    assert page(team, BOB, doc).status == 200 and page(team, CAROL, doc).status == 404


def test_the_row_button_keeps_the_title_first_and_the_rest_of_the_page(team):
    doc = made(team, "alice", PRIVATE)["doc"]
    share(team, ALICE, doc)
    text = read(team, doc)
    assert text.index("# Alice's notes") < text.index("Share") < text.index("Nothing for anyone else.")


def test_the_row_button_ticks_an_unticked_share_line_instead_of_adding_a_second(team):
    doc = made(team, "alice", SHARED)["doc"]
    assert share(team, ALICE, doc).status == 200
    assert read(team, doc).count("Share") == 1 and "- [x] Share" in read(team, doc)


def test_the_row_button_refuses_a_stale_hash_and_writes_nothing(team):
    doc = made(team, "alice", PRIVATE)["doc"]
    before = read(team, doc)
    got = team.post("/_/share", {"doc": doc, "hash": md_hash("# Something else\n")}, member=ALICE)
    assert got.status == 409 and read(team, doc) == before
    assert page(team, BOB, doc).status == 404


def test_the_row_button_is_the_owners_alone(team):
    doc = made(team, "alice", NAMED)["doc"]
    tick(team, ALICE, doc, "Share with")
    before = read(team, doc)
    got = share(team, BOB, doc)
    assert got.status == 409 and "owner" in got.text and read(team, doc) == before


def test_the_row_button_refuses_a_page_that_is_already_shared(team):
    doc = made(team, "alice", SHARED)["doc"]
    share(team, ALICE, doc)
    before = read(team, doc)
    got = share(team, ALICE, doc)
    assert got.status == 409 and read(team, doc) == before


def test_the_row_button_refuses_a_name_that_is_not_a_short_name(team):
    doc = made(team, "alice", PRIVATE)["doc"]
    for bad in (["bob, carol\n- [x] Share"], "bob", [""], [3]):
        assert share(team, ALICE, doc, **{"with": bad}).status == 400
    assert read(team, doc) == PRIVATE


def test_the_row_button_writes_a_line_of_the_write_log(team):
    doc = made(team, "alice", PRIVATE)["doc"]
    share(team, ALICE, doc)
    lines = team.get(f"/_/writes?doc={doc}", member=ALICE).json()["lines"]
    assert [l["via"] for l in lines][-2:] == ["share", "save"] and {l["writer"] for l in lines[-2:]} == {"Alice"}


def test_a_row_carries_the_hash_to_share_against_only_for_an_own_page_no_share_line_opens(team):
    mine = made(team, "alice", PRIVATE, doc="mine.md")["doc"]
    open_ = made(team, "alice", SHARED, doc="open.md")["doc"]
    tick(team, ALICE, open_, "Share")
    rows = {r["doc"]: r for r in shared_rows(team, ALICE)["rows"]}
    assert rows[mine]["share"] == md_hash(read(team, mine)) and rows[open_]["share"] == ""
    assert [r["share"] for r in shared_rows(team, BOB)["rows"]] == [""]          # a page given to Bob is not his to Share


# ── the review's findings (PR 394, round 1) ──────────────────────────────────

def test_an_agent_create_that_holds_private_work_does_not_open_with_a_ticked_share_line(team):
    text = "---\nsources: [library:doc-123]\n---\n# Agent page\n\n- [x] Share with bob\n"
    doc = made(team, "alice", text)["doc"]
    assert page(team, BOB, doc).status == 404 and page(team, CAROL, doc).status == 404


def test_a_recipients_agent_cannot_narrow_or_withdraw_the_share(team):
    out = made(team, "alice", "# Agent page\n\n- [x] Share with bob, carol\n")
    for text in ("# Agent page\n\n- [x] Share with bob\n", "# Agent page\n\n- [ ] Share with bob, carol\n", "# Agent page\n"):
        bad, why = call(team, "bob", "update", doc=out["doc"], text=text, expected_hash=out["hash"])
        assert bad, why
    assert page(team, CAROL, out["doc"]).status == 200


def test_a_task_that_says_share_with_a_phrase_is_not_a_share_box():
    assert audience("# T\n\n- [x] Share with the client\n") is None
    assert audience("# T\n\n- [x] Share with bob, carol\n") == frozenset({"bob", "carol"})


def test_the_row_button_does_not_tell_a_member_who_cannot_open_the_page_that_it_changed(team):
    doc = made(team, "alice", PRIVATE)["doc"]
    got = share(team, CAROL, doc)
    assert got.status == 404 and "changed" not in got.text


def test_a_tick_the_hub_refuses_after_the_row_button_wrote_the_line_takes_the_line_off_again(team, monkeypatch):
    doc = made(team, "alice", PRIVATE)["doc"]
    from sheafmd.hub import handler
    from sheafmd.hub.handler import Refuse
    def refuse(self, req):
        raise Refuse(409, "the page changed")
    monkeypatch.setattr(handler.Handler, "_save", refuse)
    assert share(team, ALICE, doc).status == 409
    assert read(team, doc) == PRIVATE


# ── the review's findings (PR 394, round 2) ──────────────────────────────────

def _bob_streams(team, doc):
    sub = team.get(f"/_/live?doc={doc}", member=BOB).stream
    sub.drain()
    return sub


def _comment(team, doc):
    text = read(team, doc)
    quote = "Agent page" if "Agent page" in text else "A plan"
    blk, start, end = rdc.find_quote(text, quote)
    got = team.post("/_/comment", {"doc": doc, "op": "add", "hash": md_hash(text), "block": blk, "start": start,
                                   "end": end, "quote": quote, "body": "A note for Bob's tab."}, member=ALICE)
    assert got.status == 200, got.text


def test_an_open_stream_of_bob_hears_nothing_once_the_names_are_edited_off_the_line(team):
    doc = made(team, "alice", NAMED)["doc"]
    tick(team, ALICE, doc, "Share with")
    sub = _bob_streams(team, doc)
    team.hub.file(doc).write_text(read(team, doc).replace("Share with bob", "Share with carol"), encoding="utf-8")
    team.hub.entry(doc).live.refresh(force=True)
    _comment(team, doc)
    assert sub.drain() == []


def test_an_open_stream_of_bob_hears_nothing_once_the_owners_save_unticks_the_share(team):
    doc = made(team, "alice", NAMED)["doc"]
    tick(team, ALICE, doc, "Share with")
    sub = _bob_streams(team, doc)
    assert tick(team, ALICE, doc, "Share with", release=True).status == 200
    sub.drain()
    _comment(team, doc)
    team.hub.entry(doc).live.refresh(force=True)
    assert sub.drain() == []


def test_an_open_stream_of_bob_hears_nothing_once_the_owners_agent_withdraws_the_share(team):
    out = made(team, "alice", "# Agent page\n\n- [x] Share with bob\n")
    sub = _bob_streams(team, out["doc"])
    bad, why = call(team, "alice", "update", doc=out["doc"], text="# Agent page\n\n- [ ] Share with bob\n", expected_hash=out["hash"])
    assert not bad, why
    assert page(team, BOB, out["doc"]).status == 404
    sub.drain()
    _comment(team, out["doc"])
    team.hub.entry(out["doc"]).live.refresh(force=True)
    assert sub.drain() == []


def test_a_share_line_the_hub_cannot_find_after_writing_it_is_taken_off_again(team, monkeypatch):
    doc = made(team, "alice", PRIVATE)["doc"]
    monkeypatch.setattr(the_list, "share_edit", lambda text: None)
    assert share(team, ALICE, doc).status == 400
    assert read(team, doc) == PRIVATE


def documents(team, who, **args):
    return call(team, who, "documents", **args)


def test_a_root_of_another_member_that_shares_nothing_is_answered_as_a_root_that_does_not_exist(team):
    made(team, "alice", PRIVATE)
    bad, gone = documents(team, "bob", root="loose-alice")
    bad_, none = documents(team, "bob", root="loose-nobody")
    assert bad and bad_ and gone.replace("loose-alice", "X") == none.replace("loose-nobody", "X")


def test_a_closed_root_of_another_member_is_not_listed_as_shut_to_anyone_it_shares_nothing_with(team, monkeypatch):
    made(team, "alice", PRIVATE)
    from sheafmd.hub import roots
    monkeypatch.setattr(roots.Root, "closed", lambda self: "cannot be read" if self.name == "loose-alice" else None)
    bad, out = documents(team, "bob")
    assert not bad and "loose-alice" not in out
    bad, out = documents(team, "alice")
    assert not bad and "loose-alice" in out


def test_a_root_that_shares_a_page_with_bob_is_still_his_to_list(team):
    doc = made(team, "alice", "# Agent page\n\n- [x] Share with bob\n")["doc"]
    bad, out = documents(team, "bob", root="loose-alice", open_only=False)
    assert not bad and json.loads(out)[0]["doc"] != doc


DEEP = "# Deep plan\n\n- [ ] Share with bob\n\nA plan.\n"


def deep(team):
    bad, out = call(team, "alice", "create", doc="plan.md", folder="private-matters/deep", text=DEEP)
    assert not bad, out
    doc = json.loads(out)["doc"]
    assert "private-matters" in doc
    assert tick(team, ALICE, doc, "Share with").status == 200
    return doc


def test_the_recipient_is_told_no_folder_name_nor_path_of_the_owner_anywhere(team):
    real = deep(team)
    sheaf = json.dumps(shared_rows(team, BOB))
    bad, rows = documents(team, "bob", root="loose-alice", open_only=False)
    row = json.loads(rows)[0]
    bad, got = call(team, "bob", "read", doc=row["doc"])
    for seen in (sheaf, rows, got):
        assert "private-matters" not in seen and "deep" not in seen.replace("Deep plan", "") and "plan.md" not in seen
    assert "path" not in row and row["doc"].startswith("loose-alice/s-") and row["url"].endswith(row["doc"].split("/", 1)[1])
    assert json.loads(got)["doc"] == row["doc"]
    assert real not in rows


def test_the_opaque_name_opens_the_page_for_the_recipient_and_for_no_one_else(team):
    real = deep(team)
    name = json.loads(documents(team, "bob", root="loose-alice", open_only=False)[1])[0]["doc"]
    mine = page(team, BOB, name)
    assert mine.status == 200 and "private-matters" not in mine.text
    assert page(team, CAROL, name).status == 404 and page(team, CAROL, name).body == page(team, CAROL, "loose-alice/s-0000000000000000.md").body
    assert team.get(f"/_/doc?doc={name}", member=BOB).status == 200
    bad, text = call(team, "bob", "read", doc=name)
    assert not bad and json.loads(text)["text"] == read(team, real)
    assert page(team, ALICE, name).status == 200            # the owner reaches it by either


def test_a_withdrawn_share_closes_the_opaque_name_too(team):
    deep_doc = deep(team)
    name = json.loads(documents(team, "bob", root="loose-alice", open_only=False)[1])[0]["doc"]
    assert tick(team, ALICE, deep_doc, "Share with", release=True).status == 200
    assert page(team, BOB, name).status == 404
    bad, _ = call(team, "bob", "read", doc=name)
    assert bad
