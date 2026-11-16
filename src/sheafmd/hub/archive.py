"""Archive, Keep and the trash of a member's loose pages (SPEC 8.6). A page is archived when its mark is not older than
its last write: the mark is a line of the root's `.sheaf/archived.json`, so a write or a new comment (which moves the
file's mtime past the mark) brings the page back with nothing to clear, and an open, which writes nothing to the page,
does not. Nothing is in the text. `.sheaf/seen.json` holds when the hub first listed each page: `archive_after` counts
from the later of that and the mtime, so a page that arrives with an old mtime, or a hub's first boot, archives nothing
at once. Delete moves a page into `.sheaf/trash/<time>/<path>` for thirty days. Repo pages are never touched: they are
not in a loose root."""
import contextlib
import os
import shutil
import stat
from pathlib import Path

from .. import config
from . import loose, state
from . import roots as roots_mod

DAY = 86400
SWEEP_EVERY = 600           # seconds between two sweeps on the hub's tick
TRASH_DAYS = 30
ARCHIVED, SEEN = "archived.json", "seen.json"
TRASH = Path(".sheaf") / "trash"


def is_archived(archived: dict, rel: str, mtime: float) -> bool:
    """A page is archived when its mark is not older than its last write."""
    at = archived.get(rel)
    return at is not None and at >= mtime


def due(pages: list, archived: dict, seen: dict, kept, now: float, days: int) -> list:
    """The pages to archive now: `pages` is `[(rel, mtime, open comments)]`. Quiet for more than `days` days counted from
    the later of the last write and the first time the hub saw the page, not kept, no comment open, not archived yet."""
    out = []
    for rel, mtime, open_ in pages:
        if rel in kept or open_ or is_archived(archived, rel, mtime):
            continue
        if rel not in seen:
            continue                    # no first seen yet: it is written first, and counts from now
        if now - max(mtime, seen[rel]) > days * DAY:
            out.append(rel)
    return out


class Marks:
    """What a loose root holds about its pages, read together: a mark file that cannot be read refuses the lot."""

    def __init__(self, root_path: Path):
        self.archived = loose.times(root_path, ARCHIVED)
        self.seen = loose.times(root_path, SEEN)
        self.kept = set(loose.marks(root_path))


class Archive:
    def __init__(self, hub):
        self.hub = hub
        self._next = 0.0

    # ── the loose roots ──────────────────────────────────────────────────────
    def _loose_roots(self):
        """(member, root) of each member's loose root."""
        proxy = getattr(self.hub, "proxy", None)
        if proxy is None:
            return
        for mid, folder in self.hub.loose._read().items():
            member = proxy.members.get(mid)
            if member is None:
                continue
            root = self.hub.roots.for_document(Path(folder) / "x.md")
            if root.path == Path(os.path.realpath(folder)):
                yield member, root

    def _pages(self, member, root) -> list:
        found = self.hub.index.data(member=member)
        for r in found["roots"]:
            if r["name"] == root.name and "shared_from" not in r:
                return [(roots_mod.Address.parse(d["doc"]).rel, d["mtime"], d["open"]) for d in r["docs"]]
        return []

    def days(self, root) -> int:
        return config.load_root_config(root.path, lambda _m: None).archive_after

    # ── the sweep ────────────────────────────────────────────────────────────
    def tick(self, now: float) -> None:
        """The sweep on the hub's tick: at the first tick, then every ten minutes."""
        if now < self._next:
            return
        self._next = now + SWEEP_EVERY
        try:
            self.sweep()                        # a root whose marks cannot be read stops this, not the trash or the clones
        finally:
            self.purge()
            if getattr(self.hub, "repos", None) is not None:
                self.hub.repos.sleep_idle()     # a clone nobody used for thirty days sleeps (13)

    def sweep(self) -> None:
        """Mark the pages that are due, in each loose root. A root whose marks cannot be read is refused (`loose.Refused`)
        before anything of it is written, never read as none."""
        now = self.hub.clock()
        for member, root in self._loose_roots():
            pages = self._pages(member, root)
            marks = Marks(root.path)
            loose.stamp(root.path, SEEN, {rel: now for rel, _, _ in pages if rel not in marks.seen}, only_new=True)
            seen = {**{rel: now for rel, _, _ in pages}, **marks.seen}
            gone = due(pages, marks.archived, seen, marks.kept, now, self.days(root))
            mtimes = {rel: mtime for rel, mtime, _ in pages}
            loose.stamp(root.path, ARCHIVED, {rel: max(now, mtimes[rel]) for rel in gone})

    # ── what a row says ──────────────────────────────────────────────────────
    def facts(self, root) -> Marks | None:
        """The marks of a loose root for the Sheaf's rows; None when they cannot be read (no row is hidden then)."""
        try:
            return Marks(root.path)
        except loose.Refused:
            return None

    # ── the member's acts ────────────────────────────────────────────────────
    def archive_now(self, root, rel: str, mtime: float) -> None:
        loose.stamp(root.path, ARCHIVED, {rel: max(self.hub.clock(), mtime)})

    def restore(self, root, rel: str) -> None:
        """Back to the default view, and the page's own clock starts over."""
        now = self.hub.clock()
        loose.stamp(root.path, ARCHIVED, {rel: None})
        loose.stamp(root.path, SEEN, {rel: now})

    def keep(self, root, rel: str, on: bool, mtime: float) -> None:
        loose.keep(root.path, rel, on)
        if on:
            self.restore(root, rel)             # a kept page is in the default view

    # ── the trash ────────────────────────────────────────────────────────────
    @staticmethod
    def _plain_dir(path: Path, make: bool = False) -> None:
        """`path` is a folder that is not a link; made when `make`."""
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            if not make:
                raise
            os.mkdir(path, 0o700)
            return
        if not stat.S_ISDIR(st.st_mode):
            raise loose.Refused("the trash of the loose root is in a folder that is a link or a file: refused")

    def trash(self, root, rel: str) -> None:
        """Move the page into the root's trash under the time of the deletion; its marks go, its versions stay where they are."""
        src = Path(root.path) / rel
        if not stat.S_ISREG(os.lstat(src).st_mode):
            raise loose.Refused("the page is not a plain file: refused")
        at = int(self.hub.clock())
        with state.file_locked("loose-keep.lock"):
            for part in (Path(root.path) / ".sheaf", Path(root.path) / TRASH, Path(root.path) / TRASH / str(at)):
                self._plain_dir(part, make=True)
            dest = Path(root.path) / TRASH / str(at) / rel
            for part in reversed(dest.relative_to(Path(root.path) / TRASH / str(at)).parents):
                if str(part) != ".":
                    self._plain_dir(Path(root.path) / TRASH / str(at) / part, make=True)
            if os.path.lexists(dest):
                raise loose.Refused("a page of that name was deleted in the same second: try again")
            os.replace(src, dest)
        loose.stamp(root.path, ARCHIVED, {rel: None})
        loose.stamp(root.path, SEEN, {rel: None})
        loose.keep(root.path, rel, False)

    def trashed(self, root) -> list:
        """`[{id, rel, deleted_at, days_left}]` of the root's trash, newest first."""
        base = Path(root.path) / TRASH
        out, now = [], self.hub.clock()
        try:
            stamps = [e for e in os.scandir(base) if e.name.isdigit() and e.is_dir(follow_symlinks=False)]
        except OSError:
            return []
        for e in stamps:
            for dirpath, _, files in os.walk(e.path):
                for f in files:
                    rel = str((Path(dirpath) / f).relative_to(e.path))
                    out.append({"id": f"{e.name}/{rel}", "rel": rel, "deleted_at": int(e.name),
                                "days_left": max(0, TRASH_DAYS - int((now - int(e.name)) // DAY))})
        return sorted(out, key=lambda r: (-r["deleted_at"], r["rel"]))

    def restore_trash(self, root, ident: str) -> str:
        """Put a trashed page back at its old address; refused (`Taken`) when a page is there, never overwritten."""
        stamp, _, rel = ident.partition("/")
        if not stamp.isdigit() or not rel or any(p in ("", ".", "..") for p in rel.split("/")):
            raise KeyError(ident)
        src = Path(root.path) / TRASH / stamp / rel
        if not os.path.lexists(src) or not stat.S_ISREG(os.lstat(src).st_mode):
            raise KeyError(ident)
        dest = Path(root.path) / rel
        if os.path.lexists(dest):
            raise Taken(rel)
        for part in reversed(Path(rel).parents):
            if str(part) != ".":
                os.makedirs(Path(root.path) / part, mode=0o700, exist_ok=True)
        os.rename(src, dest)            # rename, not replace: a page that came in between is not overwritten
        loose.stamp(root.path, SEEN, {rel: self.hub.clock()})
        with contextlib.suppress(OSError):
            for p in Path(rel).parents:
                os.rmdir(Path(root.path) / TRASH / stamp / p)
            os.rmdir(Path(root.path) / TRASH / stamp)
        return rel

    def purge(self) -> None:
        """Empty what has been in a trash for more than thirty days."""
        now = self.hub.clock()
        for _, root in self._loose_roots():
            base = Path(root.path) / TRASH
            try:
                stamps = [e for e in os.scandir(base) if e.name.isdigit() and e.is_dir(follow_symlinks=False)]
            except OSError:
                continue
            for e in stamps:
                if now - int(e.name) > TRASH_DAYS * DAY:
                    shutil.rmtree(e.path, ignore_errors=True)


class Taken(Exception):
    """A page is at the old address already."""


def sweep(hub) -> None:
    hub.archive.sweep()
