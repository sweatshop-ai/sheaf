"""SPEC 10 says what the page does where the page does something the text had not caught up with: one
pin per sentence, so that the text and the behaviour cannot part again without a test noticing.

Each pin reads one section of SPEC.md and looks for the words of the sentence. The behaviour itself is
pinned by the page tests (tests/page/) and by the static pins of the script (tests/test_page_upgrade.py)."""
import re
from pathlib import Path

SPEC = (Path(__file__).resolve().parent.parent / "SPEC.md").read_text(encoding="utf-8")


def section(number):
    """The text of `### <number> ...` to the next heading of the same or a higher level."""
    m = re.search(r"^### %s\b.*?(?=^#{2,3} |\Z)" % re.escape(number), SPEC, re.M | re.S)
    assert m, number
    return m.group(0)


def flat(text):
    return re.sub(r"\s+", " ", text)


# ---- 10.7: a new version -------------------------------------------------------------------------------

def test_the_outage_diagram_does_not_save_and_reload_for_a_new_version_whatever_is_on_screen():
    s = section("10.7")
    assert "new version, so save and reload" not in s
    assert re.search(r"Back --> Settle: new version and nothing only on screen, so reload", s)
    assert re.search(r"Back --> Connected: new version and something only on screen, so a notice", s)


def test_a_new_version_reloads_a_page_with_nothing_only_on_screen_and_gives_a_notice_to_any_other():
    s = flat(section("10.7"))
    assert "A new `version` reloads the page" in s
    assert "unsaved edits or text typed in a comment form" in s
    assert "The sheaf hub was upgraded. Save your edits, then reload this page to use the new version." in s
    assert "Send or cancel your comment, then reload this page to use the new version." in s
    assert "never saves for the person" in s
    assert "for moved text, not for a new version" in s


# ---- 10.2 and 10.4: Escape with text typed -------------------------------------------------------------

def test_escape_with_text_typed_in_a_comment_form_closes_nothing_and_cancel_closes_the_form():
    s = flat(section("10.2"))
    assert "Escape closes one thing per press: popover, side panel, menu, then edit mode" in s
    assert "A popover whose form holds typed text" in s
    assert "closes nothing" in s and "the press is spent" in s
    assert "A popover that holds only a kept comment (10.4) is no popover for this" in s
    assert "Cancel closes the form" in s


def test_a_click_outside_leaves_typed_text_alone_as_escape_does():
    s = flat(section("10.4"))
    assert "**Escape and a click outside** leave a popover whose form holds typed text alone (10.2)" in s
    assert "A kept comment is a notice, not a form being written" in s
    assert "its popover says \"Your comment is being sent…\", and the press or click says" in s


def test_sends_are_counted_per_form():
    s = flat(section("10.4"))
    assert "**A send is per form.**" in s
    for phrase in ("a new comment that is being sent", "a reply or an edit that is out",
                 "Your comment is being sent. Wait for its answer first.",
                 "Send or cancel the comment you are writing first.",
                 "write but a save fails after 30 s without an answer",
                 "a reload waits for every send that is out",
                 "\"Your reply is being sent…\"",
                 "\"What you sent reached the hub after all.\""):
        assert phrase in s, phrase


# ---- 10.4: a selection in edit mode ---------------------------------------------------------------------

def test_in_edit_mode_the_selection_is_not_redrawn_and_the_widened_run_is_painted():
    s = flat(section("10.4"))
    assert "outside edit mode" in s
    assert "In edit mode the selection stays as the person made it" in s
    assert "typing replaces only what was selected" in s
    assert "where the browser has CSS highlights" in s


# ---- 10.8: what the stores hold and who reads them -------------------------------------------------------

def test_the_drafts_stores_are_described_with_their_entries_and_their_readers():
    s = flat(section("10.8"))
    assert "`sheaf-comment-draft:<port>:<doc>`, which holds a list" in s
    assert "`{quote, body, block, head, tail, occ, rid, at, root}`" in s
    assert "`{thread, born, about, kind, body, rid, of, out, at, root}`" in s
    assert "neither holds a key or a token" in s
    assert "every document page of the hub shares that store" in s
    assert "any script of that origin can read it" in s


def test_the_out_mark_names_its_wall_clock_limit_beside_the_open_form_one():
    s = flat(section("10.8"))
    assert "`|now - out| < 32 s`" in s
    assert "a clock that jumps more than 32 s backward right after a send" in s
    assert "the second known limit of the mark" in s
    assert "a form that another page already has open is not withdrawn when the send goes out" in s


def test_the_known_limit_of_a_kept_comment_found_by_the_words_a_paragraph_ends_with_is_written():
    s = flat(section("10.4"))
    assert "Known limit: a paragraph that opens with the entry's words is not offered the entry" in s
    assert "cannot tell this from a paragraph that took over the entry's opening words" in s


def test_a_cancel_given_up_takes_the_busy_button_away_whether_or_not_it_reached_the_hub():
    s = flat(section("10.4"))
    assert "**A cancel given up.**" in s
    assert "A cancel the hub does not answer within 30 s" in s
    assert "takes the busy button" in s and "and the pending line away" in s
    assert "even though the cancel may never have reached the hub, or may have arrived all the same" in s
    assert "A cancel that fails otherwise (the hub unreachable, an error answer) leaves them." in s


def test_an_ask_a_given_up_cancel_did_not_stop_shows_idle_and_a_tell_shows_again_with_a_snapshot():
    s = flat(section("10.4"))
    assert "An Ask the cancel did not stop may still run: the page shows it idle until its answer arrives in its thread or the page is loaded again." in s
    assert "A Tell still waiting shows again with the next snapshot the page applies, or when the page is loaded again." in s
