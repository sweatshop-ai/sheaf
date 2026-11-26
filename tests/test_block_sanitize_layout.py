"""The layout divs through both sanitiser layers (block editor v1, ticket 05): `column` carries a bare `size` (pandoc writes
no `data-` prefix for it), `box` and `image` the data attributes; everything else is removed. Same CASES in
tests/page/test_mount_layout_blocks.py for `page/mount.js`."""
import pytest

from test_block_sanitize import first_div
from sheafmd.sanitize import sanitize

# (input, id, class, the attributes left besides id and class)
CASES = [
    ('<div id="a" class="column" size="33">x</div>', "a", "column", {"size": "33"}),
    ('<div class="column" size="33%" onclick="y()">x</div>', None, "column", {}),
    ('<div class="column" size="12">x</div>', None, "column", {}),
    ('<div class="column" size="85" style="position:fixed" data-size="85">x</div>', None, "column", {"size": "85"}),
    ('<div class="columns" size="33" data-pad="m">x</div>', None, "columns", {}),
    ('<div id="b" class="box" data-align="center" data-pad="l">x</div>', "b", "box", {"data-align": "center", "data-pad": "l"}),
    ('<div class="box" data-align="justify" data-pad="xl">x</div>', None, "box", {}),
    ('<div class="image" size="50" data-align="right">x</div>', None, "image", {"size": "50", "data-align": "right"}),
    ('<div class="image" size="60">x</div>', None, "image", {}),
]


@pytest.mark.parametrize("html,ident,cls,attrs", CASES, ids=[f"{i:02d}" for i in range(len(CASES))])
def test_a_layout_div_keeps_its_declared_attributes_and_nothing_else(html, ident, cls, attrs):
    for mount in (False, True):
        got = first_div(sanitize(html, mount=mount))
        assert got.pop("class") == cls
        assert got.pop("id", None) == ident
        assert got == attrs
