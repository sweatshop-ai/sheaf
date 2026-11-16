"""A root moves to another tiroir when its `.sheaf.toml` changes (SPEC 13). This file is the part that needs no channel:
the notice (which tiroir a clone's `.sheaf.toml` names), the check that nothing leaves while text is unpushed, and
`root_moves.json`, which keeps a move across a crash so that a missed pull loses nothing. It holds no page text."""
import json
import subprocess
import threading
from pathlib import Path

from .. import config
from ..atomic import write_text_atomic

FILE = "root_moves.json"


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
