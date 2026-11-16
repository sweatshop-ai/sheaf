"""Delete and restore-trash against a Move (SPEC 8.6, 9.11): a Delete takes the moves' lock and then the file lock, so it
never comes between a move's link and its unlink; restore-trash takes the moves' lock too and puts a page back at no
address that a Forward holds, since an address that once pointed at a page does not silently become another. Through
the handler as the proxy sets it. Not run on a laptop: they start a hub, so CI is their run."""
import threading

import pytest
import test_share
from test_move_forward import ALICE, at, in_folder, move, moved, read
from test_share import page

from sheafmd.hub import moves

team = test_share.team


def delete(team, doc):
    return team.post("/_/delete", {"doc": doc}, member=ALICE)


def restore_trash(team, ident):
    return team.post("/_/restore-trash", {"id": ident}, member=ALICE)


def root_of(team):
    return team.hub.roots.get("loose-alice")


# ── point 2: a Delete waits for the moves' lock ──────────────────────────────

def test_a_delete_waits_while_another_thread_holds_the_moves_lock(team):
    in_folder(team, "a")
    held, release, answer = threading.Event(), threading.Event(), {}

    def holder():
        with moves._LOCK:
            held.set()
            release.wait(20)
    h = threading.Thread(target=holder)
    h.start()
    assert held.wait(20)
    d = threading.Thread(target=lambda: answer.update(got=delete(team, at("a"))))
    d.start()
    d.join(1.5)
    waiting = d.is_alive()
    release.set()
    h.join(20)
    d.join(20)
    assert waiting, "the delete did not wait for the moves' lock"
    assert answer["got"].status == 200 and not team.hub.file(at("a")).exists()


def test_a_delete_racing_a_move_leaves_the_page_in_one_place_and_never_a_500(team, monkeypatch):
    """The delete comes in while the move holds the page's file lock between its link and its unlink: it waits, and then the
    page is at the new address (the delete of the old one finds nothing) or in the trash, never both."""
    old = in_folder(team, "a")
    inside, go, out = threading.Event(), threading.Event(), {}
    real = moves._link

    def link(*a, **k):
        inside.set()
        assert go.wait(20)
        return real(*a, **k)
    monkeypatch.setattr(moves, "_link", link)
    mover = threading.Thread(target=lambda: out.update(move=move(team, ALICE, old, "b")))
    mover.start()
    assert inside.wait(20)
    deleter = threading.Thread(target=lambda: out.update(delete=delete(team, old)))
    deleter.start()
    deleter.join(1.5)
    waiting = deleter.is_alive()
    go.set()
    mover.join(20)
    deleter.join(20)
    assert waiting, "the delete did not wait for the move"
    assert out["move"].status == 200, out["move"].text
    assert out["delete"].status in (200, 404), out["delete"].text
    root = root_of(team)
    here = [p for p in ("a/plan.md", "b/plan.md") if (root.path / p).exists()]
    trashed = team.hub.archive.trashed(root)
    assert len(here) + len(trashed) == 1, (here, trashed)


# ── point 3: restore-trash refuses an address a Forward holds ────────────────

def test_restore_trash_refuses_an_address_that_a_forward_holds_and_says_it_is_taken(team):
    first = in_folder(team, "a")
    assert delete(team, first).status == 200
    [row] = team.hub.archive.trashed(root_of(team))
    second = in_folder(team, "a", text="# Another page\n\nAnother.\n")
    new = moved(team, ALICE, second, "b")
    assert team.hub.forwards.follow(first) == new
    got = restore_trash(team, row["id"])
    assert got.status == 409 and "taken" in got.text.lower(), (got.status, got.text)
    assert not team.hub.file(first).exists()
    assert [r["id"] for r in team.hub.archive.trashed(root_of(team))] == [row["id"]]      # still in the trash
    assert team.hub.forwards.follow(first) == new
    assert read(team, new) == "# Another page\n\nAnother.\n"


def test_restore_trash_of_an_address_no_forward_holds_still_puts_the_page_back(team):
    first = in_folder(team, "a")
    assert delete(team, first).status == 200
    [row] = team.hub.archive.trashed(root_of(team))
    got = restore_trash(team, row["id"])
    assert got.status == 200, got.text
    assert team.hub.file(first).exists() and team.hub.archive.trashed(root_of(team)) == []


def test_restore_trash_waits_while_another_thread_holds_the_moves_lock(team):
    first = in_folder(team, "a")
    assert delete(team, first).status == 200
    [row] = team.hub.archive.trashed(root_of(team))
    held, release, answer = threading.Event(), threading.Event(), {}

    def holder():
        with moves._LOCK:
            held.set()
            release.wait(20)
    h = threading.Thread(target=holder)
    h.start()
    assert held.wait(20)
    r = threading.Thread(target=lambda: answer.update(got=restore_trash(team, row["id"])))
    r.start()
    r.join(1.5)
    waiting = r.is_alive()
    release.set()
    h.join(20)
    r.join(20)
    assert waiting, "the restore did not wait for the moves' lock"
    assert answer["got"].status == 200


# ── restore-trash's link: a swapped entry is not followed, a failed unlink is a clean answer ─────

def test_a_trash_entry_swapped_for_a_link_after_the_check_is_not_put_back_through_it(team, monkeypatch, tmp_path):
    """The entry is a plain file when it is looked at and a link to a file outside the root when the link is made: the page
    is not restored through it, nothing of the outside file reaches the address, and the answer is a refusal."""
    import os
    first = in_folder(team, "a")
    assert delete(team, first).status == 200
    [row] = team.hub.archive.trashed(root_of(team))
    outside = tmp_path / "outside.md"
    outside.write_text("# Not the page\n")
    real = os.link
    swapped = []

    def link(src, dst, *a, **k):
        if str(src).endswith("plan.md") and ".sheaf/trash" in str(src) and not swapped:
            swapped.append(src)
            os.unlink(src)
            os.symlink(outside, src)
        return real(src, dst, *a, **k)
    with monkeypatch.context() as m:
        m.setattr(os, "link", link)
        got = restore_trash(team, row["id"])
    assert swapped and got.status == 409, (got.status, got.text)
    dest = team.hub.file(first)
    assert not os.path.lexists(dest), "the page was put back through the swapped entry"
    assert outside.read_text() == "# Not the page\n"


def test_a_trash_entry_that_cannot_be_unlinked_after_the_link_leaves_a_clean_refusal_and_the_page_in_the_trash(team, monkeypatch):
    import os
    first = in_folder(team, "a")
    assert delete(team, first).status == 200
    [row] = team.hub.archive.trashed(root_of(team))
    real = os.unlink

    def unlink(path, *a, **k):
        if ".sheaf/trash" in str(path):
            raise PermissionError(13, "Permission denied")
        return real(path, *a, **k)
    with monkeypatch.context() as m:
        m.setattr(os, "unlink", unlink)
        got = restore_trash(team, row["id"])
    assert got.status == 409, (got.status, got.text)
    assert not team.hub.file(first).exists()                            # the link made is taken off again
    assert [r["id"] for r in team.hub.archive.trashed(root_of(team))] == [row["id"]]
    assert restore_trash(team, row["id"]).status == 200                 # and the entry is still good: a second try restores it


# ── a Forward that leads to a deleted address goes with it (round 7) ─────────────────────────────

@pytest.mark.parametrize("how", ["create", "move", "restore"])
def test_no_forward_leads_to_the_page_that_takes_the_address_of_a_deleted_one(team, how):
    """Move A to B, delete B, then another page comes to B (a door create, a Move into it, a restore of an older page that was
    at B): A does not lead to it. SPEC 9.11 says nothing of a delete, so the delete drops the Forwards that lead to its address."""
    now = [1_000_000.0]
    team.hub.clock = lambda: now[0]         # two deletes of one address in one second are refused: each gets its own
    if how == "restore":
        older = in_folder(team, "b")
        assert delete(team, older).status == 200
        [row] = team.hub.archive.trashed(root_of(team))
        now[0] += 10
    a = in_folder(team, "a")
    b = moved(team, ALICE, a, "b")
    assert team.hub.forwards.follow(a) == b
    assert delete(team, b).status == 200
    if how == "create":
        assert in_folder(team, "b", text="# Another\n\nAnother page.\n") == b
    elif how == "move":
        other = in_folder(team, "c", text="# Another\n\nAnother page.\n")
        assert moved(team, ALICE, other, "b") == b
    else:
        got = restore_trash(team, row["id"])
        assert got.status == 200, got.text
    assert team.hub.file(b).exists()
    assert team.hub.forwards.follow(a) is None
    assert page(team, ALICE, a).status == 404


# ── a forwards.json that cannot be written after the page is in the trash (round 7, minor) ───────────

def test_a_forwards_file_that_cannot_be_written_after_the_page_is_in_the_trash_is_logged_and_the_delete_still_answers_200(team, monkeypatch):
    from sheafmd.hub import state
    a = in_folder(team, "a")
    b = moved(team, ALICE, a, "b")
    assert team.hub.forwards.follow(a) == b
    told, touched, logged = [], [], []
    real_write = state.write_json

    def write_json(path, obj):
        if path.name == "forwards.json":
            raise PermissionError(13, "Permission denied")
        return real_write(path, obj)
    with monkeypatch.context() as m:
        m.setattr(state, "write_json", write_json)
        m.setattr(team.hub, "forget_document", told.append)
        m.setattr(team.hub.index, "touch", touched.append)
        m.setattr(team.hub, "record_exception", lambda kind, *a, **k: logged.append(kind))
        got = delete(team, b)
    assert got.status == 200, (got.status, got.text)
    assert not team.hub.file(b).exists()
    assert [r["id"].partition("/")[2] for r in team.hub.archive.trashed(root_of(team))] == [b.partition("/")[2]]
    assert told == [b] and touched == [b]                       # the tabs open on it are told, the index is told
    assert logged and logged[0] == "delete-forward-failed"
