"""A member's loose root: the folder where the pages they make through the door without a root are written. One per
member, named `loose-<short>`, made on the member's first `create`. It is kept against the member's id, never the name:
`loose.json` holds `{member id: folder}`, so a renamed member keeps their root, and a short name another member once
had never opens it. A page's `keep` mark is a line of `.sheaf/keep.json` in the root, never in the text."""
import contextlib
import dataclasses
import json
import os
import stat
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


class Refused(ValueError):
    """The loose root cannot be where it must be, or its keep marks cannot be read or written: the reason."""


def kept(root_path: Path, rel: str) -> bool:
    """Whether the page at `rel` in the root at `root_path` is marked never to be archived."""
    return rel in marks(root_path)


def marks(root_path: Path) -> list:
    """The pages the root marks never to be archived. No file is no marks; a file that is a link, is not a list of
    names, or cannot be read is refused (`Refused`), never read as no marks: the next `keep` would write it over."""
    folder, mark = Path(root_path) / KEEP.parent, Path(root_path) / KEEP
    try:
        st = os.lstat(folder)
    except FileNotFoundError:
        return []
    except OSError as e:
        raise Refused(f"the keep marks of the loose root cannot be read ({e.strerror})") from None
    if not stat.S_ISDIR(st.st_mode):
        raise Refused("the keep marks of the loose root are in a folder that is a link or a file: refused")
    try:
        fd = os.open(mark, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0))
    except FileNotFoundError:
        return []
    except OSError as e:
        raise Refused(f"the keep marks of the loose root cannot be read ({e.strerror})") from None
    try:
        with os.fdopen(fd, "rb") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                raise Refused("the keep marks of the loose root are not a file: refused")
            data = json.loads(f.read().decode("utf-8"))
    except (OSError, ValueError):
        raise Refused("the keep marks of the loose root cannot be read as a list of pages: refused, and left as they "
                      "are") from None
    if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
        raise Refused("the keep marks of the loose root are not a list of pages: refused, and left as they are")
    return data


def keep(root_path: Path, rel: str) -> None:
    """Mark the page at `rel` never to be archived: the file is written whole beside itself and put in place by a
    replace, in a folder reached without a link. Refused (`Refused`) when it cannot be."""
    mark = Path(root_path) / KEEP
    with state.file_locked("loose-keep.lock"):      # two creates at once each keep their own mark
        held = marks(root_path)
        if rel in held:
            return
        made = False
        try:
            try:
                os.mkdir(mark.parent, 0o700)
                made = True
            except FileExistsError:
                pass
            if not stat.S_ISDIR(os.lstat(mark.parent).st_mode):
                raise Refused("the keep marks of the loose root are in a folder that is a link or a file: refused")
            if os.path.lexists(mark) and not stat.S_ISREG(os.lstat(mark).st_mode):
                raise Refused("the keep marks of the loose root are a link or not a file: refused")
            state.write_text_private(mark, json.dumps(sorted([*held, rel]), indent=1, ensure_ascii=False) + "\n",
                                     inside=True)
        except (OSError, paths.PathError) as e:
            if made:
                with contextlib.suppress(OSError):
                    os.rmdir(mark.parent)           # the folder this call made goes with it, so the root stays empty
            raise Refused(f"the keep mark could not be written ({getattr(e, 'strerror', None) or e})") from None


def keep_moved(root_path: Path, old: str, new: str) -> None:
    """The keep mark of the page at `old` is the page at `new`'s, a page that moved: written in one replace, so a page
    is never there unmarked. Refused (`Refused`) when the marks cannot be written."""
    mark = Path(root_path) / KEEP
    with state.file_locked("loose-keep.lock"):
        held = marks(root_path)
        if old not in held:
            return
        state.write_text_private(mark, json.dumps(sorted({*(r for r in held if r != old), new}), indent=1,
                                                  ensure_ascii=False) + "\n", inside=True)


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
                if m is not None and not self._holds(m, folder) and self.hub.roots.stands_alone(Path(folder)):
                    proxy.members[mid] = dataclasses.replace(m, roots=(*m.roots, folder))
                    self.hub.roots.for_document(Path(folder) / "x.md")

    @staticmethod
    def _holds(member, folder: str) -> bool:
        real = os.path.realpath(folder)
        return any(os.path.realpath(r) == real for r in member.roots)

    def root_for(self, member):
        """(the loose root of `member`, whether this call made it). Made on the first call: their folder by id, else a
        new one named for their short name that no other member's loose folder, and no root of the hub, has. The
        folder must be the root of itself: one inside a git work tree or a registered root would not be, and the
        page would land in that other root, so it is refused (`Refused`) before anything is made."""
        with self._lock, state.file_locked("loose.lock"):
            held = self._read()
            folder = held.get(member.id)
            fresh = folder is None
            if fresh:
                taken = set(held.values())
                base, n = f"loose-{_word(member)}", 1
                while True:
                    name = base if n == 1 else f"{base}-{n}"
                    path = _base() / name
                    if str(path) not in taken and not path.exists() and self.hub.roots.get(name) is None:
                        break
                    n += 1
                folder = str(path)
            if not self.hub.roots.stands_alone(Path(folder)):
                raise Refused("a loose page cannot be made here: the folder for loose pages lies inside a git work "
                              "tree or a root of the hub, so the page would land in that root, not in the member's "
                              "loose root")
            if fresh:
                path.mkdir(parents=True, mode=0o700)
                state.write_json(_file(), {**held, member.id: folder})
            Path(folder).mkdir(parents=True, exist_ok=True, mode=0o700)
            self.attach()
            root = self.hub.roots.for_document(Path(folder) / "x.md")
            if root.path != Path(os.path.realpath(folder)):
                raise Refused("a loose page cannot be made here: the loose folder is not a root of its own")
            return root, fresh

    def owner_of(self, root) -> str | None:
        """The id of the member whose loose root `root` is, None for any other root."""
        real = os.path.realpath(root.path)
        return next((mid for mid, folder in self._read().items() if os.path.realpath(folder) == real), None)

    def known(self, member) -> Path | None:
        """The loose folder of `member`, when it has one."""
        folder = self._read().get(member.id)
        return Path(folder) if folder is not None else None

    def drop(self, member, root) -> None:
        """Take back a loose root a refused create had just made, if nothing has been put in it: its hub root, its entry
        in `loose.json`, its folder, and the root it added to the member. A root that holds anything stays."""
        with self._lock, state.file_locked("loose.lock"):
            folder = self._read().get(member.id)
            if folder is None or os.path.realpath(folder) != os.path.realpath(root.path) or os.listdir(folder):
                return
            self.hub.forget_root(root.name)
            os.rmdir(folder)
            state.write_json(_file(), {k: v for k, v in self._read().items() if k != member.id})
            proxy = getattr(self.hub, "proxy", None)
            m = proxy.members.get(member.id) if proxy is not None else None
            if m is not None:
                proxy.members[member.id] = dataclasses.replace(m, roots=tuple(
                    r for r in m.roots if os.path.realpath(r) != os.path.realpath(folder)))
