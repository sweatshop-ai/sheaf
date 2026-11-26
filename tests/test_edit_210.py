"""Ticket 210: the Codex re-check of #685 (ticket 201's fix) and of #691 (ticket 207's fix). One test per box."""
from test_edit_191 import saved_as

from sheafmd import edit as rde


# ── A: an unchanged line beside a run outranks two lines that each kept some of their words ──
# `_source_runs_kept` scored a pair by the sum of what the two lines beside it kept, so a new run with both lines
# close to the source's took the pair from the source's own run, whose line before it had not changed: the source's
# run was split and the new run kept as hard breaks, the reverse of the edit.

def test_the_run_with_an_unchanged_line_beside_it_is_the_sources_over_one_with_two_lines_close_to_it():
    src = "Alpha one two three\\\n\\\nBeta four five six\n"
    page = ("<p>Alpha one two three<br>\n<br>\nAlpha one two<span><br></span><span><br></span>"
            "Beta four five</p>")
    got = rde.html_block_to_md(page, source=src, strays=[])
    assert got == "Alpha one two three\\\n\\\nAlpha one two\n\nBeta four five", got


# ── B: a literal the cut word diff leaves unmatched is still placed by its neighbours ──
# Past the bound `_word_pairs` cuts the text at words found once on each side; an escaped shortcode moved across
# those words, with another `:name:` typed beside it, is matched by no stretch's diff, and `_places_by_order` gave
# up on it instead of placing it by the characters beside it, as it did when the whole diff gave None.

_REPEATED = " ".join(["x y"] * 800)       # no word found once: the anchors are B and C only


def test_an_escape_moved_across_the_anchors_of_a_cut_diff_is_placed_by_its_neighbours():
    src = f"A \\:smile: {_REPEATED} B C {_REPEATED} end"
    html = f"<p>{_REPEATED} B C {_REPEATED} A :smile: :smile: end</p>"
    out = saved_as(src, html)
    assert out.count("\\:smile:") == 1, out.count("\\:smile:")
    assert out.endswith("A \\:smile: :smile: end\n"), out[-40:]     # the one the reader typed stays the emoji


def test_an_escape_the_reader_deleted_gives_its_escape_to_no_shortcode_typed_after_the_same_characters():
    # The review of 210: a literal the diff left unmatched within one stretch is one the reader deleted, and a
    # `:smile:` typed after the same twelve characters elsewhere stays the emoji (#594).
    later = " ".join(f"v{i}" for i in range(400))
    for n in range(395, 415):
        first = " ".join(f"w{i}" for i in range(n))
        src = f"{first} Mood today: \\:smile: fine. {later} Mood today: sad. end"
        html = f"<p>{first} Mood today: fine. {later} Mood today: :smile: sad. :smile: end</p>"
        out = saved_as(src, html)
        assert "\\:smile:" not in out, (n, out[-50:])
