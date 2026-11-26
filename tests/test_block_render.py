"""A hand-written callout through the render (block editor v1, ticket 04): the same in reading, share copy and PDF, laid out
by the base stylesheet before any Theme, and shaped by a Theme's properties."""
import re

import pytest

import sheafmd
from sheafmd import render as R

TEXT = ('# T\n\nBefore.\n\n::: {#c1 .callout tone="warning" pad="l"}\nBe careful.\n\n- one\n- two\n:::\n\nAfter.\n\n'
        '::: {#x .foo}\nUnknown.\n:::\n')


def render(tmp_path, text=TEXT, **kw):
    p = tmp_path / "d.md"
    p.write_text(text, encoding="utf-8")
    return sheafmd.render(p, **kw)


def callout_of(out):
    m = re.search(r'<div\b(?=[^>]*\bid="c1")[^>]*>.*?</div>', out, re.S)
    assert m, out[out.index("<main>"):out.index("</main>")]
    return m.group(0)


def test_a_callout_renders_as_a_declared_div_with_its_data_attributes(tmp_path):
    div = callout_of(render(tmp_path))
    assert 'data-tone="warning"' in div and 'data-pad="l"' in div and "<li>one</li>" in div and "Be careful." in div


def test_the_reading_copy_and_the_share_copy_hold_the_same_callout(tmp_path):
    # the reading copy carries the inert block markers the page maps its blocks by; the share copy has none
    reading = re.sub(r"<!--MDB:\d+-->\n?", "", callout_of(render(tmp_path, share=False)))
    assert reading == callout_of(render(tmp_path, share=True))


def test_an_unknown_div_renders_its_content_in_a_plain_div(tmp_path):
    out = render(tmp_path)
    assert "Unknown." in out


def test_a_callout_with_an_undeclared_attribute_comes_out_without_it(tmp_path):
    out = render(tmp_path, '::: {#c1 .callout onclick="alert(1)" style="x:y" tone="neon"}\nA.\n:::\n')
    div = callout_of(out)
    assert "onclick" not in div and "style" not in div and "neon" not in div and "A." in div


def test_the_base_stylesheet_lays_out_the_callout_before_the_theme(tmp_path):
    out = render(tmp_path)
    assert out.index("div.callout{") < out.index("--accent:#1F3864")        # the base block rules, then the plain theme's own
    assert 'div.callout[data-tone="warning"]' in out and "--sheaf-callout-warning-bg" in out


def test_a_theme_written_before_blocks_still_lays_a_callout_out(tmp_path):
    out = render(tmp_path)
    css = re.search(r"<style[^>]*>(.*?)</style>", out, re.S).group(1)
    for var in set(re.findall(r"var\((--sheaf-[\w-]+)", css)):
        assert re.search(re.escape(var) + r"\s*:", css), var                 # every Theme property used has a default


def test_a_theme_property_overrides_the_callout_tone(tmp_path):
    folder = tmp_path / "t"
    folder.mkdir()
    (folder / "theme.toml").write_text('name = "t"\n', encoding="utf-8")
    (folder / "theme.css").write_text(":root{--sheaf-callout-warning-bg:#abcdef;--sheaf-callout-radius:0}\nbody{margin:0}\n",
                                      encoding="utf-8")
    out = render(tmp_path, theme=str(folder))
    css = re.search(r"<style[^>]*>(.*?)</style>", out, re.S).group(1)
    assert css.index("--sheaf-callout-warning-bg:#fff8e6") < css.index("--sheaf-callout-warning-bg:#abcdef")    # the Theme comes after the default
    assert "div.callout{" in css and css.index("div.callout{") < css.index("--sheaf-callout-warning-bg:#abcdef")


def test_an_older_theme_with_none_of_the_block_properties_still_lays_callouts_out(tmp_path):
    folder = tmp_path / "old"
    folder.mkdir()
    (folder / "theme.toml").write_text('name = "old"\n', encoding="utf-8")
    (folder / "theme.css").write_text("body{margin:0}\n", encoding="utf-8")
    css = re.search(r"<style[^>]*>(.*?)</style>", render(tmp_path, theme=str(folder)), re.S).group(1)
    assert "div.callout{" in css and "--sheaf-callout-info-bg:" in css and "--sheaf-pad-m:" in css


def test_the_base_block_css_is_light_only_and_the_plain_theme_carries_its_own_dark_tones():
    from sheafmd.blocks import declarations
    from sheafmd.theme import load_theme
    assert "prefers-color-scheme" not in declarations.css()       # a Theme with a light page must not get dark boxes
    plain = load_theme("plain").css
    assert "--sheaf-callout-info-bg" in plain and "prefers-color-scheme:dark" in plain
