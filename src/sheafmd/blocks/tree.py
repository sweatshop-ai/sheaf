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
from . import declarations as decl
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


def _attrs(kvs) -> dict:
    """Attributes as pandoc renders them: of a repeated key the first value counts (the HTML writer drops the rest)."""
    out = {}
    for k, v in kvs:
        out.setdefault(k, v)
    return out


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
    if b["t"] == "Div":
        classes = b["c"][0][1]
        if classes and classes[0] in decl.DECLARED:
            return classes[0], _attrs(b["c"][0][2])
    return t, {}


_LOCKED_AST = frozenset({"CodeBlock", "RawBlock"})      # locked at the top level (fence, raw HTML, indented code): locked at every depth


def _source(div: dict, api) -> str:
    """The Markdown of a div held inside a quote or a list, written back by pandoc: children hold no bytes of their own."""
    doc = {"pandoc-api-version": api, "meta": {}, "blocks": [div]}
    got = _pandoc.run(["-f", "json", "-t", FORMAT, "--wrap=preserve"], json.dumps(doc))
    if got.returncode != 0:
        raise Unreadable(got.stderr.strip() or "pandoc did not write a div back")
    return got.stdout.rstrip("\n")


def _children(blocks: list, api) -> list:
    """(type, attrs, ast, its own children, stored id, caps, content) for the blocks held by a quote, a list or a div,
    from the AST. A div that is no declared type is a locked Stub with its type name and its source."""
    out = []
    for b in blocks:
        t, attrs = _type_and_attrs([b], "")
        ast = [b]
        kids, stored, caps, content = [], "", ALL, ""
        if b["t"] == "BlockQuote":
            kids = _children(b["c"], api)
        elif b["t"] == "Div":
            if t in decl.DECLARED:
                kids = _children(b["c"][1], api)
                stored = b["c"][0][0]
            else:
                classes = b["c"][0][1]
                content = _source(b, api)
                t, attrs, caps, ast = "stub", {"type": classes[0] if classes else "", "reason": "unknown type"}, LOCKED, content
                stored = b["c"][0][0]
        elif b["t"] in ("BulletList", "OrderedList"):
            items = b["c"] if b["t"] == "BulletList" else b["c"][1]
            kids = [("item", {}, [{"t": "Item", "c": item}], _children(item, api), "", ALL, "") for item in items]
        elif b["t"] in _LOCKED_AST:
            caps = LOCKED
        out.append((t, attrs, ast, kids, stored, caps, content))
    return out


class _Ids:
    """Hands out ids in document order; a second block of the same type and AST gets a suffix."""

    def __init__(self):
        self.seen = {}
        self.used = set()           # every id handed out, stored or generated: no two blocks share one
        self.reserved = set()       # every id written in the file: a generated id never takes one, wherever the block stands

    def take(self, stored: str, type_: str, ast: str) -> str:
        """A Rich block keeps the id written in the file; a missing or repeated one falls back to a derived id."""
        if stored and stored not in self.used:
            self.used.add(stored)
            return stored
        return self(type_, ast)

    def __call__(self, type_: str, ast: str) -> str:
        h = hashlib.sha1(f"{type_}\0{ast}".encode("utf-8")).hexdigest()[:8]
        while True:
            n = self.seen[h] = self.seen.get(h, 0) + 1
            id_ = h if n == 1 else f"{h}-{n}"
            if id_ not in self.used and id_ not in self.reserved:
                self.used.add(id_)
                return id_


def _build(kids, ids: _Ids) -> tuple:
    out = []
    for t, attrs, ast, sub, stored, caps, content in kids:
        a = ast if isinstance(ast, str) else _canon(ast)
        out.append(Block(id=ids.take(stored, t, a), type=t, attrs=attrs, caps=caps, content=content, ast=a,
                         children=_build(sub, ids)))
    return tuple(out)


def _div_ids(x, out: set) -> set:
    """Every id written on a div anywhere in the AST `x`."""
    if isinstance(x, dict):
        if x.get("t") == "Div" and x["c"][0][0]:
            out.add(x["c"][0][0])
        for v in x.values():
            _div_ids(v, out)
    elif isinstance(x, list):
        for v in x:
            _div_ids(v, out)
    return out


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


def _rich_found(blocks: list):
    """The first declared-type Div held by a plain container (a quote or a list item) in `blocks`, or None."""
    for b in blocks:
        t = b["t"]
        if t == "Div":
            classes = b["c"][0][1]
            if classes and classes[0] in decl.DECLARED:
                return classes[0]
            continue            # an unknown div is a locked Stub of its own: what it holds is no reason to lock its container
        elif t == "BlockQuote":
            inner = _rich_found(b["c"])
        elif t in ("BulletList", "OrderedList"):
            items = b["c"] if t == "BulletList" else b["c"][1]
            inner = next((r for r in map(_rich_found, items) if r), None)
        else:
            continue
        if inner:
            return inner
    return None


def _div_fault(b: dict, top: bool = True):
    """(type, reason) for a Div: the reason is None when it is a valid declared Rich block, whatever it holds.
    The Container rules are checked down through every div the block holds."""
    (_, classes, kvs), content = b["c"][0], b["c"][1]
    t = classes[0] if classes else ""
    if t not in decl.DECLARED:
        return t, "unknown type"
    for extra in classes[1:]:
        return t, f"{t} has class {extra!r}, which is not declared"
    kid_types = [_type_and_attrs([k], "")[0] for k in content]
    why = (decl.top_fault(t) if top else None) or decl.check_attrs(t, _attrs(kvs)) \
        or decl.check_children(t, kid_types) or _nested_fault(content)
    why = why or (t == "image" and _image_fault(content))
    why = why or next((f for k in content if k["t"] == "Div" and (f := _div_fault(k, top=False)[1])), None)
    return t, why or None


def _image_fault(content: list):
    """An image div holds one paragraph that is one image and nothing else: the image on a line of its own."""
    ok = len(content) == 1 and content[0]["t"] in ("Para", "Plain") and len(content[0]["c"]) == 1 \
        and content[0]["c"][0]["t"] == "Image"
    return None if ok else "an image holds one image on a line of its own"


def _nested_fault(content: list):
    """A Rich block inside a quote or a list inside the content is as forbidden as one in a quote at top level."""
    for k in content:
        found = _rich_found([k]) if k["t"] in ("BlockQuote", "BulletList", "OrderedList") else None
        if found:
            return f"a {found} may not sit inside a {_type_and_attrs([k], '')[0]}"
    return None


def read_tree(text: str) -> Tree:
    """The block tree of `text`. Raises `Unreadable` for a text pandoc does not read."""
    inst, tiles = instrument(text, divs=True)
    live = [i for i, t in enumerate(tiles) if t.kind not in ("blank", "frontmatter") and t.content.strip()]
    seg, api = {}, None
    if live:
        # Bytes that are not UTF-8 reach us as lone surrogates: pandoc reads a `?` there, the
        # tiles keep the bytes, so the file still writes back byte for byte.
        got = _pandoc.run(["-f", FORMAT, "-t", "json"], inst.encode("utf-8", "replace").decode("utf-8"))
        if got.returncode != 0:
            raise Unreadable(got.stderr.strip() or "pandoc did not read the text")
        try:
            parsed = json.loads(got.stdout)
            api, seg = parsed["pandoc-api-version"], _segments(parsed)
        except (ValueError, KeyError, TypeError) as e:
            raise Unreadable(f"the AST is not in the shape expected: {e}") from None
        if set(seg) != set(live):
            raise Unreadable("a block of the text is not a top-level block for pandoc")
    ids, blocks, lead = _Ids(), [], ""
    ids.reserved = _div_ids(list(seg.values()), set())
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
            stub = None            # (declared or unknown type, why it is a Stub), for a block that is no valid Rich block
            first = ast_blocks[0] if ast_blocks else None
            if first and first["t"] == "Div":
                rtype, why = _div_fault(first)
                if why:
                    stub = (rtype, why)
                else:
                    attrs = _attrs(first["c"][0][2])
            elif first and first["t"] in ("BlockQuote", "BulletList", "OrderedList"):
                found = _rich_found(ast_blocks[:1])
                if found:
                    stub = (found, f"a {found} may not sit inside a {t}")
            if stub:
                sid = first["c"][0][0] if first["t"] == "Div" else ""
                bid = ids.take(sid, "stub", tile.content)
                blocks.append(Block(id=bid, type="stub", attrs={"type": stub[0], "reason": stub[1]}, caps=LOCKED,
                                    content=tile.content, gap=tile.gap, ast=tile.content))
                continue
            # Reference and footnote definitions are no block of the AST: they are equal when their bytes are.
            ast = _canon(ast_blocks) if ast_blocks else tile.content
            kids = _children(ast_blocks[:1], api)[0][3] if ast_blocks else []
        locked = tile.kind in LOCKED_KINDS
        if t in decl.DECLARED:
            bid = ids.take(ast_blocks[0]["c"][0][0], t, ast)
        else:
            bid = ids(t, ast)
        blocks.append(Block(id=bid, type=t, attrs=attrs, caps=LOCKED if locked else ALL, content=tile.content,
                            gap=tile.gap, children=_build(kids, ids), ast=ast))
    return Tree(text=text, blocks=tuple(blocks), lead=lead)
