"""The Source file: the one .md every writer goes through, from any process."""
import errno
import hashlib
import os
import re
import stat
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import pytest

from sheafmd import comments as rdc
from sheafmd import paths
from sheafmd import source as rds

DOC = ("Para one here.\n\n| A | B |\n|---|---|\n| cell | x |\n")


def make(tmp_path, name="d.md", text=DOC):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_a_hash_names_the_text_and_nothing_else():
    assert rds.md_hash(DOC) == rds.md_hash(str(DOC))
    assert rds.md_hash(DOC) != rds.md_hash(DOC + "\n")
    assert re.fullmatch(r"[0-9a-f]{16}", rds.md_hash(DOC))
    assert rds.md_hash(DOC) == hashlib.sha256(DOC.encode()).hexdigest()[:16]


def test_now_is_minutes_in_local_time():
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d", rds.now())


def test_a_change_that_returns_the_same_text_writes_nothing(tmp_path):
    p = make(tmp_path)
    before = p.stat().st_mtime_ns
    assert rds.update_file(p, lambda t: t) == (DOC, DOC)
    assert p.stat().st_mtime_ns == before


def test_locked_update_refuses_a_stale_hash(tmp_path):
    p = make(tmp_path)
    with pytest.raises(rds.StaleError):
        rds.update_file(p, lambda t: t + "x\n", expected_hash="0" * 16)
    assert p.read_text(encoding="utf-8") == DOC


def test_a_matching_hash_lets_the_write_through(tmp_path):
    p = make(tmp_path)
    old, new = rds.update_file(p, lambda t: t + "x\n", expected_hash=rds.md_hash(DOC))
    assert (old, new) == (DOC, DOC + "x\n") and p.read_text(encoding="utf-8") == DOC + "x\n"


WORKER = r'''
import sys
from pathlib import Path
from sheafmd import comments as rdc
from sheafmd import source as rds
p = Path(sys.argv[1])
for n in range(int(sys.argv[3])):
    def add(t):
        blk, s, e = rdc.find_quote(t, "Para one")
        return rdc.add_comment(t, blk, s, e, "Para one", sys.argv[2] + str(n), "W", "2026-09-22T10:00")[0]
    rds.update_file(p, add)
'''


def test_two_processes_writing_at_once_lose_nothing(tmp_path):
    p = make(tmp_path)
    procs = [subprocess.Popen([sys.executable, "-c", WORKER, str(p), tag, "25"])
             for tag in ("a", "b")]
    for pr in procs:
        assert pr.wait(timeout=180) == 0
    bodies = {c.body for c in rdc.parse(p.read_text(encoding="utf-8")).comments}
    assert bodies == {f"{t}{n}" for t in "ab" for n in range(25)}


# ---- where the lock lives ----------------------------------------------------

def test_the_lock_is_a_file_in_the_runtime_folder_and_none_appears_next_to_the_md(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    p = make(docs)
    rds.update_file(p, lambda t: t + "x\n")
    assert sorted(x.name for x in docs.iterdir()) == ["d.md"]
    key = hashlib.sha1(str(p.resolve()).encode()).hexdigest()[:12]
    lock = paths.runtime_dir() / "locks" / f"{key}.lock"
    assert lock.is_file() and rds.lock_key(p) == key
    assert stat.S_IMODE(lock.stat().st_mode) == 0o600
    assert stat.S_IMODE(lock.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(paths.runtime_dir().stat().st_mode) == 0o700


def test_a_symlink_and_its_target_are_one_document_with_one_lock(tmp_path):
    real = make(tmp_path, "real.md")
    link = tmp_path / "link.md"
    link.symlink_to(real)
    assert rds.lock_key(link) == rds.lock_key(real)


def test_the_runtime_folder_ignores_sheaf_home(tmp_path, monkeypatch):
    """A development hub and the daily CLI must lock the same .md through the same file."""
    p = make(tmp_path)
    monkeypatch.setenv("SHEAF_HOME", str(tmp_path / "one"))
    a = rds._lock_path(p)
    monkeypatch.setenv("SHEAF_HOME", str(tmp_path / "two"))
    assert rds._lock_path(p) == a


def blocked_until_released(tmp_path, held_path):
    """Hold an flock on held_path, start an update, and report whether it waited."""
    import fcntl
    p = make(tmp_path)
    held_path.parent.mkdir(parents=True, exist_ok=True)
    holder = open(held_path, "a+")
    fcntl.flock(holder, fcntl.LOCK_EX)
    done = threading.Event()
    t = threading.Thread(target=lambda: (rds.update_file(p, lambda s: s + "x\n"), done.set()))
    t.start()
    waited = not done.wait(0.4)
    fcntl.flock(holder, fcntl.LOCK_UN)
    holder.close()
    t.join(timeout=10)
    assert done.is_set() and p.read_text(encoding="utf-8") == DOC + "x\n"
    return waited


def test_an_update_waits_for_the_lock_in_the_runtime_folder(tmp_path):
    key = rds.lock_key(tmp_path / "d.md")
    assert blocked_until_released(tmp_path, paths.runtime_dir() / "locks" / f"{key}.lock")


def legacy_dir():
    return Path(tempfile.gettempdir()) / "render-doc" / "locks"


def test_an_update_also_waits_for_a_legacy_render_doc_lock_while_that_folder_exists(tmp_path):
    key = rds.lock_key(tmp_path / "d.md")
    assert blocked_until_released(tmp_path, legacy_dir() / f"{key}.lock")


def test_without_the_legacy_folder_nothing_is_created_there(tmp_path):
    p = make(tmp_path)
    rds.update_file(p, lambda t: t + "x\n")
    assert not (legacy_dir().parent).exists()


def test_the_legacy_lock_is_taken_after_the_sheaf_lock_and_both_are_released(tmp_path):
    p = make(tmp_path)
    legacy_dir().mkdir(parents=True)
    with rds.file_lock(p) as lk:
        assert [x.name for x in lk.paths] == [rds.lock_key(p) + ".lock"] * 2
        assert lk.paths[0].parent == paths.runtime_dir() / "locks" and lk.paths[1].parent == legacy_dir()
    assert lk.files == []


# ---- the atomic write --------------------------------------------------------

def test_the_new_text_goes_through_a_hidden_sibling_with_the_original_mode(tmp_path, monkeypatch):
    p = make(tmp_path)
    os.chmod(p, 0o640)
    seen = {}
    real_replace = os.replace

    def spy(src, dst):
        seen["src"], seen["dst"] = Path(src), Path(dst)
        seen["mode"] = stat.S_IMODE(os.stat(src).st_mode)
        seen["text"] = Path(src).read_text(encoding="utf-8")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    rds.update_file(p, lambda t: t + "x\n")
    assert seen["src"] == tmp_path / ".d.md.sheaf-tmp" and seen["dst"] == p.resolve()
    assert seen["mode"] == 0o640 and seen["text"] == DOC + "x\n"
    assert stat.S_IMODE(p.stat().st_mode) == 0o640
    assert [x.name for x in tmp_path.iterdir() if x.name != "run" and x.name != "tmp"] == ["d.md"]


def test_the_mode_survives_whatever_the_umask_says(tmp_path):
    p = make(tmp_path)
    os.chmod(p, 0o664)
    old = os.umask(0o077)
    try:
        rds.update_file(p, lambda t: t + "x\n")
    finally:
        os.umask(old)
    assert stat.S_IMODE(p.stat().st_mode) == 0o664


def test_a_stale_sibling_from_a_crash_is_overwritten_not_trusted(tmp_path):
    p = make(tmp_path)
    os.chmod(p, 0o644)
    leftover = tmp_path / ".d.md.sheaf-tmp"
    leftover.write_text("half a write that never got replaced", encoding="utf-8")
    os.chmod(leftover, 0o600)
    rds.update_file(p, lambda t: t + "x\n")
    assert p.read_text(encoding="utf-8") == DOC + "x\n"
    assert stat.S_IMODE(p.stat().st_mode) == 0o644 and not leftover.exists()


def test_a_link_planted_at_the_sibling_is_not_written_through(tmp_path):
    """Whoever can write the folder can plant `.<name>.sheaf-tmp` as a link to a file outside it.
    The write must not follow it (the file behind it keeps its text), and the document must
    stay a regular file."""
    shared = tmp_path / "shared"
    shared.mkdir()
    p = make(shared, text="keep\n")
    victim = tmp_path / "note.txt"
    victim.write_text("personal\n", encoding="utf-8")
    (shared / ".d.md.sheaf-tmp").symlink_to(victim)
    rds.update_file(p, lambda _: "replacement\n")
    assert victim.read_text(encoding="utf-8") == "personal\n"
    assert p.read_text(encoding="utf-8") == "replacement\n" and not p.is_symlink()
    assert not (shared / ".d.md.sheaf-tmp").exists()


def test_a_link_planted_between_the_unlink_and_the_open_is_refused(tmp_path, monkeypatch):
    """The sibling is made with O_EXCL: a link that appears after the stale one was removed
    makes the open fail, so nothing behind it is written, and the document is left as it was."""
    shared = tmp_path / "shared"
    shared.mkdir()
    p = make(shared, text="keep\n")
    victim = tmp_path / "note.txt"
    victim.write_text("personal\n", encoding="utf-8")
    sibling = shared / ".d.md.sheaf-tmp"
    real_unlink = os.unlink
    planted = []

    def plant_after(path, *a, **k):
        try:
            real_unlink(path, *a, **k)
        finally:
            if Path(path) == sibling and not planted:
                planted.append(sibling)
                sibling.symlink_to(victim)

    monkeypatch.setattr(os, "unlink", plant_after)
    with pytest.raises(OSError):
        rds.update_file(p, lambda _: "replacement\n")
    assert planted
    assert victim.read_text(encoding="utf-8") == "personal\n"
    assert p.read_text(encoding="utf-8") == "keep\n"


def swap_the_sibling_at(monkeypatch, name, sibling, put, swap=True):
    """Replace os.<name> (`fsync`, called while the sibling is open, or `replace`, called with it)
    by one that first removes the sibling and lets `put(sibling)` make something else at its name,
    as a user who can write the folder can at any moment, then does the real call. With swap False
    nothing is made: the control."""
    real = getattr(os, name)
    swapped = []

    def hook(*a, **k):
        if swap and not swapped and os.path.lexists(sibling):
            swapped.append(sibling)
            os.unlink(sibling)
            put(sibling)
        return real(*a, **k)

    monkeypatch.setattr(os, name, hook)
    return swapped


def outside_file(tmp_path):
    victim = tmp_path / "note.txt"
    victim.write_text("personal\n", encoding="utf-8")
    return victim


@pytest.mark.parametrize("swap", [True, False], ids=["swapped", "control"])
@pytest.mark.parametrize("planted", ["a link", "a file"])
def test_a_sibling_swapped_after_the_open_is_not_put_in_the_documents_place(tmp_path, monkeypatch, swap,
                                                                            planted):
    """The sibling is opened with O_EXCL|O_NOFOLLOW, but a user who can write the folder can remove
    it while the text is written and put a link (or a file of their own) at its name. Before the
    replace its name must still hold the file written, a regular file; otherwise nothing replaces
    the document and the write fails, so it is not acknowledged."""
    shared = tmp_path / "shared"
    shared.mkdir()
    p = make(shared, text="keep\n")
    victim = outside_file(tmp_path)
    put = (lambda s: s.symlink_to(victim)) if planted == "a link" else \
          (lambda s: s.write_text("theirs\n", encoding="utf-8"))
    swapped = swap_the_sibling_at(monkeypatch, "fsync", shared / ".d.md.sheaf-tmp", put, swap)
    if swap:
        with pytest.raises(OSError, match="was replaced while the new text was written"):
            rds.update_file(p, lambda _: "replacement\n")
        assert swapped
        assert p.read_text(encoding="utf-8") == "keep\n"
    else:
        rds.update_file(p, lambda _: "replacement\n")
        assert p.read_text(encoding="utf-8") == "replacement\n"
    assert not p.is_symlink() and victim.read_text(encoding="utf-8") == "personal\n"
    assert sorted(x.name for x in shared.iterdir()) == ["d.md"]


@pytest.mark.parametrize("swap", [True, False], ids=["swapped", "control"])
def test_a_sibling_swapped_between_the_look_and_the_replace_fails_the_write(tmp_path, monkeypatch, swap):
    """The look before the replace narrows the window and cannot close it: rename takes names, so a
    link put at the sibling's name after that look is what the document's name gets. The write then
    fails instead of answering as if the text were in the document. A user who can write the folder
    could make the document a link without sheaf, at any time (SPEC 9.1)."""
    shared = tmp_path / "shared"
    shared.mkdir()
    p = make(shared, text="keep\n")
    victim = outside_file(tmp_path)
    swap_the_sibling_at(monkeypatch, "replace", shared / ".d.md.sheaf-tmp",
                        lambda s: s.symlink_to(victim), swap)
    if swap:
        with pytest.raises(OSError, match="is not the file just written"):
            rds.update_file(p, lambda _: "replacement\n")
        assert p.is_symlink(), "the folder's writer made it a link: the write could not stop that"
    else:
        rds.update_file(p, lambda _: "replacement\n")
        assert p.read_text(encoding="utf-8") == "replacement\n" and not p.is_symlink()
    assert victim.read_text(encoding="utf-8") == "personal\n"


def put_at_the_name_after_the_replace(monkeypatch, what):
    """Right after the real replace, the document's name holds `what` instead of the inode just
    written: "a copy" (its bytes, another inode, which is what a file system that numbers files by
    name shows, such as an rclone mount), "their file" (other bytes), "a link" (to a file with the
    same bytes), "a folder" or "a pipe"."""
    real_replace = os.replace

    def replace(src, dst):
        real_replace(src, dst)
        dst = Path(dst)
        data = dst.read_bytes()
        if what == "a copy":
            dst.with_name("copy").write_bytes(data)
            real_replace(dst.with_name("copy"), dst)
        elif what == "their file":
            dst.with_name("theirs").write_bytes(b"theirs\n")
            real_replace(dst.with_name("theirs"), dst)
        elif what == "a link":
            elsewhere = dst.parent.parent / "elsewhere.md"
            real_replace(dst, elsewhere)
            dst.symlink_to(elsewhere)
        elif what == "a folder":
            dst.unlink()
            dst.mkdir()
        else:
            dst.unlink()
            os.mkfifo(dst)

    monkeypatch.setattr(os, "replace", replace)


def test_a_file_system_that_numbers_a_file_by_its_name_still_saves(tmp_path, monkeypatch):
    """On an rclone mount the document's name keeps its old inode number after the replace. The
    text is in the document all the same, and the write must not say otherwise."""
    shared = tmp_path / "shared"
    shared.mkdir()
    p = make(shared, text="keep\n")
    put_at_the_name_after_the_replace(monkeypatch, "a copy")
    assert rds.update_file(p, lambda _: "replacement\n") == ("keep\n", "replacement\n")
    assert p.read_text(encoding="utf-8") == "replacement\n" and not p.is_symlink()
    assert sorted(x.name for x in shared.iterdir()) == ["d.md"]


@pytest.mark.parametrize("what", ["their file", "a link", "a folder", "a pipe"])
def test_after_the_replace_only_the_bytes_written_in_a_regular_file_pass(tmp_path, monkeypatch, what):
    """What passes is a regular file holding exactly the bytes written: not other bytes, not a link
    to those bytes, not a folder; a pipe is answered without waiting on it; and nothing is left open."""
    shared = tmp_path / "shared"
    shared.mkdir()
    p = make(shared, text="keep\n")
    put_at_the_name_after_the_replace(monkeypatch, what)
    raised = []

    def write():
        try:
            rds.update_file(p, lambda _: "replacement\n")
        except OSError as e:
            raised.append(e)

    t = threading.Thread(target=write, daemon=True)
    t.start()
    t.join(timeout=20)
    assert not t.is_alive(), "the write hangs on what is at the name"
    assert raised and "is not the file just written" in str(raised[0])
    if Path("/proc/self/fd").is_dir():
        assert not [fd for fd in Path("/proc/self/fd").iterdir()
                    if os.path.realpath(fd).startswith(str(shared))], "a descriptor is left open"


def open_in_this_process(path) -> bool:
    fds = Path("/proc/self/fd")
    return any(os.path.realpath(fd) == str(path) for fd in fds.iterdir() if fd.is_symlink())


@pytest.mark.skipif(not Path("/proc/self/fd").is_dir(), reason="reads /proc/self/fd")
@pytest.mark.parametrize("looks", [True, False], ids=["here", "windows"])
def test_the_sibling_is_closed_at_the_replace_and_looked_at_except_on_windows(tmp_path, monkeypatch, looks):
    """Closed before the replace, as before the looks: an error that only the close reports (an
    upload that fails on an rclone mount) comes before the document is touched. The looks run
    everywhere but on Windows, which replaces as before."""
    p = make(tmp_path, text="keep\n")
    monkeypatch.setattr(rds, "CHECKS_THE_NAMES", looks)
    seen, real_replace = [], os.replace

    def spy(src, dst):
        seen.append(open_in_this_process(src))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    names = []
    monkeypatch.setattr(rds, "_holds_bytes", lambda name, data: names.append((name, data)) or True)
    rds.update_file(p, lambda _: "replacement\n")
    assert seen == [False] and p.read_text(encoding="utf-8") == "replacement\n"
    target = p.resolve()
    assert names == ([(target.with_name(".d.md.sheaf-tmp"), b"replacement\n"), (target, b"replacement\n")]
                     if looks else [])


class CloseFails:
    """The sibling's file, whose close reports an error after closing it, as an rclone mount reports
    an upload that failed (in --vfs-cache-mode off or minimal nothing is sent before the close)."""

    def __init__(self, f):
        self.f = f

    def __getattr__(self, name):
        return getattr(self.f, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if not self.f.closed:
            self.f.close()
            raise OSError(errno.EIO, "Input/output error")


@pytest.mark.parametrize("fails", [True, False], ids=["close fails", "control"])
def test_a_close_that_fails_leaves_the_document_as_it_was(tmp_path, monkeypatch, fails):
    """On an rclone mount a rename made before such a close hides the document from the mount until
    its folder cache expires, where main left it in place. The close comes first."""
    p = make(tmp_path, text="keep\n")
    real_fdopen = os.fdopen

    def fdopen(fd, mode="r", *a, **k):
        f = real_fdopen(fd, mode, *a, **k)
        return CloseFails(f) if fails and "w" in mode else f

    monkeypatch.setattr(os, "fdopen", fdopen)
    if fails:
        with pytest.raises(OSError, match="Input/output error"):
            rds.update_file(p, lambda _: "replacement\n")
        assert p.read_text(encoding="utf-8") == "keep\n"
    else:
        rds.update_file(p, lambda _: "replacement\n")
        assert p.read_text(encoding="utf-8") == "replacement\n"
    assert sorted(x.name for x in tmp_path.iterdir() if x.name not in ("run", "tmp")) == ["d.md"]


def test_without_a_planted_link_the_write_goes_through_the_sibling(tmp_path):
    p = make(tmp_path, text="keep\n")
    rds.update_file(p, lambda _: "replacement\n")
    assert p.read_text(encoding="utf-8") == "replacement\n" and not p.is_symlink()
    assert not (tmp_path / ".d.md.sheaf-tmp").exists()


def test_a_failed_replace_leaves_the_document_and_no_sibling(tmp_path, monkeypatch):
    p = make(tmp_path)

    def boom(src, dst):
        raise OSError("disk went away")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        rds.update_file(p, lambda t: t + "x\n")
    assert p.read_text(encoding="utf-8") == DOC
    assert not (tmp_path / ".d.md.sheaf-tmp").exists()


def test_a_change_that_raises_leaves_the_document_alone(tmp_path):
    p = make(tmp_path)

    def bad(t):
        raise ValueError("no")

    with pytest.raises(ValueError):
        rds.update_file(p, bad)
    assert p.read_text(encoding="utf-8") == DOC
    assert not (tmp_path / ".d.md.sheaf-tmp").exists()


def test_an_atomic_write_through_a_symlinked_md_writes_the_target_and_leaves_the_link(tmp_path):
    """The old code made its temp file next to the link and replaced the
    link itself: the link became a regular file and the real document stayed old.
    sheaf resolves the link first, so the target gets the write."""
    store = tmp_path / "store"
    store.mkdir()
    real = make(store, "real.md")
    os.chmod(real, 0o640)
    link = tmp_path / "link.md"
    link.symlink_to(os.path.relpath(real, tmp_path))      # a relative link, as people make them
    target_text = os.readlink(link)
    old, new = rds.update_file(link, lambda t: t + "added\n")
    assert old == DOC and new == DOC + "added\n"
    assert link.is_symlink() and os.readlink(link) == target_text
    assert real.read_text(encoding="utf-8") == DOC + "added\n" and not real.is_symlink()
    assert stat.S_IMODE(real.stat().st_mode) == 0o640
    assert link.read_text(encoding="utf-8") == DOC + "added\n"
    assert sorted(x.name for x in store.iterdir()) == ["real.md"]      # the sibling sits next to the target
    assert sorted(x.name for x in tmp_path.iterdir() if x.name not in ("run", "tmp", "store")) == ["link.md"]


def test_a_chain_of_links_ends_at_the_real_file(tmp_path):
    real = make(tmp_path, "real.md")
    (tmp_path / "b.md").symlink_to(real)
    (tmp_path / "a.md").symlink_to(tmp_path / "b.md")
    rds.update_file(tmp_path / "a.md", lambda t: t + "x\n")
    assert (tmp_path / "a.md").is_symlink() and (tmp_path / "b.md").is_symlink()
    assert real.read_text(encoding="utf-8") == DOC + "x\n"


def test_a_stale_hash_through_a_symlink_refuses_and_changes_nothing(tmp_path):
    real = make(tmp_path, "real.md")
    link = tmp_path / "link.md"
    link.symlink_to(real)
    with pytest.raises(rds.StaleError):
        rds.update_file(link, lambda t: t + "x\n", expected_hash="0" * 16)
    assert link.is_symlink() and real.read_text(encoding="utf-8") == DOC


def test_one_stamp_format_serves_every_timestamp_the_hub_writes():
    import time
    from sheafmd.source import STAMP_FORMAT
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d{4}", time.strftime(STAMP_FORMAT))
