"""Move a loose page within its root, or a folder of it (SPEC 9.11, "Move and Forward"). The owner puts a page of their
loose root in another folder of the same root, a new folder named by its path; renaming a folder moves each page below
it. A folder exists only while a page is in it. The address changes, so the hub writes a Forward from the old one, and
everything it keeps of the page under the address goes along (`Hub.moved_page`); the text goes with the file, so the
comments, the Share line and the page's own front matter are untouched. Nothing here commits for a repo page, moves one
root's page to another root, or moves a page of a member who is not the owner."""
import contextlib
import os
import stat
import threading
from pathlib import Path

from . import loose, place
from ..source import file_lock
from .roots import Address, NotFound

_LOCK = threading.RLock()       # one move at a time in a hub: the checks and the rename are one step


@contextlib.contextmanager
def exclusive():
    """The moves' lock, for what else makes or reads a name of a loose root: its names are held by nothing else."""
    with _LOCK:
        yield


@contextlib.contextmanager
def page_held(hub, address: str):
    """The moves' lock, the name's lock of `address` and the page's writer lock (`Hub.page_lock`), held together. The page's
    lock is held by a render for up to 120 s, and a cancel, a move, a loose create and a forget all wait on the moves' lock:
    so it is never waited for under it. Taken only when it is free; else the moves' lock is let go, the page's lock waited
    for alone, and all three taken again (lockorder.py: let go, take it, look again). Not fair: on a page saved without a
    pause it goes round once per write, never under the moves' lock and never past a save it waited for. Its callers (a
    move to another tiroir, a restore from the trash) act on a loose page, whose name the hub does not place, so the name's
    lock holds nothing there; for a page placed by name a render holds that lock too, and it is waited for under the moves'."""
    while True:
        with _LOCK, place.held(hub, address), hub.page_lock_now(address) as got:
            if got:
                yield
                return
        with hub.page_lock(address):    # the wait, under none of the three: over when the render is
            pass


class Refused(Exception):
    """A move the hub will not make: the status the route answers with, and the sentence."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _root_of(hub, member, address: str):
    """(the root, the path in it) of the page at `address`, once it is a page of `member`'s own loose root. A page of another
    root, whoever's, is not one a Move can reach, and a page of another member's loose root is its owner's alone to move."""
    if member is None:
        raise Refused(403, "Only a signed-in member moves a page.")
    at = Address.parse(address)
    root = hub.roots.get(at.root)
    if root is None:
        raise Refused(404, "no such document")
    owner = hub.loose.owner_of(root)
    if owner is None:
        raise Refused(409, "Only a page of a loose root moves; a page of a repo moves by git.")
    if owner != member.id:
        raise Refused(403, "Only the owner of this page can move it.")
    return root, at.rel


def _folder(text) -> str:
    if not isinstance(text, str):
        raise Refused(400, "folder must be text")
    try:
        return loose.folder_path(text)
    except ValueError as e:
        raise Refused(400, f"{e}.") from None


def _clear(hub, address: str, came_from: str | None):
    """Refuse an `address` that an earlier move left a Forward at: it may be taken again only by the page the Forward leads
    to, moving back. An address that once pointed at a page must not silently become another."""
    to = hub.forwards.follow(address)
    if to is not None and to != came_from:
        raise Refused(409, "A page moved away from that address, and its Forward stays: pick another folder or name.")


BEING_MOVED = "This page is being moved. Try again in a moment."


def _quiet(hub, address: str):
    """A Tell that runs on the page, or waits for its reply, holds the page's address: it is moved when that ends. The
    answer holds only under the hub's admission lock, the one a Tell's start takes (`Tell._admitting`): taken from the look
    to the rename, a Tell either began before it and is seen, or begins after the rename and finds the page gone."""
    if hub.tell_live(address):
        raise Refused(409, "A Tell is running on this page: move it when that ends.")


@contextlib.contextmanager
def _marked(hub, address: str):
    """`address` is being moved: no Tell is on it (`_quiet`) and none starts (`Tell._admitting` refuses a marked
    address), both decided under the admission lock, which is let go before the rename. So the rename waits on the
    page's name and file locks with no admission lock held, and a save in flight never keeps a Tell start on another
    page waiting. The mark stays until the hub has moved what it keeps of the page."""
    with hub.admit:
        if address in hub.moving:           # another move holds it: its mark is not ours to set again, or to clear
            raise Refused(409, BEING_MOVED)
        _quiet(hub, address)
        hub.moving.add(address)
    try:
        yield
    finally:
        with hub.admit:
            hub.moving.discard(address)


def move_page(hub, member, address: str, folder: str) -> str:
    """The page at `address`, put in `folder` of its root under the same file name: its new address. Raises `Refused`."""
    folder = _folder(folder)
    with _LOCK:
        root, rel = _root_of(hub, member, address)
        new_rel = f"{folder}/{rel.rsplit('/', 1)[-1]}"
        if new_rel == rel:
            raise Refused(409, "The page is in that folder already.")
        new = str(Address(root.name, new_rel))
        _clear(hub, new, address)
        _quiet(hub, address)        # said early, nothing taken yet; asked again with the mark (`_marked`) before the rename
        with _marked(hub, address), place.held(hub, address), place.held(hub, new):
            _put(hub, root, rel, new_rel, address, new)
            hub.moved_page(address, new, member.name)
    return new


def _put(hub, root, rel: str, new_rel: str, address: str, new: str):
    """The file at `rel` is the file at `new_rel`: made new beneath the root, each folder opened without a link, then the
    old name taken off, so the page is never missing or twice there; the folders it leaves empty go. Called with the
    name locks held, and the address marked (`_marked`) unless it is an undo; takes the page's file lock only, which a
    save holds through its whole step, so a save under way is waited for and its text is at the new address. The
    admission lock is never taken here (lockorder.py)."""
    try:
        hub.roots.resolve(address)
    except NotFound:
        raise Refused(404, "no such document") from None
    top = Path(os.path.realpath(root.path))
    src, dst = top / rel, top / new_rel
    with file_lock(src):
        _link(hub, root, top, rel, new_rel, src, dst)
    tidy(top, rel)


def _link(hub, root, top: Path, rel: str, new_rel: str, src: Path, dst: Path):
    try:
        if not stat.S_ISREG(os.lstat(src).st_mode):
            raise Refused(409, "The page is not a plain file.")
    except OSError:
        raise Refused(404, "no such document") from None
    if os.path.lexists(dst):
        raise Refused(409, "A page of that name is in that folder already.")
    made = missing_folders(top, new_rel)
    try:
        os.close(place.make_folders(top, new_rel, place.judge_for(hub, root))[0])
        os.link(src, dst)                   # fails when the name is taken: nothing is written over
    except FileExistsError:
        unmake(made)
        raise Refused(409, "A page of that name is in that folder already.") from None
    except OSError as e:
        unmake(made)
        raise Refused(409, f"The page could not be moved ({e.strerror}).") from None
    os.unlink(src)


def missing_folders(top: Path, rel: str) -> list:
    """The folders on the way to `rel` under `top` that are not there yet, outermost first."""
    out, at = [], Path(top)
    for part in rel.split("/")[:-1]:
        at = at / part
        if not os.path.lexists(at):
            out.append(at)
    return out


def unmake(made: list):
    """Take back the folders `missing_folders` named, innermost first, each only if it is empty."""
    for folder in reversed(made):
        with contextlib.suppress(OSError):
            os.rmdir(folder)


def tidy(top: Path, rel: str):
    """A folder exists only while a page is in it: the folders `rel` was in go, innermost first, each only when empty. A
    folder that holds anything else, a dot-folder among it, stays; the root itself never goes."""
    at = (top / rel).parent
    while at != top and top in at.parents:
        try:
            os.rmdir(at)
        except OSError:
            return
        at = at.parent


def move_folder(hub, member, folder: str, to: str) -> list:
    """Every page below `folder` of the member's loose root is put at the same place below `to`: the addresses moved, as
    (old, new). Nothing moves when a page would land on a name that is taken, or on an address that a Forward holds for
    another page. Raises `Refused`."""
    folder, to = _folder(folder), _folder(to)
    if member is None:
        raise Refused(403, "Only a signed-in member moves a folder.")
    if to == folder or to.startswith(folder + "/"):
        raise Refused(409, "A folder cannot be moved into itself.")
    with _LOCK:
        held = hub.loose.known(member)
        root = hub.roots.lookup(held / "x.md") if held is not None else None
        if root is None or hub.loose.owner_of(root) != member.id:
            raise Refused(404, "no such folder")
        top = Path(os.path.realpath(root.path))
        pages = _pages(top, folder)
        if not pages:
            raise Refused(404, "no such folder")
        plan = []
        for rel in pages:
            new_rel = to + rel[len(folder):]
            old, new = str(Address(root.name, rel)), str(Address(root.name, new_rel))
            if os.path.lexists(top / new_rel):
                raise Refused(409, f"A page named {new_rel.rsplit('/', 1)[-1]} is in {to} already: nothing was moved.")
            _clear(hub, new, old)
            _quiet(hub, old)
            plan.append((rel, new_rel, old, new))
        done, before = [], hub.forwards.snapshot()
        try:
            for rel, new_rel, old, new in plan:
                with _marked(hub, old), place.held(hub, old), place.held(hub, new):
                    _put(hub, root, rel, new_rel, old, new)
                    hub.moved_page(old, new, member.name)
                done.append((rel, new_rel, old, new))
        except BaseException:
            _undo(hub, root, member, done, before)
            raise
        return [(old, new) for _, _, old, new in done]


def _undo(hub, root, member, done: list, before: dict):
    """A folder move that failed halfway: the pages already moved go back, last first, each with what the hub keeps of it,
    and the Forwards are as they were. A page that cannot go back is a row in the diagnostics log, and the others go back
    all the same."""
    for rel, new_rel, old, new in reversed(done):
        try:
            with place.held(hub, new), place.held(hub, old):
                _put(hub, root, new_rel, rel, new, old)
                hub.moved_page(new, old, member.name)
        except Exception:
            hub.record_exception("move-undo-failed", old)
    hub.forwards.restore(before)


def _pages(top: Path, folder: str) -> list[str]:
    """The .md files of `folder` and the folders below it, as paths in the root: no dot-folder, no link."""
    out, base = [], top / folder
    if not base.is_dir() or base.is_symlink():
        return out
    for here, dirs, files in os.walk(base, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not os.path.islink(os.path.join(here, d)))
        for f in sorted(files):
            p = Path(here) / f
            if f.endswith(".md") and not f.startswith(".") and stat.S_ISREG(os.lstat(p).st_mode):
                out.append(p.relative_to(top).as_posix())
    return out
