"""The Markdown-file adapter's writes are correct (block editor v1, ticket 26): a path is found once, the base it returns
is the one its own next read computes, a source policy refusal is an outcome, and a save that waits for the file lock
looks nothing up again."""
import os
import sys
import threading

import pytest
from helpers import PLAN
from two_roots import two_roots

from sheafmd import adapter as rda
from sheafmd import beneath
from sheafmd import source as rds
from sheafmd.blocks import split_md_blocks
from sheafmd.hub.place import NotFound

DOC = "Para one.\n\nPara two.\n"


def test_a_callable_path_is_asked_once_per_write_and_the_write_lands_on_that_file(tmp_path):
    """A: the suffix was judged on the first answer and the text written to the second: a path that moved in between put
    a .md's text over a file that is not Markdown."""
    md, other = tmp_path / "a.md", tmp_path / "other.txt"
    md.write_text(DOC, encoding="utf-8")
    other.write_text(DOC, encoding="utf-8")          # the same content, so the same base
    asked = []

    def path():
        asked.append(1)
        return md if len(asked) == 1 else other
    out = rda.MarkdownFileAdapter(path).write(rda.Tree("Changed.\n"), rds.md_hash(DOC))
    assert out["outcome"] == "written"
    assert len(asked) == 1
    assert md.read_text(encoding="utf-8") == "Changed.\n"
    assert other.read_text(encoding="utf-8") == DOC


def test_a_callable_path_is_asked_once_per_apply(tmp_path):
    md = tmp_path / "a.md"
    md.write_text(DOC, encoding="utf-8")
    asked = []

    def path():
        asked.append(1)
        return md
    rda.MarkdownFileAdapter(path).apply(lambda t, op: "Changed.\n")
    assert len(asked) == 1


def test_a_write_of_crlf_text_returns_the_base_its_next_read_computes(tmp_path):
    """B: the hash came from the CRLF text, the read gives LF: the adapter refused its own returned base."""
    md = tmp_path / "a.md"
    md.write_text(DOC, encoding="utf-8")
    a = rda.MarkdownFileAdapter(md)
    _, base = a.read()
    out = a.write(rda.Tree("One.\r\n\r\nTwo.\r\n"), base)
    assert out["outcome"] == "written"
    assert out["base"] == a.read()[1]
    again = a.write(rda.Tree("Three.\n"), out["base"])
    assert again["outcome"] == "written", again


def test_a_write_of_lone_cr_text_hands_back_the_text_as_read_too(tmp_path):
    md = tmp_path / "a.md"
    md.write_text(DOC, encoding="utf-8")
    kept = []
    out, _, new = rda.MarkdownFileAdapter(md).apply(lambda t, op: "One.\rTwo.\r\nThree.\n", kept=kept.append)
    assert new == "One.\nTwo.\nThree.\n" == kept[0]
    assert out["base"] == rds.md_hash(new) == rda.MarkdownFileAdapter(md).read()[1]


def test_the_document_service_refuses_a_path_that_leaves_its_root_too(tmp_path):
    from sheafmd.document import DocumentService
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text(DOC, encoding="utf-8")
    (root / "link.md").symlink_to(outside)
    svc = DocumentService(rda.MarkdownFileAdapter(beneath=lambda: (root, "link.md")))
    out = svc.write(lambda t, op: "Changed.\n")
    assert out["outcome"] == "refused"
    assert outside.read_text(encoding="utf-8") == DOC


def test_a_write_in_a_root_of_crlf_text_returns_the_base_its_next_read_computes(tmp_path):
    (tmp_path / "a.md").write_text(DOC, encoding="utf-8")
    a = rda.MarkdownFileAdapter(beneath=lambda: (tmp_path, "a.md"))
    _, base = a.read()
    out = a.write(rda.Tree("One.\r\n\r\nTwo.\r\n"), base)
    assert out["outcome"] == "written"
    assert out["base"] == a.read()[1]


def test_an_md_path_that_leaves_its_root_is_refused_not_raised(tmp_path):
    """C: `Escapes` (a path outside its root, a loop, a place the hub keeps) came out of write() as an exception."""
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text(DOC, encoding="utf-8")
    (root / "link.md").symlink_to(outside)
    a = rda.MarkdownFileAdapter(beneath=lambda: (root, "link.md"))
    out = a.write(rda.Tree("Changed.\n"), rds.md_hash(DOC))
    assert out["outcome"] == "refused" and out["reason"]
    assert outside.read_text(encoding="utf-8") == DOC


def test_a_missing_file_is_still_an_error_not_a_refusal(tmp_path):
    a = rda.MarkdownFileAdapter(beneath=lambda: (tmp_path, "nope.md"))
    with pytest.raises(FileNotFoundError):
        a.write(rda.Tree("x\n"), rds.md_hash(DOC))


def test_a_save_whose_root_is_forgotten_while_it_waits_for_the_file_lock_still_lands(tmp_path, monkeypatch):
    """D (hub level): the save found its file once and opened it beneath its root; a second look-up for a diagnostic,
    made under the lock, raised NotFound for a placed root forgotten in the wait and aborted the edit."""
    two = two_roots(tmp_path)
    hub = two.hub()
    root = hub.the_list.root()
    (two.list_repo / "acme").mkdir()
    f = two.list_repo / "acme" / "post.md"
    f.write_text(PLAN, encoding="utf-8")
    address = f"{root.name}/acme/post.md"
    e = hub.entry(address)
    text = f.read_text(encoding="utf-8")
    i = next(n for n, b in enumerate(split_md_blocks(text)) if b.content.startswith("First paragraph"))
    done = []

    def save():
        try:
            done.append(e.live.save(rds.md_hash(text), [{"i": i, "html": "<p>Edited words.</p>"}]))
        except BaseException as ex:
            done.append(ex)
    at_lock = threading.Event()
    real = rds.file_lock

    class Signalling(real):
        def __enter__(self):
            at_lock.set()                   # the save is at the lock: what it waits for is held below
            return super().__enter__()
    with real(f):
        monkeypatch.setattr(rds, "file_lock", Signalling)
        t = threading.Thread(target=save, daemon=True)
        t.start()
        assert at_lock.wait(10)
        assert t.is_alive()
        gone, finish = hub.let_go_root(root.name)
        assert gone is not None
    t.join(10)
    assert not t.is_alive()
    assert isinstance(done[0], dict), done
    assert done[0]["changed"]
    assert "Edited words." in f.read_text(encoding="utf-8")
    finish()


def test_a_root_forgotten_between_the_write_and_the_render_does_not_fail_the_save(tmp_path):
    """D, the render after the write: the root goes after the save looked at its own detach flag and before the render
    found the file. The edit is written and answered."""
    from sheafmd.hub.place import NotFound
    two = two_roots(tmp_path)
    hub = two.hub()
    root = hub.the_list.root()
    (two.list_repo / "acme").mkdir()
    f = two.list_repo / "acme" / "post.md"
    f.write_text(PLAN, encoding="utf-8")
    e = hub.entry(f"{root.name}/acme/post.md")
    text = f.read_text(encoding="utf-8")
    i = next(n for n, b in enumerate(split_md_blocks(text)) if b.content.startswith("First paragraph"))
    finishes = []

    def render(_text, _gen):
        finishes.append(hub.let_go_root(root.name)[1])       # the root goes while the render starts, then its file is not found
        raise NotFound("gone")
    e.live.install = render
    out = e.live.save(rds.md_hash(text), [{"i": i, "html": "<p>Edited words.</p>"}])
    assert out["changed"] and "Edited words." in f.read_text(encoding="utf-8")
    finishes[0]()


def _escaping(tmp_path):
    def where():
        raise beneath.Escapes("x.md")
    return rda.MarkdownFileAdapter(beneath=where)


def test_a_resolver_that_raises_a_policy_refusal_is_refused_by_the_adapter_and_the_service(tmp_path):
    from sheafmd.document import DocumentService
    a = _escaping(tmp_path)
    assert a.write(rda.Tree("x\n"), "b")["outcome"] == "refused"
    assert DocumentService(a).write(lambda t, op: "x\n")["outcome"] == "refused"


def test_a_policy_error_of_a_hook_after_the_write_is_not_a_refusal_and_the_session_record_is_made(tmp_path):
    """1: the file is written when the hook raises, so the error reaches the caller, and the page session's record of the
    write is made first: its next save from that base is its own, never a conflict."""
    from sheafmd.document import DocumentService
    md = tmp_path / "a.md"
    md.write_text(DOC, encoding="utf-8")
    svc = DocumentService(rda.MarkdownFileAdapter(md))
    svc.read()
    kept = []

    def late():
        raise beneath.Escapes("a.md")
    with pytest.raises(beneath.Escapes):
        svc.write(lambda t, op: "Changed.\n", "s1", kept=kept.append, between=late)
    assert md.read_text(encoding="utf-8") == "Changed.\n"
    assert kept == ["Changed.\n"]                   # the hook after the failing one still ran
    assert svc._own(rds.md_hash(DOC), rds.md_hash("Changed.\n"), "s1")
    assert not svc._own(rds.md_hash(DOC), rds.md_hash("Changed.\n"), "s2")


def test_a_save_without_an_entry_names_in_its_diagnostics_the_file_it_wrote(tmp_path):
    """3: the path was asked for the label and again for the write; two answers named two files."""
    from sheafmd.edit import DOC as DIAG
    from sheafmd.hub.live import LiveDocument
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    a.write_text(PLAN, encoding="utf-8")
    b.write_text(PLAN, encoding="utf-8")
    state = {"n": 0}

    def find():
        state["n"] += 1
        return a if state["n"] == 1 else b
    live = LiveDocument(find, render=lambda text: None, publish=lambda *x, **k: None)
    state["n"] = 0
    seen = []
    import sheafmd.edit as rde
    real = rde.apply_edits

    def spy(text, edits):
        seen.append(DIAG.get())
        return real(text, edits)
    rde.apply_edits = spy
    try:
        text = a.read_text(encoding="utf-8")
        i = next(n for n, x in enumerate(split_md_blocks(text)) if x.content.startswith("First paragraph"))
        live.save(rds.md_hash(text), [{"i": i, "html": "<p>Edited words.</p>"}])
    finally:
        rde.apply_edits = real
    assert seen == [a]
    assert "Edited words." in a.read_text(encoding="utf-8") and "Edited words." not in b.read_text(encoding="utf-8")


REPLACEMENTS = {
    "a document": {"start.md": b"# Other\n\nReplacement words.\n"},
    "invalid utf-8": {"start.md": b"\xff\xfe not utf-8 Replacement"},
    "another document only": {"other.md": b"# Other\n\nReplacement words.\n"},
    "a malformed config": {"start.md": b"# Other\n\nReplacement words.\n", ".sheaf.toml": b"= = not toml ["},
}


def retake_the_name(hub, tmp_path, files):
    """Let the root `work` go, and let another folder with `files` take the name; (the forget's finish, the new folder)."""
    finish = hub.let_go_root("work")[1]
    other = tmp_path / "again" / "work"
    other.mkdir(parents=True)
    for name, data in files.items():
        (other / name).write_bytes(data)
    assert hub.roots.for_document(next(other / n for n in files if n.endswith(".md"))).name == "work"   # the name is held again
    return finish, other


@pytest.mark.parametrize("replacement", REPLACEMENTS)
@pytest.mark.parametrize("window", ["before the render", "between the render and the swap", "a render that raises"])
def test_a_root_forgotten_and_its_name_taken_between_the_write_and_the_page_swap_tells_the_tabs_nothing_of_the_new_root(
        world, work, tmp_path, replacement, window):
    """2: the page a save installs is the text it wrote, rendered against the entry it pinned, and swapped in only while that
    entry's root was not let go; any error of the render once it was is a let go too. Forget the root and let another folder
    take the name in the window: the save is `written` and answered, the tabs hear `gone`, and nothing of the new root is
    installed or served meanwhile."""
    hub = world.hub
    e = hub.entry("work/start.md")
    f = work / "start.md"
    text = f.read_text(encoding="utf-8")
    old_page = e.html
    i = next(n for n, b in enumerate(split_md_blocks(text)) if b.content.startswith("First paragraph"))
    sub = e.bus.subscribe()
    sub.drain()
    finishes, served = [], []

    def take_the_name():
        finishes.append(retake_the_name(hub, tmp_path, REPLACEMENTS[replacement])[0])
    if window == "before the render":
        real = e.live.install
        e.live.install = lambda t, g: (take_the_name(), real(t, g))[1]
    elif window == "a render that raises":
        def compose(*a, **k):
            take_the_name()
            raise RuntimeError("the replacement root's render failed")    # what its config or files make of the render
        hub._build = compose
    else:
        real = hub._build

        def compose(*a, **k):
            out = real(*a, **k)
            take_the_name()
            served.append(e.html)               # a GET in the window reads this
            return out
        hub._build = compose
    out = e.live.save(rds.md_hash(text), [{"i": i, "html": "<p>Edited words.</p>"}])
    assert out["changed"] and "Edited words." in f.read_text(encoding="utf-8")
    assert e.html == old_page and "Replacement" not in e.html and all(h == old_page for h in served)
    finishes[0]()
    events = sub.drain()
    assert "Replacement" not in repr(events) and "Replacement" not in e.live._text
    assert [n for n, _ in events][-1:] == ["gone"], events


@pytest.mark.parametrize("replacement", REPLACEMENTS)
def test_a_get_for_the_old_root_after_its_forget_installs_and_serves_nothing_of_the_new_root(
        world, work, tmp_path, replacement):
    """2: a request already authorized for the old root catches the entry up while the forget is still finishing: the entry
    is let go, so the refresh, the rebuild and the catch-up install nothing, whatever folder holds the name now."""
    hub = world.hub
    e = hub.entry("work/start.md")
    old_page = e.html
    finish, other = retake_the_name(hub, tmp_path, REPLACEMENTS[replacement])
    for md in other.glob("*.md"):                  # the file moved, so a catch-up has something to take in
        md.write_bytes(md.read_bytes() + b"\nMore Replacement.\n")
    for call in (e.live.refresh, e.live.rebuild, lambda: e.live.refresh(force=True), lambda: hub.catch_up(e)):
        try:
            call()
        except (OSError, NotFound):                # let go, or a file the new folder does not hold: a failure, never a page
            pass
        assert e.html == old_page and "Replacement" not in hub.page(e, "n")
    assert e.live._text.find("Replacement") < 0
    finish()


def test_a_write_that_lands_after_a_save_is_taken_in_by_the_watcher_even_with_the_size_and_mtime_kept(world, work):
    """3: the save reads nothing after its write and hands the watcher the status its write took of the file (identity, size,
    both times). An outside write right after it, of the same size and with the modification time put back, moves the change
    time: the watcher sees it, renders it and tells the tabs once. The save's own write is no change to it."""
    hub = world.hub
    e = hub.entry("work/start.md")
    f = work / "start.md"
    text = f.read_text(encoding="utf-8")
    i = next(n for n, b in enumerate(split_md_blocks(text)) if b.content.startswith("First paragraph"))
    sub = e.bus.subscribe()
    sub.drain()
    e.live.save(rds.md_hash(text), [{"i": i, "html": "<p>Edited words.</p>"}])
    assert [n for n, _ in sub.drain()] == ["changed"]
    assert e.last_stat == beneath.stat_key(f.stat())[:4] + (None,)   # the key of the file the save made, before its rename
    hub.tick()
    assert sub.drain() == []                               # its own write is looked at once, and not told again
    assert e.last_stat == beneath.stat_key(f.stat())      # the real key is stored by that first pass
    st = f.stat()
    f.write_text(f.read_text(encoding="utf-8").replace("Edited words.", "Edxted words."), encoding="utf-8")
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))
    after = f.stat()
    assert after.st_size == st.st_size and after.st_mtime_ns == st.st_mtime_ns
    hub.tick()
    assert [n for n, _ in sub.drain()] == ["changed"]
    assert "Edxted words." in e.html and e.live.current()[1] == f.read_text(encoding="utf-8")


@pytest.mark.parametrize("hook", ["between", "kept"])
def test_a_hook_passed_as_none_is_not_called_and_the_write_is_recorded(tmp_path, hook):
    """1: a disabled hook (None) is no hook: the write lands and the session's record is made."""
    from sheafmd.document import DocumentService
    md = tmp_path / "a.md"
    md.write_text(DOC, encoding="utf-8")
    svc = DocumentService(rda.MarkdownFileAdapter(md))
    svc.read()
    out = svc.write(lambda t, op: "Changed.\n", "s1", **{hook: None})
    assert out["outcome"] == "written" and md.read_text(encoding="utf-8") == "Changed.\n"
    assert svc._own(rds.md_hash(DOC), rds.md_hash("Changed.\n"), "s1")


def test_a_forget_that_fails_during_a_first_render_leaves_no_unrendered_entry(world, monkeypatch):
    """The first render of an entry runs while its root is let go and taken back (a forget that failed): the render is
    refused, the entry is not kept with an empty page, and the next open renders it."""
    hub = world.hub
    real = hub._new_entry

    def new_entry(*a, **k):
        e = real(*a, **k)
        e.live.detach()                     # the let-go's first half, its generation raised
        hub._regenerate(e, 1)
        return e
    monkeypatch.setattr(hub, "_new_entry", new_entry)
    with pytest.raises(NotFound):
        hub.entry("work/start.md")
    assert "work/start.md" not in hub.entries
    monkeypatch.setattr(hub, "_new_entry", real)
    e = hub.entry("work/start.md")
    assert e.html and "First paragraph" in e.html


@pytest.mark.parametrize("replacement", REPLACEMENTS)
def test_a_root_let_go_after_the_page_swap_does_not_fail_the_save_through_its_read_back(world, work, tmp_path, replacement):
    """26 D: the save read back the file after its page was installed, by resolving the name again. A root let go in that
    window, with another folder holding the name (a missing file, invalid UTF-8, a malformed config), made the save fail
    after its edit had landed. The save is `written` and let go: it answers, the tabs hear `gone`, nothing of the new root
    is read into the document."""
    hub = world.hub
    e = hub.entry("work/start.md")
    f = work / "start.md"
    text = f.read_text(encoding="utf-8")
    i = next(n for n, b in enumerate(split_md_blocks(text)) if b.content.startswith("First paragraph"))
    sub = e.bus.subscribe()
    sub.drain()
    finishes = []
    real = e.live.install

    def install_then_let_go(t, g):
        out = real(t, g)
        finishes.append(retake_the_name(hub, tmp_path, REPLACEMENTS[replacement])[0])
        return out
    e.live.install = install_then_let_go
    out = e.live.save(rds.md_hash(text), [{"i": i, "html": "<p>Edited words.</p>"}])
    assert out["changed"] and "Edited words." in f.read_text(encoding="utf-8")
    finishes[0]()
    events = sub.drain()
    assert "Replacement" not in repr(events) and "Replacement" not in e.live._text
    assert [n for n, _ in events][-1:] == ["gone"], events


def test_a_save_opens_nothing_after_its_write_so_a_name_given_to_a_fifo_cannot_hang_it(world, work, tmp_path):
    """26 D: after the page is installed the root name goes to another folder whose file of that name is a FIFO. The save has
    no file to open or follow any more: it returns promptly, written, with the edit on disk."""
    hub = world.hub
    e = hub.entry("work/start.md")
    f = work / "start.md"
    text = f.read_text(encoding="utf-8")
    i = next(n for n, b in enumerate(split_md_blocks(text)) if b.content.startswith("First paragraph"))
    finishes = []
    real = e.live.install

    def install_then_the_name_moves(t, g):
        out = real(t, g)
        finish, other = retake_the_name(hub, tmp_path, {"other.md": b"# Other\n"})
        os.mkfifo(other / "start.md")
        finishes.append(finish)
        return out
    e.live.install = install_then_the_name_moves
    done = {}

    def save():
        done["out"] = e.live.save(rds.md_hash(text), [{"i": i, "html": "<p>Edited words.</p>"}])
    t = threading.Thread(target=save, daemon=True)
    t.start()
    t.join(10)
    try:
        assert not t.is_alive(), "the save hangs on the replacement's FIFO"
        assert done["out"]["changed"] and "Edited words." in f.read_text(encoding="utf-8")
    finally:
        if t.is_alive():                    # let a blocked open end, so the test does not leave a thread behind
            fd = os.open(tmp_path / "again" / "work" / "start.md", os.O_RDWR | os.O_NONBLOCK)
            t.join(5)
            os.close(fd)
        for fin in finishes:
            fin()


def test_an_outside_edit_in_place_between_the_rename_and_the_key_of_a_save_is_seen_by_the_watcher(world, work, monkeypatch):
    """26: the status the save hands the watcher is taken from the new file before the rename, with no change time, so the
    first pass after the save compares the file's hash with the text it wrote once. An editor that writes the new file in place
    right after the rename (the same size, the time put back) is then published, never recorded as the save's own."""
    hub = world.hub
    e = hub.entry("work/start.md")
    f = work / "start.md"
    text = f.read_text(encoding="utf-8")
    i = next(n for n, b in enumerate(split_md_blocks(text)) if b.content.startswith("First paragraph"))
    sub = e.bus.subscribe()
    sub.drain()
    real = os.rename

    def rename_then_edit(src, dst, **kw):
        out = real(src, dst, **kw)
        if str(dst) == "start.md":
            st = f.stat()
            with open(f, "r+b") as fh:                  # in place: the same inode, the same size
                data = fh.read().replace(b"Edited words.", b"Edxted words.")
                fh.seek(0)
                fh.write(data)
            os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))
        return out
    monkeypatch.setattr(os, "rename", rename_then_edit)
    e.live.save(rds.md_hash(text), [{"i": i, "html": "<p>Edited words.</p>"}])
    monkeypatch.setattr(os, "rename", real)
    assert "Edxted words." in f.read_text(encoding="utf-8")
    sub.drain()
    hub.tick()
    assert "Edxted words." in e.html and e.live.current()[1] == f.read_text(encoding="utf-8")


@pytest.mark.skipif(not os.path.isdir("/proc/self/fd"), reason="counts descriptors through /proc")
@pytest.mark.parametrize("fails", ["the status of the new file", "the rename"])
def test_a_write_that_fails_leaks_no_descriptor_and_leaves_no_temporary_file(tmp_path, monkeypatch, fails):
    """26: the write asks the new file's status of its own descriptor (no duplicate of it is made), and whatever fails, every
    descriptor it opened is closed, the temporary file is removed and the original is untouched."""
    (tmp_path / "a.md").write_text("Old.\n", encoding="utf-8")

    def fds():
        return len(os.listdir("/proc/self/fd"))
    before = fds()
    real_fstat = os.fstat
    in_write = []

    def fstat(fd):
        if sys._getframe(1).f_code.co_name == "write":
            in_write.append(fd)
            if len(in_write) == 2:            # the first is the original's mode; the second is the new file's status
                raise OSError(24, "too many open files")
        return real_fstat(fd)

    def rename(*a, **k):
        raise OSError(5, "input/output error")
    monkeypatch.setattr(os, "fstat", fstat) if fails.startswith("the status") else monkeypatch.setattr(os, "rename", rename)
    with pytest.raises(OSError):
        rds.update_beneath(tmp_path, "a.md", lambda t, op: "New.\n")
    monkeypatch.undo()
    assert fails != "the status of the new file" or len(in_write) == 2    # the case reached the new file's status
    assert fds() == before
    assert (tmp_path / "a.md").read_text(encoding="utf-8") == "Old.\n"
    assert not [p.name for p in tmp_path.iterdir() if "sheaf-tmp" in p.name]
