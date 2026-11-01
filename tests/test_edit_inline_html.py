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


# Gate 4 on #157: Enter puts a new item or line right after the old one, with no space between their words.

@pytest.mark.parametrize("src,html,want", [
    ("- one</x1>\n- two here", "<ul>\n<li>one</li><li>new</li>\n<li>two there</li>\n</ul>",
     "- one</x1>\n- new\n- two there\n"),
    ("1. Do it</x1>\n2. two here", "<ol>\n<li>Do it</li><li>More</li>\n<li>two there</li>\n</ol>",
     "1.  Do it</x1>\n2.  More\n3.  two there\n"),
])
def test_a_closing_tag_with_no_opener_stays_in_its_item_when_enter_adds_one_after_it(src, html, want):
    assert saved(src, html=html) == want


def test_a_closing_tag_with_no_opener_stays_on_its_line_when_enter_adds_one_after_it():
    out = saved("A b</x1> here.", html="<p>A b there.<div>new</div></p>")
    assert out.startswith("A b</x1> there.") and "new</x1>" not in out


@pytest.mark.parametrize("src,html,want", [
    ("Go bar</x1> more here.", "<p>Go qux more there.</p>", "Go qux</x1> more there.\n"),
    ("a b</x1>. here", "<p>a c. there</p>", "a c</x1>. there\n"),
])
def test_a_closing_tag_with_no_opener_follows_a_word_replaced_by_one_with_no_letter_in_common(src, html, want):
    assert saved(src, html=html) == want


# Gate 5 on #157: Enter after a word moves the space after it to the new line, as a no-break space.

@pytest.mark.parametrize("src,html,want", [
    ("Line one ends here </x1>\nline two.", "<p>Line one ends here<div>&nbsp;line two.</div></p>",
     "Line one ends here</x1>\n\nline two.\n"),
    ("Word </x1> end.", "<p>Word<div>x end.</div></p>", "Word</x1>\n\nx end.\n"),
    ("A b </x1>c d here.", "<p>A b&nbsp;<div>c d here.</div></p>", "A b</x1>\n\nc d here.\n"),
    ("A </x1> stray close here.", "<p>A&nbsp;<div>stray close here.</div></p>", "A</x1>\n\nstray close here.\n"),
])
def test_a_closing_tag_with_no_opener_stays_with_the_word_before_it_when_enter_splits_the_line(src, html, want):
    assert saved(src, html=html) == want


def test_a_closing_tag_with_no_opener_stays_in_its_item_when_enter_splits_it():
    out = saved("- Item one </x1> more\n- two", html="<ul><li>Item one</li><li>&nbsp;more</li><li>two</li></ul>")
    assert out.startswith("- Item one</x1>\n") and out.count("</x1>") == 1


def test_a_closing_tag_with_no_opener_after_an_element_and_a_space_keeps_the_space_before_it():
    assert saved("A <kbd>K</kbd> </x1>b here.") == "A <kbd>K</kbd> </x1>b there.\n"


# Sheaf #161: the cases #157 left.

@pytest.mark.parametrize("src,want", [
    ("- one\n- </x1>three here", "- one</x1>three there\n"),
    ("- one </x1>\n- three here", "- one</x1>three there\n"),
])
def test_a_closing_tag_with_no_opener_stays_between_two_items_merged_with_no_space(src, want):
    assert saved(src, html="<ul><li>onethree there</li></ul>") == want


@pytest.mark.parametrize("src,html", [
    ("- Item one " + C1 + " </x1> more here\n- two",
     '<ul><li>Item one<span class="rd-anchor" data-rd-id="c1"></span></li>'
     "<li>&nbsp;&nbsp;more there</li><li>two</li></ul>"),
    ("- Item one </x1> " + C1 + " more here\n- two",
     '<ul><li>Item one</li><li>&nbsp;&nbsp;<span class="rd-anchor" data-rd-id="c1"></span> more there</li>'
     "<li>two</li></ul>"),
])
def test_a_closing_tag_with_no_opener_stays_in_its_item_when_enter_splits_it_beside_a_comment(src, html):
    out = saved(src, html=html)
    assert out.startswith("- Item one</x1>") and out.count("</x1>") == 1 and C1 in out


def test_a_closing_tag_inside_an_emphasis_still_closes_the_element_opened_before_it():
    out = saved("Go <x1>a *b* c</x1> here.")
    assert out == "Go <x1>a *b* c</x1> there.\n"


@pytest.mark.parametrize("src,want", [
    ("| a | b |\n|---|---|\n| `x\\|y` | here |", "`x\\|y`"),
    ("| a | b |\n|---|---|\n| `x\\|y\\|z` <kbd>k</kbd> | here |", "`x\\|y\\|z`"),
    ("| `x\\|y` | b |\n|---|---|\n| a | here |", "`x\\|y`"),
])
def test_a_code_span_in_a_table_cell_keeps_its_escaped_pipe(src, want):
    out = saved(src)
    assert want in out and "there" in out
    assert "<td><code>" + want[1:-1].replace("\\|", "|") + "</code>" in page_fragment(out) \
        or "<th><code>" + want[1:-1].replace("\\|", "|") + "</code>" in page_fragment(out)


def test_a_pipe_in_code_outside_a_table_gets_no_backslash():
    assert saved("Run `a|b` here.") == "Run `a|b` there.\n"


def test_a_pipe_in_code_in_a_table_pandoc_writes_as_raw_html_gets_no_backslash():
    html = "<table><tr><td><code>x|y</code></td><td>a<br>b\\c</td></tr></table>"
    assert "\\|" not in rde.html_block_to_md(html)


# Gate 1 on #161.

@pytest.mark.parametrize("src", [
    "Press <kbd><kbd>Ctrl</kbd>+<kbd>C</kbd></kbd> here.",
    "Go <mark>a <mark>b</mark> c</mark> here.",
    "Go <x1>a <x1>b <x1>c</x1> d</x1> e</x1> here.",
])
def test_nested_raw_elements_of_one_name_each_keep_their_closing_tag(src):
    assert saved(src) == src.replace("here", "there") + "\n"


def test_a_closing_tag_first_in_a_table_cell_stays_there():
    out = saved("| a | b |\n|---|---|\n| k | </x1>c here |")
    assert "| </x1>" in out and "there" in out and out.count("</x1>") == 1


@pytest.mark.parametrize("src,want", [
    ("> | a | b |\n> |---|---|\n> | `x\\|y` | here |", "`x\\|y`"),
    ("- | a | `b\\|c` |\n  |---|---|\n  | k | here |", "`b\\|c`"),
])
def test_a_code_span_in_a_table_in_a_quote_or_an_item_keeps_its_escaped_pipe(src, want):
    assert want in saved(src)


def test_a_line_of_a_raw_html_table_that_starts_with_a_pipe_gets_no_backslash_in_code():
    html = "<table><tr><td>a<br>\n| <code>x|y</code></td><td>b\\c</td></tr></table>"
    assert "<code>x|y</code>" in rde.html_block_to_md(html)


@pytest.mark.parametrize("src,old,new,want", [
    ("Go un</x1> e due.", "un", "une", "Go une</x1> e due.\n"),
    ("Go be</x1> a test.", "be", "bean", "Go bean</x1> a test.\n"),
    ("Go foo</x1> bar here.", "foo", "foobar", "Go foobar</x1> bar here.\n"),
])
def test_a_closing_tag_with_no_opener_stays_out_of_a_word_that_grew_by_the_next_words_letters(src, old, new, want):
    assert saved(src, old=old, new=new) == want


def test_a_comment_in_a_cells_code_does_not_become_its_words():
    out = rde.html_block_to_md("<table><tr><th>a</th></tr><tr><td><code><!-- MDB:a|b -->x|y</code></td></tr></table>")
    assert "MDB" not in out and "x\\|y" in out


# Gate 2 on #161.

@pytest.mark.parametrize("src", [
    "| a | b |\n|---|---|\n| here | </x1></x2> |",
    "| a | b |\n|---|---|\n| here | k |\n| l | </x1></x2> |",
    "> | a | b |\n> |---|---|\n> | here | </x1></x2> |",
    "| a | b |\n|---|---|\n| here | </x1> |",
    "| a | b |\n|---|---|\n| here | k |\n| l | </x1> |",
])
def test_a_closing_tag_with_no_words_after_it_in_a_tables_last_cell_keeps_the_table(src):
    out = saved(src)
    assert "|---" in out.replace("-|-", "---") and "</x1>" in out and "there" in out


@pytest.mark.parametrize("src", ["> here\n>\n> - </x1></x2>", "- here\n  - </x1></x2>"])
def test_a_closing_tag_alone_in_the_last_item_adds_no_item_save_after_save(src):
    once = saved(src)
    assert once.count("</x1>") == 1
    assert saved(once.rstrip("\n"), old="there", new="there") == once


@pytest.mark.parametrize("src,want", [
    ("> a\n>\n> </x1></x2>**c** here", "> </x1></x2>**c** there\n"),
    ("- </x1></x2>*c* here", "- </x1></x2>*c* there\n"),
    ("- a\n- </x1></x2>*c* here", "- </x1></x2>*c* there\n"),
])
def test_two_closing_tags_first_in_a_block_stay_together_before_its_element(src, want):
    assert saved(src).endswith(want)


def test_a_pipe_after_a_table_nested_in_a_raw_html_table_gets_no_backslash():
    src = "- <table><tr><td><table><tr><td>k</td></tr></table><code>m|n</code> here</td></tr></table>"
    html = "<ul><li>" + src[2:].replace("here", "there") + "</li></ul>"
    out = rde.html_block_to_md(html)
    assert "<code>m|n</code>" in out and "\\|" not in out


# Gate 3 on #161. A tag closed past its item, cell or emphasis pairs with its opener, as on main; these pin
# that it renders as the page showed it (the source's own place for it is split out of #161).

@pytest.mark.parametrize("src,html,want", [
    ("*a <mark>b* c</mark> here.", "<p>a <mark>b</mark> c there.</p>", "a <mark>b</mark> c there.\n"),
    ("[a <mark>b](u) c</mark> here.", "<p>a <mark>b</mark> c there.</p>", "a <mark>b</mark> c there.\n"),
    ("- a <mark>b\n- c</mark> d here", "<ul><li>a <mark>b</mark>c d there</li></ul>", "- a <mark>b</mark>c d there\n"),
    ("*a <mark>b* c</mark> here.", "<p><em>a <mark>b</mark> z</em> c there.</p>", "*a <mark>b</mark> z* c there.\n"),
    ("- a <mark>b\n- c</mark> d here", "<ul><li>a <mark>b</mark> z</li><li>c d there</li></ul>",
     "- a <mark>b</mark> z\n- c d there\n"),
    ("> a <mark>b\n>\n> c</mark> here", "<blockquote><p>a <mark>b</mark> z</p><p>c there</p></blockquote>",
     "> a <mark>b</mark> z\n>\n> c there\n"),
])
def test_a_tag_closed_past_its_container_is_closed_where_the_page_element_ends_once_words_follow_it(src, html, want):
    assert saved(src, html=html) == want


@pytest.mark.parametrize("src,html,want", [
    ("**a <mark>b** c</mark> d here.", "<p><strong>a b</strong> c d there.</p>", "**a b** c d there.\n"),
    ("- a <mark>b\n- c</mark> d here", "<ul><li>a b</li><li>c d there</li></ul>", "- a b\n- c d there\n"),
])
def test_a_tag_closed_past_its_container_and_deleted_on_the_page_takes_its_closing_tag_with_it(src, html, want):
    assert saved(src, html=html) == want


@pytest.mark.parametrize("src,html,want", [
    ("> Note <mark>this\n>\n> and</mark> that here.", "<blockquote>\n<p>Note <mark>this</mark></p>\n\n</blockquote>",
     "> Note <mark>this</mark>\n"),
    ("> Note <mark>this\n>\n> and</mark> that here.",
     "<blockquote>\n<p>Note <mark>this</mark></p>\n<p>that here.</p>\n</blockquote>",
     "> Note <mark>this</mark>\n>\n> that here.\n"),
    ("- one <mark>two\n\n- three</mark> four here", "<ul>\n<li><p>one <mark>two</mark></p></li>\n\n</ul>",
     "- one <mark>two</mark>\n"),
    ("- a <x1>b\n- c</x1> d here", "<ul>\n<li>a <x1>b</x1></li>\n<li>d here</li>\n</ul>", "- a <x1>b</x1>\n- d here\n"),
    ("| a | b |\n|---|---|\n| <x1>k | c</x1> d here |",
     "<table>\n<thead>\n<tr>\n<th>a</th>\n<th>b</th>\n</tr>\n</thead>\n<tbody>\n<tr>\n<td><x1>k</x1></td>\n"
     "<td>d here</td>\n</tr>\n</tbody>\n</table>", "<x1>k</x1>"),
])
def test_a_tag_closed_past_its_container_whose_words_after_it_went_closes_at_the_elements_end(src, html, want):
    out = saved(src, html=html)
    assert out == want if want.endswith("\n") else want in out and "</x1> d here |" not in out


@pytest.mark.parametrize("src,html,want", [
    ("*a <mark>b* c</mark> here.", "<p><em>a <mark>b</mark></em><i>z</i> c there.</p>", "<mark>b</mark>"),
    ("**a <x1>b** c</x1> here.", "<p><strong>a <x1>b</x1></strong><b>z</b> c there.</p>", "<x1>b</x1>"),
    ("- a <x1>b\n- c</x1> d here", "<ul><li>a <x1>b</x1>&nbsp;</li><li>c d there</li></ul>", "<x1>b</x1>\xa0"),
])
def test_a_tag_closed_past_its_container_closes_at_its_end_before_a_merged_emphasis_or_a_no_break_space(
        src, html, want):
    out = saved(src, html=html)
    assert want in out and out.count(want.split(">")[0].replace("<", "</") + ">") == 1
