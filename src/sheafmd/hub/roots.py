"""
sheafmd.hub.roots — which folder a document belongs to, what that folder is called, and
how an address in a URL becomes a file again (SPEC 8.2, 8.3).

A document's address is `<root>/<path-in-root>`, never a disk path (SPEC 21): the hub's URLs,
`docs.json` and the page's `doc` field all use it.
"""
import os
import re
import secrets
import stat as stat_mod
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, NamedTuple
from urllib.parse import quote, unquote

from .. import config, paths
from ..source import STAMP_FORMAT
from . import state

LIST_CAP = 2000                 # documents the walk of a root that is not a git repo lists (D15)
COUNT_LIMIT = 100_000           # documents counted past the cap before the count is given up
_GIT_LIST_SECONDS = 20


class NotFound(Exception):
    """An address that is no markdown file inside a root."""


@dataclass(frozen=True)
class Root:
    name: str
    path: Path
    git: bool
    # Random, made when the root is registered and kept in roots.json: a folder that takes the name after
    # a forget is another root, with another id, and a page of the old one tells the two apart by it
    # (SPEC 8.2, 10.7).
    id: str = ""

    def missing(self) -> bool:
        """The folder is gone: the root keeps its name, and says so (SPEC 8.6). A folder the hub
        cannot look at is not gone (`closed`); the hint for a gone one forgets its versions."""
        try:
            return not paths.is_dir(self.path)
        except OSError:
            return False

    def closed(self) -> str | None:
        """Why the hub cannot look at the folder, which may well be there, in the error's words: a
        folder on the way that it may not enter is "Permission denied". None when it can."""
        try:
            paths.is_dir(self.path)
        except OSError as e:
            return e.strerror or str(e)
        return None


class Found(NamedTuple):
    rel: str                    # the path in the root, `/` separators
    stat: os.stat_result


class Listing(NamedTuple):
    docs: list                  # [Found], sorted by path
    more: int                   # documents left out at the cap


def _new_id() -> str:
    return secrets.token_hex(8)


def clean_name(folder_name: str) -> str:
    """The folder's name with every character outside [A-Za-z0-9._-] replaced by `-`, leading
    `.` and `_` stripped, `root` when nothing is left. Never starts with `_`, which keeps
    `/_/` free for the hub."""
    return re.sub(r"[^A-Za-z0-9._-]", "-", folder_name).lstrip("._") or "root"


def url_path(address: str) -> str:
    """The path of a document's URL: each segment percent-encoded."""
    return "/" + "/".join(quote(seg, safe="") for seg in address.split("/"))


def address_of_url(target: str) -> str | None:
    """`/<root>/<path>` (percent-encoded) as an address, or None when it is not the shape of
    one: fewer than two segments, an empty segment, a decoded segment holding a slash or a
    NUL, or bytes that are not UTF-8."""
    if not target.startswith("/"):
        return None
    segments = target[1:].split("/")
    if len(segments) < 2:
        return None
    out = []
    for seg in segments:
        try:
            seg = unquote(seg, errors="strict")
        except UnicodeDecodeError:
            return None
        if not seg or "/" in seg or "\0" in seg:
            return None
        out.append(seg)
    return "/".join(out)


def _inside(real: Path, top: Path) -> bool:
    return real == top or top in real.parents


def _shaped_like_a_git_dir(at: Path) -> bool:
    """`at` is named `.git`, or holds `HEAD` and either `commondir` or `objects` and `refs`, entries of
    any kind: what git itself looks for, without checking them (SPEC 8.2)."""
    return at.name == ".git" or (os.path.lexists(at / "HEAD") and (
        os.path.lexists(at / "commondir") or (os.path.lexists(at / "objects") and os.path.lexists(at / "refs"))))


def _in_git_dir_by_path(folder: Path, top: Path | None) -> bool:
    """Whether `folder` lies in a git directory by its path alone (SPEC 8.2): it, or a folder
    above it up to `top` (not counted; `/` when None), is shaped like one."""
    at = folder
    while at != top and at != at.parent:
        if _shaped_like_a_git_dir(at):
            return True
        at = at.parent
    return False


def _enterable(folder: Path) -> bool:
    """A folder that is there and that this account may enter: one git can be asked from."""
    return os.path.isdir(folder) and os.access(folder, os.X_OK)


def _git_place(folder: Path, at: Path, stop: Path | None) -> config.GitPlace:
    """Where `folder` stands to git, asked from `at` (SPEC 8.2): the top of the work tree git names,
    and whether `folder` lies in a git directory, which git says or the path does, looked at up to
    that top, else up to `stop` (neither counted; `/` when both are None)."""
    top, in_git_dir = config.git_place(at)
    return config.GitPlace(top, in_git_dir or _in_git_dir_by_path(folder, top if top is not None else stop))


def in_git_dir(md: Path, root: Root) -> bool:
    """Whether 8.2 keeps `md`, a path under `root`'s folder, from `root` for lying in a git directory:
    its folder is in one, by git's answer or by the path's, looked at up to the top of the work tree
    git names, else up to `root`'s folder (that folder counted), and is not `root`'s own folder,
    which rule 3 leaves it. What the door asks of an address (SPEC 12)."""
    folder, top = Path(os.path.realpath(md)).parent, Path(os.path.realpath(root.path))
    if folder == top:
        return False
    # Every folder git takes for a git directory is shaped like one, so where none is, at the folder or
    # above it (`/` too, which git may answer for), git's answer is no as well and is not asked: the
    # listing of a root and a page's request run no git for an ordinary folder.
    if not any(_shaped_like_a_git_dir(at) for at in (folder, *folder.parents)):
        return False
    at = folder
    while not _enterable(at) and at != at.parent:
        at = at.parent
    return _git_place(folder, at, top.parent).in_git_dir


@dataclass(frozen=True)
class Address:
    """A document's address, `<root>/<path-in-root>` (8.2): the one place it is split and joined.
    On the wire, in `docs.json` and in the hub's dicts it stays the string `str()` gives."""
    root: str
    rel: str

    @classmethod
    def parse(cls, text: str) -> "Address":
        """Split at the first `/`: the root is what stands before it, the whole text when there is
        none (the path is then empty). `str()` always writes `root/rel`, so an address with no path
        does not come back as it went in."""
        root, _, rel = text.partition("/")
        return cls(root, rel)

    @staticmethod
    def prefix(root: str) -> str:
        """What every address in the root `root` starts with."""
        return root + "/"

    @property
    def plain(self) -> bool:
        """Whether the path is one that can name a file in the root: not empty, and no empty, `.`
        or `..` segment and no NUL."""
        return bool(self.rel) and not any(p in ("", ".", "..") or "\0" in p for p in self.rel.split("/"))

    def __str__(self) -> str:
        return f"{self.root}/{self.rel}"


def root_of_url(target: str) -> str | None:
    """`/<root>/` as the name of the root, or None when it is not the shape of one."""
    segments = target.split("/")
    if len(segments) != 3 or segments[0] or segments[2] or not segments[1]:
        return None
    try:
        name = unquote(segments[1], errors="strict")
    except UnicodeDecodeError:
        return None
    return None if "/" in name or "\0" in name else name


class Roots:
    """The registry of `roots.json`:
    `{"<name>": {"path": "/abs", "git": true, "added": "<iso>", "id": "<random>"}}`.

    A root is added when a document in it is rendered or named to the hub, never by
    scanning. Names and ids are kept across restarts. A root read without an id (a file written
    before roots had one) is given one, saved at once, so the next start reads the same.

    `writes=False` is a registry for a look that changes nothing on disk (`image_rule`): it
    reads roots.json as the hub left it, sets nothing aside, and holds what it adds in memory."""

    def __init__(self, writes: bool = True):
        self._writes = writes
        self._lock = threading.RLock()
        self._roots: dict[str, Root] = {}
        self._added: dict[str, str] = {}
        if self._load():
            with self._changing():
                self._save()

    @contextmanager
    def _changing(self):
        """A change to the registry: under the lock of the thread and of the file, with the
        registry read again from the file, so what another process wrote since is kept and an id
        it gave a root stays that root's. A registry that writes nothing changes only itself."""
        with self._lock:
            if not self._writes:
                yield
                return
            with state.file_locked("roots.lock"):
                self._load()
                yield

    def _load(self) -> bool:
        """Read roots.json into the registry; True when a root had no id and was given one here,
        which is for the caller to save."""
        data = state.read_json(self._file(), {}, aside=self._writes)
        if self._writes and self._roots and not self._file().exists():
            return False                # the file went missing or was set aside as unreadable: keep what is held
        self._roots, self._added = {}, {}
        unnamed = False
        for name, e in data.items():
            if isinstance(e, dict) and isinstance(e.get("path"), str):
                rid = e.get("id")
                if not (isinstance(rid, str) and rid):
                    rid, unnamed = _new_id(), True
                self._roots[name] = Root(name, Path(e["path"]), bool(e.get("git")), rid)
                self._added[name] = str(e.get("added") or "")
        return unnamed

    @staticmethod
    def _file() -> Path:
        return paths.state_dir() / "roots.json"

    def _save(self):
        if not self._writes:
            return
        state.write_json(self._file(), {
            n: {"path": str(r.path), "git": r.git, "added": self._added.get(n, ""), "id": r.id}
            for n, r in self._roots.items()})

    def all(self) -> list[Root]:
        with self._lock:
            return list(self._roots.values())

    def get(self, name: str) -> Root | None:
        with self._lock:
            return self._roots.get(name)

    def _add(self, path: Path, git: bool) -> Root:
        with self._lock:
            known = {n: r.path for n, r in self._roots.items()}
        with self._changing():
            path = Path(path).resolve()
            for r in self._roots.values():
                if r.path == path:
                    return r
            if {n: r.path for n, r in self._roots.items()} != known:
                # another process changed the registry since the caller chose this root: choose again
                found = self._find(path, list(self._roots.values()))[0]
                if found is not None:
                    return found
            base = clean_name(path.name)
            name, n = base, 2
            while name in self._roots:
                name, n = f"{base}-{n}", n + 1
            root = Root(name, path, git, _new_id())
            self._roots[name] = root
            self._added[name] = time.strftime(STAMP_FORMAT)
            self._save()
            return root

    def forget(self, name: str) -> Root | None:
        """Take a root out of the registry (`sheaf roots forget`). The documents' own entries
        (docs.json, seen.json) are the caller's to remove: the registry knows only roots."""
        with self._lock:
            held = self._roots.get(name)
        with self._changing():
            root = self._roots.pop(name, None)
            self._added.pop(name, None)
            if root is not None:
                self._save()
            return root or held         # a root another process already took out of the file is still the one forgotten here

    @staticmethod
    def _find(folder: Path, registered: list[Root]) -> tuple[Root | None, Path | None]:
        """The root of `registered` the rules of 8.2 give a document in `folder`, or None when they would
        make a new one, and the top of its git work tree, if it has one. `folder` need not be there.
        Git is asked from the nearest folder at or above it that git can enter, one that is there
        and that this account may enter: asked of another, git answers nothing, and such a folder
        inside a repo nested in a non-git root went to the outer root, so a member's image told
        whether that repo holds it (9.9 "Local images"). A registered root's folder met on the way
        up is the root: a root that is gone, or closed to this account, keeps what is under it.
        Inside a git directory (a `.git` folder, a bare repo, a submodule's) rule 1 gives nothing and
        rule 2 does not reach in: the root that holds the repo never gets what its git directory holds.
        Git's answer finds one, and so does the path (`_in_git_dir_by_path`): where git refuses
        to run, and where it takes a nested `.git` for a folder of its work tree. Where git names no
        work tree, the path is looked at up to the root rule 2 would give, that root's folder
        included: a git directory above a registered root takes nothing from it. It reads only
        `registered` and takes no lock: the caller says which roots it judges against."""
        at = folder
        while not _enterable(at) and at != at.parent:
            held = next((r for r in registered if r.path == at), None)
            if held is not None:
                return held, None
            at = at.parent
        inside = [r for r in registered if not r.git and (folder == r.path or r.path in folder.parents)]
        deepest = max(inside, key=lambda r: len(r.path.parts), default=None)
        top, in_git_dir = _git_place(folder, at, deepest.path.parent if deepest else None)
        if not in_git_dir:
            if top:
                return next((r for r in registered if r.path == top), None), top
            if deepest:
                return deepest, None
        return next((r for r in registered if r.path == folder), None), None

    def lookup(self, md: Path) -> Root | None:
        """The root `for_document` would give `md` when it is one the hub already has; None
        otherwise. Registers nothing: what a caller who may not add a root asks (SPEC 9.7). The roots
        are read under the lock and git is asked outside it, so a lookup that waits on git (a member's
        stream judging an event, SPEC 8.6) holds no request, no look, no sweep and no other lookup."""
        with self._lock:
            registered = list(self._roots.values())
        return self._find(Path(os.path.realpath(md)).parent, registered)[0]

    def for_document(self, md: Path) -> Root:
        """The root of `md`, first match wins (SPEC 8.2): the top of its git work tree (each
        worktree its own); else the deepest registered root that is not a git repo and holds
        it; else its own folder. Registers the root when it is new: the roots it judged against and
        the one it adds are one step, under the lock, so two documents of one new folder make one root."""
        with self._lock:
            folder = Path(os.path.realpath(md)).parent
            root, top = self._find(folder, list(self._roots.values()))
            return root or self._add(top or folder, git=bool(top))

    def address(self, md: Path) -> str:
        """`<root>/<path-in-root>` of `md`, registering its root."""
        md = Path(os.path.realpath(md))
        root = self.for_document(md)
        return str(Address(root.name, md.relative_to(root.path).as_posix()))

    def resolve(self, address: str) -> Path:
        """The file an address names. Refuses (NotFound) an unknown root, a `.` or `..` or
        empty segment, anything that does not end in `.md`, a path whose real location is
        outside the root's real location (a symlink out), and anything that is not a file."""
        return self._resolve(address)[1]

    def document(self, address: str) -> Path:
        """The file an address names to the door (SPEC 12): what `resolve` gives, and NotFound as well
        for one that 8.2 keeps from the root the address names for lying in a git directory
        (`in_git_dir`), as it keeps it from a member: `work/sub/.git/x.md` names nothing."""
        root, real = self._resolve(address)
        if in_git_dir(real, root):
            raise NotFound(address)
        return real

    def _resolve(self, address: str) -> tuple[Root, Path]:
        at = Address.parse(address)
        root = self.get(at.root)
        if root is None or not at.plain or not at.rel.endswith(".md"):
            raise NotFound(address)
        if _sheafs_own(at.rel):
            raise NotFound(address)
        try:
            top = Path(os.path.realpath(root.path))
            real = Path(os.path.realpath(root.path / at.rel))
            if not _inside(real, top) or not real.is_file() or _sheafs_own(real.relative_to(top).as_posix()):
                raise NotFound(address)
        except (OSError, ValueError):
            raise NotFound(address) from None
        return root, real


def image_rule(md: Path):
    """The image rule of proxy mode (9.9 "Local images") for a copy of `md` that the hub does not
    make (`sheaf share`): which local image files may be embedded. Those whose root, as 8.2 finds
    it in the hub's registry, is the document's own root, as the hub judges them: the document's
    root counts as registered, as a render registers it. Writes nothing."""
    reg = Roots(writes=False)
    root = reg.for_document(md)
    return lambda path: reg.lookup(path) == root


def forget(reg: Roots, docs, seen, versions, name: str, *, members) -> Root | None:
    """`sheaf roots forget` in the hub: the root leaves the registry, and its documents' entries
    (their render settings in `docs`, their read state in `seen` and in `members`, their versions
    on disk) go with it. The documents are files and stay where they are. Returns the root, or
    None when there was none by that name.

    The registry goes first: a request that comes while the entries go then finds no such
    document, where one that found it would make the document's entry again once the hub's lock
    is let go."""
    root = reg.forget(name)
    if root is not None:
        _forget_entries((docs, seen, members), versions, Address.prefix(name))
    return root


def forget_offline(name: str) -> Root | None:
    """`sheaf roots forget` with no hub (8.2): the same, in the files a hub reads when it starts.
    The registry goes last: a hub reads roots.json before the other files, so one that starts while
    the command writes either finds the root and is told by the command's second look, or finds
    neither the root nor its entries. Each file is read just before it is written, never when the
    command starts, so what a hub that started meanwhile wrote to it stays."""
    root = Roots().get(name)
    if root is None:
        return None
    _forget_entries((store() for store in (state.Docs, state.Seen, state.MemberSeen)), state.Versions(),
                    Address.prefix(name))
    Roots().forget(name)
    return root


def _forget_entries(stores, versions, prefix: str):
    """Drop the entries of every address under `prefix` from each of `stores` (render settings, read
    state, the members' read state), which may make each store as it comes to it, and their versions."""
    gone = set()
    for store in stores:
        gone.update(store.forget_prefix(prefix))
    for address in gone:
        versions.forget(address)
    versions.forget_prefix(prefix)              # a document opened and never rendered is in none of them


# ── what a root holds (SPEC 8.6) ─────────────────────────────────────────────

def _stat_inside(top: Path, rel: str, folders: dict) -> tuple[os.stat_result, bool] | None:
    """The stat of the file `rel` in a root whose real folder is `top`, and whether the file is a
    link; None when it is not a regular file, or when its real location is outside the root (what
    `resolve` refuses): the file itself a link out, or a folder of its path (git lists `docs/a.md`
    while it is tracked, though `docs` became a link out). `folders` remembers which folders were
    found inside, so a listing resolves each folder once. A file that is no link costs the one
    `lstat`; a link is resolved and stat-ed too."""
    full = os.path.join(top, rel)
    try:
        here = rel.rpartition("/")[0]
        if here:
            inside = folders.get(here)
            if inside is None:
                inside = folders[here] = _inside(Path(os.path.realpath(os.path.dirname(full))), top)
            if not inside:
                return None
        st = os.lstat(full)
        linked = stat_mod.S_ISLNK(st.st_mode)
        if linked:
            if not _inside(Path(os.path.realpath(full)), top):
                return None
            st = os.stat(full)
    except (OSError, ValueError):
        return None
    return (st, linked) if stat_mod.S_ISREG(st.st_mode) else None


_NOT_A_REPO = object()


def _git_names(folder: Path):
    """Tracked and untracked markdown files git lists in `folder`, gitignored ones and
    `node_modules` left out. `_NOT_A_REPO` when git says the folder is no repository any more
    (nothing is ignored there, so it can be walked); None when git gives no answer (not
    installed, too slow, refusing), when nothing may be listed that git did not vouch for."""
    try:
        r = subprocess.run(["git", "-C", str(folder), "ls-files", "-z", "-co", "--exclude-standard",
                            "--", "*.md", ":!:**/node_modules/**", ":!:.sheaf/**"],
                           capture_output=True, timeout=_GIT_LIST_SECONDS,
                           env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return _NOT_A_REPO if b"not a git repository" in r.stderr else None
    return [n for n in r.stdout.decode("utf-8", "surrogateescape").split("\0") if n]


SHEAFS_OWN = ".sheaf"            # a root's folder of sheaf's own files: its versions store, a theme (4.4, 7.4)


def _sheafs_own(rel: str) -> bool:
    """Whether `rel`, a path in a root, lies in the root's `.sheaf/`, which is never a page (8.3)."""
    return rel.split("/", 1)[0] == SHEAFS_OWN


def _servable(rel: str) -> bool:
    """A name the hub can serve: markdown, never inside `.git` or `node_modules` or the root's
    `.sheaf/`, and spelled in UTF-8 (a URL cannot carry any other)."""
    if (not rel.endswith(".md") or any(p in (".git", "node_modules") for p in rel.split("/"))
            or _sheafs_own(rel)):
        return False
    try:
        rel.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _kept(root: Root) -> Callable[[str, bool], bool]:
    """`(rel, linked) -> bool`: whether 8.2 leaves the file `rel` of `root` to that root, and not to a git
    directory it lies in (`in_git_dir`); asked once per real folder. `linked` is whether the file is
    a link, which the caller knows from its `lstat`: only a link is resolved file by file, any other
    file lies in its folder's real folder, found once per folder."""
    top, seen, real_of = os.path.realpath(root.path), {}, {}

    def kept(rel: str, linked: bool) -> bool:
        if linked:
            real = os.path.realpath(os.path.join(top, rel))
            folder = os.path.dirname(real)
        else:
            here, _, name = rel.rpartition("/")
            if here not in real_of:
                real_of[here] = os.path.realpath(os.path.join(top, here))
            folder = real_of[here]
            real = os.path.join(folder, name)
        if folder not in seen:
            seen[folder] = not in_git_dir(Path(real), root)
        return seen[folder]
    return kept


def _walk(top: Path) -> Iterator[str]:
    """The name of every markdown file under `top`, in walk order, skipping `.git`, `node_modules`
    and every folder whose name starts with `.` (D15)."""
    for folder, dirs, files in os.walk(top):
        dirs[:] = sorted(d for d in dirs if d != "node_modules" and not d.startswith("."))
        under = os.path.relpath(folder, top).replace(os.sep, "/")
        for name in sorted(files):
            if name.endswith(".md"):
                yield name if under == "." else f"{under}/{name}"


def _capped(top: Path, names: Iterable[str], kept: Callable[[str, bool], bool]) -> Listing:
    """The first LIST_CAP of `names` that are documents of the root: what `resolve` would serve,
    a regular file inside it, and kept by `kept`; the rest of them counted (D15), up to
    `COUNT_LIMIT`, where the count stops."""
    docs, more, folders = [], 0, {}
    for rel in names:
        if not (_servable(rel) and (found := _stat_inside(top, rel, folders)) and kept(rel, found[1])):
            continue
        if len(docs) < LIST_CAP:
            docs.append(Found(rel, found[0]))
        else:
            more += 1
            if more >= COUNT_LIMIT:
                break
    return Listing(sorted(docs, key=lambda d: d.rel), more)


def list_documents(root: Root) -> Listing:
    """The markdown files of a root, sorted by path. A git root asks git (tracked and
    untracked, minus gitignored; nothing when git gives no answer); any other folder is walked.
    What `resolve` would refuse is not listed, nor what `document` would: a file that 8.2 keeps
    from the root for lying in a git directory, which is its own folder's root (rule 3)."""
    top = Path(os.path.realpath(root.path))
    if not os.path.isdir(top):              # gone, or the hub may not enter it (`Root.closed`)
        return Listing([], 0)
    names = _git_names(top) if root.git else _NOT_A_REPO
    if names is None:                      # git gave no answer: list nothing it has not vouched for
        return Listing([], 0)
    return _capped(top, _walk(top) if names is _NOT_A_REPO else sorted(set(names)), _kept(root))
