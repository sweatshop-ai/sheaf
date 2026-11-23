"""
sheafmd.edit — pushing browser edits back into the markdown source.

sheaf renders a .md into a disposable HTML view. This module is the return
leg: it takes the HTML of the blocks the user actually touched in the browser,
converts just those back to markdown, and splices them into the source file.

The design rule is minimal contact. A pandoc html->markdown round-trip is NOT the
identity: it renormalises emphasis markers, table padding, link styles and list
bullets. So only CHANGED blocks make that trip. Everything else is written back as
the exact bytes that were read, which is what keeps chart fences, image lines,
front matter and hand-aligned tables intact when you edit one paragraph elsewhere.
"""

import contextvars
import difflib
import os
import re
from collections import Counter
from functools import cached_property, lru_cache
from html import escape as html_escape, unescape as html_unescape
from types import SimpleNamespace
from typing import NamedTuple

from . import _pandoc
from . import comments as rdc
from . import copyblock, diagnostics, orderedtask
from .blocks import LOCKED_KINDS, split_md_blocks
from .sanitize import _url_ok, sanitize


class EditError(Exception):
    pass


# Transforms sheaf applies on the way out that must be undone on the way
# back in, or the markdown would inherit presentation artefacts.
def _sanitize(fragment: str, source=None, strays=None, comments=frozenset()) -> str:
    """`source`, the block's markdown, and `strays`, a list, are for a save: markup the browser wrote that the
    source did not have is unwrapped, and each one is named in `strays`. `comments` are the placeholders of the
    block's comments (`_convert_with_comments`)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(fragment, "html.parser")

    # Rendering-only wrappers and artefacts of edit mode itself
    for div in soup.select("div.tblwrap"):
        div.unwrap()
    _lines_as_paragraphs(soup)
    _lines_as_items(soup, comments)
    _drop_empty_task_items(soup)
    if source is not None:
        _unwrap_strays(soup, source, strays)
    for el in soup.select("[contenteditable]"):
        del el["contenteditable"]
    for el in soup.select(f".rd-lock, .rd-blockmark, .{copyblock.BUTTON_CLASS}"):
        el.decompose()
    # The byline under the title shares the title's block on the page; it is drawn
    # from --by, never from the .md, so an edited title must not carry it back.
    for el in soup.select("p.doc-by"):
        el.decompose()

    # linkify_paths() turned bare absolute paths into <a class=filelink>. Left alone
    # they would come back as [/home/x](file:///home/x) and permanently rewrite the
    # source into link syntax it never had.
    for a in soup.select("a.filelink"):
        a.replace_with(a.get_text())

    # Our own heading ids/classes are generated, not authored.
    for h in soup.find_all(re.compile(r"^h[1-6]$")):
        for attr in ("id", "class"):
            if attr in h.attrs:
                del h[attr]

    for el in soup.find_all(True):
        for attr in list(el.attrs):
            if attr.startswith("data-"):
                del el[attr]

    return str(soup)


# Where a save is made, for the row it writes when it unwraps: the hub sets it around the write.
DOC = contextvars.ContextVar("sheaf_edit_doc", default=None)


def _page_own(el) -> bool:
    """Markup the page itself writes: a comment's anchor (data-rd-), the table wrapper, an `rd-` class, a math span."""
    cls = el.get("class") or []
    return (any(a.startswith("data-rd-") for a in el.attrs) or "tblwrap" in cls or "math" in cls
            or any(c.startswith("rd-") for c in cls))


def _unwrap_strays(soup, source: str, strays) -> None:
    """Markup the browser wrote that the source block did not have is no part of the markdown: a <div> that
    _lines_as_paragraphs did not reach, a <span style> left by a merge of two paragraphs, and what a paste
    brings (a mail client's styled <div> and <span>, a word processor's <b style="font-weight:normal">, a web
    page's classes). Pandoc would keep each as raw HTML, and a block with raw HTML is one the page cannot edit
    again. A <div>, a <span> and a <b> that says it is not bold are unwrapped; a style, and on a link a class,
    a target and a rel, are dropped; a <span> styled bold or italic becomes a <strong> or an <em>, and a <br> beside a block
    is dropped. What the block's source had stays as it is, in the same number and with
    the same attributes. The page's own markup (`_page_own`) is left alone."""
    from bs4 import BeautifulSoup

    def key(el):
        return (el.name, tuple(sorted((k, str(v)) for k, v in el.attrs.items())))

    had = Counter(key(el) for el in BeautifulSoup(source, "html.parser").find_all(True))
    pasted_marks = {}   # the marks `_styled_marks` made, by id: a span that says normal inside one ends it
    new_br = set()      # the <br> the source did not have: two in a row make a paragraph break (`_split_at_double_breaks`)
    for el in soup.find_all(True):
        if _page_own(el):
            continue
        k = key(el)
        if had[k] > 0:
            had[k] -= 1
            continue
        if el.name == "br":
            new_br.add(id(el))
        plain_b = el.name in ("b", "strong") and _weight(el.get("style", "")) is False
        if el.name == "br" and _beside_a_block(el):
            # An empty line a paste writes as a <br> beside a paragraph is no line of the markdown:
            # pandoc would write it as a paragraph holding a lone backslash.
            el.decompose()
            if strays is not None:
                strays.append("br")
            continue
        if el.name == "span":
            _styled_marks(soup, el, pasted_marks)
        if el.name in ("div", "span") or plain_b:
            if el.name == "div":
                # A line: its words stay apart from the text around it. A block beside it keeps them apart already:
                # a break there ends no line, and pandoc would write it as a lone backslash.
                prev, nxt = el.previous_sibling, el.next_sibling
                if prev is not None and getattr(prev, "name", None) not in ("br", *_BLOCKS) and str(prev).strip():
                    el.insert_before(soup.new_tag("br"))
                if nxt is not None and getattr(nxt, "name", None) not in ("br", *_BLOCKS) and str(nxt).strip():
                    el.insert_after(soup.new_tag("br"))
            el.unwrap()
            if strays is not None:
                strays.append(el.name)
            continue
        # A table's alignment is a style on its cells, and the one place a style is markdown.
        drop = [a for a in ("style", "class", "target", "rel")
                if a in el.attrs and (a == "style" or el.name == "a")
                and not (a == "style" and el.name in ("table", "thead", "tbody", "tr", "th", "td", "col", "colgroup"))]
        for a in drop:
            del el[a]
        if drop and strays is not None:
            strays.append(el.name)
    _split_at_double_breaks(soup, new_br)


def _split_at_double_breaks(soup, new_br) -> None:
    """Two <br> in a row, none of them in the source, inside a paragraph with words on both sides (an online word
    processor's Shift+Enter twice, each <br> in a span of its own): a blank line, so the paragraph is two. Pandoc
    would write them as two lines of a lone backslash. One <br> stays a line break."""
    def blank(c):
        return getattr(c, "name", None) is None and not str(c).strip()

    for p in soup.find_all("p"):
        if _page_own(p):
            continue
        while True:
            kids = list(p.children)
            run, first_br = [], None
            for k, c in enumerate(kids):
                if getattr(c, "name", None) == "br" and id(c) in new_br:
                    if first_br is None:
                        first_br = k
                    run.append(k)
                elif blank(c) and first_br is not None:
                    continue
                elif first_br is not None and len(run) >= 2:
                    break
                else:
                    run, first_br = [], None
            else:
                if len(run) < 2:
                    break
            if len(run) < 2 or not any(_shows(str(c)) or getattr(c, "name", None) in ("img", "a", "b", "i", "strong", "em", "code")
                                        for c in kids[:first_br]) or run[-1] + 1 >= len(kids) or all(blank(c) for c in kids[run[-1] + 1:]):
                break
            tail = soup.new_tag("p")
            for c in kids[run[-1] + 1:]:
                tail.append(c.extract())
            for c in kids[first_br:run[-1] + 1]:
                c.extract()
            p.insert_after(tail)
            p = tail


_BLOCKS = ("p", "div", "ul", "ol", "li", "blockquote", "pre", "table", "hr", "h1", "h2", "h3", "h4", "h5", "h6")


def _beside_a_block(br) -> bool:
    """Whether a <br> has a block on a side, past any more <br> and white space: a break there ends no line."""
    def block_on(step):
        el = getattr(br, step)
        while el is not None and (getattr(el, "name", None) in ("br", "meta") or not getattr(el, "name", None) and not str(el).strip()):
            el = getattr(el, step)
        return getattr(el, "name", None) in _BLOCKS

    return block_on("next_sibling") or block_on("previous_sibling")


_HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")     # a heading is bold already: a bold span in one takes no <strong>


def _declarations(style: str) -> dict:
    """A style attribute as {property: value}, both lowercase, `!important` dropped: `--font-weight:bold`, a custom
    property, is no `font-weight`, and a declaration's words inside another's value are no declaration."""
    out, parts, quote, start = {}, [], None, 0
    for k, ch in enumerate(style):
        if quote:
            quote = None if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch == ";":
            parts.append(style[start:k])
            start = k + 1
    parts.append(style[start:])
    for d in parts:
        prop, colon, value = d.partition(":")
        if colon:
            out[prop.strip().lower()] = value.lower().replace("!important", "").strip()
    return out


def _weight(style: str):
    """True when the style says bold, False when it says a normal weight, None when it says neither."""
    v = _declarations(style).get("font-weight")
    if not v:
        return None
    if v in ("bold", "bolder") or re.fullmatch(r"[6-9]00", v):
        return True
    if v in ("normal", "lighter") or re.fullmatch(r"[1-5]00", v):
        return False
    return None


def _slant(style: str):
    """True when the style says italic, False when it says upright (`normal`), None when it says neither."""
    v = _declarations(style).get("font-style")
    if not v:
        return None
    if v == "italic" or v.split()[0] == "oblique":
        return True
    return False if v == "normal" else None


_LIFTS_THROUGH = ("span", "strong", "em", "b", "i")    # what a mark may be ended across: never a link, code or a block


def _liftable(node, mark) -> bool:
    """Whether every element between `node` and `mark` is a span or a mark, none of them the page's own: anything else
    (a link, code, a block, a note) would be cut in two, so the words stay marked as before."""
    el = node.parent
    while el is not mark:
        if el.name not in _LIFTS_THROUGH or _page_own(el):
            return False
        el = el.parent
    return True


def _breaks_out(mark, side: str) -> None:
    """The <br> at the `side` ("last" or "first") end of `mark`, however deep, put just outside it: a break left
    before a closing `**` is written as a backslash that escapes it."""
    while True:
        el = mark
        while getattr(el, "name", None) not in (None, "br") and el.contents:
            el = el.contents[-1 if side == "last" else 0]
        if getattr(el, "name", None) != "br":
            return
        (mark.insert_after if side == "last" else mark.insert_before)(el.extract())


def _lift_out(soup, node, mark, pasted_marks: dict) -> None:
    """`node` taken out of `mark`, which ends before it and starts again after it; the spans between the two stay
    around `node` and around what was on either side of it (`_liftable`). A copy of a mark in `pasted_marks` is in it
    too. A <br> at either cut goes outside the mark."""

    def copy(el):
        new = soup.new_tag(el.name, attrs=dict(el.attrs))
        if id(el) in pasted_marks:
            pasted_marks[id(new)] = new
        return new

    child = node
    while True:
        el = child.parent
        right = copy(el)
        while child.next_sibling is not None:
            right.append(child.next_sibling.extract())
        if right.contents:
            el.insert_after(right)
        child.extract()
        if el is mark:
            el.insert_after(child)
        else:
            mid = copy(el)
            mid.append(child)
            el.insert_after(mid)
        if not el.contents:
            el.extract()
        if el is mark:
            if el.parent is not None:
                _breaks_out(el, "last")
            if right.parent is not None:
                _breaks_out(right, "first")
            return
        child = mid


def _styled_marks(soup, span, pasted_marks: dict) -> None:
    """A word processor writes bold and italic as a <span> with a style, and no <b> or <i>: the span's words go
    inside a <strong> or an <em>, or pandoc would drop the style and the words would lose it. Inside a mark of the
    same kind the words are marked already, and a heading's are bold already. A span that says normal inside a mark
    made here (`pasted_marks`) ends that mark around its words, as its own style wins on the page; an authored mark and a
    heading stay as they are."""
    style = span.get("style", "")
    for says, name, same in ((_slant(style), "em", ("em", "i")),
                             (_weight(style), "strong", ("strong", "b", *_HEADINGS))):
        mark = next((p for p in span.parents if p.name in same), None)
        if says is False and mark is not None and id(mark) in pasted_marks and _liftable(span, mark):
            _lift_out(soup, span, mark, pasted_marks)
        elif says and mark is None:
            inner = soup.new_tag(name)
            for c in list(span.contents):
                inner.append(c.extract())
            span.append(inner)
            pasted_marks[id(inner)] = inner     # held, so no later tag takes its id


def _trim_lead(li, skip: int) -> None:
    """The breaks, white space and empty marks that open an item, after its first `skip` children (the box),
    gone, in the first mark too (`<em><br>words</em>`): pandoc would write a box with nothing after it as a
    character, and a break that opens a mark as a backslash on a line of its own."""
    from bs4 import NavigableString

    def kept(el):
        # the page's own markup (a comment's anchor) stays, empty or not, and what follows it is looked at
        return getattr(el, "name", None) is not None and _page_own(el) and not _shows(el.get_text())

    lead = li
    while True:
        start = skip if lead is li else 0
        for el in list(lead.contents)[start:]:
            if kept(el):
                continue
            empty = (getattr(el, "name", None) not in (None, "img", "input") and not _page_own(el)
                     and not _shows(el.get_text()) and not el.find("img"))
            if empty or (isinstance(el, NavigableString) and not _shows(el)):
                el.extract()
            else:
                break
        nxt = next((c for c in list(lead.contents)[start:] if not kept(c)), None)
        if getattr(nxt, "name", None) in (None, "img", "br", "input", "ul", "ol") or _page_own(nxt):
            return
        lead = nxt


def _lines_as_items(soup, comments=frozenset()) -> None:
    """Each line typed after Enter in a task item, as a task item after it. The browser writes a <div> inside
    the <li>, which pandoc would keep as raw <div> lines. The line has a box of its own; one typed as
    `- [ ] words` or `- [x] words` is that box and those words. Words after a line, outside
    any, are an item of their own, and a line with nothing in it is none. `comments` are the placeholders of the
    block's comments: one at the start of a line is not its words."""
    from bs4 import NavigableString

    comment, leading = _placeholders(comments)

    def is_line(el):
        # a line that holds a heading, a quote, code or a table stays in its item, as it did
        return (getattr(el, "name", None) == "div" and not _page_own(el)
                and not el.find(["h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "table", "hr"]))

    def shows(el):
        return _shows(el.get_text()) or el.find("img") is not None or el.find(["ul", "ol"]) is not None

    # A plain item's line stays in the item, as a break (`_unwrap_strays`): no box says it is an item of its own.
    for li in soup.find_all("li"):
        # the page renders a task item as <li><label><input>words</label></li>, in a loose list inside a <p>
        if li.select_one(":scope > input[type=checkbox], :scope > label > input[type=checkbox],"
                         " :scope > p > label > input[type=checkbox]") is None:
            continue
        # Enter may put the line inside the label or the paragraph: it, and what follows it there, go after the
        # paragraph or label, in order
        for wrap in li.find_all(["label", "p"], recursive=False):
            moved = []
            for box in wrap.find_all("label", recursive=False) + [wrap]:
                kids = list(box.children)
                first_line = next((k for k, c in enumerate(kids) if is_line(c)), None)
                if first_line is not None:
                    moved = kids[first_line:] + (list(box.next_siblings) if box is not wrap else [])
                    break
            for c in reversed(moved):
                wrap.insert_after(c.extract())
        work = [li]
        while work:
            host = work.pop(0)
            if not any(is_line(c) for c in host.children):
                continue
            made, run, seen = [], [], False

            def close():
                if run:
                    item = soup.new_tag("li")
                    for c in run:
                        item.append(c)
                    made.append(item)
                run.clear()
            # what comes before the first line stays in the item; a list or a block after a line goes
            # with the item before it
            for c in list(host.children):
                if is_line(c):
                    seen = True
                    close()
                    for para in c.find_all("p", recursive=False):
                        para.name = "div"  # a paragraph in a line is a line of its own
                    c.extract().name = "li"
                    made.append(c)
                elif seen and getattr(c, "name", None) in ("ul", "ol", "p", "blockquote", "pre", "table",
                                                           "h1", "h2", "h3", "h4", "h5", "h6"):
                    close()
                    (made[-1] if made else host).append(c.extract())
                elif seen:
                    run.append(c.extract())
            close()
            last = host
            for item in made:
                _trim_lead(item, 0)
                while getattr(next(iter(item.contents), None), "name", None) in ("ul", "ol"):
                    last.append(item.contents[0].extract())  # a list that opens a line goes under the item before
                    _trim_lead(item, 0)
                if not (any(_shows(t) for t in item.find_all(string=True) if not t.find_parent(["ul", "ol"]))
                        or item.find("img")):
                    # a line of only a list: the list goes under the item before it
                    for sub in item.find_all(["ul", "ol"], recursive=False):
                        last.append(sub.extract())
                    item.decompose()
                    continue
                first = next(iter(item.contents), None)
                if getattr(first, "name", None) == "input":
                    # a box in the line is the line's own, ticked or not
                    last.insert_after(item)
                    last = item
                    work.append(item)
                    continue
                # a comment anchored at the very start of the line is its token first in the text, not the line's words
                token_end = leading.match(first).end() if isinstance(first, NavigableString) else 0
                m = _TYPED_TASK.match(first, token_end) if isinstance(first, NavigableString) else None
                lead_words = ""  # the words before the first list, block or line: pandoc writes a box before one as a character
                for t in item.find_all(string=True):
                    if t.find_parent(["ul", "ol", "blockquote", "pre", "table", "div", "p"]):
                        break
                    lead_words += t
                if m and not (_shows(comment.sub("", lead_words[m.end():])) or item.find("img")):
                    # a typed box with no words after it (a comment's token is none) is words itself, as in a paragraph: an item without a box
                    last.insert_after(item)
                    last = item
                    continue
                if m:
                    first.replace_with(NavigableString(first[:token_end] + first[m.end():]))
                    _trim_lead(item, 0)  # a break after the typed box
                box = soup.new_tag("input", type="checkbox")
                if m and m.group(1) in "xX":
                    box["checked"] = ""
                item.insert(0, box)
                last.insert_after(item)
                last = item
                work.append(item)
            # an item that is only its box, as when Enter was pressed right after it, is the lines that follow
            _trim_lead(host, 1)
            if last is not host and not shows(host):
                host.decompose()


def _drop_empty_task_items(soup) -> None:
    """What the page made with Enter in a task item (it marks it `data-rd-fresh`) and nobody typed in yet is not
    saved: an item with a box and nothing that shows would be written by pandoc as the character `- ☐`. An empty
    paragraph the page made between two lists, where Enter on an empty item ended the list, goes too and the two
    lists are one again, or pandoc would put `<!-- -->` between them. Both come back when words are typed. An
    item or a paragraph that was in the file is never dropped here, however little it holds."""
    from bs4 import Comment as HtmlComment, NavigableString

    for li in soup.find_all("li", attrs={"data-rd-fresh": True}):
        # what opens the moved words: the space they were cut at, which the browser writes as a no-break space once
        # something is typed beside it, and a soft break that was in the item; neither is a word, and code keeps its own
        for d in list(li.descendants):
            if isinstance(d, HtmlComment):
                continue
            if isinstance(d, NavigableString):
                if d.find_parent("code"):
                    break
                rest = d.lstrip("\u00a0 ")
                if rest != d:
                    d.replace_with(rest)
                if rest:
                    break
            elif d.name == "br":
                d.decompose()
            elif d.name in ("img", "code", "ul", "ol"):
                break
        if li.find(["ul", "ol", "img"]):
            continue
        if not _shows("".join(t for t in li.find_all(string=True) if not isinstance(t, HtmlComment))):
            list_ = li.parent
            li.decompose()
            if list_ is not None and not list_.find("li", recursive=False):
                list_.decompose()
    for para in soup.find_all("p", attrs={"data-rd-fresh": True}):
        if para.parent is not soup or para.find("img") or _shows(para.get_text()):
            continue
        before, after = para.find_previous_sibling(), para.find_next_sibling()
        para.decompose()
        if before is not None and after is not None and before.name in ("ul", "ol") and before.name == after.name:
            for c in list(after.children):
                before.append(c.extract())
            after.decompose()


_LINE_HOSTS = re.compile(r"^(?:p|h[1-6])$")
_SPLIT = "data-rd-split"     # the page's mark on a line Enter split off inside a heading's words (SPEC 7.2)
# The shape of a shortcode that GFM's emoji extension reads as its emoji (`:b:`, `:+1:`); a lone colon is none.
SHORTCODE_RE = re.compile(r":[a-z0-9_+-]+:")
# A start tag, whose quoted values may hold a `>`; text never holds a `<` (it is `&lt;`), so no text is taken for one.
_START_TAG_RE = re.compile(r'<[A-Za-z][^\s>/]*(?:"[^"]*"|\'[^\']*\'|[^>"\'])*>')
# An attribute `_sanitize` strips from the page fragment: any `data-` one but the page's own (`data-rd-`).
_DATA_ATTR_RE = re.compile(r'\s+data-(?!rd-)[^\s=>/]+(?:\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>"\']+))?')


def strip_data_attrs(html: str) -> str:
    """`html` without the `data-` attributes of its tags that `_sanitize` strips from the page: the emoji pandoc draws
    for a shortcode (`data-emoji`), and any that raw HTML in the source carries."""
    return _START_TAG_RE.sub(lambda m: _DATA_ATTR_RE.sub("", m.group(0)), html)


def _cut(t, end: bool) -> None:
    """The text node t without the no-break space that Enter leaves at a cut, at its end (the text before the
    cut) or its start (the text after it): Enter after a space or before one leaves it so, and the .md would
    keep it. One only: another beside it was typed there."""
    if end and t.endswith("\xa0"):
        t.replace_with(t[:-1])
    elif not end and t.startswith("\xa0"):
        t.replace_with(t[1:])


def _lines_as_paragraphs(soup):
    """Each line typed after Enter in a paragraph or a heading, as a paragraph after it. The block is the
    element being edited, so the browser cannot split it, and writes every new line as a <div> with no
    attributes inside it; pandoc would keep those as raw <div> lines in the .md. A render never puts a
    <div> in a <p> or a heading. Words after such a line, outside any, go into a paragraph of their own.
    Enter at the start of a heading writes the new lines before its words: they are paragraphs above it,
    and the words stay the heading. A line the page marks `data-rd-split` (Enter inside the heading's words,
    not at their end) is the heading's second half: a heading of the same level, unless it has no words."""
    from bs4 import NavigableString

    def is_line(el):
        if getattr(el, "name", None) != "div":
            return False
        if not el.has_attr(_SPLIT):
            return not _page_own(el)
        mark = el.attrs.pop(_SPLIT)          # the page's own mark on a line the browser wrote
        try:
            return not _page_own(el)
        finally:
            el[_SPLIT] = mark

    def blank(el):
        return isinstance(el, NavigableString) and not el.strip()

    def trim(el, end):
        # Only the cut: a no-break space at the start of the paragraph, at the end of its last line or in code
        # was typed there.
        words = [t for t in el.find_all(string=True) if type(t) is NavigableString]
        if words and not (words[-1] if end else words[0]).find_parent("code"):
            _cut(words[-1] if end else words[0], end)

    def lines_of(line):
        # Enter or Shift+Enter inside a line that is already a <div> nests the next one in it. The line's own
        # words are a line, each nested line follows it, and words after a nested line are another.
        pieces, run = [], []          # runs of the line's own children (lists), and the nested lines between them
        for c in list(line.children):
            c.extract()
            if is_line(c):
                pieces += [run, c]
                run = []
            else:
                run.append(c)
        pieces.append(run)
        out = []
        split = line.has_attr(_SPLIT)          # the line's own words carry its mark; a nested line has its own
        for piece in pieces:
            if not isinstance(piece, list):
                out.extend(lines_of(piece))
            elif any(not blank(c) for c in piece):
                d = soup.new_tag("div")
                if split:
                    d[_SPLIT] = ""
                split = False
                for c in piece:
                    d.append(c)
                out.append(d)
        return out or [line]

    for host in soup.find_all(_LINE_HOSTS):
        for line in [c for c in host.children if is_line(c)]:
            if any(is_line(c) for c in line.children):
                for flat in lines_of(line):
                    line.insert_before(flat)
                line.decompose()
        if not any(is_line(c) for c in host.children):
            continue
        kids = list(host.children)
        if host.name != "p" and all(is_line(c) or blank(c) for c in kids):
            # The heading's own words were all deleted: the half split off from them is the heading now.
            # Lines before it were typed above the heading, and stay above it.
            half = next((c for c in kids if is_line(c) and c.has_attr(_SPLIT) and c.get_text(strip=True)), None)
            if half is not None:
                half.unwrap()
                kids = list(host.children)
        # Where the host's own words start: the first child that is neither a line nor white space (0, none
        # moves, when there is no such child). The lines before them in a heading go above it. A paragraph
        # needs no such care: emptied by its lines going after it, it says nothing and drops out of the .md,
        # where a heading would stay as an empty `## `.
        words = next((k for k, c in enumerate(kids) if not (is_line(c) or blank(c))), 0)
        above = [c for c in kids[:words] if is_line(c)] if host.name != "p" else []
        for c in above:
            c.extract().name = "p"
            del c[_SPLIT]
            host.insert_before(c)
        last, loose, made = host, None, above + [host]
        for c in list(host.children):
            if is_line(c):
                half = bool(host.name != "p" and c.has_attr(_SPLIT) and c.get_text(strip=True))
                c.extract().name = host.name if half else "p"
                del c[_SPLIT]
                last.insert_after(c)
                last, loose = c, None
                made.append(c)
            elif last is not host:
                if loose is None:
                    loose = soup.new_tag("p")
                    last.insert_after(loose)
                    last = loose
                    made.append(loose)
                loose.append(c.extract())
        for a, b in zip(made, made[1:]):
            trim(a, end=True)
            trim(b, end=False)
        if host.has_attr("data-rd-fresh"):
            # lines typed in a paragraph the page made are the page's too: empty, they are dropped like it
            for m in made:
                m["data-rd-fresh"] = ""
    # A mark the loop did not reach (a split line pasted into a list item) is the page's, and no part of the .md: the
    # line is then a <div> the browser wrote, as if unmarked.
    for el in soup.find_all(attrs={_SPLIT: True}):
        del el[_SPLIT]


def _reject_irreversible(fragment: str):
    """Refuse conversions that would destroy the source rather than edit it."""
    from bs4 import BeautifulSoup

    # In any letter case: HTML names its tags and attributes without regard to it, and the
    # page sends whatever the tab holds. The text of a block never holds a literal `<`
    # (the page's outerHTML writes `&lt;`), so a tag is looked for in the string.
    if re.search(r"<svg", fragment, re.I):
        raise EditError("block contains a rendered chart; edit the ```chart source instead")
    # An image's address is an attribute, read as the parser reads it (names in lower case,
    # entities decoded), not a stretch of the text: a paragraph that says `src='data:` is
    # words, and `data-src` is not a `src`. And it is an <img>'s: the sanitiser keeps a data
    # address only on an <img> (`_url_ok`) and drops it anywhere else, so a span that carries
    # one is words like any other.
    for el in BeautifulSoup(fragment, "html.parser").find_all("img"):
        src = el.get("src")
        if isinstance(src, str) and re.sub(r"[\x00-\x20\x7f]+", "", src).lower().startswith("data:"):
            raise EditError("block contains an embedded image; edit the image line in the .md")
    if re.search(r"<figure", fragment, re.I):
        raise EditError("block is a figure; edit the image line in the .md")


def _boxes_as_text(fragment: str) -> str:
    """A task box as the ☐ or ☒ character pandoc's html reader turns back into
    `[ ]` or `[x]`. Left as an <input>, pandoc drops it: editing one word of a
    checklist used to strip every box from the list."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(fragment, "html.parser")
    boxes = soup.select('input[type="checkbox"]')
    if not boxes:
        return fragment
    for el in boxes:
        el.replace_with(("☒" if el.has_attr("checked") else "☐") + " ")
    return str(soup)


def _placeholder_alternation(tokens) -> str:
    """A pattern of any of `tokens`, which matches nothing when there are none. Only the placeholders
    `_convert_with_comments` issued for the block are its placeholders: words of their shape the text held are words."""
    return "|".join(re.escape(t) for t in sorted(tokens)) or "(?!)"


def _placeholders(tokens):
    """(a pattern of any of `tokens`, one of a run of them)."""
    one = _placeholder_alternation(tokens)
    return re.compile(one), re.compile(f"(?:{one})*")


_TYPED_TASK = re.compile(r"[-*][ \u00a0]\[([ \u00a0xX])\][ \u00a0\u200b-\u200d\u2060\ufeff]+")
_UNSEEN = re.compile(r"[\s\u200b-\u200d\u2060\ufeff]+")  # white space and the zero-width characters: nothing shows


def _shows(text: str) -> bool:
    """Is there anything in this text that a reader sees? White space and zero-width characters are not."""
    return bool(_UNSEEN.sub("", text))


def _list_beside(el, side: str):
    """The <ul> that touches `el` on that side of it, with only white space between, or None."""
    from bs4 import NavigableString

    sib = getattr(el, side)
    while isinstance(sib, NavigableString) and not sib.strip():
        sib = getattr(sib, side)
    return sib if getattr(sib, "name", None) == "ul" else None


def _typed_tasks(fragment: str, comments=frozenset()) -> str:
    """A paragraph that starts `- [ ] `, `- [x] ` or `* [ ] ` was typed as a task line: it becomes a
    list item with a box, which `_boxes_as_text` and pandoc then write as `- [ ] words`. Only a top-level
    paragraph is looked at, and only the start of its text (a comment anchored at its very start is not words):
    a code block, a quote and a `[ ]` mid-sentence are words.
    It runs before `_boxes_as_text`, which turns the boxes made here into the characters pandoc reads back.
    `comments` are the placeholders of the block's comments; a citation's is words."""
    from bs4 import BeautifulSoup, NavigableString

    comment, leading = _placeholders(comments)

    soup = BeautifulSoup(fragment, "html.parser")
    done = False
    for p in [el for el in soup.contents if getattr(el, "name", None) == "p"]:
        first = next(iter(p.contents), None)
        # a comment anchored at the very start of the line comes first in the text, as its token: it is not the line's words
        token_end = leading.match(first).end() if isinstance(first, NavigableString) else 0
        m = _TYPED_TASK.match(first, token_end) if isinstance(first, NavigableString) else None
        # words after the box, anywhere in the paragraph: a break, a comment or an empty mark is none
        if not m or not (_shows(comment.sub("", p.get_text()[m.end():])) or p.find("img")):
            continue
        first.replace_with(NavigableString(first[:token_end] + first[m.end():]))
        box = soup.new_tag("input", type="checkbox")
        if m.group(1) in "xX":
            box["checked"] = ""
        li = soup.new_tag("li")
        li.append(box)
        li.extend(list(p.contents))
        # a break or an empty mark right after the box would make pandoc write the box as a character
        _trim_lead(li, 1)
        # a list next to it in the block (the page makes one around a paragraph when Enter ends a list) takes the
        # item: a list, a paragraph and a list would be written with `<!-- -->` between them
        before, after = _list_beside(p, "previous_sibling"), _list_beside(p, "next_sibling")
        if before is not None:
            before.append(li)
            if after is not None:
                for c in list(after.find_all("li", recursive=False)):
                    before.append(c.extract())
                after.decompose()
            p.decompose()
        elif after is not None:
            after.insert(0, li)
            p.decompose()
        else:
            ul = soup.new_tag("ul")
            ul.append(li)
            p.replace_with(ul)
        done = True
    return str(soup) if done else fragment


# The elements an emptied block is still made of. A fragment of these with no text in
# it says nothing; one with an <img>, a rule or a table in it says something.
_EMPTY_SHELL = {"br", "p", "div", "span", "ul", "ol", "li", "blockquote", "b", "strong", "i",
                "em", "u", "h1", "h2", "h3", "h4", "h5", "h6"}
_BREAK_ENDS = (_EMPTY_SHELL - {"br", "span", "b", "strong", "i", "em", "u"}) | {"td", "th", "dt", "dd"}


def _ends_its_cell(br, cell) -> bool:
    """Whether a break shows nothing after it in its table cell: nothing but white space and breaks follow it there;
    a comment node is something the cell holds. The page's white space is not Python's: a no-break space shows,
    except the one Enter leaves at the cut, right after the break (also past the end of a mark the break ends). Two
    are a typed one."""
    from bs4 import NavigableString

    first = br.next_element
    for x in br.next_elements:
        if cell not in x.parents:
            return True
        if type(x) is NavigableString:
            text = x[1:] if x is first and x.startswith("\xa0") else str(x)
            if text.strip(" \t\n\r\f"):
                return False
        elif x.name != "br":
            return False
    return True


def _without_placeholder_breaks(fragment: str) -> str:
    """The fragment without the <br> a browser leaves at the end of a block, and "" when
    nothing else is left in it.

    A contenteditable block that was emptied keeps one `<br>` so that it keeps a line's
    height, and a line typed into it keeps one after the words. It shows nothing, but
    pandoc writes it as a hard break: a backslash on a line of its own, or after the last
    word. One break at the end of each block goes; a break between words is the writer's."""
    from bs4 import BeautifulSoup, NavigableString

    soup = BeautifulSoup(fragment, "html.parser")

    def block_ended_by(el):
        """The block `el` is the last thing in, or None."""
        while True:
            sib = el.next_sibling
            while isinstance(sib, NavigableString) and not sib.strip():
                sib = sib.next_sibling
            if sib is not None:
                return None
            el = el.parent
            if el is None or el.name == "[document]" or el.name in _BREAK_ENDS:
                return el

    table_is_taken = "\\" not in fragment and not SHORTCODE_RE.search(fragment)
    cleared = []
    for br in reversed(soup.find_all("br")):
        block = block_ended_by(br)
        # Python's strip() takes a no-break space for white space and the page does not: one after a break
        # in a cell is Enter's cut, and two are Enter's cut and a typed one. A break in code is the code's.
        if block is not None and block.name in ("td", "th") and not br.find_parent(["code", "pre"]):
            if table_is_taken:
                # _cell_breaks takes the table (no backslash or shortcode in it) and sorts the cut from a typed one.
                if type(br.next_sibling) is NavigableString and br.next_sibling.startswith("\xa0"):
                    continue
            elif not _ends_its_cell(br, block):
                # The table goes as raw HTML with its breaks: the typed line stays, without Enter's cut.
                for t, end in ((br.previous_sibling, True), (br.next_sibling, False)):
                    if type(t) is NavigableString:
                        _cut(t, end)
                continue
        if block is not None and not any(block is b for b in cleared):
            cleared.append(block)
            br.decompose()
    if (not soup.get_text().strip()
            and all(el.name in _EMPTY_SHELL for el in soup.find_all(True))):
        return ""
    return str(soup)


def _split_code_at_breaks(soup):
    """Chromium's Enter inside inline code in a table cell leaves a <br> in the <code>, which a cell cannot hold
    and which sent the whole table to raw HTML. The code is cut there into two spans with the break between
    them, as a break between words is. A break with nothing but white space after it in the code is the
    placeholder at its end, which stays where it is when it ends the cell too; where the cell's words go on after
    the code, it is Enter at the end of the code, and goes after it with the white space, a break in the cell."""
    from bs4 import NavigableString

    codes = soup.find_all("code")
    for code in codes:
        if not code.find_parent(["td", "th"]) or code.find_parent("pre"):
            continue
        for br in code.find_all("br", recursive=False):
            after = [x for x in br.next_siblings]
            if not any(str(x.get_text() if hasattr(x, "get_text") else x).strip(" \t\n\r\f\xa0") for x in after):
                if not _ends_its_cell(br, br.find_parent(["td", "th"])):
                    for x in reversed([br, *after]):
                        code.insert_after(x.extract())
                    break              # the breaks after it went out with it: none is the code's any more
                continue
            tail = soup.new_tag("code", attrs=code.attrs)
            for x in after:
                tail.append(x.extract())
            br.extract()
            code.insert_after(tail)
            code.insert_after(br)
            codes.append(tail)         # a second break in the same code is cut in its turn
            break


def _cell_breaks(fragment: str):
    """(the fragment with each line break in a table cell as a token, the token or None). A GFM table cell
    holds one line, so pandoc writes a table with a break in a cell as raw HTML, a block the page cannot
    edit; Enter in a cell writes one there. The token comes back as <br>, which GFM takes in a cell as it
    is. The no-break space Enter leaves at the cut goes, and a break that ends its cell shows nothing and
    goes too. A break in code is the code's."""
    from bs4 import BeautifulSoup, NavigableString

    if "<br" not in fragment:
        return fragment, None
    soup = BeautifulSoup(fragment, "html.parser")
    _split_code_at_breaks(soup)
    breaks = [br for br in soup.find_all("br") if br.find_parent(["td", "th"]) and not br.find_parent(["code", "pre"])]
    # Pandoc's writer leaves two backslashes as they are, which the .md reads as one, and takes a character
    # after one it escapes, in every cell of a table alike; and the pipe table is read with GFM's emoji
    # extension, which a raw HTML table is not, so a shortcode would show as its emoji and a later edit write
    # that in its place. A table that holds a backslash or a shortcode anywhere, in its text or in an attribute
    # (a link's address), goes as it went before, as raw HTML.
    if not breaks or "\\" in fragment or SHORTCODE_RE.search(fragment):
        return fragment, None
    # As wide as <br>, so that pandoc pads the column for what the cell will say: four characters of
    # Unicode's private use area, which no text the page sends holds by chance.
    token = next((t for t in ("".join(chr(0xE000 + 4 * k + n) for n in range(4)) for k in range(1024))
                  if t not in fragment), None)
    if token is None:
        return fragment, None
    for br in breaks:
        if _ends_its_cell(br, br.find_parent(["td", "th"])):
            # The no-break space Enter leaves at the cut ends with the break.
            if type(br.next_sibling) is NavigableString:
                _cut(br.next_sibling, False)
            br.decompose()
            continue
        for t, end in ((br.previous_sibling, True), (br.next_sibling, False)):
            if type(t) is NavigableString:
                _cut(t, end)
        br.replace_with(token)
    return str(soup), token


def _cell_code_pipes(fragment: str):
    """(the fragment with each `|` in a table cell's code as a token, the token or None). Pandoc's writer
    leaves a pipe in a cell's code bare, which ends the cell; GFM reads `\\|` there as the pipe. As wide as
    `\\|`, so that pandoc pads the column for what the cell will say."""
    from bs4 import BeautifulSoup, NavigableString

    if "|" not in fragment or "<code" not in fragment.lower():
        return fragment, None
    soup = BeautifulSoup(fragment, "html.parser")
    texts = [t for code in soup.find_all("code") if code.find_parent(["td", "th"])
             for t in _texts(code) if "|" in t]
    token = next((t for t in (chr(0xF000 + 2 * k) + chr(0xF001 + 2 * k) for k in range(1024))
                  if t not in fragment), None)
    if not texts or token is None:
        return fragment, None
    for t in texts:
        t.replace_with(NavigableString(t.replace("|", token)))
    return str(soup), token


# A backslash before the placeholder of a comment or a citation (`_convert_with_comments`) escapes what takes its place.
# A raw tag's placeholder (`_tags_as_text`) opens with `⟦`, which is not in the ASCII class here: a backslash before a tag
# keeps pandoc's own handling (pinned by the controls in tests/test_edit_backslash_placeholder.py).
def _backslash_escapes(tokens):
    """The backslashes of a text that the .md reads as escapes: before an ASCII mark, a line end or the end, or one
    of `tokens`, the placeholders of the block's comments and citations."""
    return re.compile(r"\\(?=[!-/:-@\[-`{-~\n]|\Z|" + _placeholder_alternation(tokens) + ")")


def _text_backslashes(fragment: str, tokens=frozenset()):
    """(the fragment with each backslash of its text that the .md would read as an escape as a token, the token
    or None). Pandoc's gfm writer leaves a backslash bare: two were saved as one, and one before a character
    the writer escapes swallowed that character. The token comes back as `\\\\`. A backslash before a letter,
    a digit or a space escapes nothing and stays as it is; code is the code's."""
    from bs4 import BeautifulSoup, NavigableString

    if "\\" not in fragment:
        return fragment, None
    soup = BeautifulSoup(fragment, "html.parser")
    texts = [t for t in _texts(soup) if "\\" in t and not any(
        u.name in ("code", "pre", "script", "style") for u in t.parents)]
    token = next((t for t in (chr(0xF800) + chr(0xF801 + k) for k in range(1024)) if t not in fragment), None)
    if not texts or token is None:
        return fragment, None
    escapes = _backslash_escapes(tokens)
    for t in texts:
        t.replace_with(NavigableString(escapes.sub(token, t)))
    return str(soup), token


# What GFM links again when written bare: an http(s) address with no `|`, and none of the marks it trims off the end.
_BARE_URL = re.compile(r"https?://[^|\s<>]*[^|\s<>.,:;!?*_~'\")]")


def _fresh_word(prefix: str, fragment: str, taken) -> str:
    """A word of `prefix` and random capitals that is neither in `fragment` nor in `taken`."""
    word = prefix + os.urandom(5).hex().upper()
    while word in fragment or word in taken:
        word = prefix + os.urandom(5).hex().upper()
    return word


def _bare_urls_as_words(fragment: str):
    """(the fragment with each bare URL that holds a backslash as a word, {word: the URL}). A bare URL is its own
    text and address, read as written: pandoc writes it as a link, whose label and address are read with escapes,
    and takes characters after a backslash."""
    from bs4 import BeautifulSoup

    if "\\" not in fragment:
        return fragment, {}
    soup, put = BeautifulSoup(fragment, "html.parser"), {}
    for a in soup.find_all("a", href=True):
        if _bare_url_whole(a["href"]) and "\\" in a["href"] and a.get_text() == a["href"] and not a.find_parent(["code", "pre"]) and not a.find(True):
            word = _fresh_word("RDURL", fragment, put)
            put[word] = a["href"]
            a.replace_with(word)
    return (str(soup), put) if put else (fragment, {})


# An address pandoc writes as `<address>` when it is also the link's text (probed with pandoc 3.7). A relative address
# and `mailto:` it writes as `[text](address)`, where a lone `)` ends the address. The list is the probed schemes, not
# pandoc's whole one: an address outside it goes as a word, which is right whichever way pandoc would write it.
_PANDOC_AUTOLINK = re.compile(r"(?:https?|ftp|file)://", re.I)


def _restore_dropped_hrefs(fragment: str, source, emoji=()) -> str:
    """The fragment with the address back on each link of the source the sanitiser took it from: any scheme outside
    SPEC 9.5's list (`ftp:`, also `javascript:`), so only an address the source already held, never a new one. The
    page shows such a link as its text and sends it as an `<a>` with no address; the .md keeps the address the
    source wrote, as it keeps a raw tag. The links are matched by their text, the k-th with the k-th, and only where
    the page's `<a>`s of that text line up with the source's: after one was deleted, which went is unknown, and
    each stays its text. An anchor of the source's own (`<a name>`, `<a id>`, an `<a>` with no address) takes none.
    The page sends it with its name, so that only the `<a>`s with neither line up with the links; a mounted page,
    which drops `name` (`sanitize.py`, mount mode), sends it as one of them, so that all the `<a>`s with no
    address line up with the links and anchors together. The save does not know which page sent it: an address
    goes back where one reading lines up, or both do and agree. Where only the first does on a mounted page (a
    link deleted beside a bare anchor of its text), the anchor takes the address, as before #591. `emoji` is `_emoji_as_tokens`' list, so a link's
    text reads as the source's render shows it."""
    from bs4 import BeautifulSoup

    if not source or not re.search(r"<a(?:\s[^>]*)?>", fragment):
        return fragment
    soup = BeautifulSoup(fragment, "html.parser")
    loose = [a for a in soup.find_all("a") if not a.has_attr("href")]
    unnamed = {id(a) for a in loose if not any(a.has_attr(k) for k in ("name", "id"))}
    html = _render_source(source) if unnamed else None
    if not html:
        return fragment

    def text(a):
        return emoji.token.sub(lambda m: emoji[int(m.group(1))][1], a.get_text()) if emoji else a.get_text()

    # By text, in order: the source's dropped address, or None for an anchor of its own; the page's `<a>`s.
    want, shown = {}, {}
    for a in BeautifulSoup(html, "html.parser").find_all("a"):
        if not a.has_attr("href"):
            want.setdefault(a.get_text(), []).append(None)
        elif not _url_ok(a, "href", a["href"]):
            want.setdefault(a.get_text(), []).append(a["href"])
    for a in loose:
        shown.setdefault(text(a), []).append(a)

    def named_kept(links, hrefs):
        """{page `<a>`: address} where the page kept its anchors' names, or None where that does not line up. An
        anchor deleted there takes no address, so only the unnamed `<a>`s and the links are counted."""
        bare, dropped = [a for a in links if id(a) in unnamed], [h for h in hrefs if h is not None]
        if len(bare) != len(dropped):
            return None
        return {id(a): h for a, h in zip(bare, dropped)}

    def names_dropped(links, hrefs):
        """{page `<a>`: address} where a mounted page sent its anchors bare, or None where that does not line up."""
        if len(links) != len(hrefs) or any(h is not None and id(a) not in unnamed for a, h in zip(links, hrefs)):
            return None
        return {id(a): h for a, h in zip(links, hrefs) if h is not None}

    put = False
    for words, links in shown.items():
        hrefs = want.get(words, [])
        readings = [r for r in (named_kept(links, hrefs), names_dropped(links, hrefs)) if r is not None]
        if not readings or any(r != readings[0] for r in readings):
            continue
        for a in links:
            if id(a) in readings[0]:
                a["href"] = readings[0][id(a)]
                put = True
    return str(soup) if put else fragment


def _hrefs_as_words(fragment: str):
    """(the fragment with each link address pandoc would write wrong as a word, {word: the address}). Pandoc's
    writer leaves an address as it is, so a backslash in it reads back as an escape and a `)` it does not balance
    ends it. An address with white space or a bracket is left to pandoc, which writes it between `<` and `>`."""
    from bs4 import BeautifulSoup

    def unbalanced(href):
        depth = 0
        for c in href:
            depth += (c == "(") - (c == ")")
            if depth < 0:
                return True
        return depth != 0

    if "\\" not in fragment and "(" not in fragment and ")" not in fragment:
        return fragment, {}
    soup, put = BeautifulSoup(fragment, "html.parser"), {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(r"[\s<>]", href) or not ("\\" in href or unbalanced(href)) or a.find_parent(["code", "pre"]):
            continue
        if "\\" not in href and a.get_text() == href and not a.find(True) and _PANDOC_AUTOLINK.match(href):
            continue                    # pandoc writes it as `<address>`, which takes no escape and holds the `)`
        word = _fresh_word("RDHREF", fragment, put)
        put[word] = href
        a["href"] = word
    return (str(soup), put) if put else (fragment, {})


# A bare URL that may end in a `)` GFM keeps.
_BARE_URL_PAREN = re.compile(r"https?://[^|\s<>]*\)")


def _bare_url_whole(url: str) -> bool:
    """Whether GFM links all of `url` when it is written bare. With a parenthesis in it, pandoc is asked: which `)` it
    keeps is not a count of parentheses (after `(*` it keeps one no `(` balances, after `)*(` it ends the URL before
    the `)`; ticket 183 BB, probed with pandoc 3.7). A failed run refuses the save (EditError) and is not remembered."""
    if "(" not in url and ")" not in url:
        return bool(_BARE_URL.fullmatch(url))
    if not (_BARE_URL.fullmatch(url) or _BARE_URL_PAREN.fullmatch(url)):
        return False
    try:
        return _pandoc_links_bare(url)
    except _Unread:
        raise EditError(f"pandoc: whether {url} is one link could not be looked up") from None


@lru_cache(maxsize=256)
def _pandoc_links_bare(url: str) -> bool:
    """Whether pandoc's GFM reader makes all of `url`, written bare at the end of a line, one link of that address.
    A failed run raises `_Unread`, which is not cached (ticket 183 BT): a guess would let the save rewrite the
    URL's text, and remembering it would do so for every later save."""
    r = _pandoc.run(["-f", "gfm", "-t", "html5", "--wrap=none"], f"x {url}\n")
    if r.returncode != 0:
        raise _Unread
    m = re.fullmatch(r'<p>x <a href="([^"]*)">([^<]*)</a></p>\s*', r.stdout)
    return m is not None and html_unescape(m.group(1)) == url == html_unescape(m.group(2))


def _gfm_domain(url: str) -> bool:
    """Whether GFM takes the domain of the bare `url` for one: at least one period, and no underscore in its last two
    labels. GFM's domain ends at the first character other than a letter, a digit, `_`, `-` or `.`. `url` holds
    `://`, as every match of `_BARE_URL` does."""
    labels = re.match(r"[^:]*://([A-Za-z0-9_.-]*)", url).group(1).split(".")
    return len(labels) > 1 and "_" not in "".join(labels[-2:])


def _gfm_links_bare(out: str, start: int, end: int, url: str) -> bool:
    """Whether `url`, written bare at out[start:end], is a link of that address in GFM: only at the start of a
    line, after white space, `*`, `_`, `~` or `(`, with a domain GFM takes (`_gfm_domain`), and whole, up to white
    space or a tag after the marks GFM trims off its end."""
    if not _bare_url_whole(url) or not _gfm_domain(url) or (start and out[start - 1] not in " \t\n*_~("):
        return False
    marks = ".,:!?*_~" if "(" in url else ".,:!?*_~)"
    return re.match(rf"[{re.escape(marks)}]*(?:\s|<|$)", out[end:]) is not None


# A shortcode drawn as its emoji: the name is in `data-emoji`, the emoji itself is the span's text.
_EMOJI_SPAN = re.compile(r'<span\b(?=[^>]*\sclass="emoji")[^>]*?\sdata-emoji="([a-z0-9_+-]+)"[^>]*>([^<]*)</span>')
# The characters an emoji token is written between, the first the fragment does not hold: the others of the private
# area the save uses are `_CODE_LT`, `_LITERAL_COLON` and `_LINE_MARKS`.
_EMOJI_MARKS = ("\uF8FE", "\uF8FF", *(chr(c) for c in range(0xF8FA, 0xF8EF, -1)))


@lru_cache(maxsize=256)
def _emoji_looked_at(name: str):
    r = _pandoc.run(["-f", "gfm", "-t", "html5"], f":{name}:")
    if r.returncode != 0:
        raise _Unread                   # an exception is not cached: a failed run must not make the name no emoji
    m = _EMOJI_SPAN.search(r.stdout)
    return m.group(2) if m else None


def _emoji_drawn(name: str):
    """The emoji pandoc draws for `:name:`, or None when it draws none. A failed run is not remembered, and refuses
    the save (EditError), as any pandoc failure of an edit does: a guess would write a shortcode the page shows as
    text bare, or one it shows as its emoji as the character."""
    try:
        return _emoji_looked_at(name)
    except _Unread:
        raise EditError(f"pandoc: the emoji of :{name}: could not be looked up") from None


_emoji_drawn.cache_clear = _emoji_looked_at.cache_clear


class _Emoji(list):
    """`_emoji_as_tokens`' (name, emoji) pairs, and `token`, the pattern of their tokens in the fragment."""
    token = None


@lru_cache(maxsize=256)
def _source_emoji(source: str) -> dict:
    """{name: [True for an emoji the source wrote as `:name:`, False for one it wrote as an HTML span, in order]}, read
    from pandoc's own parse of the source, the one the page is drawn from: a shortcode it draws is a Span of class
    `emoji`, an authored span is raw HTML, and code, comments, attributes and escaped text hold none."""
    import json

    from bs4 import BeautifulSoup

    r = _pandoc.run(["-f", "gfm", "-t", "json"], orderedtask.hide(copyblock.hide(source)))
    if r.returncode:
        # Refused, as `_emoji_looked_at` refuses: an empty answer would write every shortcode as its emoji.
        raise EditError("pandoc: the emoji of the block could not be read")
    found = {}

    def walk(x):
        if isinstance(x, list):
            for y in x:
                walk(y)
        elif isinstance(x, dict):
            t, c = x.get("t"), x.get("c")
            if t == "Span" and "emoji" in c[0][1] and (name := dict(c[0][2]).get("data-emoji")):
                found.setdefault(name, []).append(True)
            elif t in ("RawInline", "RawBlock") and c[0] == "html":
                # The spans `_EMOJI_SPAN` takes on the page: class exactly `emoji`, a name of its characters.
                for tag in BeautifulSoup(c[1], "html.parser", multi_valued_attributes=None).find_all("span"):
                    name = tag.get("data-emoji") or ""
                    if tag.get("class") == "emoji" and re.fullmatch(r"[a-z0-9_+-]+", name):
                        found.setdefault(name, []).append(False)
            walk(c)

    walk(json.loads(r.stdout).get("blocks", []))
    return found


def _emoji_as_tokens(fragment: str, source):
    """(the fragment with each emoji span the source wrote as `:name:` as a token, a `_Emoji` of (name, emoji)
    pairs). A token, not the shortcode: `_cell_breaks` sends a table holding a shortcode to raw HTML, which shows it
    as text. Which span the source wrote as `:name:` goes by its order among the source's emoji of that name: where
    the source wrote them all as shortcodes, every span; where it wrote them as HTML, or as both and the page added
    or deleted one (which, is unknown), none. A span whose text is no longer its emoji has its words kept."""
    names = _Emoji()
    mark = next((c for c in _EMOJI_MARKS if c not in fragment), None)
    if mark is None:
        return fragment, names
    names.token = re.compile(f"{mark}([0-9]+){mark}")
    on_page = Counter(m.group(1) for m in _EMOJI_SPAN.finditer(fragment))
    wrote = _source_emoji(source) if source is not None and on_page else None
    seen = Counter()

    def token(m):
        name = m.group(1)
        nth, seen[name] = seen[name], seen[name] + 1
        if wrote is not None:
            shortcode = wrote.get(name, [])            # per emoji of this name in the source: written as :name:?
            mixed = any(shortcode) and not all(shortcode)
            aligned = len(shortcode) == on_page[name]  # the page's nth emoji of the name is the source's nth
            if not any(shortcode) or mixed and not (aligned and shortcode[nth]):
                return m.group(0)
        if m.group(2) != _emoji_drawn(name):
            return m.group(0)
        names.append((name, m.group(2)))
        return f"{mark}{len(names) - 1}{mark}"

    return _EMOJI_SPAN.sub(token, fragment), names


_SHORTCODE_TEXT = re.compile(r":([a-z0-9_+-]+):")
_LITERAL_COLON = "\uF8FD"


def _in_code(t) -> bool:
    """Whether the text node t is in code or math, where GFM draws no shortcode and a backslash escapes nothing."""
    return any(u.name in ("code", "pre", "script", "style") or "math" in (u.get("class") or []) for u in t.parents)


def _shortcode_texts(soup) -> list:
    """The text nodes of soup in which GFM would draw a shortcode: not code, not math."""
    return [t for t in _texts(soup) if ":" in t and not _in_code(t)]


# A shortcode the source writes as text, `\:name:`.
_ESCAPED_SHORTCODE = re.compile(r"\\:([a-z0-9_+-]+):")
# The diff of `_source_literals` keeps this many characters of the common start and end on each side of the part
# that changed, so that a literal next to the change is still placed by its neighbours; a shortcode name is shorter.
_DIFF_MARGIN = 32
# The most characters squared the diff of `_source_literals` takes (`SequenceMatcher` is quadratic): about 20 ms
# of CPU, measured. A larger changed part is placed by order (`_places_by_order`).
_DIFF_BOUND = 2_000_000


def _places_by_order(old: str, new: str, olds) -> set:
    """The places in `new` of the literals `olds`, (place in `old`, name) pairs, by order: the k-th `:name:` of
    `old` is the k-th of `new` where both hold as many of that name. Where they do not, every `:name:` of `new`
    stays text: a shortcode the reader typed then shows as its words, rather than one the source wrote as text
    as its emoji. Linear, for a changed part too long to diff."""
    def starts(text):
        by_name = {}
        for m in _SHORTCODE_TEXT.finditer(text):
            by_name.setdefault(m.group(1), []).append(m.start())
        return by_name

    was, now, places = starts(old), starts(new), set()
    for start, name in olds:
        before, after = was.get(name, []), now.get(name, [])
        if len(before) == len(after) and start in before:
            places.add(after[before.index(start)])
        else:
            places.update(after)
    return places


def _source_literals(source: str, new: str) -> set:
    """The places in `new`, the page's shortcode text, of each `:name:` that the source wrote as `\\:name:`: its
    render shows that one as text, and a diff of the render's text against the page's carries it over. By place,
    not by name: a `:name:` the reader typed beside one the source escapes is the emoji. The common start and end
    are matched as they are and only the part between them is diffed, up to `_DIFF_BOUND`; past it, that part is
    placed by order (`_places_by_order`). A render that fails refuses the save (EditError), rather than guess."""
    from bs4 import BeautifulSoup

    html = _render_source(source)
    if html is None:
        raise EditError("pandoc: the block's source could not be rendered to place its shortcodes")
    old = "".join(_shortcode_texts(BeautifulSoup(html, "html.parser")))
    olds = [m for m in _SHORTCODE_TEXT.finditer(old) if f"\\:{m.group(1)}:" in source]
    if not olds:
        return set()
    head = len(os.path.commonprefix([old, new]))
    tail = len(os.path.commonprefix([old[head:][::-1], new[head:][::-1]]))
    head, tail = max(0, head - _DIFF_MARGIN), max(0, tail - _DIFF_MARGIN)
    for m in olds:              # no literal is cut between the common start or end and the part between them
        if m.start() < head < m.end():
            head = m.start()
        if m.start() < len(old) - tail < m.end():
            tail = len(old) - m.end()
    old_end, new_end = len(old) - tail, len(new) - tail     # the changed part is old[head:old_end], new[head:new_end]
    blocks, places = [(0, 0, head), (old_end, new_end, tail)], set()
    if (old_end - head) * (new_end - head) <= _DIFF_BOUND:
        blocks += [(a + head, b + head, size) for a, b, size in difflib.SequenceMatcher(
            None, old[head:old_end], new[head:new_end], autojunk=False).get_matching_blocks()]
    else:
        places = {head + x for x in _places_by_order(old[head:old_end], new[head:new_end], [
            (m.start() - head, m.group(1)) for m in olds if head <= m.start() and m.end() <= old_end])}
    for a, b, size in blocks:
        places.update(b + m.start() - a for m in olds if a <= m.start() and m.end() <= a + size)
    return places


_INLINE_TAGS = frozenset({"a", "abbr", "b", "cite", "del", "em", "i", "ins", "kbd", "mark", "q", "s", "small", "span",
                          "strong", "sub", "sup", "u"})


def _typed_slash_before(t, slash: str) -> bool:
    """Whether the text right before the text node t, with only inline tags between them, ends with the backslash
    token `slash` and is not code: a backslash typed in another text node than the shortcode at t's start (an
    `<em>\\</em>:smile:`). A break, an image or the start of a block between them is no such backslash."""
    from bs4 import Comment, NavigableString, Tag

    for el in t.previous_elements:
        if isinstance(el, Tag):
            if el.name not in _INLINE_TAGS:
                return False
        elif isinstance(el, NavigableString) and not isinstance(el, Comment) and str(el):
            return str(el).endswith(slash) and not _in_code(el)
    return False


def _literal_shortcodes(fragment: str, source, slash):
    """(the fragment with a mark before each `:name:` of its text that must stay text, whether it marked any). The
    page shows such a shortcode as the words it is; written bare, the next render would draw its emoji. That is one
    the source wrote as `\\:name:` (`_source_literals`), and one right after a backslash the reader typed, which
    `_text_backslashes` has made the token `slash`: the page shows that backslash, so the .md escapes it and the
    colon both, also where the backslash is in another text node (`_typed_slash_before`). A shortcode the reader
    typed bare stays bare. The source is rendered only when it escapes a name the page's text holds. Runs after
    `_text_backslashes`."""
    from bs4 import BeautifulSoup

    after_slash = slash is not None and re.search(re.escape(slash) + r"(?:<[^>]*>)*:", fragment) is not None
    escaped = bool(source) and "\\:" in source and any(
        f":{name}:" in fragment for name in set(_ESCAPED_SHORTCODE.findall(source)))
    if ":" not in fragment or _LITERAL_COLON in fragment or not (after_slash or escaped):
        return fragment, False
    soup = BeautifulSoup(fragment, "html.parser")
    texts = _shortcode_texts(soup)
    places = _source_literals(source, "".join(texts)) if escaped else set()
    found, pos = False, 0
    for t in texts:
        glued = after_slash and _typed_slash_before(t, slash)     # a typed backslash ends the text before t

        def mark(m, pos=pos, glued=glued):
            typed = slash is not None and (m.string.endswith(slash, 0, m.start()) or (glued and m.start() == 0))
            if (typed or pos + m.start() in places) and _emoji_drawn(m.group(1)):
                return _LITERAL_COLON + m.group(0)
            return m.group(0)

        pos, new = pos + len(t), _SHORTCODE_TEXT.sub(mark, str(t))
        if new != str(t):
            t.replace_with(new)
            found = True
    return (str(soup), True) if found else (fragment, False)


_CODE_LT = "\uF8FB"
_TABLE_TAG = re.compile(r"<(?=/?table\b)")


def _code_table_tags(fragment: str):
    """(the fragment with the `<` of each `<table` or `</table` in its code and math and in a title as a token,
    whether it took any). Pandoc writes code, math and a link's title as they are, so such a `<table` would count as
    a table in `html_block_to_md`; one in other text it writes as `\\<table`, which does not count."""
    from bs4 import BeautifulSoup

    if "table" not in fragment or _CODE_LT in fragment:
        return fragment, False
    soup, found = BeautifulSoup(fragment, "html.parser"), False
    for t in _texts(soup):
        if _TABLE_TAG.search(t) and any(u.name in ("code", "pre") or "math" in (u.get("class") or [])
                                        for u in t.parents):
            t.replace_with(_TABLE_TAG.sub(_CODE_LT, str(t)))
            found = True
    for el in soup.find_all(title=_TABLE_TAG):
        el["title"] = _TABLE_TAG.sub(_CODE_LT, el["title"])
        found = True
    return (str(soup), True) if found else (fragment, False)


# The character a line's backslash is written as, the first the fragment does not hold (as `_EMOJI_MARKS`).
_LINE_MARKS = ("\uF8FC", *(chr(c) for c in range(0xF8EF, 0xF8E3, -1)))
# A line of text markdown reads as a block. Pandoc's gfm writer escapes `***`, `# x`, `> x` and a list marker at the
# start of a paragraph, but not a line of dashes (a rule, or under a line a heading), a line of `=` under a line (a
# heading), nor a list marker on a line after a break, where it starts a list (an ordered one only from 1).
_RULE_LINE = re.compile(r"-\s*-\s*-[-\s]*$")          # \s: a newline in the HTML's text is a space to pandoc
_UNDER_LINE = re.compile(r"(?:-\s*)+$|=+\s*$")
_ITEM_START = re.compile(r"[-+](?=[ \t])|0*1(?=[.)](?:[ \t]|$))")


def _line_edge(t, forward: bool):
    """What ends (forward) or starts the line at text node t: "block" (the edge of a block, or a block beside it),
    "br", or None when other text or markup is on the same line."""
    from bs4 import NavigableString

    el = t
    while True:
        sib = el.next_sibling if forward else el.previous_sibling
        while isinstance(sib, NavigableString) and not sib.strip():
            sib = sib.next_sibling if forward else sib.previous_sibling
        if sib is None:
            if el.parent is None or el.parent.name not in _INLINE_TAGS:
                return "block"
            el = el.parent
            continue
        name = getattr(sib, "name", None)
        return "br" if name == "br" else "block" if name in _BLOCKS else None


def _line_marks(fragment: str):
    """(the fragment with a token before each line of text markdown would read as a block of its own, the token or
    None when it put none). The token becomes the backslash that keeps the line its text (`html_block_to_md`): a line of dashes typed
    after Enter is not a rule, nor one after Shift+Enter a heading, nor `- x` there a list."""
    from bs4 import BeautifulSoup

    mark = next((c for c in _LINE_MARKS if c not in fragment), None)
    if mark is None or not re.search(r"[-+=1]", fragment):
        return fragment, None
    soup, found = BeautifulSoup(fragment, "html.parser"), False
    for t in _texts(soup):
        words = str(t)
        lead = len(words) - len(words.lstrip())
        line = words[lead:]
        if not line or _in_code(t) or any(u.name == "table" for u in t.parents):
            continue
        block = next((u for u in t.parents if u.name in _BLOCKS), None)
        if block is not None and block.name in _HEADINGS:
            continue
        start = _line_edge(t, forward=False)
        if start is None:
            continue
        whole = _line_edge(t, forward=True) is not None
        cut = None
        if whole and (_RULE_LINE.match(line) or start == "br" and _UNDER_LINE.match(line)):
            cut = 0
        elif start == "br" and (m := _ITEM_START.match(line)):
            cut = m.end() if m.group(0)[0].isdigit() else 0
        if cut is not None:
            t.replace_with(words[:lead + cut] + mark + words[lead + cut:])
            found = True
    return (str(soup), mark) if found else (fragment, None)


def html_block_to_md(fragment: str, source=None, strays=None, comments=frozenset(), notes=frozenset()) -> str:
    """Convert one edited HTML block back to GitHub-flavoured markdown. With `source`, the block's markdown,
    markup the source did not have is unwrapped (`_unwrap_strays`) and named in `strays`. `comments` and `notes`
    are the placeholders `_convert_with_comments` put in the fragment for its comments and footnote citations."""
    _reject_irreversible(fragment)
    fragment, emoji = _emoji_as_tokens(fragment, source)
    fragment = copyblock.tokenize(fragment)
    # The page sends each block's outerHTML as the tab holds it, so what reaches pandoc
    # goes through the 9.5 sanitiser first: no handler, no script address, no element
    # that can run, and the .md never holds active markup a tool without a sanitiser
    # of its own would show. Task boxes and comments survive it; a paragraph typed as
    # `- [ ] words` becomes a task item (`_typed_tasks`).
    clean = _boxes_as_text(_typed_tasks(sanitize(_sanitize(fragment, source, strays, comments)), comments))
    clean = _restore_dropped_hrefs(clean, source, emoji)
    # The backslashes go first: `_without_placeholder_breaks` and `_cell_breaks` each decide whether the table is
    # one `_cell_breaks` takes, by a backslash in the fragment, and must see the same one. A bare URL is taken before
    # them, so that its backslashes stay the URL's.
    clean, urls = _bare_urls_as_words(clean)
    clean, slash = _text_backslashes(clean, comments | notes)
    clean, literal = _literal_shortcodes(clean, source, slash)
    clean = _without_placeholder_breaks(clean)
    if not clean.strip():
        return ""
    clean, marked = _line_marks(clean)
    clean, pipe = _cell_code_pipes(clean)
    cells, token = _cell_breaks(clean)
    cells, hrefs = _hrefs_as_words(cells)
    # After the words: a URL or href word is one more reason for the raw-table depth count below, which a title's
    # `<table` must not move.
    code_lt = False
    if pipe is not None or slash is not None or emoji or literal or marked or urls or hrefs:
        cells, code_lt = _code_table_tags(cells)
    r = _pandoc.run(["-f", "html", "-t", "gfm", "--wrap=none"], cells)
    if token is not None and r.returncode == 0 and r.stdout.count(token) != cells.count(token):
        # Pandoc's writer takes a character after a backslash it escapes, here one of the token's: the table goes
        # as it went before, as raw HTML, with every character of the cell. The cuts were sorted already: a break
        # that ends its cell and Enter's no-break space stay gone.
        r, token = _pandoc.run(["-f", "html", "-t", "gfm", "--wrap=none"], cells.replace(token, "<br>")), None
    if r.returncode != 0:
        raise EditError(f"pandoc: {r.stderr.strip()[:200]}")
    out = r.stdout if token is None else r.stdout.replace(token, "<br>")
    if pipe is not None or slash is not None or emoji or literal or marked or urls or hrefs:
        # A table pandoc writes as raw HTML has no cell for a bare pipe to end, and `\\|` would show; nor does
        # HTML read a backslash as an escape, nor a shortcode as its emoji.
        # Only a tag counts: a `<table` in text pandoc writes as `\\<table`, and one in code or math is a token.
        parts, depth = re.split(r"(?<!\\)(</?table\b)", out), 0
        for k, part in enumerate(parts):
            depth = depth + 1 if part == "<table" else max(0, depth - 1) if part == "</table" else depth
            if pipe is not None:
                part = part.replace(pipe, "|" if depth else "\\|")
            if slash is not None:
                part = part.replace(slash, "\\" if depth else "\\\\")
            if code_lt:
                part = part.replace(_CODE_LT, "&lt;" if depth else "<")
            if literal:
                part = part.replace(_LITERAL_COLON, "" if depth else "\\")
            if marked:
                part = part.replace(marked, "" if depth else "\\")
            if emoji:
                def shown(m, depth=depth):
                    name, drawn = emoji[int(m.group(1))]
                    return drawn if depth else f":{name}:"
                part = emoji.token.sub(shown, part)
            if depth:
                # Raw HTML links no bare URL; a link's address there is an attribute, read without escapes.
                for word, url in urls.items():
                    part = part.replace(word, f'<a href="{html_escape(url)}">{html_escape(url, quote=False)}</a>')
                for word, href in hrefs.items():
                    part = part.replace(word, html_escape(href))
            parts[k] = part
        out = "".join(parts)
    # Pandoc's gfm writer wraps every bare URL as <https://...>. GFM autolinks a bare
    # URL anyway, so the two render identically - but the angle brackets show up as
    # noise on every line of a table the moment one cell is edited. Unwrap them. The
    # scheme makes the match unambiguous against real tags. Only where GFM links it as written (`_gfm_links_bare`).
    out = re.sub(r"<(https?://[^>\s]+)>",
                 lambda m: m.group(1) if _gfm_links_bare(m.string, m.start(), m.end(), m.group(1)) else m.group(0), out)
    for word, url in urls.items():
        out = re.sub(word, lambda m, url=url: url if _gfm_links_bare(m.string, m.start(), m.end(), url) else f"<{url}>",
                     out)
    for word, href in hrefs.items():
        # An address in a link: every backslash, parenthesis and pipe escaped, so that it reads back as it is.
        out = out.replace(word, re.sub(r"([\\()|])", r"\\\1", href))
    return copyblock.restore(out).strip("\n")


def _norm_html(fragment: str) -> str:
    """Whitespace- and attribute-normalised HTML, for comparing two renders."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(fragment, "html.parser")
    for el in soup.find_all(True):
        for attr in ("id", "class"):
            if attr in el.attrs:
                del el[attr]
    return re.sub(r"\s+", " ", str(soup)).strip()


@lru_cache(maxsize=8)
def _rendered(content: str) -> str:
    r = _pandoc.run(["-f", "gfm", "-t", "html5", "--no-highlight"], orderedtask.hide(copyblock.hide(content)))
    if r.returncode != 0:
        raise _Unread                   # an exception is not cached: a timeout once must not refuse the next saves
    return orderedtask.show(r.stdout)


def _render_source(content: str, keep: bool = True):
    """Pandoc's HTML of a source, or None. A success is cached: a save asks it of the same block for `_unchanged`,
    for `_toggle_boxes` and for `ticked_html`, and a render of a long list takes seconds. The cache holds 8 renders,
    so a source rendered once to be compared and thrown away (`keep` false) must not push those out."""
    try:
        return (_rendered if keep else _rendered.__wrapped__)(content)
    except _Unread:
        return None


def _comparable(block, fragment: str):
    """(page fragment, source render) reduced to the same terms, or None."""
    html = _render_source(block.content)
    if html is None:
        return None
    # The page shows each comment as an anchor span; the source render has the
    # comment itself. Reduce both to the same marker, or every commented block
    # would look edited and go through pandoc on every save.
    src = COMMENT_HTML_RE.sub(lambda m: f"<!--RDA:{m.group(1)}-->", copyblock.mark(html, page=True))
    # A shortcode (`:100:`) renders as `<span class="emoji" data-emoji="100">`, and raw HTML may carry any data- attribute;
    # _sanitize strips them from the fragment, so the source loses them too, or a block with one never compares equal
    # and no box in it ticks.
    src = strip_data_attrs(src)
    frag = ANCHOR_RE.sub(lambda m: f"<!--RDA:{m.group(1)}-->", fragment)
    try:
        return _sanitize(frag), src
    except Exception:
        return None


def _unchanged(block, fragment: str) -> bool:
    """Does this submitted HTML still say what the source block says?

    A second opinion, independent of whatever the page believed was dirty. The page
    decides what to SEND; this decides what to WRITE. Without it, any regression in
    the browser's change detection silently rewrites untouched blocks through
    pandoc, which renumbers lists and reflows tables across the whole document.
    """
    both = _comparable(block, fragment)
    if both is None:
        return False
    try:
        return _norm_html(both[0]) == _norm_html(both[1])
    except Exception:
        return False


# ──────────────────────────────────────────────────────────── task boxes ──
# A click on a task box in the page sets or clears `checked` on its <input>, and
# the block is saved like any edit. When ticks are the only difference, the save
# does not go through pandoc: it flips the `[ ]` / `[x]` of those items in the
# source and leaves every other byte alone. Pandoc would rewrite the whole list
# (bullets, wrapping, a capital X), so one tick would touch every line. A bullet or an ordered item has a mark: pandoc 3.9
# draws a box for a bullet only, and `orderedtask` draws the one GitHub draws for `1. [ ] a`. The item may stand
# behind other markers on its line (`- - [ ] a`, `1. - [ ] a`, `1. > - [ ] a`): its box is drawn.
TASK_MARK_RE = re.compile(
    r"^([ \t]*(?:(?:[-*+]|\d{1,9}[.)])[ \t]+|>[ \t]*)*(?:[-*+]|\d{1,9}[.)])[ \t]+)\[([ xX])\](?=[ \t]|$)", re.M)


class _Mark:
    """A task mark found by `task_marks`, answering the part of `re.Match` the callers use: `start()` is the offset of
    the mark's line and `end()` that of the end of the mark (after its `]`), as for a match; `start(2)` and `end(2)`
    those of its state character, `group(2)` the character. Any other group is an error, not a wrong offset."""
    __slots__ = ("_line", "_box", "_state", "_end")

    def __init__(self, line: int, box: int, state: str, end: int):
        self._line, self._box, self._state, self._end = line, box, state, end

    def group(self, n: int) -> str:
        if n != 2:
            raise IndexError(f"a task mark has only group 2, not {n}")
        return self._state

    def start(self, group: int = 0) -> int:
        if group not in (0, 2):
            raise IndexError(f"a task mark has only group 2, not {group}")
        return self._line if group == 0 else self._box

    def end(self, group: int = 0) -> int:
        if group not in (0, 2):
            raise IndexError(f"a task mark has only group 2, not {group}")
        return self._end if group == 0 else self._box + 1   # the match ends after the `]`, the state character before it


def task_marks(content: str, pattern=TASK_MARK_RE) -> list:
    """The task marks of `content`, read as pandoc reads it: without its CRs, which it deletes, so a CR anywhere in a
    line, between the brackets too, neither hides a mark nor makes one. Offsets are in `content` itself."""
    if "\r" not in content:
        return list(pattern.finditer(content))
    keep = [i for i, ch in enumerate(content) if ch != "\r"]
    return [_Mark(content.rfind("\n", 0, keep[m.start()]) + 1, keep[m.start(2)], m.group(2), keep[m.end() - 1] + 1)
            for m in pattern.finditer(content.replace("\r", ""))]


def _drawing_marks(content: str, marks: list) -> list:
    """The marks of `marks` that pandoc probably draws a box for, read from the text alone: those with something
    after them on their line, or with an indented line under them that goes on with the item. A mark with nothing
    after it and no such line is an empty item, drawn as a bare `\u2610` or as the literal `[ ]`, not as a box. A
    guess, wrong for a few shapes (a NBSP after the mark, a quoted continuation, an empty parent over a sublist, a
    heading, fence, indented code or lazy line under the mark, raw HTML after it): a reading is only a candidate,
    and `_toggle_boxes` renders what it writes and refuses what draws other boxes, so when the readings before it
    fail, `_boxed_marks` serves at the cost of about log n renders (17 s at 4,100 items, ticket 140), never a wrong
    write."""
    keep = []
    for m in marks:
        end = m.end()
        eol = content.find("\n", end)
        if content[end:eol if eol >= 0 else len(content)].strip() or eol >= 0 and _goes_on(content, eol + 1, m.start()):
            keep.append(m)
    return keep


def _goes_on(content: str, pos: int, line: int) -> bool:
    """Is the line starting at `pos` a non-blank line indented deeper than the one starting at `line`?"""
    eol = content.find("\n", pos)
    nxt = content[pos:eol if eol >= 0 else len(content)]
    if not nxt.strip():
        return False
    indent = lambda row: len(row) - len(row.lstrip(" \t"))
    end = content.find("\n", line)
    this = content[line:end if end >= 0 else len(content)]
    return indent(nxt) > indent(this)


def _boxed_marks(content: str) -> list | None:
    """The marks of `content` laid out by the box each one flips, as the page draws them: item `k` is the mark whose
    state character flips box `k`, None for a box no mark stands for (a raw `<input>`). The regex reading counts
    marks and needs them to be the boxes one for one; this one asks the render, so an empty item (a mark, no box)
    and a box behind a chain are each told apart. The marks are numbered from 1 and, for each bit of the numbers,
    those with the bit set are flipped together and rendered: a box that moved has the bits of its mark's number,
    so about log2 of the marks renders lay them all out, not one per mark. None when the source does not render,
    when a box moves with no mark of that number, or when the states do not come back the same in number."""
    marks = task_marks(content)
    try:
        html = _render_source(content)
        if html is None:
            return None
        was = _ticks(copyblock.mark(html, page=True))[0]
        code = [0] * len(was)
        for bit in range(len(marks).bit_length()):
            out, last = [], 0
            for i, m in enumerate(marks):
                out.append(content[last:m.start(2)])
                out.append(("x" if m.group(2) == " " else " ") if (i + 1) >> bit & 1 else m.group(2))
                last = m.end(2)
            html = _render_source("".join(out) + content[last:], keep=False)
            now = None if html is None else _ticks(copyblock.mark(html, page=True))[0]
            if now is None or len(now) != len(was):
                return None
            for k, (a, b) in enumerate(zip(was, now)):
                code[k] |= (a != b) << bit
    except Exception:
        return None
    if any(c > len(marks) for c in code) or len({c for c in code if c}) != len([c for c in code if c]):
        return None
    return [marks[c - 1] if c else None for c in code]


def _readings(content: str):
    """The readings of the marks of `content` a tick may be written by, one after the other, each asked for only when
    the one before did not serve: `task_marks`, then the marks `_drawing_marks` guesses from the text, then
    `_boxed_marks` (renders) when it is none of those."""
    first = task_marks(content)
    yield first
    seen = [[m.start(2) for m in first]]
    if first and (drawn := _drawing_marks(content, first)) and [m.start(2) for m in drawn] not in seen:
        seen.append([m.start(2) for m in drawn])
        yield drawn
    if first and (boxed := _boxed_marks(content)) is not None and [m and m.start(2) for m in boxed] not in seen:
        yield boxed


def _ticks(fragment: str):
    """(box states in document order, the HTML with every box unticked)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(fragment, "html.parser")
    states = []
    for el in soup.select('input[type="checkbox"]'):
        states.append(el.has_attr("checked"))
        del el["checked"]
    return states, str(soup)


def _only_ticks(block, fragment: str):
    """(the states the page sent, its fragment unticked, the states of the source's render) when the fragment differs
    from the source's render in the ticks of its boxes and in nothing else; None otherwise."""
    both = _comparable(block, fragment)
    if both is None:
        return None
    try:
        want, frag = _ticks(both[0])
        have, src = _ticks(both[1])
        if not have or want == have or len(want) != len(have) or _norm_html(frag) != _norm_html(src):
            return None
    except Exception:
        return None
    return want, frag, have


def _toggle_boxes(block, fragment: str, marks=None):
    """The block with its task marks flipped, when the page changed nothing but
    which boxes are ticked. None otherwise, and then the edit is converted as usual.
    `marks` is one reading of the marks; none given, each of `_readings` is tried in turn. A reading may have None
    for a box no mark stands for: the page may not tick it, only leave it as it was."""
    if "checkbox" not in fragment:
        return None
    if marks is None:
        # What does not depend on the reading is judged first: a reading by box costs renders, and a text edit of a
        # block that holds boxes comes through here on every save.
        if _only_ticks(block, fragment) is None:
            return None
        return next((out for out in (_toggle_boxes(block, fragment, m) for m in _readings(block.content))
                     if out is not None), None)
    if (ticks := _only_ticks(block, fragment)) is None:
        return None
    want, frag, have = ticks
    # The marks found in the source must be the boxes the render drew, one for one (a box no mark stands for is
    # None and is left as it is), or a tick could land on the wrong line (a `- [ ]` inside a code block in the list,
    # say). Any doubt and the edit takes the general path.
    if len(marks) != len(have) or [h if m is None else m.group(2) != " " for m, h in zip(marks, have)] != have:
        return None
    out = block.content
    for m, w, h in reversed(list(zip(marks, want, have))):
        if w != h:
            if m is None:
                return None
            out = out[:m.start(2)] + ("x" if w else " ") + out[m.end(2):]
    # Equal counts and states do not make the marks the boxes: pandoc draws no box for an empty item (`- [ ]`) and
    # does draw one the marks miss (`- - [ ] x`), so a tick could still land on the wrong line. The result is
    # therefore rendered, and must draw exactly the boxes the page sent, ticked as the page sent them.
    again = _comparable(SimpleNamespace(content=out), fragment)
    if again is None:
        return None
    try:
        got, plain = _ticks(again[1])
        if got != want or _norm_html(plain) != _norm_html(frag):
            return None
    except Exception:
        return None
    return out


_BOX_NUMBERS: dict = {}
_MISS = object()
_BOX_NUMBERS_MAX = 4096


def box_number(content: str, pos: int) -> int | None:
    """The number, among the boxes the page draws for `content`, of the box whose state is the character at `pos`
    (the state character of a task mark): the one box that flips when that character does. None when none does
    (an empty item has a mark and no box) or when the source does not render. The count of marks is not this
    number: a mark may draw no box (an empty item) and a box may have no mark (a raw `<input>`), so the render
    is asked. An answer is kept by (content, pos), for the page asks it of every
    button on every serve and the render of a long list takes seconds; a render that failed is not kept."""
    if not 0 <= pos < len(content) or content[pos] not in " xX":
        return None
    key = (content, pos)
    if (kept := _BOX_NUMBERS.get(key, _MISS)) is not _MISS:      # one read: another thread may clear between two
        return kept
    flipped = content[:pos] + (" " if content[pos] != " " else "x") + content[pos + 1:]
    try:
        was, now = (_ticks(copyblock.mark(h, page=True))[0] if (h := _render_source(c)) is not None else None
                    for c in (content, flipped))
    except Exception:
        return None
    if was is None or now is None:
        return None
    moved = [i for i, (a, b) in enumerate(zip(was, now)) if a != b] if len(was) == len(now) else []
    got = moved[0] if len(moved) == 1 else None
    if len(_BOX_NUMBERS) >= _BOX_NUMBERS_MAX:
        _BOX_NUMBERS.clear()
    _BOX_NUMBERS[key] = got
    return got


def ticked_html(block, k: int, tick: bool = True, at: int | None = None):
    """The block as the page would send it with its `k`th task box ticked (unticked, with `tick` false), for a
    tick made away from the page (the list's row, SPEC 9.10): saved like the page's own, it takes the
    `_toggle_boxes` path and flips that one mark. None when the box is ticked already (unticked already), or when
    that path would not be the one taken (the marks are not the boxes drawn, a comment is in the way): a save would
    then go through pandoc. `k` counts the boxes the page draws, as `box_number` does; `at`, when given, is the
    offset of the state character of the mark the box stands for, and only a reading that has that mark as its `k`th
    is tried, so a tick cannot be written on the mark of another box."""
    from bs4 import BeautifulSoup

    if not block.editable:
        return None
    html = _render_source(block.content)
    if html is None:
        return None
    # The page shows each comment as its anchor; the anchor is what keeps the comment through a save.
    soup = BeautifulSoup(COMMENT_HTML_RE.sub(
        lambda m: f'<span class="rd-anchor" data-rd-id="{m.group(1)}"></span>', copyblock.mark(html, page=True)),
        "html.parser")
    found = soup.select('input[type="checkbox"]')
    if not 0 <= k < len(found):
        return None
    sets = (m for m in _readings(block.content)
            if k < min(len(found), len(m)) and m[k] is not None and (at is None or m[k].start(2) == at))
    if found[k].has_attr("checked") == tick:
        return None
    if tick:
        found[k]["checked"] = ""
    else:
        del found[k]["checked"]
    fragment = str(soup)
    for marks in sets:
        want = block.content[:marks[k].start(2)] + ("x" if tick else " ") + block.content[marks[k].end(2):]
        if _toggle_boxes(block, fragment, marks) == want:
            return fragment
    return None


# ─────────────────────────────────────────────── comments through a save ──
# pandoc html -> gfm drops HTML comments in silence (measured on paragraphs,
# headings, lists, tables and blockquotes), so a comment would vanish the first
# time anyone edited the sentence it is on. The page therefore turns each comment
# into an anchor span; here each anchor becomes a plain-text placeholder that
# survives pandoc, and after conversion the placeholder is replaced by the
# comment's ORIGINAL bytes, read from the source block. The page can move a
# comment or delete its anchor. It cannot change what a comment says.

ANCHOR_RE = re.compile(
    r'<span\b[^>]*\bclass="rd-anchor"[^>]*\bdata-rd-id="([^"]+)"[^>]*>[\s\S]*?</span>')
COMMENT_HTML_RE = re.compile(rf"<!--\s*{rdc.MARKER}\s+id=(\S+)[\s\S]*?-->")
RAW_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")
COMMENT_SRC_RE = re.compile(rf"<!--\s*{rdc.MARKER}\b[\s\S]*?-->")

# What to read left to right to find the comments that are comments: a fenced code
# line run (a list or a quote can hold one), an inline code span, or an HTML comment,
# whichever starts first. An HTML comment written in code is text, not a comment, and
# a backtick inside a comment is part of it.
CODE_OR_COMMENT_RE = re.compile(
    r"^[ \t>]*(?P<fence>`{3,}|~{3,})[^\n]*(?:\n[\s\S]*?^[ \t>]*(?P=fence)[`~]*[ \t]*$|[\s\S]*\Z)"
    r"|(?<!`)(?P<run>`+)(?!`)[\s\S]*?(?<!`)(?P=run)(?!`)"
    r"|<!--[\s\S]*?-->", re.M)


def _foreign_comments(content: str) -> list:
    """The HTML comments in a block's source that are not sheaf comments, in order.

    The old code took every `<!-- -->` in the text. One in a code span, or in a fence
    inside a list, never comes back from the page as a comment node, so each edit of
    that paragraph left a copy of it on its own line, a new hidden comment in the file
    every time.

    A rectoverso comment is one `comments.parse` accepted. One it refused (no id, an
    unknown status, a repeated key or id) has no anchor in the page and is nobody's
    to rewrite, so it is kept byte for byte like a comment from another tool; the
    person who must fix it is told by `sheaf comments`, and an edit of the
    paragraph beside it is no reason to delete it. Matched by occurrence, so of two
    comments with one id the first is the comment and the second is kept."""
    parsed = Counter(content[c.start:c.end] for c in rdc.parse(content).comments)
    found = []
    for m in CODE_OR_COMMENT_RE.finditer(content):
        raw = m.group(0)
        if not raw.startswith("<!--"):
            continue
        if parsed[raw]:
            parsed[raw] -= 1
            continue
        found.append(raw)
    return found


def _orphans(comments) -> str:
    """Comments whose text is gone, as standalone lines that render as nothing."""
    parts = []
    for c in comments:
        c.orphan = True
        parts.append(rdc.format(c, one_line=False))
    return "\n\n".join(parts) + "\n"


# ───────────────────────────────────────────────────── raw inline tags ──
# A paragraph can hold raw HTML between its words: `(ref <x1>)`, `<kbd>Ctrl</kbd>`,
# `<abbr title="...">`. Pandoc's HTML reader drops an element it does not know and writes
# <kbd>, <mark> and <abbr> as <span class=...>, so an edit of the paragraph took the tag
# out of the file (sheaf #155). Each element of the page that stands for a raw tag of the
# source goes through pandoc as two placeholders around its words, and the placeholders
# come back as the source's own bytes: the opening tag, and its closing tag or nothing
# when the source never closed it. What markdown itself writes (an emphasis, a link, a
# line break), the page's own spans and what the sanitiser removes are left to pandoc.
MARKDOWN_TAGS = frozenset({
    "a", "b", "blockquote", "br", "code", "del", "div", "em", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i",
    "img", "input", "li", "ol", "p", "pre", "s", "span", "strike", "strong", "table", "tbody", "td", "tfoot",
    "th", "thead", "tr", "ul",
})
TAG_RE = re.compile(r"^<(/?)([A-Za-z][A-Za-z0-9-]*)\b[^>]*?(/?)>$")


def _raw_tags(content: str):
    """The raw inline tags of a block's source, in order, as (tags, lone, doc), each tag in the source's
    bytes: `tags` holds (name, opening tag, closing tag or "", the opening tag as the page has it);
    `lone`, (closing tag, its node in `doc`) for each closing tag with no opener of its name; `doc`,
    pandoc's JSON of the block."""
    import json

    from .sanitize import ALSO_REMOVED, REMOVE

    if "<" not in content:
        return [], [], None
    r = _pandoc.run(["-f", "gfm", "-t", "json"], content)
    if r.returncode != 0:
        return [], [], None
    doc = json.loads(r.stdout)
    nodes = []

    def walk(node, in_table=False):
        if isinstance(node, dict):
            if node.get("t") == "RawInline" and node["c"][0] == "html":
                nodes.append((node, in_table))
            else:
                walk(node.get("c"), in_table or node.get("t") == "Table")
        elif isinstance(node, list):
            for x in node:
                walk(x, in_table)

    walk(doc["blocks"])
    tags, lone, open_, pos = [], [], {}, 0
    for node, in_table in nodes:
        raw = seen = node["c"][1]
        # In a table cell pandoc's RawInline has `|` where the source has `\|`, which keeps the cell
        # whole: the tag is the source's bytes. Nowhere else does pandoc take a backslash out of a tag.
        if in_table and "|" in raw:
            found = re.compile(re.escape(raw).replace("\\|", r"\\?\|")).search(content, pos)
            if found:
                raw, pos = found.group(0), found.end()
        m = TAG_RE.match(raw)
        if not m:
            continue
        closing, name, empty = m.group(1), m.group(2).lower(), m.group(3)
        if name in MARKDOWN_TAGS or name in REMOVE or name in ALSO_REMOVED:
            continue
        if closing:
            if open_.get(name):
                open_[name].pop()[2] = raw
            else:
                lone.append((raw, node))
            continue
        tag = [name, raw, "", seen]
        tags.append(tag)
        if not empty:
            open_.setdefault(name, []).append(tag)
    return [tuple(t) for t in tags], lone, doc


def _texts(soup) -> list:
    from bs4 import NavigableString

    return [t for t in soup.descendants if type(t) is NavigableString]


# Where an edit changed more words than this, a closing tag with no opener in the changed words goes
# where the change begins: a diff of a longer stretch costs seconds.
LONE_DIFF_MAX = 2000
LONE_CONTEXT = 40


class _Shift:
    """Where an offset in the text `old` lands in the text `new`, by the words around it: the same offset
    before the first change and after the last, and inside the changed part after the same words when they
    are still there, else before the words after it when those are, else after the last words before it that
    are. Where the changed part is longer than LONE_DIFF_MAX, two edits far apart, by the LONE_CONTEXT
    letters on either side of it, if they are there once; else the start of the change."""

    def __init__(self, old: str, new: str):
        self.old, self.new = old, new
        pre = 0
        while pre < min(len(old), len(new)) and old[pre] == new[pre]:
            pre += 1
        suf = 0
        while suf < min(len(old), len(new)) - pre and old[-1 - suf] == new[-1 - suf]:
            suf += 1
        self.pre, self.suf = pre, suf

    @cached_property
    def same(self) -> list:
        """The runs of letters the changed parts of `old` and `new` share, as difflib's (a, b, size), counted
        from the start of each changed part. Diffed once, and only when an offset falls inside the change."""
        old, new, pre, suf = self.old, self.new, self.pre, self.suf
        return [m for m in difflib.SequenceMatcher(None, old[pre:len(old) - suf], new[pre:len(new) - suf],
                                                   autojunk=False).get_matching_blocks() if m.size]

    def where(self, offset: int) -> int:
        """Where `offset`, a place in `old`, lands in `new`."""
        old, new, pre, suf = self.old, self.new, self.pre, self.suf
        if offset <= pre:
            return offset
        if offset >= len(old) - suf:
            return offset + len(new) - len(old)
        a0, b0, a1, b1 = pre, pre, len(old) - suf, len(new) - suf
        if max(a1 - a0, b1 - b0) > LONE_DIFF_MAX:
            # Two edits far apart: the words around it, if they are there once.
            left, right = old[max(a0, offset - LONE_CONTEXT):offset], old[offset:offset + LONE_CONTEXT]
            for ctx, off in ((left + right, len(left)), (left, len(left)), (right, 0)):
                if ctx and new.count(ctx, b0, b1) == 1:
                    return new.index(ctx, b0, b1) + off
            return pre
        # After the same words when they are still there, else before the words after it when those
        # are, else after the last words before it that are.
        offset, k = offset - a0, b0
        for a, b, n in self.same:
            if a < offset <= a + n:
                return b0 + b + offset - a
            if a + n <= offset:
                k = b0 + b + n
        return next((b0 + b for a, b, n in self.same if a == offset), k)


_ENCLOSED = ("code", "pre")
# A tag's placeholder in `_lone_as_text`, and a run of them at the start or the end of a text.
_TAG_TOKEN = "\u27e6[A-Z0-9]+\u27e7"
_LEADING_TAGS = re.compile(f"(?:{_TAG_TOKEN})+")
_TRAILING_TAGS = re.compile(f"(?:{_TAG_TOKEN})+$")


def _kept(s: str, comment_re) -> list:
    """The indices of the characters of `s` that are words, not a comment's placeholder. `comment_re` matches only
    the placeholders issued for the block: words of their shape are words (ticket 183 BC)."""
    drop = {i for m in comment_re.finditer(s) for i in range(m.start(), m.end())}
    return [i for i in range(len(s)) if i not in drop]


def _enclosing(t):
    """The outermost code, pre or math span around `t`, or None: a tag inside one would be its words."""
    up = [u for u in t.parents if u.name in _ENCLOSED or "math" in (u.get("class") or [])]
    return up[-1] if up else None


def _lone_as_text(soup, lone, doc, token, comment_re) -> dict:
    """Each closing tag of `lone` put in `soup` as a placeholder, after the words it followed in the
    source: {placeholder: the tag's bytes}. The browser drops a closing tag with no opener, so the
    page holds no element for it; its place is found in the page's words, against a render of the
    source with the tag written as its placeholder, and on the same side of the elements around it."""
    import json

    from bs4 import BeautifulSoup, Comment, NavigableString

    placed = {}
    for raw, node in lone:
        p = f"\u27e6{token()}\u27e7"
        placed[p] = raw
        node["t"], node["c"] = "Str", p
    r = _pandoc.run(["-f", "json", "-t", "html5", "--no-highlight", "--wrap=none"], json.dumps(doc))
    if r.returncode != 0:
        return {}
    src = BeautifulSoup(r.stdout, "html.parser")
    # How many comments stand between each tag and the words beside it: before it (a tag after words), or after it (a
    # tag at the start of an item or a cell, before its words). The page keeps a placeholder for each, and the tag goes
    # on its own side of them (ticket 183 BS). Tags side by side share the comments before or after the run of them.
    lead, trail = {}, {}

    def comments(sib, step):
        n = 0
        while isinstance(sib, Comment):
            n, sib = n + 1, getattr(sib, step)
        return n

    for t in src.find_all(string=lambda x: not isinstance(x, Comment)):
        for run, side, count in ((_LEADING_TAGS.match(str(t)), "previous_sibling", lead),
                                 (_TRAILING_TAGS.search(str(t)), "next_sibling", trail)):
            for q in re.findall(_TAG_TOKEN, run.group() if run else ""):
                if q in placed:
                    count[q] = comments(getattr(t, side), side)
    # A comment splits the source's words where the page has none.
    for c in src.find_all(string=lambda x: isinstance(x, Comment)):
        c.extract()
    src.smooth()
    for t in _texts(src):
        parts = [x for x in re.split(f"({_TAG_TOKEN})", str(t)) if x]
        if len(parts) > 1:
            t.replace_with(*(NavigableString(x) for x in parts))
    texts = _texts(src)
    old, sites = "", []
    for i, t in enumerate(texts):
        if str(t) not in placed:
            old += t
            continue
        # How many elements close between the words before it and the tag, or, with no words before
        # it, open between the tag and the words after it.
        ups = {id(u) for u in t.parents}
        before = next((x for x in reversed(texts[:i]) if str(x) not in placed), None)
        after = next((x for x in texts[i + 1:] if str(x) not in placed), None)
        # The line break between two blocks is not words before it, with words after it in its own block.
        if before is not None and not before.strip() and "\n" in before and after is not None and after.strip():
            before = None
        side = before if before is not None else after
        climb = sum(id(u) not in ups for u in side.parents) if side is not None else 0
        # The spaces between the words before it and the tag, in the same text.
        gap = len(before) - len(before.rstrip()) if before is not None and before.strip() else 0
        sites.append((len(old), str(t), before is not None, climb, gap))
    # A line break of the render and of the page is a space to the diff.
    old = re.sub(r"\s", " ", old)
    words = [comment_re.sub("", t) for t in _texts(soup)]
    raw = "".join(words)
    new = re.sub(r"\s", " ", raw)
    # Where one text of the page ends and the next begins: Enter puts a new item or line right after
    # the old one, with no space between their words.
    edges, cum = set(), 0
    for w in words:
        cum += len(w)
        edges.add(cum)
    where = _Shift(old, new).where

    def between_words(o, back, gap):
        # The diff matches letters: where the word before it was replaced, it can point into the new
        # word. A tag that stood between words in the source goes to the end of that word, or, with no
        # words before it, to the start of the word after it.
        # Enter after a word moves the space after it to the new line, as a no-break space: a tag
        # goes with the word before it, then over as many plain spaces as it had, on the same text.
        o -= gap
        k = where(o)
        # Two items merged with no space leave it between the same words, which are not one word to it;
        # a word that grew by the next word's letters holds them once more than the source did.
        w = re.match(r"\s*(\w+)", old[o:])
        if not (0 < o < len(old) and old[o - 1].isalnum() and old[o].isalnum()
                or w and new.startswith(w.group(1), k) and new.count(w.group(1)) <= old.count(w.group(1))):
            while 0 < k < len(new) and new[k - 1].isalnum() and new[k].isalnum() and k not in edges:
                k += 1 if back else -1
        for _ in range(gap):
            if k >= len(raw) or raw[k] not in " \t\n" or k in edges:
                break
            k += 1
        return k

    # From the end, so that the offsets still to place stay where they were; of two at one place, the
    # second goes first and the first lands before it.
    for o, p, back, climb in reversed(sorted(((between_words(o, back, gap), p, back, climb)
                                              for o, p, back, climb, gap in sites), key=lambda x: x[0])):
        cum, spot = 0, None
        for t in _texts(soup):
            kept = _kept(str(t), comment_re)
            n = len(kept)
            if back and o > 0 and cum < o <= cum + n or not (back and o > 0) and cum <= o < cum + n:
                j = o - cum
                # Right after the words before it, and after the comments that stood between them and it; or
                # right before the words after it, and before the comments that stood between it and them.
                if j > 0 and back:
                    at = kept[j - 1] + 1
                    for _ in range(lead.get(p, 0)):
                        if not (m := comment_re.match(str(t), at)):
                            break
                        at = m.end()
                else:
                    at = kept[j] if j < n else len(t)
                    for _ in range(trail.get(p, 0)):
                        ends = [m.start() for m in comment_re.finditer(str(t), 0, at) if m.end() == at]
                        if not ends:
                            break
                        at = ends[0]
                spot = t, at
                break
            cum += n
        if spot is None:
            # The words are all gone, and the tag goes with them.
            del placed[p]
            continue
        t, j = spot
        if 0 < j < len(t):
            t.replace_with(NavigableString(t[:j]), NavigableString(p), NavigableString(t[j:]))
            anchor, after_it = None, True
        else:
            anchor, after_it = t, j > 0
            # Beside a tag placed already there is nothing to climb out of: it stands where this one goes.
            for _ in range(0 if str(t) in placed else climb):
                sib = anchor.next_sibling if after_it else anchor.previous_sibling
                if sib is not None or anchor.parent is None or anchor.parent.name == "[document]":
                    break
                anchor = anchor.parent
        if anchor is None:
            anchor = next(x for x in _texts(soup) if str(x) == p)
            out = _enclosing(anchor)
            if out is None:
                continue
            anchor.extract()
            anchor, after_it = out, True
        else:
            out = _enclosing(anchor) if anchor.name is None or anchor.name not in _ENCLOSED else None
            if out is not None:
                anchor = out
        (anchor.insert_after if after_it else anchor.insert_before)(p)
    return placed


def _html_blocks(md: str) -> int:
    """How many HTML blocks pandoc reads in `md`, at any depth."""
    r = _pandoc.run(["-f", "gfm", "-t", "json"], md)
    return r.stdout.count('"t":"RawBlock"') if r.returncode == 0 else -1


def _tags_as_text(content: str, fragment: str, token, comments):
    """(the fragment with each element that stands for a raw tag of `content` written as two
    placeholders around its words, {placeholder: the source's bytes}). `comments` are the comment
    placeholders the fragment holds."""
    from bs4 import BeautifulSoup

    tags, lone, doc = _raw_tags(content)
    if not tags and not lone:
        return fragment, {}

    def key(el):
        return (el.name, tuple(sorted((k, " ".join(v) if isinstance(v, list) else v) for k, v in el.attrs.items())))

    # An element is the source tag that says the same: same name, same attributes, the
    # first one not yet taken. Of two that differ, the one left on the page keeps its own.
    unused = []
    for name, opening, closing, seen in tags:
        el = BeautifulSoup(seen, "html.parser").find(True)
        if el is not None:
            unused.append((key(el), opening, closing))
    soup = BeautifulSoup(fragment, "html.parser")
    placed = _lone_as_text(soup, lone, doc, token, _placeholders(comments)[0]) if lone else {}
    for el in soup.find_all(True):
        # A math span's <sup> is the render's, not a tag of the source; a wrapper the page puts around the
        # source's words, as `div.tblwrap` around a table, is not (#157).
        # In code, a tag is the code's words, and stays the element pandoc writes as text.
        if _page_own(el) or any("math" in (up.get("class") or []) or up.name in ("code", "pre")
                                for up in el.parents if up.name != "[document]"):
            continue
        k = key(el)
        hit = next((u for u in unused if u[0] == k), None)
        if hit is None:
            continue
        unused.remove(hit)
        # In brackets that are punctuation, as the tag's own < and > are: between letters pandoc would
        # take the words' `_` for intraword and drop its escape, and `\_x\_` would come back as emphasis.
        a, b = f"\u27e6{token()}\u27e7", f"\u27e6{token()}\u27e7"
        placed[a], placed[b] = hit[1], hit[2]
        el.insert_before(a)
        el.insert_after(b)
        el.unwrap()
    return (str(soup), placed) if placed else (fragment, {})


# ─────────────────────────────────────────────────────────────── footnotes ──
# The page shows a citation as pandoc's `<a href="#fnN" class="footnote-ref">`, N its place among the
# document's citations (pandoc numbers every citation, a label cited twice included), while the source
# names it by its label, `[^1]` or `[^note]`. Pandoc's HTML reader takes that link for a footnote with no
# words and writes an empty definition beside it, which the render shows in place of the note (sheaf #163).
# So each ref is named by its label in the version the page rendered (`_name_notes`), and the conversion
# writes `[^label]` where the ref was. A ref with no label is refused, never written as an empty note.

NOTE_REF_RE = re.compile(r'<a\b(?=[^>]*\bclass="[^"]*\bfootnote-ref\b)[^>]*>[\s\S]*?</a>')
# A name keeps its quotes as `_name_notes` wrote them, or a parser's: BeautifulSoup writes one that holds `"` in `'`.
NOTE_NAME_RE = re.compile(r'^<a\b[^>]*\bdata-rd-note=(?:"([^"]*)"|\'([^\']*)\')')
# A ref's number on the page: `#fn3`, or `#u-fn3` on a mounted page (mount.js gives every fragment its prefix).
NOTE_NUMBER_RE = re.compile(r'\bhref="#(?:u-)?fn(\d+)"')
NOTE_DEF_RE = re.compile(r"^ {0,3}\[\^[^\]\n]+\]:", re.M)
CITED_RE = re.compile(r"\[\^([^\]\n]+)\]")
# A citation in pandoc's sourcepos render: where it is in the source, and its number on the page. In a tight
# list item the span carries the item's place too, after its own.
CITED_AT_RE = re.compile(r'data-pos="(\d+):(\d+)-(\d+):(\d+)"(?: data-pos="[^"]*")*><a href="#fn(\d+)" class="footnote-ref"')


class _Unread(Exception):
    pass


def _note_labels(text: str) -> dict:
    """{page number: source label} for each citation of `text`, numbered as the page numbers them. Kept for the
    last few texts: a page that types on saves against one text again and again. The caller never changes it.
    A run of pandoc that failed (a time limit on a busy machine) is not kept: the next save asks again."""
    try:
        return _read_labels(text)
    except _Unread:
        return {}


@lru_cache(maxsize=8)
def _read_labels(text: str) -> dict:
    r = _pandoc.run(["-f", "gfm+sourcepos", "-t", "html5", "--wrap=none"], text)
    if r.returncode != 0:
        raise _Unread
    lines, labels = text.split("\n"), {}
    for m in CITED_AT_RE.finditer(r.stdout):
        l1, c1, l2, c2, n = map(int, m.groups())
        if l1 != l2 or l1 > len(lines):
            continue
        # Pandoc's columns count a tab to the next stop of 4: the citation is the one that starts at that column.
        line = lines[l1 - 1]
        cited = next((x for x in CITED_RE.finditer(line) if len(line[:x.start()].expandtabs(4)) + 1 == c1), None)
        if cited and len(line[:cited.end()].expandtabs(4)) + 1 == c2:
            labels[n] = cited.group(1)
    return labels


def _name_notes(text: str, edits) -> list:
    """The edits, each footnote ref in their HTML named by its label in `text`, the version the page rendered.
    A name the page sent is not the hub's and goes (SPEC 7.2); a ref that `text` does not number stays unnamed,
    and is refused."""
    edits = list(edits)
    if not any(NOTE_REF_RE.search(e["html"]) for e in edits):
        return edits
    labels = _note_labels(text)

    def name(m):
        ref = re.sub(r'\s+data-rd-note=(?:"[^"]*"|\'[^\']*\')', "", m.group(0))
        n = NOTE_NUMBER_RE.search(ref)
        label = labels.get(int(n.group(1))) if n else None
        if label is None:
            return ref
        return f'<a data-rd-note="{html_escape(label, quote=True)}"' + ref[2:]

    return [{**e, "html": NOTE_REF_RE.sub(name, e["html"])} for e in edits]


def _notes_as_tokens(fragment: str, token):
    """(fragment, {token: `[^label]`}): each footnote ref of the fragment as a placeholder pandoc keeps."""
    from bs4 import BeautifulSoup

    placed = {}
    if NOTE_REF_RE.search(fragment) and any(a.find_parent(["code", "pre", "samp", "tt", "var"]) for a in
                                            BeautifulSoup(fragment, "html.parser").select("a.footnote-ref")):
        # In code (pandoc's HTML reader takes samp, tt and var for code too) a citation is words: pandoc would no longer number it, and the page's numbers would be off.
        raise EditError("block has a footnote citation inside code; edit it in the .md")

    def swap(m):
        name = NOTE_NAME_RE.match(m.group(0))
        cited = f"[^{html_unescape(name.group(1) if name.group(1) is not None else name.group(2))}]" if name else ""
        if not CITED_RE.fullmatch(cited):
            raise EditError("block cites a footnote the edit cannot name; edit it in the .md")
        t = token()
        placed[t] = cited
        return t

    return NOTE_REF_RE.sub(swap, fragment), placed


def _convert_with_comments(block, fragment: str, strays=None):
    """(new markdown for the block, comments left without text)."""
    parsed = rdc.parse(block.content).comments
    by_id = {c.id: c for c in parsed}
    # Every other HTML comment in the block (another review tool's, a toc
    # directive, an internal note) is not sheaf's to change: it gets the same
    # placeholder trip as a rectoverso comment, matched on its exact text.
    foreign = _foreign_comments(block.content)
    unused = list(foreign)
    tokens, placed = {}, {}

    def token():
        while True:
            t = "RDCMT" + os.urandom(5).hex().upper()
            if t not in fragment:
                return t

    def swap(m):
        cid = m.group(1)
        if cid not in by_id or cid in tokens:
            return ""
        tokens[cid] = token()
        return tokens[cid]

    def keep(m):
        raw = m.group(0)
        if "MDB:" in raw:
            return raw
        # A comment node that is not in the source can only have been put there
        # by hand; it never reaches the file.
        if raw not in unused:
            return ""
        unused.remove(raw)
        t = token()
        placed[t] = raw
        return t

    frag = RAW_COMMENT_RE.sub(keep, ANCHOR_RE.sub(swap, fragment))
    comments = frozenset(tokens.values()) | frozenset(placed.keys())
    frag, tags = _tags_as_text(block.content, frag, token, comments)
    frag, notes = _notes_as_tokens(frag, token)
    new_md = html_block_to_md(frag, block.content, strays, comments, frozenset(notes.keys()))
    for t, cited in notes.items():
        if new_md.count(t) != 1:
            raise EditError("block cites a footnote the edit cannot keep; edit it in the .md")
        new_md = new_md.replace(t, cited, 1)
    if len(NOTE_DEF_RE.findall(new_md)) > len(NOTE_DEF_RE.findall(block.content)):
        # A citation put back at the start of a line reads as a definition, and an empty one hides the note.
        raise EditError("the edit leaves a footnote citation at the start of a line; edit it in the .md")
    if tags:
        before = _html_blocks(new_md)
        for t, raw in tags.items():
            # Pandoc's writer takes the character after a backslash it escapes, here the
            # placeholder's opening bracket: the placeholder is found by its own letters.
            found = re.findall(rf"\u27e6?{t[1:-1]}\u27e7", new_md)
            if len(found) != 1:
                # Pandoc lost or doubled the words around a raw tag: refused, as the file
                # would lose the tag.
                raise EditError("block holds raw HTML the edit cannot keep; edit it in the .md")
            new_md = new_md.replace(found[0], raw, 1)
        if _html_blocks(new_md) != before:
            # A tag the edit left alone at the start of a line opens an HTML block, which
            # would take the lines after it as raw text.
            raise EditError("the edit leaves raw HTML at the start of a line; edit it in the .md")
    lost = []
    for cid, c in by_id.items():
        t = tokens.get(cid)
        if t and t in new_md:
            new_md = new_md.replace(t, block.content[c.start:c.end], 1)
        else:
            lost.append(c)
    for t, raw in placed.items():
        if t in new_md:
            new_md = new_md.replace(t, raw, 1)
        else:
            unused.append(raw)
    # One the edit left without a place stays in the block, on its own line, in
    # its original order.
    stray = []
    for raw in foreign:
        if raw in unused:
            unused.remove(raw)
            stray.append(raw)
    if not RAW_COMMENT_RE.sub("", new_md).strip():
        # The block is gone: every rectoverso comment is an orphan, every other comment
        # stays where the block was.
        return "\n\n".join(foreign), parsed
    if stray:
        new_md = new_md.rstrip("\n") + "\n\n" + "\n\n".join(stray)
    return new_md, lost


LIST_BREAK = "<!-- -->"


def _apart(a, b) -> bool:
    """Does block b, written straight after block a, still begin a block of its own?"""
    head = split_md_blocks(a.text + b.content)
    return len(head) > 1 and head[0].content == a.content


def _close_up(blocks, touched, dropped) -> None:
    """Give back the blank line a change or a deletion took from between two blocks.

    A paragraph such as `Steps:` sits straight above its list with no blank line, so
    a block that is deleted after it, or replaced by a paragraph, would make the two
    one block, and the next edit of either would overwrite the other. Only a pair that
    has a touched block in or between it is looked at, and only one that now reads as a
    single block is changed: a blank line is written where the deleted block's own was.
    Two lists cannot be told apart by a blank line, nor a list from an indented code block
    under it (the code would be a paragraph of the last item), so two that a deleted
    paragraph stood between get a comment line between them instead (`merge_edits` keeps
    a deleted block's place until its last edit is in, so that its indices hold)."""
    live = [k for k, b in enumerate(blocks) if b.content or b.gap]
    for ka, kb in zip(live, live[1:]):
        a, b = blocks[ka], blocks[kb]
        lists = a.kind == "list" and b.kind in ("list", "indented_code")
        if (a.gap and not lists) or not b.content.strip() or not touched.intersection(range(ka, kb + 1)):
            continue
        if not _apart(a, b):
            if not a.gap:
                a.gap = next((dropped[k] for k in range(ka + 1, kb) if dropped.get(k)), "\n")
            if lists and not _apart(a, b):
                # Read as one loose list. A comment line between them ends the first
                # list (CommonMark's own way to keep two lists apart).
                a.gap = "\n" + LIST_BREAK + "\n\n"


def _width_text(blocks, i: int, n: int) -> str:
    """Blocks i to i + n - 1 as the content of one: their text, without the blank lines after the last."""
    return "".join(x.text for x in blocks[i:i + n - 1]) + blocks[i + n - 1].content


def _join(blocks, i: int, n: int) -> None:
    """Blocks i to i + n - 1 as one, in block i, the others left empty so that every index holds."""
    b, last = blocks[i], blocks[i + n - 1]
    b.content = _width_text(blocks, i, n)
    b.gap = last.gap
    for x in blocks[i + 1:i + n]:
        x.content = x.gap = ""


def apply_edits(md_text: str, edits, _tomb: str = "", _width: int = 1, _named: bool = False):
    """Splice edited blocks into the source. Returns (new_text, report).

    `edits` is an iterable of {"i": block index, "html": edited fragment}.
    Blocks not named here are written back byte-for-byte. The report's `toggled` holds, for each
    block whose edit only flipped task marks, its (old, new) content: the hub's Share and Stop James
    count only those (SPEC 9.11).

    `_tomb` and `_width`, for `merge_edits`, which passes one edit: an emptied block becomes this
    one line instead of going, so the block count and every index stay as they were; the edit
    takes the place of the `_width` blocks from its index, which the page's own earlier save made
    of the one block the page still shows (`_own_span`). The page never sends a width. `_named`, for
    `merge_edits` too: its footnote refs are named already, against the base (`_name_notes`).
    """
    blocks = split_md_blocks(md_text)
    cited = [CITED_RE.findall(b.content) for b in blocks]
    changed, skipped, deleted, dropped, toggled = [], [], [], {}, {}

    for e in (edits if _named else _name_notes(md_text, edits)):
        i = int(e["i"])
        toggled.pop(i, None)            # a later edit of the block decides what it holds
        if not (0 <= i and i + _width <= len(blocks)):
            skipped.append((i, "no such block"))
            continue
        locked = next((x for x in blocks[i:i + _width] if not x.editable), None)
        if locked is not None:
            skipped.append((i, f"{locked.kind} blocks are not editable"))
            continue
        if _width > 1:
            _join(blocks, i, _width)
        b = blocks[i]
        if _unchanged(b, e["html"]):
            continue
        ticked = _toggle_boxes(b, e["html"])
        if ticked is not None:
            toggled[i] = (b.content, ticked)
            b.content = ticked
            changed.append(i)
            continue
        strays = []
        try:
            new_md, lost = _convert_with_comments(b, e["html"], strays)
        except EditError as ex:
            skipped.append((i, str(ex)))
            continue
        if not new_md.strip() and lost:
            # Deleted on purpose, but its comments stay: they take the block's
            # place as standalone lines, marked orphan.
            b.content = _orphans(lost)
            changed.append(i)
            continue
        if lost:
            new_md = new_md.rstrip("\n") + "\n\n" + _orphans(lost)
        if not new_md.strip():
            # Emptied on purpose: delete the block instead of refusing the save.
            # Clearing `gap` as well as `content` takes the blank lines that
            # followed it with it, so the neighbours keep their own separation
            # and nothing merges. The block count then drops, which sets `remap`
            # below and makes the page reload rather than save again against
            # indices that no longer exist.
            if b.content or b.gap:
                if _tomb:
                    b.content = _tomb + "\n"
                else:
                    dropped[i] = b.gap
                    b.content = ""
                    b.gap = ""
                changed.append(i)
                deleted.append(i)
            continue
        if not new_md.endswith("\n"):
            new_md += "\n"
        if new_md != b.content:
            b.content = new_md
            changed.append(i)
            if strays:
                diagnostics.record("hub", "markup-unwrapped", DOC.get(), block=i, tags=",".join(strays))

    _close_up(blocks, set(changed), dropped)
    new_text = "".join(b.text for b in blocks)
    # A converted block can split into several (a new blank line makes two
    # paragraphs). That invalidates every index the open page is holding, so the
    # caller has to make the page reload rather than let it save against stale ids.
    remap = len(split_md_blocks(new_text)) != len(blocks)
    # So does a save that took a footnote citation from a block, or put one in: the page numbers each citation
    # by its place in the document (`_name_notes`), and the refs after it now have other numbers.
    remap = remap or any(CITED_RE.findall(blocks[i].content) != cited[i] for i in changed)
    return new_text, {"changed": changed, "skipped": skipped, "remap": remap, "deleted": deleted,
                      "toggled": list(toggled.values())}


# ──────────────────────────────────────────── edits against an older version ──
# The page saves against the version it was rendered from. When the .md moved on
# since (a session replying, editing another paragraph, another program), a save used
# to be refused whole, and the page froze on "Reload needed" even when nobody else
# had touched the paragraph being edited. Now the save is rebased paragraph by
# paragraph: the server keeps the texts it has handed out, lines the page's
# version up against the one on disk, and puts each edited block where it now is.
# Only the same paragraph changed on both sides is a conflict, and even then
# nothing is lost: the page's version is written and the disk's version goes into
# a comment on it.

MERGE_BY = "sheaf"


def _prose(content: str) -> str:
    return COMMENT_SRC_RE.sub("", content)


def _identity(c):
    """What makes two comments one: an id alone is not it, since the next id is the highest
    plus one and a deleted comment's id comes round again. `_unclash` asks the same."""
    return (c.id, c.by, c.at, c.quote)


# A replaced range is paired by text, never by position alone: an inserted block
# shifts every block after it, and the page's edit would land on the neighbour (the
# old code paired by position). Position decides only where text does not: in a
# range with as many blocks on each side, a block that looks like none of the file's
# is a paragraph rewritten in place.
ALIGN_MIN = 0.5       # least word-level similarity for two blocks to be one paragraph
ALIGN_LIMIT = 3000    # most (base, file) block pairs compared in one range; above it
                      # nothing is paired, so no paragraph of the file is overwritten
_WORD_RE = re.compile(r"\w+")


def _similarity(a: str, aw: list, b: str, bw: list) -> float:
    """How alike two blocks are, 0 when they are not the same paragraph."""
    from difflib import SequenceMatcher

    if a.strip() == b.strip():
        return 1.0
    if not aw or not bw:
        return 0.0
    sm = SequenceMatcher(None, autojunk=False)
    sm.set_seqs(aw, bw)
    if sm.real_quick_ratio() < ALIGN_MIN or sm.quick_ratio() < ALIGN_MIN:
        return 0.0
    r = sm.ratio()
    return r if r >= ALIGN_MIN else 0.0


def _align(base: list, cur: list) -> list:
    """Pair the blocks of a replaced range, in order, by text. Returns for each base
    block the index of the file block it is, or None when it has no match (it is
    gone). The pairing with the most similarity wins; of equal ones the earlier
    base block takes the earlier file block."""
    n, m = len(base), len(cur)
    if n * m > ALIGN_LIMIT:
        return [None] * n
    bw, cw = [_WORD_RE.findall(x) for x in base], [_WORD_RE.findall(x) for x in cur]
    sim = [[_similarity(base[a], bw[a], cur[b], cw[b]) for b in range(m)] for a in range(n)]
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    for a in range(n - 1, -1, -1):
        for b in range(m - 1, -1, -1):
            best[a][b] = max(best[a + 1][b], best[a][b + 1],
                             best[a + 1][b + 1] + sim[a][b] if sim[a][b] else 0.0)
    paired, a, b = [None] * n, 0, 0
    while a < n and b < m:
        if sim[a][b] and best[a][b] == best[a + 1][b + 1] + sim[a][b]:
            paired[a] = b
            a, b = a + 1, b + 1
        elif best[a][b] == best[a + 1][b]:
            a += 1
        else:
            b += 1
    return paired


def _pair(base: list, cur: list, placed=None) -> list:
    """`_align`, and then, in a range with as many blocks on each side, a base block
    with no match takes the file block at its own position when no match has taken it
    and taking it keeps the pairs in order. Those base blocks go into `placed`, if given."""
    paired = _align(base, cur)
    if len(base) != len(cur):
        return paired
    taken = {p for p in paired if p is not None}
    for k, p in enumerate(paired):
        if p is not None or k in taken:
            continue
        lo = max((q for q in paired[:k] if q is not None), default=-1)
        hi = min((q for q in paired[k + 1:] if q is not None), default=len(cur))
        if lo < k < hi:
            paired[k] = k
            taken.add(k)
            if placed is not None:
                placed.add(k)
    return paired


class _Row(NamedTuple):
    """A row of `_rows`: `page`, the index of a block among the page's own, or None for one the other side
    added; `other`, its index on the other side, or None for one that side does not have; and `how`:
    "same" (the same words), "changed" (paired by their words or place), "gone" or "added"."""
    page: int | None
    other: int | None
    how: str


def _rows(page: list, other: list, pair) -> list:
    """The blocks of `page` against those of `other` (each as its words, comments aside), in order, as
    `_Row`s; `pair` pairs those that are not the same."""
    from difflib import SequenceMatcher

    rows = []
    for tag, a1, a2, b1, b2 in SequenceMatcher(None, page, other, autojunk=False).get_opcodes():
        if tag == "equal":
            rows += [_Row(a1 + d, b1 + d, "same") for d in range(a2 - a1)]
            continue
        b = b1
        for d, p in enumerate(pair(page[a1:a2], other[b1:b2])):
            if p is None:
                rows.append(_Row(a1 + d, None, "gone"))
                continue
            rows += [_Row(None, y, "added") for y in range(b, b1 + p)]
            rows.append(_Row(a1 + d, b1 + p, "changed"))
            b = b1 + p + 1
        rows += [_Row(None, y, "added") for y in range(b, b2)]
    return rows


def _by_page(rows, n: int):
    """`_rows` read by the page's n own blocks: the row of each, and for each of the n + 1 places before,
    between and after them the indices of the blocks the other side added there."""
    each, added, k = [None] * n, [[] for _ in range(n + 1)], 0
    for r in rows:
        if r.page is None:
            added[k].append(r.other)
        else:
            each[r.page], k = r, r.page + 1
    return each, added


def _blank_before(before: str) -> str:
    """What has to be written after `before` so the next block starts after a blank
    line: nothing when there is one (or nothing before it)."""
    lines = before.split("\n")
    if not before or (len(lines) > 1 and lines[-1] == "" and lines[-2].strip() == ""):
        return ""
    return "\n" if before.endswith("\n") else "\n\n"


def _quote_starts(text: str, q: str) -> list:
    """Where q starts in text, every occurrence, those that overlap too."""
    return [m.start() for m in re.finditer("(?=" + re.escape(q) + ")", text)] if q else []


def _insert_comment(md_text: str, j: int, raw: str, quote: str, nth: int = 0) -> str:
    """Put an existing comment's bytes into block j, after the `nth` occurrence of `quote`
    (the first unless said; a negative `nth` is none) if it is there, else at the end of
    the block; in a heading, always at the end of its text. When the block ends in code the end of
    the block is inside the code, and a comment block ends on its `-->` line, so there the comment
    goes on a line of its own after the block. Where that is still code (a fence the
    file never closed runs to the end of the file) the comment is text, and
    `sheaf comments` would not list it: it goes on a line of its own above the block."""
    blocks = split_md_blocks(md_text)
    b = blocks[j]
    start = sum(len(x.text) for x in blocks[:j])
    at_off, own_line = len(b.content.rstrip("\n")), False
    headless = False
    if b.kind == "heading":            # a heading keeps its words whole: the comment goes at its end (ticket 55)
        headless = rdc.heading_anchor(b.content) is None
        at_off = len(b.content.rstrip("\n")) if headless else rdc.heading_anchor(b.content)
    q = rdc.squash(quote)
    try:
        proj = rdc.projection(b.content)
        # The last character of a block that ends in code has no place in the source.
        own_line = bool(proj.text) and not proj.chars[len(proj.text) - 1]
        starts = _quote_starts(proj.text, q)
        k = starts[nth] if 0 <= nth < len(starts) else -1
        if k >= 0:
            # A quote anchor_point cannot place raises, and `except` keeps the end of the block.
            at_off = rdc.comment_point(b.kind, b.content, k, k + len(q), quote)
            own_line = False
    except Exception:
        # A table's cell that has no place (an opener nothing closes) leaves the end of the last
        # row, where the block would close the opener and hide the cell's words.
        own_line = own_line or b.kind == "table" or rdc.in_table_row(b.content, at_off)
    if headless or ((b.kind in rdc.ONE_LINE_KINDS or rdc.in_table_row(b.content, at_off)) and "\n" in raw):
        # A heading with no words: a block right after its hashes would make the line a paragraph.
        # A block of several lines at the end of a heading line runs into the lines after it, and
        # in a table row it ends the table.
        own_line = True
    if b.kind in LOCKED_KINDS:
        # Code, raw html, front matter: a comment inside is literal text, and a comment
        # block ends on its `-->` line, so nothing may follow it there.
        own_line = True
    if own_line:
        end = start + len(b.content)
        lead = "" if b.content.endswith("\n") else "\n"
        pos = end + len(lead) + 1
        out = md_text[:end] + lead + "\n" + raw + "\n" + md_text[end:]
    else:
        pos = start + at_off
        out = md_text[:pos] + raw + md_text[pos:]
    offset = 0
    for x in split_md_blocks(out):
        if pos < offset + len(x.text):
            if x.kind in rdc.CODE_KINDS:
                return md_text[:start] + raw + "\n\n" + md_text[start:]
            break
        offset += len(x.text)
    return out


def _occurrence(content: str, c) -> int:
    """Which occurrence of its quote, in the block's text, the comment sits on: how many
    times the quote starts earlier in what is shown before the comment. 0 (the first, as a
    comment with no place of its own is read) when it cannot be told."""
    q = rdc.squash(c.quote)
    try:
        before = rdc.projection(content[:c.start]).text
    except Exception:
        return 0
    if not q or not before.endswith(q):
        return 0
    return sum(1 for k in _quote_starts(before, q) if k < len(before) - len(q))


def _written_block(blocks, j: int, grown: int, quote: str, nth: int = 0):
    """(index, occurrence) of where a comment the file gained goes, once the page's edit of
    block j has been written as blocks j .. j + grown (the page splits a paragraph on
    Enter): the block of them that holds the `nth` occurrence of the comment's words,
    counted over all of them in order, and which occurrence it is in that block. When the
    page took that occurrence away, the first block that holds the words at all, at the
    end of it. When none does, the last block that says something (not an orphan or a note
    the edit left after itself), and occurrence None: the page took the words out, and a
    comment is an orphan after that block (SPEC 5.4), as one on words the page itself
    removes; a note of the merge's is about the block, and goes at the end of it."""
    last = j + max(grown, 0)
    q = rdc.squash(quote)
    first = None
    if q:
        left = nth
        for k in range(j, last + 1):
            try:
                n = len(_quote_starts(rdc.projection(blocks[k].content).text, q))
            except Exception:
                continue
            if n and first is None:
                first = k
            if left < n:
                return k, left
            left -= n
    if first is not None:
        return first, -1                 # no occurrence of its own is left: the end of the block
    while last > j and not _bare(blocks[last].content):
        last -= 1
    return last, (None if q else 0)


def _put_lifted(text: str, lifted, j: int, grown: int):
    """Put each lifted comment back on the block of j..j+grown that holds its words. Returns the text and the
    comments whose words none of them holds, each with the block to follow: the caller makes them orphans (5.4).
    A merge's own note is never one: it stays at the end of its block."""
    lost = []
    for raw, quote, c, nth in lifted:
        k, nth = _written_block(split_md_blocks(text), j, grown, quote, nth)
        if nth is None and c.by != MERGE_BY:
            lost.append((k, c))
        else:
            text = _insert_comment(text, k, raw, quote, nth or 0)
    return text, lost


def _put_orphans(text: str, j: int, comments) -> str:
    """Comments whose paragraph the page deleted, as orphans on lines of their own
    where it was (what `apply_edits` does for a deleted block): after block j, which
    is the line that keeps its place or the lines that are all that is left of it."""
    if not comments:
        return text
    blocks = split_md_blocks(text)
    end = sum(len(x.text) for x in blocks[:j]) + len(blocks[j].content)
    lines = _orphans(comments)
    return text[:end] + ("" if blocks[j].content.endswith("\n") else "\n") + "\n" + lines + text[end:]


def _next_id(*texts: str) -> str:
    """The id for a comment the merge writes: above every id in any of the texts it
    works from. The file's text alone is not enough: a paragraph that is put back
    brings the base's comments with it, and a note that took one of those ids first
    would make two comments of one."""
    return max((rdc.next_id_in(t) for t in texts), key=lambda i: int(i[1:]))


def _reid(raw: str, new: str) -> str:
    """A comment's bytes with another id; nothing else in them changes."""
    inner = raw[4:-3]
    end = min((k for k in (inner.find("\n"), inner.find("<br>")) if k >= 0), default=len(inner))
    marker = rdc.MARKER_AT_HEAD_RE.search(inner[:end])
    if marker:
        for m in rdc.FIELD_RE.finditer(inner[:end], marker.end()):
            if m.group(1) == "id":
                return raw[:4 + m.start(2)] + new + raw[4 + m.end(2):]
    return raw


def _unclash(md: str, text: str, *others: str) -> str:
    """The comments of a paragraph that is put back, against the ids the file holds
    now. One the file holds is not written a second time, whatever state the file has
    taken it to since (the agent moved the paragraph's text, comment and all, elsewhere
    and resolved or answered it): the file's is the one to keep. It is the same comment
    when the id, the author, the time it was written and the words it was on are the
    same; one whose id the file gave to another comment (the agent deleted this
    paragraph and then numbered a new comment over it) gets the next free id."""
    held = {c.id: c for c in rdc.parse(text).comments}
    for c in sorted(rdc.parse(md).comments, key=lambda c: -c.start):
        h = held.get(c.id)
        if h is None:
            continue
        raw = md[c.start:c.end]
        same = raw == text[h.start:h.end] or (c.by, c.at, c.quote) == (h.by, h.at, h.quote)
        md = md[:c.start] + ("" if same else _reid(raw, _next_id(md, text, *others))) + md[c.end:]
    return md


def _note(md_text: str, j: int, body: str, at: str, *avoid: str) -> str:
    """A conflict note by sheaf on block j; its id is above every id in `avoid` too."""
    b = split_md_blocks(md_text)[j]
    t = ""
    try:
        t = rdc.projection(b.content).text
    except Exception:
        pass
    c = rdc.Comment(id=_next_id(md_text, *avoid), by=MERGE_BY, at=at, status="open",
                    quote=t[-60:], body=body.strip("\n"))
    raw = rdc.format(c, one_line=b.kind in rdc.ONE_LINE_KINDS)
    return _insert_comment(md_text, j, raw, t[-60:])


def _bare(content: str) -> str:
    """What a block says apart from its HTML comments, sheaf's or anyone else's."""
    return RAW_COMMENT_RE.sub("", content).strip()


def _drop_tombstones(text: str, tomb: str) -> str:
    """Take the lines that kept the places of deleted paragraphs out, as `apply_edits`
    takes a deleted block out: its blank lines go with it and the neighbours keep theirs."""
    blocks = split_md_blocks(text)
    dropped = {}
    for k, b in enumerate(blocks):
        if b.content.strip() == tomb:
            dropped[k] = b.gap
            b.content = b.gap = ""
    _close_up(blocks, set(dropped), dropped)
    return "".join(b.text for b in blocks)


LOCKED_NOTE = ("This paragraph was replaced in the file by a block this page cannot edit while it "
               "was being edited on this page. The page's version was:")


def _page_text(html: str) -> str:
    """What the page's edit says, as markdown; as plain text where it cannot be."""
    frag = ANCHOR_RE.sub("", html)
    try:
        return html_block_to_md(frag, "", [])
    except EditError:
        from bs4 import BeautifulSoup
        return BeautifulSoup(frag, "html.parser").get_text("\n").strip()


GONE_NOTE = ("This paragraph was deleted in the file while it was being edited on this page. "
             "The page's edit was kept; delete it again if the deletion was meant.")


def _restore(text, blocks, j, i, base, html, tomb, at, avoid, changed, skipped, conflicts) -> str:
    """The page's edit of block i of the base, which the file deleted, written where it
    was (before block j of `text`), with a note on it. An edit that says what the base
    said, is refused, or deletes the block too leaves the file's deletion as it is.

    The edit is made on the base block alone, never on the file's text around it: two
    lists cannot be told apart by a blank line, so the block put back whole joins the
    list above it or the list below it (an indented code block below it becomes a
    paragraph of its last item), and block j is then something else. Where that would
    happen a separator line takes the place of the blank line, above it, below it or
    both, until the last edit is in, so that every index above still points at the
    block it did; then `_close_up` writes the comment line that keeps them apart."""
    md, rep = _apply_one(base.content, html)
    skipped += [(i, why) for _, why in rep["skipped"]]
    if not rep["changed"] or not _bare(md):
        return text
    md = _unclash(md, text, *avoid)
    ins = md if md.endswith("\n") else md + "\n"
    pos = sum(len(x.text) for x in blocks[:j])
    before, after = text[:pos], text[pos:]
    lead, tail = _blank_before(before), "\n" if after else ""
    head = [b.content.rstrip() for b in blocks[:j]]
    rest = [b.content.rstrip() for b in blocks[j:]]
    line = tomb + "\n\n"
    # The text as it is, then with a separator above it, below it, and both.
    for sep, end in (("", ""), (line, ""), ("", line), (line, line)):
        restored = before + lead + sep + ins + tail + end + after
        now = split_md_blocks(restored)
        up, down = bool(sep), bool(end)
        grown = len(now) - len(blocks) - up - down
        if (grown >= 1 and [b.content.rstrip() for b in now[:j]] == head
                and [b.content.rstrip() for b in now[j + up + grown + down:]] == rest
                and (not up or now[j].content.strip() == tomb)
                and (not down or now[j + up + grown].content.strip() == tomb)):
            # The blocks it was written as; the note goes on the last that says anything.
            k = j + up + grown - 1
            while k > j + up and not _bare(now[k].content):
                k -= 1
            break
    else:
        # Something above takes it in (an unclosed fence): its text is in the file, in
        # that block, and the note is on the block that holds its last line.
        restored = before + lead + ins + tail + after
        now = split_md_blocks(restored)
        last, k, offset = pos + len(lead) + len(ins) - 1, 0, 0
        for k, b in enumerate(now):
            offset += len(b.text)
            if offset > last:
                break
    changed.append(i)
    conflicts.append({"i": i, "kind": "gone"})
    return _note(restored, k, GONE_NOTE, at, *avoid)


def _apply_one(md: str, html: str, **kw):
    """`apply_edits` of one edit, to the first block of `md` (and the `_width` after it, if given), its footnote
    refs named already by `merge_edits`."""
    return apply_edits(md, [{"i": 0, "html": html}], _named=True, **kw)


def _said(block) -> str:
    """What a block says in the source, comments aside and without the blank lines around it."""
    return _prose(block.content).strip()


def _own_blocks(base, saved):
    """The blocks that the page's last save of the base block `base` made of it, from `saved`, the HTML
    that save sent; None when there is none. A save that brings a reload keeps the hash of the text on
    screen until that reload (SPEC 10.3), so a second save of a block is merged against the page's first
    one, which may have made several blocks of the one (Enter splits a paragraph)."""
    if not saved:
        return None
    try:
        md, _ = _apply_one(base.content, saved)
    except EditError:
        return None
    return split_md_blocks(md) or None


def _alike(o, c) -> bool:
    """Is file block c the page's own block o: one the page can edit, of the same kind, with the same
    words, comments aside. A block the page cannot edit is never its own: a paragraph indented into a
    code block has the same words, and its edit would be skipped where it goes into a note."""
    return c.editable and o.kind == c.kind and _said(o) == _said(c)


def _own_span(page_blocks, file_blocks, j: int):
    """(first, count) of the `file_blocks` that are the page's own last save of a base block, its
    blocks `page_blocks` (`_own_blocks`): not a change made in the file; None when the file does not hold them
    so. Block j, which the merge paired with the base block, is one of them."""
    n = len(page_blocks)
    for first in range(min(j, len(file_blocks) - n), max(j - n + 1, 0) - 1, -1):
        if all(_alike(o, c) for o, c in zip(page_blocks, file_blocks[first:first + n])):
            return first, n
    return None


def _own_rows(page_blocks, file_blocks, j: int, free):
    """The page's own last save of a base block, `page_blocks` (several blocks), where the file has since changed
    one of them or put a block among them: read around file block j over the blocks that `free` says no
    other base block has, as `_rows` with file block indices, a block of `page_blocks` paired with a file block
    it does not equal only by their words. None unless block j is one of them, one at least still says
    the page's words, and the file changed one or put one among them."""
    lo = hi = j
    while lo > 0 and free(lo - 1):
        lo -= 1
    while hi + 1 < len(file_blocks) and free(hi + 1):
        hi += 1
    rows = [r if r.other is None else r._replace(other=lo + r.other)
            for r in _rows([_said(o) for o in page_blocks], [_said(c) for c in file_blocks[lo:hi + 1]], _align)]
    ends = [r.other for r in rows if r.page is not None and r.other is not None]
    if not ends:
        return None
    # The blocks the file added before the first of them or after the last are not among them.
    rows = [r for r in rows if r.other is None or ends[0] <= r.other <= ends[-1]]
    how = {r.other: r.how for r in rows if r.other is not None}
    deleted = any(r.other is None and r.page is not None for r in rows)
    if (how.get(j) not in ("same", "changed") or "same" not in how.values()
            or not ({"changed", "added"} & set(how.values()) or deleted)):
        return None
    if any(r.how == "same" and not _alike(page_blocks[r.page], file_blocks[r.other])
           or r.how == "changed" and not file_blocks[r.other].editable for r in rows):
        return None
    return rows


def _lift(content: str, held):
    """`content` without the comments that are not the base block's (`held`, their identities), and those
    comments as [(bytes, quote, comment, occurrence)], the last first."""
    out, lifted = content, []
    for c in sorted((c for c in rdc.parse(content).comments if _identity(c) not in held), key=lambda c: -c.start):
        lifted.append((out[c.start:c.end], c.quote, c, _occurrence(content, c)))
        out = out[:c.start] + out[c.end:]
    return out, lifted


def _marks(text: str):
    """The comments in a text: sheaf's by id, everyone else's by their bytes."""
    return Counter(c.id for c in rdc.parse(text).comments), Counter(_foreign_comments(text))


def _own_merge(region, first: int, rows, page_blocks, j: int, html: str, held):
    """The edit of a base block over `region`, the file blocks from `first` on, which hold the page's own
    last save of it as `rows` (`_own_rows`). The edit takes the place of the page's own blocks, and the
    blocks the file put among them stay where they are. A block of the page's own the file changed (block j, the
    one the merge paired with the base block, or another line of the page's split) stays as the file changed it
    where the edit leaves it as the page saved it; where the edit changes it too or takes it out, the page's is
    written with the note, as for a block the page did not split (ticket 137). Returns (text, notes): the
    region's new text, without the blank lines after its last block, and [(block in it, the file's
    words)] for the notes; ("", []) when the file and the edit together leave none of its blocks; None when
    it cannot be done so (the edit is refused or deletes it all, or a comment would be written twice or lost),
    and the edit goes where the merge put it."""
    rows = [r if r.other is None else r._replace(other=r.other - first) for r in rows]
    j -= first          # from here on the blocks are counted in the region
    matched = [r.other for r in rows if r.how in ("same", "changed")]
    matched_text = "".join(region[x].text for x in matched)
    content, lifted = _lift(matched_text, held)
    edit_text, rep = _apply_one(content, html, _width=len(matched))
    edited = split_md_blocks(edit_text)
    if rep["skipped"] or not any(_bare(b.content) for b in edited):
        return None
    in_file, file_added = _by_page(rows, len(page_blocks))
    in_edit, edit_added = _by_page(_rows([_said(o) for o in page_blocks], [_said(b) for b in edited], _pair), len(page_blocks))
    pieces, kept, notes, said = [], set(), [], []
    owed = []         # the file's words of the blocks it changed, for the notes on the next block of the edit's

    def file_block(x):
        pieces.append(region[x])
        kept.add(x)

    def edit_block(y):
        b = edited[y]
        pieces.append(b)
        if _bare(b.content):
            said.append(len(pieces) - 1)
            notes.extend((len(pieces) - 1, words) for words in owed)
            owed.clear()

    for k in range(len(page_blocks)):
        for x in file_added[k]:
            file_block(x)
        for y in edit_added[k]:
            edit_block(y)
        file_row, edit_row = in_file[k], in_edit[k]
        if file_row.how != "changed":
            # A line the file deleted and the edit leaves as the page saved it stays deleted.
            if edit_row.how != "gone" and not (file_row.how == "gone" and edit_row.how == "same"):
                edit_block(edit_row.other)
        elif edit_row.how == "same":
            file_block(file_row.other)
        else:
            owed.append(_said(region[file_row.other]))
            if edit_row.how == "changed":
                edit_block(edit_row.other)
    for y in edit_added[-1]:
        edit_block(y)
    for x in file_added[-1]:
        file_block(x)
    if owed:
        if not said:
            return None
        notes.extend((said[-1], words) for words in owed)

    if not pieces:
        # The file deleted what the edit leaves and the edit takes out the rest: the region goes, as a block the
        # page empties does. A comment in it would have nowhere to go, so then the edit goes where the merge put it.
        return None if any(_marks("".join(b.text for b in region))) else ("", [])
    text = "".join((b.content if b.content.endswith("\n") else b.content + "\n") + (b.gap or "\n")
                   for b in pieces[:-1])
    text += pieces[-1].content if pieces[-1].content.endswith("\n") else pieces[-1].content + "\n"
    if [b.content.rstrip("\n") for b in split_md_blocks(text)] != [b.content.rstrip("\n") for b in pieces]:
        return None
    # A comment the file added goes back where its words now are, unless it is in a block of the file's kept whole.
    starts, offset = [], 0
    for x in matched:
        starts.append((offset, x))
        offset += len(region[x].text)
    text, lost = _put_lifted(text, [x for x in lifted if [y for start, y in starts if start <= x[2].start][-1] not in kept],
                             0, len(pieces) - 1)
    if len(split_md_blocks(text)) != len(pieces):
        return None
    if lost:
        # Words the edit took out: the comments on them are orphans after the last block that says something.
        k = lost[0][0]
        text = _put_orphans(text, k, [c for _, c in lost])
        grew = len(split_md_blocks(text)) - len(pieces)
        notes = [(b + grew * (b > k), w) for b, w in notes]
    if _marks(text) != _marks("".join(b.text for b in region)):
        return None
    return text, notes


def _splice(text: str, blocks, j: int, n: int, region: str):
    """`text` with its blocks j .. j + n - 1 replaced by `region` (`_own_merge`; the blank lines after the
    last stay those of block j + n - 1); None when that leaves any other block as it was not."""
    pos = sum(len(x.text) for x in blocks[:j])
    end = pos + sum(len(x.text) for x in blocks[j:j + n])
    out = text[:pos] + region + blocks[j + n - 1].gap + text[end:]
    now, m = split_md_blocks(out), len(split_md_blocks(region))
    if (len(now) == len(blocks) - n + m and [b.content for b in now[:j]] == [b.content for b in blocks[:j]]
            and [b.content for b in now[j + m:]] == [b.content for b in blocks[j + n:]]):
        return out
    return None


BOTH_NOTE = "Edited on this page and in the file at the same time. The page's version was saved. The file had:"


def _both_note(words: str) -> str:
    """The note on a block edited on the page and in the file: `BOTH_NOTE`, a blank line, the file's words."""
    return BOTH_NOTE + "\n\n" + words


class _Step(NamedTuple):
    """One edit of a merge as it is written: at file block `start`, in `mode`, the edit of base block `i`
    with its `html`, over `width` file blocks; `merged`, the text `_own_merge` made of them with its notes,
    and `back`, the (block, mode) where the merge put the edit, for when that text no longer fits."""
    start: int
    mode: str
    i: int
    html: str
    width: int = 1
    merged: tuple | None = None
    back: tuple | None = None


def merge_edits(base_text: str, cur_text: str, edits, at: str = ""):
    """Apply edits made on `base_text` to `cur_text`. Returns (new_text, report).

    Each edit is {i, html}, and `saved`, the HTML of the page's last save of that block, if any: the
    file blocks that are that save are not a change made in the file, and the edit takes their place
    (`_own_span`).

    report: changed, skipped, remap (always True when anything moved, so the page
    reloads onto the merged document), merged, conflicts [{i, kind}].
    """
    from difflib import SequenceMatcher

    # The page numbered its footnote refs in the base: named there, before any block moves (`_name_notes`).
    edits = _name_notes(base_text, edits)
    bb, cb = split_md_blocks(base_text), split_md_blocks(cur_text)
    bp, cp = [_prose(b.content) for b in bb], [_prose(b.content) for b in cb]
    sm = SequenceMatcher(None, bp, cp, autojunk=False)
    plan = {}     # base index -> (cur index, mode)
    placed = set()  # the base blocks paired with a file block by their place alone
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "replace":
            # A block with no match is gone; it comes back where it was, after the
            # block paired before it.
            after, by_place = j1, set()
            for k, p in enumerate(_pair(bp[i1:i2], cp[j1:j2], by_place)):
                if p is None:
                    plan[i1 + k] = (after, "gone")
                else:
                    plan[i1 + k] = (j1 + p, "both")
                    after = j1 + p + 1
            placed |= {i1 + k for k in by_place}
            continue
        for k in range(i2 - i1):
            if tag == "equal":
                plan[i1 + k] = (j1 + k, "same")
            else:
                plan[i1 + k] = (j1, "gone")
    if cb and cb[0].kind == "frontmatter":
        # Front matter is the first thing in a file. A paragraph put back at the top
        # goes under it: in front, the `---` lines read as a rule and a heading.
        plan = {i: ((1, mode) if mode == "gone" and j == 0 else (j, mode)) for i, (j, mode) in plan.items()}

    # Each edit as a `_Step`. The edit of a block the merge paired takes the place of the page's own save of it,
    # all `width` of its blocks, when the merge paired none of them with another base block, no other edit has
    # taken one of them and none is put back among them or, coming after it on the page, before them (a paragraph
    # the file deleted); else it goes where the merge put it. One the merge put back as deleted stays so: two such
    # edits can find the same file block for their own. Where the file changed one of several blocks of the page's
    # own save or put one among them, the edit is `merged` with the file's blocks there (`_own_merge`).
    edits = sorted((e for e in edits if 0 <= int(e["i"]) < len(bb) and int(e["i"]) in plan), key=lambda e: int(e["i"]))
    by_i = {int(e["i"]): e for e in edits}
    paired = {j: i for i, (j, mode) in plan.items() if mode != "gone"}
    put_back = [(plan[int(e["i"])][0], int(e["i"])) for e in edits if plan[int(e["i"])][1] == "gone"]

    claims_of, page_of = {}, {}     # by base block k / by edit (i, html): a conversion, which `moves` asks for per file block

    def moves(x, i, page_blocks, html):
        """Does file block x go to edit i from the base block the merge paired it with by its place alone? It
        says what one of the page's own blocks of block i says: that base block was deleted in the file, unless
        its own edit of this save claims the block. The file may also have written the page's words over it,
        and they are kept: the edit must keep them too. An edit of that block that comes before block i has its
        step in `todo` already, where the merge put it: on this file block, which it does not claim."""
        k = paired.get(x)
        if k is None or k == i or k not in placed:
            return False
        if not any(_alike(o, cb[x]) for o in page_blocks):
            return False
        if k not in claims_of:
            claims_of[k] = _own_blocks(bb[k], by_i[k].get("saved")) if k in by_i else None
        claims = claims_of[k]
        if claims and any(_alike(o, cb[x]) for o in claims):
            return False
        if (i, html) not in page_of:
            page_of[(i, html)] = _prose(_apply_one(bb[i].content, html)[0])
        page = page_of[(i, html)]
        return not Counter(_WORD_RE.findall(_prose(cb[x].content))) - Counter(_WORD_RE.findall(page))

    taken, todo, in_todo = set(), [], {}    # in_todo: where each edit's step is in `todo`
    for e in edits:
        i = int(e["i"])
        j, mode = plan[i]
        width, place, rows, merged, back = 1, None, None, None, None
        page_blocks = None if mode == "gone" else _own_blocks(bb[i], e.get("saved"))
        if page_blocks:
            def free(x):
                return x not in taken and (paired.get(x, i) == i or moves(x, i, page_blocks, e["html"]))

            place = _own_span(page_blocks, cb, j)
            if place and not all(free(x) for x in range(place[0], sum(place))):
                place = None
            if not place and len(page_blocks) > 1:
                rows = _own_rows(page_blocks, cb, j, free)
                # A block that moves to this edit says the page's words; one the file changed stays the other's.
                if rows and all(r.how == "same" for r in rows if r.other is not None and paired.get(r.other, i) != i):
                    xs = [r.other for r in rows if r.other is not None]
                    place = xs[0], xs[-1] - xs[0] + 1
        # An edit put back among the page's own blocks or before them that comes after them on the page goes after
        # them (the file deleted the block after the split, and added one, so the merge paired it with none); one
        # that comes before them leaves them.
        among = [(g, gi) for g, gi in put_back if place and (place[0] < g < sum(place) or (g == place[0] and gi > i))]
        if any(gi < i for _, gi in among):
            place = None
        if place and rows:
            held = {_identity(c) for c in rdc.parse(bb[i].content).comments}
            merged = _own_merge(cb[place[0]:sum(place)], place[0], rows, page_blocks, j, e["html"], held)
            place, back = (place, (j, mode)) if merged else (None, None)
        if place:
            first, n = place
            for x in range(first, first + n):
                k = paired.get(x, i)
                if k != i:
                    # The base block it was paired with by its place goes back as deleted, after the page's own
                    # blocks when it comes after them and before them when it comes before.
                    plan[k] = (first + n if k > i else first, "gone")
                    if k in by_i:
                        put_back.append((plan[k][0], k))
                    if k in in_todo:
                        todo[in_todo[k]] = _Step(start=first, mode="gone", i=k, html=by_i[k]["html"])
                paired[x] = i
            for g, gi in among:
                plan[gi] = (first + n, "gone")
                put_back[put_back.index((g, gi))] = (first + n, gi)
            taken |= set(range(first, first + n))
            j, mode, width = first, "same", n
        in_todo[i] = len(todo)
        todo.append(_Step(start=j, mode=mode, i=i, html=e["html"], width=width, merged=merged, back=back))
    # From the end backwards, so every target index still points where it did.
    # At a shared index the block that is there goes first and the re-inserted
    # ones after it, later base blocks first, so each lands before it and they
    # keep their order.
    todo.sort(key=lambda t: (t.start, t.mode != "gone", t.i), reverse=True)

    # A deleted paragraph keeps its place as this line until the last edit is in. Taken
    # out at once it can leave its neighbours one block (two lists, say), and the next
    # edit, which counts blocks from the start, overwrites both.
    tomb = ""
    while not tomb or tomb in base_text + cur_text:
        tomb = f"<!--sheaf-merge-{os.urandom(6).hex()}-->"
    text, changed, skipped, conflicts, toggled = cur_text, [], [], [], []
    for t in todo:
        j, mode, i, html, width = t.start, t.mode, t.i, t.html, t.width
        blocks = split_md_blocks(text)
        if t.merged:
            region, notes = t.merged
            # An empty region keeps its place as the tomb line, as a deleted block does, until the last edit is in.
            done = _splice(text, blocks, j, width, region or tomb + "\n")
            if done is not None:
                if done != text:
                    changed.append(i)
                text = done
                for k, words in reversed(notes):
                    text = _note(text, j + k, _both_note(words), at, base_text, cur_text)
                if notes:
                    conflicts.append({"i": i, "kind": "both"})
                continue
            (j, mode), width = t.back, 1
        if mode == "gone":
            # Deleted on disk while being edited here. The edit is made on the base
            # block alone, so it cannot meet the file's text, and what it says is put
            # where the block was.
            text = _restore(text, blocks, j, i, bb[i], html, tomb, at, (base_text, cur_text),
                            changed, skipped, conflicts)
            continue
        if mode == "both" and not blocks[j].editable:
            # The file turned the paragraph into a block the page cannot write to (a
            # fence, an image, raw html). Its bytes stay; what the page said goes into
            # a note on it, so that nothing typed is lost. An edit that says what the
            # base said, or nothing, has nothing to keep.
            page = "" if not _apply_one(bb[i].content, html)[1]["changed"] \
                else _page_text(html)
            if page.strip():
                text = _note(text, j, LOCKED_NOTE + "\n\n" + page, at, base_text, cur_text)
                changed.append(i)
                conflicts.append({"i": i, "kind": "locked"})
            continue
        theirs = _prose(blocks[j].content)
        try:
            theirs_quote = rdc.projection(blocks[j].content).text[-60:]
        except Exception:
            theirs_quote = ""
        # Comments someone else added to this block while it was being edited are
        # not in the page's HTML; lift them out so the edit does not orphan them.
        # A comment is the base's when its id, author, time and words are; one that has only
        # the id of a comment the file deleted is new, and the page's anchor for the old one
        # must not be bound to it.
        held = {_identity(c) for c in rdc.parse(bb[i].content).comments}
        current = _width_text(blocks, j, width)
        # A box counts as ticked by this save (SPEC 9.11) only when the file's block is still the one the
        # page held: else the page's boxes are compared with boxes someone else changed since.
        as_held = width == 1 and current == bb[i].content
        content, lifted = _lift(current, held)
        if lifted:
            pos = sum(len(x.text) for x in blocks[:j])
            text = text[:pos] + content + text[pos + len(current):]
        n_before = len(split_md_blocks(text))
        text, rep = apply_edits(text, [{"i": j, "html": html}], _tomb=tomb, _width=width, _named=True)
        skipped += [(i, why) for _, why in rep["skipped"]]
        if as_held:
            toggled += rep["toggled"]
        # The edit of `width` blocks is now blocks j .. j + grown.
        grown = len(split_md_blocks(text)) - n_before + width - 1
        if rep["changed"] and (j in rep["deleted"] or not _bare(split_md_blocks(text)[j].content)):
            # The page deleted this paragraph. What the file put on it is not hidden
            # by that: the comments, and the note about the file's version, become
            # orphans where it was, as in `apply_edits`; they never move onto the
            # paragraph that took its place.
            changed.append(i)
            text = _put_orphans(text, j, [c for _, _, c, _ in lifted])
            if mode == "both":
                conflicts.append({"i": i, "kind": "both"})
                note = rdc.Comment(
                    id=_next_id(text, base_text, cur_text), by=MERGE_BY, at=at, status="open",
                    quote=theirs_quote, body=_both_note(theirs.strip()))
                text = _put_orphans(text, j, [note])
            continue
        if rep["changed"]:
            changed.append(i)
        text, lost = _put_lifted(text, lifted, j, grown)
        if lost:
            text = _put_orphans(text, lost[0][0], [c for _, c in lost])
        if mode == "both" and rep["changed"]:
            conflicts.append({"i": i, "kind": "both"})
            text = _note(text, j, _both_note(theirs.strip()), at, base_text, cur_text)
    if tomb in text:
        text = _drop_tombstones(text, tomb)
    return text, {"changed": changed, "skipped": skipped, "remap": True,
                  "merged": True, "conflicts": conflicts, "toggled": toggled}


def map_block(base_text: str, cur_text: str, i: int):
    """Where block i of base_text is in cur_text, if its prose is unchanged; else None."""
    from difflib import SequenceMatcher

    bb, cb = split_md_blocks(base_text), split_md_blocks(cur_text)
    sm = SequenceMatcher(None, [_prose(b.content) for b in bb],
                         [_prose(b.content) for b in cb], autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal" and i1 <= i < i2:
            return j1 + (i - i1)
    return None
