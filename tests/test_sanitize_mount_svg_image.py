"""A local SVG image reaches a mounted page as the base64 `data:image/svg+xml` sheaf embeds. The diagram viewer opens it, so the
mount sanitiser keeps that one form on an <img> and no other SVG data URL: an SVG loaded by an <img> runs no script and loads
nothing, which is why it is safe, and only the form sheaf writes itself is let through."""
import pytest

from test_sanitize_mount import attrs_of, mount

SVG64 = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0naHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmcnLz4="


def test_a_local_svg_image_stays_in_a_mounted_page():
    out = mount(f'<p><img src="{SVG64}" alt="a round thing"></p>')
    assert [a["src"] for a in attrs_of(out, "img")] == [SVG64]


@pytest.mark.parametrize("src", [
    "data:image/svg+xml,<svg onload=alert(1)>",
    "data:image/svg+xml;utf8,<svg onload=alert(1)/>",
    "data:image/svg+xml;base64,PHN2Zz4=<script>",
    "data:image/svg+xml;charset=utf-8;base64,PHN2Zz4=",
    "data:text/html;base64,PHNjcmlwdD4=",
])
def test_any_other_svg_data_address_is_still_dropped(src):
    out = mount(f'<p>keep</p><img src="{src}" alt="x">')
    assert "<img" not in out and "<p>keep</p>" in out


def test_the_svg_data_address_is_for_an_image_only():
    out = mount(f'<p>keep</p><svg><use href="{SVG64}#a"></use></svg><a href="{SVG64}">x</a>')
    assert "data:image/svg" not in out
