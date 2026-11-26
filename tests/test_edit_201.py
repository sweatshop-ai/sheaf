"""Ticket 201: the Codex re-check of #656 (ticket 188's fix). One test (or one parametrized test) per box."""
import pytest

from sheafmd import edit as rde


# ── A: a run of the source's hard breaks is the source's even when both lines beside it changed ──
# `_split_at_double_breaks` told a run of the source by its length and one line beside it unchanged; with both
# lines edited in one save the run looked new and the paragraph was split, and a new run nearby with one line in
# common took the old run's match.

@pytest.mark.parametrize("src, page, md", [
    ("Alpha\\\n\\\nBeta\n", "<p>Alpha too<br>\n<br>\nBeta too</p>", "Alpha too\\\n\\\nBeta too"),
    ("Alpha  \n\\\nBeta\n", "<p>Alpha too<br>\n<br>\nBeta too</p>", "Alpha too\\\n\\\nBeta too"),
    # two new runs before the source's, the first with the source's first line on its left: the source's run is
    # the one with both its lines, and the two new ones split
    ("Alpha\\\n\\\nBeta\n", "<p>Alpha<span><br></span><span><br></span>New<span><br></span><span><br></span>"
                            "Alpha<br>\n<br>\nBeta</p>", "Alpha\n\nNew\n\nAlpha\\\n\\\nBeta"),
    # a new run after the source's, both lines of the source's edited: the new one splits (the review of 201)
    ("Alpha\\\n\\\nBeta\n", "<p>Alpha too<br>\n<br>\nBeta too<span><br></span><span><br></span>New</p>",
     "Alpha too\\\n\\\nBeta too\n\nNew"),
    # a word is a word without the punctuation beside it (the second review of 201)
    ("Alpha\\\n\\\nBeta\n", "<p>Alpha.<br>\n<br>\nBeta!</p>", "Alpha.\\\n\\\nBeta!"),
], ids=["both lines edited", "two spaces, both lines edited", "a new run takes no match from the old one",
        "a new run after the source's", "punctuation edited"])
def test_the_source_run_of_hard_breaks_is_kept_whatever_the_lines_beside_it_say(src, page, md):
    got = rde.html_block_to_md(page, source=src, strays=[])
    assert got == md, got


@pytest.mark.parametrize("page, md", [
    ("<p>Gamma<span><br></span><span><br></span>Delta</p>", "Gamma\n\nDelta"),
    ("<p>One<span><br></span><span><br></span>Two</p>", "One\n\nTwo"),
], ids=["other words", "a pasted paragraph"])
def test_a_new_run_with_none_of_the_source_runs_words_beside_it_still_splits(page, md):
    # the source's run is gone: a new run of its length with other lines beside it is no run of the source's
    got = rde.html_block_to_md(page, source="Alpha\\\n\\\nBeta\n", strays=[])
    assert got == md, got


def test_two_runs_that_each_keep_a_word_are_both_the_sources_over_one_that_keeps_more():
    # Codex round 4: the pairing kept the most words, so one run close to the source's second run took it and left
    # the source's two runs with one pair; it keeps the most pairs first now
    src = "Alpha one two\\\n\\\nBeta three four\\\n\\\nGamma five six\n"
    page = "<p>Beta three four alpha<br>\n<br>\nGamma five six<br>\n<br>\nGamma end</p>"
    got = rde.html_block_to_md(page, source=src, strays=[])
    assert got == "Beta three four alpha\\\n\\\nGamma five six\\\n\\\nGamma end", got


# ── B: an empty element that is a link target is no remnant ──
# `remnant` took every empty inline element but an image or a box for what an emptied half leaves, and the
# promotion of the split-off half deleted it: an `<a id>` (a link target) was lost. Pandoc writes an empty target
# as `<span id>`, as it does for one in an unsplit heading.

@pytest.mark.parametrize("html, md", [
    ('<h2><a id="x"></a><div data-rd-split="">cd</div></h2>', '## <span id="x"></span>cd'),
    ('<h2><em><a name="x"></a></em><div data-rd-split="">cd</div></h2>', '## <span id="x"></span>cd'),
    ('<h2><em></em><span id="x"></span> <div data-rd-split="">\xa0cd</div></h2>', '## <span id="x"></span>cd'),
    ('<h2><a id="x"></a><em><a id="y"></a></em><div data-rd-split="">cd</div></h2>',
     '## <span id="x"></span><span id="y"></span>cd'),
], ids=["a with an id", "a name inside an emptied mark", "a span with an id beside an empty mark", "two, in order"])
def test_an_empty_link_target_left_in_an_emptied_first_half_stays_in_the_heading(html, md):
    got = rde.html_block_to_md(html)
    assert got == md, got
