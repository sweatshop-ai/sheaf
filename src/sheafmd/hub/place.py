"""
sheafmd.hub.place — where the file of a sheaf of the list's root is (SPEC 9.11 "Where a sheaf lives").

    logical(rel)                     `<client>/<project>/<name>.md` of a file at its home or at a private home
    names_private(rel)               whether a path names a folder where only the hub places sheaves
    applies(hub, root_name)          whether the hub places the sheaves of that root
    physical(hub, root, rel)         the path of the file a sheaf's name holds now (for `Roots`, at each lookup)
    file_rel(top, rel)               the same without a check: the path to read or write, or `rel`
    named(hub, root, top, rel)       the name a listed file is shown by, None for a file no name shows
    home(hub, root, name, text)      the path in the root where that text lives, None when it has none
    place(hub, address, ...)         the file moved to its home: the path it left, or None
    owner_short(hub, root, address, fm)   the `short` that names the sheaf's private folder
    make_folders(top, rel)           the folder of `rel`, made on the way, walked without following a link
    taken(top, name), holders(top, name)  whether a logical name is held, and by which paths
    held(hub, address)               the lock of the sheaf's name, for a writer that writes or moves its file
    folders_lock(top, name)          the lock of the project's private folders
    refusal(hub, address, text)      why the sheaf could not go home once its file holds `text`

In proxy mode, in the list's root (9.10) only, a sheaf at project depth has one name, its address
`<client>/<project>/<name>.md`, and one home for its file: open to the project, that path; its owner's alone,
`<client>/<project>/private/<short>/<name>.md`, where `short` is its owner's (the member its `owner` names when that
member owns it, else the first owner, in the config's order, that has one). The Memorizer's GitHub connector gives each
path glob one owner: the shared stanza reads `<client>/*/*.md`, an owner's `*/*/private/<short>/**/*.md`, so a file's
place says whose it is. The hub keys everything of a sheaf (its entry, versions, read state, render settings) by the
name, and finds the file only when it reads or writes it; a move is a rename of the file and one commit of both
paths (8.11), and nothing else moves. The private path is no address: it names no document.
"""
import os
import stat
import threading
from contextlib import contextmanager
from pathlib import Path

from ..source import _folder_of, file_lock
from . import commits as commits_mod
from . import visibility
from .roots import Address, NotFound

PRIVATE = "private"
NO_SHORT = "it is its owner's alone and no owner of it has a short to name its private folder"


def logical(rel: str) -> str | None:
    """`<client>/<project>/<name>.md` of the file at `rel` (a path in the root): `rel` itself at project depth,
    the name under `<client>/<project>` for `<client>/<project>/private/<short>/<name>.md`; None for any other
    path, which the hub never moves."""
    parts = rel.split("/")
    if not rel.endswith(".md") or len(parts) not in (3, 5) or parts[1] == PRIVATE:
        return None
    if len(parts) == 3:
        return rel
    return f"{parts[0]}/{parts[1]}/{parts[4]}" if parts[2] == PRIVATE else None


def names_private(rel: str) -> bool:
    """Whether `rel` names a project called `private`, or a `private` folder directly under a project: where
    only the hub places sheaves, so a door create there is refused (9.11, 12)."""
    parts = rel.split("/")
    return (len(parts) >= 3 and parts[1] == PRIVATE) or (len(parts) >= 4 and parts[2] == PRIVATE)


def applies(hub, root_name: str) -> bool:
    """Whether the hub places the sheaves of the root `root_name`: proxy mode, and the list's root."""
    the_list = getattr(hub, "the_list", None)
    return getattr(hub, "proxy", None) is not None and the_list is not None and the_list.serves(root_name)


def _segment(short: str) -> bool:
    """Whether a member's `short` can be a folder name: never `.`, `..` or a hidden name."""
    return bool(short) and not short.startswith(".") and "/" not in short


def _one(top: Path, name: str):
    """(the path of the one file that holds the name `name`, or `name` when none does; the count of files that
    hold it). Two entries that are one file (a move between its link and its unlink) count once."""
    rels, seen = [], set()
    for rel in holders(top, name):
        try:
            st = os.lstat(top / rel)
            key = (st.st_dev, st.st_ino)
        except OSError:
            key = rel
        if key not in seen:
            seen.add(key)
            rels.append(rel)
    return (rels[0] if rels else name), len(rels)


def _twice(hub, address: str, n: int):
    _refused(hub, address, f"its name is held by {n} files")


def physical(hub, root, rel: str) -> str:
    """The path in `root` of the file the document `rel` names (`Roots` asks it at each lookup): `rel` itself where
    the hub does not place sheaves; for a sheaf's name, the one file that holds it, at its home or at any private
    home. Raises NotFound for a private path, which is no address, and for a name that two files hold (made by
    hand: nothing repairs it), which a `place-refused` row names."""
    name = logical(rel)
    if name is None or not applies(hub, root.name):
        return rel
    if name != rel:
        raise NotFound(f"{root.name}/{rel}")
    got, n = _one(Path(os.path.realpath(root.path)), name)
    if n > 1:
        _twice(hub, f"{root.name}/{name}", n)
        raise NotFound(f"{root.name}/{rel}")
    return got


def file_rel(top: Path, rel: str) -> str:
    """The path to read or write for the sheaf named `rel` in the root at `top`, which the hub places: the one file
    that holds the name, else `rel` (a name with no file, or with two, whose lookup `physical` refuses)."""
    name = logical(rel)
    if name is None or name != rel:
        return rel
    got, n = _one(top, name)
    return got if n == 1 else rel


def named(hub, root, top: Path, rel: str) -> str | None:
    """The path in the root that the listed file `rel` is shown by, in a root the hub places: its sheaf's name for
    the one file that holds it; None for a file of a name that two files hold, which a `place-refused` row names,
    and for the second entry of a file a move has at both paths."""
    name = logical(rel)
    if name is None:
        return rel
    got, n = _one(top, name)
    if n > 1:
        _twice(hub, f"{root.name}/{name}", n)
        return None
    return name if got == rel else None


def owner_short(hub, root, address: str, fm: dict) -> str | None:
    """The `short` that names the private folder of the sheaf at `address` whose front matter is `fm`: of the
    member its `owner` names, when that member is one of its owners; else of the first owner, in the config's
    order, that has one. Only members whose roots hold `root` count (9.9). None when no owner has one."""
    members = [m for m in hub.proxy.members.values() if hub.owns(m, root)]
    owners = [m for m in visibility.owner_of(fm, members, hub.assignees(address, fm)) if _segment(m.short)]
    named_ = visibility.text(fm, "owner").casefold()
    return next((m.short for m in owners if m.short.casefold() == named_), None) or \
        next((m.short for m in owners), None)


def home(hub, root, name: str, text: str) -> str | None:
    """The path in `root` where the file of the sheaf named `name` lives once it holds `text`: `name` when it is
    open to the project, `<client>/<project>/private/<short>/<file>` when it is its owner's alone. None for one
    that is its owner's alone with no owner that has a short."""
    fm = visibility.front_matter(text)
    if visibility.effective(fm) == "project":
        return name
    short = owner_short(hub, root, f"{root.name}/{name}", fm)
    if short is None:
        return None
    client, project, file = name.split("/")
    return f"{client}/{project}/{PRIVATE}/{short}/{file}"


def make_folders(top, rel: str):
    """(fd of the folder of `rel` under `top`, the file's name), making each missing folder on the way as the
    umask gives a new folder. Each folder is opened from the one above it without following a link, as
    `create_file` walks, so a link on the way is an OSError wherever it points."""
    return _folder_of(top, rel, make=True)


def _refused(hub, address: str, why: str):
    """A `place-refused` row, once per address per hub run: a sheaf that cannot move is met at every poll."""
    if address not in hub.told_place:
        hub.told_place.add(address)
        hub.record("place-refused", address, why=why)


def _name_lock(top: Path, name: str) -> threading.RLock:
    """The lock of the logical name `name` in the root at the real path `top`. Every writer of a name's file in the
    hub's process holds it: a door create, a write (the file is found again under it), a move, the tidying after
    it."""
    with _LOCKS_GUARD:
        return _LOCKS.setdefault((str(top), name), threading.RLock())


def folders_lock(top: Path, name: str) -> threading.RLock:
    """The lock of the private folders of the project of the logical name `name` in the root at `top`: held from
    making a `private/<short>` to the file linked into it, and while a move out takes away what it left empty, so
    the one never takes a folder from under the other, whatever names they write. Taken after the name's lock,
    before a file lock."""
    client, project, _ = name.split("/")
    with _LOCKS_GUARD:
        return _LOCKS.setdefault((str(top), f"{client}/{project}/{PRIVATE}/"), threading.RLock())


_LOCKS_GUARD = threading.Lock()
_LOCKS: dict = {}


@contextmanager
def held(hub, address: str):
    """Hold the lock of the sheaf's name `address` (9.11): no create of the name, no write of its file and no move
    of it comes in while it is held, so a writer that finds the file under it writes where the file is, and one
    that judges the name's homes finds them as it judged. Nothing to hold where the hub does not place the sheaf.
    Gives whether it holds a lock. Re-entrant: `place` and a document's write take it again. Taken before the
    document's own lock (live.py) and before a file lock."""
    got = _where(hub, address)
    if got is None:
        yield False
        return
    with _name_lock(got[1], got[2]):
        yield True


def _where(hub, address: str):
    """(its root, the real path of the root, its name) of a sheaf's name that the hub places, else None."""
    at = Address.parse(address)
    if not at.plain or logical(at.rel) != at.rel or not applies(hub, at.root):
        return None
    root = hub.roots.get(at.root)
    if root is None:
        return None
    return root, Path(os.path.realpath(root.path)), at.rel


def refusal(hub, address: str, text: str) -> str | None:
    """Why the file of the sheaf named `address` could not go to its home once it holds `text`, None when it could
    or the hub does not place it: a writer asks before it writes, under `held`, so a write that would leave the
    file where it may not stay is refused instead (9.11)."""
    got = _where(hub, address)
    if got is None:
        return None
    root, top, name = got
    target = home(hub, root, name, text)
    if target is None:
        return NO_SHORT
    if target != file_rel(top, name) and os.path.lexists(top / target):
        return f"{target} is taken"
    return None


def place(hub, address: str, member=None, by: str | None = None, commit: bool = True) -> str | None:
    """Move the file of the sheaf named `address` to its home, under the lock of its name and its file lock, and
    return the path in the root it left; None when it did not move: home already, a name the hub does not place,
    a file that is a link (which stays where it is written), or a move refused (a `place-refused` row says why: no
    owner with a short, the name held by two files, the home taken). The file is linked into place, never over
    anything, and only then unlinked where it was. Nothing else moves: the hub keys the sheaf by its name. With
    `commit`, the root commits `move: <old> -> <new>` as `member`, `by` (a door caller's display name) or else the
    hub (the poll). A writer that moves the file it just wrote passes `commit=False` and commits the write and the
    move as one (`Hub.committed` with `gone`)."""
    got = _where(hub, address)
    if got is None:
        return None
    root, top, name = got
    with _name_lock(top, name), folders_lock(top, name):
        rel, n = _one(top, name)
        if n > 1:
            _twice(hub, address, n)
            return None
        gone = _move(hub, root, top, rel, name, address) if n else None
        if gone is not None:
            _tidy(top, gone)
            hub.wrote(address)
    if gone is not None and commit:
        if member is None and by is None:
            hub.committed(address, what="move", gone=gone, author=commits_mod.Author(*commits_mod.COMMITTER))
        else:
            hub.committed(address, member, "move", by, gone=gone)
    return gone


def _move(hub, root, top: Path, rel: str, name: str, address: str) -> str | None:
    with file_lock(top / rel):
        try:
            sfd, sname = _folder_of(top, rel)
        except OSError:
            return None
        try:
            try:
                st = os.stat(sname, dir_fd=sfd, follow_symlinks=False)
                if not stat.S_ISREG(st.st_mode):
                    return None         # a link stays where it is written: the sheaf it names is placed itself
                fd = os.open(sname, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=sfd)
                with os.fdopen(fd, "rb") as f:
                    text = f.read().decode("utf-8")
            except (OSError, UnicodeDecodeError):
                return None             # gone, or not a text the hub reads: nothing to judge it on
            target = home(hub, root, name, text)
            if target is None:
                _refused(hub, address, NO_SHORT)
                return None
            if target == rel:
                return None
            try:
                dfd, dname = make_folders(top, target)
            except OSError as e:
                _refused(hub, address, f"its folder could not be made ({e.strerror})")
                return None
            try:
                os.link(sname, dname, src_dir_fd=sfd, dst_dir_fd=dfd, follow_symlinks=False)
            except FileExistsError:
                _refused(hub, address, f"{target} is taken")
                return None
            except OSError as e:
                _refused(hub, address, f"it could not be moved ({e.strerror})")
                return None
            finally:
                os.close(dfd)
            os.unlink(sname, dir_fd=sfd)
        finally:
            os.close(sfd)
    return rel


def _tidy(top: Path, rel: str):
    """Take away the private folders a move out left empty, `private/<short>` and then `private`: git keeps no
    folder, and an empty one says nothing. A folder that holds anything, or is a link, stays."""
    parts = rel.split("/")
    if len(parts) != 5 or parts[2] != PRIVATE:
        return
    for folder in (top.joinpath(*parts[:4]), top.joinpath(*parts[:3])):
        try:
            os.rmdir(folder)
        except OSError:
            return


def taken(top: Path, name: str) -> bool:
    """Whether the logical name `name` is held: by a file at `<client>/<project>/<name>.md` or at any
    `<client>/<project>/private/*/<name>.md`, whatever the caller may see (9.11: a create tells that a name is
    taken, never what holds it)."""
    return bool(holders(top, name))


def holders(top: Path, name: str) -> list:
    """The paths in the root, under `top`, of every entry that holds the logical name `name`: at
    `<client>/<project>/<name>.md` and at each `<client>/<project>/private/*/<name>.md`, a link or a dangling one
    included."""
    client, project, file = name.split("/")
    held_ = [name] if os.path.lexists(top / name) else []
    try:
        with os.scandir(top / client / project / PRIVATE) as it:
            held_ += [f"{client}/{project}/{PRIVATE}/{d.name}/{file}" for d in it if d.is_dir(follow_symlinks=False)
                      and os.path.lexists(top / client / project / PRIVATE / d.name / file)]
    except OSError:
        pass
    return held_
