"""Delete and the trash of a member's loose pages (SPEC 8.6): Delete is the owner's own act from the Sheaf, moves the page
into the root's `.sheaf/trash/` for thirty days, and no agent or door path can delete. Through the handler in proxy mode
and the door, in memory, with the hub's clock under test control."""
import contextlib
import errno
import os
import shutil
import threading

import pytest
from helpers import BEA, CAL, comment, door, rpc
from test_archive import DAY, Clock, call, clock, docs, made, root_of, rows, sweep  # noqa: F401  (fixtures)
from test_hub_commits import DOC, box, git, merged_on_github, rectoversos, remote  # noqa: F401  (fixtures)
from test_share import line_edit, tick
from test_write_log import agents  # noqa: F401  (fixture)

from sheafmd.blocks import split_md_blocks
from sheafmd.hub import archive, loose, place
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


PAGE = "# Tasks\n\nFirst paragraph here.\n\n- [ ] one\n- [ ] two\n"


def behind_a_delete(agents, monkeypatch, *racers):
    """Run each of `racers` (a function) in a thread started while Delete holds the page, after the page's locks are taken and
    before it moves: each must still be waiting 0.3 s later, and is joined once Delete is done. Their results, in order."""
    results, threads = [None] * len(racers), []
    real_rename = os.rename

    def rename(src, dst, *a, **kw):
        if kw.get("dst_dir_fd") is not None and not threads:      # the move into the trash, made from folder descriptors
            for i, racer in enumerate(racers):
                t = threading.Thread(target=lambda i=i, racer=racer: results.__setitem__(i, racer()))
                t.start()
                threads.append(t)
            for t in threads:
                t.join(0.3)
            assert all(t.is_alive() for t in threads), "a writer came in while Delete moved the page"
        return real_rename(src, dst, *a, **kw)
    monkeypatch.setattr(os, "rename", rename)
    return results, threads


def test_a_save_racing_a_delete_lands_before_it_or_is_refused(agents, clock, monkeypatch):
    doc = made(agents, "bea-claude", text=PAGE)
    text = agents.hub.file(doc).read_text(encoding="utf-8")
    results, threads = behind_a_delete(agents, monkeypatch, lambda: agents.post(
        "/_/save", {"doc": doc, "hash": md_hash(text), "edits": [line_edit(text, "one")]}, member=BEA).status)
    assert delete(agents, doc).status == 200
    for t in threads:
        t.join(5)
        assert not t.is_alive()
    assert not agents.hub.file(doc).exists()                # the save did not write the page back to its address
    assert [r["rel"] for r in trash_rows(agents)] == [doc.split("/", 1)[1]]
    assert results == [404]                                 # refused, the page is gone


def test_a_comment_and_a_tick_waiting_behind_a_delete_both_answer_404(agents, clock, monkeypatch):
    doc = made(agents, "bea-claude", text=PAGE)
    text = agents.hub.file(doc).read_text(encoding="utf-8")
    i = next(i for i, b in enumerate(split_md_blocks(text)) if b.content.startswith("First"))
    results, threads = behind_a_delete(
        agents, monkeypatch,
        lambda: agents.post("/_/comment", {"doc": doc, "op": "add", "hash": md_hash(text), "block": i, "start": 0,
                                           "end": 5, "quote": "First", "body": "Is this right?"}, member=BEA).status,
        lambda: agents.post("/_/save", {"doc": doc, "hash": md_hash(text), "edits": [line_edit(text, "two")]},
                            member=BEA).status)
    assert delete(agents, doc).status == 200
    for t in threads:
        t.join(5)
        assert not t.is_alive()
    assert results == [404, 404]


def test_a_door_write_on_a_page_with_no_hub_entry_racing_a_delete_cannot_recreate_the_page(agents, clock, monkeypatch):
    doc = made(agents, "bea-claude", text=PAGE)
    text = agents.hub.file(doc).read_text(encoding="utf-8")
    agents.hub.entries.pop(doc, None)
    results, threads = behind_a_delete(agents, monkeypatch, lambda: call(
        agents, "bea-claude", "update", doc=doc, text=text + "\nA late line.\n", expected_hash=md_hash(text)))
    assert delete(agents, doc).status == 200
    for t in threads:
        t.join(5)
        assert not t.is_alive()
    assert not agents.hub.file(doc).exists()
    assert results[0][0] is True                            # the door's write is refused: the page is gone


def test_a_page_that_is_not_text_can_still_be_deleted(agents, clock):
    doc = made(agents, "bea-claude")
    agents.hub.entries.pop(doc, None)
    agents.hub.file(doc).write_bytes(b"\xff\xfe# not utf-8\n")
    assert delete(agents, doc).status == 200
    assert not agents.hub.file(doc).exists()
    assert len(trash_rows(agents)) == 1


def hooked_stamps(monkeypatch, after_archived):
    """Call `after_archived()` once, right after the ARCHIVED marks of a page are changed by a restore or a delete: between
    that write and the next one when they are separate holds, inside the one hold when they are one."""
    fired, inside = [], []

    def wrap(real, direct):
        def wrapped(root_path, name, changes, only_new=False):
            inside.append(1)
            try:
                out = real(root_path, name, changes, only_new)
            finally:
                inside.pop()
            if name == archive.ARCHIVED and not fired and (direct or not inside):
                fired.append(1)
                after_archived()
            return out
        return wrapped
    monkeypatch.setattr(loose, "stamp", wrap(loose.stamp, True))
    monkeypatch.setattr(loose, "stamp_held", wrap(loose.stamp_held, False))
    return fired


def archived_page(agents, clock):
    doc = made(agents, "bea-claude")
    sweep(agents)
    clock.now += 31 * DAY
    sweep(agents)
    assert docs(agents, view="archived") == [doc]
    return doc


def test_a_sweep_between_the_stamps_of_a_restore_leaves_the_page_restored(agents, clock, monkeypatch):
    doc = archived_page(agents, clock)
    racer = []

    def sweeping():
        t = threading.Thread(target=agents.hub.archive.sweep)
        t.start()
        t.join(0.3)
        racer.append(t)
    assert hooked_stamps(monkeypatch, sweeping) == []
    assert agents.post("/_/restore", {"doc": doc}, member=BEA).status == 200
    racer[0].join(5)
    assert docs(agents) == [doc] and docs(agents, view="archived") == []


def test_a_sweep_between_the_stamps_of_a_delete_leaves_the_page_not_archived_after_restore_trash(agents, clock, monkeypatch):
    doc = archived_page(agents, clock)
    listed, go, racer = threading.Event(), threading.Event(), []
    real_pages = agents.hub.archive._pages

    def pages(member, root):
        out = real_pages(member, root)
        if not listed.is_set():
            listed.set()
            go.wait(5)                  # this sweep read its pages before the Delete, and goes on after it
        return out
    monkeypatch.setattr(agents.hub.archive, "_pages", pages)
    sweeper = threading.Thread(target=agents.hub.archive.sweep)
    sweeper.start()
    assert listed.wait(5)

    def release():
        go.set()
        sweeper.join(0.3)
        racer.append(sweeper)
    hooked_stamps(monkeypatch, release)
    assert delete(agents, doc).status == 200
    sweeper.join(5)
    [row] = trash_rows(agents)
    assert agents.post("/_/restore-trash", {"id": row["id"]}, member=BEA).status == 200
    assert docs(agents) == [doc] and docs(agents, view="archived") == []


def test_a_page_that_a_writer_without_the_hubs_locks_puts_there_just_before_a_restore_is_kept_and_the_restore_is_refused(agents, clock, monkeypatch):
    """The restore's move is a link, never a rename: a page that another process puts at the address between the check and the
    move is not replaced. (A door create is no such writer any more: in a loose root it takes the moves' lock, which a restore
    holds, so it comes before the restore or after it, never between.)"""
    doc = made(agents, "bea-claude")
    assert delete(agents, doc).status == 200
    [row] = trash_rows(agents)
    fired = []

    def hooked(real):
        def wrapped(src, dst, *a, **kw):
            if "/.sheaf/trash/" in str(src) and not fired:      # the move of the restore: the other writer's page lands just before it
                fired.append(1)
                with open(agents.hub.file(doc), "x", encoding="utf-8") as f:
                    f.write("# New\n\nThe door's page.\n")
            return real(src, dst, *a, **kw)
        return wrapped
    monkeypatch.setattr(os, "rename", hooked(os.rename))
    monkeypatch.setattr(os, "link", hooked(os.link))
    got = agents.post("/_/restore-trash", {"id": row["id"]}, member=BEA)
    assert fired
    assert got.status == 409 and "already" in got.text      # the restore is refused: the address is taken
    assert "The door's page" in agents.hub.file(doc).read_text(encoding="utf-8")
    assert len(trash_rows(agents)) == 1                     # and the deleted page is still in the trash


def test_a_page_in_a_folder_that_leads_out_of_the_root_is_not_trashed(agents, clock, tmp_path):
    doc = made(agents, "bea-claude")
    root = root_of(agents, doc)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.md").write_text("# Not the root's\n", encoding="utf-8")
    os.symlink(outside, root.path / "way-out")
    with pytest.raises(loose.Refused):
        agents.hub.archive.trash(root, "way-out/x.md")
    assert (outside / "x.md").read_text(encoding="utf-8") == "# Not the root's\n"


def test_a_trashed_page_purged_between_the_look_and_the_link_is_not_found_not_an_error(agents, clock, monkeypatch):
    doc = made(agents, "bea-claude")
    assert delete(agents, doc).status == 200
    [row] = trash_rows(agents)
    root = root_of(agents, doc)
    real_lstat, real_makedirs = os.lstat, os.makedirs
    made_dirs = []

    def makedirs(*a, **k):
        made_dirs.append(a)                         # the folders of the old address are made after the checks, before the link
        return real_makedirs(*a, **k)

    def lstat(p, *a, **k):
        if made_dirs and str(p).startswith(str(root.path / ".sheaf" / "trash")):
            raise FileNotFoundError(p)              # purged between the checks and the look at the entry
        return real_lstat(p, *a, **k)
    monkeypatch.setattr(archive.os, "makedirs", makedirs)
    monkeypatch.setattr(archive.os, "lstat", lstat)
    with pytest.raises(KeyError):
        agents.hub.archive.restore_trash(root, row["id"])


def test_purge_does_not_follow_a_linked_sheaf_folder(agents, clock, tmp_path):
    doc = made(agents, "bea-claude")
    root = root_of(agents, doc)
    old = tmp_path / "elsewhere" / "trash" / "1000"
    old.mkdir(parents=True)
    (old / "page.md").write_text("kept\n", encoding="utf-8")
    sheaf = root.path / ".sheaf"
    sheaf.symlink_to(tmp_path / "elsewhere")
    clock.now += 60 * DAY
    agents.hub.archive.purge()
    assert (old / "page.md").is_file()


# ── Ticket 183 AN and AX ─────────────────────────────────────────────────────

def test_a_trashed_page_purged_between_the_first_look_and_its_status_is_not_found_not_an_error(agents, clock, monkeypatch):
    doc = made(agents, "bea-claude")
    assert delete(agents, doc).status == 200
    [row] = trash_rows(agents)
    root = root_of(agents, doc)
    src = root.path / ".sheaf" / "trash" / row["id"]
    real, looks = os.lstat, []

    def lstat(p, *a, **k):
        got = real(p, *a, **k)
        if str(p) == str(src) and not looks:
            looks.append(p)
            os.unlink(src)                          # the purge, right after the first look at the entry
        return got
    monkeypatch.setattr(archive.os, "lstat", lstat)
    with pytest.raises(KeyError):
        agents.hub.archive.restore_trash(root, row["id"])


def test_a_trashed_page_purged_between_its_status_and_the_link_is_not_found_not_a_refusal(agents, clock, monkeypatch):
    doc = made(agents, "bea-claude")
    assert delete(agents, doc).status == 200
    [row] = trash_rows(agents)
    root = root_of(agents, doc)
    src = root.path / ".sheaf" / "trash" / row["id"]
    real = os.link

    def link(a, b, *args, **k):
        if str(a) == str(src):
            os.unlink(src)                          # the purge, right before the link
        return real(a, b, *args, **k)
    monkeypatch.setattr(archive.os, "link", link)
    with pytest.raises(KeyError):
        agents.hub.archive.restore_trash(root, row["id"])
    assert not agents.hub.file(doc).exists()


def test_a_folder_swapped_for_a_link_after_the_check_does_not_bring_an_outside_file_into_the_trash(agents, clock, monkeypatch, tmp_path):
    doc = made(agents, "bea-claude")
    root = root_of(agents, doc)
    (root.path / "sub").mkdir()
    (root.path / "sub" / "x.md").write_text("# The root's\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.md").write_text("# Not the root's\n", encoding="utf-8")
    real = archive.file_lock

    @contextlib.contextmanager
    def swapping(p):
        os.rename(root.path / "sub", tmp_path / "sub-was")
        os.symlink(outside, root.path / "sub")      # another account swaps the folder between the check and the move
        with real(p):
            yield
    monkeypatch.setattr(archive, "file_lock", swapping)
    with pytest.raises(loose.Refused):
        agents.hub.archive.trash(root, "sub/x.md")
    assert (outside / "x.md").read_text(encoding="utf-8") == "# Not the root's\n"
    assert not list((root.path / ".sheaf").rglob("x.md"))


def test_a_page_that_cannot_be_taken_from_its_address_is_not_left_in_the_trash_too(agents, clock, monkeypatch):
    doc = made(agents, "bea-claude")
    path = agents.hub.file(doc)

    def rename(*a, **k):
        raise PermissionError(1, "Operation not permitted")
    monkeypatch.setattr(archive.os, "rename", rename)
    assert delete(agents, doc).status == 409
    assert path.exists()
    assert not list((root_of(agents, doc).path / ".sheaf").rglob(path.name))


# ── Ticket 183 BJ, BK, BL and BM ─────────────────────────────────────────────

def _linked_page(agents):
    """A page of the root, and the address it also has through a folder link that stays in the root."""
    doc = made(agents, "bea-claude")
    root = root_of(agents, doc)
    (root.path / "sub").mkdir()
    (root.path / "sub" / "x.md").write_text("# The root's\n", encoding="utf-8")
    os.symlink("sub", root.path / "alias")
    return root, f"{root.name}/alias/x.md"


def test_a_page_reached_through_a_folder_link_inside_the_root_is_refused_with_its_own_address(agents, clock):
    root, linked = _linked_page(agents)
    got = delete(agents, linked)
    assert got.status == 409, got.text
    assert "sub/x.md" in got.text                   # the answer names the address the Sheaf lists, where Delete works
    assert (root.path / "sub" / "x.md").read_text(encoding="utf-8") == "# The root's\n"
    assert not list((root.path / ".sheaf" / "trash").rglob("x.md"))
    assert delete(agents, f"{root.name}/sub/x.md").status == 200       # at its own address it is deleted as any page


def test_a_page_deleted_between_the_first_look_and_the_lock_is_not_found(agents, clock, monkeypatch):
    doc = made(agents, "bea-claude")
    path = agents.hub.file(doc)
    real = archive.file_lock

    @contextlib.contextmanager
    def deleting(p):
        os.unlink(path)                             # another process deletes the page between the look and the lock
        with real(p):
            yield
    monkeypatch.setattr(archive, "file_lock", deleting)
    got = delete(agents, doc)
    assert got.status == 404, got.text


@pytest.mark.parametrize("err", [errno.EPERM, errno.EOPNOTSUPP], ids=["EPERM", "EOPNOTSUPP"])
def test_delete_works_where_the_file_system_refuses_hard_links(agents, clock, monkeypatch, err):
    doc = made(agents, "bea-claude")
    path = agents.hub.file(doc)
    text = path.read_text(encoding="utf-8")

    def link(*a, **k):
        raise OSError(err, os.strerror(err))        # exFAT, SMB, FUSE; EPERM under fs.protected_hardlinks
    monkeypatch.setattr(archive.os, "link", link)
    got = delete(agents, doc)
    assert got.status == 200, got.text
    assert not path.exists()
    [held] = list((root_of(agents, doc).path / ".sheaf" / "trash").rglob(path.name))
    assert held.read_text(encoding="utf-8") == text


def test_a_delete_never_has_the_page_in_two_places_at_any_step(agents, clock, monkeypatch):
    doc = made(agents, "bea-claude")
    path = agents.hub.file(doc)
    trash = root_of(agents, doc).path / ".sheaf" / "trash"
    counts = []

    def counted(real):
        def step(*a, **k):
            got = real(*a, **k)
            if k.get("dst_dir_fd") is not None:     # the step that puts the page in the trash: a crash right after it
                counts.append(path.exists() + len(list(trash.rglob(path.name))))
            return got
        return step
    monkeypatch.setattr(archive.os, "link", counted(os.link))
    monkeypatch.setattr(archive.os, "rename", counted(os.rename))
    assert delete(agents, doc).status == 200
    assert counts and all(n == 1 for n in counts), counts


def test_a_folder_on_the_way_that_goes_away_before_the_lock_is_not_found(agents, clock, monkeypatch):
    doc = made(agents, "bea-claude")
    root = root_of(agents, doc)
    folder = agents.hub.file(doc).parent
    real = archive.file_lock

    @contextlib.contextmanager
    def removing(p):
        shutil.rmtree(folder)                       # the page's folder goes, with the page, between the look and the lock
        with real(p):
            yield
    monkeypatch.setattr(archive, "file_lock", removing)
    with pytest.raises(archive.Gone):
        agents.hub.archive.trash(root, doc.split("/", 1)[1])


def test_a_page_swapped_for_a_folder_right_before_the_move_is_not_moved(agents, clock, monkeypatch):
    doc = made(agents, "bea-claude")
    path = agents.hub.file(doc)
    real, swapped = os.rename, []

    def rename(a, b, *args, **k):
        if k.get("dst_dir_fd") is not None and not swapped:
            swapped.append(a)
            os.unlink(path)
            os.mkdir(path)                          # another process puts a folder at the page's name
            (path / "inside.md").write_text("# Not the page\n", encoding="utf-8")
        return real(a, b, *args, **k)
    monkeypatch.setattr(archive.os, "rename", rename)
    got = delete(agents, doc)
    assert got.status == 409, got.text
    assert (path / "inside.md").read_text(encoding="utf-8") == "# Not the page\n"
    assert not list((root_of(agents, doc).path / ".sheaf" / "trash").rglob("inside.md"))


def test_a_delete_does_not_overwrite_a_page_in_the_trash_under_the_same_second_and_name(agents, clock):
    doc = made(agents, "bea-claude")
    path = agents.hub.file(doc)
    root = root_of(agents, doc)
    there = root.path / ".sheaf" / "trash" / str(int(clock.now)) / path.relative_to(root.path)
    there.parent.mkdir(parents=True)
    there.write_text("# Deleted a moment ago\n", encoding="utf-8")
    got = delete(agents, doc)
    assert got.status == 409, got.text
    assert there.read_text(encoding="utf-8") == "# Deleted a moment ago\n"
    assert path.exists()


def test_a_restore_where_the_file_system_refuses_hard_links_says_so_and_moves_nothing(agents, clock, monkeypatch):
    doc = made(agents, "bea-claude")
    assert delete(agents, doc).status == 200
    [row] = trash_rows(agents)

    def link(*a, **k):
        raise OSError(errno.EOPNOTSUPP, os.strerror(errno.EOPNOTSUPP))
    monkeypatch.setattr(archive.os, "link", link)
    got = agents.post("/_/restore-trash", {"id": row["id"]}, member=BEA)
    assert got.status == 409, got.text
    assert "hard link" in got.text and row["id"] in got.text     # what the owner can do: move that entry back by hand
    assert not agents.hub.file(doc).exists() and len(trash_rows(agents)) == 1


def _marked_everywhere(agents, clock):
    """An archived page that also carries a keep mark and a seen time: all three marks the delete takes."""
    doc = archived_page(agents, clock)
    root, rel = root_of(agents, doc).path, doc.split("/", 1)[1]
    loose.keep(root, rel, True)
    assert _marks_of(root, rel) == ALL_MARKS
    return doc, root, rel


ALL_MARKS = {"kept": True, "archived": True, "seen": True}
NO_MARKS = {"kept": False, "archived": False, "seen": False}


def _marks_of(root, rel):
    return {"kept": rel in loose.marks(root), "archived": rel in loose.times(root, loose.ARCHIVED),
            "seen": rel in loose.times(root, loose.SEEN)}


def _folder_swapped_in(path, put_back=True):
    """An `os.rename` for the delete under test: another process puts a folder at the page's name right before the move, and
    the move back is refused unless `put_back`."""
    real, calls = os.rename, []

    def rename(a, b, *args, **k):
        calls.append(a)
        if len(calls) == 1:
            os.unlink(path)
            os.mkdir(path)
        elif not put_back:
            raise OSError(errno.EACCES, os.strerror(errno.EACCES))
        return real(a, b, *args, **k)
    return rename


def test_a_page_taken_from_the_trash_right_after_the_move_leaves_no_marks_at_its_empty_address(agents, clock, monkeypatch):
    doc, root, rel = _marked_everywhere(agents, clock)
    path = agents.hub.file(doc)
    real = os.rename

    def rename(a, b, *args, **k):
        real(a, b, *args, **k)
        if k.get("dst_dir_fd") is not None:
            os.unlink(b, dir_fd=k["dst_dir_fd"])    # a program outside the hub takes the entry from the trash in that instant
    monkeypatch.setattr(archive.os, "rename", rename)
    got = delete(agents, doc)
    assert got.status == 409, got.text
    assert not path.exists()
    assert _marks_of(root, rel) == NO_MARKS


def test_a_folder_swapped_in_that_cannot_be_put_back_leaves_no_marks_at_the_empty_address(agents, clock, monkeypatch):
    doc, root, rel = _marked_everywhere(agents, clock)
    path = agents.hub.file(doc)
    monkeypatch.setattr(archive.os, "rename", _folder_swapped_in(path, put_back=False))
    got = delete(agents, doc)
    assert got.status == 409 and "by hand" in got.text, got.text
    assert not os.path.lexists(path)
    assert _marks_of(root, rel) == NO_MARKS


def test_a_folder_swapped_in_and_put_back_keeps_the_marks_of_its_address(agents, clock, monkeypatch):
    doc, root, rel = _marked_everywhere(agents, clock)
    path = agents.hub.file(doc)
    monkeypatch.setattr(archive.os, "rename", _folder_swapped_in(path))
    got = delete(agents, doc)
    assert got.status == 409, got.text
    assert path.is_dir()
    assert _marks_of(root, rel) == ALL_MARKS


@pytest.mark.parametrize("unwritable", ["archived", "seen"])
def test_a_mark_file_that_cannot_be_written_does_not_keep_the_other_marks_on_the_empty_address(agents, clock, monkeypatch,
                                                                                               unwritable):
    doc, root, rel = _marked_everywhere(agents, clock)
    name = loose.ARCHIVED if unwritable == "archived" else loose.SEEN
    real = loose.stamp_held

    def stamp_held(root_path, which, changes, **k):
        if which == name:
            raise loose.Refused(f"the {unwritable} marks of the loose root cannot be written")
        return real(root_path, which, changes, **k)
    monkeypatch.setattr(archive.loose, "stamp_held", stamp_held)
    got = delete(agents, doc)
    assert got.status == 409, got.text
    assert not agents.hub.file(doc).exists()
    assert _marks_of(root, rel) == {**NO_MARKS, unwritable: True}


def test_a_delete_lets_go_of_the_moves_lock_while_it_waits_for_a_render_of_its_page(agents, clock, lock_order):
    """Ticket 182 line 56: a Delete waits for the page's writer lock, which a render holds for up to 120 s. It waits with the
    moves' lock let go (`moves.page_held`), so a cancel (`/_/cancel`), a move or a forget does not wait behind that render."""
    from sheafmd.hub import moves
    doc = made(agents, "bea-claude", text=PAGE)
    e = agents.hub.entry(doc)
    held, release, got, answer = threading.Event(), threading.Event(), [], []

    def render():
        with e.live.exclusive():
            held.set()
            release.wait(15)

    threading.Thread(target=render, daemon=True).start()
    assert held.wait(5)
    deleting = threading.Thread(target=lambda: answer.append(delete(agents, doc).status), daemon=True)
    deleting.start()
    deleting.join(0.3)
    ok = moves._LOCK.acquire(timeout=3)
    if ok:
        moves._LOCK.release()
    got.append(ok)
    release.set()
    deleting.join(10)
    assert got == [True], "the moves' lock is held while the Delete waits for a render of its page"
    assert answer == [200] and not agents.hub.file(doc).exists()


def test_a_page_that_went_while_a_delete_waited_for_a_render_is_not_found(agents, clock, lock_order):
    """Ticket 182 line 56: the Delete looks at the owner's page again each time it takes the moves' lock back after waiting for
    a render (`moves.page_held`'s `look`), so a page that went meanwhile is answered as a page that is not there."""
    doc = made(agents, "bea-claude", text=PAGE)
    e, path = agents.hub.entry(doc), agents.hub.file(doc)
    held, release, answer = threading.Event(), threading.Event(), []

    def render():
        with e.live.exclusive():
            held.set()
            release.wait(15)

    threading.Thread(target=render, daemon=True).start()
    assert held.wait(5)
    deleting = threading.Thread(target=lambda: answer.append(delete(agents, doc).status), daemon=True)
    deleting.start()
    deleting.join(0.3)
    assert deleting.is_alive()
    os.unlink(path)                                 # another process takes the page away while the Delete waits
    release.set()
    deleting.join(10)
    assert answer == [404]
    assert trash_rows(agents) == []


# ── 183 BY: the sweep drops the marks of an address with no page ─────────────

def test_a_page_removed_from_outside_the_hub_leaves_no_marks_after_the_sweep(agents, clock):
    doc, root, rel = _marked_everywhere(agents, clock)
    os.unlink(agents.hub.file(doc))                 # something outside the hub empties the address before the delete reaches it
    assert delete(agents, doc).status == 404
    sweep(agents)
    assert _marks_of(root, rel) == NO_MARKS
    assert made(agents, "bea-claude") == doc
    assert doc in docs(agents) and doc not in docs(agents, view="archived")
    assert not next(r for r in rows(agents) if r["doc"] == doc)["kept"]


def test_a_folder_put_back_at_a_pages_address_leaves_no_marks_after_the_sweep(agents, clock, monkeypatch):
    doc, root, rel = _marked_everywhere(agents, clock)
    path = agents.hub.file(doc)
    monkeypatch.setattr(archive.os, "rename", _folder_swapped_in(path))
    assert delete(agents, doc).status == 409
    monkeypatch.undo()
    assert path.is_dir()
    sweep(agents)
    assert _marks_of(root, rel) == NO_MARKS


def test_the_sweep_keeps_the_marks_of_a_page_its_listing_did_not_see(agents, clock, monkeypatch):
    doc, root, rel = _marked_everywhere(agents, clock)
    # the listing is read outside the lock: a page made (and kept) after it is on disk when the marks are read
    monkeypatch.setattr(archive.Archive, "_pages", lambda self, member, root: [])
    sweep(agents)
    assert _marks_of(root, rel) == ALL_MARKS
