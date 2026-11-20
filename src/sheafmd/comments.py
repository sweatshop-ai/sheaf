#!/usr/bin/env python3
"""
sheafmd.comments — comments stored inline in the markdown.

A comment is an HTML comment placed right after the text it is about:

    The gap is **52%**<!-- sheaf-comment id=c3 by="Ada" at=2026-09-19T14:02 status=open quote="The gap is 52%"
    Source? This looks like the old figure.
    @Claude 2026-09-19T14:30 answer: Re-derived from GSC, 52% holds.
    --> and it matters.

sheaf writes the marker `sheaf-comment` and reads `sheaf-comment` and the older
`rd-comment` as the same thing. A comment keeps the marker it was read with, so
rewriting an old comment does not migrate it. A reply line is
`@<who> <at>[ <role>]: <text>`; the role (`answer` or `action`) is recorded apart
from who wrote the reply (SPEC 5.2, 5.3).

Everything in here exists because pandoc and CommonMark are unforgiving about what
may sit inside an inline HTML comment. Measured with pandoc 3.1.3:

  * "--" anywhere in the text ends the comment early, and the rest renders as
    visible text. So every "--" is written "-&#45;".
  * a blank line ends the paragraph, and the comment with it. So a paragraph break
    inside a comment is written "<br>" at the end of the line before.
  * a continuation line that looks like a block start ("- x", "# x", "1. x", ">")
    starts that block, again in the middle of the comment. So the first character
    of every continuation line that could do this is written as an entity.
  * in a table cell or a heading the whole comment has to stay on one line, and a
    raw "|" splits the cell.
  * a backtick before the comment that has no partner pairs with the first one
    inside it, and the code span between them takes the comment in. So every
    backtick is written "&#96;".

Text is entity-encoded on the way in and decoded on the way out, so what a reader
typed is what they get back, including "&", "<" and "-->".
"""

import bisect
import functools
import html as _html
import re
from dataclasses import dataclass, field

from . import copyblock, orderedtask
from .blocks import SETEXT_RE, TBLSEP_RE, split_md_blocks

CODE_KINDS = {"fence", "indented_code", "frontmatter"}
ONE_LINE_KINDS = {"heading", "table"}
STATUSES = {"open", "resolved"}

# The one place the two markers are spelled. Every pattern that has to recognise a
# comment is built from MARKER, so a `sheaf-comment` is never mistaken for a foreign
# comment (and duplicated by the first edit) by a module that only knew `rd-comment`.
MARKER = r"(?:sheaf|rd)-comment"
WRITE_MARKER = "sheaf-comment"          # what new comments are written with
MARKER_AT_HEAD_RE = re.compile(rf"({MARKER})(?=\s|$)")
COMMENT_RE = re.compile(rf"<!--\s*{MARKER}\b")
ROLES = ("answer", "action")
# A CommonMark code span: a run of backticks, then the text up to the next run of the same
# length (a run, not part of a longer one). A backslash escapes the backtick it precedes, so a
# run after an odd number of them opens nothing there; what is left of an escaped run (one
# backtick shorter) may still open a span. The opening run is found by a pattern and its closer
# by a lookup among the block's runs, so an opener that nothing closes costs one lookup, not a
# search to the end of the block.
_CODE_OPEN_RE = re.compile(r"(?<!\\)(?:\\\\)*(?:(?<!`)|\\`)(`+)(?!`)")
_RUN_RE = re.compile(r"(?<!`)`+(?!`)")


class _CodeSpan:
    """What `re.Match` gives for the one group the callers read: group 1 is the opening run."""
    def __init__(self, a, b):
        self.a, self.b = a, b

    def start(self, group=0):
        return self.a

    def end(self, group=0):
        return self.b


@functools.lru_cache(maxsize=8)
def _runs_by_length(text: str):
    by_len = {}
    for m in _RUN_RE.finditer(text):
        by_len.setdefault(m.end() - m.start(), []).append(m.start())
    return by_len


class _CodeSpanFinder:
    @staticmethod
    def search(text: str, pos: int = 0):
        by_len = _runs_by_length(text)
        for m in _CODE_OPEN_RE.finditer(text, pos):
            k = m.end(1) - m.start(1)
            starts = by_len.get(k, ())
            at = bisect.bisect_left(starts, m.end(1))
            if at < len(starts):
                return _CodeSpan(m.start(1), starts[at] + k)


CODE_SPAN_RE = _CodeSpanFinder()
STRAY_RE = re.compile(r"^[ \t]*-->", re.M)
REPLY_RE = re.compile(r'^@("(?:[^"]*)"|\S+) (\d{4}-\d\d-\d\dT\d\d:\d\d)(?: (answer|action))?:\s?(.*)$',
                      re.S)
FIELD_RE = re.compile(r'\s*([a-z]+)=("([^"]*)"|\S+)')
# First characters that would start a block on a continuation line.
GUARD_FIRST = set("#-*+=_`~|>@0123456789 \t")


@dataclass
class Reply:
    by: str                      # the author exactly as read
    at: str
    text: str
    role: str | None = None      # as written: "answer", "action" or None


# Before roles existed, a Tell's session signed its reply with this author, and an
# Ask's answer was a reply by "Claude" inside an rd-comment (SPEC 5.3, D1).
LEGACY_ACTION_BY = "Claude (action)"
LEGACY_ANSWER_BY = "Claude"


def action_replies(c):
    """How many replies in c's thread came from a Tell's session. A Tell is
    answered only by one of these: a reader's reply or an old Ask answer landing in
    the same thread must not stop the "Claude is working" spinner."""
    return sum(1 for r in c.replies if c.effective_role(r) == "action")


@dataclass
class Comment:
    id: str
    by: str = ""
    at: str = ""
    status: str = "open"
    quote: str = ""
    body: str = ""
    orphan: bool = False
    replies: list = field(default_factory=list)
    # Where it sits in the source it was parsed from.
    start: int = -1
    end: int = -1
    line: int = 0
    block: int = -1
    standalone: bool = False     # on its own line, not after any text
    marker: str = WRITE_MARKER   # the marker it was read with; new comments get the new one

    def display(self, r: Reply) -> str:
        """The name to show for a reply: the author, without the legacy suffix."""
        return "Claude" if r.by == LEGACY_ACTION_BY else r.by

    def effective_role(self, r: Reply) -> str | None:
        """What a reply is, as the page and the hub treat it (SPEC 5.3 table). A
        written role wins; else the two legacy forms are read as the role they
        stood for. A reply by Claude with no role is an answer only inside an
        rd-comment; inside a sheaf-comment it is just a reply."""
        if r.role:
            return r.role
        if r.by == LEGACY_ACTION_BY:
            return "action"
        if r.by == LEGACY_ANSWER_BY and self.marker == "rd-comment":
            return "answer"
        return None

    def as_dict(self):
        return {"id": self.id, "by": self.by, "at": self.at, "status": self.status,
                "quote": self.quote, "body": self.body, "orphan": self.orphan,
                "line": self.line, "block": self.block,
                "replies": [{"by": r.by, "display": self.display(r),
                             "role": self.effective_role(r), "at": r.at, "text": r.text}
                            for r in self.replies]}


@dataclass
class Malformed:
    line: int
    reason: str
    start: int
    end: int
    text: str


@dataclass
class Parsed:
    comments: list
    malformed: list

    def by_id(self, cid):
        for c in self.comments:
            if c.id == cid:
                return c
        return None


# ───────────────────────────────────────────────────────────── encoding ──

def _enc(s: str) -> str:
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = s.replace('"', "&quot;").replace("|", "&#124;")
    s = s.replace("`", "&#96;")
    while "--" in s:
        s = s.replace("--", "-&#45;")
    return s


def _guard(line: str) -> str:
    """Make a continuation line unable to start a markdown block."""
    if line and line[0] in GUARD_FIRST:
        return f"&#{ord(line[0])};" + line[1:]
    if line and line[0].isspace():
        # Other whitespace (\x0b, \xa0, \u2028 ...) is skipped by the block splitter before
        # a marker, so the line would start a block of its own and cut the comment in two.
        return f"&#{ord(line[0])};" + line[1:]
    return line


# html.unescape drops these as a numeric reference (\x0b, \x1c-\x1f) or maps them to another
# character (\x85 to an ellipsis), so a leading one written as &#N; by _guard is read here.
_KEPT_REF_RE = re.compile(r"&#(11|28|29|30|31|133);")


def _dec(s: str) -> str:
    return _html.unescape(_KEPT_REF_RE.sub(lambda m: chr(int(m.group(1))), s))


def _val(v: str) -> str:
    # A line break in a value would end the head's line, and what follows it would be the
    # comment's body (a reader that takes a lone \r for a line break would do the same).
    # Entities read back as the characters they stand for, like every other escape here.
    v = _enc(v).replace("\n", "&#10;").replace("\r", "&#13;").replace("\t", "&#9;")
    return f'"{v}"'


def _who(name: str) -> str:
    # A reply's name is read up to the first whitespace unless it is quoted.
    return _val(name) if (not name or any(ch.isspace() for ch in name)) else _enc(name)


def format(c: Comment, one_line: bool) -> str:
    """The comment as it is written into the markdown."""
    head = f"<!-- {c.marker} id={c.id} by={_val(c.by)} at={c.at} status={c.status}"
    if c.orphan:
        head += " orphan=1"
    head += f" quote={_val(c.quote)}"
    logical = []                      # (encoded text, opens a reply)
    if c.body:
        logical += [(_enc(x), False) for x in c.body.split("\n")]
    for r in c.replies:
        lines = r.text.split("\n")
        role = f" {r.role}" if r.role else ""
        logical.append((f"@{_who(r.by)} {r.at}{role}: {_enc(lines[0])}", True))
        logical += [(_enc(x), False) for x in lines[1:]]
    if one_line:
        return head + "".join("<br>" + (x if rep else _guard(x)) for x, rep in logical) + " -->"
    out = head
    for x, rep in logical:
        out += "<br>" if x == "" else "\n" + (x if rep else _guard(x))
    return out + "\n-->"


# ────────────────────────────────────────────────────────────── parsing ──

def _parse_one(raw: str):
    """(Comment or None, reason). raw runs from '<!--' to '-->' inclusive."""
    inner = raw[4:-3]
    logical = re.split(r"\n|<br>", inner)
    head = logical[0].strip()
    marker = MARKER_AT_HEAD_RE.match(head)
    if not marker:
        return None, "not a sheaf-comment or rd-comment"
    fields, seen = {}, set()
    for m in FIELD_RE.finditer(head[marker.end():]):
        k = m.group(1)
        if k in seen:
            return None, f"duplicate key {k}"
        seen.add(k)
        fields[k] = _dec(m.group(3)) if m.group(3) is not None else m.group(2)
    if not fields.get("id"):
        return None, "missing id"
    status = fields.get("status", "open")
    if status not in STATUSES:
        return None, f"unknown status {status!r}"
    c = Comment(id=fields["id"], by=fields.get("by", ""), at=fields.get("at", ""),
                status=status, quote=fields.get("quote", ""),
                orphan=fields.get("orphan") == "1", marker=marker.group(1))
    body, cur = [], None
    for x in logical[1:]:
        x = x.strip() if x.strip() == "" else x.lstrip()
        m = REPLY_RE.match(x)
        if m:
            who = m.group(1)
            who = _dec(who[1:-1]) if who.startswith('"') else _dec(who)
            cur = Reply(who, m.group(2), _dec(m.group(4)), m.group(3))
            c.replies.append(cur)
        elif cur is not None:
            cur.text += "\n" + _dec(x)
        else:
            body.append(_dec(x))
    # The line that carries "-->" is empty when the writer wrote it.
    while body and body[-1] == "":
        body.pop()
    for r in c.replies:
        r.text = r.text.rstrip("\n").rstrip()
    c.body = "\n".join(body).rstrip()
    return c, ""


_OPENER_RE = re.compile(r"(?<!\\)(?:\\\\)*(<!--)")


def _scan(text: str):
    """What CommonMark reads in `text` at the level of inline code, HTML tags and HTML comments, left
    to right, as (kind, start, end) with kind "code", "tag", "comment", "empty" (`<!-->` and `<!--->`, a whole comment to CommonMark) or "open" (a `<!--` that nothing
    closes: it is text to pandoc and a comment to the rest of the block, so it is reported and the scan goes on). Whichever of the three starts first
    owns what it holds, so a backtick in a tag's attribute or in a comment's body opens no code span
    that runs on into the text after it.     Each search runs once and is reused while its match still lies ahead of the position: a search
    from there finds the same match as one made from an earlier position, so a block of many tags or
    spans is read once, not once per item."""
    pos, found, no_closer = 0, {}, False
    # kind -> (pattern, group): an item starts at the group, which a tag's backslash prefix and
    # an opener's escape check put after the match's own start.
    kinds = {"code": (CODE_SPAN_RE, 1), "tag": (_HTML_TAG_RE, "tag"), "comment": (_OPENER_RE, 1)}
    while True:
        for kind, (rx, group) in kinds.items():
            m = found.get(kind, False)
            if m is None:
                continue                # none now means none later: pos only moves on
            if m is False or m.start(group) < pos:
                found[kind] = rx.search(text, pos)
        ahead = [(m.start(kinds[k][1]), k, m) for k, m in found.items() if m]
        if not ahead:
            return
        a, kind, m = min(ahead)
        if kind != "comment":
            pos = m.end()
            yield kind, a, pos
            continue
        if text.startswith((">", "->"), a + 4):
            pos = a + 5 + (text[a + 4] == "-")
            yield "empty", a, pos
            continue
        else:
            e = -1 if no_closer else text.find("-->", a + 4)
            no_closer = e < 0       # no `-->` after one opener is none after a later one
            if e < 0:
                # Nothing closes it: pandoc reads it as text, so what follows is read on
                # (a code span after it is still code).
                pos = a + 4
                yield "open", a, len(text)
                continue
            pos = e + 3
        yield "comment", a, pos


def _mask_code(text: str, cells: bool = False) -> str:
    """`text` with its inline code spans blanked, the same length (see `_scan` for what owns a
    backtick). `cells`: the text is a table, whose cells pandoc splits at every unescaped `|`
    before it reads a span, so none runs from one cell or row to the next."""
    if "`" not in text:
        return text
    if cells:
        pieces = []
        for line in text.split("\n"):
            pos, parts = 0, []
            for m in _CELL_PIPE_RE.finditer(line):
                parts += [_mask_code(line[pos:m.start(1)]), "|"]
                pos = m.end(1)
            pieces.append("".join(parts) + _mask_code(line[pos:]))
        return "\n".join(pieces)
    parts, last = [], 0
    for kind, a, b in _scan(text):
        if kind == "code":
            parts += [text[last:a], " " * (b - a)]
            last = b
    parts.append(text[last:])
    return "".join(parts)


def _read_block(kind: str, text: str):
    """(masked, raw): `text` with its inline code blanked (`_mask_code`), and the heads of the comments that
    pandoc shows as raw HTML (their places, their heads, the lines that carry a cell), or None for "do not ask".
    A table that a quote or a list holds is read by pandoc (`_read_tables`), which splits its cells before it reads a span, sets the span's range, drops the
    cells beyond the table's columns and reads an indented line as code: where the block may hold one and
    holds a comment, a comment that pandoc does not show as raw HTML is not one."""
    # A table of the document is read by pandoc too (ticket 133): it drops a comment in the alt text of an image and one
    # beyond the table's columns, and reads no table where the header and the delimiter row differ in their cells.
    if kind in ("quote", "list", "table") and COMMENT_RE.search(text) and _may_hold_table(text):
        read = _read_tables(text)
        if read is not None:
            return _blank(text, read[1]), (*read[2], frozenset(read[0]))
    return _mask_code(text, kind == "table"), None


def parse(md: str) -> Parsed:
    comments, malformed, seen = [], [], set()
    pos = 0
    for bi, b in enumerate(split_md_blocks(md)):
        start = pos
        pos += len(b.text)
        if b.kind in CODE_KINDS:
            continue
        text = b.content
        # Inline code is literal text, so a comment written there is an example
        # (this spec has several). Search a copy with code spans blanked out, the
        # same length so every offset still points into the real text.
        masked, raw_heads = _read_block(b.kind, text)
        i = 0
        while True:
            m = COMMENT_RE.search(masked, i)
            if not m:
                break
            a = m.start()
            e = masked.find("-->", m.end())
            line = md.count("\n", 0, start + a) + 1
            if e < 0:
                malformed.append(Malformed(line, "never closed", start + a, start + len(text),
                                           text[a:]))
                break
            e += 3
            raw = text[a:e]
            # A comment on a line that carries a cell is shown by its place alone: its head names a comment that is
            # a block of its own, and a copy that pandoc dropped from a cell is not that one.
            if raw_heads is not None and a not in raw_heads[0] and (
                    text.count("\n", 0, a) in raw_heads[2] or _head_of(raw) not in raw_heads[1]):
                i = e
                continue
            c, why = _parse_one(raw)
            if c is None:
                malformed.append(Malformed(line, why, start + a, start + e, raw))
            elif c.id in seen:
                malformed.append(Malformed(line, f"duplicate id {c.id}", start + a, start + e, raw))
            else:
                seen.add(c.id)
                c.start, c.end, c.line, c.block = start + a, start + e, line, bi
                c.standalone = b.kind == "html" and text[:a].strip() == ""
                comments.append(c)
            i = e
        # The tail of a comment whose first line was deleted: an agent that
        # rewrites a paragraph by replacing its whole line takes the head of a
        # comment with it and leaves the body and the closing "-->" behind, where
        # they render as text. A line that STARTS
        # with "-->" outside every HTML comment is that tail; prose that merely
        # contains an arrow ("A --> B") is not.
        bare = re.sub(r"<!--[\s\S]*?-->", lambda m: re.sub(r"[^\n]", " ", m.group(0)), masked)
        for m in STRAY_RE.finditer(bare):
            line = md.count("\n", 0, start + m.start()) + 1
            malformed.append(Malformed(line, "a closing --> with no opening: the first line "
                                       "of a comment was deleted, and the rest shows as text",
                                       start + m.start(), start + m.end(), "-->"))
    return Parsed(comments, malformed)


def next_id_in(md: str) -> str:
    """The first free `cN` in the document. Pandoc deletes a CR inside the opener of a comment (`<!\r--`, `id\r=c1`) and
    shows the comment, so its id counts, though `parse` does not see it as written: the document is read both ways."""
    return next_id(parse(md), *([parse(md.replace("\r", ""))] if "\r" in md else []))


def next_id(parsed: Parsed, *more: Parsed) -> str:
    """The first free `cN`. `more` are other readings of the same document (without its CRs, say), whose ids count too."""
    n = 0
    for c in [c for p in (parsed, *more) for c in p.comments]:
        m = re.fullmatch(r"c(\d+)", c.id)
        if m:
            n = max(n, int(m.group(1)))
    for mm in [mm for p in (parsed, *more) for mm in p.malformed]:
        m = re.search(r"\bid=c(\d+)", mm.text.replace("\r", ""))
        if m:
            n = max(n, int(m.group(1)))
    return f"c{n + 1}"


# ──────────────────────────────────────── from a selection to the source ──
# A selection in the page gives offsets in RENDERED text: "**52%**" renders as
# "52%", a link as its label, "&amp;" as "&". Pandoc's gfm+sourcepos maps them
# back: it wraps every word and space in a span carrying its source range, inside
# <strong>, links and table cells too (measured with pandoc 3.1.3; columns count
# code points, the same as Python string indices).
#
# Offsets count NON-WHITESPACE characters only. The page and the server render the
# block through different paths, and the whitespace between tags differs between
# them; the visible characters do not.

class AnchorError(Exception):
    pass


class NoComment(AnchorError):
    """No comment has the id a change names: it was never there, or it was deleted."""


class ThreadChanged(AnchorError):
    """The thread under this id is not the one the caller read: ids are the highest plus one, so
    an id is free again once the last comment is deleted."""


def thread_identity(c: Comment) -> tuple:
    """What makes a thread that thread: who wrote it, when, on what passage, and what. Replies
    come and go without changing it."""
    return (c.by, c.at, c.quote, c.body)


BLOCK_TAGS = {"div", "p", "ul", "ol", "li", "table", "thead", "tbody", "tr", "td",
              "th", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "dl",
              "dt", "dd", "hr", "section", "figure", "figcaption", "caption", "colgroup",
              "col"}
VOID_TAGS = {"br", "img", "hr", "input", "col", "wbr", "source", "meta", "link"}
POS_RE = re.compile(r"(\d+):(\d+)-(\d+):(\d+)")
TASK_BOXES = "☐☒"


def squash(s: str) -> str:
    return "".join(s.split())


class _Span:
    __slots__ = ("start", "end", "first", "last")

    def __init__(self, start, end):
        self.start, self.end, self.first, self.last = start, end, -1, -1


class Projection:
    def __init__(self, text, chars):
        self.text = text          # non-whitespace rendered characters, in order
        self.chars = chars        # per character: the inline spans around it, outer first


def _sourcepos_html(block: str) -> str:
    from . import _pandoc
    r = _pandoc.run(["-f", "gfm+sourcepos", "-t", "html", "--wrap=none"], block)
    if r.returncode != 0:
        raise AnchorError(f"pandoc: {r.stderr.strip()[:200]}")
    # Pandoc passes an empty comment opener through as it is, and Python's parser reads it by version: the comment
    # after `<!-->` in a cell was lost on 3.11 and kept on 3.13.18 (nightly of 2026-11-16).
    from .sanitize import _end_empty_comments
    return _end_empty_comments(r.stdout)


def _offset_fn(block: str):
    """The function that turns a pandoc sourcepos (line, column), both from 1, into an offset in `block`."""
    starts = [0]
    for ln in block.split("\n")[:-1]:
        starts.append(starts[-1] + len(ln) + 1)

    def off(line, col):
        line = min(line, len(starts))
        text = block[starts[line - 1]:starts[line] - 1 if line < len(starts) else len(block)]
        if "\t" not in text:
            return min(starts[line - 1] + col - 1, len(block))
        # Pandoc's column counts a tab as the spaces up to the next stop of 4.
        seen = 0
        for i, ch in enumerate(text):
            if seen >= col - 1:
                return starts[line - 1] + i
            seen += 4 - seen % 4 if ch == "\t" else 1
        return min(starts[line - 1] + len(text) + max(0, col - 1 - seen), len(block))
    return off


# A table inside a quote or a list is read by pandoc, not by this module: where the rows are and which
# characters are inline code are what its sourcepos says (`data-pos` on each span of a cell and on each `<code>`),
# so no container marker is read by hand. A table needs a delimiter row, so a block with no line of only
# `|`, `-`, `:`, blanks and the marks of a quote or a list is not sent: one run per block that may hold a table.
_DELIMITER_LINE_RE = re.compile(r"^[ \t\r>\-+*.)0-9:|]*$")


_HEAD_RE = re.compile(rf"<!--\s*{MARKER}\b.*?(?=-->|\n|$)")


def _head_of(raw: str) -> str:
    """What names a comment in the HTML pandoc writes: its first line up to a `-->`."""
    m = _HEAD_RE.match(raw.replace("\r", ""))
    # Pandoc writes a tab of a raw HTML block as spaces up to the tab stop: runs of blanks are one.
    return re.sub(r"[ \t]+", " ", m.group(0) if m else raw)


# A line that may be a heading of a quote or a list: marks of containers, then a `#`.
_HEADING_LINE_RE = re.compile(r"^[ \t>\-+*.)0-9]*#", re.M)


def _container_heading(block: str, point: int):
    """(start, end) offsets of the ATX heading of a quote or a list that holds `point`, as pandoc reads it
    (`_read_tables`): from its hashes to the end of its words, or None."""
    if not _HEADING_LINE_RE.search(block):
        return None
    read = _read_tables(block)
    hit = next((h for h in read[3] if h[0] <= point <= h[1]), None) if read else None
    if hit is None:
        return None
    line_start = block.rfind("\n", 0, hit[0]) + 1
    m = re.search(r"#{1,6}[ \t]*$", block[line_start:hit[0]])
    return (line_start + m.start(), hit[1]) if m else None


def _may_hold_table(block: str) -> bool:
    return "|" in block and any("|" in ln and "-" in ln and _DELIMITER_LINE_RE.match(ln)
                                for ln in block.split("\n"))


@functools.lru_cache(maxsize=16384)
def _read_tables(block: str):
    """(rows, code, raw, heads) as pandoc reads `block`, or None when pandoc fails: `rows` the lines (from 0) that carry a
    cell of a table, `code` the (start, end) offsets of every inline code span, backticks included, `heads` the
    (start, end) offsets of every heading, from the first to the last range pandoc gives it, `raw` the
    starts of the comments that pandoc writes as raw HTML in a span (or, for one that is a block of its own, their heads, `_head_of`): one that it reads as code, drops with
    a cell beyond the table's columns or shows as text is not in it. Pandoc
    deletes a CR and counts columns without it, so it reads the block without its CRs and the offsets are
    given back for the block as it is."""
    from html.parser import HTMLParser

    keep = [i for i, ch in enumerate(block) if ch != "\r"]
    plain = block.replace("\r", "") if len(keep) < len(block) else block
    try:
        html = _sourcepos_html(plain)
    except AnchorError:
        return None
    off = _offset_fn(plain)
    back = (lambda o: keep[o] if o < len(keep) else len(block)) if plain is not block else (lambda o: o)
    rows, code, heads = set(), [], []
    starts, heads_raw = set(), set()

    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []
            self.starts = []       # per open tag, where its range starts, or None
            self.head = None

        def handle_starttag(self, tag, attrs):
            pos = next((v for k, v in attrs if k == "data-pos"), "")
            ranges = [tuple(map(int, m.groups())) for m in POS_RE.finditer(pos)]
            if tag in VOID_TAGS:
                if ranges and self.head is not None:         # an image ends a heading's words as well
                    self.head.append((back(off(ranges[0][0], ranges[0][1])), back(off(ranges[-1][2], ranges[-1][3]))))
                return
            self.stack.append(tag)
            if tag == "code" and "pre" not in self.stack and ranges:
                # A span over several lines has one range per line: the span runs from the first to the last,
                # line breaks and container marks between them included.
                code.append((back(off(ranges[0][0], ranges[0][1])), back(off(ranges[-1][2], ranges[-1][3]))))
            self.starts.append(back(off(ranges[0][0], ranges[0][1])) if ranges else None)
            if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                self.head = []
            elif ranges and self.head is not None:
                # A heading in a list carries the range of the list, not its own: it is read by its words.
                self.head.append((back(off(ranges[0][0], ranges[0][1])), back(off(ranges[-1][2], ranges[-1][3]))))
            if ranges and tag in ("span", "code") and ("td" in self.stack or "th" in self.stack):
                rows.update(a - 1 for a, _, _, _ in ranges)

        def handle_endtag(self, tag):
            if tag in VOID_TAGS:
                return
            if tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self.head is not None:
                if self.head:
                    heads.append((min(a for a, _ in self.head), max(b for _, b in self.head)))
                self.head = None
            while self.stack:
                self.starts.pop()
                if self.stack.pop() == tag:
                    break

        def handle_comment(self, data):
            # Pandoc writes a comment inside a paragraph, a heading or a cell in a span that carries its range:
            # the place names it (the text of its head is changed, a tab to spaces and `\\|` to `|`). One that
            # is a block of its own has no span and is named by its head.
            start = next((a for a in reversed(self.starts) if a is not None), None)
            at = start if start is not None and self.stack and self.stack[-1] == "span" else None
            if at is not None:
                starts.add(at)
            else:
                heads_raw.add(_head_of("<!--%s-->" % data))

    p = P()
    p.feed(html)
    p.close()
    return rows, tuple(code), (frozenset(starts), frozenset(heads_raw)), tuple(heads)


def _blank(text: str, ranges) -> str:
    """`text` with the given (start, end) ranges blanked, the same length."""
    parts, last = [], 0
    for a, b in sorted(ranges):
        if a >= last:
            parts += [text[last:a], " " * (b - a)]
            last = b
    parts.append(text[last:])
    return "".join(parts)


def projection(block: str) -> Projection:
    from html.parser import HTMLParser

    off = _offset_fn(block)

    text, chars, stack = [], [], []
    # A task list item's box comes out as a ☐ or ☒ right after <li>, outside any
    # source span. The page draws a checkbox there, which has no text, so the box
    # must not count: every offset after it would be one character off.
    box = [False]
    # An ordered item's `[ ]` is a stand-in here (`orderedtask.hide`): where an item opens with it the page draws a
    # box, so its three characters are no text; anywhere else (code) they are the characters they were.
    item_at, skip = [], [0]

    class P(HTMLParser):
        def handle_starttag(self, tag, attrs):
            box[0] = tag == "li"
            if tag == "li":
                item_at.append(len(text))
            if tag in VOID_TAGS:
                return
            span = None
            if tag not in BLOCK_TAGS:
                # From pandoc 3.8 a span carries data-pos twice: its own range, then
                # the range of the block around it. The first is the one wanted
                # (before 3.8 there is only one); dict(attrs) would keep the last.
                pos = next((v for k, v in attrs if k == "data-pos"), None)
                # A span over several lines (in a quote or a list) has one range per line: it runs from the
                # first range's start to the last range's end.
                ranges = [tuple(map(int, m.groups())) for m in POS_RE.finditer(pos or "")]
                if ranges:
                    span = _Span(off(*ranges[0][:2]), off(*ranges[-1][2:]))
            stack.append((tag, span))

        def handle_endtag(self, tag):
            if tag in VOID_TAGS:
                return
            if tag == "li" and item_at:
                item_at.pop()
            while stack:
                t, _ = stack.pop()
                if t == tag:
                    break

        def handle_data(self, data):
            spans = [s for _, s in stack if s is not None]
            if box[0] and data.strip():
                box[0] = False
                lead = data.lstrip()
                if not spans and lead[0] in TASK_BOXES:
                    data = lead[1:]
            if copyblock.STAND_IN in data:
                # The marker of a copy block is not on the page, and pandoc, not a guess at its rules, says whether
                # this is one: the stand-in first in a paragraph of a quote that opens the block. Anywhere else the
                # page shows it as the marker's own words.
                tags = [t for t, _ in stack if t != "span"]
                if not text and tags[-2:] == ["blockquote", "p"]:
                    data = data.replace(copyblock.STAND_IN, "")
                else:
                    data = data.replace(copyblock.STAND_IN, copyblock.MARKER)
            for ch in data:
                if skip[0]:                  # the mark and the close of an ordered item's box
                    skip[0] -= 1
                    continue
                if ch == orderedtask.STAND_IN_OPEN and item_at and len(text) == item_at[-1] \
                        and "pre" not in (t for t, _ in stack):
                    skip[0] = 2
                    continue
                ch = {orderedtask.STAND_IN_OPEN: "[", orderedtask.STAND_IN_CLOSE: "]"}.get(ch, ch)
                if ch.isspace():
                    continue
                k = len(text)
                text.append(ch)
                chars.append(spans)
                for s in spans:
                    if s.first < 0:
                        s.first = k
                    s.last = k

    p = P(convert_charrefs=True)
    p.feed(_sourcepos_html(orderedtask.hide(copyblock.hide(block))))
    p.close()
    return Projection("".join(text), chars)


def _kept(block: str) -> list[int]:
    """The offsets of `block` that pandoc keeps: every one but a CR, which it deletes before it reads anything."""
    return [i for i, ch in enumerate(block) if ch != "\r"]


def _unstrip(keep: list[int], at: int, block: str) -> int:
    """The offset in `block` of offset `at` in the block without its CRs: right after the character before it, so
    a run of CRs that follows stays after the point (`Title|\r\n`), and the block's first character for 0."""
    if at > len(keep):
        raise ValueError(f"offset {at} is past the end of a block of {len(keep)} characters without its CRs")
    if at:
        return keep[at - 1] + 1
    return keep[0] if keep else len(block)


def anchor_point(block: str, start: int, end: int, quote: str) -> int:
    """Offset in `block` where a comment on the selection [start, end) goes."""
    if "\r" in block:
        # Pandoc deletes a CR and counts its columns without it, so the point is found in the block without its CRs
        # and given back as an offset in the block itself.
        return _unstrip(_kept(block), anchor_point(block.replace("\r", ""), start, end, quote), block)
    proj = projection(block)
    if end <= start or proj.text[start:end] != squash(quote):
        raise AnchorError("the text changed since the page was rendered, select it again")
    k = end - 1
    spans = proj.chars[k]
    if not spans:
        raise AnchorError("this text has no position in the source, comment on the words around it")
    for s in spans:                          # outermost first
        if s.last == k:
            return s.end
    inner = spans[-1]
    src = block[inner.start:inner.end]
    if len(src) == inner.last - inner.first + 1 and squash(src) == proj.text[inner.first:inner.last + 1]:
        return inner.start + (k - inner.first) + 1
    # The selection ends inside a formatted run (inline code, a link, a run whose source
    # differs from its text): SPEC 10.4 puts the comment at the end of that run.
    return inner.end


_ATX_TEXT = re.compile(r"^( {0,3}#{1,6}[ \t]+)(.*?)(?:[ \t]+#+)?[ \t]*$")


def _atx_words(line: str):
    """The match of `_ATX_TEXT` for an ATX heading line that has words, else None. Hashes after the
    opening ones are the closing ones when nothing else is there: `### ###`, `# #` and `## #` have no
    words, `## ## ##` has the word `##` (CommonMark and pandoc read it so)."""
    m = _ATX_TEXT.match(line)
    if m and m.group(2) and set(line[m.end(1):].strip()) != {"#"}:
        return m
    return None


# An inline HTML tag as CommonMark reads it: it binds more tightly than a code span, so a backtick
# in an attribute value opens nothing. ASCII only, whitespace of a tag is space, tab, newline or return (pandoc
# reads no form feed), and an odd run of backslashes before the `<` escapes it (group `tag`).
_HTML_TAG_RE = re.compile(
    r"(?<!\\)(?:\\\\)*(?P<tag></[A-Za-z][A-Za-z0-9-]*[ \t\r\n]*>|<[A-Za-z][A-Za-z0-9-]*"
    r"(?:[ \t\r\n]+[A-Za-z_:][A-Za-z0-9_:.-]*(?:[ \t\r\n]*=[ \t\r\n]*"
    r"(?:[^ \t\r\n\"'=<>`]+|'[^']*'|\"[^\"]*\"))?)*[ \t\r\n]*/?>)")


def _unclosed_opener(text: str) -> int:
    """Where a `<!--` outside code that nothing closes starts in `text`, or -1. Any `<!--`
    counts, not only a rectoverso comment's: a block written after it would close it (see `_scan`).
    `<!-->` and `<!--->` are whole comments, as CommonMark and the list read them."""
    return next((a for kind, a, _ in _scan(text) if kind == "open"), -1)


def heading_anchor(block: str) -> int | None:
    """The offset of `_heading_anchor` read on the block without its CRs, which pandoc deletes (the splitter reads
    them so, and a heading may begin after four of them), given back as an offset in the block itself."""
    if "\r" not in block:
        return _heading_anchor(block)
    at = _heading_anchor(block.replace("\r", ""))
    return None if at is None else _unstrip(_kept(block), at, block)


def _heading_anchor(block: str) -> int | None:
    """Offset in a heading block where a comment on any of its words goes: the end of the heading's
    text, so the words stay whole for every reader of the file (a block in the middle, as in
    "Done<!-- … --> when", makes the title another one). Before an ATX heading's closing hashes and
    before a setext heading's underline, which a block after them would turn into text; before a
    backslash that ends the text, which would escape the block's `<`; before a `<!--` that nothing
    closes, which a block after it would close, hiding the words it was meant to hold. None for a
    heading with no words, where a block right after the hashes would make the line a paragraph,
    and for a line that blocks.ATX_RE reads as a heading and pandoc as a paragraph (a no-break
    space after the hashes), where the caller keeps the block after the selection."""
    lines = block.rstrip("\n").split("\n")
    if len(lines) > 1 and SETEXT_RE.match(lines[-1]):          # setext: the text is the lines above the underline
        at = len("\n".join(lines[:-1]).rstrip())
        floor = 0
    else:
        m = _atx_words(lines[0])
        if not m:
            return None
        at, floor = m.end(2), len(m.group(1).rstrip())
    open_at = _unclosed_opener(block[:at])
    if open_at >= 0:
        at = len(block[:open_at].rstrip())
        if at <= floor:
            return None
    run = len(block[:at]) - len(block[:at].rstrip("\\"))
    return at - 1 if run % 2 else at


# A cell border: a `|` with no backslash right before it. Unlike an escape in running text, pairs do not
# count here: pandoc (gfm) keeps `a \\| b` in one cell, whatever number of backslashes stand before the pipe.
_CELL_PIPE_RE = re.compile(r"(?<!\\)(\|)")


_CONTAINER_RE = re.compile(r"[ \t]*(?:>|(?:[-+*]|\d{1,9}[.)])(?=[ \t]))[ \t]?")


def in_table_row(block: str, point: int) -> bool:
    """Whether `point` is on a row of a table that a quote or a list holds (`> | a | b |`, an item
    with a paragraph before its table): a line that pandoc reads a cell on (`_read_tables`), or one
    that the splitter would read as a row (`_in_table_row_by_markers`): the splitter cuts a block at a
    delimiter row that pandoc does not read, and a comment of several lines written there is cut with it.
    The splitter reads such a block as a quote or a list, not a table, but a comment in it must be written
    as one in a table: on one line, at the end of a cell."""
    if _container_heading(block, point):
        return True
    if not _may_hold_table(block):
        return False
    read = _read_tables(block)
    if read is not None and block.count("\n", 0, point) in read[0]:
        return True
    return _in_table_row_by_markers(block, point)


def _in_table_row_by_markers(block: str, point: int) -> bool:
    """The rows as the splitter reads them: the container markers read by hand, as far as they go. Read without the
    CRs pandoc deletes (a CR before a `>` or in a delimiter row does not make the table another block)."""
    if "\r" in block:
        return _in_table_row_by_markers(block.replace("\r", ""), sum(1 for i in _kept(block) if i < point))
    lines = block.split("\n")
    n = block.count("\n", 0, point)
    bare = []
    for line in lines:
        while (m := _CONTAINER_RE.match(line)) and m.end():
            line = line[m.end():]
        bare.append(line)
    if (n + 1 < len(bare) and _CELL_PIPE_RE.search(bare[n]) and _CELL_PIPE_RE.search(bare[n + 1])
            and TBLSEP_RE.match(bare[n + 1])):
        return True                 # the header row, above its delimiter row
    for i in range(n, -1, -1):
        if not _CELL_PIPE_RE.search(bare[i]):
            return False
        if i and TBLSEP_RE.match(bare[i]) and _CELL_PIPE_RE.search(bare[i - 1]):
            return True
    return False


def cell_end(block: str, point: int, cells: bool = True, code=None) -> int:
    """Offset where a comment on a selection ending at `point` goes in a table: the end of the cell that
    holds `point`, before its closing `|` and the spaces in front of it, so the cell's words stay whole
    for every reader of the file. A `|` ends a cell unless a backslash stands right before it (pandoc counts no pairs), in code
    as well (GFM and pandoc read `a|b` in a code span as two cells); a row with no closing `|` ends the
    cell at the end of its line. Before a backslash that ends the cell's text, which would escape the
    block's `<`, and before a `<!--` in the cell that nothing closes, which a block after it would close,
    hiding the words it was meant to hold. Where the cell's end is inside a code span that `parse` reads
    across cells (pandoc splits the cells first), the block stays after the selection: written there it
    would be code to `parse`, and the comment lost. `code` is the inline code ranges that pandoc reads
    in a quote or a list (`_read_tables`), which `parse` masks the same way. Read without the CRs pandoc
    deletes, so a backslash or spaces before a CR and the pipe still stand before the pipe."""
    if "\r" in block:
        keep = _kept(block)
        if code is not None:
            code = tuple((sum(1 for i in keep if i < x), sum(1 for i in keep if i < y)) for x, y in code)
        return _unstrip(keep, cell_end(block.replace("\r", ""), sum(1 for i in keep if i < point), cells, code), block)
    line_start = block.rfind("\n", 0, point) + 1
    eol = block.find("\n", point)
    line_end = len(block) if eol < 0 else eol
    # Read from the start of the line: whether a `|` is escaped depends on the backslashes before it.
    pipes = [m.start(1) for m in _CELL_PIPE_RE.finditer(block, line_start, line_end)]
    at = next((p for p in pipes if p >= point), line_end)
    cell_start = max((p + 1 for p in pipes if p < point), default=line_start)
    while at > point and block[at - 1] in " \t":
        at -= 1
    open_at = _unclosed_opener(block[cell_start:at])
    if open_at >= 0:
        at = cell_start + len(block[cell_start:cell_start + open_at].rstrip())
        if not block[cell_start:at].strip():
            raise AnchorError("this cell has no place for a comment, comment on another cell")
    run = len(block[cell_start:at]) - len(block[cell_start:at].rstrip("\\"))
    if run % 2:
        at -= 1
    if code is not None:
        if any(a < at < b for a, b in code):
            if any(a < point < b for a, b in code):
                raise AnchorError("this cell is inside a code span, comment on another cell")
            return point
        return at
    if _mask_code(block[:at] + "\0" + block[at:], cells)[at] == " ":
        if not cells and _mask_code(block[:point] + "\0" + block[point:])[point] == " ":
            raise AnchorError("this cell is inside a code span that runs across cells, "
                              "comment on another cell")
        return point
    return at


def comment_point(kind: str, block: str, start: int, end: int, quote: str) -> int:
    """Offset in `block` (of the given kind) where a comment on the selection [start, end) goes."""
    point = anchor_point(block, start, end, quote)      # a heading checks the selection too, then ignores where it ends
    if kind == "table":
        return cell_end(block, point)
    if kind in ("quote", "list") and (head := _container_heading(block, point)):
        # A heading in a quote or a list: the comment goes at the end of its words, on its line (ticket 55).
        eol = block.find("\n", head[0])
        line = block[head[0]:len(block) if eol < 0 else eol]
        at = heading_anchor(line) if _atx_words(line.replace("\r", "")) else None
        if at is None:
            raise AnchorError("this heading has no place for a comment, comment on a paragraph")
        return head[0] + at
    if kind in ("quote", "list") and in_table_row(block, point):
        read = _read_tables(block)
        return cell_end(block, point, cells=False, code=read[1] if read else None)
    if kind != "heading":
        return point
    at = heading_anchor(block)
    if at is not None:
        return at
    lines = block.rstrip("\n").split("\n")
    if not _ATX_TEXT.match(lines[0]) and not (len(lines) > 1 and SETEXT_RE.match(lines[-1])):
        return point            # ATX_RE reads a heading, pandoc a paragraph: the selection is where it goes
    raise AnchorError("this heading has no place for a comment, comment on a paragraph")


def _block_offsets(blocks):
    pos, out = 0, []
    for b in blocks:
        out.append(pos)
        pos += len(b.text)
    return out


def _check_kind(b):
    if b.kind in CODE_KINDS:
        raise AnchorError("comments cannot go inside code")
    if b.kind in ("html", "blank", "hr"):
        raise AnchorError(f"comments cannot go in a {b.kind} block")


def add_comment(md: str, block: int, start: int, end: int, quote: str, body: str,
                by: str, at: str):
    """Insert a new comment. Returns (new markdown, new id)."""
    blocks = split_md_blocks(md)
    if not 0 <= block < len(blocks):
        raise AnchorError("no such block")
    b = blocks[block]
    _check_kind(b)
    at_off = comment_point(b.kind, b.content, start, end, quote)
    c = Comment(id=next_id_in(md), by=by, at=at, status="open",
                quote=" ".join(quote.split()), body=body.strip("\n"))
    raw = format(c, one_line=b.kind in ONE_LINE_KINDS or in_table_row(b.content, at_off))
    pos = _block_offsets(blocks)[block] + at_off
    return md[:pos] + raw + md[pos:], c.id


def find_quote(md: str, quote: str):
    """(block, start, end) of the one place `quote` occurs in the rendered text."""
    q = squash(quote)
    if not q:
        raise AnchorError("empty quote")
    hits = []
    for i, b in enumerate(split_md_blocks(md)):
        if b.kind in CODE_KINDS or b.kind in ("html", "blank", "hr") or not b.content.strip():
            continue
        t = projection(b.content).text
        j = t.find(q)
        while j >= 0:
            hits.append((i, j, j + len(q)))
            j = t.find(q, j + 1)
    if not hits:
        raise AnchorError("the passage does not occur in the document")
    if len(hits) > 1:
        raise AnchorError(f"the passage occurs in {len(hits)} places, quote more of it")
    return hits[0]


# ─────────────────────────────────────────────────── changing a comment ──

def _refuse_nested(md: str, c) -> None:
    if "<!--" in md[c.start + len("<!--"):c.end]:
        # parse ends a comment at the first -->, which here is a further comment's: changing
        # the span would leave the rest of the outer on the page as text.
        raise AnchorError(f"comment {c.id} holds another comment and cannot be changed, "
                          "separate them in the page text first")


def _opener(text: str, i: int) -> int:
    """Where the next `<!--` that opens a comment starts: one backslash before it makes it text,
    two are a backslash and the opener."""
    m = re.compile(r"(?<!\\)(?:\\\\)*(<!--)").search(text, i)
    return m.start(1) if m else -1


def _comment_spans(md: str) -> list:
    """Every `<!-- ... -->` of the page as (start, end), read left to right per block like
    CommonMark: inline code is skipped, but only where no comment is open, so a backtick inside
    an ordinary comment pairs with nothing. One never closed runs to the end."""
    spans, start, pos = [], None, 0
    for b in split_md_blocks(md):
        text, base = b.content, pos
        pos += len(b.text)
        if b.kind in CODE_KINDS:
            continue
        i, o, span = 0, None, None
        while True:
            if start is not None:
                e = text.find("-->", i)
                if e < 0:
                    break
                spans.append((start, base + e + 3))
                i, start = e + 3, None
            # Each search is reused while its hit still lies ahead of i, as `_scan` does: a search
            # from i finds what one from an earlier position found, so a block of many comments is
            # read once, not once per comment.
            if o is None or (o >= 0 and o < i):
                o = _opener(text, i)
            if span is None or (span is not False and span.start(1) < i):
                span = CODE_SPAN_RE.search(text, i) or False
            if span and (o < 0 or span.start(1) < o):
                i = span.end()
            elif o >= 0:
                i, start = o + 4, base + o
            else:
                break
    if start is not None:
        spans.append((start, len(md)))
    return spans


def _refuse_changing_neighbours(md: str, c, out: str) -> None:
    """Taking c out must leave every other comment of the page as it was, and no new one: c's
    --> may be what closes the comment around it, and what is left on both sides may join into
    a `<!--` or a `-->`. Either way text that was on the page would go (or appear)."""
    kept = [md[s:e] for s, e in _comment_spans(md) if s != c.start]
    if [out[s:e] for s, e in _comment_spans(out)] != kept:
        raise AnchorError(f"comment {c.id} cannot be deleted: taking it out would change the "
                          "comments around it, separate them in the page text first")


def _find(md: str, cid: str):
    """The comment `cid`. NoComment only when nothing of it is in the page; a comment that is
    there but parse cannot read (malformed, or inside code) is an AnchorError that says so."""
    parsed = parse(md)
    c = parsed.by_id(cid)
    if c is not None:
        return c
    ident = rf"\bid={re.escape(cid)}(?![\w-])"
    for m in parsed.malformed:      # the head's fields may be in any order here
        if re.search(ident, m.text.split("\n", 1)[0]):
            raise AnchorError(f"comment {cid} is in the page but cannot be read ({m.reason})")
    heads = rf"<!--\s*{MARKER}\b[^\n]*?{ident}"
    if re.search(rf"<!--\s*{MARKER}\s+{ident}", md) or any(
            b.kind in CODE_KINDS and re.search(heads, b.content) for b in split_md_blocks(md)):
        raise AnchorError(f"comment {cid} is in the page but cannot be read (inside code)")
    raise NoComment(f"no comment {cid} in this document")


def _rewrite(md: str, cid: str, change) -> str:
    c = _find(md, cid)
    _refuse_nested(md, c)
    change(c)
    blocks = split_md_blocks(md)
    b = blocks[c.block]
    row = in_table_row(b.content, c.start - _block_offsets(blocks)[c.block])
    raw = format(c, one_line=(b.kind in ONE_LINE_KINDS or row) and not c.standalone)
    return md[:c.start] + raw + md[c.end:]


def reply(md: str, cid: str, text: str, by: str, at: str, resolve: bool = False,
          role: str | None = None) -> str:
    """Add a reply. `role` is written as given; deciding that an agent's reply
    with no role gets "answer" (D20) is the caller's, which knows who the author is."""
    if role is not None and role not in ROLES:
        raise AnchorError(f"unknown role {role!r}, use one of: {', '.join(ROLES)}")

    def f(c):
        c.replies.append(Reply(by, at, text.strip("\n"), role))
        if resolve:
            c.status = "resolved"
    return _rewrite(md, cid, f)


def set_status(md: str, cid: str, status: str) -> str:
    if status not in STATUSES:
        raise AnchorError(f"unknown status {status!r}")
    return _rewrite(md, cid, lambda c: setattr(c, "status", status))


def edit_body(md: str, cid: str, body: str) -> str:
    return _rewrite(md, cid, lambda c: setattr(c, "body", body.strip("\n")))


def delete(md: str, cid: str) -> str:
    c = _find(md, cid)
    _refuse_nested(md, c)
    if c.standalone:
        # An orphan is a block of its own: take its line and the blank after it.
        end = c.end
        while end < len(md) and md[end] == "\n":
            end += 1
        out = md[:c.start] + md[end:]
    else:
        out = md[:c.start] + md[c.end:]
    _refuse_changing_neighbours(md, c, out)
    return out


def apply_op(md: str, op: str, fields: dict, by: str = "", at: str = "",
             role: str | None = None) -> str:
    """The change an `op` names ("reply", "status", "edit" or "delete") makes to comment
    `fields["id"]`: the one place the operation names meet the functions above. The page, the
    door and the command line all go through it. Raises AnchorError for any other `op`."""
    cid = fields.get("id", "")
    if op == "reply":
        return reply(md, cid, fields.get("body", ""), by, at, bool(fields.get("resolve")), role)
    if op == "status":
        return set_status(md, cid, fields.get("status", ""))
    if op == "edit":
        return edit_body(md, cid, fields.get("body", ""))
    if op == "delete":
        return delete(md, cid)
    raise AnchorError(f"unknown operation {op!r}")
