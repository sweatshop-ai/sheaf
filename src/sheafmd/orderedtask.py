"""Task boxes in ordered items (SPEC 7.2).

GitHub draws a box for `1. [ ] words`; pandoc's gfm reader draws one for a bullet only and leaves the characters
`[ ] words` in the item. The two places that ask pandoc for a page's HTML (`render.pandoc_html` and the source render
of `edit`) therefore swap the mark of an ordered item for a stand-in before pandoc reads the source (`hide`) and
turn the stand-in at the start of an item back into the markup pandoc writes for a bullet task (`show`); a stand-in
anywhere else (code, an item with no words) goes back to the characters it was.
"""
import re

_OPEN, _CLOSE = "\ue000", "\ue001"   # private-use characters: no document has them
STAND_IN_OPEN, STAND_IN_CLOSE = _OPEN, _CLOSE
# The marker of an ordered item, behind any list or quote markers on its line (as `edit.TASK_MARK_RE` for a bullet).
_MARK = re.compile(
    r"^([ \t]*(?:(?:[-*+]|\d{1,9}[.)])[ \t]+|>[ \t]*)*\d{1,9}[.)][ \t]+)\[([ xX])\](?=[ \t]+\S)", re.M)
# (the mark of an item with nothing after it on its line is not swapped: it stays the characters, as `show` leaves it)
_STAND_IN = re.compile(_OPEN + r"([ xX])" + _CLOSE)
# An item opens with the stand-in, then words (or an inline tag): an item with nothing after it stays the characters.
_ITEM = re.compile(r"(<li>(?:<p>)?)" + _OPEN + r"([ xX])" + _CLOSE + r"[ \t]*(?=[^<\s]|<(?!/))")
# the label ends where the item's words do: at the end of the paragraph, or before a block that follows them
_LABEL_END = re.compile(r"</p>|\n?<(?:[uo]l|pre|blockquote|table|hr|h[1-6]|div|figure|dl)\b|</li>")
# What the label's end is looked for in: a comment, skipped whole, or a tag, its quoted values taken whole. Pandoc
# passes raw HTML through as the source wrote it, and CommonMark takes a tag as raw HTML only when a value that holds
# `<`, `>` or white space is quoted, so `</p>` in a value or a comment is no end.
_COMMENT_OR_TAG = re.compile(r"<!--[\s\S]*?-->|<[^<>\"']*(?:(?:\"[^\"]*\"|'[^']*')[^<>\"']*)*>")


def _label_end(html: str, pos: int):
    """Where the label that starts at `pos` ends: the offset of its end (`_LABEL_END`), or None."""
    for m in _COMMENT_OR_TAG.finditer(html, pos):
        if m.group(0).startswith("<!--"):
            continue
        at = m.start() - 1 if m.start() > pos and html[m.start() - 1] == "\n" else m.start()
        end = _LABEL_END.match(html, at) or _LABEL_END.match(html, m.start())
        if end is not None:
            return end.start()
    return None


def hide(src: str) -> str:
    """`src` with the `[ ]` of each ordered item swapped for a stand-in. Left alone when it holds the stand-in already."""
    if _OPEN in src or _CLOSE in src:
        return src
    # Pandoc deletes every CR before it reads anything (`1. [ \r] a` is a task to it): the mark is read as pandoc reads it.
    src = src.replace("\r", "")
    return _MARK.sub(lambda m: f"{m.group(1)}{_OPEN}{m.group(2)}{_CLOSE}", src)


def _box(m: re.Match) -> str:
    box = '<label><input type="checkbox"' + (' checked=""' if m.group(2) != " " else "") + " />"
    return m.group(1) + box


def show(html: str) -> str:
    """Pandoc's HTML of `hide(src)` with a box for each item that opens with a stand-in, and the characters back
    for each stand-in left."""
    if _OPEN not in html:
        return html
    out, last = [], 0
    for m in _ITEM.finditer(html):
        end = _label_end(html, m.end())
        if end is None:
            continue
        out.append(html[last:m.start()])
        out.append(_box(m) + html[m.end():end] + "</label>")
        last = end
    out.append(html[last:])
    html = "".join(out)
    return _STAND_IN.sub(lambda m: f"[{m.group(1)}]", html)
