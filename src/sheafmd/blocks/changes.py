"""Block changes (ADR 0007): the match of a save's blocks to the base's, and the changes derived from it.

`pair(base_seq, new_seq, held_ids)` pairs sibling blocks: by the id the page held, then by equal AST (a block
that is equal and in order first), then, between the blocks matched that way, by word similarity at 0.5 (the
rule of the existing merge, `edit._align`), and last any leftover pair of alike words wherever it stands (a
block moved and edited in one save). `derive(base, new, held_ids)` runs it down the tree and turns the match into
changes: `insert`, `move` (also across containers), `remove` and `edit`; a change of type is an edit.
"""
import bisect
import json

from .tree import Block, Tree

INSERT, MOVE, REMOVE, EDIT = "insert", "move", "remove", "edit"


_BLOCKS = frozenset(("Para", "Plain", "Header", "LineBlock", "DefinitionList", "Table"))


def _texts(x, out: list) -> None:
    if isinstance(x, dict):
        t, c = x.get("t"), x.get("c")
        if t == "Str":
            out.append(c)
        elif t in ("Code", "CodeBlock", "Math", "RawInline", "RawBlock"):
            out.append(c[-1])
        elif t in ("Space", "SoftBreak", "LineBreak"):
            out.append(" ")
        else:
            _texts(c, out)
            if t in _BLOCKS:
                out.append(" ")            # the words of two paragraphs or items are not one word
    elif isinstance(x, list):
        for y in x:
            _texts(y, out)


def words(b: Block) -> str:
    """The words of a block, read from its AST (its bytes where the AST is no JSON, as a definition or front
    matter): the text similarity is judged on."""
    try:
        doc = json.loads(b.ast)
    except ValueError:
        return b.content or b.ast
    out = []
    _texts(doc, out)
    return " ".join("".join(out).split()) or b.content or b.ast


def _lis(seq: list) -> set:
    """The positions of one longest increasing subsequence of `seq`."""
    tails, idx, prev = [], [], [-1] * len(seq)
    for k, v in enumerate(seq):
        pos = bisect.bisect_left(tails, v)
        if pos == len(tails):
            tails.append(v)
            idx.append(k)
        else:
            tails[pos], idx[pos] = v, k
        prev[k] = idx[pos - 1] if pos else -1
    keep, k = set(), idx[-1] if idx else -1
    while k != -1:
        keep.add(k)
        k = prev[k]
    return keep


def pair(base: tuple, new: tuple, held_ids=None, elsewhere=frozenset()) -> list:
    """For each block of `new`, the index of the block of `base` it is, or None. `elsewhere`: the ids of the blocks
    of the document that are not among `base` (another container's): a block of `new` that holds one of them
    is that block moved in, and is settled across containers, never by its words or its likeness here."""
    from ..edit import ALIGN_LIMIT, ALIGN_MIN, _WORD_RE, _align, _similarity

    got = [None] * len(new)
    taken = set()
    fresh = set()                                   # blocks that are new whatever their words: a copied id, a moved-in id
    by_id = {}
    for i, b in enumerate(base):
        by_id.setdefault(b.id, i)
    for j in range(len(new)):                       # by the id the page held; a second block with it is new
        h = held_ids[j] if held_ids is not None and j < len(held_ids) else None
        i = by_id.get(h) if h else None
        if i is not None and i not in taken:
            got[j] = i
            taken.add(i)
        elif h and (i is not None or h in elsewhere):
            fresh.add(j)
    last = -1
    for j, b in enumerate(new):                     # by equal AST, in order first
        if got[j] is not None:
            last = got[j]
            continue
        if j in fresh:
            continue
        free = [i for i, c in enumerate(base) if i not in taken and c.key == b.key]
        if free:
            i = next((i for i in free if i > last), free[0])
            got[j] = i
            taken.add(i)
            last = i
    # By words, between the blocks matched so far that keep their order.
    pairs = [(j, i) for j, i in enumerate(got) if i is not None]
    keep = _lis([i for _, i in pairs])
    anchors = [(-1, -1)] + [p for k, p in enumerate(pairs) if k in keep] + [(len(new), len(base))]
    for (j0, i0), (j1, i1) in zip(anchors, anchors[1:]):
        js = [j for j in range(j0 + 1, j1) if got[j] is None and j not in fresh]
        is_ = [i for i in range(i0 + 1, i1) if i not in taken]
        if not js or not is_:
            continue
        if len(js) == 1 or len(is_) == 1:           # a split or a join: the identity stays with the first alike block
            wj, wi = [words(new[j]) for j in js], [words(base[i]) for i in is_]
            sims = [(_similarity(wi[a], _WORD_RE.findall(wi[a]), wj[p], _WORD_RE.findall(wj[p])), a, p)
                    for a in range(len(is_)) for p in range(len(js))]
            first = next(((a, p) for s_, a, p in sorted(sims, key=lambda t: (t[2], t[1])) if s_ >= ALIGN_MIN), None)
            if first is not None:
                a, p = first
                got[js[p]] = is_[a]
                taken.add(is_[a])
            continue
        for a, p in enumerate(_align([words(base[i]) for i in is_], [words(new[j]) for j in js])):
            if p is not None:
                got[js[p]] = is_[a]
                taken.add(is_[a])
    # Any leftover of alike words elsewhere: the block was moved and edited.
    left_j = [j for j in range(len(new)) if got[j] is None and j not in fresh]
    left_i = [i for i in range(len(base)) if i not in taken]
    cand = []
    if len(left_j) * len(left_i) > ALIGN_LIMIT:     # the limit of every alignment holds here too
        left_j = []
    for j in left_j:
        wj = words(new[j])
        for i in left_i:
            wi = words(base[i])
            s = _similarity(wi, _WORD_RE.findall(wi), wj, _WORD_RE.findall(wj))
            if s >= ALIGN_MIN:
                cand.append((-s, j, i))
    for _, j, i in sorted(cand):
        if got[j] is None and i not in taken:
            got[j] = i
            taken.add(i)
    return got


def moved(got: list) -> set:
    """The positions of `got` (a `pair` result) whose block is out of the order the others keep."""
    pairs = [(j, i) for j, i in enumerate(got) if i is not None]
    keep = _lis([i for _, i in pairs])
    return {j for k, (j, _) in enumerate(pairs) if k not in keep}


def _all_ids(blocks, out: set) -> set:
    for b in blocks:
        out.add(b.id)
        _all_ids(b.children, out)
    return out


def derive(base: Tree, new: Tree, held_ids=None) -> list:
    """The changes that make `base` into `new`, as dicts `{kind, id, new_id, type, parent}`: `id` is the block's
    id in `base` (None for an insertion), `new_id` its id in `new` (None for a removal), `parent` the id in `new`
    of the container a block was inserted or moved into (None at the top)."""
    out = []
    left_b, left_n = [], []          # unmatched blocks, for the pass across containers: (block, parent id, inside
                                     # an unmatched container) and, for the new side, a held id too
    twin = {None: None}              # id of a base block -> id of the block it is in `new`
    anywhere = _all_ids(base.blocks, set())

    def leftovers(blocks, parent, side, held=None, inside=False):
        for k, b in enumerate(blocks):
            h = held[k] if held is not None and k < len(held) else None
            side.append((b, parent, inside) if side is left_b else (b, parent, inside, h))
            leftovers(b.children, b.id, side, None, True)

    def level(bs, ns, pb, pn, held):
        got = pair(bs, ns, held, anywhere)
        off = moved(got)
        used = {i for i in got if i is not None}
        for i, b in enumerate(bs):
            if i not in used:
                leftovers((b,), pb, left_b)
        for j, n in enumerate(ns):
            i = got[j]
            if i is None:
                leftovers((n,), pn, left_n, [held[j]] if held is not None and j < len(held) else None)
                continue
            b = bs[i]
            twin[b.id] = n.id
            if b.key != n.key:
                out.append(_row(EDIT, b, n, None))
            if j in off:
                out.append(_row(MOVE, b, n, pn))
            level(b.children, n.children, b.id, n.id, None)

    level(base.blocks, new.blocks, None, None, held_ids)
    rb, rn = tuple(x[0] for x in left_b), tuple(x[0] for x in left_n)
    got = pair(rb, rn, [x[3] for x in left_n], anywhere)
    used = {i for i in got if i is not None}
    for j, i in enumerate(got):
        if i is not None:
            twin[left_b[i][0].id] = left_n[j][0].id
    for j, (n, pn, inside, _) in enumerate(left_n):
        i = got[j]
        if i is None:
            if not inside:                  # the children of an inserted container come with it
                out.append(_row(INSERT, None, n, pn))
            continue
        b, pb = left_b[i][0], left_b[i][1]
        if b.key != n.key:
            out.append(_row(EDIT, b, n, None))
        if twin.get(pb, False) != pn:       # a block that stays in the container it was in, when that moves, is no move
            out.append(_row(MOVE, b, n, pn))
    for i, (b, _, inside) in enumerate(left_b):
        if i not in used and not inside:    # the children of a removed container go with it
            out.append(_row(REMOVE, b, None, None))
    return out


def _row(kind: str, b, n, parent) -> dict:
    return {"kind": kind, "id": b.id if b else None, "new_id": n.id if n else None,
            "type": (n or b).type, "parent": parent}
