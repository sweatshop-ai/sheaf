"""Only the placeholders a save issued for its block count as placeholders (ticket 183 AD, AH).

`_convert_with_comments` swaps each comment and each footnote citation for an `RDCMT` word. Words of that shape the
text already held are words, and a citation is words too: only a comment is not.
"""
import pytest

from sheafmd import edit as rde
from test_edit_backslash import page_fragment

REF = '<a href="#fn1" class="footnote-ref" id="fnref1" role="doc-noteref"><sup>1</sup></a>'
NOTE = "\n\n[^1]: note\n"


def saved(src, html):
    doc = "# Title\n\n" + src + NOTE
    out, rep = rde.apply_edits(doc, [{"i": 1, "html": html}])
    assert rep["skipped"] == []
    assert out.endswith(NOTE)
    return out[len("# Title\n\n"):-len(NOTE)]


def test_a_literal_placeholder_word_after_a_backslash_keeps_one_backslash():
    assert saved("a\\RDCMT0123456789 here", "<p>a\\RDCMT0123456789 there</p>") == "a\\RDCMT0123456789 there"


@pytest.mark.parametrize("html", [f"<p>{REF}- [ ] milk</p>", "<p>RDCMT0123456789- [ ] milk</p>"])
def test_words_before_a_typed_box_keep_it_words(html):
    out = saved("x[^1] here", html)
    assert "<input" not in page_fragment(out + NOTE)
    assert out.index("milk") > out.index("- ")


def test_a_typed_box_before_only_a_citation_is_a_task():
    out = saved("x[^1] here", f"<p>- [ ] {REF}</p>")
    assert out == "- [ ] [^1]"


# The same in a task item: a line typed after Enter (`_lines_as_items`).
@pytest.mark.parametrize("line, want", [
    (f"{REF}- [ ] milk", "- [ ] [^1]- \\[ \\] milk"),
    ("RDCMT0123456789- [ ] milk", "- [ ] RDCMT0123456789- \\[ \\] milk"),
    (f"- [ ] {REF}", "- [ ] [^1]"),
])
def test_a_line_typed_in_a_task_item_counts_only_comments_as_placeholders(line, want):
    src = "- [ ] eggs[^1] here"
    html = page_fragment(src + NOTE).split("</ul>")[0] + "</ul>"
    out = saved(src, html.replace("</li>", f"<div>{line}</div></li>", 1))
    assert out == "- [ ] eggs[^1] here\n" + want
