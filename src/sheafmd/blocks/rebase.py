"""Rebase (ADR 0007): a page's save made on an older base, put onto the file as it is now.

`rebase(base, current, page, held_ids)` is a three-way merge of the top-level blocks. The page's changes since
`base` and the file's changes since `base` are each derived by `changes.pair`; then, per block of `base`:

- edit against edit (two different results), and removal against edit either way: a clash, which could lose text.
  The result is `Clash(ids)`, and nothing is written;
- edit against move: both apply, the edit at the block's new place; move against move: the page's wins;
- an inserted or moved block goes after its preceding sibling on the page, taken in the current version; where
  that sibling is gone, after the nearest earlier one that survives; where none does, at the start.

The text is built from the current version's own bytes for every block the page did not change, and from the
page's bytes for what it did.
"""
from dataclasses import dataclass

from .changes import moved, pair
from .tree import Tree


@dataclass(frozen=True)
class Clash:
    ids: tuple          # ids in the current version of the blocks the two sides clash on


def rebase(base: Tree, current: Tree, page: Tree, held_ids=None):
    """The text to write, or a `Clash`."""
    pg = pair(base.blocks, page.blocks, held_ids)          # page block j -> base block
    fl = pair(base.blocks, current.blocks)                 # current block i -> base block
    page_of = {b: j for j, b in enumerate(pg) if b is not None}
    cur_of = {b: i for i, b in enumerate(fl) if b is not None}
    page_moved = {pg[j] for j in moved(pg)}
    clash = []
    for b, blk in enumerate(base.blocks):
        j, i = page_of.get(b), cur_of.get(b)
        page_edit = j is not None and page.blocks[j].key != blk.key
        file_edit = i is not None and current.blocks[i].key != blk.key
        page_gone, file_gone = j is None, i is None
        if page_edit and file_edit and page.blocks[j].key != current.blocks[i].key:
            clash.append(i)
        elif (page_gone and file_edit) or (file_gone and page_edit):
            clash.append(i if i is not None else None)
    if clash:
        return Clash(tuple(current.blocks[i].id for i in clash if i is not None))

    items = []                       # ("c", i) a block of the current version, ("p", j) one of the page's
    for i, c in enumerate(current.blocks):
        b = fl[i]
        if b is None:
            items.append(("c", i))
            continue
        j = page_of.get(b)
        if j is None:
            continue                 # the page removed it (the file did not edit it, or it is no clash)
        if b in page_moved:
            continue                 # re-placed below
        file_edit = c.key != base.blocks[b].key
        items.append(("c", i) if file_edit or page.blocks[j].key == base.blocks[b].key else ("p", j))
    where = {}
    for it in items:
        if it[0] == "p":
            where[it[1]] = it
        else:
            b = fl[it[1]]
            if b is not None and b in page_of:
                where[page_of[b]] = it
    for j, blk in enumerate(page.blocks):
        b = pg[j]
        if b is not None and b not in page_moved:
            continue
        if b is not None and cur_of.get(b) is not None:       # a block the page moved: its edit or the file's
            i = cur_of[b]
            file_edit = current.blocks[i].key != base.blocks[b].key
            item = ("c", i) if file_edit or page.blocks[j].key == base.blocks[b].key else ("p", j)
        elif b is not None:
            continue                                          # moved by the page, gone from the file: no clash, gone
        else:
            item = ("p", j)
        at = 0
        for k in range(j - 1, -1, -1):
            if k in where and where[k] in items:
                at = items.index(where[k]) + 1
                break
        if at == 0 and items and current.blocks and current.blocks[0].type == "frontmatter" \
                and items[0] == ("c", 0):
            at = 1
        items.insert(at, item)
        where[j] = item
    return _compose(items, current, page)


def _compose(items: list, current: Tree, page: Tree) -> str:
    parts = [current.lead]
    n = len(items)
    for k, (src, x) in enumerate(items):
        tree = current if src == "c" else page
        b = tree.blocks[x]
        content, gap = b.content, b.gap
        last_in_source = x == len(tree.blocks) - 1
        if k < n - 1:
            if not content.endswith("\n"):
                content += "\n"
            if not gap and items[k + 1] != (src, x + 1):
                gap = "\n"
        elif not last_in_source:
            gap = ""
        parts.append(content + gap)
    return "".join(parts)
