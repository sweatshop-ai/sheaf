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
    return got.json().get("id")


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


def nodes(tree):
    """Every node of the Sheaf's tree by its path."""
    out = {}
    for n in tree:
        out[n["path"]] = n
        out.update(nodes(n["children"]))
    return out


def tree_of(team, member):
    return nodes(team.get("/_/mount?sheaf=1", member=member).json()["sheaf"]["tree"])


def test_a_folder_of_the_owners_loose_root_can_be_renamed_and_the_root_itself_cannot(team):
    in_folder(team, "f/sub")
    tree = tree_of(team, ALICE)
    assert tree["loose-alice/f"]["rename"] is True and tree["loose-alice/f/sub"]["rename"] is True
    assert tree["loose-alice"]["rename"] is False


def test_a_folder_of_a_repo_root_and_a_shared_view_has_no_rename(team, tmp_path):
    doc = tmp_path / "alice-work" / "n.md"
    doc.write_text(PLAN, encoding="utf-8")
    team.hub.roots.for_document(doc)
    (doc.parent / "deep").mkdir()
    (doc.parent / "deep" / "m.md").write_text(PLAN, encoding="utf-8")
    shared = made(team, "alice", SHARED)["doc"]
    tick(team, ALICE, shared, "Share")
    mine = tree_of(team, ALICE)
    work = team.hub.roots.lookup(doc).name
    assert f"{work}/deep" in mine and mine[f"{work}/deep"]["rename"] is False and mine[work]["rename"] is False
    theirs = tree_of(team, BOB)
    assert theirs and not any(n["rename"] for n in theirs.values())


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


# ── the fix round over c844295 ───────────────────────────────────────────────

def test_a_door_create_in_a_loose_root_waits_for_a_move_under_way(team):
    """A loose root's name has no lock of its own (`place.held` holds nothing there): the moves' lock is the one a door
    create takes, so it neither makes a file between a move's checks and its rename nor reads a Forward half written."""
    import threading
    from sheafmd.hub import moves
    done = threading.Event()
    out = []

    def create():
        out.append(call(team, "alice", "create", doc="late.md", text=PLAN))
        done.set()
    with moves._LOCK:
        worker = threading.Thread(target=create)
        worker.start()
        assert not done.wait(0.4)
    worker.join(10)
    assert done.is_set() and out == [(False, out[0][1])]


def test_a_door_create_in_a_registered_root_does_not_wait_for_the_moves_lock(team, tmp_path):
    import threading
    from sheafmd.hub import moves
    work = tmp_path / "alice-work"
    (work / "n.md").write_text(PLAN, encoding="utf-8")
    team.hub.roots.for_document(work / "n.md")        # a root of the member's own, not the loose one
    done = threading.Event()
    out = []

    def create():
        out.append(call(team, "alice", "create", doc=str(work / "reg.md"), text=PLAN))
        done.set()
    with moves._LOCK:
        worker = threading.Thread(target=create)
        worker.start()
        finished = done.wait(5)
    worker.join(10)
    assert finished and out[0][0] is False, out


def test_a_folder_move_that_fails_on_the_third_of_five_pages_puts_every_page_back(team, monkeypatch):
    from sheafmd.hub import moves
    hub = team.hub
    olds = [in_folder(team, "f", name=f"p{i}.md") for i in range(5)]
    news = [o.replace("/f/", "/g/") for o in olds]
    hub.docs.put(olds[0], {"title": "Kept"})
    hub.seen.mark(olds[1], "c1", 2)
    real, calls = moves._put, []

    def flaky(*args):
        calls.append(args[3])
        if len(calls) == 3:
            raise moves.Refused(409, "disk full")
        return real(*args)
    monkeypatch.setattr(moves, "_put", flaky)
    got = team.post("/_/move-folder", {"folder": "f", "to": "g"}, member=ALICE)
    assert got.status == 409 and "disk full" in got.text
    assert all(hub.file(o).exists() and read(team, o) == PLAN for o in olds)
    assert not any(hub.file(n).exists() for n in news)
    assert all(hub.forwards.follow(a) is None for a in olds + news)
    assert hub.docs.get(olds[0]) == {"title": "Kept"} and hub.docs.get(news[0]) == {}
    assert hub.seen.get(olds[1]) == {"c1": 2} and hub.seen.get(news[1]) == {}
    assert not (hub.file(olds[0]).parent.parent / "g").exists()


def test_forget_prefix_drops_the_forwards_of_a_root_and_those_that_lead_into_it():
    f = forwards.Forwards()
    f.add("r/a/x.md", "r/b/x.md", by="Alice")
    f.add("s/a/x.md", "r/c/x.md", by="Alice")
    f.add("s/a/y.md", "s/b/y.md", by="Alice")
    f.forget_prefix("r/")
    assert f.follow("r/a/x.md") is None and f.follow("s/a/x.md") is None and f.follow("s/a/y.md") == "s/b/y.md"


def test_forgetting_a_root_takes_its_forwards_with_it(team):
    old = made(team, "alice", PLAN)["doc"]
    new = moved(team, ALICE, old, "b")
    assert team.hub.forwards.follow(old) == new
    team.hub.forget_root("loose-alice")
    assert team.hub.forwards.follow(old) is None


def test_the_old_entrys_document_lets_go_of_its_versions_before_the_entry_goes(team, monkeypatch):
    old = made(team, "alice", PLAN)["doc"]
    hub = team.hub
    e = hub.entry(old)
    gone = []
    real = e.live.forget
    monkeypatch.setattr(e.live, "forget", lambda: (gone.append(1), real())[1])
    moved(team, ALICE, old, "b")
    assert gone == [1]


def test_a_version_put_at_the_old_address_during_the_move_does_not_survive_it(team, monkeypatch):
    old = made(team, "alice", PLAN)["doc"]
    hub = team.hub
    hub.entry(old)
    kept = md_hash(read(team, old))
    hub.versions.put(old, read(team, old))
    real = type(hub.versions).rename

    def rename_then_stale(self, a, b):
        real(self, a, b)
        self.put(a, "# Stale\n")        # a write that began before the move lands under the old key
    monkeypatch.setattr(type(hub.versions), "rename", rename_then_stale)
    new = moved(team, ALICE, old, "b")
    assert hub.versions.get(old, md_hash("# Stale\n")) is None
    assert hub.versions.get(new, kept) is not None


def test_a_recipients_open_tab_is_told_gone_under_its_opaque_name_when_the_page_moves(team):
    old = made(team, "alice", SHARED)["doc"]
    tick(team, ALICE, old, "Share")
    opaque = told(team, BOB, old)
    sub = team.get(f"/_/live?doc={opaque}", member=BOB).stream
    sub.drain()
    new = moved(team, ALICE, old, "b")
    got = [(n, d) for n, d in sub.drain()]
    assert ("gone", {"doc": opaque}) in got
    assert not any(n == "moved" for n, _ in got)
    assert told(team, BOB, new) == opaque


def test_a_folder_the_move_made_before_a_private_refusal_is_taken_back(team, monkeypatch):
    from sheafmd import beneath
    from sheafmd.hub import place
    old = made(team, "alice", PLAN)["doc"]
    real = place.make_folders

    def private(top, rel, judge=None):
        os.close(real(top, rel, judge)[0])
        raise beneath.Private("loose-alice")
    monkeypatch.setattr(place, "make_folders", private)
    got = move(team, ALICE, old, "x/y")
    assert 400 <= got.status < 500
    assert team.hub.file(old).exists() and not (team.hub.file(old).parent / "x").exists()


# ── the fix round over 9c98fc9: the two races ────────────────────────────────

def test_a_save_that_began_before_a_move_is_at_the_new_address_after_it(team, monkeypatch):
    """The file moves under the page's file lock, as every write of it is made: a save already inside it is waited for, and
    the move links the file it wrote. The interleave is fixed by the moves' own `file_lock` (the hook): the save is held
    inside its `change` until the move has come to the lock, or has gone by it."""
    import threading
    from sheafmd import source
    from sheafmd.hub import moves
    old = made(team, "alice", PLAN)["doc"]
    top, rel = team.hub.roots.get("loose-alice").path, old.split("/", 1)[1]
    in_save, release, at_lock = threading.Event(), threading.Event(), threading.Event()
    saved, result = [], []

    def change(text, opened):
        in_save.set()
        assert release.wait(20)
        return text + "\nSaved.\n"

    def save():
        try:
            saved.append(source.update_beneath(top, rel, change))
        except Exception as e:
            saved.append(e)

    class Probe(source.file_lock):
        def __enter__(self):
            at_lock.set()
            return super().__enter__()
    monkeypatch.setattr(moves, "file_lock", Probe, raising=False)
    saver = threading.Thread(target=save)
    saver.start()
    assert in_save.wait(20)
    mover = threading.Thread(target=lambda: result.append(move(team, ALICE, old, "b")))
    mover.start()
    while mover.is_alive() and not at_lock.wait(0.01):     # at the lock, or through the move already
        pass
    release.set()
    saver.join(20)
    mover.join(20)
    new = "loose-alice/b/plan.md"
    assert isinstance(saved[0], tuple), saved
    assert result[0].status == 200 and read(team, new).endswith("\nSaved.\n")
    assert not team.hub.file(old).exists()


def test_a_tell_that_starts_between_the_check_and_the_rename_is_refused_or_the_move_is(team, monkeypatch):
    """A Tell's start and the move's check of it take the same lock, the hub's admission lock: the move sees the Tell and
    answers 409, or marks the address under that lock and the Tell's start, which looks at the mark under it, is refused.
    The hook is `tell_live` itself: the Tell's start is begun the moment the move has looked, and the move goes on only
    when that start is through or waits."""
    import threading
    from sheafmd.hub import tell as tell_mod
    hub = team.hub
    old = made(team, "alice", PLAN)["doc"]
    entry = hub.entry(old)
    attempted, started, hold = threading.Event(), threading.Event(), threading.Event()
    outcome = []

    class Probe:
        def __init__(self, real):
            self.real = real

        def __enter__(self):
            if threading.current_thread().name == "tell-start":
                attempted.set()
            return self.real.__enter__()

        def __exit__(self, *a):
            return self.real.__exit__(*a)

    def start():
        try:
            with hub.tell._admitting(old):
                outcome.append(hub.tell._start(entry, "tell", "c1", lambda job: hold.wait(20), None))
        except tell_mod.JobRefused as e:
            outcome.append(e)
        finally:
            started.set()
    starter = threading.Thread(target=start, name="tell-start")
    real_live, begun = hub.tell_live, []

    def tell_live(address):
        seen = real_live(address)
        if address == old and not begun:
            begun.append(1)
            starter.start()
            assert attempted.wait(20)          # the Tell's start has come to the admission lock
            started.wait(0.3)                  # through it at once (no lock held), or waiting for the move that holds it
        return seen
    monkeypatch.setattr(hub, "admit", Probe(hub.admit))
    monkeypatch.setattr(hub, "tell_live", tell_live)
    got = move(team, ALICE, old, "b")
    assert started.wait(20)
    started_on_old = bool(outcome) and not isinstance(outcome[0], Exception)
    hold.set()
    starter.join(20)
    assert not (got.status == 200 and started_on_old), (got.status, outcome)


# ── the fix round over 0e268f1 ───────────────────────────────────────────────

def test_a_door_create_that_names_a_full_loose_root_address_takes_the_moves_lock(team, monkeypatch):
    """The lock is taken for a create that ends in a loose root, however the address was spelled: not only when the door
    rewrote a bare name. The hook is `moves.exclusive`, the lock's entry; a registered root's create stays free of it."""
    import contextlib
    from sheafmd.hub import moves
    entered = []
    real = moves.exclusive

    @contextlib.contextmanager
    def probe():
        entered.append(1)
        with real():
            yield
    monkeypatch.setattr(moves, "exclusive", probe)
    made(team, "alice", PLAN)                        # a bare name: the loose root is made
    in_folder(team, "sub", name="first.md")
    del entered[:]
    bad, out = call(team, "alice", "create", doc="loose-alice/sub/full.md", text=PLAN)
    assert not bad, out
    assert entered == [1]


def test_a_save_in_flight_on_one_page_does_not_block_an_admission_while_another_page_moves(team, monkeypatch):
    """A move waits for the page's file lock, which a save holds through its whole step; the hub's admission lock, which
    every Tell start and an upgrade stop take, is not held meanwhile: one order everywhere, file lock first. The hook is
    the move's own `file_lock`: when it has come to the lock, an admission is asked for, and is given at once."""
    import threading
    from sheafmd import source
    from sheafmd.hub import moves
    a = made(team, "alice", PLAN)["doc"]
    top, rel = team.hub.roots.get("loose-alice").path, a.split("/", 1)[1]
    in_save, release, at_lock = threading.Event(), threading.Event(), threading.Event()

    def change(text, opened):
        in_save.set()
        assert release.wait(20)
        return text + "\nSaved.\n"
    saver = threading.Thread(target=lambda: source.update_beneath(top, rel, change))

    class Probe(source.file_lock):
        def __enter__(self):
            at_lock.set()
            return super().__enter__()
    monkeypatch.setattr(moves, "file_lock", Probe, raising=False)
    saver.start()
    assert in_save.wait(20)
    result = []
    mover = threading.Thread(target=lambda: result.append(move(team, ALICE, a, "b")))
    mover.start()
    try:
        assert at_lock.wait(20)
        taken = team.hub.admit.acquire(timeout=3)         # page B's admission, with the move waiting on page A's lock
        if taken:
            team.hub.admit.release()
        assert taken, "the move holds the admission lock while it waits for the page's file lock"
    finally:
        release.set()
        saver.join(20)
        mover.join(20)
    assert result[0].status == 200


def test_a_tell_queued_while_the_page_moves_ends_on_the_new_address(team, monkeypatch):
    """A Tell queued for an agent resolves its address under the admission lock and the moves' lock: a move that comes
    between the entry found at the old address and the queue is either done first (the Tell goes to the new address) or
    waits for the queue (the rename carries the row). The hook is the queue itself: the move is started the moment the Tell
    comes to queue, and given a short while to get through."""
    import threading
    old = made(team, "alice", PLAN)["doc"]
    cid = comment(team, old)
    assert cid
    assert team.post("/_/target", {"doc": old, "target": "agent:alice-claude"}, member=ALICE).status == 200
    alice = team.hub.proxy.members[ALICE]
    waiting = team.hub.waiting_tells
    real, begun, moved_done = waiting.queue, [], threading.Event()
    mover = threading.Thread(target=lambda: (move(team, ALICE, old, "b"), moved_done.set()))

    def queue(address, *a, **k):
        if not begun:
            begun.append(1)
            mover.start()
            moved_done.wait(1)                 # through at once when nothing holds it, else it waits for the Tell's queue
        return real(address, *a, **k)
    monkeypatch.setattr(waiting, "queue", queue)
    team.hub.tell.queue_agent(old, cid, alice)
    mover.join(20)
    new = "loose-alice/b/plan.md"
    assert team.hub.forwards.follow(old) == new
    from sheafmd.hub import waiting as waiting_mod
    rows = waiting_mod.read_json(waiting_mod._file(), [], aside=False)
    assert [r["doc"] for r in rows] == [new], rows


def test_forgetting_a_root_offline_takes_its_forwards_with_it_and_a_new_root_of_the_name_has_none(team):
    from sheafmd.hub import roots as roots_mod
    old = made(team, "alice", PLAN)["doc"]
    new = moved(team, ALICE, old, "b")
    assert team.hub.forwards.follow(old) == new
    roots_mod.forget_offline("loose-alice")
    assert forwards.Forwards().follow(old) is None


# ── the fix round over b2f6ebe: one lock order (SPEC 9.11, `sheafmd.hub.lockorder`) ──────────────

def test_a_move_renames_with_no_admission_lock_held(team, monkeypatch):
    """The rename waits on the page's file lock and takes the admission lock never: a save in flight on one page must not keep
    a Tell start on another waiting. The hook is `_link`, which runs under the file lock: from another thread the admission
    lock is taken at once, and the move is still marked, so a Tell start on the page is refused."""
    import threading
    from sheafmd.hub import moves, tell as tell_mod
    hub = team.hub
    old = made(team, "alice", PLAN)["doc"]
    inside, go, seen = threading.Event(), threading.Event(), {}
    real = moves._link

    def link(*a, **k):
        inside.set()
        assert go.wait(20)
        return real(*a, **k)
    monkeypatch.setattr(moves, "_link", link)
    mover = threading.Thread(target=lambda: move(team, ALICE, old, "b"))
    mover.start()
    assert inside.wait(20)

    def probe():
        got = hub.admit.acquire(timeout=3)
        seen["taken"] = got
        if got:
            try:
                seen["marked"] = old in hub.moving
                with pytest.raises(tell_mod.JobRefused) as r:
                    with hub.tell._admitting(old):
                        pass
                seen["refused"] = r.value.status
            finally:
                hub.admit.release()
    t = threading.Thread(target=probe)
    t.start()
    t.join(10)
    go.set()
    mover.join(20)
    assert seen == {"taken": True, "marked": True, "refused": 409}, seen
    assert old not in hub.moving                       # the mark is gone once the move is done


def test_the_mark_of_a_refused_move_is_taken_off(team):
    """A move that is refused after the mark (a name the folder holds) leaves no mark, so a Tell starts there."""
    old = made(team, "alice", PLAN)["doc"]
    in_folder(team, "b")
    assert move(team, ALICE, old, "b").status == 409
    assert old not in team.hub.moving
    with team.hub.tell._admitting(old):
        pass


def test_a_queue_for_an_agent_holds_neither_the_admission_lock_nor_the_moves_lock_while_it_finds_the_entry(team, monkeypatch):
    """`queue_agent` resolves the Forward and finds the entry (its first read and render may happen there) with no lock held,
    and takes the moves' lock and the admission lock only for the look at the address and the queue."""
    from sheafmd.hub import moves
    old = made(team, "alice", PLAN)["doc"]
    cid = comment(team, old)
    assert team.post("/_/target", {"doc": old, "target": "agent:alice-claude"}, member=ALICE).status == 200
    alice = team.hub.proxy.members[ALICE]
    held = []
    real = team.hub.tell._entry

    def entry(address):
        held.append((team.hub.admit._is_owned(), moves._LOCK._is_owned()))
        return real(address)
    monkeypatch.setattr(team.hub.tell, "_entry", entry)
    team.hub.tell.queue_agent(old, cid, alice)
    assert held and set(held) == {(False, False)}, held


# ── the fix round over 355dfee: the archive marks go with the page ───────────────────────────────

def test_a_move_carries_the_archived_and_seen_marks_and_leaves_none_at_the_old_path(team):
    """A move is no activity for the archive (SPEC 9.11): the page keeps its seen time, an archived page stays archived at
    its new path, and the old path holds no mark, so a page moved back does not come back archived by a stale one."""
    from sheafmd.hub import archive, loose
    hub = team.hub
    in_folder(team, "a")
    root = hub.roots.get("loose-alice").path
    mtime = os.stat(hub.file(at("a"))).st_mtime
    loose.stamp(root, archive.SEEN, {"a/plan.md": 111.0, "a/other.md": 5.0})
    loose.stamp(root, archive.ARCHIVED, {"a/plan.md": mtime + 10, "a/other.md": 6.0})
    moved(team, ALICE, at("a"), "b")
    assert loose.times(root, archive.SEEN) == {"b/plan.md": 111.0, "a/other.md": 5.0}
    assert loose.times(root, archive.ARCHIVED) == {"b/plan.md": mtime + 10, "a/other.md": 6.0}
    assert archive.is_archived(loose.times(root, archive.ARCHIVED), "b/plan.md", mtime)


def test_a_move_of_a_page_with_no_archive_marks_writes_none(team):
    from sheafmd.hub import archive, loose
    in_folder(team, "a")
    root = team.hub.roots.get("loose-alice").path
    moved(team, ALICE, at("a"), "b")
    assert loose.times(root, archive.SEEN) == {} and loose.times(root, archive.ARCHIVED) == {}
    assert not (root / ".sheaf" / archive.SEEN).exists() and not (root / ".sheaf" / archive.ARCHIVED).exists()


def test_the_door_answers_a_move_whose_page_cannot_be_read_after_it_with_a_tool_error(team, monkeypatch):
    from sheafmd.hub import moves
    old = made(team, "alice", PLAN)["doc"]
    real = moves.move_page

    def then_gone(hub, member, address, folder):
        new = real(hub, member, address, folder)
        hub.file(new).unlink()
        return new
    monkeypatch.setattr(moves, "move_page", then_gone)
    bad, out = call(team, "alice", "move", doc=old, folder="b")
    assert bad and "could not be read" in out
