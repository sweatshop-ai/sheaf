"""
sheafmd.beneath — the one open of a file under a root (SPEC 9.11, rule A).

    open_beneath(top, rel)         an `Opened`: the file's descriptor, and the identity of every directory the walk went through
    Opened.text()                  the file's text, read from that descriptor
    Opened.write(text)             the new text, written through the folder descriptor of the walk and renamed over the file
    Opened.close()

A path is resolved once. The kernel (`openat2` with RESOLVE_BENEATH, no other flag) or a walk of our own
(`openat` with O_NOFOLLOW, one name at a time) opens the file below the descriptor of the root's folder, and a link
that stays inside the root is followed while one that leaves it is refused (SPEC 8.3). What is judged (a private
root, SPEC 9.11) is the object that was opened, by (st_dev, st_ino) of the descriptors of that walk, and what is read
or written is that descriptor and no path. `FALLBACK` forces the walk of our own, as a kernel without `openat2` does.
"""
import ctypes
import errno
import os
import stat
from collections import deque

FALLBACK = False                  # tests: take the walk of our own although the kernel has openat2
MAX_HOPS = 40                     # links followed in one walk; more is a loop
_RESOLVE_NO_SYMLINKS = 0x04
_RESOLVE_BENEATH = 0x08
_SYS_OPENAT2 = 437                # the same number on every architecture that has it


class Escapes(FileNotFoundError):
    """The path leaves the root, loops, or names a place that is the hub's own: read as a file that is not there."""

    def __init__(self, rel):
        super().__init__(errno.ENOENT, "outside the root, a loop, or not served", rel)


class Linked(FileNotFoundError):
    """A file with more than one name: a hard link can put a private file under a name that no folder's identity
    judges, so no door opens one (SPEC 9.11). Read as a file that is not there."""

    def __init__(self, rel):
        super().__init__(errno.ENOENT, "more than one name for the file", rel)


OWN = (".sheaf", ".git")          # names no walk goes through, in a path or in the target of a link (SPEC 8.2)


class _How(ctypes.Structure):
    _fields_ = [("flags", ctypes.c_uint64), ("mode", ctypes.c_uint64), ("resolve", ctypes.c_uint64)]


def _libc():
    try:
        return ctypes.CDLL(None, use_errno=True)
    except OSError:
        return None


_LIBC = _libc()
_HAS_OPENAT2 = None               # None until tried: True or False after the first call


def _openat2(dirfd: int, rel: str, flags: int, resolve: int = _RESOLVE_BENEATH) -> int:
    """The descriptor of `rel` below `dirfd`, the kernel refusing anything that leaves it (EXDEV). NotImplementedError
    where there is no such call."""
    global _HAS_OPENAT2
    if _HAS_OPENAT2 is False or _LIBC is None or not hasattr(_LIBC, "syscall"):
        raise NotImplementedError
    how = _How(flags | os.O_CLOEXEC, 0, resolve)
    fd = _LIBC.syscall(_SYS_OPENAT2, dirfd, rel.encode(), ctypes.byref(how), ctypes.sizeof(how))
    if fd < 0:
        err = ctypes.get_errno()
        if err in (errno.ENOSYS, errno.EPERM) and _HAS_OPENAT2 is None:
            _HAS_OPENAT2 = False
            raise NotImplementedError
        raise OSError(err, os.strerror(err), rel)
    _HAS_OPENAT2 = True
    return fd


def ident(fd: int) -> tuple:
    st = os.fstat(fd)
    return (st.st_dev, st.st_ino)


class Opened:
    """A file opened below a root. `dirs` are the identities of the root's folder, of its parents and of every folder the
    walk went into (the walk of our own sees them all, `openat2` the root's and the file's); `file` is the file's."""

    def __init__(self, fd, file, dirs, parent, name, how, top, rel):
        self.fd, self.file, self.dirs, self._parent, self.name, self.how = fd, file, dirs, parent, name, how
        self.top, self.rel = top, rel

    def idents(self) -> list:
        return [*self.dirs, self.file]

    def bytes(self) -> bytes:
        with os.fdopen(os.dup(self.fd), "rb") as f:
            f.seek(0)
            return f.read()

    def text(self) -> str:
        return self.bytes().decode("utf-8")

    def write(self, text: str):
        """Replace the file with `text` whole, through the folder descriptor of the walk: a sibling made there and
        renamed over the name, only while the name still holds the file that was opened."""
        pfd, name = self._folder()
        tmp = f".{name}.sheaf-tmp"
        try:
            os.unlink(tmp, dir_fd=pfd)
        except FileNotFoundError:
            pass
        mode = stat.S_IMODE(os.fstat(self.fd).st_mode)
        out = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=pfd)
        try:
            with os.fdopen(out, "wb") as f:
                f.write(text.encode("utf-8"))
                f.flush()
                os.fchmod(f.fileno(), mode)
                os.fsync(f.fileno())
                made = ident(f.fileno())
            sib = os.stat(tmp, dir_fd=pfd, follow_symlinks=False)       # a folder writer may swap the sibling while it is written
            if (sib.st_dev, sib.st_ino) != made:
                raise OSError(errno.ESTALE, "the new text was swapped out of its place", tmp)
            st = os.stat(name, dir_fd=pfd, follow_symlinks=False)
            if (st.st_dev, st.st_ino) != self.file:
                raise OSError(errno.ESTALE, "the file is no longer the one that was opened", name)
            os.rename(tmp, name, src_dir_fd=pfd, dst_dir_fd=pfd)
        except BaseException:
            try:
                os.unlink(tmp, dir_fd=pfd)
            except OSError:
                pass
            raise

    def _folder(self):
        """(descriptor of the folder holding the file, its name). The walk of our own has it; after `openat2` the walk is
        made now, and its file must be the one `openat2` opened."""
        if self._parent is None:
            w = _walk(self.top, self.rel)
            try:
                if w[1] != self.file:
                    raise OSError(errno.ESTALE, "the file is no longer the one that was opened", self.rel)
                self._parent, self.name = w[3], w[4]
            finally:
                os.close(w[0])
        return self._parent, self.name

    def close(self):
        for fd in (self.fd, self._parent):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        self.fd = self._parent = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _root_dirs(rootfd: int) -> list:
    """The identities of the root's folder and of its parents up to `/`, by `..` from the descriptor."""
    out, fd = [ident(rootfd)], os.dup(rootfd)
    try:
        while True:
            up = os.open("..", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = up
            here = ident(fd)
            if here == out[-1]:
                return out
            out.append(here)
    finally:
        os.close(fd)


def _walk(top, rel: str, meta: bool = False):
    """(file fd, file identity, identities of the folders on the way, folder fd, name): one name at a time, each
    opened from the descriptor above it with O_NOFOLLOW. A link is read with `readlinkat` and its target walked by us,
    from the root or from the folder of the link, so that it never leaves the root: `..` past it is refused, and so is
    a name of `OWN` anywhere on the way. An absolute target is made relative to the root and walked from it."""
    top = os.fspath(top)
    base = os.path.realpath(top)
    rootfd = os.open(top, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    stack = [rootfd]                    # the folders from the root down: their descriptors
    seen = _root_dirs(rootfd)
    pending = deque(rel.split("/"))
    hops = 0
    try:
        while pending:
            name = pending.popleft()
            if name in ("", "."):
                continue
            if name in OWN:
                raise Escapes(rel)
            if name == "..":
                if len(stack) == 1:
                    raise Escapes(rel)
                os.close(stack.pop())
                continue
            last = not pending
            while True:
                try:
                    try:
                        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | (0 if last else os.O_DIRECTORY),
                                     dir_fd=stack[-1])
                    except PermissionError:
                        if not (meta and last):
                            raise
                        # a file that cannot be read still has an identity: a descriptor that reads nothing
                        fd = os.open(name, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=stack[-1])
                except OSError as e:
                    if e.errno not in (errno.ELOOP, errno.ENOTDIR):
                        raise
                    try:
                        target = os.readlink(name, dir_fd=stack[-1])
                    except OSError as e2:
                        if e2.errno == errno.EINVAL and e.errno == errno.ELOOP and (hops := hops + 1) <= MAX_HOPS:
                            continue           # it stopped being a link between the two calls: open it again
                        raise e if e2.errno in (errno.ENOENT, errno.EINVAL) else e2
                    hops += 1
                    if hops > MAX_HOPS:
                        raise Escapes(rel)
                    if target.startswith("/"):          # from the root: a place outside it comes out as `..`, refused above
                        while len(stack) > 1:
                            os.close(stack.pop())
                        target = os.path.relpath(os.path.normpath(target), base)
                    pending.extendleft(reversed(target.split("/")))
                    break
                if last:
                    st = os.fstat(fd)
                    if not stat.S_ISREG(st.st_mode):
                        os.close(fd)
                        raise OSError(errno.EISDIR, "not a file", name)
                    if st.st_nlink > 1:
                        os.close(fd)
                        raise Linked(rel)
                    parent = os.dup(stack[-1])
                    return fd, (st.st_dev, st.st_ino), seen, parent, name
                stack.append(fd)
                seen.append(ident(fd))
                break
        raise OSError(errno.ENOENT, "no file", rel)
    finally:
        for fd in stack:
            os.close(fd)


def open_beneath(top, rel: str, meta: bool = False) -> Opened:
    """`rel` (`/` separators) below the folder `top`, opened for reading. `meta`: a file that cannot be read is opened
    all the same, by a descriptor that reads nothing (`O_PATH`), for what only its identity is asked. OSError when it is not a file below it:
    missing, a link that leaves the root, a loop, a folder. The folder `top` itself is opened by its name once, and
    every judgement after that is of descriptors."""
    top = os.fspath(top)
    if not FALLBACK:
        rootfd = os.open(top, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            if any(n in OWN for n in rel.split("/")):
                raise Escapes(rel)
            try:
                # No link at all, first: the kernel alone then decides, and every name of the path is the one checked above.
                try:
                    fd = _openat2(rootfd, rel, os.O_RDONLY, _RESOLVE_BENEATH | _RESOLVE_NO_SYMLINKS)
                except PermissionError:
                    if not meta:
                        raise
                    fd = _openat2(rootfd, rel, os.O_PATH, _RESOLVE_BENEATH | _RESOLVE_NO_SYMLINKS)
            except NotImplementedError:
                pass
            except OSError as e:
                if e.errno not in (errno.ELOOP, errno.EXDEV):   # a link on the way: our walk follows it inside the root,
                    raise                                       # names what it goes through, and refuses what leaves
            else:
                st = os.fstat(fd)
                if not stat.S_ISREG(st.st_mode):
                    os.close(fd)
                    raise OSError(errno.EISDIR, "not a file", rel)
                if st.st_nlink > 1:
                    os.close(fd)
                    raise Linked(rel)
                return Opened(fd, (st.st_dev, st.st_ino), _root_dirs(rootfd), None, None, "openat2", top, rel)
        finally:
            os.close(rootfd)
    fd, file, dirs, parent, name = _walk(top, rel, meta)
    return Opened(fd, file, dirs, parent, name, "walk", top, rel)
