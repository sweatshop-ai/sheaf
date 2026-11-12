"""A versions store inside a root keeps the root's modes (SPEC 7.4): a clone shared with a group is 2750 on every
folder, and the hub that writes a version must neither reset an existing folder to 0700 nor make a new one so."""
import os
import stat

import pytest

from sheafmd import paths
from sheafmd.hub import state

NAME = "list"
SHARED = 0o2750


def mode(p):
    return stat.S_IMODE(os.lstat(p).st_mode)


@pytest.fixture
def shared_root(tmp_path):
    """A root whose folders are 2750 (setgid), with a store already holding one document's folder and a pins folder."""
    old = os.umask(0o027)
    try:
        root = tmp_path / "root"
        root.mkdir()
        d = root
        for seg in (".sheaf", "versions", state.doc_key("a.md"), "pins"):
            d = d / seg
            d.mkdir()
        for p in [root, *root.rglob("*")]:
            os.chmod(p, SHARED)
        yield root
    finally:
        os.umask(old)


def test_put_leaves_the_modes_of_existing_folders(shared_root):
    before = {p: mode(p) for p in [shared_root, *shared_root.rglob("*")]}
    assert set(before.values()) == {SHARED}
    v = state.Versions(shared_root, NAME)
    v.put(f"{NAME}/a.md", "text one\n")
    v.pin(f"{NAME}/a.md", "text one\n")
    for p, m in before.items():
        assert mode(p) == m, f"{p} went {oct(m)} -> {oct(mode(p))}"


def test_a_new_document_folder_comes_out_with_the_parents_modes(shared_root):
    v = state.Versions(shared_root, NAME)
    v.put(f"{NAME}/b.md", "text two\n")
    v.pin(f"{NAME}/b.md", "text two\n")
    folder = shared_root / state.INSIDE / state.doc_key("b.md")
    assert mode(folder) == SHARED and mode(folder / "pins") == SHARED


def test_a_store_made_from_nothing_inherits_the_roots_modes(tmp_path):
    old = os.umask(0o027)
    try:
        root = tmp_path / "fresh"
        root.mkdir()
        os.chmod(root, SHARED)
        state.Versions(root, NAME).put(f"{NAME}/c.md", "x\n")
        for p in (root / ".sheaf", root / state.INSIDE, root / state.INSIDE / state.doc_key("c.md")):
            assert mode(p) == SHARED
        assert mode(root) == SHARED
    finally:
        os.umask(old)


def test_the_state_folder_store_stays_private():
    state.Versions().put("list/a.md", "text\n")
    folder = paths.state_dir() / "versions" / state.doc_key("list/a.md")
    assert mode(paths.state_dir() / "versions") == 0o700 and mode(folder) == 0o700
    state.Versions().pin("list/a.md", "text\n")
    assert mode(folder / "pins") == 0o700


def test_a_link_in_place_of_the_store_is_still_refused(tmp_path):
    root, out = tmp_path / "root", tmp_path / "out"
    root.mkdir(), out.mkdir()
    (root / ".sheaf").symlink_to(out)
    with pytest.raises(paths.PathError):
        state.Versions(root, NAME).put(f"{NAME}/a.md", "x\n")
    assert not list(out.iterdir())
