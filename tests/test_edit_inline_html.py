"""Saving an edited block must keep the raw inline HTML its source holds (sheaf #155).

Pandoc's HTML reader drops an element it does not know (`<x1>`) and writes `<kbd>`, `<mark>` and
`<abbr>` as `<span class=...>`, so the save puts each raw tag of the source back byte for byte.
Fragments are built the way the page builds them: the block rendered by pandoc, one word changed.
"""
import pytest

from helpers import pandoc
from sheafmd import edit as rde


def page_fragment(block_md):
    return pandoc(["-f", "gfm", "-t", "html5", "--no-highlight"], block_md).strip()


def saved(block_md, old="here", new="there", html=None):
    """The block as the save writes it, after `old` became `new` on the page."""
    doc = "# Title\n\n" + block_md + "\n"
    frag = html if html is not None else page_fragment(block_md).replace(old, new)
    out, rep = rde.apply_edits(doc, [{"i": 1, "html": frag}])
    assert rep["skipped"] == []
    return out[len("# Title\n\n"):]


@pytest.mark.parametrize("src", [
    "See (ref <x1>) here.",
    "Two <x1> and <x2/> here.",
    "A <x-y>custom</x-y> element here.",
    "Press <kbd>Ctrl</kbd> here.",
    'A <mark>marked</mark> and <abbr title="Search engine optimisation">SEO</abbr> here.',
    "H<sub>2</sub>O and x<sup>2</sup> and <u>under</u> here.",
    "Upper <KBD>Esc</KBD> and <x1  class='a'> here.",
    "*Emphasis with <x1> inside* here.",
    r"Use <kbd>\_init\_</kbd> and <kbd>\_</kbd>x<kbd>\_</kbd> here.",
    r"Stars <kbd>\*a\*</kbd>, <x1>\[b\]</x1> and <kbd>\`c\`</kbd> here.",
])
def test_an_edit_keeps_each_raw_inline_tag_byte_for_byte(src):
    assert saved(src) == src.replace("here", "there") + "\n"


@pytest.mark.parametrize("src", [
    "- one <x1> item\n- two here\n",
    "## A <kbd>K</kbd> heading here\n",
    "> quoted <x1> line here\n",
])
def test_raw_inline_tags_survive_in_every_editable_block(src):
    assert saved(src.rstrip("\n")) == src.replace("here", "there")


def test_a_raw_inline_tag_survives_in_a_table_cell():
    # Pandoc pads the table's columns again; the cell keeps its tag.
    out = saved("| A | B |\n|---|---|\n| <x1> cell | here |")
    assert "| <x1> cell | there |" in out


def test_the_words_inside_a_raw_element_can_be_edited():
    assert saved("Press <kbd>Ctrl</kbd> now.", "Ctrl", "Alt") == "Press <kbd>Alt</kbd> now.\n"


def test_a_raw_element_deleted_on_the_page_is_gone_from_the_file():
    html = "<p>Press now.</p>"
    assert saved("Press <kbd>Ctrl</kbd> now.", html=html) == "Press now.\n"


def test_of_two_raw_elements_the_one_deleted_on_the_page_is_the_one_that_goes():
    src = 'Then <abbr title="one">A</abbr> and <abbr title="two">B</abbr> here.'
    html = '<p>Then A and <abbr title="two">B</abbr> there.</p>'
    assert saved(src, html=html) == 'Then A and <abbr title="two">B</abbr> there.\n'


def test_an_unchanged_block_with_raw_inline_html_is_not_rewritten():
    doc = "# Title\n\nSee (ref <x1>) and <kbd>K</kbd> here.\n"
    out, rep = rde.apply_edits(doc, [{"i": 1, "html": page_fragment("See (ref <x1>) and <kbd>K</kbd> here.")}])
    assert out == doc and rep["changed"] == []


# The other inline constructs a save could lose the same way: each keeps its meaning.

def test_an_html_comment_in_an_edited_paragraph_is_kept_byte_for_byte():
    assert saved("Text <!-- note --> here.") == "Text <!-- note --> there.\n"


def test_autolinks_in_an_edited_paragraph_still_link_to_the_same_address():
    out = saved("Go <https://example.com/a?b=1> or <a@b.com> here.")
    assert out == "Go https://example.com/a?b=1 or <a@b.com> there.\n"
    assert page_fragment(out) == page_fragment("Go <https://example.com/a?b=1> or <a@b.com> there.")


def test_entities_in_an_edited_paragraph_still_show_the_same_characters():
    src = "A &copy; B&nbsp;C &lt;b&gt; &amp; &#8364; &#x2014; here."
    out = saved(src)
    assert page_fragment(out) == page_fragment(src.replace("here", "there"))


def test_a_sup_the_math_render_wrote_is_not_taken_for_the_sources_raw_sup():
    # The page shows $x^2$ as a math span that holds a <sup>; the source's own <sup> is never closed.
    html = '<p>Area <span class="math inline"><em>x</em><sup>2</sup></span> and x<sup>3 there.</sup></p>'
    out = saved("Area $x^2$ and x<sup>3 here.", html=html)
    assert out.endswith(" and x<sup>3 there.\n") and "<sup>2</sup>" in out


@pytest.mark.parametrize("src", ["- the <li> tag here", "| A |\n|---|\n| the <td> tag here |"])
def test_a_raw_tag_named_like_a_block_element_does_not_take_the_blocks_own_element(src):
    # The page's own <li> or <td> is not the source's tag: the save does what it did before #155.
    out = saved(src)
    assert out.count("\n- ") == 0 and "there" in out
