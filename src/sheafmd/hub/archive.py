"""Archive, Keep and the trash of a member's loose pages (SPEC 8.6). A page is archived when its mark is not older than
its last write: the mark is a line of the root's `.sheaf/archived.json`, so a write or a new comment (which moves the
file's mtime past the mark) brings the page back with nothing to clear, and an open, which writes nothing to the page,
does not. Nothing is in the text. `.sheaf/seen.json` holds when the hub first listed each page: `archive_after` counts
from the later of that and the mtime, so a page that arrives with an old mtime, or a hub's first boot, archives nothing
at once. Delete moves a page into `.sheaf/trash/<time>/<path>` for thirty days. Repo pages are never touched: they are
not in a loose root."""
import contextlib
import errno
import os
import shutil
import stat
import threading
from pathlib import Path

from .. import config
from ..source import _folder_of, file_lock
from . import loose, moves, state
from . import roots as roots_mod

DAY = 86400
SWEEP_EVERY = 600           # seconds between two sweeps on the hub's tick
TRASH_DAYS = 30
ARCHIVED, SEEN = loose.ARCHIVED, loose.SEEN
TRASH = Path(".sheaf") / "trash"
# what os.link answers where a file system allows no hard link, or a policy (fs.protected_hardlinks) refuses this one
NO_HARD_LINKS = frozenset({errno.EPERM, errno.EOPNOTSUPP, errno.ENOTSUP, errno.ENOSYS})


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
        self._worker: threading.Thread | None = None    # the sweep, the purge and the clones' sleep: one at a time, off the tick
        self._refused: set = set()                      # roots whose refusal is recorded already, until they are read again
        self._unpaged: dict = {}                        # per root the last sweep read, the marked addresses it found with no page (183 BY)

    @staticmethod
    def _holds_a_page(root, rel: str) -> bool:
        """Whether `rel` may still hold a page: False only when nothing is there, or a folder is. A look that fails another
        way (a folder unreadable for a moment, a stale network handle) is not taken for an empty address."""
        try:
            return not stat.S_ISDIR(os.stat(Path(root.path) / rel).st_mode)
        except (FileNotFoundError, NotADirectoryError):
            return False
        except OSError:
            return True

    def own_root(self, folder):
        """The root of a member's loose `folder` when that folder is the root itself, else None: a folder inside another root
        or a git work tree is that root's, and its trash and marks are not read, nor a page put back into it."""
        root = self.hub.roots.for_document(Path(folder) / "x.md")
        return root if root.path == Path(os.path.realpath(folder)) else None

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
            if (root := self.own_root(folder)) is not None:
                yield member, root

    def _pages(self, member, root) -> list:
        found = self.hub.index.data(member=member)
        pages = []
        for r in found["roots"]:
            if r["name"] == root.name and "shared_from" not in r:
                pages = [(roots_mod.Address.parse(d["doc"]).rel, d["mtime"], d["open"]) for d in r["docs"]]
        if found["more"].get(root.name):                # the listing stops at its cap: the sweep reads the rest from the root itself
            have = {rel for rel, _, _ in pages}
            for f in roots_mod.list_documents(root, cap=roots_mod.COUNT_LIMIT).docs:
                if f.rel not in have:
                    address = str(roots_mod.Address(root.name, f.rel))
                    if (s := self.hub.index.summary(address, root.path / f.rel, f.stat, member)) is not None:
                        pages.append((f.rel, f.stat.st_mtime, s.open))
        return pages

    def days(self, root) -> int:
        return config.load_root_config(root.path, lambda _m: None).archive_after

    # ── the sweep ────────────────────────────────────────────────────────────
    def tick(self, now: float) -> None:
        """The sweep on the hub's tick: at the first tick, then every ten minutes. It runs in a thread of its own, one at a
        time: a listing of every loose root and the clones' git calls are not the tick's to wait for."""
        if now < self._next or (self._worker is not None and self._worker.is_alive()):
            return
        self._next = now + SWEEP_EVERY
        self._worker = threading.Thread(target=self._run, name="archive-sweep", daemon=True)
        self._worker.start()

    def _run(self) -> None:
        try:
            self.sweep()
        except Exception:
            self.hub.record_exception("archive-failed")
        finally:
            try:
                self.purge()
                if getattr(self.hub, "repos", None) is not None:
                    self.hub.repos.sleep_idle()     # a clone nobody used for thirty days sleeps (13)
                    from . import root_sender
                    root_sender.sweep(self.hub)     # a root whose `.sheaf.toml` names another tiroir moves there
            except Exception:
                self.hub.record_exception("archive-failed")

    def settle(self, seconds: float = 30.0) -> None:
        """Wait for the sweep the tick started, if one runs."""
        if (t := self._worker) is not None:
            t.join(seconds)

    def sweep(self) -> None:
        """Mark the pages that are due, in each loose root. A root whose marks cannot be read is refused whole
        (`loose.Refused`) before anything of it is written, never read as none, and the other roots are swept all the same."""
        now = self.hub.clock()
        # 183 BY: a root this sweep does not read (refused, skipped, forgotten) starts its run of misses over
        missed_before, self._unpaged = self._unpaged, {}
        for member, root in self._loose_roots():
            try:
                self._sweep_root(member, root, now, missed_before.get(root.path, set()))
            except loose.Refused:
                if root.path not in self._refused:      # told once, until the root is read again
                    self._refused.add(root.path)
                    self.hub.record_exception("archive-root-refused", root=root.name)
            else:
                self._refused.discard(root.path)

    def _sweep_root(self, member, root, now: float, missed_before: frozenset | set = frozenset()) -> None:
        pages = self._pages(member, root)            # the slow part, outside the lock
        # The moves' lock first (lockorder.py), then the marks' hold: a Move renames a page and carries its marks in one
        # hold of the moves' lock, so the sweep never finds a moved page of this hub process gone from its old address with
        # its marks still there. The lock is the process's own: a Move in another hub process is covered only by the run
        # of two sweeps.
        with moves.exclusive(), state.file_locked("loose-keep.lock"):   # the marks are read and the archive written in one hold: a Keep or a Restore comes before or after
            marks = Marks(root.path)
            # 183 BY: the marks of an address with no page go (emptied from outside the hub, a delete that found it gone or
            # put a folder back there), or a page made there later is born kept. Two looks: not in the listing, and no file
            # under the lock, so a page made (and kept) since the listing keeps its marks. And at two sweeps running: a
            # page a sync tool takes away and puts back between two of them keeps its marks. A mark file that cannot be
            # written leaves those marks for the next sweep and stops nothing of this one.
            listed = {rel for rel, _, _ in pages}
            unpaged = {rel for rel in {*marks.archived, *marks.seen, *marks.kept}
                       if rel not in listed and not self._holds_a_page(root, rel)}
            self._unpaged[root.path] = unpaged
            if unpaged & missed_before:
                self._unmark_quietly(root, unpaged & missed_before)
                marks = Marks(root.path)
            loose.stamp_held(root.path, SEEN, {rel: now for rel, _, _ in pages if rel not in marks.seen}, only_new=True)
            seen = {**{rel: now for rel, _, _ in pages}, **marks.seen}
            gone = due(pages, marks.archived, seen, marks.kept, now, self.days(root))
            mtimes = {rel: mtime for rel, mtime, _ in pages}
            loose.stamp_held(root.path, ARCHIVED, {rel: max(now, mtimes[rel]) for rel in gone})

    # ── what a row says ──────────────────────────────────────────────────────
    def facts(self, root) -> Marks | None:
        """The marks of a loose root for the Sheaf's rows; None when they cannot be read (no row is hidden then)."""
        try:
            return Marks(root.path)
        except loose.Refused:
            return None

    # ── the member's acts ────────────────────────────────────────────────────
    def archive_now(self, root, rel: str, mtime: float) -> None:
        """Archive at once; refused (`loose.Refused`) for a kept page, which is never archived: Keep comes off first."""
        with state.file_locked("loose-keep.lock"):
            if rel in loose.marks(root.path):
                raise loose.Refused("the page is kept and a kept page is never archived: take Keep off first")
            loose.stamp_held(root.path, ARCHIVED, {rel: max(self.hub.clock(), mtime)})

    def restore(self, root, rel: str) -> None:
        """Back to the default view, and the page's own clock starts over: both marks in one hold, so a sweep comes before
        or after and never between them."""
        with state.file_locked("loose-keep.lock"):
            self._restore_held(root, rel)

    def _restore_held(self, root, rel: str) -> None:
        now = self.hub.clock()
        loose.stamp_held(root.path, ARCHIVED, {rel: None})
        loose.stamp_held(root.path, SEEN, {rel: now})

    def keep(self, root, rel: str, on: bool, mtime: float) -> None:
        with state.file_locked("loose-keep.lock"):
            loose.keep_held(root.path, rel, on)
            if on:
                self._restore_held(root, rel)   # a kept page is in the default view

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
        try:
            if not stat.S_ISREG(os.lstat(src).st_mode):
                raise loose.Refused("the page is not a plain file: refused")
        except FileNotFoundError:
            raise Gone(rel) from None
        base = os.path.realpath(root.path)
        real = os.path.realpath(src)
        if os.path.commonpath([real, base]) != base:      # lstat looks at the last part of the path only
            raise loose.Refused("the page is in a folder that leads out of the root: refused")
        if real != os.path.join(base, rel):
            # 183 BJ: a folder link that stays in the root gives a page a second address, which the Sheaf never lists (its
            # walk follows no link). The page is deleted at its own address, where its marks, versions and Forwards are.
            own = Path(os.path.relpath(real, base)).as_posix()
            raise loose.Refused(f"this address reaches the page through a folder link: delete it at its own address, {own}")
        at = int(self.hub.clock())
        # The page's file lock first, as a writer takes it (the order of the hub's locks: a file lock, then the state stores'):
        # a door write of a page the hub holds no entry for comes before the move or finds the page gone.
        with file_lock(src), state.file_locked("loose-keep.lock"):
            for part in (Path(root.path) / ".sheaf", Path(root.path) / TRASH, Path(root.path) / TRASH / str(at)):
                self._plain_dir(part, make=True)
            dest = Path(root.path) / TRASH / str(at) / rel
            for part in reversed(dest.relative_to(Path(root.path) / TRASH / str(at)).parents):
                if str(part) != ".":
                    self._plain_dir(Path(root.path) / TRASH / str(at) / part, make=True)
            # The move is made from folder descriptors, each folder opened from the one above it without following a link:
            # a folder on the way swapped for a link since the look by path above is refused, never followed out of the root.
            try:
                sfd, sname = _folder_of(root.path, rel)
            except FileNotFoundError:
                raise Gone(rel) from None       # 183 BK: a folder on the way went away since the look: the page is not there
            except OSError:
                raise loose.Refused("the page is in a folder that is a link or went away: refused") from None
            try:
                try:
                    if not stat.S_ISREG(os.stat(sname, dir_fd=sfd, follow_symlinks=False).st_mode):
                        raise loose.Refused("the page is not a plain file: refused")
                except FileNotFoundError:
                    raise Gone(rel) from None   # 183 BK: deleted between the first look and the lock
                try:
                    dfd, dname = _folder_of(root.path, str(dest.relative_to(root.path)))
                except OSError:
                    raise loose.Refused("the trash of the loose root is in a folder that is a link or a file: refused") from None
                try:
                    # A rename, one step (183 BL, BM): it needs no hard link (exFAT, SMB, FUSE, fs.protected_hardlinks), and
                    # neither a failure nor a crash can leave the page in two places. A rename replaces a name that is taken,
                    # so the name in the trash is looked at first: every move into a trash holds `loose-keep.lock`, a flock
                    # each process of the hub takes, so nothing of the hub's comes in between the look and the rename.
                    try:
                        os.stat(dname, dir_fd=dfd, follow_symlinks=False)
                    except FileNotFoundError:
                        pass
                    else:
                        raise loose.Refused("a page of that name was deleted in the same second: try again")
                    try:
                        os.rename(sname, dname, src_dir_fd=sfd, dst_dir_fd=dfd)
                    except FileNotFoundError:
                        if os.path.lexists(src):        # the trash folder went, not the page
                            raise loose.Refused("the trash of the loose root went away during the delete: try again") from None
                        raise Gone(rel) from None
                    except OSError as e:
                        raise loose.Refused(f"the page could not be moved to the trash ({e.strerror})") from None
                    # A rename takes whatever is at the name, where the link it replaces refused a folder: a folder another
                    # process put there since the look goes back, and the delete is refused.
                    try:
                        moved = os.stat(dname, dir_fd=dfd, follow_symlinks=False).st_mode
                    except OSError as e:
                        # 183 BW: refused, but the address is empty all the same: its marks go, or a page made there later
                        # would be born archived or kept.
                        self._unmark_quietly(root, [rel])
                        raise loose.Refused(f"the page was moved to the trash, then something else took it from there "
                                            f"({e.strerror})") from None
                    if not stat.S_ISREG(moved):
                        try:
                            os.rename(dname, sname, src_dir_fd=dfd, dst_dir_fd=sfd)
                        except OSError as e:
                            self._unmark_quietly(root, [rel])     # 183 BW: the address is empty here too
                            raise loose.Refused(f"what was at the page's address changed during the delete and is in the "
                                                f"trash now ({e.strerror}): move {TRASH / str(at) / rel} back by hand") from None
                        raise loose.Refused("what is at the page's address changed during the delete: refused, nothing was moved")
                finally:
                    os.close(dfd)
            finally:
                os.close(sfd)
            self._unmark(root, [rel])   # the marks go in the hold of the move: no sweep between

    @staticmethod
    def _unmark(root, rels) -> None:
        """Take the archived, seen and keep marks of each address of `rels`, each mark tried even when one before it cannot
        be written; then the first refusal is raised (`Refused`). The caller holds `loose-keep.lock`."""
        failed = None
        clears = [lambda: loose.stamp_held(root.path, ARCHIVED, {rel: None for rel in rels}),
                  lambda: loose.stamp_held(root.path, SEEN, {rel: None for rel in rels})]
        clears += [lambda rel=rel: loose.keep_held(root.path, rel, False) for rel in rels]
        for clear in clears:
            try:
                clear()
            except (loose.Refused, OSError) as e:
                failed = failed or e
        if isinstance(failed, OSError):
            raise loose.Refused(f"the page is in the trash, but its marks could not be cleared ({failed.strerror})")
        if failed:
            raise failed

    @classmethod
    def _unmark_quietly(cls, root, rels) -> None:
        """`_unmark` where a mark file that cannot be written must not stop what comes next: a delete that is refused all the
        same keeps the refusal that says where the page went, and a sweep archives the root's other pages."""
        with contextlib.suppress(loose.Refused):
            cls._unmark(root, rels)

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

    @staticmethod
    def _drop(dest: Path) -> None:
        """Take off the link a restore made at `dest`, so a refused restore leaves the page where it was, in the trash."""
        try:
            os.unlink(dest)
        except OSError as e:
            raise loose.Refused(f"the page is at its address and still in the trash ({e.strerror}): delete one of them") from None

    def restore_trash(self, root, ident: str) -> str:
        """Put a trashed page back at its old address; refused (`Taken`) when a page is there, also when one comes in while this runs, and never overwritten."""
        stamp, _, rel = ident.partition("/")
        if not stamp.isdigit() or not rel or any(p in ("", ".", "..") for p in rel.split("/")):
            raise KeyError(ident)
        src = Path(root.path) / TRASH / stamp / rel
        try:
            if not stat.S_ISREG(os.lstat(src).st_mode):     # one look: a purge between two looks leaked FileNotFoundError
                raise KeyError(ident)
        except FileNotFoundError:
            raise KeyError(ident) from None
        dest = Path(root.path) / rel
        # The file lock of the address first (the hub's lock order: a file lock, then the state stores'). A door create takes no
        # lock, only a link that fails when the name is taken: so the move here is a link too, never a rename, which would
        # replace a page that came in between the check and the move.
        with file_lock(dest), state.file_locked("loose-keep.lock"):
            if os.path.lexists(dest):
                raise Taken(rel)
            for part in reversed(Path(rel).parents):
                if str(part) != ".":
                    os.makedirs(Path(root.path) / part, mode=0o700, exist_ok=True)
            try:
                before = os.lstat(src)
            except FileNotFoundError:
                raise KeyError(ident) from None     # purged since the look above
            try:
                os.link(src, dest, follow_symlinks=False)       # the entry itself, never what a link put there since the look leads to
            except FileExistsError:
                raise Taken(rel) from None
            except FileNotFoundError:
                if not os.path.lexists(src):
                    raise KeyError(ident) from None     # purged since its status above
                raise loose.Refused("the page could not be put back (its folder went away)") from None
            except OSError as e:
                if e.errno in NO_HARD_LINKS:
                    # 183 BL: a restore links, never renames, so a page a door create puts at the address meanwhile is never
                    # replaced; a file system without hard links cannot do that, and the owner moves the page back by hand.
                    raise loose.Refused(f"the page could not be put back: the file system, or its policy on hard links, refused "
                                        f"the hard link a restore needs so it never overwrites a page ({e.strerror}). Move "
                                        f"{TRASH / ident} back to {rel} by hand") from None
                raise loose.Refused(f"the page could not be put back ({e.strerror})") from None
            try:
                made = os.lstat(dest)
                if not stat.S_ISREG(made.st_mode) or (made.st_dev, made.st_ino) != (before.st_dev, before.st_ino):
                    raise loose.Refused("the page in the trash changed while it was put back: refused, nothing was restored")
                os.unlink(src)
            except loose.Refused:
                self._drop(dest)
                raise
            except OSError as e:
                self._drop(dest)
                raise loose.Refused(f"the page could not be taken out of the trash ({e.strerror}): nothing was restored") from None
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
                self._plain_dir(Path(root.path) / ".sheaf")     # a linked .sheaf or trash is not followed (`trash` refuses it too)
                self._plain_dir(base)
                stamps = [e for e in os.scandir(base) if e.name.isdigit() and e.is_dir(follow_symlinks=False)]
            except (OSError, loose.Refused):
                continue
            for e in stamps:
                if now - int(e.name) > TRASH_DAYS * DAY:
                    shutil.rmtree(e.path, ignore_errors=True)


class Taken(Exception):
    """A page is at the old address already."""


class Gone(Exception):
    """The page to delete went away before it was moved: a page that is not there (183 BK)."""


def sweep(hub) -> None:
    hub.archive.sweep()
