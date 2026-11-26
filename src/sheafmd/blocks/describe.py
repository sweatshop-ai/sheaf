"""A block tree as the MCP door's `blocks` tool tells it (block editor v1, ticket 14).

Per block: `id` (the id the Document service gives, so an edit can name it), `type`, `attrs`, `capabilities`
(`edit`, `move`, `remove`: a locked block and a Stub have only the last two), `markdown` and `children`.
A top-level block's Markdown is its own bytes in the file. A child of a quote, a list or a Rich block holds no
bytes of its own (`tree.py`), so its Markdown is written from its AST by the pinned pandoc.
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


@functools.lru_cache(maxsize=1)
def _api_version() -> list:
    got = _pandoc.run(["-f", "markdown", "-t", "json"], "")
    return json.loads(got.stdout)["pandoc-api-version"]


@functools.lru_cache(maxsize=2048)
def _written(ast: str) -> str:
    """The Markdown of a nested block, from its AST (a list item is written as its content)."""
    blocks = json.loads(ast)
    if blocks and blocks[0].get("t") == "Item":
        blocks = blocks[0]["c"]
    doc = {"pandoc-api-version": _api_version(), "meta": {}, "blocks": blocks}
    got = _pandoc.run(["-f", "json", "-t", "gfm", "--wrap=none"], json.dumps(doc))
    return got.stdout.strip("\n") if got.returncode == 0 else ""


def one(b: Block, depth: int | None, top: bool, text: bool = True) -> dict:
    """`b` as a row. `depth` is the levels of children still to show (None: all); a block cut by it says
    in `more` how many children it left out. Without `text` the row has no `markdown` and only the structural
    attributes: nothing a person wrote (SPEC 9.7)."""
    out = {"id": b.id, "type": b.type,
           "attrs": dict(b.attrs) if text else decl.structural(b.type, b.attrs),
           "capabilities": [c for c in ORDER if c in b.caps], "children": []}
    if text:
        out["markdown"] = b.content.rstrip("\n") if top else _written(b.ast)
    if depth is None or depth > 1:
        out["children"] = [one(c, None if depth is None else depth - 1, False, text) for c in b.children]
    elif b.children:
        out["more"] = len(b.children)
    return out


def rows(tree: Tree, depth: int | None = None, ids=None, text: bool = True) -> list:
    """The tree's top-level rows; or, for `ids`, the rows of those blocks wherever they sit, in the order asked,
    each with its own children cut by `depth`. Raises `NotFound` for an id the tree does not hold."""
    if ids is None:
        return [one(b, depth, True, text) for b in tree.blocks]
    top_ids = {b.id for b in tree.blocks}
    out = []
    for i in ids:
        b = tree.get(i)
        if b is None:
            raise NotFound(i)
        out.append(one(b, depth, i in top_ids, text))
    return out


__all__ = ["NotFound", "one", "rows"]
