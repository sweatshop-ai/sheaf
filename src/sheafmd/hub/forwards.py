"""Forwards (SPEC 9.11, "Move and Forward"): where an address a page once had now leads. `forwards.json` holds
`{old address: {"to": new address, "by": who moved it, "at": when}}`. A Forward never expires; a link that names the old
address is not rewritten, this resolves it. There is one hop, never a chain: a page that moves again re-points every Forward
that led to its last address, and a page that moves back to an address it once left drops the Forward there."""
import time

from ..source import STAMP_FORMAT
from .state import _Store


class Forwards(_Store):
    name = "forwards.json"

    def follow(self, address: str) -> str | None:
        """The address `address` now leads to, None when it has no Forward."""
        with self._lock:
            e = self._data.get(address)
            to = e.get("to") if isinstance(e, dict) else None
            return to if isinstance(to, str) else None

    def entry(self, address: str) -> dict | None:
        with self._lock:
            e = self._data.get(address)
            return dict(e) if isinstance(e, dict) else None

    def add(self, old: str, new: str, by: str) -> None:
        """`old` now leads to `new`. Whatever led to `old` leads to `new`; whatever `new` led to is no Forward any more,
        the page being there again."""
        def change(data):
            at = time.strftime(STAMP_FORMAT)
            for k, e in data.items():
                if isinstance(e, dict) and e.get("to") == old:
                    e["to"] = new
            data.pop(new, None)
            data[old] = {"to": new, "by": by, "at": at}
            for k in [k for k, e in data.items() if isinstance(e, dict) and e.get("to") == k]:
                del data[k]
            return None, True
        self._change(change)

    def snapshot(self) -> dict:
        """Every Forward as it is now, to `restore` after a move that is taken back."""
        with self._lock:
            return {k: dict(e) for k, e in self._data.items() if isinstance(e, dict)}

    def restore(self, kept: dict) -> None:
        """The Forwards are `kept`, as `snapshot` gave them."""
        def change(data):
            data.clear()
            data.update({k: dict(e) for k, e in kept.items()})
            return None, True
        self._change(change)

    def drop_leading_to(self, address: str) -> None:
        """The page at `address` is gone (deleted): each Forward that led to it goes, so what takes the address next is never
        what the old address of that page leads to."""
        def change(data):
            gone = [k for k, e in data.items() if isinstance(e, dict) and e.get("to") == address]
            for k in gone:
                del data[k]
            return None, bool(gone)
        self._change(change)

    def forget_prefix(self, prefix: str) -> None:
        """A root was forgotten (`<root>/`): drop each Forward from an address under it and each that leads into it."""
        def change(data):
            gone = [k for k, e in data.items() if k.startswith(prefix) or
                    (isinstance(e, dict) and str(e.get("to", "")).startswith(prefix))]
            for k in gone:
                del data[k]
            return None, bool(gone)
        self._change(change)

    def leads_elsewhere(self, address: str, page: str | None = None) -> bool:
        """Whether `address` is the old address of a page other than the one that now stands at `page`: an address that
        once pointed at a page must not silently become another one."""
        to = self.follow(address)
        return to is not None and to != page
