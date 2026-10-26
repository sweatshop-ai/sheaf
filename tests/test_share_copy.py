"""A share copy carries no comment and no script, in any shape the source gives them
(SPEC 6.1, 9.5, 18 Security).

The one failure that cannot be taken back is a note in a file that has already been
sent, so each test plants a SECRET string where a comment can hide, and asserts on the
bytes of the file, not on how the comment was parsed. Every document is also rendered
as a page, where the secrets must show: a share test that cannot fail would pass
there too."""
import importlib
import json
import random
import re

import pytest
from helpers import active_content

import sheafmd
from sheafmd import comments as rdc
from sheafmd.theme import Theme

R = importlib.import_module("sheafmd.render")    # sheafmd.render is the public function

SECRETS = ["ZQ-SHEAF", "ZQ-LEGACY", "ZQ-FOREIGN", "ZQ-HEADING", "ZQ-CELL", "ZQ-ITEM",
           "ZQ-MULTI-ONE", "ZQ-MULTI-TWO", "ZQ-ORPHAN", "ZQ-QUOTE", "ZQ-INLINE", "ZQ-BETWEEN",
           "ZQ-LEADING", "ZQ-REPLY", "ZQ-EMPTYISH"]


def c(cid, marker, body, *, one_line, quote="passage", orphan=False, replies=()):
    cm = rdc.Comment(id=cid, by="Grace", at="2026-10-14T10:00", quote=quote, body=body,
                     orphan=orphan, marker=marker, replies=list(replies))
    return rdc.format(cm, one_line)


def secret_doc() -> str:
    reply = rdc.Reply(by="Ada", at="2026-10-14T11:00", text="the answer ZQ-REPLY")
    multi = "line one ZQ-MULTI-ONE\nline two ZQ-MULTI-TWO"
    return f"""<!-- ZQ-LEADING note before the title -->
# Plan

First paragraph about the passage.{c("c1", "sheaf-comment", "note ZQ-SHEAF", one_line=True, replies=[reply])}

Second paragraph about budgets.{c("c2", "rd-comment", "old note ZQ-LEGACY", one_line=True)}
<!-- @comment{{ZQ-FOREIGN}} -->

## Budget{c("c3", "sheaf-comment", "heading ZQ-HEADING", one_line=True)}

| a | b |
|---|---|
| one{c("c4", "sheaf-comment", "cell ZQ-CELL", one_line=True)} | two |

- item one{c("c5", "rd-comment", "item ZQ-ITEM", one_line=True)}
<!-- ZQ-BETWEEN -->
- item two

> quoted text<!-- ZQ-QUOTE -->

*emph<!-- ZQ-INLINE -->asis* and the rest.

{c("c6", "sheaf-comment", multi, one_line=False)}

{c("c7", "sheaf-comment", "gone ZQ-ORPHAN", one_line=False, orphan=True, quote="deleted passage")}

Closing text.
"""


def doc(tmp_path, text, name="doc.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_every_secret_shows_in_the_page_so_the_test_can_fail(tmp_path):
    page = sheafmd.render(doc(tmp_path, secret_doc()), share=False)
    missing = [s for s in SECRETS if s not in page and s != "ZQ-EMPTYISH"]
    assert missing == []


def test_no_secret_reaches_the_share_copy(tmp_path):
    log = []
    out = sheafmd.render(doc(tmp_path, secret_doc()), log=log)
    assert [s for s in SECRETS if s in out] == []
    for needle in ("<!--", "-->", "sheaf-comment", "rd-comment", "MDB:", "rd-edit-meta",
                   "rd-anchor", "data-rd-id", "@comment"):
        assert needle not in out, needle
    assert "<script" not in out.lower()
    assert active_content(out) == []
    # What is left is the document.
    for kept in ("First paragraph about the passage.", "Second paragraph about budgets.",
                 "Budget", "item two", "quoted text", "Closing text."):
        assert kept in out
    # and each removal is in the log, none silent
    assert sum("internal note removed" in line for line in log) >= 12


def test_the_same_through_the_library_with_a_crlf_file(tmp_path):
    p = tmp_path / "crlf.md"
    p.write_bytes(secret_doc().replace("\n", "\r\n").encode())
    out = sheafmd.render(p)
    assert [s for s in SECRETS if s in out] == [] and "<!--" not in out


@pytest.mark.parametrize("comment", ["<!---->", "<!-- -->", "<!--\n-->", "<!--x-->", "<!--sheaf-comment-->",
                                     "<!-- id=c1 -->", "<!--\n\n\nZQ-EMPTYISH\n\n-->", "<!-- <b>ZQ-EMPTYISH</b> -->",
                                     "<!-- <script>ZQ-EMPTYISH</script> -->", "<!-- -- ZQ-EMPTYISH -- -->"])
def test_odd_comments_go_whole(tmp_path, comment):
    # In running text a comment cannot run across paragraphs: pandoc shows what lies
    # between (see DROPPED below), so that shape is only tried as a block.
    inline = "" if "\n\n" in comment else f" {comment}"
    out = sheafmd.render(doc(tmp_path, f"before\n\n{comment}\n\nafter{inline} end\n"))
    assert "ZQ-EMPTYISH" not in out and "<!--" not in out and "-->" not in out
    assert "before" in out and "after" in out and "end" in out


# ── removing one comment must not make another ───────────────────────────────

def test_a_comment_that_removal_joins_together_is_removed_too(tmp_path):
    log = []
    p = doc(tmp_path, "para <!<!-- x -->-- ZQ-JOINED --> end\n")
    out = sheafmd.render(p, log=log)
    assert "ZQ-JOINED" not in out and "<!--" not in out
    assert "para" in out and "end" in out
    assert sum("internal note removed" in line for line in log) == 2


def test_strip_comments_repeats_until_none_is_left():
    log = []
    assert sheafmd.strip_comments("a<!<!-- x -->-- y -->b<!<!<!-- 1 -->-- 2 -->-- 3 -->c", log) == "abc"
    assert len(log) == 5


def test_a_dash_dash_bang_comment_end_cannot_let_markup_out(tmp_path):
    p = doc(tmp_path, "a\n\n<!-- ZQ-A --!> <img src=x onerror=alert(1)> -->\n\nb\n")
    out = sheafmd.render(p)
    assert "ZQ-A" not in out and "onerror" not in out
    assert active_content(out) == []


def test_a_dash_dash_bang_comment_end_with_words_after_it_stops_the_share_copy(tmp_path):
    # A browser ends the comment at --!> and shows ZQ-B; the strip takes it with the rest.
    p = doc(tmp_path, "a\n\n<!-- ZQ-A --!> <img src=x onerror=alert(1)> ZQ-B -->\n\nb\n")
    with pytest.raises(sheafmd.UnclosedComment) as e:
        sheafmd.render(p)
    assert e.value.line == 3


# ── an opener nothing closes ────────────────────────────────────────────────

LINE_START = ["<!-- never closed", "  <!-- never closed", "> <!-- never closed",
              "- <!-- never closed", "<!--never closed", "<!-- never closed --!>"]


@pytest.mark.parametrize("opener", LINE_START)
def test_an_unclosed_comment_at_a_line_start_stops_the_share_copy_and_names_its_line(tmp_path, opener):
    p = doc(tmp_path, f"one\n\n{opener}\n\nthree ZQ-AFTER\n")
    with pytest.raises(sheafmd.UnclosedComment) as e:
        sheafmd.render(p)
    assert e.value.line == 3 and "line 3" in str(e.value)
    assert isinstance(e.value, sheafmd.RenderError)


@pytest.mark.parametrize("opener", ["two <!-- never closed", "- item <!-- never closed",
                                    "# head <!-- never closed", "| <!-- never closed |",
                                    "**bold <!-- never closed**"])
def test_an_unclosed_opener_in_running_text_hides_nothing_and_is_not_an_error(tmp_path, opener):
    body = "| a |\n|---|\n" if opener.startswith("|") else ""
    out = sheafmd.render(doc(tmp_path, f"one\n\n{body}{opener}\n\nthree ZQ-AFTER\n"))
    assert "ZQ-AFTER" in out and "<!--" not in out
    assert "&lt;!--" in out


HEADS = ['<!-- sheaf-comment id=c1 by="Ada" at=2026-10-14T10:00 status=open quote="budget"',
         '<!-- rd-comment id=c1 by="Ada" at=2026-10-14T10:00 status=open quote="budget"']


@pytest.mark.parametrize("head", HEADS)
@pytest.mark.parametrize("lead", ["", "- ", "> ", "## "])
def test_a_comment_that_lost_its_closing_arrow_stops_the_share_copy_whatever_the_opener_sits_in(
        tmp_path, head, lead):
    """The note is a reviewer's: pandoc turns the opener in running text into &lt;!--,
    so nothing hides the body, and it would reach the person the copy goes to. The copy
    is refused, with the line, and says to close or delete the comment."""
    p = doc(tmp_path, f"One.\n\n{lead}The budget is fine.{head}\nInternal: ZQ-LOST, do not tell them.\n\nNext.\n")
    with pytest.raises(sheafmd.UnclosedComment) as e:
        sheafmd.render(p)
    assert e.value.line == 3
    assert "line 3" in str(e.value) and "close" in str(e.value) and "delete" in str(e.value)
    assert "ZQ-LOST" not in str(e.value)


def test_a_comment_that_lost_its_closing_arrow_still_shows_on_the_page(tmp_path):
    p = doc(tmp_path, f"One.\n\nThe budget is fine.{HEADS[0]}\nInternal: ZQ-LOST.\n\nNext.\n")
    assert "Next." in sheafmd.render(p, share=False)


def test_the_line_is_the_one_in_the_file_as_written_when_a_closed_comment_is_above_it(tmp_path):
    closed = c("c9", "sheaf-comment", "ZQ-CLOSED", one_line=False)
    text = f"One.{closed}\n\nTwo.\n\nThe budget is fine.{HEADS[0]}\nInternal: ZQ-LOST.\n\nNext.\n"
    want = next(n for n, line in enumerate(text.split("\n"), 1) if line.startswith("The budget"))
    with pytest.raises(sheafmd.UnclosedComment) as e:
        sheafmd.render(doc(tmp_path, text))
    assert e.value.line == want and want > 5


def test_a_lost_arrow_that_a_later_comment_closes_across_paragraphs_is_refused_too(tmp_path):
    """The strip would run on to the next closing arrow and take the paragraphs in
    between with it; nothing leaks, but it is the same lost arrow, and it is refused."""
    later = c("c2", "sheaf-comment", "ZQ-LATER", one_line=False)
    p = doc(tmp_path, f"One.{HEADS[0]}\nInternal: ZQ-LOST.\n\nTwo.{later}\n")
    with pytest.raises(sheafmd.UnclosedComment):
        sheafmd.render(p)


H = HEADS[0]
# A backtick that pairs with another one far away, or none at all, must not hide the head
# from the check while pandoc still prints the note's body: every shape is a reviewer's
# comment that lost its arrow, and every one must stop the copy.
LEAKS = {
    "backtick across list items": f"- Use `foo for this{H}\n  ZQ-SECRET\n- Other `bar` item\n",
    "backtick across quote paragraphs": f"> Use `foo{H}\n> ZQ-SECRET\n>\n> Then `x` too\n",
    "backtick across table cells": f"| a | b |\n|---|---|\n| `a{H}<br>ZQ-SECRET | b` |\n",
    "escaped backtick": f"A \\`x{H}\nZQ-SECRET ` end\n",
    "backtick inside an earlier comment": f"A <!-- x ` y --> B{H}\nZQ-SECRET ` end\n",
}


@pytest.mark.parametrize("shape", LEAKS)
def test_a_lost_arrow_after_an_odd_or_escaped_backtick_stops_the_share_copy(tmp_path, shape):
    text = f"One.\n\n{LEAKS[shape]}\nNext.\n"
    want = next(n for n, line in enumerate(text.split("\n"), 1) if "sheaf-comment" in line)
    p = doc(tmp_path, text)
    with pytest.raises(sheafmd.UnclosedComment) as e:
        sheafmd.render(p)
    assert e.value.line == want and f"line {want}" in str(e.value) and "close" in str(e.value)
    assert "ZQ-SECRET" not in str(e.value)
    assert "Next." in sheafmd.render(p, share=False)


def test_a_lost_arrow_hidden_by_a_backtick_is_refused_when_a_later_comment_would_close_it(tmp_path):
    later = c("c2", "sheaf-comment", "ZQ-LATER", one_line=False)
    p = doc(tmp_path, f"One.\n\nA `x{H}\nZQ-LOST ` end.\n\nBetween ZQ-BETWEEN.\n\nTwo.{later}\n")
    with pytest.raises(sheafmd.UnclosedComment) as e:
        sheafmd.render(p)
    assert e.value.line == 3 and "a note by a reviewer" in str(e.value)


def test_a_lost_arrow_at_a_line_start_says_it_is_a_reviewers_note(tmp_path):
    p = doc(tmp_path, f"One.\n\n{H}\nZQ-SECRET\n\nNext.\n")
    with pytest.raises(sheafmd.UnclosedComment) as e:
        sheafmd.render(p)
    assert e.value.line == 3 and "a note by a reviewer" in str(e.value)
    assert "ZQ-SECRET" not in str(e.value)


@pytest.mark.parametrize("quoted", ["- item\n\n  ~~~\n  {head}\n  ~~~\n",
                                    "- item\n\n      {head}\n",
                                    "> ~~~\n> {head}\n> ~~~\n"])
def test_a_comment_head_quoted_in_code_inside_a_list_or_quote_is_an_example_not_an_error(tmp_path, quoted):
    out = sheafmd.render(doc(tmp_path, f"One.\n\n{quoted.format(head=H)}\nafter ZQ-KEEP\n"))
    assert "ZQ-KEEP" in out and "<!--" not in out
    assert "&lt;!-- sheaf-comment" in out


@pytest.mark.parametrize("text", ["Start one with `<!-- sheaf-comment id=c1 by=Ada` in the source.\n",
                                  "```md\n<!-- sheaf-comment id=c1 by=Ada\n```\n"])
def test_a_comment_head_quoted_in_code_is_an_example_not_an_error(tmp_path, text):
    out = sheafmd.render(doc(tmp_path, f"One.\n\n{text}\nafter ZQ-KEEP\n"))
    assert "ZQ-KEEP" in out and "<!--" not in out


# An opener in running text that nothing closes hides nothing by itself (pandoc prints it
# as text). But the strip closes it with the next `-->` anywhere below and takes every
# paragraph in between, so a share copy would lose text without a word. Pandoc says
# which openers are text: it prints those as `&lt;!--` outside code.
SWALLOWED = ["A <!-- x", "- item <!-- x", "> quote <!-- x", "# Head <!-- x", "A \\<!-- x"]
LATER = ["B <!-- y -->", "<!-- y -->", "B " + c("c9", "sheaf-comment", "ZQ-LATER", one_line=True)]


@pytest.mark.parametrize("later", LATER)
@pytest.mark.parametrize("opener", SWALLOWED)
def test_an_unclosed_opener_in_running_text_that_a_later_comment_would_close_stops_the_share_copy(
        tmp_path, opener, later):
    p = doc(tmp_path, f"One.\n\n{opener}\n\nImportant ZQ-KEEP.\n\n{later}\n\nEnd.\n")
    with pytest.raises(sheafmd.UnclosedComment) as e:
        sheafmd.render(p)
    assert e.value.line == 3 and "line 3" in str(e.value)
    assert "close" in str(e.value) and "remove" in str(e.value)
    assert "ZQ-KEEP" not in str(e.value) and "ZQ-LATER" not in str(e.value)
    out = sheafmd.render(p, share=False)                  # the page shows the text
    assert "ZQ-KEEP" in out and "End." in out


@pytest.mark.parametrize("quoted", ["Use `<!--` to open.", "```html\n<!-- x\n```"])
def test_an_opener_quoted_in_code_that_a_later_comment_would_close_stops_the_share_copy_too(tmp_path, quoted):
    # Nothing is hidden by the example itself, but the strip does not spare code: it
    # would close the example with the next arrow and drop what lies between.
    text = f"One.\n\n{quoted}\n\nImportant ZQ-KEEP.\n\nB <!-- y -->\n\nEnd.\n"
    want = next(n for n, line in enumerate(text.split("\n"), 1) if "<!--" in line)
    with pytest.raises(sheafmd.UnclosedComment) as e:
        sheafmd.render(doc(tmp_path, text))
    assert e.value.line == want and "ZQ-KEEP" not in str(e.value)


# The strip and pandoc must agree on what a comment is. The check is not a list of
# shapes: it asks pandoc for the words it shows outside code, before and after the strip,
# and refuses the copy when the strip took one. Each of these lost KEEP1 without a word.
DROPPED = {
    "a code span opener, a bare arrow in running text":
        ("Type `<!--` to open a comment.\n\nKEEP1 para.\n\nThe flow is input --> output, KEEP2.\n", 1),
    "a code span opener, a bare arrow in a mermaid fence":
        ("To hide a line, type `<!--` before it.\n\nKEEP1 para.\n\n```mermaid\ngraph TD\nA --> B\n```\n\nKEEP2 end.\n", 1),
    "an opener in text, a bare arrow in a fence":
        ("Use <!-- to start.\n\nKEEP1 para.\n\n```\n-->\n```\n\nKEEP2.\n", 1),
    "an opener in front matter":
        ("---\ntitle: a <!-- b\n---\n\nKEEP1 para.\n\nLater<!-- SECRET generic --> KEEP2.\n", 2),
    "an opener in an attribute value":
        ('A <span title="<!--">x</span>\n\nKEEP1 para.\n\nLater<!-- SECRET generic --> KEEP2.\n', 1),
    "an empty comment that pandoc reads and the strip does not":
        ("A <http://x/<!--> b\n\nKEEP1 para.\n\nLater<!-- SECRET generic --> KEEP2.\n", 1),
    "a comment that the strip's second pass makes of two":
        ("A <!<!-- x -->-- stray\n\nKEEP1 para.\n\n--> KEEP2\n", 1),
    "a comment written in running text across paragraphs":
        ("before\n\nafter <!--\n\n\nKEEP1\n\n--> end\n", 3),
    "a comment written with an escaped opener in running text":
        ("Write \\<!-- your KEEP1 note --> to hide a note.\n", 1),
    "the same in a list item":
        ("- Write \\<!-- your KEEP1 note --> to hide.\n", 1),
    "the same in a heading":
        ("# Write \\<!-- your KEEP1 note --> to hide\n", 1),
    "the same in a table cell":
        ("| a | b |\n|---|---|\n| Write \\<!-- your KEEP1 note --> | y |\n", 3),
    "an opener in an attribute of raw html":
        ('<table>\n<tr><td title="<!--">KEEP1</td></tr>\n<tr><td>KEEP2 <!-- note --> KEEP3</td></tr>\n</table>\n', 2),
    "a comment that a browser ends at --!> and pandoc does not":
        ("A <!-- a --!> KEEP1 visible --> end\n", 1),
    "a comment whose removal makes a script tag":
        ("<scr<!-- x -->ipt>\nKEEP1 para\n\nKEEP2 more\n", 1),
    "an opener and a bare arrow in one paragraph":
        ("Type `<!--` to open and `-->` to close, KEEP1.\n", 1),
    # <style-name> is an element nobody defined, not a style: it hides nothing after it
    "a placeholder tag that starts with style, then a swallowed paragraph":
        ("New styles go in styles/<style-name>.go.\n\nTo hide a draft, type `<!--` before it.\n\n"
         "KEEP1 This paragraph must reach the client.\n\nThe pipeline: input --> output.\n", 3),
    "a comment inside math":
        ("Math $a <!-- KEEP1 --> b$ end\n", 1),
    "a comment whose removal makes a style tag":
        ("<sty<!-- x -->le>\nKEEP1 para\n\nKEEP2 more\n", 1),
    "a comment whose removal makes a link reference definition, which shows nothing":
        ("[KEEP1]:<!-- c --> http://x\n\nKEEP2\n", 1),
    # a tag the strip forms inside a paragraph hides the text after it, in every block after it
    "a comment whose removal makes a script tag inside a paragraph":
        ("~~<em><span title=' KEEP1 |<span title='<scr<!-- x -->ipt> KEEP2 \n```\n KEEP3 <scr<!-- x -->ipt> KEEP4 \n", 1),
    # only a raw node that is a whole comment can join the pieces of one: `<b></b>` is not
    "a comment the text spells around raw tags that are not comments":
        ("Text <<b></b>!-- \\<!-- KEEP1 --> end.\n", 1),
    # a stretch the strip takes inside a tag joins its pieces into a tag the sanitiser deletes
    # with its content, or that hides what follows: one rule, not a list of tags
    "a stretch inside the name of a form tag, after a code span that says form":
        ("The `form` tag.\n\n<fo<!-- x -->rm>\n\nKEEP1 para.\n\nKEEP2 end.\n", 3),
    "a stretch inside the name of a script tag":
        ("<div>\n<script<!-- x -->>\n\nKEEP1 para.\n", 2),
    "a stretch inside an attribute name, which hides the block":
        ("<div hidden<!-- x -->>\n\nKEEP1 para.\n", 1),
    "a stretch inside the name of a title tag":
        ("<div>\n<title<!-- x -->>\n\nKEEP1 para.\n", 2),
    "a stretch inside the value of an attribute, which is the safe side of a rule that has no parser":
        ('<a href="x" title="a <!-- c --> b">KEEP1</a>\n', 1),
    # The strip leaves `</p><td title="` and a browser reads the
    # next paragraph as the attribute's value; nothing closes the tag in the same block
    "a stretch inside a tag that nothing closes before the block ends":
        ('</p><td title="<!--"><!--->\n\n KEEP1  KEEP2 \n', 1),
    # the other half of that rule: a `<y` the stretch is in, closed by a `>` later in the block,
    # is a tag the strip makes (the same text without the `>` is text and is not refused)
    "a stretch after a `<` and a letter that a later arrow in the block closes":
        ("Say x<y <!-- c --> KEEP1 z>w\n", 1),
    # a self-closed <style/> or <script/> in an HTML block opens no element for the sanitiser, which
    # keeps the text after it, so the check must count that text
    **{f"a self-closed {tag} tag, then a swallowed paragraph":
       (f"<div>\n{tag}\n</div>\n\nIntro `<!--` code.\n\nKEEP1 para.\n\nend `-->` code.\n", 5)
       for tag in ("<STYLE/>", "<script/>", "<style />")},
    # a document the check cannot read (a tree too deep for it) is refused, naming the first
    # stretch, when it has one: the render reads what the strip leaves and could lack text
    "quotes nested too deep for the check to read, then a swallowed paragraph":
        ("> " * 700 + "x\n\nIntro `<!--` code.\n\nKEEP1 para.\n\nend `-->` code.\n", 3),
    # the same when the stretch is a whole comment that loses nothing: the tree is the reason
    "quotes nested too deep for the check to read, then a whole comment":
        ("> " * 700 + "x <!-- c -->\n", 1),
    # The strip makes an image of a link, and the images step shows a file that is not there as a
    # notice without its alt. The check does not count an image's alt as text the page shows (the
    # smaller change: the images step stays as it is)
    "words the strip makes the alt text of an image":
        ("!<!-- x -->[KEEP1 words](x.png)\n", 1),
    # The strip makes a link of `[a]` and `(KEEP1)`, and the word moves into an
    # address, which counts as shown (it has to: `[KEEP1](http://x/<!-- c -->y)` loses nothing)
    "a stretch between a closing bracket and an opening parenthesis, which makes a link":
        ("[a]<!-- x -->(KEEP1)\n", 1),
    "the same with a title, which is a tooltip":
        ('[a]<!-- x -->(http://x "KEEP1")\n', 1),
    "a stretch inside a style tag whose word is also in a code span":
        ("Text <sty<!-- x -->le> KEEP1 `style KEEP1`\n", 1),
    **{f"a stretch inside the name of a {tag} tag":
       (f"<div>\n<{tag}<!-- x -->>\n\nKEEP1 para.\n", 2)
       for tag in ("form", "select", "button", "iframe", "textarea", "template")},
    # text with no word character is text too: emoji, check marks, punctuation
    "symbols and no letter between a code span opener and a code span arrow":
        ("the start.\n\n`<!--`\n\n\U0001F389 \U0001F680 \u2713 \u2717\n\n`-->`\n", 3),
    # the strip makes an image of text, and the words become its title, a tooltip
    "words that the strip moves into the title of an image":
        (' KEEP1 [a](![i](x.png " KEEP2 <!-- sheaf-comment id=c9 by="A" at=2026-10-14T09:00 status=open quote="q"\n'
         'note text\n--> KEEP3  KEEP4  KEEP5 ")** KEEP6 <p>\n', 1),
}


@pytest.mark.parametrize("shape", DROPPED)
def test_a_strip_that_would_take_text_pandoc_shows_stops_the_share_copy_whatever_the_shape(tmp_path, shape):
    text, line = DROPPED[shape]
    with pytest.raises(sheafmd.UnclosedComment) as e:
        sheafmd.render(doc(tmp_path, text))
    assert e.value.line == line and f"line {line}" in str(e.value)
    assert "KEEP1" not in str(e.value) and "SECRET" not in str(e.value)


@pytest.mark.parametrize("shape", [
    "quotes nested too deep for the check to read, then a swallowed paragraph",
    "quotes nested too deep for the check to read, then a whole comment",
])
def test_the_refusal_for_a_tree_the_check_cannot_read_blames_the_nesting_not_a_comment(tmp_path, shape):
    # The refusal named the first stretch the strip takes and said its `<!--` "is not a
    # comment to the reader". When the stretch is a whole comment (the second shape) that is false:
    # it is closed, and it loses nothing. The check could not read the tree, and that is the reason.
    text, line = DROPPED[shape]
    with pytest.raises(sheafmd.UnclosedComment) as e:
        sheafmd.render(doc(tmp_path, text))
    message = str(e.value)
    assert e.value.line == line and f"line {line}" in message
    assert "nests too deep" in message and "is not a comment" not in message


def test_the_comments_a_document_of_46_kb_spells_in_raw_tags_are_found_in_a_second(tmp_path, monkeypatch):
    # The text of a block was read character by character against every
    # cut against every comment it spells, which is slow on a large input. The whole refusal still costs
    # a dozen pandoc runs (and more on a loaded machine), so the bound is on that one step.
    import time
    spent = []
    real = R._spelled_out

    def timed(text, marks):
        start = time.perf_counter()
        try:
            return real(text, marks)
        finally:
            spent.append(time.perf_counter() - start)

    monkeypatch.setattr(R, "_spelled_out", timed)
    text = ("<<b></b>!-- y --> " + "<b>x</b> " * 5000 + "\n\n" + "a <!-- c --> b\n\n" * 63
            + "Type `<!--` here.\n\nKEEP1\n\n`-->`\n")
    assert 45_000 < len(text) < 47_000
    with pytest.raises(sheafmd.UnclosedComment):
        sheafmd.render(doc(tmp_path, text))
    assert spent and sum(spent) < 1, sum(spent)


@pytest.mark.parametrize("limit", [("HEAP", "-M256m"), ("TIMEOUT", 2)])
def test_a_share_copy_is_not_made_when_pandoc_cannot_read_the_document_the_check_reads(tmp_path, monkeypatch, limit):
    # The check reads the original, the render reads what the strip leaves, and the
    # strip takes the footnote that cites itself, which pandoc cannot read. The check must not
    # pass the document then: a copy without KEEP1 and the word after it, with one
    # log line about an internal note, is a loss. The page of the same text is not made.
    from sheafmd import _pandoc
    monkeypatch.setattr(_pandoc, *limit)
    text = "Intro `<!--` code.\n\n[^1]: a [^1]\n\nKEEP1 para.\n\nend `-->` code.\n"
    with pytest.raises(sheafmd.RenderError):
        sheafmd.render(doc(tmp_path, text))
    with pytest.raises(sheafmd.RenderError):
        sheafmd.render(doc(tmp_path, text), share=False)


def test_a_document_of_350_nested_images_is_not_refused_for_its_depth_whichever_reader_reads_its_tree(tmp_path, monkeypatch):
    # pandoc's tree of 350 nested images is 1055 levels deep. json.loads gives up
    # on it on 3.11 (from 330 images, at about 1000 levels), where it raised RecursionError past the
    # check and the stack reader reads it now; on 3.12 json.loads reads it (it reads 9997 levels there),
    # so the stack reader is not used. The copy is made either way (its images step shows a file that is
    # not there as a missing image, KEEP1 being the alt text of one). The test after this one makes
    # json.loads give up on every Python; here the check is that the stack reader read a tree exactly
    # when json.loads could not, so the comment above cannot go stale on the interpreter that runs it.
    trees, by_stack = [], []
    json_loads, stack_reader = R._json_loads, R._loads_without_recursion
    monkeypatch.setattr(R, "_json_loads", lambda text: (trees.append(text), json_loads(text))[1])
    monkeypatch.setattr(R, "_loads_without_recursion", lambda text: (by_stack.append(text), stack_reader(text))[1])
    text = "![" * 350 + "KEEP1" + "](x.png)" * 350 + " <!-- c -->\n"
    out = sheafmd.render(doc(tmp_path, text))
    assert "missing image" in out and "<!--" not in out
    gave_up = []
    for tree in trees:
        try:
            json.loads(tree)
        except RecursionError:
            gave_up.append(tree)
    assert trees and by_stack == gave_up


def test_the_check_reads_a_tree_that_json_loads_gives_up_on_whichever_python_it_runs_on(tmp_path, monkeypatch):
    # json.loads stops near 1000 levels on 3.11 (the test above) and much later on 3.12, so on 3.12
    # this makes it give up on pandoc's tree the way 3.11 does: how deep a document may nest must
    # not depend on the interpreter.
    real = json.loads

    def loads(s, *a, **k):
        if isinstance(s, str) and '"pandoc-api-version"' in s[:60]:
            raise RecursionError("maximum recursion depth exceeded while decoding a JSON array")
        return real(s, *a, **k)
    monkeypatch.setattr(json, "loads", loads)
    text = "![" * 150 + "KEEP1" + "](x.png)" * 150 + " <!-- c -->\n"
    out = sheafmd.render(doc(tmp_path, text))
    assert "missing image" in out and "<!--" not in out


def test_a_json_tree_deeper_than_any_python_recurses_is_read_all_the_same():
    n = 200_000
    text = "[" * n + '"leaf"' + "]" * n
    with pytest.raises(RecursionError):         # the premise: on 3.11, 3.12 and later alike
        json.loads(text)
    tree, depth = R._json_loads(text), 0
    while isinstance(tree, list):
        tree, depth = tree[0], depth + 1
    assert depth == n and tree == "leaf"


JSON_READS = [
    "null", "true", "false", "0", "-12", "3.5e2", "123456789012345678901234567890", '"a"',
    '"\\u00e9\\ud83d\\ude00 \\n \\" \\\\ \\/"', "[]", "{}", "[[],{}]", "NaN", "[Infinity, -Infinity]",
    ' \n[1 , 2,\t{"a" : [null, "x"], "b": {}}]\r\n', '{"a":1,"a":2}', '{"t":"Str","c":"é\U0001f600"}',
    '{"pandoc-api-version":[1,23,1],"meta":{},"blocks":[{"t":"Para","c":[{"t":"Str","c":"x"},'
    '{"t":"Space"},{"t":"Link","c":[["",[],[]],[{"t":"Str","c":"y"}],["http://x/","t"]]}]}]}',
]
JSON_REFUSED = [
    "", " ", "[", "]", "{", "}", "[1,]", "[,1]", "[1 2]", "[1,,2]", "[}", "{]", "[1]]", "[1] x",
    '{"a" 1}', '{"a":}', '{"a":1,}', '{1:2}', '{"a":1 "b":2}', '{"a"}', "tru", '"abc', "﻿[]",
]


def agree(text):
    """Both read it to the same value, or both refuse it as a ValueError."""
    try:
        want = repr(json.loads(text))
    except ValueError:
        with pytest.raises(ValueError):
            R._loads_without_recursion(text)
        return "refused"
    assert repr(R._loads_without_recursion(text)) == want, text
    return "read"


@pytest.mark.parametrize("text", JSON_READS)
def test_the_stack_reader_reads_what_json_loads_reads(text):
    assert agree(text) == "read"


@pytest.mark.parametrize("text", JSON_REFUSED)
def test_the_stack_reader_refuses_what_json_loads_refuses(text):
    assert agree(text) == "refused"


def test_the_stack_reader_and_json_loads_agree_on_a_few_thousand_damaged_texts():
    rng = random.Random(14)
    seen = {"read": 0, "refused": 0}
    for _ in range(3000):
        text = rng.choice(JSON_READS)
        i = rng.randrange(len(text) + 1)
        how = rng.randrange(4)
        if how == 0:
            text = text[:i] + text[i + 1:]
        elif how == 1:
            text = text[:i] + rng.choice('[]{},:"\\ 0a\x0b ') + text[i:]
        elif how == 2:
            text = text[:i]
        else:
            text = text[:i] + text[i:] * 2
        seen[agree(text)] += 1
    assert seen["read"] > 100 and seen["refused"] > 100, seen


@pytest.mark.parametrize("text", [
    "Write <\\!-- KEEP0 to open one.\nAnd x <!-- old <!-- nested --> y KEEP1.\n",
    "- Write <\\!-- KEEP0 to open one.\n- And x <!-- old <!-- nested --> y KEEP1.\n",
])
def test_an_opener_pandoc_shows_earlier_in_the_block_does_not_make_a_later_whole_comment_a_loss(tmp_path, text):
    # Nothing is dropped but the comment: the escaped opener is text to the strip too.
    out = sheafmd.render(doc(tmp_path, text))
    assert "KEEP0" in out and "KEEP1" in out and "nested" not in out and "<!--" not in out.replace("&lt;!--", "")


def test_the_check_asks_pandoc_a_fixed_number_of_times_however_many_comments_there_are(tmp_path, monkeypatch):
    import subprocess
    calls = []
    real = subprocess.run
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    items = "".join(f"- item {n} <!-- old <!-- nested --> end\n" for n in range(60))
    sheafmd.render(doc(tmp_path, items))
    assert len(calls) <= 8, len(calls)


@pytest.mark.parametrize("text", [
    "Never edit between `<!-- start -->` and `<!-- end -->`. Edit KEEP1.\n",
    "Write `<!-- note -->`, KEEP1; or `<!-- other -->`.\n",
    "Example:\n\n```html\n<!-- one -->\n<!-- two -->\n```\n\nand KEEP1 after.\n",
    "The note asked for `<!-- TO CONFIRM: x -->` (or `<!-- later -->`), KEEP1.\n",
])
def test_comments_quoted_whole_in_code_are_removed_as_before_and_do_not_stop_the_copy(tmp_path, text):
    # What the strip takes is the example and nothing else: the words around it stay,
    # though the backticks it leaves behind pair up differently.
    out = sheafmd.render(doc(tmp_path, text))
    assert "KEEP1" in out and "<!--" not in out


@pytest.mark.parametrize("text", [
    "[KEEP1](http://x/<!-- c -->y)\n",                       # the strip turns the text into a link
    "<div>\n<!-- c -->\nKEEP1\n</div>\n",
    "<div>\nKEEP1 <!-- a > b --> KEEP2\n</div>\n",
    "<p>KEEP1 <!----> KEEP2 <!-- x --></p>\n",
    "Text KEEP1 <!-- c --> and <b>KEEP2</b> <!-- d -->.\n",
    '[KEEP1](http://x.y "tip <!-- c --> KEEP2")\n',      # a title is a tooltip, not text
    "<script>\nvar a = 1; <!-- c -->\n</script>\n\nKEEP1\n",   # a script that is closed hides nothing after it
    "\u2713 KEEP1 <!-- c --> \u2717 \u2014 \u00ab \U0001F389 \u00bb\n",   # symbols the strip leaves where they are
    "Text <b>KEEP1</b><!-- c --> and <i>x</i> <!-- d --> y.\n",             # beside tags, not inside one
    "If a < b <!-- c --> and c > d, KEEP1.\n",                              # a `<` that opens no tag
    # a `<` and a letter that nothing closes in the block is text, with or without a code span
    # or a fence around it: the halves make no tag (nothing is lost)
    "Say x<y and <!-- c --> KEEP1.\n",
    "Use `a<b` here <!-- note --> KEEP1 done.\n",
    "```\nif a<b:\n    pass\n```\nKEEP1 text <!-- c --> KEEP2\n",
    # code is an example and joins nothing: a stretch in it makes no tag and no link, and a `<` or a
    # `>` in code is not one the rule reads (the comment goes from the code)
    "`[a]<!-- x -->(KEEP1)`\n",
    "Write `<b<!-- x -->>` to show it. KEEP1\n",
    "```\n<div hidden<!-- x -->>\n```\n\nKEEP1\n",
    "```\n[a]<!-- x -->(KEEP1)\n```\n\nKEEP2\n",
    "Compare `a<b` <!-- note --> and `c>d`, KEEP1.\n",
])
def test_a_comment_in_a_link_address_or_in_raw_html_that_the_strip_takes_whole_is_not_a_loss(tmp_path, text):
    out = sheafmd.render(doc(tmp_path, text))
    assert "KEEP1" in out and "<!--" not in out


@pytest.mark.parametrize("text", [
    "Icon \U000f0001 and text KEEP1<!-- note --> end.\n",                  # an icon font's character, plane 15
    "\ue000 <b>KEEP1</b><!-- c --> \U000f0000 end\n",                      # raw html and private-use characters
    "Icons: " + "".join(chr(c) for c in range(0xE000, 0xF8FF)) + "\n\nText KEEP1<!-- note --> end.\n",
])
def test_private_use_characters_in_the_document_cannot_break_the_check(tmp_path, text):
    out = sheafmd.render(doc(tmp_path, text))
    assert "KEEP1" in out and "<!--" not in out


def test_an_entity_that_spells_the_character_the_check_uses_for_a_hole_is_not_a_loss(tmp_path):
    # `&#xE000;` is the first private-use character, the hole's choice
    # when only the characters of the source were avoided, and the hole is not a word: the
    # entity's character was taken out with it, "a" and "b" read as one word, and the copy
    # that lost nothing was refused at line 1.
    out = sheafmd.render(doc(tmp_path, "a&#xE000;b KEEP1 <!-- c --> KEEP2\n"))
    assert "KEEP1" in out and "KEEP2" in out and "<!--" not in out


def test_a_comment_inside_two_footnote_labels_is_not_refused_for_a_footnote_that_cites_itself(tmp_path):
    # One hole for every stretch made `[^<!--a-->]: x [^<!--b-->]` into
    # `[^H]: x [^H]`, a footnote that cites itself, and pandoc ran out of heap on it. A hole
    # of its own for each stretch keeps the two labels apart, as they are in the source.
    out = sheafmd.render(doc(tmp_path, "Intro.\n\n[^<!--a-->]: x [^<!--b-->]\n\nKEEP1 end.\n"))
    assert "KEEP1" in out and "<!--" not in out


@pytest.mark.parametrize("tag", ["script", "style"])
def test_a_raw_element_nothing_closes_says_in_the_log_that_the_text_after_it_went_too(tmp_path, tag):
    # The sanitiser reads `<script>` in running text as an element that runs to the end
    # of the document and removes it with everything after it. That is not the strip's doing and the
    # copy is made, but a log line that says only "<script> removed" hides that KEEP1 and KEEP2 went.
    log = []
    out = sheafmd.render(doc(tmp_path, f"One.\n\nA <{tag}> note KEEP1\n\nKEEP2\n"), log=log)
    assert "KEEP1" not in out and "KEEP2" not in out
    [line] = [x for x in log if "never closed" in x]
    assert line.lstrip().startswith("!") and "line 3" in line and f"<{tag}>" in line and "after it" in line


@pytest.mark.parametrize("text", [
    "<script>\nvar a = 1;\n</script>\n\nKEEP1\n",                # closed
    "A `<script>` tag, and <style/> too.\n\nKEEP1\n",              # in code, and a tag that holds nothing
    "```html\n<script>\n```\n\nKEEP1\n",                         # in a fence
])
def test_a_raw_element_that_is_closed_or_not_an_element_adds_no_warning_to_the_log(tmp_path, text):
    log = []
    out = sheafmd.render(doc(tmp_path, text), log=log)
    assert "KEEP1" in out
    assert not [x for x in log if "never closed" in x]


@pytest.mark.parametrize("text, line", [
    ("<script>closed</script>\n\nA <script> note KEEP1\n\nKEEP2\n", 3),     # one that is closed, before it
    ("<style>a { }</style>\n\nB <style> x KEEP1\n\nKEEP2\n", 3),
    ("Use `<script>` here.\n\nA <script> note KEEP1\n\nKEEP2\n", 3),          # one in a code span
    ("```html\n<script>\n```\n\nA <script> note KEEP1\n\nKEEP2\n", 5),        # one in a fence
    ("<!-- <script> -->\n\nA <script> note KEEP1\n\nKEEP2\n", 3),             # one in a comment
])
def test_a_raw_element_nothing_closes_is_named_at_its_own_line_whatever_comes_before_it(tmp_path, text, line):
    # The line named was the first `<script>` of the source that is not in a code block, closed
    # or not; the line to name is that of the tag that is not closed.
    log = []
    sheafmd.render(doc(tmp_path, text), log=log)
    [found] = [x for x in log if "never closed" in x]
    assert f"line {line}:" in found


def test_a_comment_that_names_a_script_adds_no_warning_to_the_page_log(tmp_path):
    # The page keeps its comments in the html pandoc gives, and `<script>` in one is words, not a
    # tag: nothing was removed, so the log must not say that the text after it was.
    text = ('Intro.\n\n<!-- sheaf-comment id=c1 by="A" at=2026-10-14T09:00 status=open quote="Intro"\n'
            'the <script> tag here is unsafe\n-->\n\nKEEP1 after.\n')
    log = []
    out = sheafmd.render(doc(tmp_path, text), share=False, log=log)
    assert "KEEP1" in out and not [x for x in log if "never closed" in x]


def test_text_in_code_between_a_quoted_opener_and_a_later_arrow_is_lost_by_decision_and_logged(tmp_path):
    # Decided and final: the check does not count code on the page side. A comment
    # quoted whole in a code span or a fence is lost from the copy (the example is the loss), and
    # so is the text between a quoted opener and a later arrow of the same code block. Counting
    # code would refuse every document that quotes a whole comment in backticks. This test pins the decision so that nothing changes it by accident.
    log = []
    out = sheafmd.render(doc(tmp_path, "\n```\n<!---> KEEP1 <!--> KEEP2\n\n"), log=log)
    assert "KEEP1" not in out and "KEEP2" in out and "<!--" not in out
    assert any("internal note removed" in line for line in log)


def test_a_tooltip_title_is_not_counted_so_a_comment_in_one_takes_its_words_by_decision(tmp_path):
    # Decided and final: a title is a tooltip, not text the page shows. A comment
    # inside one is removed with whatever it holds, and the copy is made.
    log = []
    out = sheafmd.render(doc(tmp_path, '[a](http://x "title <!-- KEEP1 --> t")\n'), log=log)
    assert "KEEP1" not in out and 'title="title' in out and ">a</a>" in out
    assert any("internal note removed" in line for line in log)


def test_the_refusal_of_a_swallowing_opener_names_the_opener_not_the_comment_that_closes_it(tmp_path):
    p = doc(tmp_path, "One.\n\nTwo <!-- harmless <!-- b --> comment.\n\nA <!-- x\n\nImportant ZQ-KEEP.\n\nB <!-- y -->\n")
    with pytest.raises(sheafmd.UnclosedComment) as e:
        sheafmd.render(p)
    assert e.value.line == 5


@pytest.mark.parametrize("text", [
    "One.\n\n<!-- a <!-- b -->\n\nZQ-KEEP\n",                 # one comment, whatever it holds
    "One <!-- a <!-- b --> two.\n\nZQ-KEEP\n",                  # inline, the same
    "One <!-- x\nmore\nB <!-- y --> end.\n\nZQ-KEEP\n",       # closed in its own paragraph
    "One.\n\n<!-- x\n\nBetween.\n\n<!-- y -->\n\nZQ-KEEP\n",  # at a line start it is a comment to HTML
    "One.\n\nA <!-- x\n\nZQ-KEEP\n",                           # nothing closes it later: hides nothing
])
def test_an_opener_that_pandoc_takes_for_a_comment_or_that_no_arrow_follows_is_not_refused(tmp_path, text):
    out = sheafmd.render(doc(tmp_path, text))
    assert "ZQ-KEEP" in out and "<!--" not in out


def test_the_line_is_the_one_of_the_unclosed_opener_not_of_a_closed_one(tmp_path):
    p = doc(tmp_path, "<!-- closed -->\n\n<!-- also closed\nover two lines -->\n\ntext\n\n<!-- open\n")
    with pytest.raises(sheafmd.UnclosedComment) as e:
        sheafmd.render(p)
    assert e.value.line == 8


def test_the_line_is_the_opener_pandoc_let_through_not_an_earlier_harmless_one(tmp_path):
    p = doc(tmp_path, "one\n\ntwo <!-- harmless, in running text\n\nthree\n\n<!-- the real one\n\nfour\n")
    with pytest.raises(sheafmd.UnclosedComment) as e:
        sheafmd.render(p)
    assert e.value.line == 7


def test_an_unclosed_comment_does_not_stop_the_page(tmp_path):
    p = doc(tmp_path, "one\n\n<!-- never closed\n\nthree\n")
    assert "three" in sheafmd.render(p, share=False)


def test_a_lone_closing_dash_dash_gt_does_not_make_an_opener(tmp_path):
    p = doc(tmp_path, "text --> more\n\nlast\n")
    out = sheafmd.render(p)
    assert "text" in out and "last" in out


def test_an_opener_in_code_hides_nothing_and_is_not_an_error(tmp_path):
    p = doc(tmp_path, "Start a comment with `<!--` in HTML.\n\n```html\n<!-- opens here\n```\n\nafter ZQ-KEEP\n")
    out = sheafmd.render(p)
    assert "ZQ-KEEP" in out and "<!--" not in out
    assert "&lt;!--" in out


def test_a_whole_comment_quoted_in_a_code_fence_is_removed_too(tmp_path):
    log = []
    p = doc(tmp_path, "Example:\n\n```html\n<!-- ZQ-EXAMPLE -->\n<p>x</p>\n```\n")
    out = sheafmd.render(p, log=log)
    assert "ZQ-EXAMPLE" not in out and "<p>x</p>" in out or "&lt;p&gt;x" in out
    assert any("internal note removed" in line and "ZQ-EXAMPLE" in line for line in log)


def test_a_stray_tail_is_reported_but_does_not_block(tmp_path):
    log = []
    p = doc(tmp_path, "text\n\n--> tail of a comment whose head is gone\n\nmore text\n")
    out = sheafmd.render(p, log=log)
    assert "more text" in out and "-->" not in out
    [warn] = [line for line in log if line.lstrip().startswith("!")]
    assert "line 3" in warn and "-->" in warn


def test_a_tail_inside_a_comment_is_not_a_stray(tmp_path):
    log = []
    sheafmd.render(doc(tmp_path, "text\n\n<!-- a\n--> still the comment -->\n\nend\n"), log=log)
    assert not [line for line in log if line.lstrip().startswith("!")]


# ── hostile raw HTML in the share copy ──────────────────────────────────────

HOSTILE_DOC = """# Title

<script>alert('ZQ-SCRIPT')</script>

<img src=x onerror="alert('ZQ-ONERROR')">

[click](javascript:alert('ZQ-JS')) and <a href="jav&#x09;ascript:alert(1)">tab</a>

<iframe src="https://example.com/x">ZQ-IFRAME</iframe>

<form action="https://example.com/"><button>ZQ-BUTTON</button></form>

<style>body{background:url(https://example.com/ZQ-STYLE)}</style>

<details open ontoggle="alert(1)"><summary>Sum</summary>Body text</details>

<svg onload="alert(1)"><script>alert(2)</script><text>svgword</text></svg>

<![CDATA[><script>alert(3)</script>]]>

Plain text survives.
"""


@pytest.mark.parametrize("share", [True, False])
def test_hostile_raw_html_is_sanitised_in_the_share_copy_and_in_the_page(tmp_path, share):
    out = sheafmd.render(doc(tmp_path, HOSTILE_DOC), share=share)
    for s in ("ZQ-SCRIPT", "ZQ-ONERROR", "ZQ-JS", "ZQ-IFRAME", "ZQ-BUTTON", "ZQ-STYLE", "alert(1)",
              "alert(2)", "alert(3)"):
        assert s not in out, s
    assert "Plain text survives." in out and "Body text" in out and "svgword" in out
    if share:
        assert "<script" not in out.lower()
        assert active_content(out) == []
    else:
        # the meta block and the editor, and nothing the document brought
        assert out.lower().count("<script") == 2


def test_a_javascript_link_in_markdown_keeps_its_words_and_loses_its_address(tmp_path):
    out = sheafmd.render(doc(tmp_path, "[click here](javascript:alert(1))\n"))
    assert "click here" in out and "javascript" not in out


# ── nothing a person types gets into the page unescaped ─────────────────────

def test_title_by_wordmark_tagline_footer_and_credit_are_escaped(tmp_path):
    p = doc(tmp_path, "# Hello\n\ntext\n")
    theme = Theme(name="evil", css="body{color:#000}", wordmark="<script>alert(1)</script>",
                  tagline="<img src=x onerror=alert(2)>",
                  pdf_footer='"}</style><script>alert(3)</script>')
    out = sheafmd.render(p, theme=theme, title="</title><script>alert(4)</script>",
                         by="<b onmouseover=alert(5)>", credit=True)
    assert "<script" not in out.lower()
    assert active_content(out) == []
    assert out.count("</style>") == 1 and out.count("</title>") == 1
    assert "&lt;script&gt;alert(4)" in out
    assert "Document prepared by &lt;b onmouseover" in out


def test_a_chart_cannot_carry_markup_in_its_labels(tmp_path):
    spec = {"type": "bar", "title": "<script>alert(1)</script>", "y_label": "<img src=x onerror=1>",
            "note": "</div><script>alert(2)</script>", "x": ["<script>a</script>", "b"],
            "series": [{"name": "<script>n</script>", "values": [1, 2]}]}
    import json
    out = sheafmd.render(doc(tmp_path, "```chart\n" + json.dumps(spec) + "\n```\n"))
    assert "<svg" in out
    assert "<script" not in out.lower() and active_content(out) == []


@pytest.mark.parametrize("share", [True, False])
def test_a_chart_cannot_carry_a_handler_in_its_colours_or_band_opacity(tmp_path, share):
    import json
    spec = {"type": "bar", "x": ["a", "b"], "series": [{"name": "n", "values": [1, 2]}],
            "colors": ['" onmouseover="alert(1)'],
            "bands": [{"from": 0, "to": 1, "color": 'red"><img src=x onerror=alert(2)>',
                       "opacity": '0.1" onclick="alert(3)', "label": "L"}]}
    out = sheafmd.render(doc(tmp_path, "```chart\n" + json.dumps(spec) + "\n```\n"), share=share)
    assert out.count('opacity=".88"') == 2          # the chart is still drawn
    assert "alert(" not in out
    # the page's own meta block and editor are its only scripts; the share copy has none
    assert active_content(out) == ([] if share else ["<script>", "<script>"])


def test_an_image_name_cannot_break_out_of_its_attribute(tmp_path):
    p = doc(tmp_path, '![a" onerror="alert(1)](missing "x" <b>.png)\n\n![x](ok"onerror=alert(2).png)\n')
    out = sheafmd.render(p)
    assert active_content(out) == []


# ── the order of the pipeline ───────────────────────────────────────────────

def test_sheafs_own_svg_and_images_come_after_the_sanitiser_and_survive_it(tmp_path):
    import base64
    import hashlib
    from sheafmd import paths
    mermaid_src = "graph LR\n  A-->B\n"
    key = hashlib.sha256(mermaid_src.rstrip("\n").encode()).hexdigest()[:12]    # pandoc drops the last newline
    cache = paths.cache_dir() / "mermaid"
    cache.mkdir(parents=True)
    (cache / f"{key}.svg").write_text(f'<svg id="mmd-{key}"><style>.a{{fill:red}}</style><text>node</text></svg>')
    (tmp_path / "pic.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>')
    p = doc(tmp_path, f"```mermaid\n{mermaid_src}```\n\n![pic](pic.svg)\n\n<style>.raw{{x:y}}</style>\n")
    out = sheafmd.render(p)
    assert f'<svg id="mmd-{key}"><style>.a{{fill:red}}</style>' in out      # sheaf's own <style> stays
    assert ".raw{x:y}" not in out                                           # the document's goes
    assert "data:image/svg+xml;base64," in out                              # sheaf's own data: image stays
    assert base64.b64encode(b"<svg").decode()[:4] in out


# ── the last check, on the bytes that will be sent ──────────────────────────

def test_a_sanitiser_that_failed_cannot_send_a_script(tmp_path, monkeypatch):
    monkeypatch.setattr(R.sanitizer, "sanitize", lambda frag, **kw: frag)
    with pytest.raises(sheafmd.RenderError, match="script"):
        sheafmd.render(doc(tmp_path, "<script>alert(1)</script>\n\ntext\n"))


def test_a_comment_that_got_into_the_assembled_page_is_removed_and_logged(tmp_path):
    log = []
    theme = Theme(name="t", css="/* <!-- ZQ-THEME --> */ body{margin:0}")
    out = sheafmd.render(doc(tmp_path, "text\n"), theme=theme, log=log)
    assert "ZQ-THEME" not in out and "<!--" not in out
    assert any("after assembly" in line for line in log)


def test_pandoc_output_with_a_comment_in_it_is_not_shipped(tmp_path, monkeypatch):
    real = R.pandoc_html
    monkeypatch.setattr(R, "pandoc_html", lambda text: real(text) + "<!-- ZQ-PANDOC -->")
    log = []
    out = sheafmd.render(doc(tmp_path, "text\n"), log=log)
    assert "ZQ-PANDOC" not in out
    assert any("pandoc produced an HTML comment" in line for line in log)


def test_the_share_copy_of_a_document_with_no_comment_has_none_either(tmp_path):
    out = sheafmd.render(doc(tmp_path, "# Plain\n\nJust text.\n"))
    assert "<!--" not in out and "<script" not in out


def test_the_source_file_is_not_touched(tmp_path):
    p = doc(tmp_path, secret_doc())
    before = p.read_bytes()
    sheafmd.render(p)
    sheafmd.render(p, share=False)
    assert p.read_bytes() == before
