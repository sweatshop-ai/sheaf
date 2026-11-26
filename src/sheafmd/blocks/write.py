"""The writer: the text of a save, with the original bytes of every block whose AST did not change.

`write_back(new, current, held_ids)` takes the tree of the Markdown a page sent and the tree of the file as it is
now, matches each block of the first to a block of the second (by the id the page held, then by equal AST) and
gives the text to write: a matched block is written as the file had it, bytes, spacing after it and all; a block
with no match is written as the page sent it. So pandoc's cosmetic rewrites (a fence of another length, a
re-padded table, the page's own blank-line spacing) change no byte of a block that is the same block, and a
text in which every block is matched in its place is the file's text itself.
"""
from .tree import Tree


def match(new: Tree, current: Tree, held_ids=None) -> list:
    """For each block of `new`, the index of the block of `current` it is, or None.

    By id first: a block the page held under an id of `current`, with an equal AST (a block that was edited has
    no equal AST, and no match here). Then by equal AST, each block taking the next unused equal block after
    the previous match, else the first unused equal block."""
    cur = current.blocks
    taken = set()
    got = [None] * len(new.blocks)
    by_id = {}
    for i, b in enumerate(cur):
        by_id.setdefault(b.id, i)
    for j, b in enumerate(new.blocks):
        h = held_ids[j] if held_ids is not None and j < len(held_ids) else None
        i = by_id.get(h) if h else None
        if i is not None and i not in taken and cur[i].key == b.key:
            got[j] = i
            taken.add(i)
    last = -1
    for j, b in enumerate(new.blocks):
        if got[j] is not None:
            last = got[j]
            continue
        free = [i for i, c in enumerate(cur) if i not in taken and c.key == b.key]
        if not free:
            continue
        i = next((i for i in free if i > last), free[0])
        got[j] = i
        taken.add(i)
        last = i
    return got


def write_back(new: Tree, current: Tree, held_ids=None) -> str:
    got = match(new, current, held_ids)
    if (len(got) == len(current.blocks) and got == list(range(len(got)))):
        return current.text                # every block is the file's own, in its place: nothing to write
    parts = [current.lead if any(i is not None for i in got) else new.lead]
    n = len(got)
    for j, (b, i) in enumerate(zip(new.blocks, got)):
        if i is None:
            content, gap = b.content, b.gap
            if j < n - 1 and not content.endswith("\n"):
                content += "\n"
        else:
            content, gap = current.blocks[i].content, current.blocks[i].gap
            # Blocks that touch in the file (a list that interrupts a paragraph) may touch where they did, or where
            # the page's own text has them touch (and the last block of a file has no gap at all): any other
            # neighbour is set apart by a blank line.
            if j < n - 1 and not gap and got[j + 1] != i + 1 and b.gap:
                content, gap = (content if content.endswith("\n") else content + "\n"), "\n"
        parts.append(content + gap)
    return "".join(parts)
