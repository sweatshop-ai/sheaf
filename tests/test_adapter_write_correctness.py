"""The Markdown-file adapter's writes are correct (block editor v1, ticket 26): a path is found once, the base it returns
is the one its own next read computes, a source policy refusal is an outcome, and a save that waits for the file lock
looks nothing up again."""
import threading

import pytest
from helpers import PLAN
from two_roots import two_roots

from sheafmd import adapter as rda
from sheafmd import source as rds
from sheafmd.blocks import split_md_blocks

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


def test_a_save_whose_root_is_forgotten_while_it_waits_for_the_file_lock_still_lands(tmp_path):
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
    with rds.file_lock(f):
        t = threading.Thread(target=save, daemon=True)
        t.start()
        t.join(0.5)
        assert t.is_alive(), "the save should wait for the file lock"
        gone, finish = hub.let_go_root(root.name)
        assert gone is not None
    t.join(10)
    assert not t.is_alive()
    assert isinstance(done[0], dict), done
    assert done[0]["changed"]
    assert "Edited words." in f.read_text(encoding="utf-8")
    finish()
