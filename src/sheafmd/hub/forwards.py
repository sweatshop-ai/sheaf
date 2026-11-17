"""Forwards (SPEC 9.11, "Move and Forward"): where an address a page once had now leads. `forwards.json` holds
`{old address: {"to": new address, "by": who moved it, "at": when}}`; a page that went to another tiroir (ticket 20) is
`{"origin": that tiroir, "to": its address there, "by", "at", "hash": the text that landed}`: `to` is then an address of the
other tiroir, never of this one, so everything here that looks at a `to` as a local address skips an entry with an `origin`. A Forward never expires; a link that names the old
address is not rewritten, this resolves it. There is one hop, never a chain: a page that moves again re-points every Forward
that led to its last address, and a page that moves back to an address it once left drops the Forward there."""
import time

from ..source import STAMP_FORMAT
from .state import _Store


class Forwards(_Store):
    name = "forwards.json"

    def follow(self, address: str) -> str | None:
        """The address `address` now leads to, None when it has no Forward. For a Forward to another tiroir (`remote`) it is the
        address there."""
        with self._lock:
            e = self._data.get(address)
            to = e.get("to") if isinstance(e, dict) else None
            return to if isinstance(to, str) else None

    def local(self, address: str) -> str | None:
        """The address on this tiroir that `address` now leads to: None when it has no Forward, or its Forward leads to another tiroir."""
        with self._lock:
            e = self._data.get(address)
            to = e.get("to") if isinstance(e, dict) and "origin" not in e else None
            return to if isinstance(to, str) else None

    def remote(self, address: str) -> dict | None:
        """The Forward at `address` when it leads to another tiroir, else None."""
        e = self.entry(address)
        return e if e is not None and isinstance(e.get("origin"), str) else None

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
                if isinstance(e, dict) and "origin" not in e and e.get("to") == old:
                    e["to"] = new
            data.pop(new, None)
            data[old] = {"to": new, "by": by, "at": at}
            for k in [k for k, e in data.items() if isinstance(e, dict) and "origin" not in e and e.get("to") == k]:
                del data[k]
            return None, True
        self._change(change)

    def add_remote(self, old: str, origin: str, to: str, by: str, hash_: str, was: str = "") -> None:
        """`old` now leads to `to` on the tiroir at `origin`, where the page landed with text `hash_`; `was` is the hash of the text
        that left, which a laptop compares with the one it last read. Whatever led to `old` here leads there too (one hop, never a
        chain)."""
        def change(data):
            at = time.strftime(STAMP_FORMAT)
            for k, e in data.items():
                if isinstance(e, dict) and "origin" not in e and e.get("to") == old:
                    data[k] = {"origin": origin, "to": to, "by": e.get("by", by), "at": e.get("at", at), "hash": hash_, "was": was}
            data[old] = {"origin": origin, "to": to, "by": by, "at": at, "hash": hash_, "was": was}
            return None, True
        self._change(change)

    def drop(self, address: str) -> None:
        """The Forward at `address` is no more: the page came back to it."""
        def change(data):
            return None, data.pop(address, None) is not None
        self._change(change)

    def lift_remote(self, address: str) -> dict:
        """The page that left from `address` is back: its Forward goes, and with it every other Forward the move made for the same
        page (the addresses it had before, re-pointed by `add_remote`: same tiroir, same address there). What was lifted, by address."""
        def change(data):
            far = data.get(address)
            if not (isinstance(far, dict) and isinstance(far.get("origin"), str)):
                return {}, False
            gone = {k: dict(e) for k, e in data.items() if k == address or (isinstance(e, dict) and e.get("origin") == far["origin"]
                                                                          and e.get("to") == far.get("to"))}
            for k in gone:
                del data[k]
            return gone, True
        return self._change(change)

    def put_back(self, lifted: dict) -> None:
        """The Forwards `lift_remote` took away, as they were: a landing that took them away did not land."""
        def change(data):
            data.update({k: dict(e) for k, e in lifted.items()})
            return None, bool(lifted)
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
            gone = [k for k, e in data.items() if isinstance(e, dict) and "origin" not in e and e.get("to") == address]
            for k in gone:
                del data[k]
            return None, bool(gone)
        self._change(change)

    def forget_prefix(self, prefix: str) -> None:
        """A root was forgotten (`<root>/`): drop each Forward from an address under it and each that leads into it."""
        def change(data):
            gone = [k for k, e in data.items() if k.startswith(prefix) or
                    (isinstance(e, dict) and "origin" not in e and str(e.get("to", "")).startswith(prefix))]
            for k in gone:
                del data[k]
            return None, bool(gone)
        self._change(change)

    def leads_elsewhere(self, address: str, page: str | None = None) -> bool:
        """Whether `address` is the old address of a page other than the one that now stands at `page`: an address that
        once pointed at a page must not silently become another one."""
        to = self.follow(address)
        return to is not None and to != page
