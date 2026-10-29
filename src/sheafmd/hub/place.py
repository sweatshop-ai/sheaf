"""
sheafmd.hub.place — where a sheaf of the list's root lives (SPEC 9.11 "Where a sheaf lives").

    logical(rel)                     `<client>/<project>/<name>.md` of a sheaf at its home or at a private home
    names_private(rel)               whether a path names a folder where only the hub places sheaves
    applies(hub, root_name)          whether the hub places the sheaves of that root
    home(hub, root, logical, address, text)   the path in the root where that text lives, None when it has none
    place(hub, address, ...)         the file moved to its home: the address it lives at now
    found(hub, address, may_see)     the one address a missing logical or private name lives at now

In proxy mode, in the list's root (9.10) only, a sheaf at project depth has one home: open to the project,
`<client>/<project>/<name>.md`; its owner's alone, `<client>/<project>/private/<short>/<name>.md`, where `short`
is its owner's (the member its `owner` names when that member owns it, else the first owner, in the config's
order, that has one). The Memorizer's GitHub connector gives each path glob one owner: the shared stanza reads
`<client>/*/*.md`, an owner's `*/*/private/<short>/**/*.md`, so a file's place says whose it is. A move takes the
document's versions, read state and render settings with it, and is one commit of both paths (8.11).
"""
import os
import stat
import threading
from contextlib import contextmanager
from pathlib import Path

from ..source import _folder_of, file_lock
from . import commits as commits_mod
from . import visibility
from .roots import Address

PRIVATE = "private"
NO_SHORT = "it is its owner's alone and no owner of it has a short to name its private folder"


def logical(rel: str) -> str | None:
    """`<client>/<project>/<name>.md` of the sheaf at `rel` (a path in the root): `rel` itself at project depth,
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


def owner_short(hub, root, address: str, fm: dict) -> str | None:
    """The `short` that names the private folder of the sheaf at `address` whose front matter is `fm`: of the
    member its `owner` names, when that member is one of its owners; else of the first owner, in the config's
    order, that has one. Only members whose roots hold `root` count (9.9). None when no owner has one."""
    members = [m for m in hub.proxy.members.values() if hub.owns(m, root)]
    owners = [m for m in visibility.owner_of(fm, members, hub.assignees(address, fm)) if _segment(m.short)]
    named = visibility.text(fm, "owner").casefold()
    return next((m.short for m in owners if m.short.casefold() == named), None) or \
        next((m.short for m in owners), None)


def home(hub, root, name: str, address: str, text: str) -> str | None:
    """The path in `root` where the sheaf `text`, whose logical name is `name` and whose file is at `address`
    (or is to be made there), lives: `name` when it is open to the project, `<client>/<project>/private/<short>/
    <file>` when it is its owner's alone. None for one that is its owner's alone with no owner that has a short."""
    fm = visibility.front_matter(text)
    if visibility.effective(fm) == "project":
        return name
    short = owner_short(hub, root, address, fm)
    if short is None:
        return None
    client, project, file = name.split("/")
    return f"{client}/{project}/{PRIVATE}/{short}/{file}"


def make_folders(top, rel: str):
    """(fd of the folder of `rel` under `top`, the file's name), making each missing folder on the way as the
    umask gives a new folder. Each folder is opened from the one above it without following a link, as
    `create_file` walks, so a link on the way is an OSError wherever it points."""
    parts = rel.split("/")
    fd = os.open(top, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for seg in parts[:-1]:
            try:
                inner = os.open(seg, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                try:
                    os.mkdir(seg, 0o777, dir_fd=fd)
                except FileExistsError:
                    pass                # made meanwhile: opened as any other, a link refused
                inner = os.open(seg, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = inner
    except BaseException:
        os.close(fd)
        raise
    return fd, parts[-1]


def _refused(hub, address: str, why: str):
    """A `place-refused` row, once per address per hub run: a sheaf that cannot move is met at every poll."""
    if address not in hub.told_place:
        hub.told_place.add(address)
        hub.record("place-refused", address, why=why)


def _name_lock(top: Path, name: str) -> threading.RLock:
    """The lock of the logical name `name` in the root at the real path `top`. Every writer that judges or changes
    where a name's file is (a door create, a move, the tidying after it) is in the hub's process and holds it."""
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
    """Hold the lock of the logical name of the sheaf at `address` (9.11): no create of the name, and no move of
    its file, comes in while it is held, so a writer that judges the name's homes and then writes finds them as it
    judged. Nothing to hold where the hub does not place the sheaf. Gives whether it holds a lock. Re-entrant:
    `place` takes it again."""
    got = _where(hub, address)
    if got is None:
        yield False
        return
    with _name_lock(got[1], got[2]):
        yield True


def _where(hub, address: str):
    """(its root, the real path of the root, its logical name) of a sheaf the hub places, else None."""
    at = Address.parse(address)
    if not at.plain or not applies(hub, at.root):
        return None
    name = logical(at.rel)
    root = hub.roots.get(at.root)
    if name is None or root is None:
        return None
    return root, Path(os.path.realpath(root.path)), name


def refusal(hub, address: str, text: str) -> str | None:
    """Why the sheaf at `address` could not go to its home once its file holds `text`, None when it could or the
    hub does not place it: a writer asks before it writes, under `held`, so a write that would leave the sheaf
    where it may not stay is refused instead (9.11)."""
    got = _where(hub, address)
    if got is None:
        return None
    root, top, name = got
    return _judge(hub, root, top, Address.parse(address).rel, name, address, text)[1]


def _judge(hub, root, top: Path, rel: str, name: str, address: str, text: str):
    """(the home of `text`, None) when it may go there or is there, (None, why) when it may not."""
    target = home(hub, root, name, address, text)
    if target is None:
        return None, NO_SHORT
    if target != rel and [r for r in holders(top, name) if r != rel]:
        # The name has one file (9.11): another under any home of it, its target or not, keeps this one here.
        return None, f"its name {name} is held by another file"
    return target, None


def place(hub, address: str, member=None, by: str | None = None, commit: bool = True) -> str:
    """Move the sheaf at `address` to its home, under the lock of its name and its file lock, and return the
    address it lives at now: `address` itself when it is home already, when the hub does not place it (another
    root, loopback mode, a path that is no sheaf's, a link, which stays where it is written), or when the move is
    refused (a `place-refused` row says why: no owner with a short, the name held by another file). The file is
    linked into place, never over anything, and only then unlinked where it was. Its versions, read state and
    render settings follow it, an open page is told `moved`, the index and the list hear of both addresses, and,
    with `commit`, the root commits `move: <old> -> <new>` as `member`, `by` (a door caller's display name) or
    else the hub (the poll). A writer that moves the file it just wrote passes `commit=False` and commits the
    write and the move as one (`Hub.committed` with `gone`)."""
    got = _where(hub, address)
    if got is None:
        return address
    root, top, name = got
    rel = Address.parse(address).rel
    with _name_lock(top, name), folders_lock(top, name):
        new = _move(hub, root, top, rel, name, address)
        if new != address:
            _tidy(top, rel)
    if new != address and commit:
        if member is None and by is None:
            hub.committed(new, what="move", gone=rel, author=commits_mod.Author(*commits_mod.COMMITTER))
        else:
            hub.committed(new, member, "move", by, gone=rel)
    return new


def _move(hub, root, top: Path, rel: str, name: str, address: str) -> str:
    with file_lock(top / rel):
        try:
            sfd, sname = _folder_of(top, rel)
        except OSError:
            return address
        try:
            try:
                st = os.stat(sname, dir_fd=sfd, follow_symlinks=False)
                if not stat.S_ISREG(st.st_mode):
                    return address      # a link stays where it is written: the sheaf it names is placed itself
                fd = os.open(sname, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=sfd)
                with os.fdopen(fd, "rb") as f:
                    text = f.read().decode("utf-8")
            except (OSError, UnicodeDecodeError):
                return address          # gone, or not a text the hub reads: nothing to judge it on
            target, why = _judge(hub, root, top, rel, name, address, text)
            if target is None:
                _refused(hub, address, why)
                return address
            if target == rel:
                return address
            try:
                dfd, dname = make_folders(top, target)
            except OSError as e:
                _refused(hub, address, f"its folder could not be made ({e.strerror})")
                return address
            try:
                os.link(sname, dname, src_dir_fd=sfd, dst_dir_fd=dfd, follow_symlinks=False)
            except FileExistsError:
                _refused(hub, address, f"{target} is taken")
                return address
            except OSError as e:
                _refused(hub, address, f"it could not be moved ({e.strerror})")
                return address
            finally:
                os.close(dfd)
            os.unlink(sname, dir_fd=sfd)
        finally:
            os.close(sfd)
        new = f"{root.name}/{target}"
        _follow(hub, root, address, new)
    return new


def _follow(hub, root, old: str, new: str):
    """What the hub keeps of the document at `old` goes to `new`: its versions (7.4), the read state of the hub's
    person and of each member, its render settings; its entry goes, and each page open on it is told `moved`, the
    last event of its stream; the index looks at both addresses and the list's row takes the new path."""
    hub._versions_of(root).move(old, new)
    for store in (hub.seen, hub.member_seen, hub.docs):
        store.move(old, new)
    with hub._lock:
        e = hub.entries.pop(old, None)
    if e is not None:
        e.bus.publish("moved", {"doc": old, "to": new})
    hub.wrote(new)
    try:
        hub.index.touch(old)
    except Exception:
        hub.record_exception("status-failed")
    if hub.the_list is not None:
        hub.the_list.moved(Address.parse(old).rel, Address.parse(new).rel)


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


def found(hub, address: str, may_see) -> str | None:
    """The address where the sheaf that `address` names lives now, when `address` is a sheaf's name in the list's
    root and no file is there: the one file among `<client>/<project>/<name>.md` and every
    `<client>/<project>/private/*/<name>.md` that `may_see(address)` lets the caller open. None when there is no
    such file, or more than one, or a file is at `address`."""
    at = Address.parse(address)
    if not at.plain or not applies(hub, at.root):
        return None
    name = logical(at.rel)
    root = hub.roots.get(at.root)
    if name is None or root is None:
        return None
    top = Path(os.path.realpath(root.path))
    if os.path.lexists(top / at.rel):
        return None
    client, project, file = name.split("/")
    rels = [name]
    try:
        with os.scandir(top / client / project / PRIVATE) as it:
            rels += [f"{client}/{project}/{PRIVATE}/{d.name}/{file}" for d in it
                     if _segment(d.name) and d.is_dir(follow_symlinks=False)]
    except OSError:
        pass
    hits = []
    for rel in rels:
        if rel == at.rel or not (top / rel).is_file() or (top / rel).is_symlink():
            continue
        if may_see(f"{root.name}/{rel}"):
            hits.append(f"{root.name}/{rel}")
    return hits[0] if len(hits) == 1 else None


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
    held = [name] if os.path.lexists(top / name) else []
    try:
        with os.scandir(top / client / project / PRIVATE) as it:
            held += [f"{client}/{project}/{PRIVATE}/{d.name}/{file}" for d in it if d.is_dir(follow_symlinks=False)
                     and os.path.lexists(top / client / project / PRIVATE / d.name / file)]
    except OSError:
        pass
    return held

