"""A page edit keeps a shortcode as the reader typed it (ticket 137).

GFM's emoji extension draws `:+1:` as `<span class="emoji" data-emoji="+1">👍</span>`; the save wrote the
emoji itself into the .md, so the next render drew a plain character where the source had a name.
"""
import pytest

from helpers import pandoc
from sheafmd import edit as rde


def page_fragment(block_md):
    return pandoc(["-f", "gfm", "-t", "html5", "--no-highlight"], block_md).strip()


def saved(block_md, old="here", new="there"):
    doc = "# Title\n\n" + block_md + "\n"
    out, rep = rde.apply_edits(doc, [{"i": 1, "html": page_fragment(block_md).replace(old, new)}])
    assert rep["skipped"] == []
    return out[len("# Title\n\n"):]


@pytest.mark.parametrize("src", [
    "Nice :+1: here",
    ":100: here",
    "a :heavy_check_mark: and :-1: here",
    "- :smile: here",
    "## :tada: here",
])
def test_an_edit_writes_a_shortcode_back_as_the_shortcode(src):
    assert saved(src) == src.replace("here", "there") + "\n"


def test_an_edit_in_a_table_cell_next_to_a_shortcode_keeps_it():
    out = saved("| a | b |\n|---|---|\n| :+1: | here |")
    assert ":+1:" in out and "👍" not in out and "there" in out


def test_enter_in_a_table_cell_with_a_shortcode_keeps_a_pipe_table():
    src = "| :+1: | here |\n|---|---|\n| a | b |"
    doc = "# Title\n\n" + src + "\n"
    html = page_fragment(src).replace("here", "th<br>ere")
    out, rep = rde.apply_edits(doc, [{"i": 1, "html": html}])
    assert rep["skipped"] == []
    assert "<table" not in out and ":+1:" in out and "th<br>ere" in out


def test_a_span_the_reader_typed_with_data_emoji_keeps_its_words():
    src = 'x <span data-emoji="smile">hello world</span> here'
    assert "hello world" in saved(src)


@pytest.mark.parametrize("junk", ["\ufc000\ufc01", "\uf8fe0\uf8ff", "\uf8fe9\uf8ff"])
def test_text_that_looks_like_a_token_is_not_taken_for_one(junk):
    assert junk in saved(f"{junk} :smile: here")


def test_words_typed_inside_an_emoji_span_are_kept():
    src = "Nice :+1: here"
    doc = "# Title\n\n" + src + "\n"
    html = page_fragment(src).replace("\U0001F44D", "\U0001F44D typed words")
    out, rep = rde.apply_edits(doc, [{"i": 1, "html": html}])
    assert rep["skipped"] == [] and "typed words" in out


@pytest.mark.parametrize("typed", ["\u00e9", "\U0001F600", "\u0301"])
def test_non_ascii_text_typed_inside_an_emoji_span_is_kept(typed):
    src = "Nice :+1: here"
    html = page_fragment(src).replace("\U0001F44D", "\U0001F44D" + typed)
    out, rep = rde.apply_edits("# Title\n\n" + src + "\n", [{"i": 1, "html": html}])
    assert rep["skipped"] == [] and typed in out


def test_a_keycap_shortcode_is_written_back_as_the_shortcode():
    assert saved("Step :one: here") == "Step :one: there\n"
