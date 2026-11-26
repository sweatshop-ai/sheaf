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

A save is refused whole, and nothing is written, when it makes a Rich block that breaks its declaration (an
attribute or value it does not declare, a forbidden nesting: `blocks.declarations`), or when it changes a locked
block that the page held under its id. A block already invalid in the file stays as it is: a save that leaves it alone
is not refused for it. An unknown type is a Stub, kept byte for byte, never refused.

A text pandoc cannot read is written as the page sent it: the service never refuses what the page saved before.
"""
import threading
from collections import OrderedDict

from . import adapter as rda
from . import source as rds
from .blocks import LOCKED, Clash, Unreadable, derive, read_tree, rebase, write_back
from .blocks import declarations as decl
from .blocks.write import match

RECORDS = 512       # the writes whose session is remembered: the page's chain is a few saves long
TEXTS = 64          # the texts kept by hash, for a stale base to be rebased from
TREES = 4           # the trees kept, by text hash: a save reads the file's and the page's, the next reads the one just written


class DocumentService:
    def __init__(self, adapter):
        self.adapter = adapter
        self._lock = threading.Lock()
        self._next = OrderedDict()       # hash of a text -> (hash of the text written over it, session)
        self._trees = OrderedDict()      # hash -> tree
        self._texts = OrderedDict()      # hash -> text of a base the service has read or written

    # ── read ────────────────────────────────────────────────────────────────
    def tree(self, text: str):
        """The block tree of `text` (kept by its hash), or raises `Unreadable`."""
        h = rds.md_hash(text)
        self._remember(text, h)
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
        """The tree and the base. Raises `blocks.Unreadable` for a file pandoc cannot read: it has no tree, where
        `save` writes the page's text as sent."""
        tree, base = self.adapter.read()
        return self.tree(tree.text), base

    # ── save ────────────────────────────────────────────────────────────────
    def save(self, markdown: str, held_ids, base: str, session: str, author: str = "", note: str = "", move=None,
             base_text: str | None = None) -> dict:
        """`base_text`: the text `base` names, for a base the service has not read or written itself."""
        info = {}
        out = self.write(lambda text, opened: self.settle(text, markdown, held_ids, base, session, base_text, info),
                         session, author=author, note=note, move=move)
        if out["outcome"] == "written":
            out["changes"] = info.get("changes", [])
        return out

    def changes_since(self, base: str) -> list:
        """The block changes that make the base `base` (its hash) into the document as it is now. Raises `KeyError`
        for a base the service never held."""
        old = self._text_of(base)
        if old is None:
            raise KeyError(base)
        tree, _ = self.read()
        return derive(self.tree(old), tree)

    def write(self, change, session: str = "", *, author: str = "", note: str = "", move=None, **hooks) -> dict:
        """The write `change(text, opened)` makes through the adapter, under its lock, recorded as this session's.
        A `Conflict` the change raises is the outcome `conflict`. Returns the outcome; `hooks` are the adapter's own."""
        here, name = self.adapter.pinned()
        if not self.adapter.accepts(name):
            return rda.refused(f"{name} is not a .md file")
        try:
            outcome, old, new = here.apply(change, author=author, note=note, move=move, **hooks)
        except rda.Refused as r:
            return rda.refused(r.reason, r.block)
        except rda.POLICY as e:
            return rda.policy_refusal(name, e)
        if outcome["outcome"] == "written":
            self._record(old, new, session)
            outcome["blocks"] = self._ids(new)
        return outcome

    def settle(self, current: str, markdown: str, held_ids, base: str, session: str, base_text: str | None = None,
               info: dict | None = None) -> str:
        """The text to write for a page's `markdown` over the `current` text of the file. Raises `Conflict`
        for a base that is stale by anyone else's writing and either unknown to the service or unreadable, or whose
        changes clash with the page's (ADR 0007), the latter with the rows of the clashing blocks. `info`, if given, receives the page's block changes as `changes`."""
        here = rds.md_hash(current)
        if base_text is not None:
            self._remember(base_text, base)
        try:
            page = self.tree(markdown)
            old = self._text_of(base) if base and base != here else current
            if info is not None and old is not None:
                info["changes"] = derive(self.tree(old), page, held_ids)
            # the page's edit is checked against the text it was made from: the base when the service holds it
            self._refuse(page, self.tree(old if old is not None else current), held_ids)
            if base and base != here and not self._own(base, here, session):
                if old is None:
                    raise rda.Conflict(here)
                got = rebase(self.tree(old), self.tree(current), page, held_ids)
                if isinstance(got, Clash):
                    raise rda.Conflict(here, got.rows)
                return got
            if markdown == current:
                return current
            return write_back(page, self.tree(current), held_ids)
        except Unreadable:
            if base and base != here and not self._own(base, here, session):
                raise rda.Conflict(here) from None
            return markdown

    @staticmethod
    def _refuse(new, cur, held_ids) -> None:
        """Raises `Refused` for a save that makes an invalid Rich block or changes a locked block the page held."""
        got = match(new, cur, held_ids)
        for b, i in zip(new.blocks, got):
            if i is None and b.type == "stub" and b.attrs.get("type") in decl.DECLARED:
                raise rda.Refused(b.attrs["reason"], b.id)
            if i is None and b.type != "stub":
                why = decl.button_fault(b.ast)         # a block that is new or edited may hold valid buttons only
                if why:
                    raise rda.Refused(why, b.id)
        if held_ids is not None:
            by_id = {b.id: b for b in cur.blocks}
            for j, b in enumerate(new.blocks):
                h = held_ids[j] if j < len(held_ids) else None
                old = by_id.get(h) if h else None
                if old is not None and old.caps == LOCKED and old.key != b.key:
                    raise rda.Refused(f"the {old.type} block is locked and cannot be changed", old.id)

    def _remember(self, text: str, h: str | None = None) -> None:
        h = h or rds.md_hash(text)
        with self._lock:
            self._texts[h] = text
            self._texts.move_to_end(h)
            while len(self._texts) > TEXTS:
                self._texts.popitem(last=False)

    def _text_of(self, h: str):
        with self._lock:
            return self._texts.get(h)

    # ── the page session record ─────────────────────────────────────────────
    def _record(self, old: str, new: str, session: str) -> None:
        a, b = rds.md_hash(old), rds.md_hash(new)
        self._remember(old, a)
        self._remember(new, b)
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
