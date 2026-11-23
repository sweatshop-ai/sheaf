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

from .. import config, paths
from . import roots as roots_mod
from . import state

KEEP = Path(".sheaf") / "keep.json"
ARCHIVED, SEEN = "archived.json", "seen.json"      # the times of the archive (archive.py)
TIMES = (ARCHIVED, SEEN)
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


def _load(root_path: Path, name: str, what: str):
    """The JSON of the mark file `.sheaf/<name>` of the root, or None when there is none. A folder or file that is a link or
    not a plain one, or a file that cannot be read as JSON, is refused (`Refused`), never read as no marks: the next write
    would put it over."""
    folder, mark = Path(root_path) / ".sheaf", Path(root_path) / ".sheaf" / name
    try:
        st = os.lstat(folder)
    except FileNotFoundError:
        return None
    except OSError as e:
        raise Refused(f"the {what} of the loose root cannot be read ({e.strerror})") from None
    if not stat.S_ISDIR(st.st_mode):
        raise Refused(f"the {what} of the loose root are in a folder that is a link or a file: refused")
    try:
        fd = os.open(mark, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0))
    except FileNotFoundError:
        return None
    except OSError as e:
        raise Refused(f"the {what} of the loose root cannot be read ({e.strerror})") from None
    try:
        with os.fdopen(fd, "rb") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                raise Refused(f"the {what} of the loose root are not a file: refused")
            return json.loads(f.read().decode("utf-8"))
    except (OSError, ValueError):
        raise Refused(f"the {what} of the loose root cannot be read: refused, and left as they are") from None


def marks(root_path: Path) -> list:
    """The pages the root marks never to be archived. No file is no marks; a file that is not a list of names is refused
    (`Refused`)."""
    data = _load(root_path, KEEP.name, "keep marks")
    if data is None:
        return []
    if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
        raise Refused("the keep marks of the loose root are not a list of pages: refused, and left as they are")
    return data


def times(root_path: Path, name: str) -> dict:
    """`{page: time}` of the mark file `.sheaf/<name>` (archived, seen): no file is none; a file that is not that is refused."""
    data = _load(root_path, name, f"{name[:-5]} marks")
    if data is None:
        return {}
    if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool)
                                             for k, v in data.items()):
        raise Refused(f"the {name[:-5]} marks of the loose root are not a table of times: refused, and left as they are")
    return data


def _put(root_path: Path, name: str, data, what: str) -> None:
    """Write the mark file whole beside itself and put it in place by a replace, in a folder reached without a link.
    Refused (`Refused`) when it cannot be. The caller holds the lock."""
    mark = Path(root_path) / ".sheaf" / name
    made = False
    try:
        try:
            os.mkdir(mark.parent, 0o700)
            made = True
        except FileExistsError:
            pass
        if not stat.S_ISDIR(os.lstat(mark.parent).st_mode):
            raise Refused(f"the {what} of the loose root are in a folder that is a link or a file: refused")
        if os.path.lexists(mark) and not stat.S_ISREG(os.lstat(mark).st_mode):
            raise Refused(f"the {what} of the loose root are a link or not a file: refused")
        state.write_text_private(mark, json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n", inside=True)
    except (OSError, paths.PathError) as e:
        if made:
            with contextlib.suppress(OSError):
                os.rmdir(mark.parent)           # the folder this call made goes with it, so the root stays empty
        raise Refused(f"the {what.removesuffix('s')} could not be written ({getattr(e, 'strerror', None) or e})") from None


def keep(root_path: Path, rel: str, on: bool = True) -> None:
    """Mark the page at `rel` never to be archived (`on`), or take the mark off. Written whole by a replace; refused
    (`Refused`) when it cannot be."""
    with state.file_locked("loose-keep.lock"):      # two creates at once each keep their own mark
        keep_held(root_path, rel, on)


def keep_held(root_path: Path, rel: str, on: bool = True) -> None:
    """`keep` for a caller that holds `loose-keep.lock` already (the flock is not re-entrant)."""
    held = marks(root_path)
    if (rel in held) == on:
        return
    _put(root_path, KEEP.name, sorted([*held, rel] if on else [h for h in held if h != rel]), "keep marks")


def stamp(root_path: Path, name: str, changes: dict, only_new: bool = False) -> None:
    """Set (or, for a None, take off) the times of pages in the mark file `.sheaf/<name>`; with `only_new` a page that has one
    keeps it. Nothing is written when nothing changes."""
    with state.file_locked("loose-keep.lock"):
        stamp_held(root_path, name, changes, only_new)


def stamp_held(root_path: Path, name: str, changes: dict, only_new: bool = False) -> None:
    """`stamp` for a caller that holds `loose-keep.lock` already (the flock is not re-entrant): it reads the marks and
    writes them in the one hold, as the sweep does."""
    held = times(root_path, name)
    out = dict(held)
    for rel, at in changes.items():
        if at is None:
            out.pop(rel, None)
        elif not (only_new and rel in out):
            out[rel] = at
    if out != held:
        _put(root_path, name, out, f"{name[:-5]} marks")


def marks_moved(root_path: Path, old: str, new: str) -> None:
    """What the root holds about the page at `old` (its keep mark, and its archived and seen times) is the page at `new`'s,
    a page that moved: a Move is no activity for the archive, so the seen time stays, an archived page stays archived and
    a page moved back is not archived by a stale mark. All three are read under one hold before any is written (a file
    that cannot be read refuses the lot, and nothing is changed), and each file is written in one replace, so a page is
    never there unmarked. A mark at `new` (keep, archived or seen) that the page at `old` has no counterpart of goes. Refused (`Refused`) when a
    mark cannot be read or written."""
    with state.file_locked("loose-keep.lock"):
        held = marks(root_path)
        tables = {name: times(root_path, name) for name in TIMES}
        if old in held or new in held:
            kept = {*(r for r in held if r not in (old, new)), *([new] if old in held else [])}
            state.write_text_private(Path(root_path) / KEEP, json.dumps(sorted(kept), indent=1, ensure_ascii=False) + "\n",
                                     inside=True)
        for name, table in tables.items():
            out = {k: v for k, v in table.items() if k not in (old, new)}
            if old in table:
                out[new] = table[old]
            if out != table:
                _put(root_path, name, out, f"{name[:-5]} marks")


def marks_gone(root_path: Path, rel: str) -> None:
    """The page at `rel` left the root (it went to another tiroir): its keep mark and its archived and seen times go with it, so
    a page that comes to the name later is not born kept or archived."""
    with state.file_locked("loose-keep.lock"):
        held = marks(root_path)
        tables = {name: times(root_path, name) for name in TIMES}
        if rel in held:
            state.write_text_private(Path(root_path) / KEEP, json.dumps(sorted(r for r in held if r != rel), indent=1,
                                                                        ensure_ascii=False) + "\n", inside=True)
        for name, table in tables.items():
            if rel in table:
                _put(root_path, name, {k: v for k, v in table.items() if k != rel}, f"{name[:-5]} marks")


class Loose:
    """The registry of loose roots of a hub, over `loose.json`."""

    def __init__(self, hub):
        self.hub = hub
        self._lock = threading.RLock()
        self._listing = threading.local()       # this thread's `remembered` read of the registry: None outside one

    def _read(self) -> dict:
        data = state.read_json(_file(), {})
        return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}

    @contextlib.contextmanager
    def remembered(self):
        """Within it, this thread reads `loose.json` once for the questions of `owner_of` and `known` (SPEC 8.6): a listing asks
        them for every page, and the registry does not change inside one listing. The answer is dropped when it ends, so the
        next listing reads the file again; a nested use shares the outer one's. The writers read it fresh, always."""
        if getattr(self._listing, "held", None) is not None:
            yield
            return
        self._listing.held = self._read()
        try:
            yield
        finally:
            self._listing.held = None

    def _registry(self) -> dict:
        held = getattr(self._listing, "held", None)
        return held if held is not None else self._read()

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
        """The id of the member whose loose root `root` is, None for any other root. Within a listing each folder is resolved once."""
        real = config.realpath(root.path)
        return next((mid for mid, folder in self._registry().items() if config.realpath(folder) == real), None)

    def known(self, member) -> Path | None:
        """The loose folder of `member`, when it has one."""
        folder = self._registry().get(member.id)
        return Path(folder) if folder is not None else None

    def drop(self, member, root) -> None:
        """Take back a loose root a refused create had just made, if nothing has been put in it: its hub root, its entry
        in `loose.json`, its folder, and the root it added to the member. A root that holds anything stays. The moves'
        lock first: the forget takes it, and a create in a loose root holds it before it asks this registry."""
        from . import moves
        with moves.exclusive(), self._lock, state.file_locked("loose.lock"):
            folder = self._read().get(member.id)
            if folder is None or os.path.realpath(folder) != os.path.realpath(root.path):
                return
            try:
                if os.listdir(folder):
                    return
                os.rmdir(folder)            # first: a folder that cannot go leaves the root and its entry as they were
            except OSError:
                return
            self.hub.forget_root(root.name)
            state.write_json(_file(), {k: v for k, v in self._read().items() if k != member.id})
            proxy = getattr(self.hub, "proxy", None)
            m = proxy.members.get(member.id) if proxy is not None else None
            if m is not None:
                proxy.members[member.id] = dataclasses.replace(m, roots=tuple(
                    r for r in m.roots if os.path.realpath(r) != os.path.realpath(folder)))
