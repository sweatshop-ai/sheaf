"""
sheafmd.render — a markdown file to one self-contained HTML file (SPEC 6).

Two outputs come out of the same pipeline (SPEC 6.1):

    page         comments shown as anchors, the editor script, block sentinels when
                 they are render-inert; what the hub serves
    share copy   every HTML comment removed from the SOURCE before pandoc, no script
                 at all, no sentinels; what goes to a client

`build()` runs the steps in the order of SPEC 6.2. The order is part of the
contract: the sanitiser runs on pandoc's output before sheaf adds its own SVG and
images (which it must not strip), and the share copy is checked once more after
assembly, because the one failure that cannot be taken back is a comment or a script
in a file that has already been sent.

The markdown stays the source of truth; the HTML is a disposable view. Everything is
inlined (CSS, fonts, images, charts) so the page works over file://, offline, and when
forwarded.
"""
import html
import json
import re
import subprocess
import unicodedata
from bisect import bisect_left, bisect_right
from collections import Counter
from importlib import resources
from pathlib import Path


from . import _pandoc, charts, config, images, links
from . import comments as rdc
from . import sanitize as sanitizer
from . import source as src_mod
from .blocks import SENTINEL_RE, instrument, split_md_blocks
from .theme import Theme, css_string, font_css, load_theme

FLAG_RE = re.compile(r'\b(correction|corrected|retracted|retraction|superseded)\b', re.I)
COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")
CREDIT = ('<p class="sheaf-credit">Made with '
          '<a href="https://github.com/sweatshop-ai/sheaf">sheaf</a></p>')

# Blocks a reader can select text in and comment on. Code, raw HTML and front
# matter are refused in v1: an HTML comment inside code is literal code.
COMMENTABLE = {"para", "heading", "list", "quote", "table"}


class RenderError(Exception):
    """A render that must not produce a file. The message says what and where."""


class UnclosedComment(RenderError):
    def __init__(self, line: int, note: bool = False, swallows: bool = False,
                 unreadable: bool = False):
        self.line = line
        if unreadable:
            # The check could not read pandoc's tree, so it cannot say whether the stretch
            # loses text: the stretch may be a whole comment that loses nothing.
            super().__init__(
                f"line {line} holds the first stretch the share copy would take out, and this "
                "document nests too deep for the check to read it, so the check cannot tell "
                "whether that stretch loses text. Nothing was written. Flatten the nesting "
                "(quotes, lists or images inside one another), or remove the stretch, and "
                "share again.")
            return
        if swallows:
            # An opener that pandoc shows as text (or reads as something else), which
            # the strip closes with a later arrow and drops what lies between.
            super().__init__(
                f"line {line} holds a <!-- that is not a comment to the reader: nothing "
                "closes it, or it is written as text, or a browser ends it sooner. In the "
                "share copy the next --> below would close it and the text this document "
                "shows in between would be dropped. Close it with -->, or remove it, and "
                "share again.")
            return
        if note:
            # A sheaf-comment or rd-comment head: its body is a reviewer's note, and
            # with the closing arrow gone it would be printed in the copy.
            super().__init__(
                f"line {line} starts a comment (a note by a reviewer) that is never "
                "closed, so its text would show in the share copy. Close it with -->, or "
                "delete the comment, and share again.")
            return
        super().__init__(
            f"line {line} opens an HTML comment with <!-- that is never closed. In the "
            "share copy a browser would hide everything after it; close it with -->, or "
            "remove it, and share again.")


# ───────────────────────────────────────────────────────────── base stylesheet ──

BASE_CSS = r"""*{box-sizing:border-box}
/* One root size drives everything, and it scales with the viewport. A fixed
   column leaves wide margins and small type on a large monitor, and a browser
   scopes zoom per origin, which is a new ephemeral port for every document, so
   a zoom would not stick. Sizes below are rem, so type, column, tables and
   rules all grow together and the line stays ~85 characters instead of
   stretching to the width of the screen. clamp() keeps a forwarded copy sane
   on a laptop (floor) and on a 4K panel (ceiling). */
html{font-size:clamp(16px,1.28vw,31px)}
body{background:var(--bg);color:var(--fg);margin:0;padding:0 1.25rem 7rem}
/* A word wider than the screen breaks rather than widen the page on a phone (#128): a slug with no hyphen, a
   long path. break-word, not anywhere, so a table's columns keep their words and the table scrolls in its
   .tblwrap; a pre keeps its lines and scrolls inside itself. */
body{overflow-wrap:break-word}
#wrap{max-width:calc(var(--toc) + 2.2rem + var(--col));margin:0 auto;display:grid;
  grid-template-columns:var(--toc) minmax(0,var(--col));gap:2.2rem;align-items:start}
.notoc #wrap{display:block;max-width:var(--col)}
@media(max-width:1000px){#wrap{display:block}#toc{position:static!important;max-height:none!important;
  border-right:0!important;border-bottom:1px solid var(--rule);margin-bottom:2rem}}
#toc{position:sticky;top:1.4rem;max-height:calc(100vh - 2.8rem);overflow-y:auto;font-size:.72rem;
  line-height:1.45;border-right:1px solid var(--rule);padding:1.6rem 1rem 1.6rem 0}
#toc .lbl{font-size:.6rem;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);
  margin:0 0 .75rem;font-weight:700}
#toc a{display:block;padding:3px 0 3px 10px;color:var(--muted);text-decoration:none;
  border-left:2px solid transparent}
#toc a:hover{color:var(--accent);border-left-color:var(--accent);background:var(--soft)}
#toc a.lv1{color:var(--fg);font-weight:700;margin-top:10px}
#toc a.lv3{padding-left:22px;font-size:.66rem}
#toc a.flag::after{content:"!";font-size:.5rem;font-weight:700;color:var(--warn-br);
  border:1px solid var(--warn-br);border-radius:3px;padding:0 4px;margin-left:6px;vertical-align:1px}
main{padding-top:1.6rem;min-width:0}

/* Document header: who prepared it, then one labelled field per line. */
.doc-by{margin:0;padding:.4rem 0 .4rem 1rem;border-left:3px solid var(--accent);
  color:var(--muted);font-size:.85em;letter-spacing:.01em}
.doc-fields{margin:0 0 1.9rem;padding:.4rem 0 .55rem 1rem;border-left:3px solid var(--accent);
  line-height:1.55}
.doc-by+.doc-fields{padding-top:0}
.tblwrap{overflow-x:auto;margin:0 0 22px}
table{border-collapse:collapse;width:100%}
.flagged{background:var(--warn-bg);border-left:5px solid var(--warn-br);
  padding:10px 14px!important;margin-left:-19px}
figure{margin:28px 0}
figure img{max-width:100%;height:auto;display:block}
figcaption{font-size:.78rem;color:var(--muted);margin-top:8px;line-height:1.45}
.mermaid-svg{margin:26px 0;padding:14px;background:#fff;border:1px solid var(--rule);border-radius:6px;text-align:center}
.mermaid-svg svg{max-width:100%;height:auto}
.chart{margin:26px 0}
.chart svg{max-width:100%;height:auto}
.chart .cap{font-size:.72rem;color:var(--muted);margin-top:6px}
.chart .bandleg{display:flex;flex-wrap:wrap;gap:4px 16px;margin-top:8px;font-size:.7rem;color:var(--muted)}
.chart .bandleg i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px;
  vertical-align:baseline;opacity:.85}
a.filelink{word-break:break-all}

/* Print / PDF. The page is the same document, not a second design: same type,
   same rules, same charts. What changes is what a paged medium breaks badly.
   A chart cut across a page boundary is worse than no chart, and a table that
   loses its header on page two stops being evidence. */
@media print{
  /* A4, not Chrome's US-Letter default: most readers print on A4, and Letter
     shows up as a slightly wrong margin nobody names but everybody notices. */
  @page{size:A4;margin:16mm 14mm 18mm;
    /* Every theme prints the page count. CSS page-margin boxes (Chrome 131+), so it
       needs no footer template and survives --no-pdf-header-footer. The bottom margin
       holds it; the 15pt padding matches body's side padding in print. */
    @bottom-right{content:counter(page) " / " counter(pages);font-size:6.5pt;color:#555;
      vertical-align:middle;padding-right:15pt}}
  html,body{background:#fff}
  #wrap{display:block;max-width:none;margin:0}
  #toc{display:none}                     /* a sidebar TOC is screen furniture */
  main{padding-top:0}
  /* .tblwrap scrolls on screen; in print overflow:auto CLIPS the overflow
     instead of scrolling it, so a wide table silently loses its right-hand
     columns. This is the one print defect that looks fine until someone
     checks a number against the source. */
  .tblwrap{overflow:visible!important}
  /* Charts, figures and their captions travel as one unit. */
  .chart,figure,pre,blockquote{break-inside:avoid;page-break-inside:avoid}
  /* A short list splitting across a break leaves one bullet stranded from its
     siblings. Chrome breaks a list taller than a page regardless, so this
     protects the short ones and degrades on its own for the long ones. */
  ul,ol{break-inside:avoid;page-break-inside:avoid}
  li{break-inside:avoid}
  .chart svg{max-width:100%;height:auto}
  /* Tables are allowed to break — a long one must — but rows are not split and
     the header repeats on every page it reaches. */
  table{break-inside:auto}
  thead{display:table-header-group}
  tr,td,th{break-inside:avoid;page-break-inside:avoid}
  /* Widow control for a split table. The header repeating is right, but a
     repeated header over one stranded row reads as a second, near-empty table
     asserting a number whose evidence is on the previous sheet. Chaining
     break-before:avoid across the final rows carries them over together, so a
     table that breaks ANYWHERE leaves at least three rows after the break
     rather than one. */
  tbody tr:last-child,
  tbody tr:nth-last-child(2){break-before:avoid;page-break-before:avoid}
  /* No line stranded alone across a break, and no near-empty final page: the
     document's closing block stays with what precedes it. An 80-character last
     page reads as an accident rather than an ending. */
  p,li{orphans:3;widows:3}
  /* The closing run, not just the closing block. Chained the same way as the
     table rows above: with only :last-child protected, the break lands one
     paragraph earlier and a document still ends on a near-empty page whose
     opening line refers to a list the reader last saw on the page before. */
  main>:last-child,
  main>:nth-last-child(2){break-before:avoid;page-break-before:avoid}
  /* No heading stranded at the foot of a page. */
  h1,h2,h3,h4{break-after:avoid;page-break-after:avoid}
  h2,h3{break-inside:avoid}
  /* A paragraph ending in a colon introduces what follows; do not break between. */
  .leadin{break-after:avoid;page-break-after:avoid}
  .doc-mark{position:static}
  a{text-decoration:underline}
  /* Trailing margin on the last block spills past the page edge and Chrome
     emits an entirely blank final sheet for it. Costs nothing to zero, and a
     client PDF that ends on a blank page looks like a printing fault. */
  main>:last-child{margin-bottom:0}
  main{padding-bottom:0}
  html,body{margin-bottom:0;padding-bottom:0}
}

/* The theme's wordmark, above the title: text, not an image, so it costs no bytes and
   cannot fail to load. A theme's own stylesheet restyles it. */
.doc-mark{display:flex;align-items:center;gap:.7rem;margin:0 0 .6rem;line-height:1;color:var(--fg)}
.doc-mark b{font-weight:700;font-size:.9rem;letter-spacing:-.02em;white-space:nowrap}
.doc-mark span{font-size:.68rem;padding-left:.7rem;border-left:1px solid var(--rule)}
@media(max-width:640px){.doc-mark{flex-direction:column;align-items:flex-start;gap:.4rem}
  .doc-mark span{border-left:0;padding-left:0}}
.sheaf-credit{margin:3rem 0 0;font-size:.72rem;color:var(--muted)}
"""


# ──────────────────────────────────────────────────────────── share-copy stripping ──

def strip_comments(text: str, log: list[str] | None = None) -> str:
    """The text without any HTML comment: the share copy's first step.

    Pandoc passes comments straight through, so a note left in the source is readable
    in the delivered page's view-source. Every removal is logged, so a silent strip is
    impossible. Code is not spared: a comment in a fence is removed too, which is the
    safe direction and costs a document that quotes `<!-- ... -->` as an example that
    example.

    Removing a comment can join the text around it into a new one (`<!<!-- x -->-- y
    -->`), so it repeats until none is left."""
    log = log if log is not None else []
    while True:
        found = COMMENT_RE.findall(text)
        if not found:
            return text
        for c in found:
            head = re.sub(r"\s+", " ", c[4:-3]).strip()
            log.append(f"  - internal note removed ({len(c)} chars): {head[:60]}…")
        text = COMMENT_RE.sub("", text)


def _unclosed_line(src: str, frag: str) -> int | None:
    """The line of the `<!--` that no comment of the source closes and that pandoc let
    through as raw HTML: an opener in running text is escaped to `&lt;!--` and hides
    nothing, one at the start of a line is an HTML block that runs to the end of the
    document. The first one whose line pandoc copied verbatim, else the first one."""
    spans = [m.span() for m in COMMENT_RE.finditer(src)]
    first = None
    for m in re.finditer(r"<!--", src):
        if any(a <= m.start() < b for a, b in spans):
            continue
        line = src.count("\n", 0, m.start()) + 1
        first = first or line
        rest = src[m.start():].split("\n", 1)[0]
        if rest in frag:
            return line
    return first


def _stray_tails(src: str) -> list[int]:
    """Lines that start with `-->` outside every comment: what is left of a comment
    whose head an earlier edit removed (a share copy shows it as text)."""
    spans = [m.span() for m in COMMENT_RE.finditer(src)]
    lines, pos = [], 0
    for n, line in enumerate(src.split("\n"), 1):
        if line.startswith("-->") and not any(a <= pos < b for a, b in spans):
            lines.append(n)
        pos += len(line) + 1
    return lines


# A reviewer's comment is a note nobody is meant to read in the copy. Two things can
# let one through, and neither is decided by reading backticks, which is a guess
# (a backtick pairs across list items, an escaped one pairs with nothing, a comment
# can own one): the strip takes it with the text up to the next arrow, or pandoc
# prints its body. The second is read off pandoc's own output.
VISIBLE_NOTE_RE = re.compile(r"&lt;!--\s*(?:sheaf|rd)-comment\b")
CODE_HTML_RE = re.compile(r"<(pre|code)\b[\s\S]*?</\1>")


def _swallowed_note_line(src: str) -> int | None:
    """The line of a reviewer's comment whose own closing arrow is gone while an arrow
    further down is not: the strip would run on to that one and take everything in
    between with it. (No arrow below: pandoc decides, see `_shows_a_note`.)"""
    lines = [m.line for m in rdc.parse(src).malformed
             if m.reason == "never closed" and src.find("-->", m.start + 4) >= 0]
    for m in COMMENT_RE.finditer(src):
        # A comment cannot hold an opener (`_enc` writes every `<` as `&lt;`), so a
        # span that does is an unclosed opener and the comment after it.
        if rdc.COMMENT_RE.match(m.group(0)) and "<!--" in m.group(0)[4:]:
            lines.append(src.count("\n", 0, m.start()) + 1)
    return min(lines, default=None)


def _shows_a_note(frag: str) -> bool:
    """Does the page print a reviewer's comment head as text? In code it is an example."""
    return bool(VISIBLE_NOTE_RE.search(CODE_HTML_RE.sub("", frag)))


# What a reader sees is text in Str tokens, in the address of a link, and in raw html; the
# strip can take any of them, or move one into another.
_TEXT_BLOCKS = {"Para", "Plain", "Header", "LineBlock"}

# What counts as shown: a word, or a symbol that is not ASCII and not a space (emoji, check
# marks, arrows, dashes). A paragraph of them has no `\w` and was never counted. ASCII
# punctuation stays out on purpose: it is markup too, and a strip that makes a link of
# `[KEEP1](http://x/<!-- c -->y)` turns brackets into structure with nothing lost.
_TOKEN_RE = re.compile(r"\w+|[^\x00-\x7f\w\s]")


def _free_chars(used):
    """Private-use characters that are not in `used`, for a hole and for the markers of
    raw nodes: a document can hold any of them (icon fonts use thousands)."""
    for lo, hi in ((0xE000, 0xF900), (0xF0000, 0xFFFFE), (0x100000, 0x10FFFE)):
        for c in range(lo, hi):
            if chr(c) not in used:
                yield chr(c)


# What a browser does not show of raw html, read left to right as it reads it: a comment,
# which it ends at `-->` or `--!>` (`<!-->` and `<!--->` are empty, one never ended runs
# to the end, and pandoc's reading is longer when `--!>` is in it); the body of a script
# or a style; a tag, whose quoted values are whole (`<td title="<!--">` opens no comment);
# a declaration or a bogus comment. A `<style/>` or `<script/>` is a tag that holds nothing: the
# sanitiser's parser reads it as a start and an end, and keeps the text after it.
_RAW_NOISE_RE = re.compile(r"""
      <!--(?:>|->|[\s\S]*?(?:-->|--!>|\Z))
    | <(script|style)(?=[\s/>])(?![^>]*/>)[^>]*>[\s\S]*?(?:</\1\s*>|\Z)
    | </?[A-Za-z](?:=\s*"[^"]*"?|=\s*'[^']*'?|[^>])*>?
    | <[!?/][^>]*>?
    """, re.X | re.I)


def _raw_scan(html: str, hidden: str | None) -> tuple[list[str], str | None]:
    """The words a browser shows of one raw html node, and what it is still inside after
    it: a `<script>` or `<style>` that nothing closes hides the text of every node after
    it, whatever kind, until a `</script>` (`<scr<!-- x -->ipt>` is one the strip forms)."""
    if hidden:
        m = re.search(rf"</{hidden}\s*>", html, re.I)
        if not m:
            return [], hidden
        html, hidden = html[m.end():], None
    for m in _RAW_NOISE_RE.finditer(html):
        tag = m.group(1)
        if tag and not re.search(rf"</{tag}\s*>$", m.group(0), re.I):
            hidden = tag.lower()
    return _TOKEN_RE.findall(_RAW_NOISE_RE.sub(" ", html)), hidden


def _spelled_out(text: str, marks: dict) -> str:
    """The block's text without the comments its pieces spell: a head or a tail that a
    whole comment was cut out of (`<!<!-- x -->-- y -->`, which the strip's second pass
    takes). One written out in the text (`\\<!-- y -->`) is text to pandoc and stays, and
    so does a comment around any other raw node (`<<b></b>!-- \\<!-- y -->`): only a node
    that is a whole comment is gone when the strip has run, every other one stays in the
    text, marked, and keeps what is on either side of it apart."""
    cuts, clean = [], []
    for ch in text:
        if ch in marks and COMMENT_RE.fullmatch(marks[ch]):
            cuts.append((len(clean), ch))
        else:
            clean.append(ch)
    clean = "".join(clean)
    where = [c for c, _ in cuts]            # sorted: the cuts come in the order of the text
    gone = []
    for m in COMMENT_RE.finditer(clean):
        a, b = m.span()
        # a cut inside the opener (a, a + 4) or inside the closer (b - 3, b) is one this comment spells
        if (bisect_right(where, a) < bisect_left(where, a + 4)
                or bisect_right(where, b - 3) < bisect_left(where, b)):
            gone.append((a, b))
    if not gone:
        return text
    out, i, k = [], 0, 0
    for a, b in gone + [(len(clean), len(clean))]:
        while k < len(cuts) and cuts[k][0] <= a:      # the text up to a, with the cuts at or before it
            out.append(clean[i:cuts[k][0]])
            out.append(cuts[k][1])
            i, k = cuts[k][0], k + 1
        out.append(clean[i:a])
        while k < len(cuts) and cuts[k][0] < b:       # a cut inside the comment goes with it
            k += 1
        i = b
    return "".join(out)


_JSON_SPACE_RE = re.compile(r"[ \t\n\r]*")


def _json_loads(text: str):
    """`json.loads`, and for a tree it gives up on, the same value read without recursion. The
    depth it gives up at is the interpreter's: about 1000 levels on 3.11, about 10,000 on 3.12,
    what the C stack holds on later ones (pandoc's tree of 350 nested images is 1055 levels deep),
    and how deep a document may nest is not for the interpreter to say. The recursion limit is the
    process's and the hub's other threads share it, so it is not raised."""
    try:
        return json.loads(text)
    except RecursionError:
        return _loads_without_recursion(text)


def _loads_without_recursion(text: str):
    """What `json.loads` returns for `text`, read with a stack of its own. The brackets, commas and
    colons are read here: a string or a number is read by the decoder `json.loads` uses, so the two
    cannot disagree on one. A text `json.loads` refuses is refused here too, as a ValueError."""
    scalar = json.JSONDecoder().raw_decode
    stack: list = []            # the lists and dicts still open, the innermost last
    key = None                  # the key of the innermost dict, read and waiting for its value
    root = None
    want = "value"              # value, value-or-end, key, key-or-end, colon, comma, then done

    def attach(value):
        nonlocal root, want
        if not stack:
            root, want = value, "done"
        elif isinstance(stack[-1], list):
            stack[-1].append(value)
            want = "comma"
        else:
            stack[-1][key] = value
            want = "comma"

    def close():
        nonlocal want
        stack.pop()
        want = "comma" if stack else "done"

    pos, size = 0, len(text)
    while True:
        pos = _JSON_SPACE_RE.match(text, pos).end()
        if pos >= size:
            break
        ch = text[pos]
        if want == "done":
            raise ValueError("extra data after the JSON value")
        if want == "colon":
            if ch != ":":
                raise ValueError("expected ':' after a key")
            want, pos = "value", pos + 1
        elif want == "comma":
            in_list = isinstance(stack[-1], list)
            if ch == ",":
                want, pos = ("value" if in_list else "key"), pos + 1
            elif ch == ("]" if in_list else "}"):
                close()
                pos += 1
            else:
                raise ValueError("expected ',' or the end of the container")
        elif want in ("key", "key-or-end"):
            if ch == "}" and want == "key-or-end":
                close()
                pos += 1
            elif ch == '"':
                key, pos = scalar(text, pos)
                want = "colon"
            else:
                raise ValueError("expected a key")
        elif ch == "]" and want == "value-or-end":
            close()
            pos += 1
        elif ch in "[{":
            box = [] if ch == "[" else {}
            attach(box)
            stack.append(box)
            want, pos = ("value-or-end" if ch == "[" else "key-or-end"), pos + 1
        else:
            value, pos = scalar(text, pos)
            attach(value)
    if want != "done":
        raise ValueError("the JSON text ends before its value does")
    return root


def _shown_words(src: str, hole: str = "", code: bool = False) -> Counter:
    """The words pandoc shows for `src`, read from its own tree (an HTML parser would
    read a comment differently: `<!-->` is an empty one to pandoc and to a browser), in
    the order a browser meets them. Text in code counts only with `code`: it is not shown
    as text, but a word that moved into code is still on the page. `hole` is the characters
    that stand where text was taken out, one for each stretch; they are not words. The
    address of a link counts (a word that moved there is on the page) and its title does
    not (a tooltip); the alt text of an image does not either. A word is a run of letters
    and digits, or one symbol that is not ASCII (`_TOKEN_RE`)."""
    r = _pandoc.run(["-f", "gfm", "-t", "json"], src)
    if r.returncode != 0:
        raise subprocess.CalledProcessError(r.returncode, "pandoc", stderr=r.stderr)
    items: list[tuple] = []     # ("text", str), ("raw", html) or ("block", text, {marker: raw html})
    free = _free_chars(set(src) | set(r.stdout))     # markers of raw inline nodes in a block's text

    holes = {ord(h): None for h in hole}

    def drop(text: str) -> str:
        return text.translate(holes) if holes else text

    def walk(node, buf, raws):
        if isinstance(node, list):
            for x in node:
                walk(x, buf, raws)
        elif isinstance(node, dict):
            t, c = node.get("t"), node.get("c")
            if t == "Str":
                buf.append(c)
            elif t in ("Space", "SoftBreak", "LineBreak"):
                buf.append(" ")
            elif t in ("Code", "CodeBlock"):
                if code:
                    items.append(("text", c[1]))
            elif t == "RawBlock":
                if c[0] == "html":
                    items.append(("raw", drop(c[1])))
            elif t == "RawInline":
                if c[0] == "html":
                    marker = next(free)
                    buf.append(marker)
                    raws[marker] = drop(c[1])
            elif t == "Link":
                walk(c[1], buf, raws)
                buf.append(" " + drop(c[2][0]) + " ")
            elif t == "Image":
                # The alt is not text the page shows: the images step drops it for a file that is
                # not there. (A link the strip makes an image of loses its words, and is refused.)
                buf.append(" " + drop(c[2][0]) + " ")
            elif t == "Math":
                buf.append(" " + drop(c[1]) + " ")
            elif t in _TEXT_BLOCKS:
                inner: list[str] = []
                inner_raws: dict[str, str] = {}
                walk(c, inner, inner_raws)
                items.append(("block", drop("".join(inner)), inner_raws))
            else:
                walk(c, buf, raws)

    walk(_json_loads(r.stdout)["blocks"], [], [])
    words: Counter = Counter()
    hidden = None
    for item in items:
        if item[0] == "raw":
            found, hidden = _raw_scan(item[1], hidden)
            words.update(found)
        elif item[0] == "text":
            if not hidden:
                words.update(_TOKEN_RE.findall(drop(item[1])))
        else:
            # A raw tag or comment between two stretches of text does not split a word
            # (`emph<!-- x -->asis` is one word to the strip, `x<b>y</b>` to a browser).
            shown = []
            for ch in _spelled_out(item[1], item[2]):
                if ch in item[2]:
                    found, hidden = _raw_scan(item[2][ch], hidden)
                    words.update(found)
                elif not hidden:
                    shown.append(ch)
            words.update(_TOKEN_RE.findall("".join(shown)))
    return words


def _stripped_runs(src: str) -> list[tuple[int, int]]:
    """The stretches of `src` that `strip_comments` takes out, in `src`'s own offsets:
    every pass of it, so a comment that the first pass joins together is in them."""
    alive, text = list(range(len(src))), src
    while True:
        spans = [m.span() for m in COMMENT_RE.finditer(text)]
        if not spans:
            break
        keep, pos = [], 0
        for a, b in spans:
            keep.extend(alive[pos:a])
            pos = b
        keep.extend(alive[pos:])
        alive = keep
        text = "".join(src[i] for i in alive)
    runs, pos = [], 0
    for i in alive + [len(src)]:
        if i > pos:
            runs.append((pos, i))
        pos = i + 1
    return runs


_BLANK_LINE_RE = re.compile(r"\n[ \t]*\n")
_TAG_START = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz/!?")
_OPEN_VALUE_RE = re.compile(r"""=\s*(?:"[^"]*|'[^']*)\Z""")


def _code_flags(src: str, comments: bool = False) -> bytearray:
    """One byte for each character of `src`, 1 where it is code: a fence, an indented block or an
    inline code span, and with `comments` a comment too."""
    flags, pos = bytearray(len(src)), 0
    for b in split_md_blocks(src):
        end = pos + len(b.text)
        if b.kind in ("fence", "indented_code"):
            flags[pos:end] = b"\1" * (end - pos)
        else:
            masked = rdc._mask_code(b.text)
            if masked != b.text:
                for i, (x, y) in enumerate(zip(b.text, masked)):
                    if x != y:
                        flags[pos + i] = 1
        pos = end
    if comments:
        for m in COMMENT_RE.finditer(src):
            flags[m.start():m.end()] = b"\1" * (m.end() - m.start())
    return flags


def _first_joined_markup(src: str, runs: list[tuple[int, int]]) -> int | None:
    """The index of the first stretch the strip takes out from between two halves of markup that
    it joins: the words of the page are not the question here, the joining is.

    Code is an example, not markup: a stretch inside a fence or a code span joins nothing, and a
    `<`, a `>`, a bracket or a parenthesis in code is not one the rules below read.

    A stretch inside a tag: a `<` followed by a letter, `/`, `!` or `?` before the place the
    stretch was, with nothing after it but characters that are not delimiters (no `<`, no `>`,
    no blank line) up to that place. The halves make a tag the writer never wrote: one the
    sanitiser deletes with everything it holds (`<fo<!-- x -->rm>`), one a browser lets hide
    what follows (`<div hidden<!-- x -->>`), or one nothing closes before the block ends
    (`<td title="<!-->`), which a browser carries on into the next block. It is one rule and not
    a list of tags: whatever the tag becomes, the stretch was inside it. A `>` later in the block
    or an attribute value left open closes the question; without either, `x<y and <!-- c --> z`
    is text on both sides and is not refused.

    A stretch between `]` and `(`: the halves make a link, and the words of the second move into
    an address, which counts as shown (a word that moved there is on the page, or
    `[KEEP1](http://x/<!-- c -->y)` would be refused with nothing lost)."""
    code = _code_flags(src)
    # Code is blanked with a character that is no delimiter, no space and no letter, so that a
    # line of a fence does not read as a blank line and `<` before a code span is not a tag.
    seen = "".join("." if code[i] and ch != "\n" else ch for i, ch in enumerate(src))
    parts, pos = [], 0
    for a, b in runs:
        parts.append(seen[pos:a])
        pos = b
    parts.append(seen[pos:])
    text = "".join(parts)                           # what the strip leaves, code blanked
    gone = 0
    for n, (a, b) in enumerate(runs):
        at = a - gone                               # where the stretch was, in `text`
        gone += b - a
        if all(code[a:b]):
            continue
        if seen[a - 1:a] == "]" and seen[b:b + 1] == "(":
            return n
        lt = text.rfind("<", 0, at)
        if lt < 0 or text.rfind(">", 0, at) > lt or text[lt + 1:lt + 2] not in _TAG_START:
            continue
        if _BLANK_LINE_RE.search(text, lt, at):
            continue
        # The halves make a tag only if something closes it in the block, or the stretch sat in an
        # attribute value that the strip leaves open. Without either, `x<y and <!-- c --> z` is
        # text before and after.
        end = _BLANK_LINE_RE.search(text, at)
        closes = ">" in text[at:end.start() if end else len(text)]
        if closes or _OPEN_VALUE_RE.search(text, lt, at):
            return n
    return None


def _dropped_text_line(src: str) -> int | None:
    """The line where the strip would take text out of the share copy, or None.

    The strip closes a `<!--` with the next `-->` wherever it is, and pandoc does not
    always agree that it was a comment: an opener in running text, in a code span or a
    fence, in front matter or an attribute, a bare arrow in a flow chart, an escaped
    `\\<!--`, and a browser that ends a comment at `--!>`. Every shape the strip and the
    reader can disagree on is one question: are the words pandoc shows before the strip
    still shown after it? It is asked twice. With each stretch the strip takes replaced
    by a hole (not by nothing: a comment quoted whole in a code span is the example's loss
    alone, and the backticks it leaves must not pair up and count the words between as
    code); and with the stretches gone as the strip leaves it, where a word that moved
    into code or an address is still on the page but one that the strip's joining made
    part of a tag (`<scr<!-- x -->ipt>`) is not. The first stretch whose removal loses a
    word is the line, found by halving. Three runs of pandoc on the way through, a few
    more only when it refuses. A tree the check cannot read (nested too deep for its walk) is
    refused here, as an `UnclosedComment` that says so, at the first stretch the strip takes."""
    runs = _stripped_runs(src)
    if not runs:
        return None
    # A hole of its own for each stretch, so that two places which differ in the source cannot
    # become equal (`[^<!--a-->]: x [^<!--b-->]` is not a footnote that cites itself), and none
    # that the source spells with an entity (`&#xE000;` is a character of the text).
    free = _free_chars(set(src) | set(html.unescape(src)))
    holes = [next(free) for _ in runs]

    def holed(k: int) -> str:
        out, pos = [], 0
        for (a, b), hole in zip(runs[:k], holes):
            out += [src[pos:a], hole]
            pos = b
        return "".join(out) + src[pos:]

    def gone(k: int) -> str:
        out, pos = [], 0
        for a, b in runs[:k]:
            out.append(src[pos:a])
            pos = b
        return "".join(out) + src[pos:]

    # The stretches before the first one that joins markup are asked about as before; that one is
    # refused whatever they say.
    tag = _first_joined_markup(src, runs)
    last = len(runs) if tag is None else tag
    if tag == 0:
        return src.count("\n", 0, runs[0][0]) + 1
    try:
        shown = _shown_words(src)

        def lost(k: int) -> bool:
            return bool(shown - _shown_words(holed(k), "".join(holes[:k]))) or bool(shown - _shown_words(gone(k), code=True))

        if not lost(last):
            return None if tag is None else src.count("\n", 0, runs[tag][0]) + 1
        lo, hi = 0, last                    # nothing taken loses nothing; all of it does
        while hi - lo > 1:
            mid = (lo + hi) // 2
            lo, hi = (lo, mid) if lost(mid) else (mid, hi)
    except subprocess.CalledProcessError as e:
        # The check could not read the document, and the render reads what the strip leaves:
        # the strip can take the very stretch pandoc failed on (a footnote that cites itself),
        # so a copy made now would be made unchecked, and could lack text. The page's own
        # run of the same text fails the same way.
        raise RenderError(f"pandoc could not read this document: {(e.stderr or '').strip()[:200]}") from None
    except (ValueError, RecursionError):
        # The check could not read the tree (it is nested too deep for the walk in `_shown_words`,
        # the same on every Python), and the render reads what the strip leaves: refuse at the first
        # stretch rather than make a copy nobody checked. That stretch may be a closed comment
        # that loses nothing, so the message names the tree, not the stretch.
        raise UnclosedComment(src.count("\n", 0, runs[0][0]) + 1, unreadable=True) from None
    return src.count("\n", 0, runs[hi - 1][0]) + 1


_RAW_ELEMENT_RE = re.compile(r"<(script|style)(?=[\s/>])(?![^>]*/>)[^>]*>", re.I)


def _unclosed_raw_element(frag: str, original: str) -> tuple[str, int] | None:
    """The first `<script>` or `<style>` in pandoc's html that nothing closes, with the line of
    its opener in the source, or None. The sanitiser reads one as an element that runs to the end
    of the document (a browser hides the same text) and removes it with everything after it; its
    own log line names the tag and not the text that went with it. A comment (the page keeps its
    comments in `frag`) and code are words: pandoc escapes the code, and neither is a tag."""
    bare = COMMENT_RE.sub(" ", CODE_HTML_RE.sub(" ", frag))
    for m in _RAW_ELEMENT_RE.finditer(bare):
        name = m.group(1).lower()
        if re.search(rf"</{name}\s*>", bare[m.end():], re.I):
            continue
        return name, _open_element_line(original, name)
    return None


def _open_element_line(original: str, name: str) -> int:
    """The line of the first `<name>` of the source that nothing closes, reading the openers and
    closers in order as a browser does: an opener runs to the next closer, and the openers in
    between are its text. Code and comments hold none."""
    skip = _code_flags(original, comments=True)
    opener = re.compile(rf"<{name}(?=[\s/>])(?![^>]*/>)", re.I)
    closer = re.compile(rf"</{name}\s*>", re.I)
    pos = 0
    while True:
        o = next((m for m in opener.finditer(original, pos) if not skip[m.start()]), None)
        if o is None:
            return 1
        c = next((m for m in closer.finditer(original, o.end()) if not skip[m.start()]), None)
        if c is None:
            return original.count("\n", 0, o.start()) + 1
        pos = c.end()


def _shown_head_line(src: str) -> int:
    """The line of the head of a note that is not closed: the first one no closed
    comment holds and no code block quotes, else the first one."""
    spans = [m.span() for m in COMMENT_RE.finditer(src)]
    code, pos = [], 0
    for b in split_md_blocks(src):
        if b.kind in rdc.CODE_KINDS:
            code.append((pos, pos + len(b.content)))
        pos += len(b.text)
    first = None
    for m in rdc.COMMENT_RE.finditer(src):
        if any(a <= m.start() < b for a, b in spans):
            continue
        line = src.count("\n", 0, m.start()) + 1
        first = first or line
        if not any(a <= m.start() < b for a, b in code):
            return line
    return first or 1


# ───────────────────────────────────────────────────────────────── transforms ──

def pandoc_html(text: str) -> str:
    """The bundled pandoc, never whatever is on PATH (SPEC 3.2)."""
    r = _pandoc.run(["-f", "gfm", "-t", "html5", "--no-highlight"], text)
    if r.returncode != 0:
        raise RenderError(f"pandoc could not read this document: {r.stderr.strip()[:200]}")
    return r.stdout


PRE_RE = re.compile(r"(<pre\b[\s\S]*?</pre>)", re.I)


def _same_render(a: str, b: str) -> bool:
    """Do the page's two renders say the same thing? Whitespace between elements is
    not a difference; inside a <pre> it is, because the markers the splitter puts
    between the blocks of a raw <pre> with a blank line would show there."""
    def n(h):
        parts = PRE_RE.split(SENTINEL_RE.sub("", h))
        return "".join(p if i % 2 else re.sub(r"\s+", " ", p) for i, p in enumerate(parts)).strip()
    return n(a) == n(b)


def slugger():
    seen = {}
    def make(text):
        t = html.unescape(re.sub(r"<[^>]+>", "", text))
        t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
        t = re.sub(r"[^\w\s-]", "", t).strip().lower()
        t = re.sub(r"[\s_]+", "-", t) or "sec"
        n = seen.get(t, 0); seen[t] = n + 1
        return f"{t}-{n}" if n else t
    return make


def protect_code(hml):
    """Split into alternating (text, code) chunks so rewrites never touch code."""
    return re.split(r"(<pre\b[\s\S]*?</pre>|<code\b[\s\S]*?</code>)", hml)


def linkify_paths(hml):
    """Absolute local paths -> clickable file:// links.

    Skips fenced code and existing links. Inline `backticks` are NOT skipped when the
    whole <code> element is one path: that is how people actually write a reference
    ("the workbook is at `/home/...`"), and protecting it would leave most path
    references unclickable, which is the failure the rule exists to prevent. A code sample like `cp /home/a /home/b` has more than one path
    in it and so is left alone.
    """
    pat = re.compile(r"(?<![\w/=\"'])(/(?:home|Users|opt|var|etc|srv)/[\w.@+~-]+(?:/[\w.@+~%-]+)+)")
    parts = protect_code(hml)
    for i in range(0, len(parts), 2):
        chunk = parts[i]
        out, last = [], 0
        for m in pat.finditer(chunk):
            before = chunk[max(0, m.start() - 260):m.start()]
            if before.rfind("<a ") > before.rfind("</a>"):   # already inside a link
                continue
            out.append(chunk[last:m.start()])
            p = m.group(1)
            out.append(f'<a class="filelink" href="file://{p}">{p}</a>')
            last = m.end()
        out.append(chunk[last:])
        parts[i] = "".join(out)

    for i in range(1, len(parts), 2):          # the protected chunks
        c = parts[i]
        if not c.startswith("<code"):          # <pre> wins the alternation, so fenced
            continue                           # blocks never reach here
        m = re.fullmatch(r"(<code[^>]*>)([^<]+)(</code>)", c)
        if m and pat.fullmatch(m.group(2).strip()):
            path = m.group(2).strip()
            parts[i] = (f'{m.group(1)}<a class="filelink" href="file://{path}">'
                        f'{path}</a>{m.group(3)}')
    return "".join(parts)


def mark_lead_ins(hml: str) -> str:
    """Tag paragraphs that end in a colon, so print keeps them with what follows.

    CSS cannot select on text content, so the class has to be applied here. A
    paragraph ending in a colon introduces the list or table under it, and a
    page break between the two strands the introduction: the reader turns the
    page to find bullets whose lead-in was on the previous sheet. Same family
    as a table header repeating over a single stranded row.
    """
    def repl(m):
        attrs, inner = m.group(1), m.group(2)
        if not re.sub(r"<[^>]+>", "", inner).rstrip().endswith(":"):
            return m.group(0)
        if 'class="' in attrs:
            attrs = re.sub(r'class="([^"]*)"', r'class="\1 leadin"', attrs, count=1)
        else:
            attrs += ' class="leadin"'
        return f"<p{attrs}>{inner}</p>"
    # The name must end at the "p": a bare "<p" also opens <polygon>, <path>, <pre>.
    return re.sub(r"<p((?:\s[^>]*)?)>([\s\S]*?)</p>", repl, hml)


# Any whitespace before the label, not a newline specifically. pandoc reflows
# its output, so whether the newline the author wrote survives into the HTML
# depends on how long the lines happen to be: short header fields get folded
# onto one line and the newline is gone. Matching only "\n" therefore worked on
# long field values and silently failed on short ones, which is the wrong way
# round -- it is the tidy three-line header that broke. The paragraph has
# already been checked to OPEN with a bold label before this runs, so every
# bold "Label:" inside it is a field rather than prose.
LABEL_LINE = re.compile(r"\s+(<strong>[^<>]{1,44}:</strong>)")


def doc_header(frag: str, by: str, for_: str | None) -> str:
    """Put a header on the document: who prepared it, one labelled field per line.

    A report or a set of notes often opens with a run of "**Label:** value"
    lines -- Date, Attendees, Status. Markdown folds soft line breaks, so they
    arrived glued into one paragraph and had to be read apart. Pandoc keeps the
    author's newline in its output, so breaking on "\n<strong>Label:</strong>"
    splits exactly where the author started a line and leaves a wrapped
    continuation attached to its own field.

    Done on the HTML, never on the markdown. Edit mode maps DOM nodes back to
    source blocks by index and guards the file with a hash of the raw source, so
    rewriting the markdown here would corrupt the document on the first Ctrl+S.
    """
    m = re.search(r"</h1>", frag)
    at = m.end() if m else 0
    head = ""
    if by:
        # data-rd-ui: the page leaves it out of the title block's text, which the
        # server counts from the .md, where the byline is not.
        head = (f'<p class="doc-by" data-rd-ui>Document prepared by {html.escape(by)}'
                + (f' for {html.escape(for_)}' if for_ else "") + '</p>')

    # First paragraph after the title, and only if it opens with a bold label.
    pm = re.compile(r"<p([^>]*)>([\s\S]*?)</p>").search(frag, at)
    if pm and re.match(r"\s*(?:<!--[^>]*-->\s*)?<strong>[^<>]{1,44}:</strong>", pm.group(2)):
        attrs, inner = pm.group(1), pm.group(2)
        inner = LABEL_LINE.sub(r"<br>\n\1", inner)
        cls = re.search(r'class="([^"]*)"', attrs)
        if cls:
            attrs = attrs.replace(cls.group(0), f'class="{cls.group(1)} doc-fields"')
        else:
            attrs += ' class="doc-fields"'
        frag = frag[:pm.start()] + f"<p{attrs}>{inner}</p>" + frag[pm.end():]
    return frag[:at] + head + frag[at:]


def _page_asset(name: str) -> str:
    return (resources.files("sheafmd") / "page" / name).read_text(encoding="utf-8")


FRONT_MATTER_TITLE_RE = re.compile(r"\A---\r?\n(?:(?!---\r?\n).*\r?\n)*?title:[ \t]*\S")


def no_title_warning(first_section: str, tab: str, front_matter_title: bool = False) -> str:
    """The stderr text for a document with no H1."""
    opens = f'on its first section, "{first_section}"' if first_section else "with no heading"
    shown = "; a front-matter `title:` is not shown" if front_matter_title else ""
    return (f"  ! no `# ` title line: the page opens {opens}, and the browser tab says "
            f'"{tab}"{shown}.\n'
            "    Start the document with one `# ` line that names its subject in plain words.")


# ──────────────────────────────────────────────────────────────────── build() ──

def build(md: Path, *, theme: Theme, share: bool = True, title: str | None = None,
          toc: str = "auto", max_image_width: int = 1400, by: str = "",
          for_: str | None = None, credit: bool = False, link_rule: bool = True,
          link_tlds=(), log: list[str], src: str | None = None, warn=None,
          extra_meta: dict | None = None, script_nonce: str | None = None, image_ok=None) -> str:
    """The HTML of `md`, as a share copy (`share=True`) or as the page.

    `log` collects the render log: "  +" added, "  !" warning, "  -" removed.
    `warn(text)` receives the link-rule warning; the hub's re-renders after a save
    pass none, so a bare host name is reported once, when the document is first
    rendered, not on every save. `extra_meta` is what the hub adds to the page's
    meta block (SPEC 10.1). `script_nonce` is the CSP nonce the hub puts on the page's script
    element (SPEC 9.5). `image_ok(path)`, when given, is which local images may be embedded
    (proxy mode, SPEC 9.9): any other is left out."""
    md = Path(md)
    # 1. Read the source. A share copy loses every HTML comment, in the source.
    if src is None:
        src = md.read_text(encoding="utf-8")
    original = src
    if share:
        # A reviewer's comment that lost its closing arrow is never stripped-and-
        # warned: here a later arrow would close it for the strip and take the text
        # between; below, pandoc would print what nothing closed.
        line = _swallowed_note_line(original)
        if line:
            raise UnclosedComment(line, note=True)
        # And any opener the strip would close with a later arrow that pandoc does not
        # take for a comment: nothing leaks, but the text between would go.
        line = _dropped_text_line(original)
        if line:
            raise UnclosedComment(line, swallows=True)
        src = strip_comments(src, log)
        for n in _stray_tails(original):
            log.append(f'  ! line {n} starts with "-->" outside any comment; if an earlier '
                       "edit cut a comment in two, this is its tail and it shows as text")

    # 2. pandoc.
    frag = pandoc_html(src)
    if share and _shows_a_note(frag):
        raise UnclosedComment(_shown_head_line(original), note=True)
    if share and "<!--" in frag:
        # A comment that survived: the stripped source held an opener nothing closes
        # (pandoc would pass it on and a browser would hide the rest of the page), or
        # pandoc made one of its own. Never ship it.
        line = _unclosed_line(original, frag)
        if line:
            head = rdc.COMMENT_RE.search(original.split("\n")[line - 1])
            raise UnclosedComment(line, note=bool(head))
        log.append("  ! pandoc produced an HTML comment in the share copy; it was removed")
        frag = strip_comments(frag, log)

    # 3. Page only: the same source with block sentinels. Injecting them is supposed
    # to be render-inert, and is on nearly every document, but "supposed to" is not
    # good enough for a document about to be read. So render both ways and compare.
    # If they disagree, the plain render wins and this document is simply not
    # editable: a document that renders wrong is a much worse failure than one that
    # cannot be edited in the browser.
    blocks, why = None, ""
    if not share:
        try:
            inst, blks = instrument(src)
            marked = pandoc_html(inst)
            if _same_render(marked, frag):
                frag, blocks = marked, blks
            else:
                why = "block markers would alter this render"
                log.append("  ! edit mode off: " + why)
        except RenderError:
            why = "pandoc rejected the instrumented source"
            log.append("  ! edit mode off: " + why)

    # 4. Raw HTML in the document: remove what can run, load or navigate (SPEC 9.5).
    open_element = _unclosed_raw_element(frag, original)
    if open_element:
        log.append(f"  ! line {open_element[1]}: <{open_element[0]}> is never closed, so the text "
                   "after it is removed from the document too")
    frag = sanitizer.sanitize(frag, comments=not share, log=log)

    # 5. Headings h1 to h4: ids, flags, the table of contents.
    slug, toc_rows, first_h1, first_head = slugger(), [], [], []
    def head(m):
        lvl, attrs, inner = int(m.group(1)), m.group(2), m.group(3)
        # Comments first: a review comment in a heading holds "<br>", and the tag
        # pattern below would stop at its ">" and put the comment's text into the
        # contents and the heading's id.
        bare = COMMENT_RE.sub("", inner)
        plain = " ".join(html.unescape(re.sub(r"<[^>]+>", "", bare)).split())
        sid = slug(bare)
        flagged = bool(FLAG_RE.search(plain[:70]))
        if lvl == 1 and not first_h1:
            first_h1.append(plain)
        if not first_head:
            first_head.append(plain)
        if lvl <= 3:
            toc_rows.append((lvl, sid, re.sub(r"^[⚠️\s]+", "", plain), flagged))
        cls = ' class="flagged"' if flagged else ""
        # pandoc already emitted its own id=; drop it so the heading does not
        # carry two id attributes (invalid HTML, and the two disagree on
        # accented headings because our slugger ASCII-folds and pandoc does not)
        attrs = re.sub(r'\s*\bid="[^"]*"', "", attrs)
        return f'<h{lvl} id="{sid}"{cls}{attrs}>{inner}</h{lvl}>'
    frag = re.sub(r"<h([1-4])([^>]*)>([\s\S]*?)</h\1>", head, frag)

    # 6. Charts and diagrams, inline.
    frag = charts.render_charts(frag)
    frag = charts.render_mermaid(frag, log)
    # 7. Local images, embedded.
    frag = images.process_images(frag, md.parent, max_image_width, log, image_ok)
    # 8. Absolute local paths become file:// links.
    frag = linkify_paths(frag)
    # 9. The link rule: a warning, never a block, and only for a command-line render.
    if warn and link_rule:
        found = links.unlinked_mentions(frag, link_tlds)
        if found:
            warn(links.warning(found))
    # 9b. The title rule: the page title is the first H1, so a document without
    # one opens on its first section. Same terms as the link rule.
    if warn and not first_h1:
        warn(no_title_warning(first_head[0] if first_head else "",
                              title or md.stem.replace("-", " "),
                              bool(FRONT_MATTER_TITLE_RE.match(original))))
    # 10. Lead-ins. 11. The document header. 12. Tables.
    frag = mark_lead_ins(frag)
    frag = doc_header(frag, by, for_)
    frag = re.sub(r"(<table[\s\S]*?</table>)", r'<div class="tblwrap">\1</div>', frag)

    # 13. The table of contents.
    want_toc = toc == "always" or (toc == "auto" and len(toc_rows) >= 6)
    nav = ""
    if want_toc:
        rows = "".join(
            f'<a class="lv{l}{" flag" if f else ""}" href="#{s}">{html.escape(p)}</a>'
            for l, s, p, f in toc_rows)
        nav = f'<nav id="toc"><div class="lbl">Contents</div>{rows}</nav>'

    # 14. Assemble.
    title = title or (first_h1[0] if first_h1 and first_h1[0] else "") \
        or md.stem.replace("-", " ")
    css = BASE_CSS + theme.css
    if theme.pdf_footer:
        css += ("\n@media print{@page{@bottom-left{content:\"" + css_string(theme.pdf_footer)
                + "\";font-size:7pt;color:#000;vertical-align:middle;padding-left:15pt}}}")
    fonts = font_css(theme, log)
    mark = ""
    if theme.wordmark:
        mark = (f'<p class="doc-mark"><b>{html.escape(theme.wordmark)}</b>'
                + (f'<span>{html.escape(theme.tagline)}</span>' if theme.tagline else "")
                + "</p>")
    tail = CREDIT if credit else ""

    editor = ""
    if not share:
        parsed = rdc.parse(src)
        meta = {
            "name": md.name,
            "hash": src_mod.md_hash(src),
            "editable": [i for i, b in enumerate(blocks) if b.editable] if blocks else [],
            "commentable": [i for i, b in enumerate(blocks) if b.kind in COMMENTABLE]
                           if blocks else [],
            "edit": blocks is not None,
            "why": why,
            "me": by,
            "comments": [c.as_dict() for c in parsed.comments],
            "malformed": [{"line": m.line, "reason": m.reason} for m in parsed.malformed],
            **(extra_meta or {}),
        }
        css += "\n" + _page_asset("page.css")
        # "<" escaped: comment text is in here, and a comment holding "</script>"
        # would otherwise end this element and put the rest of it into the page.
        nonce = f' nonce="{html.escape(script_nonce, quote=True)}"' if script_nonce else ""
        editor = ('<script id="rd-edit-meta" type="application/json">'
                  + json.dumps(meta).replace("<", "\\u003c")
                  + f"</script>\n<script{nonce}>" + _page_asset("page.js") + "</script>")
        if blocks is None:
            log.append("  + export only: no in-page editing")
        else:
            log.append(f"  + edit mode, {len(meta['editable'])}/{len(blocks)} blocks editable")

    out = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>{fonts}{css}</style></head>
<body class="{'' if want_toc else 'notoc'}">
<div id="wrap">{nav}<main>{mark}{frag}{tail}</main></div>
{editor}
</body></html>"""

    if share:
        # The last check, on the bytes that will be sent. Nothing above can be trusted
        # to have caught everything; this cannot be argued with.
        if "<!--" in out:
            log.append("  ! the share copy held an HTML comment after assembly; it was removed")
            out = strip_comments(out, log)
        if re.search(r"<script\b", out, re.I):
            raise RenderError("the share copy would carry a script; nothing was written")
    return out


# ───────────────────────────────────────────────────────────────── render_file ──

def render_file(path, *, share: bool = True, theme=None, title: str | None = None,
                toc: str = "auto", max_image_width: int = 1400, by: str | None = None,
                for_: str | None = None, credit: bool | None = None, log: list[str] | None = None,
                warn=None,
                src: str | None = None, extra_meta: dict | None = None,
                root: Path | None = None, script_nonce: str | None = None, image_ok=None) -> str:
    """Everything `sheafmd.render` does, plus the arguments only the CLI and the hub
    use (`warn`, `src`, `extra_meta`, `root`, `script_nonce`, `image_ok`). Reads the root's `.sheaf.toml` itself:
    `for`, `links`, `link_tlds`, `credit` and the theme.

    `log` receives every render-log line. Without one, the warnings ("  !") go to
    stderr: a font that is missing or a comment that was removed is never silent."""
    path = Path(path)
    own = log is None
    log = [] if own else log
    root = Path(root) if root else config.find_root(path)
    rc = config.load_root_config(root, lambda s: log.append(s))
    if not isinstance(theme, Theme):
        theme = load_theme(theme or rc.theme or "plain", root, lambda s: log.append(s))
    html_out = build(path, theme=theme, share=share, title=title, toc=toc,
                     max_image_width=max_image_width,
                     by=by if by is not None else config.user_name(),
                     for_=for_ if for_ is not None else rc.for_,
                     credit=rc.credit if credit is None else credit,
                     link_rule=rc.links, link_tlds=rc.link_tlds, log=log, src=src,
                     warn=warn, extra_meta=extra_meta, script_nonce=script_nonce, image_ok=image_ok)
    if own:
        import sys
        for line in log:
            if line.lstrip().startswith("!"):
                print(line, file=sys.stderr)
    return html_out
