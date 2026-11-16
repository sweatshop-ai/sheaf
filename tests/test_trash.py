"""Delete and the trash of a member's loose pages (SPEC 8.6): Delete is the owner's own act from the Sheaf, moves the page
into the root's `.sheaf/trash/` for thirty days, and no agent or door path can delete. Through the handler in proxy mode
and the door, in memory, with the hub's clock under test control."""
import contextlib
import os
import threading

import pytest
from helpers import BEA, CAL, comment, door, rpc
from test_archive import DAY, Clock, call, clock, docs, made, root_of, rows, sweep  # noqa: F401  (fixtures)
from test_hub_commits import DOC, box, git, merged_on_github, rectoversos, remote  # noqa: F401  (fixtures)
from test_share import line_edit, tick
from test_write_log import agents  # noqa: F401  (fixture)

from sheafmd.hub import loose, place
from sheafmd.source import md_hash


def trash_rows(agents, member=BEA):
    got = agents.get("/_/mount?sheaf=1&view=trash", member=member)
    assert got.status == 200, got.text
    return got.json()["sheaf"]["trash"]


def delete(agents, doc, member=BEA):
    return agents.post("/_/delete", {"doc": doc}, member=member)


def test_delete_moves_the_page_to_the_roots_trash_and_it_leaves_every_view_and_its_address(agents, clock):
    doc = made(agents, "bea-claude")
    path = agents.hub.file(doc)
    assert delete(agents, doc).status == 200
    assert not path.exists()
    assert docs(agents) == [] and docs(agents, view="archived") == []
    assert agents.get(f"/{doc}", member=BEA).status == 404
    held = list((root_of(agents, doc).path / ".sheaf" / "trash").rglob("notes.md"))
    assert len(held) == 1
    assert [r["rel"] for r in trash_rows(agents)] == [doc.split("/", 1)[1]]


def test_a_deleted_page_is_restored_to_its_old_address_with_its_comments(agents, clock):
    doc = made(agents, "bea-claude")
    comment(agents.hub.file(doc))
    text = agents.hub.file(doc).read_text(encoding="utf-8")
    assert delete(agents, doc).status == 200
    [row] = trash_rows(agents)
    got = agents.post("/_/restore-trash", {"id": row["id"]}, member=BEA)
    assert got.status == 200, got.text
    assert agents.hub.file(doc).read_text(encoding="utf-8") == text
    assert docs(agents) == [doc] and trash_rows(agents) == []


def test_restoring_over_a_taken_name_is_refused_and_overwrites_nothing(agents, clock):
    doc = made(agents, "bea-claude")
    assert delete(agents, doc).status == 200
    again = made(agents, "bea-claude", text="# New\n\nA different page.\n", folder=doc.split("/")[1])
    assert again == doc
    [row] = trash_rows(agents)
    got = agents.post("/_/restore-trash", {"id": row["id"]}, member=BEA)
    assert got.status == 409 and "already" in got.text
    assert "A different page" in agents.hub.file(doc).read_text(encoding="utf-8")
    assert len(trash_rows(agents)) == 1


def test_the_trash_is_emptied_after_thirty_days_and_not_before(agents, clock):
    doc = made(agents, "bea-claude")
    assert delete(agents, doc).status == 200
    clock.now += 29 * DAY
    agents.hub.archive.purge()
    assert len(trash_rows(agents)) == 1
    clock.now += 2 * DAY
    agents.hub.archive.purge()
    assert trash_rows(agents) == []
    assert list((root_of(agents, doc).path / ".sheaf" / "trash").rglob("*.md")) == []


def test_the_hub_tick_purges_the_trash(agents, clock):
    doc = made(agents, "bea-claude")
    assert delete(agents, doc).status == 200
    clock.now += 31 * DAY
    agents.hub.tick()
    agents.hub.archive.settle()
    assert trash_rows(agents) == []


def test_delete_is_the_owners_alone_a_recipient_gets_the_answer_of_a_page_that_is_not_there(agents, clock):
    doc = made(agents, "bea-claude", text="# Shared\n\n- [ ] Share\n\nA plan.\n")
    assert tick(agents, BEA, doc, "Share").status == 200
    there = delete(agents, doc, CAL)
    gone = delete(agents, "loose-bea/never/made.md", CAL)
    assert (there.status, there.text) == (gone.status, gone.text) == (404, there.text)
    assert agents.hub.file(doc).exists()
    assert agents.post("/_/restore-trash", {"id": "1/x.md"}, member=CAL).status == 404


def test_delete_refuses_a_repo_page_a_registered_root_page_and_a_list_page(agents, clock):
    assert delete(agents, DOC).status == 404            # a page of a registered root, which the fixture holds
    assert agents.hub.file(DOC).exists()
    assert delete(agents, "repo/owner/name/page.md").status == 404
    assert not (root_of(agents, "rectoversos/x").path / ".sheaf" / "trash").exists()


def test_the_door_lists_no_delete_tool_and_a_delete_call_is_an_unknown_tool(agents):
    res = door(agents.door, rpc("tools/list"), token=agents.tokens["bea-claude"], as_name=None)
    names = [t["name"] for t in res.json()["result"]["tools"]]
    assert not any(w in n for n in names for w in ("delete", "trash", "archive", "restore", "keep"))
    for tool in ("delete", "archive", "restore", "trash"):
        res = door(agents.door, rpc("tools/call", {"name": tool, "arguments": {"doc": "notes.md"}}),
                   token=agents.tokens["bea-claude"], as_name=None)
        got = res.json()
        assert "error" in got or got["result"]["isError"]


def test_no_door_tool_can_write_into_a_roots_sheaf_folder(agents):
    doc = made(agents, "bea-claude")
    bad, _ = call(agents, "bea-claude", "create", doc="x.md", text="# X\n", folder=".sheaf/trash")
    assert bad
    bad, _ = call(agents, "bea-claude", "update", doc=f"{doc.split('/')[0]}/.sheaf/trash/x.md", text="# X\n", expected_hash="0" * 64)
    assert bad
    assert not (root_of(agents, doc).path / ".sheaf" / "trash").exists()


@pytest.mark.parametrize("route,body", [("/_/delete", {"doc": "x"}), ("/_/archive", {"doc": "x"}), ("/_/restore", {"doc": "x"}),
                                        ("/_/keep", {"doc": "x", "on": True}), ("/_/restore-trash", {"id": "1/x.md"})])
def test_an_agent_token_cannot_call_the_routes_of_archive_keep_and_delete(agents, route, body):
    doc = made(agents, "bea-claude")
    body = {**body, **({"doc": doc} if "doc" in body else {})}
    for headers in ({"Authorization": f"Bearer {agents.tokens['bea-claude']}"}, {"X-Sheaf-Member": BEA}):
        got = agents.door.request("POST", route, body=body, cookie=False, key=False, headers=headers)
        assert got.status in (401, 403, 404), (route, got.status)
    assert agents.hub.file(doc).exists()


def test_the_delete_route_checks_the_owner_not_only_the_cookie(agents, clock):
    doc = made(agents, "bea-claude", text="# Shared\n\n- [ ] Share\n\nA plan.\n")
    assert tick(agents, BEA, doc, "Share").status == 200
    for route in ("/_/delete", "/_/archive", "/_/restore"):
        assert agents.post(route, {"doc": doc}, member=CAL).status == 404
    assert agents.post("/_/keep", {"doc": doc, "on": True}, member=CAL).status == 404
    assert agents.hub.file(doc).exists()


def test_a_door_read_or_update_on_a_trashed_page_is_refused_like_a_missing_page(agents, clock):
    doc = made(agents, "bea-claude")
    assert delete(agents, doc).status == 200
    never = "loose-bea/never/made.md"
    for tool, extra in (("read", {}), ("update", {"expected_hash": "0" * 64, "text": "# T\n"})):
        trashed = call(agents, "bea-claude", tool, doc=doc, **extra)
        missing = call(agents, "bea-claude", tool, doc=never, **extra)
        assert trashed[0] and missing[0]
        assert trashed[1].replace(doc, "X") == missing[1].replace(never, "X"), tool


def test_a_deleted_pages_versions_stay_where_the_hub_keeps_them(agents, clock):
    doc = made(agents, "bea-claude")
    agents.get(f"/{doc}", member=BEA)
    before = sorted(p.name for p in agents.hub.versions.dir.rglob("*") if p.is_file())
    assert before
    assert delete(agents, doc).status == 200
    assert sorted(p.name for p in agents.hub.versions.dir.rglob("*") if p.is_file()) == before


def test_a_trash_file_that_is_a_link_is_refused(agents, clock, tmp_path):
    doc = made(agents, "bea-claude")
    os.mkdir(root_of(agents, doc).path / ".sheaf")
    os.symlink(tmp_path, root_of(agents, doc).path / ".sheaf" / "trash")
    assert delete(agents, doc).status == 409
    assert agents.hub.file(doc).exists()
    assert list(tmp_path.iterdir()) == [] or all(not p.name.isdigit() for p in tmp_path.iterdir())


def test_delete_takes_the_pages_marks_with_it(agents, clock):
    doc = made(agents, "bea-claude", keep=True)
    assert delete(agents, doc).status == 200
    assert loose.marks(root_of(agents, doc).path) == []


def test_a_loose_folder_that_is_not_its_own_root_has_no_trash_to_read_or_restore(agents, clock, monkeypatch):
    foreign = root_of(agents, "rectoversos/x")
    held = foreign.path / ".sheaf" / "trash" / "1" / "stray.md"
    held.parent.mkdir(parents=True)
    held.write_text("# Stray\n", encoding="utf-8")
    made(agents, "bea-claude")
    monkeypatch.setattr(agents.hub.roots, "for_document", lambda path: foreign)      # the loose folder lies inside another root
    assert trash_rows(agents) == []
    assert agents.post("/_/restore-trash", {"id": "1/stray.md"}, member=BEA).status == 404
    assert held.exists() and not (foreign.path / "stray.md").exists()


def test_restore_from_trash_and_delete_hold_the_place_lock_and_tell_the_index(agents, clock, monkeypatch):
    doc = made(agents, "bea-claude")
    held, touched, inside = [], [], []
    real_restore = agents.hub.archive.restore_trash

    @contextlib.contextmanager
    def watch(hub, address):
        held.append(address)
        yield
    monkeypatch.setattr(place, "held", watch)
    monkeypatch.setattr(agents.hub.index, "touch", touched.append)
    assert delete(agents, doc).status == 200
    assert doc in held and touched[-1] == doc
    [row] = trash_rows(agents)
    held.clear()
    monkeypatch.setattr(agents.hub.archive, "restore_trash", lambda root, ident: (inside.append(list(held)), real_restore(root, ident))[1])
    assert agents.post("/_/restore-trash", {"id": row["id"]}, member=BEA).status == 200
    assert inside and set(inside[0]) == {doc} and touched[-1] == doc


def test_a_save_racing_a_delete_lands_before_it_or_is_refused(agents, clock, monkeypatch):
    doc = made(agents, "bea-claude", text="# Tasks\n\n- [ ] one\n- [ ] two\n")
    text = agents.hub.file(doc).read_text(encoding="utf-8")
    saved, real_trash = [], agents.hub.archive.trash

    def save():
        saved.append(agents.post("/_/save", {"doc": doc, "hash": md_hash(text), "edits": [line_edit(text, "one")]}, member=BEA))

    def trash(root, rel):
        racer = threading.Thread(target=save)
        racer.start()
        racer.join(0.3)                 # a save that can come in beside the move would have finished by now
        assert racer.is_alive(), "a save came in while Delete moved the page"
        saved.append(racer)
        real_trash(root, rel)
    monkeypatch.setattr(agents.hub.archive, "trash", trash)
    assert delete(agents, doc).status == 200
    racer = saved.pop(0)
    racer.join(5)
    assert not racer.is_alive()
    assert not agents.hub.file(doc).exists()                # the save did not write the page back to its address
    assert [r["rel"] for r in trash_rows(agents)] == [doc.split("/", 1)[1]]
    assert [r.status for r in saved] == [404], saved                  # refused, the page is gone
