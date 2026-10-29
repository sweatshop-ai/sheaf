"""The Source file: the .md a page is rendered from, and the one way to write it.

The hub, the CLI and an Ask job are separate processes. A Python lock inside one
of them protects nothing against the others, so every write takes an exclusive
flock across read, hash check and replace. The lock file lives in the runtime
folder, keyed by the document's path, so no dotfile appears next to the .md.
"""
import errno
import hashlib
import os
import secrets
import stat
import tempfile
import time
from pathlib import Path

from . import paths

try:
    import fcntl
except ImportError:            # Windows: the static render never writes
    fcntl = None


class StaleError(Exception):
    def __init__(self, message: str = "", code: str | None = None):
        super().__init__(message)
        self.code = code             # what a page tests, in place of the words (SPEC 8.5)


STAMP_FORMAT = "%Y-%m-%dT%H:%M:%S%z"    # the time the hub and the CLI write down, to the second with the offset


def md_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def now() -> str:
    """The time a comment or reply is stamped with."""
    return time.strftime("%Y-%m-%dT%H:%M")


def lock_key(md_path) -> str:
    """First 12 hex of sha1 of the absolute path, links resolved: a link to a .md
    and the .md itself are one document and take one lock."""
    return hashlib.sha1(str(Path(md_path).resolve()).encode()).hexdigest()[:12]


def _lock_path(md_path):
    return paths.locks_dir() / (lock_key(md_path) + ".lock")


def _legacy_lock_path(md_path):
    """The lock render-doc servers take, `<tempdir>/render-doc/locks/<same key>.lock`.

    Servers of the tool this one replaces may still be alive and write the same .md, so
    while their folder exists update_file takes their lock too, after its own. The code
    can go once none of them runs."""
    d = Path(tempfile.gettempdir()) / "render-doc" / "locks"
    return d / (lock_key(md_path) + ".lock") if d.is_dir() else None


def _open_lock(path):
    # 0600: a lock file is the user's own, and the folder is theirs alone.
    return os.fdopen(os.open(path, os.O_RDWR | os.O_CREAT, 0o600), "a+")


class file_lock:
    def __init__(self, md_path):
        self.paths = [_lock_path(md_path)]
        if (legacy := _legacy_lock_path(md_path)):
            self.paths.append(legacy)
        self.files = []

    def __enter__(self):
        try:
            for p in self.paths:
                try:
                    f = _open_lock(p)
                except OSError:
                    if p is self.paths[0]:
                        raise
                    continue        # a legacy folder that is not ours: nothing of ours to wait for
                self.files.append(f)
                if fcntl:
                    fcntl.flock(f, fcntl.LOCK_EX)
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *a):
        for f in reversed(self.files):
            try:
                if fcntl:
                    fcntl.flock(f, fcntl.LOCK_UN)
            finally:
                f.close()
        self.files = []


# Windows has no O_NOFOLLOW, so a look there would follow a link, and nothing runs sheaf on it in a
# test: it replaces as before, without the looks.
CHECKS_THE_NAMES = os.name != "nt"


def _holds_bytes(name: Path, data: bytes) -> bool:
    """Does the name hold a regular file, not a link, whose bytes are `data`? Opened without
    waiting, so a pipe put at the name answers no instead of hanging the write."""
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError:
        return False
    try:
        regular = stat.S_ISREG(os.fstat(fd).st_mode)
    except OSError:
        regular = False
    if not regular:
        os.close(fd)
        return False
    with os.fdopen(fd, "rb") as f:
        return f.read(len(data) + 1) == data


def _replace_if_ours(tmp: Path, target: Path, data: bytes):
    """os.replace(tmp, target), where tmp was written with `data` and closed: refused when tmp's
    name no longer holds those bytes in a regular file, not a link, and failed when target's does
    not just after.

    By the bytes, not by the inode: the file is closed before the rename, so that an error only the
    close reports (an upload that failed, on an rclone mount) comes before the document is touched;
    once closed, its inode number can pass to a file made at its name; and some file systems (an
    rclone mount) number a file by its name. A file of someone else's holding exactly those bytes
    costs nothing."""
    if not _holds_bytes(tmp, data):
        raise OSError(f"{tmp} was replaced while the new text was written to it, "
                      f"so {target} is left as it was")
    os.replace(tmp, target)
    if not _holds_bytes(target, data):
        raise OSError(f"{target} is not the file just written (its folder changed "
                      f"during the write), so the new text is not in it")


def _write_atomic(p: Path, text: str):
    """Write text to p through a hidden sibling, `.<name>.sheaf-tmp`, then os.replace.

    The sibling is made next to the path's TARGET, not next to the path: when the
    .md is a symlink, os.replace on the link would swap the link itself for a
    regular file and leave the real document untouched. This is a deliberate change
    from the tool this one replaces, which did exactly that. The original's mode is put on
    the sibling before the replace, so the file never shows up with another one.

    Whatever sits at the sibling's name is removed first and the sibling is created with
    O_EXCL|O_NOFOLLOW: every sheaf writer holds the flock, so the name is nobody else's of
    sheaf, and a link planted there (by someone who can write the folder) is neither
    followed nor kept: the open fails if one appears between the unlink and the open.

    The replace takes names, and a folder writer can swap the sibling after the open too, so
    the sibling's name must still hold the text written just before the replace, and the
    target's just after; otherwise the write fails (an OSError) rather than answer as if the
    text were in the document. That narrows the window and cannot close it (SPEC 7.1, 9.1).
    On Windows the replace is made as before."""
    target = p.resolve()
    tmp = target.with_name("." + target.name + ".sheaf-tmp")
    mode = stat.S_IMODE(target.stat().st_mode)
    try:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode)
        data = text.encode("utf-8")
        with os.fdopen(fd, "wb") as f:
            os.fchmod(f.fileno(), mode)        # open() applies the umask
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if CHECKS_THE_NAMES:
            _replace_if_ours(tmp, target, data)
        else:
            os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def update_file(md_path, change, expected_hash=None, move=None):
    """Apply change(text) -> new text under the lock. Returns (old, new).

    With expected_hash, the check happens inside the lock: a write that lands
    between a caller's read and this one is refused, never overwritten.
    The new text goes through a sibling temp file, so an interrupted write
    cannot truncate the document.

    `move(text, new)`, called under the lock before a write that changes the text, may move the
    file (a sheaf going to the home of its new text, SPEC 9.11) and give the path it is at now:
    the new text is written there, under that path's lock too."""
    p = Path(md_path)
    with file_lock(p):
        text = p.read_text(encoding="utf-8")
        if expected_hash and md_hash(text) != expected_hash:
            raise StaleError("the .md changed on disk since this page was rendered - "
                             "reload the document before saving, or your edit would "
                             "overwrite that change")
        new = change(text)
        if new != text:
            q = move(text, new) if move is not None else None
            if q is None:
                _write_atomic(p, new)
            else:
                with file_lock(q):
                    _write_atomic(Path(q), new)
        return text, new


def create_file(top, rel: str, text: str):
    """Write the new file `rel` (`/` separators, every folder of it existing) under the folder
    `top`, whole, and never over anything (SPEC 12, `create`).

    Each folder is opened from the one above it without following a link, so a link on the way
    is refused (an OSError) wherever it points, and a folder swapped for a link after a check
    cannot carry the write elsewhere. The text goes into a hidden sibling first and is linked into
    place: a reader never sees half a page, and the link fails (FileExistsError) when the name is
    taken by anything, a dangling link included, even one that appeared a moment ago. The file gets
    the mode the umask gives a new file. A missing folder is FileNotFoundError."""
    fd, name = _folder_of(top, rel)
    try:
        tmp = f".{name}.sheaf-new-{secrets.token_hex(6)}"
        out = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o666, dir_fd=fd)
        try:
            with os.fdopen(out, "wb") as f:
                f.write(text.encode("utf-8"))
                f.flush()
                os.fsync(f.fileno())
            os.link(tmp, name, src_dir_fd=fd, dst_dir_fd=fd)
        finally:
            try:
                os.unlink(tmp, dir_fd=fd)
            except OSError:
                pass
    finally:
        os.close(fd)


def check_create(top, rel: str):
    """Raise what `create_file(top, rel, …)` would raise for its path, writing nothing: FileExistsError when the
    name is taken by anything, a dangling link included, and the OSError of its walk for a missing folder or a
    link on the way. So a create refused for another reason can answer as the path alone would."""
    fd, name = _folder_of(top, rel)
    try:
        try:
            os.stat(name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        raise FileExistsError(errno.EEXIST, "File exists", rel)
    finally:
        os.close(fd)


def _folder_of(top, rel: str, make: bool = False):
    """(fd of the folder of `rel` under `top`, the file's name): each folder opened from the one above it
    without following a link, so a link on the way is an OSError wherever it points. With `make`, a missing
    folder is made on the way, as the umask gives a new folder, and then opened as any other."""
    parts = rel.split("/")
    fd = os.open(top, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for seg in parts[:-1]:
            if make:
                try:
                    os.mkdir(seg, 0o777, dir_fd=fd)
                except FileExistsError:
                    pass                # there already, or made meanwhile: opened as any other, a link refused
            inner = os.open(seg, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = inner
    except BaseException:
        os.close(fd)
        raise
    return fd, parts[-1]


class Source:
    """A markdown file as the library API sees it (SPEC 16).

    `read()` gives the text and its hash; `update()` applies a change under the file
    lock, and with `expected_hash` refuses (StaleError) a write that would overwrite
    what landed in between."""

    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        text = self.path.read_text(encoding="utf-8")
        return text, md_hash(text)

    def update(self, change, expected_hash=None):
        return update_file(self.path, change, expected_hash)
