"""Block tree correctness (block editor v1, ticket 25): ids that never collide, locked blocks locked at every depth,
unknown divs as Stubs inside a quote, and a repeated attribute read the way pandoc renders it (the first)."""
import pytest

from sheafmd.blocks import ALL, LOCKED, read_tree
from sheafmd.blocks import declarations as dec

LOCKED_TYPES = {"code", "html", "stub", "frontmatter"}

NESTED = '''---
title: t
---

```
top fence
```

> ```
> fence in a quote
> ```
>
> <div>raw html in a quote</div>
>
>     indented code in a quote
>
> ::: {.mystery}
> unknown div in a quote
> :::

- ```
  fence in a list
  ```

  <div>raw html in a list</div>

      indented code in a list

:::: {#cols .columns}
::: {#c1 .column size="50"}
```
fence in a column
```

<div>raw html in a column</div>

    indented code in a column
:::
::: {#c2 .column size="50"}
text
:::
::::
'''


def test_a_locked_block_is_never_editable_at_any_depth():
    tree = read_tree(NESTED)
    blocks = list(tree.walk())
    kinds = {b.type for b in blocks}
    assert {"code", "html", "stub"} <= kinds, kinds
    assert "div" not in kinds
    for b in blocks:
        want = LOCKED if b.type in LOCKED_TYPES else ALL
        assert b.caps == want, (b.id, b.type, sorted(b.caps))
    inside = [b for b in blocks if b.type in ("code", "html") and b not in tree.blocks]
    assert len(inside) >= 6


def test_an_unknown_div_in_a_quote_is_a_locked_stub_with_its_type_and_raw_source():
    tree = read_tree("> ::: {.mystery}\n> inside\n> :::\n")
    stub = tree.blocks[0].children[0]
    assert stub.type == "stub" and stub.caps == LOCKED and stub.attrs["type"] == "mystery"
    assert "inside" in stub.content and stub.content.lstrip().startswith(":::") and ".mystery" in stub.content


def _collide(stored_first):
    """A paragraph's generated id, written into the file as the stored id of a column."""
    para = read_tree("Hello.\n").blocks[0].id
    cols = f':::: {{#{para} .columns}}\n::: {{#k1 .column size="50"}}\nx\n:::\n::: {{#k2 .column size="50"}}\ny\n:::\n::::\n'
    return para, ("Hello.\n\n" + cols) if not stored_first else (cols + "\nHello.\n")


@pytest.mark.parametrize("stored_first", [True, False])
def test_a_stored_id_and_a_generated_id_never_collide(stored_first):
    _, text = _collide(stored_first)
    tree = read_tree(text)
    ids = [b.id for b in tree.walk()]
    assert len(ids) == len(set(ids)), ids
    cols = next(b for b in tree.blocks if b.type == "columns")
    assert tree.get(cols.id).type == "columns"
    para = next(b for b in tree.blocks if b.type == "paragraph")
    assert tree.get(para.id).type == "paragraph"


def _cols(first_col_attrs):
    return (f':::: {{#k .columns}}\n::: {{#a .column {first_col_attrs}}}\ntext\n:::\n'
            '::: {#b .column size="60"}\nx\n:::\n::::\n')


def test_a_repeated_attribute_is_read_as_pandoc_renders_it_the_first():
    col = read_tree(_cols('size="40" size="60"')).get("a")
    assert col.type == "column" and col.attrs["size"] == "40"


def test_a_repeated_attribute_is_validated_on_its_first_value():
    # the reviewer's case: 42 is no declared size, and pandoc renders the first value, so the block is a Stub
    stub = read_tree(_cols('size="42" size="60"')).blocks[0]
    assert stub.type == "stub" and "42" in stub.attrs["reason"]
    # the other way round: the first value is declared, the last is not, and the first is what is rendered
    assert read_tree(_cols('size="40" size="999"')).get("a").attrs["size"] == "40"


def test_a_repeated_callout_attribute_reads_its_first_value():
    tone = next(a for a in dec.DECLARED["callout"].attrs if a.name == "tone")
    first, last = tone.values[0], tone.values[-1]
    callout = read_tree(f'::: {{#c .callout tone="{first}" tone="{last}"}}\nhi\n:::\n').blocks[0]
    assert callout.type == "callout" and callout.attrs["tone"] == first


def test_a_repeated_image_attribute_is_validated_on_its_first_value():
    ok = read_tree('::: {#i .image size="50" size="60"}\n![a](https://example.org/a.png)\n:::\n').blocks[0]
    assert ok.type == "image" and ok.attrs["size"] == "50"
    bad = read_tree('::: {#i .image size="60" size="50"}\n![a](https://example.org/a.png)\n:::\n').blocks[0]
    assert bad.type == "stub" and "60" in bad.attrs["reason"]


def test_a_callout_never_shares_its_stored_id_with_a_plain_block():
    para = read_tree("Hello.\n").blocks[0].id
    tree = read_tree(f"Hello.\n\n::: {{#{para} .callout}}\nhi\n:::\n")
    ids = [b.id for b in tree.walk()]
    assert len(ids) == len(set(ids)), ids
    assert tree.get(tree.blocks[1].id).type == "callout"
