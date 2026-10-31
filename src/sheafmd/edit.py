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
import os
import re
from collections import Counter
from typing import NamedTuple

from . import _pandoc
from . import comments as rdc
from . import diagnostics
from .blocks import LOCKED_KINDS, split_md_blocks
from .sanitize import sanitize


class EditError(Exception):
    pass


# Transforms sheaf applies on the way out that must be undone on the way
# back in, or the markdown would inherit presentation artefacts.
def _sanitize(fragment: str, source=None, strays=None) -> str:
    """`source`, the block's markdown, and `strays`, a list, are for a save: markup the browser wrote that the
    source did not have is unwrapped, and each one is named in `strays`."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(fragment, "html.parser")

    # Rendering-only wrappers and artefacts of edit mode itself
    for div in soup.select("div.tblwrap"):
        div.unwrap()
    _lines_as_paragraphs(soup)
    _lines_as_items(soup)
    _drop_empty_task_items(soup)
    if source is not None:
        _unwrap_strays(soup, source, strays)
    for el in soup.select("[contenteditable]"):
        del el["contenteditable"]
    for el in soup.select(".rd-lock, .rd-blockmark"):
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
    a target and a rel, are dropped. What the block's source had stays as it is, in the same number and with
    the same attributes. The page's own markup (`_page_own`) is left alone."""
    from bs4 import BeautifulSoup

    def key(el):
        return (el.name, tuple(sorted((k, str(v)) for k, v in el.attrs.items())))

    had = Counter(key(el) for el in BeautifulSoup(source, "html.parser").find_all(True))
    for el in soup.find_all(True):
        if _page_own(el):
            continue
        k = key(el)
        if had[k] > 0:
            had[k] -= 1
            continue
        plain_b = (el.name in ("b", "strong")
                   and re.search(r"font-weight:\s*(normal|400)", el.get("style", "")))
        if el.name in ("div", "span") or plain_b:
            if el.name == "div":
                # A line: its words stay apart from the text around it.
                prev, nxt = el.previous_sibling, el.next_sibling
                if prev is not None and getattr(prev, "name", None) not in ("br", "div") and str(prev).strip():
                    el.insert_before(soup.new_tag("br"))
                if nxt is not None and getattr(nxt, "name", None) != "br" and str(nxt).strip():
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


def _lines_as_items(soup) -> None:
    """Each line typed after Enter in a task item, as a task item after it. The browser writes a <div> inside
    the <li>, which pandoc would keep as raw <div> lines. The line has a box of its own; one typed as
    `- [ ] words` or `- [x] words` is that box and those words. Words after a line, outside
    any, are an item of their own, and a line with nothing in it is none."""
    from bs4 import NavigableString

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
                at = next((k for k, c in enumerate(kids) if is_line(c)), None)
                if at is not None:
                    moved = kids[at:] + (list(box.next_siblings) if box is not wrap else [])
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
                m = _TYPED_TASK.match(first) if isinstance(first, NavigableString) else None
                own = ""  # the words before the first list, block or line: pandoc writes a box before one as a character
                for t in item.find_all(string=True):
                    if t.find_parent(["ul", "ol", "blockquote", "pre", "table", "div", "p"]):
                        break
                    own += t
                if m and not (_shows(own[m.end():]) or item.find("img")):
                    # a typed box with no words after it is words itself, as in a paragraph: an item without a box
                    last.insert_after(item)
                    last = item
                    continue
                if m:
                    first.replace_with(NavigableString(first[m.end():]))
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
# The shape of a shortcode that GFM's emoji extension reads as its emoji (`:b:`, `:+1:`); a lone colon is none.
SHORTCODE_RE = re.compile(r":[a-z0-9_+-]+:")


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
    and the words stay the heading."""
    from bs4 import NavigableString

    def is_line(el):
        return getattr(el, "name", None) == "div" and not _page_own(el)

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
        out, run = [], []

        def close():
            if any(not blank(c) for c in run):
                d = soup.new_tag("div")
                for c in run:
                    d.append(c)
                out.append(d)
            run.clear()
        for c in list(line.children):
            c.extract()
            if is_line(c):
                close()
                out.extend(lines_of(c))
            else:
                run.append(c)
        close()
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
        # Where the host's own words start: the first child that is neither a line nor white space (0, none
        # moves, when there is no such child). The lines before them in a heading go above it. A paragraph
        # needs no such care: emptied by its lines going after it, it says nothing and drops out of the .md,
        # where a heading would stay as an empty `## `.
        words = next((k for k, c in enumerate(kids) if not (is_line(c) or blank(c))), 0)
        above = [c for c in kids[:words] if is_line(c)] if host.name != "p" else []
        for c in above:
            c.extract().name = "p"
            host.insert_before(c)
        last, loose, made = host, None, above + [host]
        for c in list(host.children):
            if is_line(c):
                c.extract().name = "p"
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


_COMMENT_TOKEN = re.compile(r"RDCMT[0-9A-F]{10}")  # a comment on its way through pandoc (`_convert_with_comments`)
_TYPED_TASK = re.compile(r"^[-*][ \u00a0]\[([ \u00a0xX])\][ \u00a0\u200b-\u200d\u2060\ufeff]+")
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


def _typed_tasks(fragment: str) -> str:
    """A paragraph that starts `- [ ] `, `- [x] ` or `* [ ] ` was typed as a task line: it becomes a
    list item with a box, which `_boxes_as_text` and pandoc then write as `- [ ] words`. Only a top-level
    paragraph is looked at, and only the start of its text: a code block, a quote and a `[ ]` mid-sentence are words.
    It runs before `_boxes_as_text`, which turns the boxes made here into the characters pandoc reads back."""
    from bs4 import BeautifulSoup, NavigableString

    soup = BeautifulSoup(fragment, "html.parser")
    done = False
    for p in [el for el in soup.contents if getattr(el, "name", None) == "p"]:
        first = next(iter(p.contents), None)
        m = _TYPED_TASK.match(first) if isinstance(first, NavigableString) else None
        # words after the box, anywhere in the paragraph: a break, a comment or an empty mark is none
        if not m or not (_shows(_COMMENT_TOKEN.sub("", p.get_text()[m.end():])) or p.find("img")):
            continue
        first.replace_with(NavigableString(first[m.end():]))
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

    cleared = []
    for br in reversed(soup.find_all("br")):
        block = block_ended_by(br)
        if block is not None and not any(block is b for b in cleared):
            cleared.append(block)
            br.decompose()
    if (not soup.get_text().strip()
            and all(el.name in _EMPTY_SHELL for el in soup.find_all(True))):
        return ""
    return str(soup)


def _cell_breaks(fragment: str):
    """(the fragment with each line break in a table cell as a token, the token or None). A GFM table cell
    holds one line, so pandoc writes a table with a break in a cell as raw HTML, a block the page cannot
    edit; Enter in a cell writes one there. The token comes back as <br>, which GFM takes in a cell as it
    is. The no-break space Enter leaves at the cut goes, and a break that ends its cell shows nothing and
    goes too. A break in code is the code's."""
    from bs4 import BeautifulSoup, NavigableString

    def ends_its_cell(br, cell):
        # Nothing but white space and breaks after it in its cell; a comment node is something the cell holds.
        for x in br.next_elements:
            if cell not in x.parents:
                return True
            if (x.strip() if type(x) is NavigableString else x.name != "br"):
                return False
        return True

    if "<br" not in fragment:
        return fragment, None
    soup = BeautifulSoup(fragment, "html.parser")
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
        if ends_its_cell(br, br.find_parent(["td", "th"])):
            br.decompose()
            continue
        for t, end in ((br.previous_sibling, True), (br.next_sibling, False)):
            if type(t) is NavigableString:
                _cut(t, end)
        br.replace_with(token)
    return str(soup), token


def html_block_to_md(fragment: str, source=None, strays=None) -> str:
    """Convert one edited HTML block back to GitHub-flavoured markdown. With `source`, the block's markdown,
    markup the source did not have is unwrapped (`_unwrap_strays`) and named in `strays`."""
    _reject_irreversible(fragment)
    # The page sends each block's outerHTML as the tab holds it, so what reaches pandoc
    # goes through the 9.5 sanitiser first: no handler, no script address, no element
    # that can run, and the .md never holds active markup a tool without a sanitiser
    # of its own would show. Task boxes and comments survive it; a paragraph typed as
    # `- [ ] words` becomes a task item (`_typed_tasks`).
    clean = _without_placeholder_breaks(_boxes_as_text(_typed_tasks(sanitize(_sanitize(fragment, source, strays)))))
    if not clean.strip():
        return ""
    cells, token = _cell_breaks(clean)
    r = _pandoc.run(["-f", "html", "-t", "gfm", "--wrap=none"], cells)
    if token is not None and r.returncode == 0 and r.stdout.count(token) != cells.count(token):
        # Pandoc's writer takes a character after a backslash it escapes, here one of the token's: the table goes
        # as it went before, as raw HTML, with every character of the cell.
        r, token = _pandoc.run(["-f", "html", "-t", "gfm", "--wrap=none"], clean), None
    if r.returncode != 0:
        raise EditError(f"pandoc: {r.stderr.strip()[:200]}")
    out = r.stdout if token is None else r.stdout.replace(token, "<br>")
    # Pandoc's gfm writer wraps every bare URL as <https://...>. GFM autolinks a bare
    # URL anyway, so the two render identically - but the angle brackets show up as
    # noise on every line of a table the moment one cell is edited. Unwrap them. The
    # scheme makes the match unambiguous against real tags.
    out = re.sub(r"<(https?://[^>\s]+)>", r"\1", out)
    return out.strip("\n")


def _norm_html(fragment: str) -> str:
    """Whitespace- and attribute-normalised HTML, for comparing two renders."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(fragment, "html.parser")
    for el in soup.find_all(True):
        for attr in ("id", "class"):
            if attr in el.attrs:
                del el[attr]
    return re.sub(r"\s+", " ", str(soup)).strip()


def _comparable(block, fragment: str):
    """(page fragment, source render) reduced to the same terms, or None."""
    r = _pandoc.run(["-f", "gfm", "-t", "html5", "--no-highlight"], block.content)
    if r.returncode != 0:
        return None
    # The page shows each comment as an anchor span; the source render has the
    # comment itself. Reduce both to the same marker, or every commented block
    # would look edited and go through pandoc on every save.
    src = COMMENT_HTML_RE.sub(lambda m: f"<!--RDA:{m.group(1)}-->", r.stdout)
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
# (bullets, wrapping, a capital X), so one tick would touch every line.
TASK_MARK_RE = re.compile(
    r"^((?:[ \t]*>)*[ \t]*(?:[-*+]|\d{1,9}[.)])[ \t]+)\[([ xX])\](?=[ \t]|$)", re.M)


def _ticks(fragment: str):
    """(box states in document order, the HTML with every box unticked)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(fragment, "html.parser")
    states = []
    for el in soup.select('input[type="checkbox"]'):
        states.append(el.has_attr("checked"))
        del el["checked"]
    return states, str(soup)


def _toggle_boxes(block, fragment: str):
    """The block with its task marks flipped, when the page changed nothing but
    which boxes are ticked. None otherwise, and then the edit is converted as usual."""
    if "checkbox" not in fragment:
        return None
    both = _comparable(block, fragment)
    if both is None:
        return None
    try:
        want, frag = _ticks(both[0])
        have, src = _ticks(both[1])
        if not have or want == have or len(want) != len(have):
            return None
        if _norm_html(frag) != _norm_html(src):
            return None
    except Exception:
        return None
    # The marks found in the source must be the boxes the render drew, one for
    # one, or a tick could land on the wrong line (a `- [ ]` inside a code
    # block in the list, say). Any doubt and the edit takes the general path.
    marks = list(TASK_MARK_RE.finditer(block.content))
    if [m.group(2) != " " for m in marks] != have:
        return None
    out = block.content
    for m, w, h in reversed(list(zip(marks, want, have))):
        if w != h:
            out = out[:m.start(2)] + ("x" if w else " ") + out[m.end(2):]
    return out


def ticked_html(block, k: int, tick: bool = True):
    """The block as the page would send it with its `k`th task box ticked (unticked, with `tick` false), for a
    tick made away from the page (the list's row, SPEC 9.10): saved like the page's own, it takes the
    `_toggle_boxes` path and flips that one mark. None when the box is ticked already (unticked already), or when
    that path would not be the one taken (the marks are not the boxes drawn, a comment is in the way): a save would
    then go through pandoc."""
    from bs4 import BeautifulSoup

    if not block.editable:
        return None
    r = _pandoc.run(["-f", "gfm", "-t", "html5", "--no-highlight"], block.content)
    if r.returncode != 0:
        return None
    # The page shows each comment as its anchor; the anchor is what keeps the comment through a save.
    soup = BeautifulSoup(COMMENT_HTML_RE.sub(
        lambda m: f'<span class="rd-anchor" data-rd-id="{m.group(1)}"></span>', r.stdout), "html.parser")
    found = soup.select('input[type="checkbox"]')
    marks = list(TASK_MARK_RE.finditer(block.content))
    if not 0 <= k < min(len(found), len(marks)) or found[k].has_attr("checked") == tick:
        return None
    if tick:
        found[k]["checked"] = ""
    else:
        del found[k]["checked"]
    fragment = str(soup)
    want = block.content[:marks[k].start(2)] + ("x" if tick else " ") + block.content[marks[k].end(2):]
    return fragment if _toggle_boxes(block, fragment) == want else None


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

    A sheaf comment is one `comments.parse` accepted. One it refused (no id, an
    unknown status, a repeated key or id) has no anchor in the page and is nobody's
    to rewrite, so it is kept byte for byte like a comment from another tool; the
    person who must fix it is told by `sheaf comments`, and an edit of the
    paragraph beside it is no reason to delete it. Matched by occurrence, so of two
    comments with one id the first is the comment and the second is kept."""
    mine = Counter(content[c.start:c.end] for c in rdc.parse(content).comments)
    found = []
    for m in CODE_OR_COMMENT_RE.finditer(content):
        raw = m.group(0)
        if not raw.startswith("<!--"):
            continue
        if mine[raw]:
            mine[raw] -= 1
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

    def walk(node):
        if isinstance(node, dict):
            if node.get("t") == "RawInline" and node["c"][0] == "html":
                nodes.append(node)
            else:
                walk(node.get("c"))
        elif isinstance(node, list):
            for x in node:
                walk(x)

    walk(doc["blocks"])
    tags, lone, open_, at = [], [], {}, 0
    for node in nodes:
        raw = seen = node["c"][1]
        # In a table cell pandoc's RawInline has `|` where the source has `\|`, which keeps the cell
        # whole: the tag is the source's bytes.
        found = re.compile(re.escape(raw).replace("\\|", r"\\?\|")).search(content, at)
        if found:
            raw, at = found.group(0), found.end()
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


def _lone_as_text(soup, lone, doc, token) -> dict:
    """Each closing tag of `lone` put in `soup` as a placeholder, after the words it followed in the
    source: {placeholder: the tag's bytes}. The browser drops a closing tag with no opener, so the
    page holds no element for it; its place is found in the page's words, against a render of the
    source with the tag written as its placeholder."""
    import difflib
    import json

    from bs4 import BeautifulSoup, NavigableString

    placed = {}
    for raw, node in lone:
        p = f"\u27e6{token()}\u27e7"
        placed[p] = raw
        node["t"], node["c"] = "Str", p
    r = _pandoc.run(["-f", "json", "-t", "html5", "--no-highlight"], json.dumps(doc))
    if r.returncode != 0:
        return {}
    old, at = "", []
    for t in _texts(BeautifulSoup(r.stdout, "html.parser")):
        for part in re.split("(\u27e6[A-Z0-9]+\u27e7)", str(t)):
            if part in placed:
                at.append((len(old), part))
            else:
                old += part
    new = "".join(_texts(soup))
    same = [b for b in difflib.SequenceMatcher(None, old, new, autojunk=False).get_matching_blocks() if b.size]

    def where(o):
        # After the same words when they are still there, else after the last words before it that are.
        k = 0
        for a, b, n in same:
            if a < o <= a + n:
                return b + o - a
            if a + n <= o:
                k = b + n
        return k

    # From the end, so that the offsets still to place stay where they were; of two at one place, the
    # second goes first and the first lands before it.
    for o, p in reversed(sorted(((where(o), p) for o, p in at), key=lambda x: x[0])):
        cum = 0
        for t in _texts(soup):
            if cum <= o <= cum + len(t) and (o > cum or cum == 0):
                up = [u for u in t.parents if u.name in ("code", "pre")]
                if up:
                    # Never inside code, where it would be the code's words.
                    up[-1].insert_after(p)
                else:
                    t.replace_with(NavigableString(t[:o - cum]), NavigableString(p), NavigableString(t[o - cum:]))
                break
            cum += len(t)
    return placed


def _html_blocks(md: str) -> int:
    """How many HTML blocks pandoc reads in `md`, at any depth."""
    r = _pandoc.run(["-f", "gfm", "-t", "json"], md)
    return r.stdout.count('"t":"RawBlock"') if r.returncode == 0 else -1


def _tags_as_text(content: str, fragment: str, token):
    """(the fragment with each element that stands for a raw tag of `content` written as two
    placeholders around its words, {placeholder: the source's bytes})."""
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
    placed = _lone_as_text(soup, lone, doc, token) if lone else {}
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


def _convert_with_comments(block, fragment: str, strays=None):
    """(new markdown for the block, comments left without text)."""
    parsed = rdc.parse(block.content).comments
    by_id = {c.id: c for c in parsed}
    # Every other HTML comment in the block (another review tool's, a toc
    # directive, an internal note) is not sheaf's to change: it gets the same
    # placeholder trip as a sheaf comment, matched on its exact text.
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
    frag, tags = _tags_as_text(block.content, frag, token)
    new_md = html_block_to_md(frag, block.content, strays)
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
        # The block is gone: every sheaf comment is an orphan, every other comment
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


def _span_text(blocks, i: int, n: int) -> str:
    """Blocks i to i + n - 1 as the content of one: their text, without the blank lines after the last."""
    return "".join(x.text for x in blocks[i:i + n - 1]) + blocks[i + n - 1].content


def _join(blocks, i: int, n: int) -> None:
    """Blocks i to i + n - 1 as one, in block i, the others left empty so that every index holds."""
    b, last = blocks[i], blocks[i + n - 1]
    b.content = _span_text(blocks, i, n)
    b.gap = last.gap
    for x in blocks[i + 1:i + n]:
        x.content = x.gap = ""


def apply_edits(md_text: str, edits, _tomb: str = "", _span: int = 1):
    """Splice edited blocks into the source. Returns (new_text, report).

    `edits` is an iterable of {"i": block index, "html": edited fragment}.
    Blocks not named here are written back byte-for-byte. The report's `toggled` holds, for each
    block whose edit only flipped task marks, its (old, new) content: the hub's Share and Stop James
    count only those (SPEC 9.11).

    `_tomb` and `_span`, for `merge_edits`, which passes one edit: an emptied block becomes this
    one line instead of going, so the block count and every index stay as they were; the edit
    takes the place of the `_span` blocks from its index, which the page's own earlier save made
    of the one block the page still shows (`_own_span`). The page never sends a span.
    """
    blocks = split_md_blocks(md_text)
    changed, skipped, deleted, dropped, toggled = [], [], [], {}, {}

    for e in edits:
        i = int(e["i"])
        toggled.pop(i, None)            # a later edit of the block decides what it holds
        if not (0 <= i and i + _span <= len(blocks)):
            skipped.append((i, "no such block"))
            continue
        locked = next((x for x in blocks[i:i + _span] if not x.editable), None)
        if locked is not None:
            skipped.append((i, f"{locked.kind} blocks are not editable"))
            continue
        if _span > 1:
            _join(blocks, i, _span)
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
    """A row of `_rows`: `own`, the index of a block among the page's own, or None for one the other side
    added; `other`, its index on the other side, or None for one that side does not have; and `how`:
    "same" (the same words), "changed" (paired by their words or place), "gone" or "added"."""
    own: int | None
    other: int | None
    how: str


def _rows(own: list, other: list, pair) -> list:
    """The blocks of `own` against those of `other` (each as its words, comments aside), in order, as
    `_Row`s; `pair` pairs those that are not the same."""
    from difflib import SequenceMatcher

    rows = []
    for tag, a1, a2, b1, b2 in SequenceMatcher(None, own, other, autojunk=False).get_opcodes():
        if tag == "equal":
            rows += [_Row(a1 + d, b1 + d, "same") for d in range(a2 - a1)]
            continue
        b = b1
        for d, p in enumerate(pair(own[a1:a2], other[b1:b2])):
            if p is None:
                rows.append(_Row(a1 + d, None, "gone"))
                continue
            rows += [_Row(None, y, "added") for y in range(b, b1 + p)]
            rows.append(_Row(a1 + d, b1 + p, "changed"))
            b = b1 + p + 1
        rows += [_Row(None, y, "added") for y in range(b, b2)]
    return rows


def _by_own(rows, n: int):
    """`_rows` read by the page's n own blocks: the row of each, and for each of the n + 1 places before,
    between and after them the indices of the blocks the other side added there."""
    each, added, k = [None] * n, [[] for _ in range(n + 1)], 0
    for r in rows:
        if r.own is None:
            added[k].append(r.other)
        else:
            each[r.own], k = r, r.own + 1
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
    the block. When the block ends in code the end of the block is inside the code, and a
    comment block ends on its `-->` line, so there the comment goes on a line of its own
    after the block. Where that is still code (a fence the
    file never closed runs to the end of the file) the comment is text, and
    `sheaf comments` would not list it: it goes on a line of its own above the block."""
    blocks = split_md_blocks(md_text)
    b = blocks[j]
    start = sum(len(x.text) for x in blocks[:j])
    at_off, own_line = len(b.content.rstrip("\n")), False
    q = rdc.squash(quote)
    try:
        proj = rdc.projection(b.content)
        # The last character of a block that ends in code has no place in the source.
        own_line = bool(proj.text) and not proj.chars[len(proj.text) - 1]
        starts = _quote_starts(proj.text, q)
        k = starts[nth] if 0 <= nth < len(starts) else -1
        if k >= 0:
            # A quote anchor_point cannot place raises, and `except` keeps the end of the block.
            at_off = rdc.anchor_point(b.content, k, k + len(q), quote)
            own_line = False
    except Exception:
        pass
    if b.kind in LOCKED_KINDS:
        # Code, raw html, front matter: a comment inside is literal text, and a comment
        # block ends on its `-->` line, so nothing may follow it there.
        own_line = True
    if own_line:
        end = start + len(b.content)
        lead = "" if b.content.endswith("\n") else "\n"
        at = end + len(lead) + 1
        out = md_text[:end] + lead + "\n" + raw + "\n" + md_text[end:]
    else:
        at = start + at_off
        out = md_text[:at] + raw + md_text[at:]
    offset = 0
    for x in split_md_blocks(out):
        if at < offset + len(x.text):
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
    end of it; when none does, the last block that says something (not an orphan or a note
    the edit left after itself), at the end of it."""
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
    return last, 0


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
    return max((rdc.next_id(rdc.parse(t)) for t in texts), key=lambda i: int(i[1:]))


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
    """`apply_edits` of one edit, to the first block of `md` (and the `_span` after it, if given)."""
    return apply_edits(md, [{"i": 0, "html": html}], **kw)


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


def _own_span(own, file_blocks, j: int):
    """(first, count) of the `file_blocks` that are the page's own last save of a base block, its
    blocks `own` (`_own_blocks`): not a change made in the file; None when the file does not hold them
    so. Block j, which the merge paired with the base block, is one of them."""
    n = len(own)
    for first in range(min(j, len(file_blocks) - n), max(j - n + 1, 0) - 1, -1):
        if all(_alike(o, c) for o, c in zip(own, file_blocks[first:first + n])):
            return first, n
    return None


def _own_rows(own, file_blocks, j: int, free):
    """The page's own last save of a base block, `own` (several blocks), where the file has since changed
    one of them or put a block among them: read around file block j over the blocks that `free` says no
    other base block has, as `_rows` with file block indices, a block of `own` paired with a file block
    it does not equal only by their words. None unless block j is one of them, one at least still says
    the page's words, and the file changed one or put one among them."""
    lo = hi = j
    while lo > 0 and free(lo - 1):
        lo -= 1
    while hi + 1 < len(file_blocks) and free(hi + 1):
        hi += 1
    rows = [r if r.other is None else r._replace(other=lo + r.other)
            for r in _rows([_said(o) for o in own], [_said(c) for c in file_blocks[lo:hi + 1]], _align)]
    ends = [r.other for r in rows if r.own is not None and r.other is not None]
    if not ends:
        return None
    # The blocks the file added before the first of them or after the last are not among them.
    rows = [r for r in rows if r.other is None or ends[0] <= r.other <= ends[-1]]
    how = {r.other: r.how for r in rows if r.other is not None}
    if (how.get(j) not in ("same", "changed") or "same" not in how.values()
            or not {"changed", "added"} & set(how.values())):
        return None
    if any(r.how == "same" and not _alike(own[r.own], file_blocks[r.other])
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


def _own_merge(region, first: int, rows, own, j: int, html: str, held):
    """The edit of a base block over `region`, the file blocks from `first` on, which hold the page's own
    last save of it as `rows` (`_own_rows`). The edit takes the place of the page's own blocks, and the
    blocks the file put among them stay where they are. Block j, the one the merge paired with the base
    block, as the file changed it stays where the edit leaves it as the page saved it; where the edit
    changes it too or takes it out, the page's is written with the note. Another block the file changed
    stays after the page's, as where the page's own save is not found. Returns (text, notes): the
    region's new text, without the blank lines after its last block, and [(block in it, the file's
    words)] for the notes; None when it cannot be done so (the edit is refused or deletes it all, or a
    comment would be written twice or lost), and the edit goes where the merge put it."""
    rows = [r if r.other is None else r._replace(other=r.other - first) for r in rows]
    j -= first          # from here on the blocks are counted in the region
    mine = [r.other for r in rows if r.how in ("same", "changed")]
    span = "".join(region[x].text for x in mine)
    content, lifted = _lift(span, held)
    edit_text, rep = _apply_one(content, html, _span=len(mine))
    edited = split_md_blocks(edit_text)
    if rep["skipped"] or not any(_bare(b.content) for b in edited):
        return None
    in_file, file_added = _by_own(rows, len(own))
    in_edit, edit_added = _by_own(_rows([_said(o) for o in own], [_said(b) for b in edited], _pair), len(own))
    pieces, kept, notes, said, beside = [], set(), [], [], []
    owed = None       # the file's words of block j, for the note on the next block of the edit's

    def file_block(x):
        pieces.append(region[x])
        kept.add(x)

    def flush():
        # A block the file changed that is kept beside the page's comes after the page's and the lines
        # without words that follow it (comments left without their text), as it does when the page's own
        # save is not found and the edit is written whole before it.
        while beside:
            file_block(beside.pop(0))

    def edit_block(y, hold=False):
        nonlocal owed
        b = edited[y]
        if _bare(b.content) and not hold:
            flush()
        pieces.append(b)
        if _bare(b.content):
            said.append(len(pieces) - 1)
            if owed is not None:
                notes.append((len(pieces) - 1, owed))
                owed = None

    for k in range(len(own)):
        for x in file_added[k]:
            flush()
            file_block(x)
        for y in edit_added[k]:
            edit_block(y)
        file_row, edit_row = in_file[k], in_edit[k]
        if file_row.how != "changed" or file_row.other != j:
            if edit_row.how != "gone":
                edit_block(edit_row.other)
            if file_row.how == "changed":
                beside.append(file_row.other)
        elif edit_row.how == "same":
            flush()
            file_block(file_row.other)
        else:
            owed = _said(region[file_row.other])
            if edit_row.how == "changed":
                edit_block(edit_row.other)
    for y in edit_added[-1]:
        edit_block(y, hold=True)
    flush()
    for x in file_added[-1]:
        file_block(x)
    if owed is not None:
        if not said:
            return None
        notes.append((said[-1], owed))

    text = "".join((b.content if b.content.endswith("\n") else b.content + "\n") + (b.gap or "\n")
                   for b in pieces[:-1])
    text += pieces[-1].content if pieces[-1].content.endswith("\n") else pieces[-1].content + "\n"
    if [b.content.rstrip("\n") for b in split_md_blocks(text)] != [b.content.rstrip("\n") for b in pieces]:
        return None
    # A comment the file added goes back where its words now are, unless it is in a block of the file's kept whole.
    starts, offset = [], 0
    for x in mine:
        starts.append((offset, x))
        offset += len(region[x].text)
    for raw, quote, c, nth in lifted:
        if [x for at, x in starts if at <= c.start][-1] in kept:
            continue
        k, nth = _written_block(split_md_blocks(text), 0, len(pieces) - 1, quote, nth)
        text = _insert_comment(text, k, raw, quote, nth)
    if len(split_md_blocks(text)) != len(pieces) or _marks(text) != _marks("".join(b.text for b in region)):
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


class _Step(NamedTuple):
    """One edit of a merge as it is written: at file block `at`, in `mode`, the edit of base block `i`
    with its `html`, over `span` file blocks; `merged`, the text `_own_merge` made of them with its notes,
    and `back`, the (block, mode) where the merge put the edit, for when that text no longer fits."""
    at: int
    mode: str
    i: int
    html: str
    span: int = 1
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
    # all `span` of its blocks, when the merge paired none of them with another base block, no other edit has
    # taken one of them and none is put back among them or, coming after it on the page, before them (a paragraph
    # the file deleted); else it goes where the merge put it. One the merge put back as deleted stays so: two such
    # edits can find the same file block for their own. Where the file changed one of several blocks of the page's
    # own save or put one among them, the edit is `merged` with the file's blocks there (`_own_merge`).
    edits = sorted((e for e in edits if 0 <= int(e["i"]) < len(bb) and int(e["i"]) in plan), key=lambda e: int(e["i"]))
    by_i = {int(e["i"]): e for e in edits}
    paired = {j: i for i, (j, mode) in plan.items() if mode != "gone"}
    put_back = [(plan[int(e["i"])][0], int(e["i"])) for e in edits if plan[int(e["i"])][1] == "gone"]

    claims_of, page_of = {}, {}     # by base block k / by edit (i, html): a conversion, which `moves` asks for per file block

    def moves(x, i, own, html):
        """Does file block x go to edit i from the base block the merge paired it with by its place alone? It
        says what one of the page's own blocks of block i says: that base block was deleted in the file, unless
        its own edit of this save claims the block. The file may also have written the page's words over it,
        and they are kept: the edit must keep them too. An edit of that block that comes before block i has its
        step in `todo` already, where the merge put it: on this file block, which it does not claim."""
        k = paired.get(x)
        if k is None or k == i or k not in placed:
            return False
        if not any(_alike(o, cb[x]) for o in own):
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
        span, place, rows, merged, back = 1, None, None, None, None
        own = None if mode == "gone" else _own_blocks(bb[i], e.get("saved"))
        if own:
            def free(x):
                return x not in taken and (paired.get(x, i) == i or moves(x, i, own, e["html"]))

            place = _own_span(own, cb, j)
            if place and not all(free(x) for x in range(place[0], sum(place))):
                place = None
            if not place and len(own) > 1:
                rows = _own_rows(own, cb, j, free)
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
            merged = _own_merge(cb[place[0]:sum(place)], place[0], rows, own, j, e["html"], held)
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
                        todo[in_todo[k]] = _Step(first, "gone", k, by_i[k]["html"])
                paired[x] = i
            for g, gi in among:
                plan[gi] = (first + n, "gone")
                put_back[put_back.index((g, gi))] = (first + n, gi)
            taken |= set(range(first, first + n))
            j, mode, span = first, "same", n
        in_todo[i] = len(todo)
        todo.append(_Step(j, mode, i, e["html"], span, merged, back))
    # From the end backwards, so every target index still points where it did.
    # At a shared index the block that is there goes first and the re-inserted
    # ones after it, later base blocks first, so each lands before it and they
    # keep their order.
    todo.sort(key=lambda t: (t.at, t.mode != "gone", t.i), reverse=True)

    # A deleted paragraph keeps its place as this line until the last edit is in. Taken
    # out at once it can leave its neighbours one block (two lists, say), and the next
    # edit, which counts blocks from the start, overwrites both.
    tomb = ""
    while not tomb or tomb in base_text + cur_text:
        tomb = f"<!--sheaf-merge-{os.urandom(6).hex()}-->"
    text, changed, skipped, conflicts, toggled = cur_text, [], [], [], []
    for t in todo:
        j, mode, i, html, span = t.at, t.mode, t.i, t.html, t.span
        blocks = split_md_blocks(text)
        if t.merged:
            region, notes = t.merged
            done = _splice(text, blocks, j, span, region)
            if done is not None:
                if done != text:
                    changed.append(i)
                text = done
                for k, words in reversed(notes):
                    text = _note(text, j + k, BOTH_NOTE + "\n\n" + words, at, base_text, cur_text)
                if notes:
                    conflicts.append({"i": i, "kind": "both"})
                continue
            (j, mode), span = t.back, 1
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
        mine = _span_text(blocks, j, span)
        # A box counts as ticked by this save (SPEC 9.11) only when the file's block is still the one the
        # page held: else the page's boxes are compared with boxes someone else changed since.
        as_held = span == 1 and mine == bb[i].content
        content, lifted = _lift(mine, held)
        if lifted:
            pos = sum(len(x.text) for x in blocks[:j])
            text = text[:pos] + content + text[pos + len(mine):]
        n_before = len(split_md_blocks(text))
        text, rep = apply_edits(text, [{"i": j, "html": html}], _tomb=tomb, _span=span)
        skipped += [(i, why) for _, why in rep["skipped"]]
        if as_held:
            toggled += rep["toggled"]
        # The edit of `span` blocks is now blocks j .. j + grown.
        grown = len(split_md_blocks(text)) - n_before + span - 1
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
                    quote=theirs_quote, body=BOTH_NOTE + "\n\n" + theirs.strip())
                text = _put_orphans(text, j, [note])
            continue
        if rep["changed"]:
            changed.append(i)
        for raw, quote, _, nth in lifted:
            k, nth = _written_block(split_md_blocks(text), j, grown, quote, nth)
            text = _insert_comment(text, k, raw, quote, nth)
        if mode == "both" and rep["changed"]:
            conflicts.append({"i": i, "kind": "both"})
            text = _note(text, j, BOTH_NOTE + "\n\n" + theirs.strip(), at, base_text, cur_text)
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
