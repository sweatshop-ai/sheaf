"""Task boxes in ordered items (SPEC 7.2).

GitHub draws a box for `1. [ ] words`; pandoc's gfm reader draws one for a bullet only and leaves the characters
`[ ] words` in the item. The two places that ask pandoc for a page's HTML (`render.pandoc_html` and the source render
of `edit`) therefore swap the mark of an ordered item for a stand-in before pandoc reads the source (`hide`) and
turn the stand-in at the start of an item back into the markup pandoc writes for a bullet task (`show`); a stand-in
anywhere else (code, an item with no words) goes back to the characters it was.
"""
import re

_OPEN, _CLOSE = "", ""
# The marker of an ordered item, behind any list or quote markers on its line (as `edit.TASK_MARK_RE` for a bullet).
_MARK = re.compile(
    r"^([ \t]*(?:(?:[-*+]|\d{1,9}[.)])[ \t]+|>[ \t]*)*\d{1,9}[.)][ \t]+)\[([ xX])\](?=[ \t]|$)", re.M)
_STAND_IN = re.compile(_OPEN + r"([ xX])" + _CLOSE)
# An item opens with the stand-in, then words (or an inline tag): an item with nothing after it stays the characters.
_ITEM = re.compile(r"(<li>(?:<p>)?)" + _OPEN + r"([ xX])" + _CLOSE + r"[ \t]*(?=[^<\s]|<(?!/))")
_LABEL_END = re.compile(r"</p>|\n?<[uo]l\b|</li>")


def hide(src: str) -> str:
    """`src` with the `[ ]` of each ordered item swapped for a stand-in. Left alone when it holds the stand-in already."""
    if _OPEN in src or _CLOSE in src:
        return src
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
        end = _LABEL_END.search(html, m.end())
        if end is None:
            continue
        out.append(html[last:m.start()])
        out.append(_box(m) + html[m.end():end.start()] + "</label>")
        last = end.start()
    out.append(html[last:])
    html = "".join(out)
    return _STAND_IN.sub(lambda m: f"[{m.group(1)}]", html)
