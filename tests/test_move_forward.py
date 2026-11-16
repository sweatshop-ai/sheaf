"""Move a loose page within its root, and the Forward the old address keeps for ever (SPEC 9.11, "Move and Forward").
Alice, Bob and Carol of one tiroir, through the handler as the proxy sets it (`Front`) and through the door. The risk is
the same as Share's: a move must carry everything the hub keeps of a page, never open it to anyone it was closed to,
and never tell a member who cannot open a page that its old address ever led anywhere."""
import json
import os

import pytest
import test_share
from test_share import ALICE, BOB, CAROL, SHARED, call, made, page, read, told, tick

import sheafmd.comments as rdc
from sheafmd.hub import forwards
from sheafmd.source import md_hash

PLAN = "# Alice's plan\n\nA plan.\n"
team = test_share.team         # Alice, Bob and Carol of one tiroir, the fixture of the Share tests


def move(team, member, doc, folder):
    return team.post("/_/move", {"doc": doc, "folder": folder}, member=member)


def moved(team, member, doc, folder):
    got = move(team, member, doc, folder)
    assert got.status == 200, got.text
    return got.json()["doc"]


def comment(team, doc):
    text = read(team, doc)
    blk, start, end = rdc.find_quote(text, "A plan")
    got = team.post("/_/comment", {"doc": doc, "op": "add", "hash": md_hash(text), "block": blk, "start": start,
                                   "end": end, "quote": "A plan", "body": "A note."}, member=ALICE)
    assert got.status == 200, got.text


def at(folder, name="plan.md"):
    return f"loose-alice/{folder}/{name}"


def in_folder(team, folder, text=PLAN, name="plan.md"):
    bad, out = call(team, "alice", "create", doc=name, text=text, folder=folder)
    assert not bad, out
    return json.loads(out)["doc"]


# ── the Forward store ────────────────────────────────────────────────────────

def test_a_forward_is_kept_across_a_restart_and_never_expires(team):
    forwards.Forwards().add("loose-alice/a/x.md", "loose-alice/b/x.md", by="Alice")
    again = forwards.Forwards()
    assert again.follow("loose-alice/a/x.md") == "loose-alice/b/x.md"
    assert again.follow("loose-alice/zzz/x.md") is None


def test_a_second_move_makes_the_first_forward_point_at_the_last_address(team):
    f = forwards.Forwards()
    f.add("r/a/x.md", "r/b/x.md", by="Alice")
    f.add("r/b/x.md", "r/c/x.md", by="Alice")
    assert f.follow("r/a/x.md") == "r/c/x.md" and f.follow("r/b/x.md") == "r/c/x.md"


def test_moving_a_page_back_drops_the_forward_at_its_old_address(team):
    f = forwards.Forwards()
    f.add("r/a/x.md", "r/b/x.md", by="Alice")
    f.add("r/b/x.md", "r/a/x.md", by="Alice")
    assert f.follow("r/a/x.md") is None and f.follow("r/b/x.md") == "r/a/x.md"


# ── the move of a page (AC 1) ────────────────────────────────────────────────

def test_a_move_puts_the_page_in_the_new_folder_and_the_old_address_redirects_to_it(team):
    old = made(team, "alice", PLAN)["doc"]
    new = moved(team, ALICE, old, "clients/blog")
    assert new == "loose-alice/clients/blog/plan.md"
    assert read(team, new) == PLAN and not team.hub.file(old).exists()
    got = page(team, ALICE, old)
    assert got.status == 302 and got.headers["Location"] == f"/{new}"
    assert "no-store" in got.headers["Cache-Control"]       # never a 301: a page can move back
    assert page(team, ALICE, new).status == 200


def test_a_move_carries_every_store_keyed_by_the_address(team):
    old = at("a")
    in_folder(team, "a")
    hub = team.hub
    comment(team, old)
    hub.entry(old)
    kept = md_hash(read(team, old))
    hub.versions.put(old, read(team, old))
    hub.docs.put(old, {"title": "Kept title"})
    hub.seen.mark(old, "c1", 2)
    hub.member_seen.mark(ALICE, old, "c1", 2)
    hub.member_opened.mark(ALICE, old, 5)
    hub.writes.add(old, "Alice", "page", "save")
    from sheafmd.hub import loose
    loose.keep(hub.roots.get("loose-alice").path, "a/plan.md")
    new = moved(team, ALICE, old, "b")
    assert hub.versions.get(new, kept) is not None and hub.versions.get(old, kept) is None
    assert hub.docs.get(new) == {"title": "Kept title"} and hub.docs.get(old) == {}
    assert hub.seen.get(new) == {"c1": 2} and hub.seen.get(old) == {}
    assert hub.member_seen.get(ALICE, new) == {"c1": 2} and hub.member_seen.get(ALICE, old) == {}
    assert hub.member_opened.get(ALICE, new) == 5 and hub.member_opened.get(ALICE, old) == 0
    assert [w.via for w in hub.writes.lines(new)] == ["create", "save", "move"] and hub.writes.lines(old) == []
    assert loose.marks(hub.roots.get("loose-alice").path) == ["b/plan.md"]
    assert "A note." in read(team, new)
    assert team.get(f"/_/doc?doc={new}", member=ALICE).status == 200


def test_the_write_log_forgets_the_old_address_after_a_restart(team):
    old = made(team, "alice", PLAN)["doc"]
    new = moved(team, ALICE, old, "b")
    from sheafmd.hub.writelog import WriteLog
    again = WriteLog()
    assert again.lines(old) == [] and [w.via for w in again.lines(new)][-1] == "move"


def test_share_goes_along_bob_still_opens_the_page_at_its_new_address(team):
    old = made(team, "alice", SHARED)["doc"]
    tick(team, ALICE, old, "Share")
    before = told(team, BOB, old)
    assert page(team, BOB, before).status == 200
    new = moved(team, ALICE, old, "tidy")
    assert told(team, BOB, new) == before       # the opaque name Bob holds is the same page
    assert page(team, BOB, before).status == 200 and "- [x] Share" in read(team, new)
    rows = team.get("/_/mount?sheaf=1", member=BOB).json()["sheaf"]["rows"]
    assert [r["doc"] for r in rows] == [before]


def test_a_new_folder_typed_in_the_dialog_is_made_and_the_old_folder_goes_when_empty(team):
    old = in_folder(team, "old/deep")
    root = team.hub.roots.get("loose-alice").path
    moved(team, ALICE, old, "new/deeper")
    assert (root / "new/deeper/plan.md").exists()
    assert not (root / "old").exists()              # a folder exists only while a page is in it


def test_the_old_folder_stays_while_another_page_is_in_it(team):
    in_folder(team, "keep", name="b.md")
    old = in_folder(team, "keep")
    moved(team, ALICE, old, "elsewhere")
    assert (team.hub.roots.get("loose-alice").path / "keep/b.md").exists()


def test_links_in_other_pages_are_not_rewritten_and_the_forward_resolves_them(team):
    old = made(team, "alice", PLAN)["doc"]
    other = made(team, "alice", f"# Other\n\nSee [the plan](/{old}).\n", doc="other.md")["doc"]
    moved(team, ALICE, old, "b")
    assert f"(/{old})" in read(team, other)
    assert page(team, ALICE, old).status == 302


def test_a_stranger_gets_the_same_answer_for_a_forwarded_address_as_for_one_never_used(team):
    old = made(team, "alice", PLAN)["doc"]
    moved(team, ALICE, old, "b")
    never = page(team, BOB, "loose-alice/nothing/x.md")
    got = page(team, BOB, old)
    assert got.status == 404 and got.body == never.body and "Location" not in got.headers


def test_a_forward_is_not_followed_for_a_recipient_who_never_knew_the_old_address(team):
    old = made(team, "alice", SHARED)["doc"]
    tick(team, ALICE, old, "Share")
    kept = told(team, BOB, old)
    moved(team, ALICE, old, "b/secret-folder")
    never, got = page(team, BOB, "loose-alice/nothing/x.md"), page(team, BOB, old)
    assert got.status == 404 and got.body == never.body and "Location" not in got.headers
    assert page(team, BOB, kept).status == 200          # the name Bob holds still opens it


def test_moving_a_page_back_opens_it_at_the_old_address_again(team):
    old = made(team, "alice", PLAN)["doc"]
    new = moved(team, ALICE, old, "b")
    assert moved(team, ALICE, new, os.path.dirname(old.split("/", 1)[1])) == old
    assert page(team, ALICE, old).status == 200
    assert page(team, ALICE, new).status == 302


def test_a_move_onto_an_address_that_forwards_elsewhere_is_refused(team):
    first = in_folder(team, "a")
    moved(team, ALICE, first, "b")                        # a/plan.md now forwards to b/plan.md
    other = in_folder(team, "c")                          # a different page with the same name
    got = move(team, ALICE, other, "a")
    assert got.status == 409 and read(team, other) == PLAN


def test_a_create_at_an_address_that_forwards_elsewhere_is_refused(team):
    first = in_folder(team, "a")
    moved(team, ALICE, first, "b")
    bad, out = call(team, "alice", "create", doc="plan.md", text=PLAN, folder="a")
    assert bad and "moved" in out


def test_a_move_onto_a_taken_name_is_refused_and_nothing_moves(team):
    in_folder(team, "b")
    old = in_folder(team, "a")
    got = move(team, ALICE, old, "b")
    assert got.status == 409 and team.hub.file(old).exists()


def test_the_move_does_not_reset_the_pages_quiet_clock(team):
    old = made(team, "alice", PLAN)["doc"]
    os.utime(team.hub.file(old), (1_000_000, 1_000_000))
    new = moved(team, ALICE, old, "b")
    assert team.hub.file(new).stat().st_mtime == 1_000_000


def test_an_open_tab_on_the_old_address_is_told_where_the_page_went(team):
    old = made(team, "alice", PLAN)["doc"]
    sub = team.get(f"/_/live?doc={old}", member=ALICE).stream
    sub.drain()
    new = moved(team, ALICE, old, "b")
    got = sub.drain()
    assert ("moved", {"doc": old, "to": new}) in [(n, d) for n, d in got]


# ── the move of a folder (AC 2) ──────────────────────────────────────────────

def test_renaming_a_folder_moves_each_page_below_it_with_its_own_forward(team):
    a, b = in_folder(team, "f", name="a.md"), in_folder(team, "f/sub", name="b.md")
    got = team.post("/_/move-folder", {"folder": "f", "to": "g"}, member=ALICE)
    assert got.status == 200, got.text
    assert read(team, "loose-alice/g/a.md") == PLAN and read(team, "loose-alice/g/sub/b.md") == PLAN
    assert page(team, ALICE, a).headers["Location"] == "/loose-alice/g/a.md"
    assert page(team, ALICE, b).headers["Location"] == "/loose-alice/g/sub/b.md"
    assert not (team.hub.roots.get("loose-alice").path / "f").exists()


def test_a_folder_rename_that_would_hit_a_taken_name_moves_nothing_and_names_the_page(team):
    in_folder(team, "f", name="a.md")
    in_folder(team, "f", name="b.md")
    in_folder(team, "g", name="b.md")
    got = team.post("/_/move-folder", {"folder": "f", "to": "g"}, member=ALICE)
    assert got.status == 409 and "b.md" in got.text
    assert team.hub.file("loose-alice/f/a.md").exists() and team.hub.file("loose-alice/f/b.md").exists()


def test_a_folder_cannot_be_renamed_into_itself(team):
    in_folder(team, "f")
    assert team.post("/_/move-folder", {"folder": "f", "to": "f/inside"}, member=ALICE).status == 409
    assert team.hub.file("loose-alice/f/plan.md").exists()


# ── who may move, and where (AC 3) ───────────────────────────────────────────

def test_a_recipient_of_a_share_has_no_move_on_the_row_and_the_route_refuses_it(team):
    old = made(team, "alice", SHARED)["doc"]
    tick(team, ALICE, old, "Share")
    row = [r for r in team.get("/_/mount?sheaf=1", member=BOB).json()["sheaf"]["rows"]][0]
    assert row["can_move"] is False
    got = move(team, BOB, row["doc"], "mine")
    assert got.status in (403, 404) and team.hub.file(old).exists()
    assert "loose-alice" not in got.text


def test_the_owners_row_can_move(team):
    made(team, "alice", PLAN)
    rows = team.get("/_/mount?sheaf=1", member=ALICE).json()["sheaf"]["rows"]
    assert [r["can_move"] for r in rows] == [True]


def test_a_member_who_cannot_see_the_page_gets_the_answer_of_a_page_that_is_not_there(team):
    old = made(team, "alice", PLAN)["doc"]
    never = move(team, CAROL, "loose-alice/nothing/x.md", "mine")
    got = move(team, CAROL, old, "mine")
    assert got.status == never.status == 404 and got.body == never.body and team.hub.file(old).exists()


def test_a_page_of_a_registered_root_is_not_moved_by_the_move_route(team, tmp_path):
    doc = tmp_path / "alice-work" / "n.md"
    doc.write_text(PLAN, encoding="utf-8")
    team.hub.roots.for_document(doc)
    address = f"{team.hub.roots.lookup(doc).name}/n.md"
    assert move(team, ALICE, address, "b").status == 409 and doc.exists()


@pytest.mark.parametrize("folder", ["/etc", "../x", "a/../b", ".hidden", "a/.git", "", "a//b", "a\\b"])
def test_an_absolute_or_dotted_or_hidden_folder_is_refused(team, folder):
    old = made(team, "alice", PLAN)["doc"]
    assert move(team, ALICE, old, folder).status in (400, 409) and team.hub.file(old).exists()


def test_a_folder_that_names_another_members_root_is_only_a_folder_of_the_own_root(team):
    made(team, "bob", PLAN)
    old = made(team, "alice", PLAN)["doc"]
    new = moved(team, ALICE, old, "loose-bob")
    assert new == "loose-alice/loose-bob/plan.md"


# ── the door (AC 5, hub half) ────────────────────────────────────────────────

def test_the_door_moves_a_page_of_the_owner_and_answers_the_new_path(team):
    old = made(team, "alice", PLAN)["doc"]
    bad, out = call(team, "alice", "move", doc=old, folder="b")
    assert not bad, out
    got = json.loads(out)
    assert got["doc"] == "loose-alice/b/plan.md" and got["moved_from"] == old
    assert team.hub.file(got["doc"]).exists()


def test_the_door_move_is_refused_to_a_member_the_page_is_shared_with(team):
    old = made(team, "alice", SHARED)["doc"]
    tick(team, ALICE, old, "Share")
    bad, out = call(team, "bob", "move", doc=told(team, BOB, old), folder="mine")
    assert bad and team.hub.file(old).exists() and "loose-alice" not in out


def test_the_door_move_leaves_a_line_in_the_write_log_and_the_diagnostics(team):
    old = made(team, "alice", PLAN)["doc"]
    bad, out = call(team, "alice", "move", doc=old, folder="b")
    assert not bad
    new = json.loads(out)["doc"]
    assert team.hub.writes.last(new).via == "move"


def test_the_door_read_of_the_old_address_answers_the_new_one(team):
    old = made(team, "alice", PLAN)["doc"]
    new = moved(team, ALICE, old, "b")
    bad, out = call(team, "alice", "read", doc=old)
    assert not bad, out
    got = json.loads(out)
    assert got["doc"] == new and got["moved_from"] == old and got["text"].startswith("# Alice's plan")


def test_the_door_update_of_the_old_address_writes_at_the_new_one(team):
    old = made(team, "alice", PLAN)["doc"]
    new = moved(team, ALICE, old, "b")
    bad, out = call(team, "alice", "update", doc=old, text=PLAN + "\nMore.\n", expected_hash=md_hash(PLAN))
    assert not bad, out
    assert json.loads(out)["doc"] == new and "More." in read(team, new)


def test_the_door_read_of_a_forward_for_a_stranger_is_a_page_that_is_not_there(team):
    old = made(team, "alice", PLAN)["doc"]
    moved(team, ALICE, old, "b")
    bad, out = call(team, "bob", "read", doc=old)
    bad2, out2 = call(team, "bob", "read", doc="loose-alice/nothing/x.md")
    assert bad and bad2 and out.replace(old, "X") == out2.replace("loose-alice/nothing/x.md", "X")


def test_the_door_lists_move_among_the_write_tools_and_offers_no_delete(team):
    from sheafmd import mcp
    assert "move" in mcp.WRITE_TOOLS and "move" in mcp.PAGE_TOOLS and "delete" not in mcp.TOOLS


def test_a_page_with_a_tell_running_on_it_is_not_moved_until_it_ends(team, monkeypatch):
    old = made(team, "alice", PLAN)["doc"]
    running = [True]
    monkeypatch.setattr(team.hub, "tell_live", lambda address: running[0] and address == old)
    assert move(team, ALICE, old, "b").status == 409 and team.hub.file(old).exists()
    running[0] = False
    assert move(team, ALICE, old, "b").status == 200


def test_a_waiting_tell_goes_with_the_page(team):
    old = made(team, "alice", PLAN)["doc"]
    from sheafmd.hub import waiting
    team.hub.waiting_tells._change(lambda rows: (rows.append({"id": "t1", "doc": old, "thread": "c1", "token": "alice-claude",
                                                              "tid": "x", "by": "Alice", "at": "now", "seen": None}), (None, True))[1])
    new = moved(team, ALICE, old, "b")
    rows = waiting.read_json(waiting._file(), [], aside=False)
    assert [r["doc"] for r in rows] == [new]
