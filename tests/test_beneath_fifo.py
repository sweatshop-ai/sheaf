"""A name turned into a FIFO after a file was opened beneath its root is never waited on: a save, changed or not, is
refused at once (an error) and its lock is let go, on the `openat2` open and on the walk of our own."""
import os
import threading

import pytest

from sheafmd import beneath
from sheafmd.source import update_beneath


@pytest.mark.parametrize("walk", [False, True], ids=["openat2", "walk"])
@pytest.mark.parametrize("rel", ["a.md", "d/e/a.md"])
@pytest.mark.parametrize("changed", [True, False], ids=["changed", "unchanged"])
def test_a_save_does_not_wait_on_a_fifo_that_took_the_name_after_the_read(tmp_path, monkeypatch, walk, rel, changed):
    monkeypatch.setattr(beneath, "FALLBACK", walk)
    f = tmp_path / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("one\n", encoding="utf-8")
    out = []

    def change(text, opened):
        f.unlink()
        os.mkfifo(f)                     # after the initial read, before the write
        return "two\n" if changed else text

    def save():
        try:
            out.append(update_beneath(tmp_path, rel, change))
        except OSError as e:
            out.append(e)

    t = threading.Thread(target=save, daemon=True)
    t.start()
    t.join(5)
    if t.is_alive():
        # unblock the thread blocked in open(): a writer on the FIFO ends the test cleanly
        fd = os.open(f, os.O_WRONLY | os.O_NONBLOCK)
        os.close(fd)
        t.join(5)
        pytest.fail("the save waits on the FIFO")
    if changed:
        assert isinstance(out[0], OSError)
    else:
        assert out[0] == ("one\n", "one\n")


@pytest.mark.parametrize("walk", [False, True], ids=["openat2", "walk"])
def test_a_fifo_where_the_file_is_opened_is_refused_not_waited_on(tmp_path, monkeypatch, walk):
    monkeypatch.setattr(beneath, "FALLBACK", walk)
    os.mkfifo(tmp_path / "a.md")
    out = []

    def go():
        try:
            beneath.open_beneath(tmp_path, "a.md").close()
        except OSError as e:
            out.append(e)

    t = threading.Thread(target=go, daemon=True)
    t.start()
    t.join(5)
    if t.is_alive():
        os.close(os.open(tmp_path / "a.md", os.O_WRONLY | os.O_NONBLOCK))
        t.join(5)
        pytest.fail("the open waits on the FIFO")
    assert out and isinstance(out[0], OSError)


def test_a_folder_moved_outside_the_root_after_the_read_is_refused_and_the_file_outside_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(beneath, "FALLBACK", False)
    root, outside = tmp_path / "root", tmp_path / "outside"
    (root / "d").mkdir(parents=True)
    outside.mkdir()
    (root / "d" / "a.md").write_text("one\n", encoding="utf-8")
    with beneath.open_beneath(root, "d/a.md") as op:
        if op.how != "openat2":
            pytest.skip("no openat2 here: the walk of our own is the one in use")
        assert op.text() == "one\n"
        os.rename(root / "d", outside / "d")          # the folder leaves the root after the read
        with pytest.raises(OSError):
            op.write("two\n")
    assert (outside / "d" / "a.md").read_text(encoding="utf-8") == "one\n"
    assert sorted(p.name for p in (outside / "d").iterdir()) == ["a.md"]
