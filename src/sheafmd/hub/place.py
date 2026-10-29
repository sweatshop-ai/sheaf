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
    held(hub, address)               the lock of the sheaf's name, for every read and write of its file
    owns(hub, address)               whether this thread holds that lock (a commit asserts it)
    ahead(hub, address, old, new)    a writer's move of the file to the home of the text it is about to write;
                                     `Refused` when it cannot go there, and nothing is written
    folders_lock(top, name)          the lock of the project's private folders
    tell_link(hub, root, top, rel)   a `link-ignored` row for a listed entry that holds no name
    ignores(top, target)             whether a private home is one the root's repo ignores
    tell_ignored(hub, root, folders) a `private-ignored` row when the root's repo ignores a private home

In proxy mode, in the list's root (9.10) only, a sheaf at project depth has one name, its address
`<client>/<project>/<name>.md`, and one home for its file: open to the project, that path; its owner's alone,
`<client>/<project>/private/<short>/<name>.md`, where `short` is its owner's (the member its `owner` names when that
member owns it, else the first owner, in the config's order, that has one). The Memorizer's GitHub connector gives each
path glob one owner: the shared stanza reads `<client>/*/*.md`, an owner's `*/*/private/<short>/**/*.md`, so a file's
place says whose it is. The hub keys everything of a sheaf (its entry, versions, read state, render settings) by the
name, and finds the file only when it reads or writes it; a move is a rename of the file and one commit of both
paths (8.11), and nothing else moves. Every read and every write of a name holds its lock (`held`); a move is move,
write, render, commit, under it, and a write and its commit are one step under it. A name is held only by a regular
file reached from the root through real folders: a link, or a file under a linked folder, holds none, so one file
never has two names and two name locks. A path under `private/` is no address: it names no document. The repo of
such a root must not ignore `private/`: the listing (8.6) would no longer show a sheaf the hub moved there, so a move
into a folder the repo ignores is refused, and the root is told of once.
"""
import os
import stat
import subprocess
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

from ..source import _folder_of, file_lock
from . import commits as commits_mod
from . import visibility
from .roots import Address, NotFound

PRIVATE = "private"
# The folder of a project's private folders where an owner-only sheaf the hub cannot place goes (#61): no `short` can
# name it (`~` is none of a short's characters), so no owner's Library glob reads it, nor the project's
# `<client>/<project>/*.md`; it is no hidden folder, which the listing would leave out (8.6).
QUARANTINE = "~unplaced"
NO_SHORT = "it is its owner's alone and no owner of it has a short to name its private folder"
IGNORED = "the repo ignores the private folder"


class Refused(Exception):
    """A write whose file could not go to the home of the text it was about to write (9.11): nothing is written.
    `why` says what kept it, as a `place-refused` row would."""

    def __init__(self, why: str):
        super().__init__(why)
        self.why = why


def _ignored(top: Path, paths: list) -> list:
    """Those of `paths` (in the root at `top`) that the repo's ignore rules name, in one `git check-ignore`; none
    outside a git work tree, or when git does not answer."""
    if not paths:
        return []
    try:
        got = subprocess.run(["git", "-C", str(top), "check-ignore", "--", *paths], capture_output=True, text=True,
                             timeout=commits_mod.GIT_SECONDS, env=commits_mod._env())
    except (OSError, subprocess.SubprocessError):
        return []
    return got.stdout.splitlines() if got.returncode == 0 else []


def _private_home(rel: str) -> bool:
    parts = rel.split("/")
    return len(parts) == 5 and parts[2] == PRIVATE


def quarantine(name: str) -> str:
    """The path in the root of the quarantine of the sheaf named `name`: `<client>/<project>/private/~unplaced/<file>`."""
    client, project, file = name.split("/")
    return f"{client}/{project}/{PRIVATE}/{QUARANTINE}/{file}"


def quarantined(rel: str) -> bool:
    """Whether `rel` is a file in a project's quarantine."""
    parts = rel.split("/")
    return len(parts) == 5 and parts[2] == PRIVATE and parts[3] == QUARANTINE


def ignores(top: Path, target: str) -> bool:
    """Whether `target`, a home in the root at `top`, is a private home its repo ignores: no file goes there, by a
    move or a create (9.11), or the listing (8.6) would no longer show it."""
    return _private_home(target) and bool(_ignored(top, [target]))


def tell_ignored(hub, root, folders):
    """A `private-ignored` row (15) and a line on stderr, once per root per hub run, when the repo of `root`, which
    the hub places, ignores the private home of a member whose roots hold it in one of the project `folders`
    (`<client>/<project>`): the listing leaves out what git ignores (8.6), so a sheaf moved there would leave the
    list, the index and the door. Nothing moves there (`_move`)."""
    if root.id in hub.told_ignored:
        return
    shorts = [m.short for m in hub.proxy.members.values() if _segment(m.short) and hub.owns(m, root)]
    probes = [f"{f}/{PRIVATE}/{s}/{PROBE}" for f in sorted(folders) for s in shorts]
    got = _ignored(Path(os.path.realpath(root.path)), probes)
    if not got:
        return
    hub.told_ignored.add(root.id)
    folder = got[0].rsplit("/", 1)[0]
    hub.record("private-ignored", None, root=root.name, folder=folder)
    print(f"sheaf: {root.name}/{folder} is ignored by the repo: sheaves are not moved into private folders there",
          file=sys.stderr, flush=True)


PROBE = "sheaf.md"


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


def _holds(top: Path, rel: str) -> bool:
    """Whether the entry at `rel` in the root at the real path `top` can hold a name (9.11): a regular file, reached
    from the root through real folders. A link, or a file under a linked folder, holds none: a link and its target
    would be two names, two name locks, of one file and its one file lock."""
    try:
        if not stat.S_ISREG(os.lstat(top / rel).st_mode):
            return False
    except OSError:
        return False
    return _real(top, rel)


def _real(top: Path, rel: str) -> bool:
    """Whether `rel` is reached from the root at the real path `top` through no link, itself none (9.11)."""
    return os.path.realpath(top / rel) == str(top / rel)


def _one(top: Path, name: str):
    """(the path of the one file that holds the name `name`, or `name` when none does; the count of files that
    hold it). Two entries that are one file (a move between its link and its unlink) count once; an entry that
    holds no name (`_holds`) is not counted."""
    rels, seen = [], set()
    for rel in holders(top, name):
        try:
            st = os.lstat(top / rel)
            key = (st.st_dev, st.st_ino)
        except OSError:
            continue
        if not _holds(top, rel):
            continue
        if key not in seen:
            seen.add(key)
            rels.append(rel)
    return (rels[0] if rels else name), len(rels)


def _twice(hub, address: str, n: int):
    _refused(hub, address, f"its name is held by {n} files")


def physical(hub, root, rel: str) -> str:
    """The path in `root` of the file the document `rel` names (`Roots` asks it at each lookup): `rel` itself where
    the hub does not place sheaves; for a sheaf's name, the one file that holds it, at its home or at any private
    home. Raises NotFound for any path under a project's `private` folder (or in a project called `private`), at
    any depth, which is no address; for a path that is a link or passes through one, at any depth, made or not;
    for a name that two files hold (made by hand: nothing repairs it), which a `place-refused` row names; and for
    a name whose entries hold none (a link: `_holds`)."""
    if not applies(hub, root.name):
        return rel
    if names_private(rel):
        raise NotFound(f"{root.name}/{rel}")
    top = Path(os.path.realpath(root.path))
    name = logical(rel)
    if name is None:
        if not _real(top, rel):
            raise NotFound(f"{root.name}/{rel}")        # no address reaches a file through a link (9.11)
        return rel
    got, n = _one(top, name)
    if n > 1:
        _twice(hub, f"{root.name}/{name}", n)
        raise NotFound(f"{root.name}/{rel}")
    if n == 0 and taken(top, name):
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
    for the second entry of a file a move has at both paths, for an entry that holds no name (a link: `_holds`),
    for any other path that is a link or passes through one, which no address reaches (`physical`), and for any
    other file under a `private` folder, which no name shows."""
    name = logical(rel)
    if name is None:
        return None if names_private(rel) or not _real(top, rel) else rel
    got, n = _one(top, name)
    if n > 1:
        _twice(hub, f"{root.name}/{name}", n)
        return None
    return name if n == 1 and got == rel else None


def tell_link(hub, root, top: Path, rel: str):
    """A `link-ignored` row (15) with the root and the path, and a line on stderr, once per path per hub run, for an
    entry the listing gave that is a link or under a linked folder (9.11), at a sheaf's path or any other:
    the poll says it, never a lookup, so a link someone makes is seen and the hub serves nothing through it."""
    if (_holds(top, rel) if logical(rel) else _real(top, rel)) or (root.id, rel) in hub.told_link:
        return
    hub.told_link.add((root.id, rel))
    hub.record("link-ignored", None, root=root.name, path=rel)
    print(f"sheaf: {root.name}/{rel} is a link, or under a linked folder: it holds no sheaf's name and is not served",
          file=sys.stderr, flush=True)


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


def _refused(hub, address: str, why: str, quarantined_: bool = False):
    """A `place-refused` row, once per address per hub run: a sheaf that cannot move is met at every poll. A sheaf
    in quarantine (#61) has its own row, `quarantined: true`, once too."""
    if (address, quarantined_) not in hub.told_place:
        hub.told_place.add((address, quarantined_))
        hub.record("place-refused", address, why=why, **({"quarantined": True} if quarantined_ else {}))


@contextmanager
def _locked(key: tuple):
    """Hold the lock of `key` (re-entrant), counted in this thread's `_OWNED`. The lock lives in `_LOCKS` only while
    a thread holds it or waits on it: a name nobody holds costs nothing, however many names are asked for."""
    with _LOCKS_GUARD:
        got = _LOCKS.setdefault(key, [threading.RLock(), 0])
        got[1] += 1
    try:
        with got[0]:
            owned = _owned()
            owned[key] = owned.get(key, 0) + 1
            try:
                yield
            finally:
                owned[key] -= 1
                if not owned[key]:
                    del owned[key]
    finally:
        with _LOCKS_GUARD:
            got[1] -= 1
            if not got[1]:
                del _LOCKS[key]


def _owned() -> dict:
    if not hasattr(_THREAD, "owned"):
        _THREAD.owned = {}
    return _THREAD.owned


def _name_lock(top: Path, name: str):
    """The lock of the logical name `name` in the root at the real path `top`. Every writer of a name's file in the
    hub's process holds it: a door create, a write (the file is found again under it) and its commit, a move, the
    tidying after it; and every reader, from finding the file to the text read or rendered."""
    return _locked((str(top), name))


def folders_lock(top: Path, name: str):
    """The lock of the private folders of the project of the logical name `name` in the root at `top`: held from
    making a `private/<short>` to the file linked into it, and while a move out takes away what it left empty, so
    the one never takes a folder from under the other, whatever names they write. Taken after the name's lock,
    before a file lock."""
    client, project, _ = name.split("/")
    return _locked((str(top), f"{client}/{project}/{PRIVATE}/"))


_LOCKS_GUARD = threading.Lock()
_LOCKS: dict = {}                       # key -> [its RLock, the threads that hold it or wait on it]
_THREAD = threading.local()


def owns(hub, address: str) -> bool:
    """Whether this thread holds the lock of the sheaf's name `address`; True where the hub does not place it. A
    commit asserts it (`Hub.committed`): nothing commits a sheaf's file without holding its name (9.11)."""
    got = _where(hub, address)
    return got is None or (str(got[1]), got[2]) in _owned()


@contextmanager
def held(hub, address: str):
    """Hold the lock of the sheaf's name `address` (9.11): no create of the name, no write of its file and no move
    of it comes in while it is held, so a writer that finds the file under it writes where the file is, one that
    judges the name's homes finds them as it judged, and a reader reads the file it found, in the folder its text
    says. Nothing to hold where the hub does not place the sheaf. Gives whether it holds a lock. Re-entrant:
    `place` and a document's write take it again. Taken first: before the hub's lock (`Hub.entry`), the document's
    own lock (live.py), a file lock and the root's commit lock (commits.py). Held for disk work only: nothing under
    it waits on the network."""
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


def ahead(hub, address: str, old: str, new: str) -> str | None:
    """A writer that is about to write `new` over `old`, the text of the file of the sheaf named `address`, holding
    the name's lock and the file's lock, moves the file to the home of `new` first (9.11), so the new text is
    written, and rendered, in the folder it says: a reader never meets a visibility with the folder of the other.
    Returns the path in the root the file left, None when it stays (home already, a name the hub does not place);
    the writer then finds the file again and writes it there, and commits the write and the move as one. The one
    judge of whether the write may go: a file at the home of `old` that cannot go to the home of `new`, for any
    reason (no owner with a short, the home taken or ignored, a folder or a link that cannot be made), raises
    `Refused`, and the writer writes nothing; a file that was not at the home of `old` is written as before."""
    got = _where(hub, address)
    if got is None:
        return None
    root, top, name = got
    with _name_lock(top, name), folders_lock(top, name):
        rel, n = _one(top, name)
        if n != 1:
            return None
        strict = home(hub, root, name, old) == rel
        gone = _move(hub, root, top, rel, name, address, text=new, strict=strict)
        if gone is not None:
            _tidy(top, gone)
    return gone


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
    with _name_lock(top, name):
        rel, n = _one(top, name)
        if n > 1:
            _twice(hub, address, n)
            return None
        gone = None
        if n:
            # The file's lock before the folders', as a writer that moves holds them (`ahead`): one order (9.11),
            # so a path that turns into a link to another sheaf's file meanwhile waits for that writer, and is
            # then looked at again.
            with file_lock(top / rel), folders_lock(top, name):
                if _one(top, name) == (rel, 1):
                    gone = _move(hub, root, top, rel, name, address)
                    if gone is not None:
                        _tidy(top, gone)
        if gone is None:
            return None
        # Rendered and committed under the name's lock (9.11), after the folders' is let go: no other writer of
        # the name comes between the move and its commit.
        hub.wrote(address, moved=True)
        if commit:
            if member is None and by is None:
                hub.committed(address, what="move", gone=gone, author=commits_mod.Author(*commits_mod.COMMITTER))
            else:
                hub.committed(address, member, "move", by, gone=gone)
    return gone


def _move(hub, root, top: Path, rel: str, name: str, address: str, text: str | None = None,
          strict: bool = False) -> str | None:
    """Link the file at `rel` into the home of its text, or of `text` when given (`ahead`), then unlink it at `rel`:
    the path it left, or None. The caller holds the name's lock, the file's and then the folders'. A move that
    cannot be made is a `place-refused` row, or with `strict` (`ahead`) raises `Refused`."""
    def refused(why: str):
        if strict:
            raise Refused(why)
        gone = None
        if rel == name and text is not None and visibility.effective(visibility.front_matter(text)) != "project":
            gone = _to_quarantine(top, sfd, sname, name)      # never at the project's path (#61)
        _refused(hub, address, why, gone is not None or quarantined(rel))
        return gone
    try:
        sfd, sname = _folder_of(top, rel)
    except OSError as e:
        return refused(f"its folder could not be opened ({e.strerror})") if strict else None
    try:
        try:
            st = os.stat(sname, dir_fd=sfd, follow_symlinks=False)
            if not stat.S_ISREG(st.st_mode):
                return None         # a link stays where it is written: the sheaf it names is placed itself
            if text is None:
                fd = os.open(sname, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=sfd)
                with os.fdopen(fd, "rb") as f:
                    text = f.read().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return None             # gone, or not a text the hub reads: nothing to judge it on
        target = home(hub, root, name, text)
        if target is None:
            return refused(NO_SHORT)
        if target == rel:
            return None
        if ignores(top, target):
            return refused(IGNORED)
        try:
            dfd, dname = make_folders(top, target)
        except OSError as e:
            return refused(f"its folder could not be made ({e.strerror})")
        try:
            os.link(sname, dname, src_dir_fd=sfd, dst_dir_fd=dfd, follow_symlinks=False)
        except FileExistsError:
            return refused(f"{target} is taken")
        except OSError as e:
            return refused(f"it could not be moved ({e.strerror})")
        finally:
            os.close(dfd)
        os.unlink(sname, dir_fd=sfd)
    finally:
        os.close(sfd)
    return rel


def _to_quarantine(top: Path, sfd: int, sname: str, name: str) -> str | None:
    """Link the file `sname` in the folder `sfd`, the sheaf named `name` at the project's path, into its quarantine,
    never over anything, then unlink it: `name`, the path it left, or None when it stays (a quarantine the repo
    ignores, taken, or a folder that cannot be made). The caller holds the name's lock, the file's and the
    folders'."""
    target = quarantine(name)
    if ignores(top, target):
        return None
    try:
        dfd, dname = make_folders(top, target)
    except OSError:
        return None
    try:
        os.link(sname, dname, src_dir_fd=sfd, dst_dir_fd=dfd, follow_symlinks=False)
    except OSError:
        return None
    finally:
        os.close(dfd)
    os.unlink(sname, dir_fd=sfd)
    return name


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
