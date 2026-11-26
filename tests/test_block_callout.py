"""A callout, read and written end to end through the block tree and the Document service (block editor v1,
ticket 04): stored ids, declared attributes, Stubs for what is invalid or unknown, and the refusals of a save."""
import pytest

from sheafmd import adapter as rda
from sheafmd.blocks import ALL, LOCKED, read_tree, write_back
from sheafmd.document import DocumentService

CALLOUT = '::: {#c1 .callout tone="warning"}\nBe careful.\n\n- one\n- two\n:::\n'


# ── reading ──────────────────────────────────────────────────────────────────

def test_a_callout_is_read_with_its_stored_id_declared_attributes_and_children():
    tree = read_tree("Intro.\n\n" + CALLOUT + "\nOutro.\n")
    assert [b.type for b in tree.blocks] == ["paragraph", "callout", "paragraph"]
    c = tree.blocks[1]
    assert c.id == "c1" and c.attrs == {"tone": "warning"} and c.caps == ALL
    assert c.content == CALLOUT.rstrip("\n") + "\n" or c.content == CALLOUT
    assert [k.type for k in c.children] == ["paragraph", "list"]
    assert tree.get("c1") is c


def test_a_callout_with_no_stored_id_gets_a_derived_one_and_other_blocks_keep_theirs():
    tree = read_tree("::: {.callout}\nA.\n:::\n\n::: {.callout}\nA.\n:::\n")
    a, b = tree.blocks
    assert a.type == b.type == "callout" and a.id != b.id


def test_an_edit_inside_a_callout_changes_its_ast_but_not_its_stored_id():
    one = read_tree('::: {#c1 .callout}\nA.\n:::\n').blocks[0]
    two = read_tree('::: {#c1 .callout}\nB.\n:::\n').blocks[0]
    assert one.id == two.id == "c1" and one.key != two.key


@pytest.mark.parametrize("src,why", [
    ('::: {#c1 .callout onclick="x"}\nA.\n:::\n', "onclick"),
    ('::: {#c1 .callout style="color:red"}\nA.\n:::\n', "style"),
    ('::: {#c1 .callout tone="purple"}\nA.\n:::\n', "purple"),
    ('::: {#c1 .callout .extra}\nA.\n:::\n', "extra"),
    ('::: {#c1 .callout}\n::: {#c2 .callout}\nA.\n:::\n:::\n', "callout may not sit inside"),
    ('> ::: {#c1 .callout}\n> A.\n> :::\n', "quote"),
    ('- ::: {#c1 .callout}\n  A.\n  :::\n', "list"),
])
def test_an_invalid_callout_written_by_hand_is_a_locked_stub_with_a_reason_and_its_bytes(src, why):
    tree = read_tree("Before.\n\n" + src + "\nAfter.\n")
    stub = tree.blocks[1]
    assert stub.type == "stub" and stub.caps == LOCKED
    assert stub.attrs["type"] == "callout" and why in stub.attrs["reason"]
    assert stub.content.startswith(src.split("\n")[0])
    assert write_back(tree, tree) == tree.text


def test_an_unknown_type_is_a_stub_with_its_raw_bytes_and_stays_byte_for_byte():
    src = '::: {#x .foo bar="1"}\nInside.\n\nMore.\n:::\n'
    tree = read_tree(src + "\nAfter.\n")
    stub = tree.blocks[0]
    assert stub.type == "stub" and stub.attrs["type"] == "foo" and stub.caps == LOCKED
    assert stub.content == src and stub.id == "x"
    assert write_back(tree, tree) == tree.text


def test_a_stub_is_equal_to_itself_by_its_bytes():
    a = read_tree("::: {.foo}\nA.\n:::\n").blocks[0]
    b = read_tree("::: {.foo}\nA.\n:::\n").blocks[0]
    c = read_tree("::: {.foo}\nB.\n:::\n").blocks[0]
    assert a.key == b.key != c.key


# ── old documents never raise ────────────────────────────────────────────────

OLD = {
    "raw html": "<div class=\"x\" onclick=\"y\">hi</div>\n\n<script>1</script>\n\nText.\n",
    "chart fence": "```chart\n{\"type\": \"bar\", \"data\": [1, 2]}\n```\n\nText.\n",
    "comment span": "A <span data-sheaf-comment='x'>word</span> and <!-- sheaf-comment id=1 -->.\n",
    "crlf": "# T\r\n\r\n::: {.callout}\r\nA.\r\n\r\nB.\r\n:::\r\n\r\nEnd\r\n",
    "non utf-8": "Caf\udce9 and � bytes.\n\n::: {.callout}\nA \udcff b.\n:::\n",
    "unclosed div": "::: {.callout}\nA.\n\nB.\n",
    "stray closer": "Text.\n\n:::\n\nMore.\n",
}


@pytest.mark.parametrize("name", sorted(OLD))
def test_an_old_document_opens_and_writes_back_byte_for_byte(name):
    text = OLD[name]
    tree = read_tree(text)
    assert tree.blocks
    assert write_back(tree, tree) == text


def test_raw_html_and_chart_fences_are_locked_blocks():
    t = read_tree(OLD["raw html"]).blocks[0]
    assert t.caps == LOCKED
    f = read_tree(OLD["chart fence"]).blocks[0]
    assert f.caps == LOCKED


# ── the Document service ─────────────────────────────────────────────────────

@pytest.fixture
def doc(tmp_path):
    path = tmp_path / "doc.md"
    path.write_text("Intro.\n\n" + CALLOUT + "\n::: {#s1 .foo}\nraw\n:::\n", encoding="utf-8")
    return path, DocumentService(rda.MarkdownFileAdapter(path))


def _save(svc, markdown, held=None):
    _, base = svc.adapter.read()
    return svc.save(markdown, held, base, "page-1")


def test_a_callout_is_read_through_the_service(doc):
    path, svc = doc
    tree, _ = svc.read()
    assert [b.type for b in tree.blocks] == ["paragraph", "callout", "stub"]


def test_a_save_that_edits_inside_a_callout_is_written_and_keeps_the_id(doc):
    path, svc = doc
    text = path.read_text(encoding="utf-8").replace("Be careful.", "Be very careful.")
    out = _save(svc, text)
    assert out["outcome"] == "written" and "c1" in out["blocks"]
    assert path.read_text(encoding="utf-8") == text


@pytest.mark.parametrize("old,new,why", [
    ('{#c1 .callout tone="warning"}', '{#c1 .callout tone="warning" onclick="x"}', "onclick"),
    ('{#c1 .callout tone="warning"}', '{#c1 .callout tone="neon"}', "neon"),
    ('{#c1 .callout tone="warning"}', '{#c1 .callout tone="warning" style="color:red"}', "style"),
])
def test_an_undeclared_attribute_or_value_is_refused_whole_and_the_file_is_unchanged(doc, old, new, why):
    path, svc = doc
    before = path.read_text(encoding="utf-8")
    out = _save(svc, before.replace(old, new).replace("Intro.", "Changed intro."))
    assert out["outcome"] == "refused" and out["block"] == "c1" and why in out["reason"]
    assert path.read_text(encoding="utf-8") == before        # not even the intro was written


def test_a_forbidden_nesting_is_refused_with_the_block_and_the_reason(doc):
    path, svc = doc
    before = path.read_text(encoding="utf-8")
    nested = before.replace("Be careful.", "::: {#c9 .callout}\nInner.\n:::")
    out = _save(svc, nested)
    assert out["outcome"] == "refused" and out["block"] in ("c1", "c9") and "callout" in out["reason"]
    assert path.read_text(encoding="utf-8") == before


def test_a_new_callout_in_a_quote_is_refused(doc):
    path, svc = doc
    before = path.read_text(encoding="utf-8")
    out = _save(svc, before + "\n> ::: {#c7 .callout}\n> Hi.\n> :::\n")
    assert out["outcome"] == "refused" and "quote" in out["reason"]
    assert path.read_text(encoding="utf-8") == before


def test_an_invalid_block_already_in_the_file_does_not_refuse_a_save_that_leaves_it_alone(tmp_path):
    path = tmp_path / "d.md"
    path.write_text('Intro.\n\n::: {#c1 .callout onclick="x"}\nA.\n:::\n', encoding="utf-8")
    svc = DocumentService(rda.MarkdownFileAdapter(path))
    out = _save(svc, path.read_text(encoding="utf-8").replace("Intro.", "Intro two."))
    assert out["outcome"] == "written"
    assert 'onclick="x"' in path.read_text(encoding="utf-8")


def test_a_stub_is_written_back_byte_for_byte_when_the_page_moves_it(doc):
    path, svc = doc
    before = path.read_text(encoding="utf-8")
    tree, _ = svc.read()
    stub = tree.get("s1")
    moved = "::: {#s1 .foo}\nraw\n:::\n\nIntro.\n\n" + CALLOUT
    out = _save(svc, moved, held=[stub.id, tree.blocks[0].id, "c1"])
    assert out["outcome"] == "written"
    assert path.read_text(encoding="utf-8").startswith("::: {#s1 .foo}\nraw\n:::\n")
    assert before != path.read_text(encoding="utf-8")


def test_an_edit_to_a_stub_the_page_held_is_refused_whole(doc):
    path, svc = doc
    before = path.read_text(encoding="utf-8")
    tree, _ = svc.read()
    held = [b.id for b in tree.blocks]
    out = _save(svc, before.replace("raw", "rewritten").replace("Intro.", "Changed."), held=held)
    assert out["outcome"] == "refused" and out["block"] == "s1"
    assert path.read_text(encoding="utf-8") == before


def test_an_edit_to_locked_raw_html_the_page_held_is_refused_whole(tmp_path):
    path = tmp_path / "d.md"
    path.write_text("Intro.\n\n<div>raw</div>\n\nEnd.\n", encoding="utf-8")
    svc = DocumentService(rda.MarkdownFileAdapter(path))
    tree, _ = svc.read()
    out = _save(svc, "Intro.\n\n<div>changed</div>\n\nEnd.\n", held=[b.id for b in tree.blocks])
    assert out["outcome"] == "refused" and out["block"] == tree.blocks[1].id
    assert "raw" in path.read_text(encoding="utf-8")


def test_bytes_that_are_not_utf8_read_as_a_tree_and_write_back_byte_for_byte():
    raw = b"Intro.\n\nCaf\xe9 bytes.\n\n::: {.callout}\nA \xff b.\n:::\n"
    text = raw.decode("utf-8", "surrogateescape")          # what a reader that keeps the bytes hands over
    tree = read_tree(text)
    assert [b.type for b in tree.blocks] == ["paragraph", "paragraph", "callout"]
    assert write_back(tree, tree).encode("utf-8", "surrogateescape") == raw


def test_a_refusal_in_the_hub_save_is_an_edit_error_not_a_crash(tmp_path, monkeypatch):
    import sheafmd.edit as rde
    import sheafmd.hub.live as rdl
    import sheafmd.source as rds
    md = tmp_path / "d.md"
    md.write_text("Intro.\n\nOther.\n", encoding="utf-8")
    doc = rdl.LiveDocument(md, render=lambda *_: None, publish=lambda *_: None, by="Ada")

    def refuse(*a, **k):
        raise rda.Refused("the callout has an attribute it does not declare: onclick", "c1")
    monkeypatch.setattr(doc._service, "settle", refuse)
    with pytest.raises(rde.EditError, match="onclick"):
        doc.save(rds.md_hash("Intro.\n\nOther.\n"), [{"i": 1, "html": "<p>Changed.</p>"}])
    assert md.read_text(encoding="utf-8") == "Intro.\n\nOther.\n"
