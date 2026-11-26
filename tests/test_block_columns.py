"""Columns, box and image layout divs end to end (block editor v1, ticket 05): declarations, reading, refusal, Stubs,
the sanitised render and the generated look. The wire sample of the spec round-trips byte for byte."""
import re

import pytest

import sheafmd
from sheafmd.blocks import ALL, LOCKED, read_tree, write_back
from sheafmd.blocks import declarations as dec

WIRE = '''Intro.

::: {#c7 .callout}
A plain paragraph inside a callout.
:::

:::: {#k2 .columns}
::: {#k2a .column size="33"}
![Alt](https://example.org/a.png)
:::
::: {#k2b .column size="67"}
Text, then a button: [[Book a call](https://example.org)]{.button size="m" variant="primary"}
:::
::::

::: {#b4 .box align="center" pad="m"}
A centred, padded paragraph.
:::
'''


def test_the_wire_sample_round_trips_byte_for_byte():
    tree = read_tree(WIRE)
    assert [b.type for b in tree.blocks] == ["paragraph", "callout", "columns", "box"]
    assert write_back(tree, tree) == WIRE


def test_columns_are_read_with_their_columns_sizes_and_children():
    k = read_tree(WIRE).get("k2")
    assert k.caps == ALL and [c.type for c in k.children] == ["column", "column"]
    assert [c.attrs for c in k.children] == [{"size": "33"}, {"size": "67"}]
    assert [c.id for c in k.children] == ["k2a", "k2b"]
    assert [g.type for g in k.children[0].children] == ["paragraph"]


def test_a_box_and_an_image_div_are_declared_types_with_their_attributes():
    tree = read_tree('::: {#i1 .image size="50" align="center"}\n![Alt](https://example.org/a.png)\n:::\n\n'
                     '::: {#b1 .box pad="l"}\nText.\n:::\n')
    i, b = tree.blocks
    assert (i.type, i.attrs) == ("image", {"size": "50", "align": "center"})
    assert (b.type, b.attrs) == ("box", {"pad": "l"})


def test_a_layout_div_inside_a_callout_or_a_column_is_read_as_its_type():
    tree = read_tree('::: {#c1 .callout}\n::: {#b1 .box align="right"}\nText.\n:::\n:::\n')
    assert tree.blocks[0].type == "callout"
    assert [(k.type, k.attrs) for k in tree.blocks[0].children] == [("box", {"align": "right"})]


@pytest.mark.parametrize("src,type_,why", [
    # a size off the declared steps
    ('::: {#k .columns}\n::: {#a .column size="33.5"}\nx\n:::\n:::\n', "columns", "size"),
    ('::: {#k .columns}\n::: {#a .column size="10"}\nx\n:::\n:::\n', "columns", "size"),
    ('::: {#k .columns}\n::: {#a .column size="90"}\nx\n:::\n:::\n', "columns", "size"),
    ('::: {#i .image size="30"}\n![A](u.png)\n:::\n', "image", "size"),
    ('::: {#i .image size="100%"}\n![A](u.png)\n:::\n', "image", "size"),
    ('::: {#b .box width="50"}\nx\n:::\n', "box", "width"),
    ('::: {#b .box pad="xl"}\nx\n:::\n', "box", "pad"),
    # nesting the Container rules forbid
    ('::: {#k .columns}\n::: {#a .column}\n::: {#c .callout}\nx\n:::\n:::\n:::\n', "columns", "callout may not sit inside a column"),
    ('::: {#c .callout}\n::: {#k .columns}\n::: {#a .column}\nx\n:::\n:::\n:::\n', "callout", "columns may not sit inside a callout"),
    ('::: {#k .columns}\n::: {#k2 .columns}\n::: {#a .column}\nx\n:::\n:::\n:::\n', "columns", "columns may not sit inside"),
    ('::: {#k .columns}\nLoose text.\n:::\n', "columns", "paragraph may not sit inside a columns"),
    ('::: {#a .column}\nx\n:::\n', "column", "column"),
    ('::: {#b .box}\n::: {#b2 .box}\nx\n:::\n:::\n', "box", "box may not sit inside a box"),
    ('::: {#k .columns}\n::: {#a .column}\n::: {#b .box}\n::: {#b2 .box}\nx\n:::\n:::\n:::\n:::\n', "columns", "box may not sit inside a box"),
    ('::: {#k .columns}\n::: {#a .column .extra}\nx\n:::\n:::\n', "columns", "extra"),
])
def test_an_invalid_layout_div_written_by_hand_is_a_locked_stub_with_a_reason_and_its_bytes(src, type_, why):
    tree = read_tree("Before.\n\n" + src + "\nAfter.\n")
    stub = tree.blocks[1]
    assert stub.type == "stub" and stub.caps == LOCKED
    assert stub.attrs["type"] == type_ and why in stub.attrs["reason"]
    assert stub.content == src.rstrip("\n") + "\n" or stub.content == src
    assert write_back(tree, tree) == tree.text


def test_a_column_may_hold_the_plain_blocks_and_one_level_of_layout_divs():
    src = ('::: {#k .columns}\n::: {#a .column size="50"}\n## H\n\n- one\n\n::: {#b .box pad="s"}\nText.\n:::\n\n'
           '::: {#i .image size="75"}\n![A](u.png)\n:::\n:::\n::: {#z .column size="50"}\nB.\n:::\n:::\n')
    tree = read_tree(src)
    assert tree.blocks[0].type == "columns"
    assert [g.type for g in tree.blocks[0].children[0].children] == ["heading", "list", "box", "image"]


def test_the_declarations_name_the_steps():
    column = {a.name: a for a in dec.DECLARED["column"].attrs}["size"]
    assert column.values == tuple(str(n) for n in sorted({*range(15, 86, 5), 33, 67}))   # 5 % steps and the thirds of the presets
    image = {a.name: a for a in dec.DECLARED["image"].attrs}
    assert image["size"].values == ("25", "50", "75", "100") and image["align"].values == ("left", "center", "right")
    box = {a.name: a for a in dec.DECLARED["box"].attrs}
    assert box["align"].values == ("left", "center", "right") and box["pad"].values == ("none", "s", "m", "l")
    assert dec.DECLARED["columns"].children == ("column",)
    assert "callout" not in dec.DECLARED["column"].children and "columns" not in dec.DECLARED["column"].children
    assert dec.check_children("callout", ["box", "image"]) is None
    assert "box may not sit inside a box" in dec.check_children("box", ["box"])
    assert "column may not stand alone" in dec.top_fault("column")
    assert dec.top_fault("columns") is None


# ── render and look ──────────────────────────────────────────────────────────

def render(tmp_path, text, **kw):
    p = tmp_path / "d.md"
    p.write_text(text, encoding="utf-8")
    return sheafmd.render(p, **kw)


def test_the_wire_sample_renders_columns_with_their_size_in_the_reading_and_the_share_copy(tmp_path):
    for share in (False, True):
        out = render(tmp_path, WIRE, share=share)
        assert re.search(r'<div\b[^>]*\bclass="columns"', out)
        assert len(re.findall(r'<div\b[^>]*\bclass="column"[^>]*\bsize="(?:33|67)"', out)) == 2
        assert re.search(r'<div\b[^>]*\bclass="box"[^>]*data-align="center"[^>]*data-pad="m"', out)


def test_a_column_loses_what_is_not_declared_in_the_render(tmp_path):
    out = render(tmp_path, '::: {#k .columns}\n::: {#a .column size="33" onclick="x()" style="color:red"}\nA.\n:::\n:::\n')
    div = re.search(r'<div\b[^>]*\bclass="column"[^>]*>', out).group(0)
    assert "onclick" not in div and "style" not in div and 'size="33"' in div


def base_css(out):
    return re.search(r"<style[^>]*>(.*?)</style>", out, re.S).group(1)


def test_the_css_has_a_rule_per_step_generated_from_the_declarations():
    css = dec.css()
    for n in sorted({*range(15, 86, 5), 33, 67}):
        assert f'div.column[size="{n}"]{{' in css
    for v in ("25", "50", "75", "100"):
        assert f'div.image[size="{v}"]{{' in css
    for v in ("left", "center", "right"):
        assert f'div.image[data-align="{v}"]{{' in css and f'div.box[data-align="{v}"]{{' in css
    for v in ("none", "s", "m", "l"):
        assert f'div.box[data-pad="{v}"]{{' in css
    # no step rule is written by hand: every `[size=` / `[data-…=` selector comes from a declared value
    for typ, attr, val in re.findall(r'div\.(\w+)\[(?:data-)?(\w+)="([^"]+)"\]', css):
        a = {x.name: x for x in dec.DECLARED[typ].attrs}[attr]
        assert val in a.values


def test_columns_stack_on_screens_under_600px_and_stay_side_by_side_in_print():
    css = dec.css()
    stack = re.search(r"@media\s+screen\s+and\s+\(max-width:\s*599(?:\.98)?px\)\{(.*?)\}\s*(?:\n|$)", css, re.S)
    assert stack and "flex-direction:column" in stack.group(1)
    assert "div.columns{display:flex" in css
    assert "@media print" not in css or "flex-direction:column" not in css.split("@media print")[1]


def test_an_image_keeps_its_share_of_its_column_at_every_width():
    css = dec.css()
    assert "div.image img{" in css and "width:100%" in css.split("div.image img{")[1].split("}")[0]
    assert 'div.image[size="50"]{width:50%}' in css


# ── the Document service: refusal on write ───────────────────────────────────

SAVED = 'Intro.\n\n::: {#k .columns}\n::: {#a .column size="40"}\nLeft.\n:::\n::: {#b .column size="60"}\nRight.\n:::\n:::\n'


@pytest.fixture
def doc(tmp_path):
    from sheafmd import adapter as rda
    from sheafmd.document import DocumentService
    path = tmp_path / "doc.md"
    path.write_text(SAVED, encoding="utf-8")
    return path, DocumentService(rda.MarkdownFileAdapter(path))


def _save(svc, markdown):
    _, base = svc.adapter.read()
    return svc.save(markdown, None, base, "page-1")


def test_a_save_that_edits_a_column_is_written_and_keeps_every_stored_id(doc):
    path, svc = doc
    text = SAVED.replace("Left.", "Left, edited.")
    out = _save(svc, text)
    assert out["outcome"] == "written" and path.read_text(encoding="utf-8") == text
    assert {"k", "a", "b"} <= {b.id for b in svc.read()[0].walk()}


@pytest.mark.parametrize("old,new,why", [
    ('size="40"', 'size="42"', "size"),
    ('size="40"', 'size="5"', "size"),
    ('{#k .columns}', '{#k .columns pad="m"}', "pad"),
    ("Left.", "::: {#c .callout}\nInner.\n:::", "callout may not sit inside a column"),
])
def test_a_save_off_the_declarations_is_refused_whole_and_the_file_is_unchanged(doc, old, new, why):
    path, svc = doc
    out = _save(svc, SAVED.replace(old, new).replace("Intro.", "Changed intro."))
    assert out["outcome"] == "refused" and out["block"] == "k" and why in out["reason"]
    assert path.read_text(encoding="utf-8") == SAVED


def test_an_image_size_off_its_steps_is_refused_on_write(doc):
    path, svc = doc
    out = _save(svc, SAVED + '\n::: {#i .image size="60"}\n![A](u.png)\n:::\n')
    assert out["outcome"] == "refused" and out["block"] == "i" and "size" in out["reason"]
    assert path.read_text(encoding="utf-8") == SAVED


def test_a_callout_holding_columns_is_refused_on_write(doc):
    path, svc = doc
    out = _save(svc, SAVED + "\n::: {#c .callout}\n" + SAVED.split("\n\n", 1)[1].replace(":::\n:::\n", ":::\n:::\n") + ":::\n")
    assert out["outcome"] == "refused" and "columns may not sit inside a callout" in out["reason"]


def test_a_size_written_by_hand_off_its_steps_is_shown_locked_and_survives_a_neighbour_edit(tmp_path):
    from sheafmd import adapter as rda
    from sheafmd.document import DocumentService
    hand = SAVED.replace('size="40"', 'size="41"')
    path = tmp_path / "d.md"
    path.write_text(hand, encoding="utf-8")
    svc = DocumentService(rda.MarkdownFileAdapter(path))
    tree, _ = svc.read()
    assert tree.blocks[1].type == "stub" and tree.blocks[1].caps == LOCKED and "size" in tree.blocks[1].attrs["reason"]
    out = _save(svc, hand.replace("Intro.", "Intro two."))
    assert out["outcome"] == "written" and path.read_text(encoding="utf-8") == hand.replace("Intro.", "Intro two.")


def test_no_tile_inside_columns_is_offered_for_editing_in_the_page(tmp_path):
    import json
    out = render(tmp_path, "Before.\n\n" + SAVED.split("\n\n", 1)[1] + "\nAfter.\n", share=False)
    meta = json.loads(re.search(r'<script id="rd-edit-meta" type="application/json">(.*?)</script>', out, re.S).group(1))
    assert meta["editable"][0] == 0 and len(meta["editable"]) == 2       # "Before." and "After.", no tile of the columns


@pytest.mark.parametrize("body", ["Just words.", "![A](u.png) and words", "![A](u.png)\n\n![B](v.png)"])
def test_an_image_div_that_is_not_one_image_on_a_line_of_its_own_is_a_locked_stub(body):
    stub = read_tree(f'::: {{#i .image size="50"}}\n{body}\n:::\n').blocks[0]
    assert stub.type == "stub" and "one image" in stub.attrs["reason"]


def test_a_column_outside_columns_names_its_holder():
    assert dec.top_fault("column") == "a column may not stand alone: it belongs inside a columns"
