"""
sheafmd.paths — the folders sheaf keeps things in (SPEC 4.1).

    state    diagnostics, versions, the hub's own files
    config   config.toml
    cache    fonts, downscaled images
    runtime  lock files, hub sockets

`exists`, `is_dir` and `is_file` tell a path that is not there from one that cannot be
looked at, which pathlib's own no longer does from Python 3.14 on.

These are functions, not constants, so a test or a development hub that sets
SHEAF_HOME or an XDG variable after import is honoured. SHEAF_HOME replaces
state, config and cache, never the runtime folder: a development hub and the
daily CLI must lock the same .md through the same file.
"""
import base64
import binascii
import errno
import os
import stat
import sys
import time
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:            # Windows: no flock
    fcntl = None


class PathError(Exception):
    pass


def _home() -> Path | None:
    h = os.environ.get("SHEAF_HOME")
    return Path(h).expanduser() if h else None


def _xdg(var: str, fallback: str) -> Path:
    v = os.environ.get(var)
    return (Path(v) if v and os.path.isabs(v) else Path.home() / fallback) / "sheaf"


def state_dir() -> Path:
    if h := _home():
        return h / "state"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "sheaf" / "state"
    return _xdg("XDG_STATE_HOME", ".local/state")


def config_file() -> Path:
    if h := _home():
        return h / "config.toml"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "sheaf" / "config.toml"
    return _xdg("XDG_CONFIG_HOME", ".config") / "config.toml"


def cache_dir() -> Path:
    if h := _home():
        return h / "cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "sheaf"
    return _xdg("XDG_CACHE_HOME", ".cache")


def runtime_dir() -> Path:
    """Not under SHEAF_HOME. On macOS never under Application Support: a Unix
    socket path with a space in it can pass the 104-byte limit."""
    v = os.environ.get("XDG_RUNTIME_DIR")
    if sys.platform != "darwin" and v and os.path.isabs(v):
        return Path(v) / "sheaf"
    return Path(f"/tmp/sheaf-{os.getuid()}")


def private_dir(path: Path) -> Path:
    """Create path as a folder of mode 0700 that this user owns, and return it.

    The runtime folder can fall back to /tmp, where another local user could have
    made the same name first: a folder that is a link or belongs to someone else
    is refused, never used."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = os.lstat(path)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise PathError(f"{path} is not a folder of yours; sheaf will not use it")
    if stat.S_IMODE(st.st_mode) != 0o700:
        os.chmod(path, 0o700)
    return path


def _stat(path: str | os.PathLike) -> os.stat_result | None:
    """The path's stat, or None when it is not there: what pathlib's `exists` took for absent up to
    Python 3.13 (missing, a non-folder on the way, a bad descriptor, a link loop, a NUL in the
    name). Anything else raises, as `open` does, a folder on the way that this account may not
    enter among it: from 3.14 on, pathlib's `exists`, `is_dir` and `is_file` say False there, and
    a folder that cannot be looked at would pass for gone."""
    try:
        return os.stat(path)
    except OSError as e:
        if e.errno in (errno.ENOENT, errno.ENOTDIR, errno.EBADF, errno.ELOOP):
            return None
        raise
    except ValueError:
        return None


def exists(path: str | os.PathLike) -> bool:
    """Whether the path is there (a link counts by where it points); raises as `_stat` does."""
    return _stat(path) is not None


def is_dir(path: str | os.PathLike) -> bool:
    """Whether the path is a folder (a link to one counts); raises as `_stat` does."""
    st = _stat(path)
    return st is not None and stat.S_ISDIR(st.st_mode)


def is_file(path: str | os.PathLike) -> bool:
    """Whether the path is a regular file (a link to one counts); raises as `_stat` does."""
    st = _stat(path)
    return st is not None and stat.S_ISREG(st.st_mode)


def hub_socket(port: int) -> Path:
    """`<runtime>/hub-<port>.sock`: the address Tell messages come from (SPEC 11.4)."""
    return runtime_dir() / f"hub-{port}.sock"


def locks_dir() -> Path:
    """`<runtime>/locks/`: one flock file per .md (SPEC 4.2)."""
    return private_dir(private_dir(runtime_dir()) / "locks")


# ── the hub key (SPEC 4.2, 9.3) ─────────────────────────────────────────────

def key_file() -> Path:
    return state_dir() / "hub.key"


def key_bytes(text: str) -> bytes:
    """The 32 bytes a key line stands for. Every HMAC uses these, never the text."""
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError, TypeError):
        raw = b""
    if len(raw) != 32 or base64.urlsafe_b64encode(raw).rstrip(b"=").decode() != text:
        raise PathError("hub.key does not hold a hub key (32 random bytes, base64url, one line)")
    return raw


def _read_key(f: Path) -> str:
    # A reader can arrive between another process creating the file and writing the
    # key into it: wait a moment for the line before calling the file wrong.
    for attempt in range(20):
        text = f.read_text(encoding="ascii", errors="replace").strip()
        if text:
            break
        time.sleep(0.05)
    try:
        key_bytes(text)
    except PathError:
        raise PathError(f"{f} does not hold a hub key; sheaf will not replace it. "
                        "Remove it yourself if it is not worth keeping") from None
    if stat.S_IMODE(f.stat().st_mode) != 0o600:
        os.chmod(f, 0o600)
    return text


def ensure_key() -> str:
    """The hub key, made on first use: 32 random bytes, base64url, one line, mode 0600.

    Every command and the hub call this before anything else, so a command never starts
    a hub before the key exists. The file is opened with O_CREAT|O_EXCL: two processes
    that race both end up with the one key that won. A file that is there but is not a
    key is refused, never overwritten."""
    d = private_dir(state_dir())
    f = d / "hub.key"
    try:
        fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return _read_key(f)
    key = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    with os.fdopen(fd, "w", encoding="ascii") as out:
        out.write(key + "\n")
        out.flush()
        os.fsync(out.fileno())
    return key


@contextmanager
def key_lock():
    """Held while a hub reads its key and takes its port, and while `sheaf rotate` replaces the
    key on a machine with no hub on it: a hub never starts on a key that a finished rotation has
    already replaced. A hub that is up holds nothing: it is rotated through the hub."""
    f = open(os.open(locks_dir() / "hub-key.lock", os.O_RDWR | os.O_CREAT, 0o600), "a+")
    try:
        if fcntl:
            fcntl.flock(f, fcntl.LOCK_EX)
        yield
    finally:
        f.close()


def rotate_key() -> str:
    """Replace the hub key with a new one and return it (SPEC 9.3). The new key is written whole
    to a file of its own, flushed to disk, then moved over `hub.key` in one step, so a reader
    sees the old key or the new one and never half of either. A file that is there but is not a
    key is refused, as `ensure_key` refuses it. The key is returned for the hub to switch to
    and for nothing else: no caller prints or logs it."""
    d = private_dir(state_dir())
    f = d / "hub.key"
    if f.exists():
        _read_key(f)
    key = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    tmp = d / f".hub.key.{os.getpid()}.new"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as out:
            out.write(key + "\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, f)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return key
