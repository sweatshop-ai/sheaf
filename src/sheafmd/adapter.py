"""The Source adapter interface (ADR 0004) and its first implementation, the Markdown-file adapter.

Every write to a rectoverso's file, from the page, the MCP door or the CLI, goes through
`MarkdownFileAdapter`; nothing else calls `source.update_file`, `update_beneath` or `create_file`.

The interface (version `INTERFACE_VERSION`):

    read()                                    -> (tree, base)
    write(tree, base, author, note)           -> outcome
    publish(note)                             optional, the file adapter has none
    interface                                 an integer

The base is the content hash of the text. Until the block model exists the tree is a thin wrapper
over the Markdown text. An outcome is one of the three shapes of the spec:

    {"outcome": "written",  "base": new base, "blocks": []}
    {"outcome": "conflict", "base": current base, "blocks": []}
    {"outcome": "refused",  "block": id, "reason": text}

`apply(change)` is the same write for a caller that derives the new text from the current one under
the file lock (a save that merges, a comment): `change(text, opened)` returns the new text, and an
error it raises reaches the caller unchanged.
"""
import functools
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from . import source as rds

INTERFACE_VERSION = 1
SUFFIX = ".md"


class Refused(Exception):
    """A write the adapter will not make (an outcome `refused`, for a caller that raises)."""

    def __init__(self, reason: str, block: str = ""):
        super().__init__(reason)
        self.reason, self.block = reason, block


class _Conflict(Exception):
    def __init__(self, base: str):
        super().__init__(base)
        self.base = base


class Tree(NamedTuple):
    """The document as the adapter hands it over: the Markdown text, until the block model (ticket 02)."""
    text: str


def written(base: str) -> dict:
    return {"outcome": "written", "base": base, "blocks": []}


def conflict(base: str) -> dict:
    return {"outcome": "conflict", "base": base, "blocks": []}


def refused(reason: str, block: str = "") -> dict:
    return {"outcome": "refused", "block": block, "reason": reason}


class MarkdownFileAdapter:
    interface = INTERFACE_VERSION

    def __init__(self, path=None, *, beneath: Callable[[], tuple] | None = None):
        """The file by `path` (a path, or a callable that finds it at each use), or, with `beneath`,
        a callable giving `(top, rel)`: the file is then opened once beneath its root, never through a link."""
        if (path is None) == (beneath is None):
            raise TypeError("a Markdown-file adapter takes a path or a beneath, one of them")
        self._path, self._beneath = path, beneath

    @staticmethod
    def accepts(name) -> bool:
        """Whether a document of this name is one this adapter keeps: a `.md` file."""
        return str(name).endswith(SUFFIX)

    def _file(self) -> Path:
        p = self._path() if callable(self._path) else self._path
        return Path(p)

    def read(self):
        if self._beneath is not None:
            from .beneath import open_beneath
            top, rel = self._beneath()
            with open_beneath(top, rel) as op:
                text = op.text()
        else:
            text = self._file().read_text(encoding="utf-8")
        return Tree(text), rds.md_hash(text)

    def write(self, tree, base, author: str = "", note: str = "", move=None) -> dict:
        name = self._beneath()[1] if self._beneath is not None else self._file().name
        if not self.accepts(name):
            return refused(f"{name} is not a .md file")
        out, _, _ = self.apply(lambda t, opened: tree.text, expected=base, move=move, author=author, note=note)
        return out

    def apply(self, change: Callable, *, expected: str | None = None, move=None, author: str = "", note: str = "",
              by=None):
        """`(outcome, old, new)`: `change(text, opened)` applied under the file lock. With `expected`, a text
        that is no longer the one that hash names is a conflict, and nothing is written. `by`: the low-level writer to use instead of
        `source.update_beneath` / `update_file` (a seam for a caller whose tests stand in for it)."""
        def judged(text, opened):
            if expected is not None and rds.md_hash(text) != expected:
                raise _Conflict(rds.md_hash(text))
            return change(text, opened)
        try:
            if self._beneath is not None:
                top, rel = self._beneath()
                old, new = (by or rds.update_beneath)(top, rel, judged, move=move)
            else:
                old, new = (by or rds.update_file)(self._file(), lambda t: judged(t, None), move=move)
        except _Conflict as c:
            return conflict(c.base), None, None
        return written(rds.md_hash(new)), old, new

    @staticmethod
    def creating(top, rel: str, text: str, judge=None, by=None):
        """The creation of a new page, checked and ready: a callable that writes it whole and never over anything
        (`source.create_file`) and gives `(st_dev, st_ino)` of the file made. Raises `Refused` for a name that is not
        `.md`, before anything is made. A partial, not a wrapper, so the writer is called from the caller's own frame."""
        if not MarkdownFileAdapter.accepts(rel):
            raise Refused(f"{rel} is not a .md file")
        return functools.partial(by or rds.create_file, top, rel, text, judge)
