"""A declared Rich block through both sanitiser layers (block editor v1, ticket 04): `sanitize.py` here, `page/mount.js`
in tests/page/test_mount_blocks.py, from the same CASES. Both let through exactly the declared `data-<attr>` with an allowed
value on `div.<type>`, its id and its type as the only class; no style, free class, title or handler."""
import re

import pytest

from sheafmd.blocks import declarations
from sheafmd.sanitize import sanitize

PWN = "window.__pwned=1"
# (input, expected: id or None, class, the data attributes left)
CASES = [
    ('<div id="c1" class="callout" data-tone="warning">x</div>', "c1", "callout", {"data-tone": "warning"}),
    ('<div class="callout" data-tone="warning" data-pad="l" data-align="center">x</div>', None, "callout",
     {"data-tone": "warning", "data-pad": "l", "data-align": "center"}),
    ('<div class="callout" data-tone="neon" data-pad="xl">x</div>', None, "callout", {}),
    ('<div class="callout" data-evil="1" data-rd-x="1" data-tone="info">x</div>', None, "callout", {"data-tone": "info"}),
    (f'<div class="callout" onclick="{PWN}" onmouseover="{PWN}" data-tone="danger">x</div>', None, "callout", {"data-tone": "danger"}),
    ('<div class="callout" style="position:fixed;top:0;background:red" data-tone="info">x</div>', None, "callout", {"data-tone": "info"}),
    ('<div class="callout extra other" title="t" lang="fr" data-tone="success">x</div>', None, "callout", {"data-tone": "success"}),
    ('<div class="extra callout" data-tone="warning">x</div>', None, "callout", {"data-tone": "warning"}),
    ('<div class="callout" DATA-TONE="info">x</div>', None, "callout", {"data-tone": "info"}),
]


def first_div(out: str):
    m = re.search(r"<div\b([^>]*)>", out)
    assert m, out
    return dict(re.findall(r'([\w:-]+)="([^"]*)"', m.group(1)))


def test_the_allow_list_both_layers_read_is_the_declarations():
    assert declarations.allow_list()["callout"]["attrs"]["data-tone"] == ["info", "success", "warning", "danger"]


@pytest.mark.parametrize("mount", [False, True], ids=["page", "mounted"])
@pytest.mark.parametrize("html,ident,cls,data", CASES, ids=[f"{i:02d}" for i in range(len(CASES))])
def test_a_declared_block_keeps_its_declared_data_attributes_and_nothing_else(html, ident, cls, data, mount):
    got = first_div(sanitize(html, mount=mount))
    assert got.pop("class") == cls
    assert got.pop("id", None) == ident
    assert got == data
    assert "x" in sanitize(html, mount=mount)


def test_an_undeclared_div_is_not_a_block_and_keeps_the_rules_it_had():
    out = sanitize('<div class="plain" data-x="1" onclick="y()">x</div>')
    assert 'data-x="1"' in out and "onclick" not in out


def test_the_declared_class_on_another_element_is_no_block():
    out = sanitize('<p class="callout" data-tone="neon">x</p>')
    assert 'data-tone="neon"' in out         # unchanged from before blocks: only a div of a declared type is a block


def test_the_block_survives_a_second_pass_unchanged():
    once = sanitize('<div id="c1" class="callout extra" data-tone="warning" style="x:y">a<script>1</script></div>')
    assert sanitize(once) == once
