"""The copy block (SPEC 6.8): a quote whose first line is `[!COPY]`.

An agent writes a mail, a title or a prompt in one, and the page draws it as a quote with a Copy button.
Three places need to agree on what the marker is: the render takes it off the words and marks the quote,
a save puts it back (the page never held it), and a comment's offsets skip it. The button itself is the
page's (page.js); the share copy and the PDF get a plain quote.

pandoc turns the line break after the marker into a space, so the HTML cannot tell `> [!COPY]` from
`> [!COPY] words`. The marker line is therefore swapped for a word of this module's before pandoc reads the
source (`hide`), and that word is what `mark` finds in the HTML.
"""
import re

from .blocks import split_md_blocks

MARKER = "[!COPY]"
PAGE_CLASS = "rd-copy"
BUTTON_CLASS = "rd-copybtn"
STAND_IN = "RDCOPYMARKQX7"

# The first line of a top-level quote, and then at least one line with words.
_LINE = re.compile(r"(\s{0,3}>[ \t]?)" + re.escape(MARKER) + r"[ \t]*(?=\r?(?:\n|$))")
_WORDS = re.compile(r"^[ \t>]*[^\s>]", re.M)


def is_copy_block(content: str) -> bool:
    """Is this block of the source (a quote, without the blank lines after it) a copy block?"""
    first, _, rest = content.partition("\n")
    return bool(_LINE.fullmatch(first.rstrip("\r")) and _WORDS.search(rest))


def hide(src: str) -> str:
    """`src` with the marker line of each copy block swapped for STAND_IN, for pandoc."""
    if MARKER not in src:
        return src
    out = []
    for b in split_md_blocks(src):
        if b.kind == "quote" and is_copy_block(b.content):
            out.append(_LINE.sub(lambda m: m.group(1) + STAND_IN, b.content, count=1) + b.gap)
        else:
            out.append(b.text)
    return "".join(out)


_START = re.compile(rf"<blockquote>(\s*)<p>{STAND_IN}(</p>\s*|\s+)")


def mark(fragment: str, page: bool) -> str:
    """`fragment`, pandoc's HTML of a source passed through `hide`, with the marker word taken off each copy
    block: the quote carries `class="rd-copy"` on the page and nothing in a share copy."""
    if STAND_IN not in fragment:
        return fragment
    open_tag = f'<blockquote class="{PAGE_CLASS}">' if page else "<blockquote>"
    fragment = _START.sub(lambda m: open_tag + m.group(1) + ("" if m.group(2).startswith("</p>") else "<p>"),
                          fragment)
    return fragment.replace(STAND_IN, MARKER)      # a word left anywhere else (not first in its quote) shows as the marker


# A page block's copy blocks go to pandoc with a paragraph of STAND_IN first in each, which comes back as the
# marker line, so the quote reads `> [!COPY]` and then its words, as an agent wrote it.
_TOKEN_LINE = re.compile(rf"^([ \t]*(?:>[ ]?)+){STAND_IN}\n(?:[ \t]*(?:>[ ]?)+\n)?", re.M)


def tokenize(fragment: str) -> str:
    """The page's HTML for one block, each `blockquote.rd-copy` given its marker paragraph again."""
    if PAGE_CLASS not in fragment:
        return fragment
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(fragment, "html.parser")
    for q in soup.select(f"blockquote.{PAGE_CLASS}"):
        p = soup.new_tag("p")
        p.string = STAND_IN
        q.insert(0, p)
    return str(soup)


def restore(md: str) -> str:
    """pandoc's markdown for a tokenized block, the marker paragraphs written as `[!COPY]` lines."""
    return _TOKEN_LINE.sub(lambda m: m.group(1) + MARKER + "\n", md) if STAND_IN in md else md


def skipped(block: str) -> int:
    """How many non-whitespace characters of a block's rendered text the page does not show: the marker's."""
    return len(MARKER) if is_copy_block(block) else 0
