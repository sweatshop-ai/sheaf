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

import html as _html
import re
from dataclasses import dataclass, field

from .blocks import split_md_blocks

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
# A CommonMark code span: a run of backticks, then the shortest text up to a run of
# the same length that is not part of a longer one.
CODE_SPAN_RE = re.compile(r"(?<!`)(`+)(?!`)[\s\S]*?(?<!`)\1(?!`)")
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
    answered only by one of these: an Ask answer or a reader's reply landing in
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
    return line


def _dec(s: str) -> str:
    return _html.unescape(s)


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


def _mask_code(text: str) -> str:
    """`text` with its inline code spans blanked, the same length. Read left to right,
    as CommonMark does: a comment that starts before a backtick owns it, so a backtick
    in a comment's body does not open a span that runs on into the text after it."""
    out, pos, span, head, no_head = [], 0, None, None, False
    while True:
        if span is None or span.start() < pos:
            span = CODE_SPAN_RE.search(text, pos)
        if not span:
            break
        # Both searches run once and are reused while their match still lies ahead of
        # pos: a search from pos finds the same match as the one made from an earlier
        # position, so a block of many spans is read once, not once per span.
        if not no_head and (head is None or head.start() < pos):
            head = COMMENT_RE.search(text, pos)
            no_head = head is None      # none now means none later: pos only moves on
        if head and head.start() < span.start():
            end = text.find("-->", head.end())
            if end < 0:
                break                   # never closed: the rest of the block is the comment
            pos = end + 3
            continue
        out.append(span.span())
        pos = span.end()
    parts, last = [], 0
    for a, b in out:
        parts.append(text[last:a])
        parts.append(" " * (b - a))
        last = b
    parts.append(text[last:])
    return "".join(parts)


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
        masked = _mask_code(text)
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


def next_id(parsed: Parsed) -> str:
    n = 0
    for c in parsed.comments:
        m = re.fullmatch(r"c(\d+)", c.id)
        if m:
            n = max(n, int(m.group(1)))
    for mm in parsed.malformed:
        m = re.search(r"\bid=c(\d+)", mm.text)
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
    return r.stdout


def projection(block: str) -> Projection:
    from html.parser import HTMLParser

    starts = [0]
    for ln in block.split("\n")[:-1]:
        starts.append(starts[-1] + len(ln) + 1)

    def off(line, col):
        line = min(line, len(starts))
        return min(starts[line - 1] + col - 1, len(block))

    text, chars, stack = [], [], []
    # A task list item's box comes out as a ☐ or ☒ right after <li>, outside any
    # source span. The page draws a checkbox there, which has no text, so the box
    # must not count: every offset after it would be one character off.
    box = [False]

    class P(HTMLParser):
        def handle_starttag(self, tag, attrs):
            box[0] = tag == "li"
            if tag in VOID_TAGS:
                return
            span = None
            if tag not in BLOCK_TAGS:
                # From pandoc 3.8 a span carries data-pos twice: its own range, then
                # the range of the block around it. The first is the one wanted
                # (before 3.8 there is only one); dict(attrs) would keep the last.
                pos = next((v for k, v in attrs if k == "data-pos"), None)
                m = POS_RE.search(pos or "")
                if m:
                    a, b, c, d = map(int, m.groups())
                    span = _Span(off(a, b), off(c, d))
            stack.append((tag, span))

        def handle_endtag(self, tag):
            if tag in VOID_TAGS:
                return
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
            for ch in data:
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
    p.feed(_sourcepos_html(block))
    p.close()
    return Projection("".join(text), chars)


def anchor_point(block: str, start: int, end: int, quote: str) -> int:
    """Offset in `block` where a comment on the selection [start, end) goes."""
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
    at_off = anchor_point(b.content, start, end, quote)
    c = Comment(id=next_id(parse(md)), by=by, at=at, status="open",
                quote=" ".join(quote.split()), body=body.strip("\n"))
    raw = format(c, one_line=b.kind in ONE_LINE_KINDS)
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

def _rewrite(md: str, cid: str, change) -> str:
    c = parse(md).by_id(cid)
    if c is None:
        raise NoComment(f"no comment {cid} in this document")
    change(c)
    kind = split_md_blocks(md)[c.block].kind
    raw = format(c, one_line=kind in ONE_LINE_KINDS and not c.standalone)
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
    c = parse(md).by_id(cid)
    if c is None:
        raise NoComment(f"no comment {cid} in this document")
    if c.standalone:
        # An orphan is a block of its own: take its line and the blank after it.
        end = c.end
        while end < len(md) and md[end] == "\n":
            end += 1
        return md[:c.start] + md[end:]
    return md[:c.start] + md[c.end:]


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
