"""The block tree of plain Markdown (ADR 0004): per block an id, a Block type, attributes, capabilities,
content and children.

The text is read once through the pinned pandoc as `gfm+fenced_divs+bracketed_spans`, with the flat model's
sentinels between its tiles (`flat.instrument`): the sentinels keep pandoc's view of the whole document (a
reference link defined in another block, a footnote) and tell which AST blocks belong to which tile, so each
top-level block has its own bytes and its own AST. Two versions of a block are equal when their AST is equal,
so pandoc's cosmetic rewrites (a fence of another length, a re-padded table) are no change.

A plain block has no stored id. Its id is a short hash of its type and its AST, suffixed `-2`, `-3` on the
second and later of equal blocks, so an edit elsewhere in the document leaves it valid and it changes once its
own block is edited.

Only the top-level blocks carry their bytes (`content`, then `gap`, the blank lines that follow it); the
children of a quote or a list are read from the AST and hold no text of their own.
"""
import hashlib
import json
from dataclasses import dataclass

from .. import _pandoc
from .flat import LOCKED_KINDS, SENTINEL_RE, instrument

FORMAT = "gfm+fenced_divs+bracketed_spans"
EDIT, MOVE, REMOVE = "edit", "move", "remove"
ALL = frozenset({EDIT, MOVE, REMOVE})
LOCKED = frozenset({MOVE, REMOVE})        # a fence, raw HTML, front matter: moved and removed, never edited in place


class Unreadable(Exception):
    """The text is one pandoc cannot read, or reads in a shape the tree cannot take."""


@dataclass(frozen=True)
class Block:
    id: str
    type: str
    attrs: dict
    caps: frozenset
    content: str = ""           # the block's own bytes, no trailing blank lines (top level only)
    gap: str = ""               # the blank lines that follow it, verbatim (top level only)
    children: tuple = ()
    ast: str = ""               # the block's pandoc AST as canonical JSON: the key of equality

    @property
    def key(self):
        return self.type, self.ast


@dataclass(frozen=True)
class Tree:
    text: str
    blocks: tuple = ()
    lead: str = ""              # blank lines before the first block

    @property
    def ids(self) -> list:
        return [b.id for b in self.blocks]

    def walk(self):
        """Every block, children after their parent, in document order."""
        def down(blocks):
            for b in blocks:
                yield b
                yield from down(b.children)
        yield from down(self.blocks)

    def get(self, id_):
        return next((b for b in self.walk() if b.id == id_), None)


_NAMES = {"Para": "paragraph", "Plain": "paragraph", "Header": "heading", "BulletList": "list",
          "OrderedList": "list", "BlockQuote": "quote", "Table": "table", "CodeBlock": "code",
          "RawBlock": "html", "HorizontalRule": "rule", "DefinitionList": "definitions",
          "LineBlock": "lines", "Div": "div", "Figure": "figure"}


def _canon(x) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _type_and_attrs(blocks: list, kind: str):
    if kind == "frontmatter":
        return "frontmatter", {}
    if not blocks:
        return "definitions", {}          # reference definitions and the like: text that is no block of the AST
    b = blocks[0]
    t = _NAMES.get(b["t"], b["t"].lower())
    if b["t"] == "Header":
        return t, {"level": b["c"][0]}
    if b["t"] == "CodeBlock":
        classes = b["c"][0][1]
        return t, {"lang": classes[0] if classes else ""}
    if b["t"] == "OrderedList":
        return t, {"ordered": True, "start": b["c"][0][0]}
    if b["t"] == "BulletList":
        return t, {"ordered": False}
    return t, {}


def _children(blocks: list) -> list:
    """(type, attrs, ast, its own children) for the blocks held by a quote or a list, from the AST."""
    out = []
    for b in blocks:
        t, attrs = _type_and_attrs([b], "")
        ast = [b]
        kids = []
        if b["t"] == "BlockQuote":
            kids = _children(b["c"])
        elif b["t"] in ("BulletList", "OrderedList"):
            items = b["c"] if b["t"] == "BulletList" else b["c"][1]
            kids = [("item", {}, [{"t": "Item", "c": item}], _children(item)) for item in items]
        out.append((t, attrs, ast, kids))
    return out


class _Ids:
    """Hands out ids in document order; a second block of the same type and AST gets a suffix."""

    def __init__(self):
        self.seen = {}

    def __call__(self, type_: str, ast: str) -> str:
        h = hashlib.sha1(f"{type_}\0{ast}".encode("utf-8")).hexdigest()[:8]
        n = self.seen[h] = self.seen.get(h, 0) + 1
        return h if n == 1 else f"{h}-{n}"


def _build(kids, ids: _Ids) -> tuple:
    out = []
    for t, attrs, ast, sub in kids:
        a = _canon(ast)
        out.append(Block(id=ids(t, a), type=t, attrs=attrs, caps=ALL, ast=a, children=_build(sub, ids)))
    return tuple(out)


def _segments(doc: dict) -> dict:
    """The AST blocks that follow each sentinel, by tile index."""
    seg, cur = {}, None
    for b in doc["blocks"]:
        if b["t"] == "RawBlock" and b["c"][0] == "html":
            m = SENTINEL_RE.fullmatch(b["c"][1].strip())
            if m:
                cur = int(m.group(1))
                seg[cur] = []
                continue
        if cur is not None:
            seg[cur].append(b)
    return seg


def read_tree(text: str) -> Tree:
    """The block tree of `text`. Raises `Unreadable` for a text pandoc does not read."""
    inst, tiles = instrument(text)
    live = [i for i, t in enumerate(tiles) if t.kind not in ("blank", "frontmatter") and t.content.strip()]
    seg = {}
    if live:
        got = _pandoc.run(["-f", FORMAT, "-t", "json"], inst)
        if got.returncode != 0:
            raise Unreadable(got.stderr.strip() or "pandoc did not read the text")
        try:
            seg = _segments(json.loads(got.stdout))
        except (ValueError, KeyError, TypeError) as e:
            raise Unreadable(f"the AST is not in the shape expected: {e}") from None
        if set(seg) != set(live):
            raise Unreadable("a block of the text is not a top-level block for pandoc")
    ids, blocks, lead = _Ids(), [], ""
    for i, tile in enumerate(tiles):
        if tile.kind == "blank":
            lead = tile.gap
            continue
        if tile.kind == "frontmatter":
            ast = tile.content           # front matter is equal when its bytes are
            t, attrs = "frontmatter", {}
            kids = ()
        else:
            ast_blocks = seg.get(i, [])
            t, attrs = _type_and_attrs(ast_blocks, tile.kind)
            # Reference and footnote definitions are no block of the AST: they are equal when their bytes are.
            ast = _canon(ast_blocks) if ast_blocks else tile.content
            kids = _children(ast_blocks[:1])[0][3] if ast_blocks else []
        locked = tile.kind in LOCKED_KINDS
        bid = ids(t, ast)
        blocks.append(Block(id=bid, type=t, attrs=attrs, caps=LOCKED if locked else ALL, content=tile.content,
                            gap=tile.gap, children=_build(kids, ids), ast=ast))
    return Tree(text=text, blocks=tuple(blocks), lead=lead)
