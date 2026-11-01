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


def refused(block_md, html):
    doc = "# Title\n\n" + block_md + "\n"
    out, rep = rde.apply_edits(doc, [{"i": 1, "html": html}])
    return out == doc and rep["skipped"] and rep["skipped"][0][0] == 1


@pytest.mark.parametrize("src,html", [
    ("- a <x1> here\n  - b *c*", "<ul><li><x1></x1><ul><li>b <em>c</em></li></ul></li></ul>"),
    ("A <x1> here.", "<p><x1></x1></p>"),
])
def test_an_edit_that_leaves_a_raw_tag_alone_on_its_line_is_refused(src, html):
    # Alone at the start of a line the tag opens an HTML block, which takes the lines after it as text.
    assert refused(src, html)


@pytest.mark.parametrize("src", [r"A \\<kbd>a</kbd> here.", r"A <kbd>\\</kbd> here.", r"A <kbd>a\\</kbd>b here."])
def test_a_backslash_beside_a_raw_tag_keeps_the_tag(src):
    assert saved(src) == src.replace("here", "there") + "\n"


def test_a_raw_element_inside_code_on_the_page_stays_text():
    # Pandoc writes it as it did before #155; the tag is never put back inside the backticks as text.
    out = saved("A <kbd>x</kbd> here.", html="<p>A <code><kbd>x</kbd></code> there.</p>")
    assert "`<kbd>" not in out and "`x`" in out


# A closing tag with no opener (sheaf #157): the browser drops it, so the page has no element to put back.

@pytest.mark.parametrize("src,html", [
    ("A <x1>b</x2> here.", "<p>A <x1>b there.</x1></p>"),
    ("A </x1> stray close here.", "<p>A  stray close there.</p>"),
    ("Two </x1></x2> strays here.", "<p>Two  strays there.</p>"),
    ("Text </kbd> and <kbd>K</kbd> here.", "<p>Text  and <kbd>K</kbd> there.</p>"),
    ("End of the line here.</x1>", "<p>End of the line there.</p>"),
])
def test_a_closing_tag_with_no_opener_is_kept_where_it_was(src, html):
    assert saved(src, html=html) == src.replace("here", "there") + "\n"


def test_a_closing_tag_with_no_opener_survives_in_a_list_item():
    assert saved("- one </x1> item\n- two here") == "- one </x1> item\n- two there\n"


def test_a_closing_tag_with_no_opener_survives_in_a_table_cell():
    out = saved("| A | B |\n|---|---|\n| a </x1> cell | here |")
    assert "| a </x1> cell" in out and "| there" in out


def test_a_closing_tag_with_no_opener_stays_after_the_words_before_it_when_others_change():
    out = saved("Before </x1> after here.", html="<p>Before  something else there.</p>")
    assert out == "Before </x1> something else there.\n"


# An escaped pipe in a tag's attribute in a table cell (sheaf #157): pandoc's RawInline holds it without the
# backslash, and a bare `|` splits the cell.

@pytest.mark.parametrize("attr", [r'title="a\|b"', r'title="a\|b\|c" lang="x"'])
def test_an_escaped_pipe_in_a_raw_tags_attribute_keeps_its_backslash_in_a_table(attr):
    out = saved(f"| A | B |\n|---|---|\n| <abbr {attr}>X</abbr> | here |")
    assert f"| <abbr {attr}>X</abbr> | there |" in out


def test_a_raw_tag_in_a_table_the_page_wraps_in_its_tblwrap_is_kept():
    # The page sends a table inside its own <div class="tblwrap">, which hid every raw tag of the table.
    src = "| A | B |\n|---|---|\n| <kbd>K</kbd> cell | here |"
    out = saved(src, html='<div class="tblwrap">' + page_fragment(src).replace("here", "there") + "</div>")
    assert "| <kbd>K</kbd> cell |" in out and "| there" in out


def test_a_pipe_in_a_raw_tags_attribute_outside_a_table_is_not_given_a_backslash():
    assert saved('A <abbr title="a|b">X</abbr> here.') == 'A <abbr title="a|b">X</abbr> there.\n'


# Gate 1 on #157.

@pytest.mark.parametrize("src", [
    r'`<abbr title="a\|b">` and <abbr title="a|b">X</abbr> here.',
    r'\<abbr title="a\|b"> and <abbr title="a|b">X</abbr> here.',
])
def test_a_pipe_outside_a_table_is_not_given_the_backslash_of_the_same_tag_written_as_text(src):
    # Pandoc's writer escapes the text's `>` as `\>`, as on main; the tag keeps its bytes.
    assert saved(src).endswith(' and <abbr title="a|b">X</abbr> there.\n')


@pytest.mark.parametrize("src,html", [
    ("Press <kbd>K</kbd></x1> now here.", "<p>Press <kbd>K</kbd> now there.</p>"),
    ("A [a](http://u)</x1> link here.", '<p>A <a href="http://u">a</a> link there.</p>'),
    ("An *a*</x1> here.", "<p>An <em>a</em> there.</p>"),
    # At the start of a paragraph the tag would open an HTML block; a heading has none.
    ("## </x1><kbd>K</kbd> first here", "<h2><kbd>K</kbd> first there</h2>"),
])
def test_a_closing_tag_with_no_opener_stays_outside_the_element_beside_it(src, html):
    assert saved(src, html=html) == src.replace("here", "there") + "\n"


def test_a_closing_tag_with_no_opener_after_math_stays_outside_the_math_span():
    html = '<p>Area <span class="math inline"><em>x</em><sup>2</sup></span> there.</p>'
    out = saved("Area $x^2$</x1> here.", html=html)
    assert out.endswith("</span></x1> there.\n") and "</x1></sup>" not in out


def test_a_closing_tag_with_no_opener_keeps_its_place_in_a_line_the_render_wraps():
    src = "a " * 27 + "x</x1> here."
    assert saved(src) == src.replace("here", "there") + "\n"


def test_placing_a_closing_tag_with_no_opener_compares_only_the_words_the_edit_changed(monkeypatch):
    # A diff of the whole block is quadratic: a paragraph of 47 KB took 54 s.
    import difflib

    sizes, real = [], difflib.SequenceMatcher

    def counted(isjunk=None, a="", b="", autojunk=True):
        sizes.append(max(len(a), len(b)))
        return real(isjunk, a, b, autojunk)

    monkeypatch.setattr(difflib, "SequenceMatcher", counted)
    src = "word " * 8000 + "x</x1> here."
    assert saved(src) == src.replace("here", "there") + "\n"
    assert max(sizes, default=0) < 2100


# Gate 2 on #157: a comment's placeholder is text on the page side only, and two edits far apart leave a
# long stretch between them.

C1 = '<!-- sheaf-comment id=c1 by="Ada" at=2026-10-14T09:00 status=open quote="Start"\nA note.\n-->'
WORDS = "w " * 1200


@pytest.mark.parametrize("comment,anchor", [
    (C1, '<span class="rd-anchor" data-rd-id="c1"></span>'),
    ("<!-- foreign -->", "<!-- foreign -->"),
])
def test_a_comment_far_away_does_not_move_a_closing_tag_with_no_opener(comment, anchor):
    src = "Start" + comment + " " + WORDS + "x</x1> " + WORDS + "here."
    html = "<p>Start" + anchor + " " + WORDS + "x " + WORDS + "there.</p>"
    out = saved(src, html=html)
    assert " w x</x1> w " in out and out.count("</x1>") == 1


def test_two_edits_far_apart_leave_a_closing_tag_with_no_opener_where_it_was():
    src = "First " + WORDS + "x</x1> " + WORDS + "here."
    html = "<p>Once " + WORDS + "x " + WORDS + "there.</p>"
    assert saved(src, html=html) == src.replace("First", "Once").replace("here", "there") + "\n"


# Gate 3 on #157: a tag between words in the source stays between words when the word before it changes.

@pytest.mark.parametrize("src,html,want", [
    ("The red car</x1> is here.", "<p>The red cat is there.</p>", "The red cat</x1> is there.\n"),
    ("Click Save</x1> now here.", "<p>Click Submit now there.</p>", "Click Submit</x1> now there.\n"),
    ("one two</x1> three here.", "<p>one three there.</p>", "one three</x1> there.\n"),
])
def test_a_closing_tag_with_no_opener_is_not_put_inside_a_word(src, html, want):
    assert saved(src, html=html) == want


def test_a_closing_tag_with_no_opener_inside_a_word_in_the_source_stays_there():
    assert saved("A wo</x1>rd here.") == "A wo</x1>rd there.\n"
