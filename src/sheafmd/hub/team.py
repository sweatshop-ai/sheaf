"""Team comments (SPEC 9.10b): the agency's own verso on a client's page. A comment lives here, in one private JSON file of
the agency hub's state folder, keyed by the page's address; it is never written into the client's file and never sent to
the client tiroir, so the client side holds no trace of it. There is no markdown in it and no anchor: a comment holds
the quote it was made on. It reuses `comments.Comment` for the shape the page renders, so both versos draw alike.
The ids are `tN`, so the side of a comment is told from its id alone and never collides with the client's `cN`."""
import re
import threading
from pathlib import Path

from .. import comments
from . import state
from .live import NotAuthor

ID_RE = re.compile(r"t[0-9]+")


class NoComment(KeyError):
    """No comment of that id on the page."""


def _shape(c: dict) -> dict:
    return comments.Comment(id=c["id"], by=c["by"], at=c["at"], status=c["status"], quote=c["quote"], body=c["body"],
                            replies=[comments.Reply(by=r["by"], at=r["at"], text=r["text"]) for r in c["replies"]]).as_dict() \
        | {"page_hash": c.get("page_hash", "")}


class TeamComments:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data = state.read_json(self.path, {})
        self._rids = {}              # request id -> (what was sent, the id made): an add sent again is answered, not stored twice

    # ── reads ────────────────────────────────────────────────────────────────
    def list(self, address: str) -> list:
        with self._lock:
            return [_shape(c) for c in self._data.get(address, [])]

    # ── writes: each reads the file again under the lock, changes one comment, writes it whole ──
    def _change(self, address: str, fn):
        with self._lock, state.file_locked("team-comments.lock"):
            self._data = state.read_json(self.path, {})
            out = fn(self._data.setdefault(address, []))
            if not self._data[address]:
                del self._data[address]
            state.write_json(self.path, self._data)
            return out

    @staticmethod
    def _find(items: list, cid: str) -> dict:
        for c in items:
            if c["id"] == cid:
                return c
        raise NoComment(cid)

    def add(self, address: str, by: str, quote: str, body: str, page_hash: str, at: str, rid: str | None = None) -> dict:
        sent = (address, by, quote, body)
        def go(items):
            if rid is not None and self._rids.get(rid, (None,))[0] == sent:
                again = [c for c in items if c["id"] == self._rids[rid][1]]
                if again:
                    return _shape(again[0])
            n = max([int(c["id"][1:]) for c in items] + [0]) + 1
            c = {"id": f"t{n}", "by": by, "at": at, "status": "open", "quote": quote, "body": body,
                 "replies": [], "page_hash": page_hash}
            items.append(c)
            if rid is not None:
                self._rids[rid] = (sent, c["id"])
                while len(self._rids) > 256:
                    del self._rids[next(iter(self._rids))]
            return _shape(c)
        return self._change(address, go)

    def reply(self, address: str, cid: str, by: str, text: str, at: str) -> dict:
        def go(items):
            c = self._find(items, cid)
            c["replies"].append({"by": by, "at": at, "text": text})
            return _shape(c)
        return self._change(address, go)

    def status(self, address: str, cid: str, status: str) -> dict:
        if status not in comments.STATUSES:
            raise ValueError(f"status must be one of {', '.join(sorted(comments.STATUSES))}")

        def go(items):
            c = self._find(items, cid)
            c["status"] = status
            return _shape(c)
        return self._change(address, go)

    def edit(self, address: str, cid: str, by: str, body: str) -> dict:
        def go(items):
            c = self._find(items, cid)
            if c["by"] != by:
                raise NotAuthor("only your own comments can be edited")
            c["body"] = body
            return _shape(c)
        return self._change(address, go)

    def delete(self, address: str, cid: str, by: str) -> None:
        def go(items):
            c = self._find(items, cid)
            if c["by"] != by:
                raise NotAuthor("only your own comments can be deleted, and only while no one else has replied")
            if any(r["by"] != by for r in c["replies"]):
                raise NotAuthor("only your own comments can be deleted, and only while no one else has replied")
            items.remove(c)
        self._change(address, go)
