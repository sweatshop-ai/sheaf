"""A block tree as the MCP door's `blocks` tool tells it (block editor v1, ticket 14).

Per block: `id` (the id the Document service gives, so an edit can name it), `type`, `attrs`, `capabilities`
(`edit`, `move`, `remove`: a locked block and a Stub have only the last two), `markdown` and `children`.
A top-level block's Markdown is its own bytes in the file. A child of a quote, a list or a Rich block holds no
bytes of its own (`tree.py`), so its Markdown is written from its AST by the pinned pandoc (as commonmark_x, so a column or a button keeps its Markdown form).
A Stub is listed by `type: "stub"`, with its type name in `attrs.type`, and its raw source as `markdown`.
"""
import functools
import json

from .. import _pandoc
from . import declarations as decl
from .tree import EDIT, MOVE, REMOVE, Block, Tree

ORDER = (EDIT, MOVE, REMOVE)


class NotFound(KeyError):
    """An id the tree does not hold."""


class WriteFailed(RuntimeError):
    """Pandoc could not write a nested block as Markdown. Never cached: the next call asks pandoc again."""


@functools.lru_cache(maxsize=1)
def _api_version() -> list:
    got = _pandoc.run(["-f", "markdown", "-t", "json"], "")
    try:
        return json.loads(got.stdout)["pandoc-api-version"]
    except (ValueError, KeyError):
        raise WriteFailed("pandoc gave no api version") from None


@functools.lru_cache(maxsize=2048)
def _written(ast: str) -> str:
    """The Markdown of a nested block, from its AST (a list item is written as its content). It describes the block
    and is not round-trip source: typography stays as it is (no `smart`), raw inline HTML stays HTML, a column and a
    button keep their fenced-div and bracketed-span forms."""
    blocks = json.loads(ast)
    if blocks and blocks[0].get("t") == "Item":
        blocks = blocks[0]["c"]
    doc = {"pandoc-api-version": _api_version(), "meta": {}, "blocks": blocks}
    got = _pandoc.run(["-f", "json", "-t", "commonmark_x-smart+raw_html-raw_attribute", "--wrap=none"], json.dumps(doc))
    if got.returncode != 0:
        raise WriteFailed(got.stderr.strip()[:200] or "pandoc exited with an error")
    return got.stdout.strip("\n")


def one(b: Block, depth: int | None, top: bool, text: bool = True, alias: dict | None = None) -> dict:
    """`b` as a row. `depth` is the levels of children still to show (None: all); a block cut by it says
    in `more` how many children it left out. Without `text` the row has no `markdown` and only the structural
    attributes: nothing a person wrote (SPEC 9.7)."""
    out = {"id": alias[id(b)] if alias else b.id, "type": b.type,
           "attrs": dict(b.attrs) if text else decl.structural(b.type, b.attrs),
           "capabilities": [c for c in ORDER if c in b.caps], "children": []}
    if text:
        out["markdown"] = b.content.rstrip("\n") if top else _written(b.ast)
    if depth is None or depth > 1:
        out["children"] = [one(c, None if depth is None else depth - 1, False, text, alias) for c in b.children]
    elif b.children:
        out["more"] = len(b.children)
    return out


def _opaque(tree: Tree) -> tuple:
    """`({id(block): p1, p2, ...}, {p1: block, ...})` in document order (a block before its children), for a caller
    who may not read the page's text: its ids say where a block sits and nothing of what it holds, and hold only
    for the page as it is. Keyed by the block itself, never by its id: two blocks that share an id still get two
    aliases, and the alias numbering never shows that they share one."""
    alias, by_alias = {}, {}

    def walk(b):
        name = f"p{len(alias) + 1}"
        alias[id(b)], by_alias[name] = name, b
        for c in b.children:
            walk(c)
    for b in tree.blocks:
        walk(b)
    return alias, by_alias


def rows(tree: Tree, depth: int | None = None, ids=None, text: bool = True) -> list:
    """The tree's top-level rows; or, for `ids`, the rows of those blocks wherever they sit, in the order asked,
    each with its own children cut by `depth`. Without `text` every id is an opaque positional one (`p1`, `p2`...,
    in document order) and `ids` are read as such. Raises `NotFound` for an id the tree does not hold."""
    alias, by_alias = (None, {}) if text else _opaque(tree)
    if ids is None:
        return [one(b, depth, True, text, alias) for b in tree.blocks]
    tops = {id(b) for b in tree.blocks}
    out = []
    for i in ids:
        b = by_alias.get(i) if alias else tree.get(i)
        if b is None:
            raise NotFound(i)
        out.append(one(b, depth, id(b) in tops, text, alias))
    return out


__all__ = ["NotFound", "WriteFailed", "one", "rows"]
