"""The Markdown-file adapter: the one door every write to a rectoverso goes through (block editor v1, ticket 01)."""
import pytest

from sheafmd import adapter as rda
from sheafmd import source as rds

DOC = "Para one.\n\nPara two.\n"


def make(tmp_path, name="d.md", text=DOC):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_the_adapter_declares_an_integer_interface_version(tmp_path):
    a = rda.MarkdownFileAdapter(make(tmp_path))
    assert isinstance(a.interface, int) and not isinstance(a.interface, bool)
    assert a.interface == rda.INTERFACE_VERSION


def test_read_gives_the_tree_and_the_content_hash_as_base(tmp_path):
    tree, base = rda.MarkdownFileAdapter(make(tmp_path)).read()
    assert tree.text == DOC
    assert base == rds.md_hash(DOC)


def test_a_write_against_the_current_base_is_written(tmp_path):
    p = make(tmp_path)
    a = rda.MarkdownFileAdapter(p)
    tree, base = a.read()
    out = a.write(rda.Tree("Changed.\n"), base, author="Ada", note="n")
    assert out["outcome"] == "written"
    assert out["base"] == rds.md_hash("Changed.\n")
    assert p.read_text(encoding="utf-8") == "Changed.\n"
    assert a.read()[1] == out["base"]


def test_a_stale_base_is_a_conflict_not_an_exception_and_writes_nothing(tmp_path):
    p = make(tmp_path)
    a = rda.MarkdownFileAdapter(p)
    _, old_base = a.read()
    p.write_text("Someone else.\n", encoding="utf-8")
    out = a.write(rda.Tree("Mine.\n"), old_base, author="Ada", note="")
    assert out["outcome"] == "conflict"
    assert out["base"] == rds.md_hash("Someone else.\n")
    assert out["blocks"] == []
    assert p.read_text(encoding="utf-8") == "Someone else.\n"


def test_a_name_that_is_not_markdown_is_refused_and_nothing_is_written(tmp_path):
    p = make(tmp_path, "d.txt")
    a = rda.MarkdownFileAdapter(p)
    out = a.write(rda.Tree("x\n"), rds.md_hash(DOC), author="Ada", note="")
    assert out["outcome"] == "refused"
    assert out["reason"]
    assert p.read_text(encoding="utf-8") == DOC


def test_accepts_is_the_one_place_the_md_suffix_is_judged():
    assert rda.MarkdownFileAdapter.accepts("a/b.md")
    assert not rda.MarkdownFileAdapter.accepts("a/b.txt")
    assert not rda.MarkdownFileAdapter.accepts("b.md.bak")


def test_apply_runs_a_change_under_the_lock_and_gives_old_and_new(tmp_path):
    p = make(tmp_path)
    a = rda.MarkdownFileAdapter(p)
    out, old, new = a.apply(lambda t, opened: t + "More.\n")
    assert (old, new) == (DOC, DOC + "More.\n")
    assert out["outcome"] == "written" and out["base"] == rds.md_hash(new)
    assert p.read_text(encoding="utf-8") == new


def test_apply_with_an_unchanged_text_writes_nothing(tmp_path):
    a = rda.MarkdownFileAdapter(make(tmp_path))
    out, old, new = a.apply(lambda t, opened: t)
    assert old == new and out["outcome"] == "written" and out["base"] == rds.md_hash(DOC)


def test_apply_with_a_stale_expected_base_is_a_conflict(tmp_path):
    p = make(tmp_path)
    a = rda.MarkdownFileAdapter(p)
    out, old, new = a.apply(lambda t, opened: "X\n", expected="0" * 16)
    assert out["outcome"] == "conflict" and out["base"] == rds.md_hash(DOC)
    assert p.read_text(encoding="utf-8") == DOC


def test_an_error_the_change_raises_reaches_the_caller_as_it_did(tmp_path):
    a = rda.MarkdownFileAdapter(make(tmp_path))

    def change(t, opened):
        raise rds.StaleError("moved on", code="select-again")
    with pytest.raises(rds.StaleError) as e:
        a.apply(change)
    assert e.value.code == "select-again"


def test_the_file_may_be_opened_beneath_a_root(tmp_path):
    make(tmp_path)
    a = rda.MarkdownFileAdapter(beneath=lambda: (tmp_path, "d.md"))
    assert a.read()[0].text == DOC
    out, old, new = a.apply(lambda t, opened: "B.\n")
    assert out["outcome"] == "written" and (tmp_path / "d.md").read_text(encoding="utf-8") == "B.\n"


def test_create_writes_a_new_page_and_refuses_a_name_that_is_not_markdown(tmp_path):
    a = rda.MarkdownFileAdapter
    got = a.creating(tmp_path, "n.md", "New.\n")()
    assert (tmp_path / "n.md").read_text(encoding="utf-8") == "New.\n" and len(got) == 2
    with pytest.raises(rda.Refused):
        a.creating(tmp_path, "n.txt", "x\n")
    with pytest.raises(FileExistsError):
        a.creating(tmp_path, "n.md", "again\n")()
