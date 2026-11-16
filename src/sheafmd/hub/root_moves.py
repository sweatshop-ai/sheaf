"""A root moves to another tiroir when its `.sheaf.toml` changes (SPEC 13). This file is the part that needs no channel:
the notice (which tiroir a clone's `.sheaf.toml` names), the check that nothing leaves while text is unpushed, and
`root_moves.json`, which keeps a move across a crash so that a missed pull loses nothing. It holds no page text."""
import json
import subprocess
import threading
from pathlib import Path
from typing import NamedTuple

from .. import config, diagnostics
from ..atomic import write_text_atomic
from . import proxy

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
    """`root_moves.json` in `base`: per repo `{to, id, sent: [paths forwarded], held: {path: reason}}`, written whole and
    atomically. A file that cannot be read is an empty one."""

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
            if isinstance(row, dict) and (row.get("to") == to or row.get("sent")):
                return row
            data[repo] = {"to": to, "id": id, "sent": [], "held": {}}
            self._write(data)
            return data[repo]

    def sent(self, repo: str, page: str):
        """`page` is confirmed by the receiver."""
        with self._lock:
            data = self._read()
            row = data.get(repo)
            if isinstance(row, dict) and page not in row["sent"]:
                row["sent"] = sorted({*row["sent"], page})
                row["held"].pop(page, None)
                self._write(data)

    def hold(self, repo: str, why: dict) -> bool:
        """What holds the pages now; True when it differs from what was held (a row is written only then)."""
        with self._lock:
            data = self._read()
            row = data.get(repo)
            if not isinstance(row, dict) or row["held"] == why:
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


def owner_email(member) -> str | None:
    """The e-mail the sender gives for a page's owner: the member's own, never the one made up for one with none."""
    return member.email or None


def match_owner(members, email, origins=()) -> tuple:
    """The member of this tiroir who owns a landed page, by e-mail ignoring case: `(id, None)`, or `(None, why)`: `refused`
    (no e-mail, or one made up for a member with none, on either side's origin in `origins`), `no_owner`, `ambiguous_owner`."""
    members = list(members)
    if not email:
        return None, "refused"
    want = email.strip().lower()
    if not want or any(want == proxy.default_email(m.id, o).lower() for m in members for o in origins):
        return None, "refused"
    found = [m.id for m in members if m.email and m.email.strip().lower() == want]
    if not found:
        return None, "no_owner"
    return (found[0], None) if len(found) == 1 else (None, "ambiguous_owner")


def tip_holds(clone: Path, branch: str, page: str, blob: str) -> bool:
    """The save branch's tip holds `page` with this blob: the page is that text on this side too."""
    return _git(clone, "rev-parse", f"origin/{branch}:{page}") == blob
