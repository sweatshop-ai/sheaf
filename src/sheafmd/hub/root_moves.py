"""A root moves to another tiroir when its `.sheaf.toml` changes (SPEC 13). This file is the part that needs no channel:
the notice (which tiroir a clone's `.sheaf.toml` names), the check that nothing leaves while text is unpushed, and
`root_moves.json`, which keeps a move across a crash so that a missed pull loses nothing. It holds no page text."""
import json
import subprocess
import threading
from pathlib import Path
from typing import NamedTuple

from .. import config, connect, diagnostics
from ..atomic import write_text_atomic

FILE = "root_moves.json"
RETRY_EVERY = 600           # seconds between two tries of a move from the hub's poll; a pull always tries


def origin(named: str) -> str:
    """An origin as the hub spells its own: lower case, no trailing slash."""
    return named.strip().lower().rstrip("/")


def target(clone: Path, own: str | None) -> str | None:
    """The origin the clone's `.sheaf.toml` sends the root to, when it is another one than `own`; None when it names none,
    names this hub's own, or this hub has no origin (a loopback hub has none and never starts a move)."""
    if not own:
        return None
    named = config.load_root_config(clone, lambda *_: None).tiroir
    if not named:
        return None
    named = origin(named)
    return named if named and named != origin(own) else None


def _git(clone: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(clone), *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def held(clone: Path, branch: str, pages) -> dict:
    """The pages that may not leave yet, `{path: reason}`: all of them `unpushed` while the clone has commits that
    `origin/<branch>` lacks (comments are only in git once pushed), else each page whose file is not what the tip holds
    (`differs`)."""
    ahead = _git(clone, "rev-list", f"origin/{branch}..HEAD")
    if ahead is None or ahead:
        return {p: "unpushed" for p in pages}
    out = {}
    for page in pages:
        tip = _git(clone, "rev-parse", f"origin/{branch}:{page}")
        here = _git(clone, "hash-object", "--", page)
        if tip is None or here is None or tip != here:
            out[page] = "differs"
    return out


class Moves:
    """`root_moves.json` in `base`: per repo `{to, id, sent: [paths the receiver confirmed], hashes: {path: the receiver's
    hash}, forwarded: [paths that have their Forward], held: {path: reason}}`, written whole and atomically. A file that cannot be read is an empty one."""

    def __init__(self, base: Path):
        self.path = Path(base) / FILE
        self._lock = threading.Lock()

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(self.path, json.dumps(data, indent=1, sort_keys=True) + "\n")

    def get(self, repo: str) -> dict | None:
        row = self._read().get(repo)
        return row if isinstance(row, dict) else None

    def start(self, repo: str, to: str, id: str) -> dict:
        """A move of `repo` to `to`. The same target keeps its id and what it did; another target replaces a move that has
        confirmed no page yet, and is ignored after (the move runs to the end; a change back is a new move)."""
        with self._lock:
            data = self._read()
            row = data.get(repo)
            if isinstance(row, dict):
                lost = [p for p in row.get("sent", []) if not row.get("hashes", {}).get(p) and p not in row.get("forwarded", [])]
                if lost:        # confirmed without a hash (a row from before the hash was kept): it goes again
                    row["sent"] = [p for p in row["sent"] if p not in lost]
                    self._write(data)
            if isinstance(row, dict) and (row.get("to") == to or row.get("sent")):
                return row
            data[repo] = {"to": to, "id": id, "sent": [], "hashes": {}, "forwarded": [], "held": {}}
            self._write(data)
            return data[repo]

    def sent(self, repo: str, page: str, hash: str):
        """`page` is confirmed by the receiver, which holds it with `hash`; its Forward is still to be written."""
        with self._lock:
            data = self._read()
            row = data.get(repo)
            if isinstance(row, dict) and page not in row.get("sent", []):
                row["sent"] = sorted({*row.get("sent", []), page})
                row["hashes"] = {**row.get("hashes", {}), page: hash}
                row["held"] = {k: v for k, v in row.get("held", {}).items() if k != page}
                self._write(data)

    def forwarded(self, repo: str, page: str):
        """`page` has its Forward: a crash between the confirm and the Forward leaves it out of this, and it is tried again."""
        with self._lock:
            data = self._read()
            row = data.get(repo)
            if isinstance(row, dict) and page in row["sent"] and page not in row.get("forwarded", []):
                row["forwarded"] = sorted({*row.get("forwarded", []), page})
                self._write(data)

    def pending_forward(self, repo: str) -> dict:
        """The pages the receiver confirmed that have no Forward yet, `{path: the receiver's hash}`."""
        row = self.get(repo)
        if row is None:
            return {}
        return {p: row.get("hashes", {}).get(p, "") for p in row.get("sent", []) if p not in row.get("forwarded", [])}

    def cancel(self, repo: str) -> bool:
        """A move that has confirmed no page is dropped (its `.sheaf.toml` was put back before the first confirm); False when
        there is none, or when a page is confirmed (the move runs to the end)."""
        with self._lock:
            data = self._read()
            row = data.get(repo)
            if not isinstance(row, dict) or row.get("sent"):
                return False
            del data[repo]
            self._write(data)
            return True

    def done(self, repo: str) -> bool:
        """A move whose confirmed pages all have their Forward is finished and dropped, so a later move to the same tiroir
        starts afresh; False when there is none or a page still waits for its Forward."""
        with self._lock:
            data = self._read()
            row = data.get(repo)
            if not isinstance(row, dict) or not row.get("sent") or set(row["sent"]) - set(row.get("forwarded", [])):
                return False
            del data[repo]
            self._write(data)
            return True

    def hold(self, repo: str, why: dict) -> bool:
        """What holds the pages now; True when it differs from what was held (a row is written only then)."""
        with self._lock:
            data = self._read()
            row = data.get(repo)
            if not isinstance(row, dict) or row.get("held", {}) == why:
                return False
            row["held"] = dict(why)
            self._write(data)
            return True


class Clock:
    """When each move was last tried: due at every pull, and from the poll at most every `RETRY_EVERY` seconds."""

    def __init__(self):
        self._at: dict[str, float] = {}

    def due(self, repo: str, now: float, pulled: bool = False) -> bool:
        last = self._at.get(repo)
        return pulled or last is None or now - last >= RETRY_EVERY

    def tried(self, repo: str, now: float):
        self._at[repo] = now


class Diag:
    """One diagnostics row per state change of a move (`root-move-started`, `-held`, `-done`, `-unpaired`): the repo, the
    tiroir it goes to, page paths with a reason or a count. Never page text, never a token."""

    def __init__(self):
        self._unpaired: set = set()

    @staticmethod
    def _row(kind: str, **detail):
        diagnostics.record("hub", f"root-move-{kind}", None, **detail)

    def started(self, repo: str, to: str):
        self._row("started", repo=repo, to=to)

    def held(self, repo: str, to: str, pages: dict):
        self._row("held", repo=repo, to=to, pages=dict(pages))

    def done(self, repo: str, to: str, count: int):
        self._row("done", repo=repo, to=to, count=count)

    def unpaired(self, repo: str, to: str):
        """A `.sheaf.toml` names a tiroir this hub holds no peer credential for: written once per repo and origin."""
        if (repo, to) not in self._unpaired:
            self._unpaired.add((repo, to))
            self._row("unpaired", repo=repo, to=to)

    def paired(self, repo: str, to: str):
        """The target is paired now: a later loss of the pairing is a state change again, and writes its row again."""
        self._unpaired.discard((repo, to))


class Inventory(NamedTuple):
    send: dict          # path -> owner: the pages that go and are forwarded
    ownerless: set      # pages with hub state and no owner: they open to nobody, so they have no Forward and are not sent


def inventory(owner_of, record, versions, logged) -> Inventory:
    """The pages of a clone a move carries: each with a record, versions or Write log lines. A page with no owner is
    kept out (it opens to nobody, so a Forward for it would be an oracle); git carries it."""
    send, ownerless = {}, set()
    for path in sorted({*record, *versions, *logged}):
        owner = owner_of(path)
        if owner:
            send[path] = owner
        else:
            ownerless.add(path)
    return Inventory(send, ownerless)


def tip_holds(clone: Path, branch: str, page: str, blob: str) -> bool:
    """The save branch's tip holds `page` with this blob: the page is that text on this side too."""
    return _git(clone, "rev-parse", f"origin/{branch}:{page}") == blob


def paired(to: str, store=None) -> bool:
    """This hub holds a peer token for the tiroir at `to` (`sheaf peer use`). A `.sheaf.toml` naming any other starts nothing:
    pairing is by hand, so a push alone never copies a root's versions and logs to a host of the pusher's choosing."""
    try:
        return bool(connect.peer_token_for(to, store))
    except connect.ConnectError:
        return False
