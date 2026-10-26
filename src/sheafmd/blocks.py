#!/usr/bin/env python3
"""
sheafmd.blocks — the markdown block model behind editing on the page.

Why this exists
---------------
sheaf turns a .md into a disposable HTML view. Edit mode lets the reader edit
that view in the browser and push the result back into the .md, which stays the
source of truth. Pushing an edit back means answering one question: which bytes of
the source does this on-screen paragraph correspond to?

The answer is a block model. The source is split into top-level markdown blocks that
TILE it exactly (every line belongs to exactly one block, joining them reproduces the
file byte-for-byte). Each block is announced to pandoc with an inert HTML comment
sentinel, which survives into the rendered HTML and lets the page map DOM nodes back
to block indices.

The property that makes this safe: on save, ONLY blocks whose HTML actually changed
are converted back to markdown. Every untouched block keeps its original bytes, so
chart fences, image lines, hand-tuned table alignment and front matter survive edits
made elsewhere in the document. A pandoc html->md round-trip is not the identity, so
the fewer blocks that pass through it, the better.
"""

import re

FENCE_RE   = re.compile(r"^(\s{0,3})(`{3,}|~{3,})(.*)$")
ATX_RE     = re.compile(r"^\s{0,3}#{1,6}(\s|$)")
LIST_RE    = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])(\s+|$)")
QUOTE_RE   = re.compile(r"^\s{0,3}>")
HTML_RE    = re.compile(r"^\s{0,3}(?:</?[A-Za-z][A-Za-z0-9-]*(?:[\s/>]|$)|<!--|<!|<\?)")
# NB: deliberately stricter than "<" + letter. An autolink like
# <https://blueoakcouncil.org/license/1.0.0> is NOT an HTML block start (the
# "tag name" would be "https", terminated by ":"), and treating it as one splits
# the paragraph that contains it.
HR_RE      = re.compile(r"^\s{0,3}((\*\s*){3,}|(-\s*){3,}|(_\s*){3,})$")
IMG_TAG_RE = re.compile(r"<img\b", re.I)
SETEXT_RE  = re.compile(r"^\s{0,3}(=+|-+)\s*$")
TBLSEP_RE  = re.compile(r"^\s{0,3}\|?[\s:|-]*-[\s:|-]*$")
INDENT_RE  = re.compile(r"^(\s{4,}|\t)")

# Blocks we must never let the browser edit: converting their HTML back to markdown
# would destroy the source (a chart's JSON becomes an <svg>, an image line becomes a
# multi-megabyte data: URI, a fence's contents get re-escaped).
LOCKED_KINDS = {"fence", "frontmatter", "html", "indented_code"}

# Blocks a reader can select text in and comment on. Code, raw HTML and front
# matter are refused: an HTML comment inside code is literal code.
COMMENTABLE_KINDS = {"para", "heading", "list", "quote", "table"}


class Block:
    __slots__ = ("kind", "content", "gap", "start")

    def __init__(self, kind, content, gap, start):
        self.kind = kind        # heading | para | list | quote | table | fence | ...
        self.content = content  # the block's own lines, no trailing blank lines
        self.gap = gap          # the blank lines that followed it, verbatim
        self.start = start      # 0-based line number in the source

    @property
    def editable(self):
        if self.kind in LOCKED_KINDS:
            return False
        # A block holding an image becomes a <figure> with an embedded data: URI that
        # cannot go back to markdown. Any `![` is taken for one: inline, reference
        # (`![alt][p]`, `![alt][]`) and shortcut (`![alt]`) forms all render the same
        # way, and the definition may sit in another block.
        if "![" in self.content:
            return False
        # A raw <img> is one too: with its file missing the page shows a red
        # placeholder span for it, and saving the paragraph would write that span
        # over the tag.
        if IMG_TAG_RE.search(self.content):
            return False
        return True

    @property
    def text(self):
        return self.content + self.gap

    def __repr__(self):
        head = self.content.split("\n")[0][:40]
        return f"<Block {self.kind} @{self.start} {head!r}>"


def _looks_like_table(lines, i):
    """A gfm table is a header row followed by a |---|---| separator."""
    if i + 1 >= len(lines):
        return False
    nxt = lines[i + 1]
    return ("|" in lines[i]) and ("-" in nxt) and TBLSEP_RE.match(nxt) is not None and "|" in nxt


def _scan_fence(lines, i):
    m = FENCE_RE.match(lines[i])
    marker = m.group(2)
    ch, need = marker[0], len(marker)
    j = i + 1
    while j < len(lines):
        m2 = FENCE_RE.match(lines[j])
        if m2 and m2.group(2)[0] == ch and len(m2.group(2)) >= need and not m2.group(3).strip():
            return j + 1
        j += 1
    return len(lines)          # unterminated fence runs to EOF, as CommonMark says


def _scan_list(lines, i):
    """Consume a whole list, including everything nested inside its items.

    Getting this wrong is the one way this splitter can corrupt a document: a
    sentinel injected mid-list splits the list in two, which changes the render
    (tight lists turn loose, nested lists detach, a fenced block indented inside an
    item escapes its item). Indentation is what decides, not the shape of the line -
    a ```fence indented two spaces inside a list item still looks like a fence.
    """
    base = len(lines[i]) - len(lines[i].lstrip())
    n = len(lines)
    j = i + 1
    while j < n:
        ln = lines[j]
        if not ln.strip():
            k = j
            while k < n and not lines[k].strip():
                k += 1
            if k < n:
                ind = len(lines[k]) - len(lines[k].lstrip())
                if ind > base or LIST_RE.match(lines[k]):
                    j = k
                    continue
            break
        ind = len(ln) - len(ln.lstrip())
        if ind > base:                     # nested list, indented fence, continuation
            j += 1
        elif LIST_RE.match(ln):            # sibling item at the same level
            j += 1
        elif not _starts_block(lines, j):  # lazy paragraph continuation
            j += 1
        else:
            break
    return j


def _scan_quote(lines, i):
    j = i + 1
    while j < len(lines) and lines[j].strip() and (QUOTE_RE.match(lines[j]) or not _starts_block(lines, j)):
        j += 1
    return j


def _starts_block(lines, i):
    """Would this line begin a new block if we saw it standing alone?"""
    ln = lines[i]
    return bool(
        ATX_RE.match(ln) or FENCE_RE.match(ln) or QUOTE_RE.match(ln)
        or LIST_RE.match(ln) or HR_RE.match(ln) or HTML_RE.match(ln)
        or _looks_like_table(lines, i)
    )


def _split_lines(text):
    """Split into lines that KEEP their own terminator, so joining is exact.

    Deliberately not str.splitlines(): that also breaks on \x0b, \x0c and \u2028,
    which markdown does not treat as line breaks, and the round-trip would silently
    lose them.
    """
    return re.findall(r"[^\n]*\n|[^\n]+", text)


def _interrupts_para(lines, i):
    """Can this line end the paragraph that is already open above it?

    CommonMark is deliberately asymmetric here, and the asymmetry is the whole
    reason this function exists separately from _starts_block(). Verified against
    pandoc 3.1.3:

        text:              text:              text:             text:
        | a | b |          - a                3. a                  code
        |---|---|

        stays one          becomes a          stays one          stays one
        paragraph          real list          paragraph          paragraph

    A GFM table and an indented code block CANNOT interrupt a paragraph, and an
    ordered list can only do so when it starts at 1. Splitting on them anyway turns
    literal text in the source into a rendered table - which is arguably nicer, but
    it is not what the document says, and edit mode must never change the render.
    """
    ln = lines[i]
    if ATX_RE.match(ln) or FENCE_RE.match(ln) or HR_RE.match(ln) \
       or QUOTE_RE.match(ln) or HTML_RE.match(ln):
        return True
    m = LIST_RE.match(ln)
    if m and len(m.group(1)) < 4 and ln[m.end():].strip():
        marker = m.group(2)
        return marker in "-*+" or marker[:-1] == "1"
    return False


def split_md_blocks(text):
    """Split markdown into top-level blocks that tile the source exactly.

    Guarantee, enforced by the test suite against every .md in the repo:
        "".join(b.text for b in split_md_blocks(t)) == t
    """
    lines = _split_lines(text)
    n = len(lines)
    blocks, i = [], 0

    def emit(kind, start, end):
        """Take lines[start:end] as content, then absorb the blank run after it."""
        j = end
        while j < n and not lines[j].strip():
            j += 1
        blocks.append(Block(kind, "".join(lines[start:end]), "".join(lines[end:j]), start))
        return j

    # leading blank lines belong to no block; keep them as an inert one
    if i < n and not lines[i].strip():
        j = i
        while j < n and not lines[j].strip():
            j += 1
        blocks.append(Block("blank", "", "".join(lines[i:j]), i))
        i = j

    # YAML front matter, only at the very top
    if i == 0 and n and lines[0].strip() == "---":
        for j in range(1, n):
            if lines[j].strip() in ("---", "..."):
                i = emit("frontmatter", 0, j + 1)
                break

    while i < n:
        ln = lines[i]
        if not ln.strip():
            i += 1
            continue

        if INDENT_RE.match(ln):
            # Checked first: at top level, 4 spaces means indented code, and that
            # beats the list / table / html shapes those same characters would
            # otherwise match. The \s{0,3} guards on the other patterns encode the
            # same rule; LIST_RE, HTML_RE and the table probe do not.
            j = i + 1
            while j < n and (INDENT_RE.match(lines[j]) or not lines[j].strip()):
                j += 1
            while j - 1 > i and not lines[j - 1].strip():
                j -= 1
            i = emit("indented_code", i, j)
        elif FENCE_RE.match(ln):
            i = emit("fence", i, _scan_fence(lines, i))
        elif ATX_RE.match(ln):
            i = emit("heading", i, i + 1)
        elif HR_RE.match(ln):
            i = emit("hr", i, i + 1)
        elif _looks_like_table(lines, i):
            j = i + 2
            while j < n and lines[j].strip() and "|" in lines[j]:
                j += 1
            i = emit("table", i, j)
        elif LIST_RE.match(ln):
            i = emit("list", i, _scan_list(lines, i))
        elif QUOTE_RE.match(ln):
            i = emit("quote", i, _scan_quote(lines, i))
        elif HTML_RE.match(ln):
            if ln.lstrip().startswith("<!--"):
                # An HTML comment block ends at --> , NOT at the next blank line.
                # Stopping at the blank line splits out whatever the comment was
                # commenting OUT, and that text then renders as live content.
                j = i
                while j < n and "-->" not in lines[j]:
                    j += 1
                j = min(j + 1, n)
            else:
                j = i + 1
                while j < n and lines[j].strip():
                    j += 1
            i = emit("html", i, j)
        else:
            # paragraph: runs to a blank line or to the start of another block
            j, kind = i + 1, "para"
            while j < n and lines[j].strip():
                if j > i and SETEXT_RE.match(lines[j]) and not LIST_RE.match(lines[j]):
                    j += 1
                    kind = "heading"
                    break
                if _interrupts_para(lines, j):
                    break
                j += 1
            i = emit(kind, i, j)

    return blocks


SENTINEL = "MDB"
SENTINEL_RE = re.compile(r"<!--" + SENTINEL + r":(\d+)-->")


def instrument(text):
    """Return markdown with an inert HTML-comment sentinel before each block.

    Pandoc passes the comments through to the HTML untouched, which is what lets the
    rendered page map a DOM node back to the source block it came from.

    Layout, per block:   <blank line>  <!--MDB:i-->  <blank line>  block content

    The blank-line arithmetic is load-bearing, not cosmetic. Exactly ONE blank line
    must precede the sentinel: two of them silently turn a preceding GFM task list
    loose (every <li> gains a <p>), a real render change that the inertness test
    catches on ~200 real client documents. Original inter-block gaps are therefore
    normalised here. That is safe because this instrumented text is throwaway - it
    is only ever fed to pandoc. Reassembly on save works from the block list, whose
    gaps are untouched, so the source file keeps its exact spacing.
    """
    blocks = split_md_blocks(text)
    out, first = [], True
    for idx, b in enumerate(blocks):
        if b.kind == "blank" or not b.content.strip():
            out.append(b.text)
            continue
        if b.kind == "frontmatter":
            # Pandoc only recognises a YAML metadata block at byte 0 of the input.
            # A sentinel in front of it displaces it, and the whole block stops being
            # metadata and renders as an <hr> plus a paragraph of raw YAML. It needs
            # no sentinel anyway: metadata produces no HTML to map back to.
            out.append(b.content if b.content.endswith("\n") else b.content + "\n")
            first = False
            continue
        content = b.content if b.content.endswith("\n") else b.content + "\n"
        if not first:
            out.append("\n")
        out.append(f"<!--{SENTINEL}:{idx}-->\n\n")
        out.append(content)
        first = False
    # Preserve the document's trailing blank lines verbatim. Dropping them is not
    # cosmetic: pandoc renders a GFM task list at end-of-document TIGHT with no
    # trailing blank line and LOOSE with one, so the tail is part of the render.
    if blocks:
        out.append(blocks[-1].gap)
    return "".join(out), blocks
