"""Shortcode follow-ups of a page edit (ticket 137): a raw-HTML table, a shortcode typed as text, a failed look."""
import pytest

from sheafmd import edit as rde
from test_edit_emoji import page_fragment, saved


@pytest.fixture(autouse=True)
def _fresh_emoji_cache():
    """A test that makes a look-up fail leaves no name of it cached for the next, even when it fails itself."""
    rde._emoji_drawn.cache_clear()
    yield
    rde._emoji_drawn.cache_clear()


def test_a_shortcode_in_a_table_pandoc_writes_as_raw_html_keeps_its_emoji():
    src = "| :+1: | here |\n|---|---|\n| a | b |"
    doc = "# Title\n\n" + src + "\n"
    html = page_fragment(src).replace("here", "<ul><li>x</li><li>y</li></ul>")
    out, rep = rde.apply_edits(doc, [{"i": 1, "html": html}])
    assert rep["skipped"] == []
    assert "<table" in out and "<th>👍</th>" in out and ":+1:" not in out


def test_a_shortcode_typed_as_text_stays_text():
    out = saved("a \\:smile: here")
    assert out == "a \\:smile: there\n"
    assert "emoji" not in page_fragment(out)


def test_a_shortcode_that_is_no_emoji_is_not_escaped():
    assert saved("a :nonesuch: here") == "a :nonesuch: there\n"


def test_a_failed_look_at_an_emoji_is_not_kept(monkeypatch):
    real = rde._pandoc.run
    calls = []

    def once_failing(*a, **k):
        calls.append(1)
        r = real(*a, **k)
        if len(calls) == 1:
            r.returncode = 1
        return r

    monkeypatch.setattr(rde._pandoc, "run", once_failing)
    with pytest.raises(rde.EditError):
        rde._emoji_drawn("tada")
    assert rde._emoji_drawn("tada") == "\U0001F389"


def test_a_backslash_shortcode_typed_on_the_page_reads_back_as_typed():
    # The page shows what the reader typed: `\:smile:` is a backslash and the name, never the emoji.
    out = saved("a b here", old="b", new="\\:smile:")
    assert out == "a \\\\\\:smile: here\n"
    assert "emoji" not in page_fragment(out) and "\\:smile:" in page_fragment(out)


def test_two_backslashes_typed_before_a_shortcode_read_back_as_typed():
    out = saved("a b here", old="b", new="\\\\:smile:")
    assert "emoji" not in page_fragment(out) and "\\\\:smile:" in page_fragment(out)


def test_a_backslash_shortcode_typed_in_a_raw_html_table_reads_back_as_typed():
    src = "| a | here |\n|---|---|\n| c | d |"
    doc = "# Title\n\n" + src + "\n"
    html = page_fragment(src).replace("here", "<ul><li>x</li><li>y</li></ul>").replace(">a<", ">\\:smile:<")
    out, rep = rde.apply_edits(doc, [{"i": 1, "html": html}])
    assert rep["skipped"] == [] and "<table" in out
    assert "<th>\\:smile:</th>" in out


def test_a_literal_shortcode_is_kept_by_place_not_by_name():
    # The source writes one `:smile:` as text; the reader types another, meaning the emoji.
    out = saved("a \\:smile: b here", old="b", new=":smile:")
    assert out == "a \\:smile: :smile: here\n"


def test_a_literal_shortcode_typed_before_the_one_the_source_has_is_the_emoji():
    out = saved("x a \\:smile: here", old="x", new=":smile: x")
    assert out == ":smile: x a \\:smile: here\n"


def test_two_literal_shortcodes_of_the_source_both_stay_text():
    assert saved("\\:smile: and \\:smile: here") == "\\:smile: and \\:smile: there\n"


@pytest.mark.parametrize("src", [
    "a \\<table x \\:smile: here",
    "a `<table` x \\:smile: here",
    "a \\<table x a\\\\\\\\ b here",
    "- x\n\n      <table>\n\n  \\:smile: here",
])
def test_a_table_tag_that_is_text_does_not_count_as_a_table(src):
    # The tokens come back by whether they are in a table pandoc writes as raw HTML; a `<table` that is
    # text or code is none.
    assert saved(src) == src.replace("here", "there") + "\n"


def _emoji_look_fails(monkeypatch):
    """Pandoc fails on the look-up of a shortcode, and only there."""
    real = rde._pandoc.run

    def failing(args, text, *a, **k):
        r = real(args, text, *a, **k)
        if args == ["-f", "gfm", "-t", "html5"] and rde.SHORTCODE_RE.fullmatch(text):
            r.returncode = 1
        return r

    monkeypatch.setattr(rde._pandoc, "run", failing)


@pytest.mark.parametrize("src", [
    "a \\:smile: here",                         # the source's literal: written bare it would draw its emoji
    "Nice :+1: here",                           # a drawn emoji: written as the character it would lose its name
])
def test_a_failed_emoji_look_refuses_the_save_and_writes_no_guess(monkeypatch, src):
    page = page_fragment(src).replace("here", "there")
    _emoji_look_fails(monkeypatch)
    doc = "# Title\n\n" + src + "\n"
    out, rep = rde.apply_edits(doc, [{"i": 1, "html": page}])
    assert out == doc and [i for i, _ in rep["skipped"]] == [1]


def test_a_backslash_shortcode_typed_on_the_page_is_refused_when_the_look_fails(monkeypatch):
    page = page_fragment("a b here").replace("b", "\\:smile:")
    _emoji_look_fails(monkeypatch)
    out, rep = rde.apply_edits("# Title\n\na b here\n", [{"i": 1, "html": page}])
    assert out == "# Title\n\na b here\n" and [i for i, _ in rep["skipped"]] == [1]
