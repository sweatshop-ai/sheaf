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
import shutil
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .. import diagnostics, paths
from ..source import STAMP_FORMAT, md_hash
from .auth import MAX_TOKEN, TOKEN_PREFIX, clean_display, new_token, token_hash

try:
    import fcntl
except ImportError:            # Windows: no flock; the token file is written by one process at a time
    fcntl = None

VERSIONS_KEPT = 60              # per document
VERSIONS_MAX_AGE = 7 * 86400    # seconds
PINS_KEPT = 16                  # per document: the versions pages keep (`pin`)
PINS_MAX_AGE = 7 * 86400        # seconds since a page last pinned it
_HASH_RE = re.compile(r"[0-9a-f]{16}")
_ADDRESS_FILE = "address"       # in each versions folder: the address it is the key of
_PINS = "pins"
INSIDE = Path(".sheaf") / "versions"  # a root's own versions store, inside it (7.4)                  # in each versions folder: the versions pages keep


def write_text_private(path: Path, text: str):
    """Write `text` to `path`: complete or not at all, 0600."""
    path = Path(path)
    paths.private_dir(path.parent)
    tmp = path.with_name("." + path.name + ".tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
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


def doc_key(address: str) -> str:
    """First 16 hex of the sha256 of `<root>/<path>`: the folder of that document's versions."""
    return hashlib.sha256(address.encode("utf-8")).hexdigest()[:16]


class Versions:
    """Every text the hub handed a page, on disk, so a save against a page rendered before a
    restart still merges. `<state>/versions/<doc-key>/<hash>.md`, the newest 60 per document,
    nothing older than 7 days after `prune()` (run when the hub starts). Beside them, in `pins/`,
    the versions pages said they keep past a change of the file (`pin`): the newest 16, none
    pinned last more than 7 days before `prune()`. Each folder also holds `address`, the
    `<root>/<path>` it is the key of, so a whole root's folders can be found."""

    def __init__(self, root: Path | None = None, name: str = ""):
        """Without `root`, the store of the state folder. With it, the store of that root's own
        documents, inside it at `.sheaf/versions/` (7.4, `versions = "root"`), keyed by the path in the
        root, not the address: another hub, a clone's, names the root otherwise. `name` is the root's."""
        self._root, self._prefix = root, f"{name}/"

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
        folder = paths.private_dir(paths.private_dir(self.dir) / doc_key(self._key(address)))
        if not (folder / _ADDRESS_FILE).exists():
            write_text_private(folder / _ADDRESS_FILE, self._key(address))
        return folder

    @staticmethod
    def _keep(folder: Path, text: str, newest: int) -> str:
        """Write `text` under its hash in `folder` (or count it as written now), and keep the
        `newest` files there. Only a file named by a hash counts or is deleted here: anything else
        is not a version (`get` would not believe it) and takes no slot."""
        h = md_hash(text)
        f = folder / f"{h}.md"
        if f.is_file():
            os.utime(f)
        else:
            write_text_private(f, text)
        files = []
        for p in folder.glob("*.md"):
            if _HASH_RE.fullmatch(p.stem) and p.is_file():
                try:
                    files.append((p.stat().st_mtime_ns, p.name, p))
                except OSError:
                    pass
        for _, _, p in sorted(files)[:-newest]:
            try:
                p.unlink()
            except OSError:
                pass
        return h

    def put(self, address: str, text: str) -> str:
        return self._keep(self._make_folder(address), text, VERSIONS_KEPT)

    def pin(self, address: str, text: str) -> str:
        """Keep `text` as a version a page keeps, apart from the newest 60, which writes from
        outside push out."""
        return self._keep(paths.private_dir(self._make_folder(address) / _PINS), text, PINS_KEPT)

    def get(self, address: str, h) -> str | None:
        """The text with hash `h`, among the newest or the pinned, or None. `h` comes from a
        request: nothing that is not 16 lowercase hex reaches the disk, and a file whose text
        does not hash to its name is not believed."""
        if not isinstance(h, str) or not _HASH_RE.fullmatch(h):
            return None
        folder = self._folder(address)
        for f in (folder / f"{h}.md", folder / _PINS / f"{h}.md"):
            try:
                text = f.read_text(encoding="utf-8")
            except (OSError, ValueError):
                continue
            if md_hash(text) == h:
                return text
        return None

    def forget(self, address: str):
        """Drop every version of one document. A root that is forgotten takes its documents'
        versions with it: the name may go to another folder, and a page still open on the old
        document must not be merged into the new one."""
        shutil.rmtree(self._folder(address), ignore_errors=True)

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
            for files, max_age in ((folder, VERSIONS_MAX_AGE), (folder / _PINS, PINS_MAX_AGE)):
                cutoff = now - max_age
                for f in files.glob("*.md"):
                    try:
                        if f.stat().st_mtime < cutoff:
                            f.unlink()
                    except OSError:
                        pass
            try:
                if not any(folder.glob("*.md")) and not any((folder / _PINS).glob("*.md")):
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
                write_json(file, self._data)
            return result

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
    """A token as `Tokens.add` makes it: the secret itself, which also knows the display name that was kept."""

    display: str

    def __new__(cls, token: str, display: str = ""):
        self = super().__new__(cls, token)
        self.display = display
        return self


def _row_addable(row: dict) -> bool:
    """Whether `Tokens.add` could have written this row's name and display: a name that fullmatches
    `_TOKEN_NAME_RE`, and a display that is a string `clean_display` leaves as it is and not empty."""
    name, display = row.get("name"), row.get("display")
    return (isinstance(name, str) and _TOKEN_NAME_RE.fullmatch(name) is not None
            and isinstance(display, str) and display != "" and clean_display(display) == display)


@dataclass(frozen=True)
class TokenRow:
    """One token as the hub and the CLI see it: who it is, never its hash. `created` and
    `last_used` are the stamps of the file as they are."""
    name: str
    display: str | None             # None only for a hand-edited row that lacks one (`verify` refuses such a row)
    write: bool = False
    created: str | None = None
    last_used: str | None = None
    invalid: bool = False           # set by `of` only: `verify` refuses this row for its name or display

    @classmethod
    def of(cls, entry) -> "TokenRow | None":
        """The row of one entry of `tokens.json`, or None for an entry that is not a named token.
        `write` is only ever a real `true`. `invalid` says `verify` would turn this row's token away
        for its name or display, so a listing can show the row and say so."""
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            return None
        return cls(entry["name"], entry.get("display"), entry.get("write") is True,
                   entry.get("created"), entry.get("last_used"), not _row_addable(entry))

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

    def add(self, name: str, display: str | None = None, write: bool = False) -> NewToken:
        """Make a token and keep its hash. The token is returned here and nowhere else, with the
        display name its replies are signed with."""
        if not isinstance(name, str) or not _TOKEN_NAME_RE.fullmatch(name):
            raise TokenError("a token name is 1 to 40 letters, digits, dots, dashes or underscores")
        shown = name
        if display is not None:
            shown = clean_display(display)
            if not shown:
                raise TokenError("a display name needs at least one printable character")
        with self._locked():
            rows = self._rows()
            if any(r.get("name") == name for r in self._entries(rows)):
                raise TokenError(f"a token named {name} already exists")
            token = new_token()
            rows.append({"name": name, "display": shown, "sha256": token_hash(token),
                         "created": self._stamp(), "last_used": None, "write": write is True})
            self._write(rows)
        return NewToken(token, shown)

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

    def verify(self, token) -> TokenRow | None:
        """The row of the token's owner (`name`, `display`, `write`), or None for a token that was never made
        or was revoked, or whose row `add` could not have written (a name that fails `_TOKEN_NAME_RE`, a display
        that is not a string, is empty or changes when cleaned), or whose hash more than one row holds.
        A good use stamps `last_used`, at most once a minute."""
        if not isinstance(token, str) or not token.startswith(TOKEN_PREFIX) or len(token) > MAX_TOKEN:
            return None
        found = self._holders(self._rows(), token_hash(token).encode("ascii"))
        # a row `add` could not have made (a hand-edited one) cannot be signed or audited, and a hash held
        # twice does not say whose token it is
        if len(found) != 1 or not _row_addable(found[0]):
            return None
        row = found[0]
        if self._stale(row.get("last_used")) and not self._touch(row["sha256"]):
            return None
        return TokenRow(row["name"], row["display"], row.get("write") is True)

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
