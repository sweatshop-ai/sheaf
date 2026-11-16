"""A member's loose root: the folder where the pages they make through the door without a root are written. One per
member, named `loose-<short>`, made on the member's first `create`. It is kept against the member's id, never the name:
`loose.json` holds `{member id: folder}`, so a renamed member keeps their root, and a short name another member once
had never opens it. A page's `keep` mark is a line of `.sheaf/keep.json` in the root, never in the text."""
import dataclasses
import json
import os
import re
import threading
import time
from pathlib import Path

from .. import paths
from . import roots as roots_mod
from . import state

KEEP = Path(".sheaf") / "keep.json"
MONTH = "%Y-%m"


def _file() -> Path:
    return paths.state_dir() / "loose.json"


def _base() -> Path:
    return paths.state_dir() / "loose"


def month() -> str:
    return time.strftime(MONTH)


def _word(member) -> str:
    """The name the root takes: the member's short name, else their name, cleaned as a root's name is."""
    return roots_mod.clean_name(member.short or member.name).lower()


def folder_path(folder: str | None) -> str:
    """`folder` (or the month) as a path inside the root: relative, no empty, `.`, `..` or hidden part, no NUL, no
    backslash. ToolError's job is the caller's: this raises ValueError with the reason."""
    if folder is None:
        return month()
    if folder.startswith("/") or "\\" in folder or "\0" in folder:
        raise ValueError("a folder is a path inside the loose root, not an absolute one")
    parts = folder.rstrip("/").split("/")
    if any(p in ("", ".", "..") or p.startswith(".") for p in parts):
        raise ValueError("a folder has no empty, `.`, `..` or hidden part")
    return "/".join(parts)


def kept(root_path: Path, rel: str) -> bool:
    """Whether the page at `rel` in the root at `root_path` is marked never to be archived."""
    return rel in _marks(root_path)


def _marks(root_path: Path) -> list:
    try:
        data = json.loads((Path(root_path) / KEEP).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def keep(root_path: Path, rel: str) -> None:
    marks = _marks(root_path)
    if rel not in marks:
        (Path(root_path) / KEEP).parent.mkdir(mode=0o700, exist_ok=True)
        state.write_json(Path(root_path) / KEEP, sorted([*marks, rel]))


class Loose:
    """The registry of loose roots of a hub, over `loose.json`."""

    def __init__(self, hub):
        self.hub = hub
        self._lock = threading.RLock()

    def _read(self) -> dict:
        data = state.read_json(_file(), {})
        return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}

    def attach(self) -> None:
        """Add the loose root of each member that has one to their roots, so `Hub.owns` finds it: the member of
        the config knows nothing of it. Idempotent; called at start and after a root is made."""
        proxy = getattr(self.hub, "proxy", None)
        if proxy is None:
            return
        with self._lock:
            for mid, folder in self._read().items():
                m = proxy.members.get(mid)
                if m is not None and not self._holds(m, folder):
                    proxy.members[mid] = dataclasses.replace(m, roots=(*m.roots, folder))
                    self.hub.roots.for_document(Path(folder) / "x.md")

    @staticmethod
    def _holds(member, folder: str) -> bool:
        real = os.path.realpath(folder)
        return any(os.path.realpath(r) == real for r in member.roots)

    def root_for(self, member):
        """The loose root of `member`, made on the first call: their folder by id, else a new one named for their
        short name that no other member's loose folder, and no root of the hub, has."""
        with self._lock, state.file_locked("loose.lock"):
            held = self._read()
            folder = held.get(member.id)
            if folder is None:
                taken = set(held.values())
                base, n = f"loose-{_word(member)}", 1
                while True:
                    name = base if n == 1 else f"{base}-{n}"
                    path = _base() / name
                    if str(path) not in taken and not path.exists() and self.hub.roots.get(name) is None:
                        break
                    n += 1
                folder = str(path)
                path.mkdir(parents=True, mode=0o700)
                state.write_json(_file(), {**held, member.id: folder})
            Path(folder).mkdir(parents=True, exist_ok=True, mode=0o700)
            self.attach()
            return self.hub.roots.for_document(Path(folder) / "x.md")
