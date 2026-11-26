"""The Document service (block editor v1, ADR 0004 and 0007): the one place a whole page save becomes a write.

    read()                                                          -> (tree, base)
    save(markdown, held_ids, base, session, author, note, move)     -> outcome

One service keeps one document, through its Source adapter (`adapter.py`). `read` hands over the block tree
(`blocks.read_tree`) and the base. `save` takes the whole Markdown a page sends, the id each of its blocks held
when the page loaded (a list parallel to the blocks of `markdown`, None for a block the page made; or None
for no ids), the base the page held, and a `session`, the page's own identity.

A save writes the text of `blocks.write_back`: every block that is the same block as in the file keeps the
file's bytes, so a cosmetic rewrite of pandoc's (a fence length, a table's padding) changes none. The
outcome is one of the three of the spec, `written` with the new base and the ids of the new tree, `conflict` with
the current base, or `refused` with its reason.

A page never conflicts with itself. The service records, for each text it wrote, the session that wrote it:
a base older than the file's is the page's own when every write since it is a record of that session, and the
save then stands; a write from anywhere else (another session, the MCP door, the CLI) breaks the chain and the
stale base is a `conflict`. Matching of moved or reworded blocks, rebase and the clash rules are the next ticket's.

A text pandoc cannot read is written as the page sent it: the service never refuses what the page saved before.
"""
import threading
from collections import OrderedDict

from . import adapter as rda
from . import source as rds
from .blocks import Unreadable, read_tree, write_back

RECORDS = 512       # the writes whose session is remembered: the page's chain is a few saves long
TREES = 4           # the trees kept, by text hash: a save reads the file's and the page's, the next reads the one just written


class DocumentService:
    def __init__(self, adapter):
        self.adapter = adapter
        self._lock = threading.Lock()
        self._next = OrderedDict()       # hash of a text -> (hash of the text written over it, session)
        self._trees = OrderedDict()      # hash -> tree

    # ── read ────────────────────────────────────────────────────────────────
    def tree(self, text: str):
        """The block tree of `text` (kept by its hash), or raises `Unreadable`."""
        h = rds.md_hash(text)
        with self._lock:
            t = self._trees.get(h)
            if t is not None:
                self._trees.move_to_end(h)
                return t
        t = read_tree(text)
        with self._lock:
            self._trees[h] = t
            while len(self._trees) > TREES:
                self._trees.popitem(last=False)
        return t

    def read(self):
        tree, base = self.adapter.read()
        return self.tree(tree.text), base

    # ── save ────────────────────────────────────────────────────────────────
    def save(self, markdown: str, held_ids, base: str, session: str, author: str = "", note: str = "", move=None) -> dict:
        return self.write(lambda text, opened: self.settle(text, markdown, held_ids, base, session),
                          session, author=author, note=note, move=move)

    def write(self, change, session: str = "", *, author: str = "", note: str = "", move=None, **hooks) -> dict:
        """The write `change(text, opened)` makes through the adapter, under its lock, recorded as this session's.
        A `Conflict` the change raises is the outcome `conflict`. Returns the outcome; `hooks` are the adapter's own."""
        here, name = self.adapter.pinned()
        if not self.adapter.accepts(name):
            return rda.refused(f"{name} is not a .md file")
        outcome, old, new = here.apply(change, author=author, note=note, move=move, **hooks)
        if outcome["outcome"] == "written":
            self._record(old, new, session)
            outcome["blocks"] = self._ids(new)
        return outcome

    def settle(self, current: str, markdown: str, held_ids, base: str, session: str) -> str:
        """The text to write for a page's `markdown` over the `current` text of the file. Raises `Conflict`
        for a base that is stale by anyone else's writing."""
        here = rds.md_hash(current)
        if base and base != here and not self._own(base, here, session):
            raise rda.Conflict(here)
        if markdown == current:
            return current
        try:
            return write_back(self.tree(markdown), self.tree(current), held_ids)
        except Unreadable:
            return markdown

    # ── the page session record ─────────────────────────────────────────────
    def _record(self, old: str, new: str, session: str) -> None:
        a, b = rds.md_hash(old), rds.md_hash(new)
        if a == b:
            return
        with self._lock:
            self._next[a] = (b, session)
            self._next.move_to_end(a)
            while len(self._next) > RECORDS:
                self._next.popitem(last=False)

    def _own(self, base: str, here: str, session: str) -> bool:
        """Whether every write from `base` to `here` is a record of `session`."""
        if not session:
            return False
        with self._lock:
            h = base
            for _ in range(len(self._next) + 1):
                step = self._next.get(h)
                if step is None or step[1] != session:
                    return False
                h = step[0]
                if h == here:
                    return True
        return False

    def _ids(self, text: str) -> list:
        try:
            return self.tree(text).ids
        except Unreadable:
            return []
