"""
sheafmd.hub.state — what the hub keeps in the state folder (SPEC 4.2): small JSON files
(`roots.json`, `docs.json`, `seen.json`) and the texts it handed pages, for the merge (7.4).

Every file is written whole through a hidden sibling and `os.replace`, mode 0600, in a
folder of mode 0700.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import stat
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .. import diagnostics, paths
from ..source import STAMP_FORMAT, md_hash
from .auth import (CLIENT_MAX, MAX_TOKEN, TOKEN_PREFIX, agent_name, clean_display, client_ok, new_token,
                   token_hash)

try:
    import fcntl
except ImportError:            # Windows: no flock; the token file is written by one process at a time
    fcntl = None

VERSIONS_KEPT = 60              # per document
VERSIONS_MAX_AGE = 7 * 86400    # seconds
PINS_KEPT = 16                  # per member of each document: the versions their pages keep (`pin`)
PINS_MAX_AGE = 7 * 86400        # seconds since a page last pinned it
_HASH_RE = re.compile(r"[0-9a-f]{16}")
_ADDRESS_FILE = "address"       # in each versions folder: the address it is the key of
_PINS_DIR = "pins"              # in each versions folder: the versions pages keep
_MEMBER_PINS = "m-"             # in `pins/`: the prefix of a member's own folder (`member_key`)
_PIN_CLOCK_AHEAD = 60           # seconds a pin time may lie ahead of this clock (another clone's)
PINNED_AT = _PINNED_AT = ".at"              # in a root's own store, beside a pin `<hash>.md`: when it was last pinned, ns since the epoch
_LOCAL_ONLY = f"*{_PINNED_AT}\n.gitignore\n"   # `.gitignore` of a root's own store: each hub's pin times stay out of git
INSIDE = Path(".sheaf") / "versions"    # a root's own versions store, inside it (7.4)


def inside_dir(path: Path) -> Path:
    """A folder of a root's own versions store (7.4), made when missing and returned. It is made as the
    umask gives a new folder (`mkdir 0777`), so a setgid parent passes its group on, and an existing one is
    never chmodded: the root's modes are the root's (a clone shared with a group), not the hub's to reset.
    A link, or a folder of someone else, is refused as `paths.private_dir` refuses it."""
    try:
        os.mkdir(path, 0o777)
    except FileExistsError:
        st = os.lstat(path)
        if not stat.S_ISDIR(st.st_mode) and not (stat.S_ISLNK(st.st_mode) and path.is_dir()):
            raise               # a file or a dangling link stands there: an OSError, as `mkdir` gave before
    st = os.lstat(path)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise paths.PathError(f"{path} is not a folder of yours; sheaf will not use it")
    return path


def write_text_private(path: Path, text: str, inside: bool = False):
    """Write `text` to `path`: complete or not at all, 0600. The hidden sibling is made new: whatever
    stands at its name (a link planted in a root's versions store, 7.4) goes first, never written
    through. `inside`: the file is one of a root's versions store, whose folder keeps the modes it has."""
    path = Path(path)
    (inside_dir if inside else paths.private_dir)(path.parent)
    tmp = path.with_name("." + path.name + ".tmp")
    try:
        os.unlink(tmp)
    except FileNotFoundError:
        pass
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@contextmanager
def file_locked(name: str):
    """Hold the flock `<runtime>/locks/<name>` across a read-modify-write of a file that more than
    one process changes. One lock is not held twice by one process: a second `with` on the same name
    inside the first would wait on itself."""
    f = open(os.open(paths.locks_dir() / name, os.O_RDWR | os.O_CREAT, 0o600), "a+")
    try:
        if fcntl:
            fcntl.flock(f, fcntl.LOCK_EX)
        yield
    finally:
        f.close()


def _drop(version: Path):
    """The version file `version` gone, with the pin time beside it if it has one."""
    for f in (version, version.with_suffix(_PINNED_AT)):
        try:
            f.unlink()
        except OSError:
            pass


def read_small(path: Path, most: int = 4096) -> str | None:
    """The text of `path`, a regular file of at most `most` bytes reached without a link, or None: never a link's
    target, never a wait on a FIFO. For a file of a root's versions store, which may hold traps (7.4)."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                return None
            data = f.read(most + 1)
        return data.decode("utf-8") if len(data) <= most else None
    except (OSError, ValueError):
        return None


def write_json(path: Path, obj):
    write_text_private(path, json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n")


def read_json(path: Path, default, kind=None, aside=True):
    """The JSON in `path`, or `default` when there is none. A file that cannot be read as
    JSON of the expected kind (the type of `default`, unless `kind` says another) is set
    aside as `<name>.corrupt` and read as the default: the hub starts anyway, and what was
    in the file is still there to look at; a `file-set-aside` diagnostics row says where it went. `aside=False` reads it as the default and leaves it
    where it is: for a reader that must change nothing on disk."""
    path = Path(path)
    kind = kind or type(default)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, kind):
            return data
    except FileNotFoundError:
        return default
    except (ValueError, OSError):
        pass
    if not aside:
        return default
    aside_path = path.with_name(path.name + ".corrupt")
    try:
        os.replace(path, aside_path)
    except FileNotFoundError:
        pass  # another reader moved it first, and wrote the row
    except OSError as e:
        diagnostics.record("hub", "file-set-aside-failed", None, file=str(path), error=f"{type(e).__name__}: {e}")
    else:
        diagnostics.record("hub", "file-set-aside", None, file=str(path), moved_to=str(aside_path))
    return default


def member_key(member: str) -> str | None:
    """The folder in `pins/` of a member's pins: `m-` and the first 16 hex of the sha256 of their id, so the id is
    never a file name (a root's own store goes to git, 8.11). None for the hub's person (a request with no member
    id: the loopback port), whose pins are in `pins/` itself, where every pin went before the cap was per member:
    those are read as the hub's person's."""
    if not member:
        return None
    return _MEMBER_PINS + hashlib.sha256(member.encode("utf-8")).hexdigest()[:16]


def doc_key(address: str) -> str:
    """First 16 hex of the sha256 of `<root>/<path>`: the folder of that document's versions."""
    return hashlib.sha256(address.encode("utf-8")).hexdigest()[:16]


@dataclass
class _Claims:
    """Who put each hash in one document's versions folder while a late forget watches it (`Versions.watch`)."""
    watchers: set = field(default_factory=set)      # the forgotten documents whose `forget_texts` is still to come
    by_hash: dict = field(default_factory=dict)     # hash -> {writer, ...}; None is a writer that is no document


def times_out_of_git(store: Path):
    """Keep every pin time of a root's own store at `store` out of git, whether or not this hub has pinned there: the
    store's `.gitignore` is written unless it is a file of its own holding the hub's lines, and any other `.gitignore`
    in the store, which could say `!*.at`, goes (ticket 203 C, round 8). A clone gets no store `.gitignore` from git:
    the file ignores itself. Nothing is made when there is no store. Nothing is touched through `.sheaf` or a store
    that is a link or a folder of another account (7.4, rounds 9 and 10): `PermissionError`, since nothing then keeps
    pin times out. OSError: the caller must not stage the store."""
    for d in (store.parent, store):
        try:
            st = os.lstat(d)
        except FileNotFoundError:
            return
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
            raise PermissionError(f"{d.name} is not a folder of this account; its pin times cannot be kept out of git")
    if read_small(store / ".gitignore") != _LOCAL_ONLY:
        write_text_private(store / ".gitignore", _LOCAL_ONLY, True)
    for d, dirs, names in os.walk(store):
        if d != str(store) and ".gitignore" in names + dirs:
            p = Path(d) / ".gitignore"
            if not stat.S_ISDIR(os.lstat(p).st_mode):
                os.unlink(p)


class Versions:
    """Every text the hub handed a page, on disk, so a save against a page rendered before a
    restart still merges. `<state>/versions/<doc-key>/<hash>.md`, the newest 60 per document,
    nothing older than 7 days after `prune()` (run when the hub starts). Beside them, in `pins/`,
    the versions pages said they keep past a change of the file (`pin`): the newest 16 of each member
    (the hub's person's in `pins/`, a member's in `pins/<member_key>/`), none pinned last more than 7
    days before (`get` does not believe one, `prune()` deletes it). Each folder also holds `address`, the
    `<root>/<path>` it is the key of, so a whole root's folders can be found."""

    def __init__(self, root: Path | None = None, name: str = ""):
        """Without `root`, the store of the state folder. With it, the store of that root's own
        documents, inside it at `.sheaf/versions/` (7.4, `versions = "root"`), keyed by the path in the
        root, not the address: another hub, a clone's, names the root otherwise. `name` is the root's."""
        self._root, self._prefix = root, f"{name}/"

    # Between a document's `watch` (its root was forgotten, and the name may be another folder's at once) and its
    # `forget_texts`, who put each hash in that document's folder, by the folder's path: one file holds a text whatever
    # document stored it, and the late forget takes out only the texts the old document wrote (SPEC 8.2; ticket 182 L).
    # In memory only, the stored format is unchanged: both documents are of one hub run, and the record is open no
    # longer than that window. Shared by every store, since the forgotten document's store and the new document's are
    # two objects over one folder. No other process needs recording: one hub runs per OS user (8.1) and only it writes
    # the state folder's versions (`roots.forget_offline` runs when none does), and in a root's own store, which another
    # hub or a pull may write, `forget_texts` deletes nothing.
    _claims_lock = threading.Lock()
    _claims: dict = {}          # folder -> _Claims

    @property
    def dir(self) -> Path:
        if self._root is not None:
            return self._root / INSIDE
        return paths.state_dir() / "versions"

    def _key(self, address: str) -> str:
        """What the folder of `address` is named by, and what its `address` file holds."""
        if self._root is not None and address.startswith(self._prefix):
            return address[len(self._prefix):]
        return address

    def _folder(self, address: str) -> Path:
        return self.dir / doc_key(self._key(address))

    def _make_folder(self, address: str) -> Path:
        """`_folder`, made when it is not there yet, with its `address` file."""
        if self._root is not None:
            inside_dir(self._root / INSIDE.parent)   # `.sheaf` itself: never a link out of the root
        folder = self._dir(self._dir(self.dir) / doc_key(self._key(address)))
        named = folder / _ADDRESS_FILE
        if read_small(named) != self._key(address):     # a link, or a text planted there, is written over
            write_text_private(named, self._key(address), self._root is not None)
        return folder

    def _dir(self, path: Path) -> Path:
        """`path` as a folder of this store: private (0700) in the state folder, as it is in a root."""
        return paths.private_dir(path) if self._root is None else inside_dir(path)

    def _keep(self, folder: Path, text: str, newest: int, pinned: bool = False) -> str:
        """Write `text` under its hash in `folder` (or count it as written now), and keep the
        `newest` files there. Only a file named by a hash counts or is deleted here: anything else
        is not a version (`get` would not believe it) and takes no slot. A pin of a root's own store
        has its time in a file beside it (`_pinned_at`)."""
        h = md_hash(text)
        timed = pinned and self._root is not None
        if timed:                                   # first: a pin with no time is never believed
            self._times_out_of_git(folder)
            write_text_private(folder / f"{h}{_PINNED_AT}", str(int(time.time() * 1e9)), True)
        f = folder / f"{h}.md"
        if f.is_file():
            os.utime(f, follow_symlinks=False)
        else:
            write_text_private(f, text, self._root is not None)
        files = []
        for p in folder.glob("*.md"):
            if _HASH_RE.fullmatch(p.stem) and p.is_file():
                try:
                    at = self._pin_time(p) if pinned else p.stat().st_mtime_ns
                except OSError:
                    continue
                if timed and not at:
                    continue        # another clone's pin, pulled with no time here: theirs to trim, never this hub's (203 B)
                files.append((at, p.name, p))
        for _, _, p in sorted(files)[:-newest]:
            _drop(p)
        return h

    def _times_out_of_git(self, folder: Path):
        """Keep the pin times of a root's own store out of git before one is written in `folder`: the store's `.gitignore`
        is written again unless it is a file of its own holding the hub's lines (git reads no link, and other lines may
        not ignore `*.at`), and a `.gitignore` in a folder of the store between it and `folder`, which could say `!*.at`,
        goes (ticket 203 A). The store is the hub's: no other `.gitignore` belongs in it."""
        if read_small(self.dir / ".gitignore") != _LOCAL_ONLY:
            write_text_private(self.dir / ".gitignore", _LOCAL_ONLY, True)
        d = folder
        while d != self.dir and self.dir in d.parents:
            try:
                if not stat.S_ISDIR(os.lstat(d / ".gitignore").st_mode):    # a folder of that name is no ignore file
                    os.unlink(d / ".gitignore")
            except FileNotFoundError:
                pass
            d = d.parent

    def _pin_time(self, pin: Path) -> int:
        """When the pin `pin` was last pinned, in ns: its mtime in the state folder, the file beside it in a root's own
        store (`_pinned_at`)."""
        return self._pinned_at(pin) if self._root is not None else pin.stat().st_mtime_ns

    @staticmethod
    def _pinned_at(pin: Path) -> int:
        """When the pin `pin` of a root's own store was last pinned, in ns: the file beside it says, since the store goes to git
        (8.11) and a clone or checkout writes every file with its own time (ticket 192). That file is this hub's alone: the
        store's `.gitignore` keeps it out of git, so two clones pinning one version never conflict, and a pin another clone
        made is not believed here. None there, or no number: 0, a pin never believed; nor a time more than a minute to come."""
        try:
            at = int((read_small(pin.with_suffix(_PINNED_AT), 32) or "").strip())   # never a link or a FIFO (7.4)
        except ValueError:
            return 0
        return at if at <= (time.time() + _PIN_CLOCK_AHEAD) * 1e9 else 0          # a time to come is no age either

    def _claimed(self, address: str, keep, writer) -> str:
        """`keep()`, the write of a text in the folder of `address`, and, when a late forget watches that folder, the
        record that `writer` put its hash there (None: a writer that is no document, which no forget owns either). Under
        the claims' lock then, so that a forget never deletes between this write and its record. A folder no forget
        watches is written without the lock: a watch starts before any other document can write there (`watch`)."""
        folder = self._folder(address)
        if folder not in self._claims:
            return keep()
        with self._claims_lock:
            watched = self._claims.get(folder)
            h = keep()
            if watched is not None:
                watched.by_hash.setdefault(h, set()).add(writer)
            return h

    def put(self, address: str, text: str, writer=None) -> str:
        return self._claimed(address, lambda: self._keep(self._make_folder(address), text, VERSIONS_KEPT), writer)

    def pin(self, address: str, text: str, member: str = "", writer=None) -> str:
        """Keep `text` as a version a page of `member` keeps (the hub's person's: ""), apart from the newest 60,
        which writes from outside push out, and apart from the pins of every other member."""
        def keep():
            folder = self._dir(self._make_folder(address) / _PINS_DIR)
            key = member_key(member)
            return self._keep(folder if key is None else self._dir(folder / key), text, PINS_KEPT, pinned=True)
        return self._claimed(address, keep, writer)

    @staticmethod
    def _members(pins: Path) -> list[Path]:
        """The members' folders in `pins/`: never a link, which could reach out of the store (a root's is a clone)."""
        try:
            return sorted(m for m in pins.glob(f"{_MEMBER_PINS}*") if m.is_dir() and not m.is_symlink())
        except OSError:
            return []

    def _pinned(self, folder: Path, h: str) -> list[Path]:
        """Where a pin of `h` can be, in the document folder `folder`: the hub's person's, then each member's."""
        pins = folder / _PINS_DIR
        return [pins / f"{h}.md", *(m / f"{h}.md" for m in self._members(pins))]

    def get(self, address: str, h) -> str | None:
        """The text with hash `h`, among the newest or the pinned, or None. `h` comes from a
        request: nothing that is not 16 lowercase hex reaches the disk, and a file whose text
        does not hash to its name is not believed."""
        if not isinstance(h, str) or not _HASH_RE.fullmatch(h):
            return None
        folder = self._folder(address)
        stale = int((time.time() - PINS_MAX_AGE) * 1e9)
        for f in (folder / f"{h}.md", *self._pinned(folder, h)):
            try:
                if f.parent != folder and self._pin_time(f) < stale:
                    continue        # a pin past its age, before any prune (a root's own store is never pruned)
                text = f.read_text(encoding="utf-8")
            except (OSError, ValueError):
                continue
            if md_hash(text) == h:
                return text
        return None

    def texts(self, address: str) -> list[str]:
        """The newest versions of the document, oldest first, each only when it hashes to its name (as `get` believes it)."""
        found = []
        for p in self._folder(address).glob("*.md"):
            try:
                if _HASH_RE.fullmatch(p.stem) and p.is_file():
                    found.append((p.stat().st_mtime_ns, p.name, p))
            except OSError:
                pass
        out = []
        for _, _, p in sorted(found):
            try:
                text = p.read_text(encoding="utf-8")
            except (OSError, ValueError):
                continue
            if md_hash(text) == p.stem:
                out.append(text)
        return out

    def stamps(self, address: str) -> dict[str, int]:
        """The age of each version of the document, `{hash: mtime_ns}`, as `texts` orders them: what `take_back` gives back."""
        found = {}
        for p in self._folder(address).glob("*.md"):
            try:
                if _HASH_RE.fullmatch(p.stem) and p.is_file():
                    found[p.stem] = p.stat().st_mtime_ns
            except OSError:
                pass
        return found

    def unwatch(self, address: str, writer):
        """`writer`'s `watch` of the folder of `address` ends, and what it recorded there with it, as `forget_texts` ends it."""
        folder = self._folder(address)
        with self._claims_lock:
            watched = self._claims.get(folder)
            if watched is None:
                return
            watched.watchers.discard(writer)
            for h in [h for h, writers in watched.by_hash.items() if writers == {writer}]:
                del watched.by_hash[h]
            for writers in watched.by_hash.values():
                writers.discard(writer)
            if not watched.watchers:
                del self._claims[folder]

    def take_back(self, address: str, before: list[str], made: list[str], stamps: dict[str, int] | None = None, writer=None) -> None:
        """A landing that put the texts `made` among the newest versions of the document and did not land takes back those, and no
        more: a version of `made` that `before` (as `texts` gave them) did not hold goes, a version it pushed out of the newest
        comes back, and what someone else wrote meanwhile and the pinned ones are never touched. With `stamps` (as `stamps` gave
        them before) every version `before` held has its age again, the one a landing touched and the one it pushed out alike, so
        the order of the history and the days a version has left are the ones it had. With `writer` (the landing's `watch`, which
        its `put`s named) a text that another writer saved meanwhile has the same hash and stays; the watch ends here."""
        folder = self._folder(address)
        kept = {md_hash(t) for t in before}
        for h in {md_hash(t) for t in made} - kept:
            if writer is not None:
                with self._claims_lock:
                    watched = self._claims.get(folder)
                    if watched is not None and watched.by_hash.get(h, set()) - {writer}:
                        continue
            try:
                (folder / f"{h}.md").unlink()
            except OSError:
                pass
        if writer is not None:
            self.unwatch(address, writer)
        for text in before:
            h = md_hash(text)
            f = folder / f"{h}.md"
            if not f.is_file():
                write_text_private(self._make_folder(address) / f"{h}.md", text, self._root is not None)
            if stamps and h in stamps:
                try:
                    os.utime(f, ns=(stamps[h], stamps[h]), follow_symlinks=False)
                except OSError:
                    pass

    def forget(self, address: str, inside: bool = False):
        """Drop every version of one document. A root that is forgotten takes its documents'
        versions with it: the name may go to another folder, and a page still open on the old
        document must not be merged into the new one. A store inside a root keeps them: they are
        files of the root, as its documents are (7.4), unless the page itself has left the root
        (`inside`: it moved to another tiroir, and keeps no versions under the old address).
        """
        if self._root is None or inside:
            shutil.rmtree(self._folder(address), ignore_errors=True)

    def watch(self, address: str, writer):
        """The document `writer` at `address` lost its root (SPEC 8.2), and its `forget_texts` comes later: from now until
        then, record who puts each text in the folder of `address`, which the folder that takes the name writes to as well.
        The watch is `writer`'s, and its `forget_texts` ends it, whatever other document of the address watches too."""
        with self._claims_lock:
            self._claims.setdefault(self._folder(address), _Claims()).watchers.add(writer)

    def forget_texts(self, address: str, hashes, inside: bool = False, writer=None):
        """`forget`, for the texts named by `hashes` only, newest and pinned alike: what one document put there, when
        the folder of `address` may hold another document's by now (a forget that came after the name was taken).
        After a `watch`, a hash that a writer other than `writer` put there since stays, and its pins with it, the old
        document's among them (the same text): that file is the other document's version too. Ends `writer`'s `watch`,
        also when a delete fails, and takes `writer` out of the record: a hash it put there with another forgotten
        document goes with that one's forget."""
        folder = self._folder(address)
        with self._claims_lock:
            watched = self._claims.get(folder)
            try:
                if self._root is None or inside:
                    by_hash = watched.by_hash if watched is not None else {}
                    for h in hashes:
                        if by_hash.get(h, set()) - {writer}:
                            continue
                        self._unlink(folder, h)
            finally:
                if watched is not None:
                    watched.watchers.discard(writer)
                    for h in [h for h, writers in watched.by_hash.items() if writers == {writer}]:
                        del watched.by_hash[h]
                    for writers in watched.by_hash.values():
                        writers.discard(writer)
                    if not watched.watchers:
                        del self._claims[folder]

    def _unlink(self, folder: Path, h: str):
        """The version `h` in the document folder `folder`, newest and pinned alike, gone."""
        for f in (folder / f"{h}.md", *self._pinned(folder, h)):
            _drop(f)

    def rename(self, old: str, new: str):
        """The versions of the document at `old` are those of `new`: a page that moved keeps its history, newest and
        pinned alike. Nothing at `old`, nothing to carry; whatever `new` held before is replaced (its page is the one that
        moved there)."""
        src = self._folder(old)
        dst = self._dir(self.dir) / doc_key(self._key(new))
        with self._claims_lock:     # a late forget that watches `new` leaves what moved there: another page's history
            left = self._claims.get(src)
            if left is not None:
                # A late forget watches `old`, and would find none of what moves out of its reach: a text only forgotten
                # documents put there since the watch is theirs, not the history of the page that moves, so it stays
                # behind and goes now, as their forget would take it (`forget_texts`). What is put at `old` from now on is
                # recorded afresh.
                if self._root is None:
                    for h, writers in left.by_hash.items():
                        if writers and writers <= left.watchers:
                            self._unlink(src, h)
                left.by_hash.clear()
            if not src.is_dir():
                shutil.rmtree(dst, ignore_errors=True)      # nothing moved there, so what `new` held is the history of a page that is gone
                return
            if dst != src:
                shutil.rmtree(dst, ignore_errors=True)
                os.replace(src, dst)
            write_text_private(dst / _ADDRESS_FILE, self._key(new), self._root is not None)
            watched = self._claims.get(dst)
            if watched is not None:
                pins = dst / _PINS_DIR
                for files in (dst, pins, *self._members(pins)):
                    for p in files.glob("*.md"):
                        if _HASH_RE.fullmatch(p.stem):
                            watched.by_hash.setdefault(p.stem, set()).add(None)

    def addresses(self, prefix: str) -> list[str]:
        """The addresses that start with `prefix` (`<root>/`) and hold versions, found by the `address` file of each folder."""
        found = []
        if self.dir.is_dir():
            for folder in self.dir.iterdir():
                key = read_small(folder / _ADDRESS_FILE)
                address = self._prefix + key if key is not None and self._root is not None else key
                if address is not None and address.startswith(prefix):
                    found.append(address)
        return sorted(found)

    def forget_prefix(self, prefix: str):
        """Drop the versions of every document whose address starts with `prefix` (`<root>/`),
        found by the `address` file of each folder. A document that was opened and never
        rendered is in no other store, and its versions are on disk all the same."""
        if not self.dir.is_dir():
            return
        for folder in self.dir.iterdir():
            try:
                if (folder / _ADDRESS_FILE).read_text(encoding="utf-8").startswith(prefix):
                    shutil.rmtree(folder, ignore_errors=True)
            except (OSError, ValueError):
                pass

    def prune(self, now: float | None = None):
        now = time.time() if now is None else now
        if not self.dir.is_dir():
            return
        for folder in self.dir.iterdir():
            if not folder.is_dir():
                continue
            pins = folder / _PINS_DIR
            members = self._members(pins)
            for files, max_age in ((folder, VERSIONS_MAX_AGE), (pins, PINS_MAX_AGE),
                                   *((m, PINS_MAX_AGE) for m in members)):
                cutoff = now - max_age
                for f in files.glob("*.md"):
                    try:
                        if f.stat().st_mtime < cutoff:
                            f.unlink()
                    except OSError:
                        pass
            for m in members:
                try:
                    m.rmdir()           # only when it is empty: a member with a pin left keeps it
                except OSError:
                    pass
            try:
                if not any(folder.glob("*.md")) and not any(pins.glob("*.md")) and \
                        not any(any(m.glob("*.md")) for m in self._members(pins)):
                    shutil.rmtree(folder, ignore_errors=True)
            except OSError:
                pass


class _Store:
    """A JSON file of one dict, read when the hub starts and changed under a lock. The hub, the
    offline `forget` and any other process change the file, so a change reads the file again inside
    the flock (`<name>.lock`, as `Roots` does) and applies itself to what is there: an entry another
    process wrote or dropped stays so."""
    name = ""

    def __init__(self):
        self._lock = threading.Lock()
        self._data = read_json(paths.state_dir() / self.name, {})

    def _change(self, change):
        """Run `change(data)` on the file's current dict, under the thread lock and the file lock.
        It returns `(result, save)`; the file is written when `save` is true. The result is returned."""
        file = paths.state_dir() / self.name
        with self._lock, file_locked(Path(self.name).stem + ".lock"):
            self._data = read_json(file, {})
            result, save = change(self._data)
            if save:
                try:
                    write_json(file, self._data)
                except BaseException:
                    self._data = read_json(file, {})      # the change is not the file's: memory goes back to what is there
                    raise
            return result

    def rename(self, old: str, new: str) -> None:
        """The entry of the address `old` becomes that of `new`, for a page that moved (9.11); `new`'s own is replaced."""
        def change(data):
            if old not in data:
                return None, data.pop(new, None) is not None     # nothing moved there: what `new` held is of a page that is gone
            data[new] = data.pop(old)
            return None, True
        self._change(change)

    def forget_prefix(self, prefix: str) -> list[str]:
        """Drop every entry whose address starts with `prefix` (`<root>/`); the addresses dropped."""
        def change(data):
            gone = [k for k in data if k.startswith(prefix)]
            for k in gone:
                del data[k]
            return gone, True
        return self._change(change)


class TokenError(Exception):
    """A token that cannot be made: a bad name or display name, or a name already taken."""


_TOKEN_NAME_RE = re.compile(r"[A-Za-z0-9._-]{1,40}")
TOKEN_USED_EVERY = 60            # seconds: how often a busy token rewrites tokens.json


class NewToken(str):
    """A token as `Tokens.add` makes it: the secret itself, which also knows the display name that was kept
    (for an agent's token, the client, which `signed` builds the name from)."""

    display: str
    client: str | None
    id: str

    def __new__(cls, token: str, display: str = "", client: str | None = None, id: str = ""):
        self = super().__new__(cls, token)
        self.display = display
        self.client = client
        self.id = id
        return self


PEER_SCOPES = ("transfer", "read")      # what a peer tiroir's token may ask of this one (ticket 20, 23)


def _row_addable(row: dict) -> bool:
    """Whether `Tokens.add` could have written this row's name and display: a name that fullmatches
    `_TOKEN_NAME_RE`, and either a display that is a string `clean_display` leaves as it is and not empty,
    or (an agent's) a `client` that `client_ok` accepts and no display. A peer's row (`add_peer`) has neither:
    an origin, and scopes that are all of `PEER_SCOPES`."""
    name, display = row.get("name"), row.get("display")
    if not (isinstance(name, str) and _TOKEN_NAME_RE.fullmatch(name) is not None):
        return False
    if "peer" in row:
        return (isinstance(row["peer"], str) and row["peer"] != "" and "display" not in row and "client" not in row
                and _scopes_ok(row.get("scopes", ["transfer"])))
    if "client" in row:
        return "display" not in row and client_ok(row["client"])
    return isinstance(display, str) and display != "" and clean_display(display) == display


def _scopes_ok(scopes) -> bool:
    return isinstance(scopes, list) and all(isinstance(x, str) and x in PEER_SCOPES for x in scopes)


def _scopes_of(entry: dict) -> tuple | None:
    scopes = entry.get("scopes")
    return tuple(x for x in scopes if isinstance(x, str)) if isinstance(scopes, list) else None


def _text(v) -> str | None:
    return v if isinstance(v, str) and v else None


@dataclass(frozen=True)
class TokenRow:
    """One token as the hub and the CLI see it: who it is, never its hash. `created` and
    `last_used` are the stamps of the file as they are."""
    name: str
    display: str | None             # None for an agent's row (it has a client) and for a hand-edited row that lacks one (`verify` refuses that)
    write: bool = False
    created: str | None = None
    last_used: str | None = None
    invalid: bool = False           # set by `of` only: `verify` refuses this row for its name, display or client
    client: str | None = None       # an agent's token (SPEC 9.7): the AI client it speaks for, and no display
    id: str | None = None           # random, written by `add`: tells a revoked token from a new one of its name; none on older rows
    member: str | None = None       # a laptop's token (SPEC 9.7): the front's id of the member it acts for, kept in the row, not in the config
    laptop: str | None = None       # the name its member gave the laptop it was made for
    peer: str | None = None         # a peer tiroir's token (ticket 20): the origin it was made for; it opens the channel and nothing else
    scopes: tuple | None = None     # a peer's: what it may ask (`PEER_SCOPES`); None, a row with no field, is `transfer` only

    def allows(self, scope: str) -> bool:
        """Whether this is a peer's token that holds `scope`: a row with no `scopes` field transfers and does no more."""
        if self.peer is None:
            return False
        return scope in (self.scopes if self.scopes is not None else ("transfer",))

    @classmethod
    def of(cls, entry) -> "TokenRow | None":
        """The row of one entry of `tokens.json`, or None for an entry that is not a named token.
        `write` is only ever a real `true`. `invalid` says `verify` would turn this row's token away
        for its name or display, so a listing can show the row and say so."""
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            return None
        client = entry.get("client")
        return cls(entry["name"], entry.get("display"), entry.get("write") is True,
                   entry.get("created"), entry.get("last_used"), not _row_addable(entry),
                   client if isinstance(client, str) else None,
                   entry["id"] if isinstance(entry.get("id"), str) else None,
                   _text(entry.get("member")), _text(entry.get("laptop")),
                   _text(entry.get("peer")), _scopes_of(entry))

    def is_pair(self, name, tid) -> bool:
        """Whether a stored `token` name and `id` (a Tell's `token`, `tid`; a target's `token`, `id`) name this token:
        both together, so a token revoked and made again under the same name is not the old one (9.7, 9.8)."""
        return self.name == name and self.id == tid

    def signed(self, person: str, cfg=None) -> str:
        """The name this token's replies are signed with. An agent's is built, never typed: `<client> (<member>)`,
        the member the config's `tokens` name this token for (`cfg`, the checked `[proxy]` table), else the hub's
        `person`. Any other token keeps its display."""
        if self.client is None:
            return self.display or ""
        member = cfg.member_of_row(self) if cfg is not None else None
        return agent_name(self.client, member.name if member is not None else person)

    @property
    def name_text(self) -> str:
        """The name for a listing: an invalid one may hold control characters, so it is escaped."""
        return self.name.encode("unicode_escape").decode("ascii") if self.invalid else self.name

    @property
    def display_text(self) -> str:
        """The display name for a listing; an invalid row's may be missing or not text."""
        return "(invalid)" if self.invalid else self.display

    @property
    def created_text(self) -> str:
        return str(self.created)[:16]

    @property
    def last_used_text(self) -> str:
        return str(self.last_used)[:16] if self.last_used else "never"


class Tokens:
    """`tokens.json` (SPEC 4.2, 9.7): `[{name, display, sha256, created, last_used, write}]`, the
    hash of each MCP token and never the token itself. `write` is the right to make and change pages
    through the door; only a real `true` gives it, so a row made before it existed has none.

    The CLI makes and revokes tokens in its own process and the hub checks them in another, so
    nothing is cached: every call reads the file, and a revoked token stops working on the very
    next request. Changes are made under a lock, because the hub rewrites `last_used` too."""

    def __init__(self, clock=time.time):
        self._clock = clock

    @staticmethod
    def _file() -> Path:
        return paths.state_dir() / "tokens.json"

    path = _file                    # the file this environment reads, for a command to name

    def _rows(self) -> list:
        return read_json(self._file(), [])

    @staticmethod
    def _entries(rows: list):
        """The entries of the file that are rows at all. A hand-edited file may hold others; they
        are skipped here and kept by every write."""
        return (r for r in rows if isinstance(r, dict))

    def _write(self, rows: list):
        write_json(self._file(), rows)

    @contextmanager
    def _locked(self):
        with file_locked("tokens.lock"):
            yield

    def _stamp(self) -> str:
        return time.strftime(STAMP_FORMAT, time.localtime(self._clock()))

    def add(self, name: str, display: str | None = None, write: bool = False,
            client: str | None = None, member: str | None = None, laptop: str | None = None,
            clash: "Callable[[list[TokenRow]], str | None] | None" = None) -> NewToken:
        """Make a token and keep its hash. The token is returned here and nowhere else, with the
        display name its replies are signed with; an agent's (`client`) keeps the cleaned client and
        no display. `clash`, when given, is called with the rows the file holds once the lock is ours (so two adds at
        once cannot both pass it) and returns the reason to refuse, or None; the caller reads its config before."""
        if not isinstance(name, str) or not _TOKEN_NAME_RE.fullmatch(name):
            raise TokenError("a token name is 1 to 40 letters, digits, dots, dashes or underscores")
        if client is not None:
            if display is not None:
                raise TokenError("a token has a client or a display name, not both")
            client = clean_display(client)
            if not client_ok(client):
                raise TokenError(f"a client is 1 to {CLIENT_MAX} printable characters, without parentheses")
        shown = name
        if display is not None:
            shown = clean_display(display)
            if not shown:
                raise TokenError("a display name needs at least one printable character")
        with self._locked():
            rows = self._rows()
            if any(r.get("name") == name for r in self._entries(rows)):
                raise TokenError(f"a token named {name} already exists")
            if clash is not None and (why := clash([r for r in map(TokenRow.of, rows) if r is not None])):
                raise TokenError(why)
            token = new_token()
            who = {"client": client} if client is not None else {"display": shown}
            token_id = secrets.token_hex(8)         # not a secret: it is never compared as one
            bound = {"member": member, "laptop": laptop} if member is not None else {}
            rows.append({"name": name, "id": token_id, **who, **bound, "sha256": token_hash(token),
                         "created": self._stamp(), "last_used": None, "write": write is True})
            self._write(rows)
        return NewToken(token, shown if client is None else "", client, token_id)

    def add_peer(self, name: str, origin: str, scopes=None) -> NewToken:
        """A peer tiroir's token (ticket 20): what the tiroir at `origin` sends to open the hub-to-hub channel of this one,
        and nothing else, never the door. `scopes` is a list of `PEER_SCOPES`; None is `transfer` only, and is written
        out, so no row reads as one with the field missing. The token is returned here and nowhere else."""
        if not isinstance(name, str) or not _TOKEN_NAME_RE.fullmatch(name):
            raise TokenError("a token name is 1 to 40 letters, digits, dots, dashes or underscores")
        scopes = ["transfer"] if scopes is None else list(dict.fromkeys(scopes))
        if not scopes or not _scopes_ok(scopes):
            raise TokenError(f"a peer token's scope is one of {', '.join(PEER_SCOPES)}")
        with self._locked():
            rows = self._rows()
            if any(r.get("name") == name for r in self._entries(rows)):
                raise TokenError(f"a token named {name} already exists")
            token = new_token()
            rows.append({"name": name, "id": secrets.token_hex(8), "peer": origin, "scopes": scopes,
                         "sha256": token_hash(token), "created": self._stamp(), "last_used": None, "write": False})
            self._write(rows)
        return NewToken(token, "", None, rows[-1]["id"])

    def list(self) -> list[TokenRow]:
        """Every token: its name, display name, created, last used and whether it may write. Never
        its hash."""
        return [row for row in map(TokenRow.of, self._rows()) if row is not None]

    def revoke(self, name: str) -> bool:
        with self._locked():
            rows = self._rows()
            kept = [r for r in rows if not (isinstance(r, dict) and r.get("name") == name)]
            if len(kept) == len(rows):
                return False
            self._write(kept)
            return True

    @classmethod
    def _holders(cls, rows: list, digest: bytes) -> list:
        """Every row that holds this hash. Every row is compared, so the time taken does not say
        which matched. `verify` and `_touch` both ask this, so they never pick different rows."""
        return [r for r in cls._entries(rows)
                if isinstance(r.get("sha256"), str) and hmac.compare_digest(r["sha256"].encode("utf-8"), digest)]

    def verify_peer(self, token) -> TokenRow | None:
        """The row of a peer tiroir's token, as `verify` judges it; None for any other kind of token."""
        return self.verify(token, peer=True)

    def verify(self, token, peer: bool = False) -> TokenRow | None:
        """The row of the token's owner (`name`, `display`, `write`), or None for a token that was never made
        or was revoked, or whose row `add` could not have written (a name that fails `_TOKEN_NAME_RE`, a display
        that is not a string, is empty or changes when cleaned), or whose hash more than one row holds.
        A good use stamps `last_used`, at most once a minute."""
        if not isinstance(token, str) or not token.startswith(TOKEN_PREFIX) or len(token) > MAX_TOKEN:
            return None
        found = self._holders(self._rows(), token_hash(token).encode("ascii"))
        # a row `add` could not have made (a hand-edited one) cannot be signed or audited, and a hash held
        # twice does not say whose token it is
        if len(found) != 1 or not _row_addable(found[0]) or ("peer" in found[0]) is not peer:
            return None             # a peer's token is the channel's alone, and a door's token never opens the channel
        row = found[0]
        if self._stale(row.get("last_used")) and not self._touch(row["sha256"]):
            return None
        return TokenRow(row["name"], row.get("display"), row.get("write") is True, client=row.get("client"),
                        id=row["id"] if isinstance(row.get("id"), str) else None,
                        member=_text(row.get("member")), laptop=_text(row.get("laptop")),
                        peer=_text(row.get("peer")), scopes=_scopes_of(row))

    def _stale(self, last_used) -> bool:
        try:
            then = datetime.strptime(last_used, STAMP_FORMAT).timestamp()
        except (TypeError, ValueError):
            return True
        return self._clock() - then >= TOKEN_USED_EVERY

    def _touch(self, sha256: str) -> bool:
        """Stamp the row with this hash. False when it has been revoked since it was read, when a second
        row holds the hash now, or when the row is no longer one `add` could have written."""
        with self._locked():
            rows = self._rows()
            found = self._holders(rows, sha256.encode("ascii", "replace"))
            if len(found) == 1 and _row_addable(found[0]):
                found[0]["last_used"] = self._stamp()
                self._write(rows)
                return True
        return False


class Docs(_Store):
    """`docs.json`: per rendered document its last render settings and target (SPEC 8.3)."""
    name = "docs.json"

    def get(self, address: str) -> dict:
        with self._lock:
            e = self._data.get(address)
            return dict(e) if isinstance(e, dict) else {}

    def put(self, address: str, entry: dict):
        def change(data):
            data[address] = dict(entry)
            return None, True
        self._change(change)

    def change(self, address: str, settle) -> tuple[dict, dict]:
        """Read the entry, let `settle(copy)` return the new one and write it, all under the file's lock, so
        a render and a change of target never overwrite each other. (the entry before, the entry after)"""
        def go(data):
            e = data.get(address)
            old = dict(e) if isinstance(e, dict) else {}
            new = settle(dict(old))
            if new == old:
                return (old, new), False
            data[address] = new
            return (old, new), True
        return self._change(go)


class Seen(_Store):
    """`seen.json`: `{"<root>/<path>": {"c3": 2}}`, how many messages of each thread the
    hub's person has seen (SPEC 8.7). A count never goes down: two tabs, one older."""
    name = "seen.json"

    def get(self, address: str) -> dict:
        with self._lock:
            e = self._data.get(address)
            return dict(e) if isinstance(e, dict) else {}

    def mark(self, address: str, cid: str, count: int):
        def change(data):
            doc = data.setdefault(address, {})
            if count > doc.get(cid, 0):
                doc[cid] = count
                return None, True
            return None, False
        self._change(change)


class MemberOpened(_Store):
    """`opened-members.json`: `{"<member id>": {"<root>/<path>": <mtime_ns>}}`, the change of a page that each member of
    proxy mode had in front of them when they last opened it. A page of another member's Shared with them is new to
    them while it changed since (the Sheaf's "new" dot, 8.6). Keyed by the front's id, as `MemberSeen` is."""
    name = "opened-members.json"

    def get(self, member: str, address: str) -> int:
        with self._lock:
            e = self._data.get(member)
            n = e.get(address) if isinstance(e, dict) else None
            return n if isinstance(n, int) else 0

    def mark(self, member: str, address: str, mtime_ns: int):
        def change(data):
            docs = data.setdefault(member, {})
            if docs.get(address) == mtime_ns:
                return None, False
            docs[address] = mtime_ns
            return None, True
        self._change(change)

    def rename(self, old: str, new: str) -> None:
        """Every member's entry of the address `old` becomes that of `new`, for a page that moved (9.11)."""
        def change(data):
            hit = False
            for docs in data.values():
                if isinstance(docs, dict) and old in docs:
                    docs[new] = docs.pop(old)
                    hit = True
            return None, hit
        self._change(change)

    def forget_prefix(self, prefix: str) -> list[str]:
        def change(data):
            gone = set()
            for docs in data.values():
                if isinstance(docs, dict):
                    for k in [k for k in docs if k.startswith(prefix)]:
                        del docs[k]
                        gone.add(k)
            return sorted(gone), bool(gone)
        return self._change(change)


class SharedIds(_Store):
    """`shared-ids.json`: `{"<id>": "<root>/<path>"}`, the opaque names under which a page of another member's loose root
    is told to the members it is Shared with (9.11): the owner's folder names and the path on disk are theirs alone.
    An id is random, made once for a page and kept, so a link the recipient holds keeps working."""
    name = "shared-ids.json"

    def of(self, address: str) -> str:
        def change(data):
            for k, v in data.items():
                if v == address:
                    return k, False
            k = "s-" + secrets.token_hex(8)
            data[k] = address
            return k, True
        return self._change(change)

    def known(self, address: str) -> str | None:
        """The opaque name already made for `address`, else None: never makes one."""
        with self._lock:
            return next((k for k, v in self._data.items() if v == address), None)

    def address(self, key: str) -> str | None:
        with self._lock:
            v = self._data.get(key)
            return v if isinstance(v, str) else None

    def rename(self, old: str, new: str) -> None:
        """The opaque name of the page at `old` is now the name of the page at `new`: a recipient's link keeps working."""
        def change(data):
            hit = [k for k, v in data.items() if v == old]
            for k in hit:
                data[k] = new
            return None, bool(hit)
        self._change(change)

    def forget_prefix(self, prefix: str) -> None:
        def change(data):
            gone = [k for k, v in data.items() if isinstance(v, str) and v.startswith(prefix)]
            for k in gone:
                del data[k]
            return None, bool(gone)
        self._change(change)


class MemberSeen(_Store):
    """`seen-members.json`: `{"<member id>": {"<root>/<path>": {"c3": 2}}}`, what each member of
    proxy mode has seen, kept apart from the hub's person's (SPEC 4.2, 9.9). Keyed by the front's
    id, so a member renamed in the config keeps what they had read."""
    name = "seen-members.json"

    def get(self, member: str, address: str) -> dict:
        with self._lock:
            e = self._data.get(member)
            e = e.get(address) if isinstance(e, dict) else None
            return dict(e) if isinstance(e, dict) else {}

    def mark(self, member: str, address: str, cid: str, count: int):
        def change(data):
            doc = data.setdefault(member, {}).setdefault(address, {})
            if count > doc.get(cid, 0):
                doc[cid] = count
                return None, True
            return None, False
        self._change(change)

    def rename(self, old: str, new: str) -> None:
        """Every member's entry of the address `old` becomes that of `new`, for a page that moved (9.11)."""
        def change(data):
            hit = False
            for docs in data.values():
                if isinstance(docs, dict) and old in docs:
                    docs[new] = docs.pop(old)
                    hit = True
            return None, hit
        self._change(change)

    def forget_prefix(self, prefix: str) -> list[str]:
        """Drop every member's entries whose address starts with `prefix` (`<root>/`)."""
        def change(data):
            gone = set()
            for docs in data.values():
                if isinstance(docs, dict):
                    for k in [k for k in docs if k.startswith(prefix)]:
                        del docs[k]
                        gone.add(k)
            return sorted(gone), bool(gone)         # loopback mode never writes the file
        return self._change(change)
