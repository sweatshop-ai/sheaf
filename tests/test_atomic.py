"""sheafmd.atomic: a file that is either the old one or the whole new one."""
import os
import stat
from pathlib import Path

import pytest

from sheafmd.atomic import write_text_atomic


def test_a_new_file_gets_the_text_and_the_mode_asked_for(tmp_path):
    target = tmp_path / "deep" / "file.json"
    write_text_atomic(target, "whole\n", mode=0o600)
    assert target.read_text(encoding="utf-8") == "whole\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert os.listdir(target.parent) == ["file.json"]


def test_with_no_mode_the_file_gets_what_the_umask_leaves(tmp_path):
    old = os.umask(0o027)
    try:
        write_text_atomic(tmp_path / "f", "x")
    finally:
        os.umask(old)
    assert stat.S_IMODE((tmp_path / "f").stat().st_mode) == 0o640


def test_a_check_that_refuses_keeps_the_old_file_and_leaves_no_temp_file(tmp_path):
    tmp_path = tmp_path / "dir"
    tmp_path.mkdir()
    target = tmp_path / "f"
    target.write_text("old")

    def refuse():
        raise RuntimeError("changed meanwhile")

    with pytest.raises(RuntimeError, match="changed meanwhile"):
        write_text_atomic(target, "new", check=refuse)
    assert target.read_text() == "old"
    assert os.listdir(tmp_path) == ["f"]


def test_the_check_runs_once_the_new_file_is_whole(tmp_path):
    tmp_path = tmp_path / "dir"
    tmp_path.mkdir()
    target = tmp_path / "f"
    target.write_text("old")
    seen = []
    write_text_atomic(target, "new", check=lambda: seen.append(
        [(p.name, p.read_text()) for p in tmp_path.iterdir()]))
    assert ("f", "old") in seen[0] and any(t == "new" for _, t in seen[0])
    assert target.read_text() == "new"


def _swap_our_temp_at_fsync(monkeypatch, folder, put, swap=True):
    """While the new text is written, something else takes the temp file's name, as a user who can write the
    folder can at any moment. With swap False nothing is made: the control."""
    real, swapped = os.fsync, []

    def hook(fd):
        temps = [p for p in folder.iterdir() if p.name.endswith(".sheaf-tmp")]
        if swap and temps and not swapped:
            swapped.append(temps[0])
            temps[0].unlink()
            put(temps[0])
        return real(fd)

    monkeypatch.setattr(os, "fsync", hook)
    return swapped


@pytest.mark.parametrize("swap", [True, False], ids=["swapped", "control"])
@pytest.mark.parametrize("planted", ["a link", "a file"])
def test_a_temp_file_swapped_during_the_write_does_not_take_the_files_place(tmp_path, monkeypatch, swap, planted):
    """One writer for every file sheaf replaces: the same look as a document's save (source._write_atomic)
    before the temp file takes the old one's place."""
    folder = tmp_path / "dir"
    folder.mkdir()
    target = folder / "f.json"
    target.write_text("old\n")
    victim = tmp_path / "note.txt"
    victim.write_text("personal\n")
    put = (lambda s: s.symlink_to(victim)) if planted == "a link" else (lambda s: s.write_text("theirs\n"))
    swapped = _swap_our_temp_at_fsync(monkeypatch, folder, put, swap)
    if swap:
        with pytest.raises(OSError, match="was replaced while the new text was written"):
            write_text_atomic(target, "new\n")
        assert swapped and target.read_text() == "old\n"
    else:
        write_text_atomic(target, "new\n")
        assert target.read_text() == "new\n"
    assert not target.is_symlink() and victim.read_text() == "personal\n"
    assert sorted(p.name for p in folder.iterdir()) == ["f.json"]


def test_an_existing_file_with_no_mode_asked_gets_what_the_umask_leaves(tmp_path):
    """Unlike a document's save, which keeps the document's mode, a file written here with no mode
    gets the umask's, whatever mode the old one had."""
    target = tmp_path / "f"
    target.write_text("old")
    os.chmod(target, 0o600)
    old = os.umask(0o022)
    try:
        write_text_atomic(target, "new")
    finally:
        os.umask(old)
    assert stat.S_IMODE(target.stat().st_mode) == 0o644 and target.read_text() == "new"


def test_a_link_at_the_path_is_replaced_and_what_it_points_to_is_left(tmp_path):
    """Kept as it was: the file is written at the path given, so a link there becomes a regular file."""
    real = tmp_path / "real"
    real.write_text("pointed to")
    link = tmp_path / "link"
    link.symlink_to(real)
    write_text_atomic(link, "new")
    assert not link.is_symlink() and link.read_text() == "new" and real.read_text() == "pointed to"


def test_two_writes_at_once_each_use_a_temp_file_of_their_own(tmp_path, monkeypatch):
    """The callers hold no file lock, so a second write started while the first is open must not take
    its temp file: the first still lands whole."""
    tmp_path = tmp_path / "dir"
    tmp_path.mkdir()
    target = tmp_path / "f"
    target.write_text("old")
    real, inner = os.fsync, []

    def hook(fd):
        if not inner:
            inner.append(1)
            write_text_atomic(target, "second")
        return real(fd)

    monkeypatch.setattr(os, "fsync", hook)
    write_text_atomic(target, "first")
    assert target.read_text() == "first" and sorted(p.name for p in tmp_path.iterdir()) == ["f"]


def test_a_write_another_process_replaces_right_after_still_returns(tmp_path, monkeypatch):
    """These callers hold no file lock, so another sheaf command can replace the file just after this write's
    replace: the last writer wins, as before, and the first is not told its text is missing."""
    target = tmp_path / "f"
    target.write_text("old")
    real = os.replace

    def then_theirs(src, dst, *a, **k):
        real(src, dst, *a, **k)
        if Path(dst) == target:
            Path(dst).write_text("theirs")

    monkeypatch.setattr(os, "replace", then_theirs)
    write_text_atomic(target, "mine")
    assert target.read_text() == "theirs"


# ── ticket 194 A, B, C (#570) ────────────────────────────────────────────────

@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="owner bits mean nothing to root; Windows has none")
def test_a_mode_that_leaves_the_owner_no_read_is_still_given(tmp_path):
    """The read-back of the temp file is made before its mode is set, so a mode without the owner's read is the
    file's, as any other mode is."""
    target = tmp_path / "f"
    target.write_text("old\n")
    write_text_atomic(target, "new\n", mode=0o200)
    assert stat.S_IMODE(target.stat().st_mode) == 0o200
    os.chmod(target, 0o600)
    assert target.read_text() == "new\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["f"]


@pytest.mark.skipif(os.name == "nt", reason="no owner-only mode on Windows")
@pytest.mark.parametrize("locked", [False, True], ids=["file", "document"])
def test_the_temp_file_is_the_owners_alone_until_its_text_is_whole(tmp_path, monkeypatch, locked):
    """A temp file a crash leaves half written is never readable by the group or others, whatever mode the file gets."""
    from sheafmd import source
    target = tmp_path / "f.md"
    target.write_text("old\n")
    os.chmod(target, 0o644)
    real, modes = os.fsync, []

    def hook(fd):
        modes.append(stat.S_IMODE(os.fstat(fd).st_mode))
        return real(fd)
    monkeypatch.setattr(os, "fsync", hook)
    if locked:
        source._write_atomic(target, "new\n")
    else:
        write_text_atomic(target, "new\n", mode=0o644)
    assert modes and all(m == 0o600 for m in modes), oct(modes[0]) if modes else modes
    assert stat.S_IMODE(target.stat().st_mode) == 0o644 and target.read_text() == "new\n"


@pytest.mark.skipif(not os.path.isdir("/proc/self/fd"), reason="counts descriptors through /proc")
@pytest.mark.parametrize("locked", [False, True], ids=["file", "document"])
def test_a_text_that_cannot_be_encoded_leaves_no_descriptor_and_no_temp_file(tmp_path, locked):
    from sheafmd import source
    target = tmp_path / "f.md"
    target.write_text("old\n")
    before = len(os.listdir("/proc/self/fd"))
    with pytest.raises(UnicodeEncodeError):
        if locked:
            source._write_atomic(target, "bad \ud800\n")
        else:
            write_text_atomic(target, "bad \ud800\n")
    assert len(os.listdir("/proc/self/fd")) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["f.md"] and target.read_text() == "old\n"
