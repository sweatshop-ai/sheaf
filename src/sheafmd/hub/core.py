"""
sheafmd.hub.core — the Hub: every open document, the files it keeps, and the watcher's step.

No socket and no thread here: `Hub` is what the request handler (handler.py) talks to and what
the server (server.py) drives. A test builds one and calls `tick()` itself.

A document is served from an Entry: its LiveDocument, its event bus, and the page's HTML in
memory (no file in /tmp, SPEC 8.9).
"""
import errno
import json
import os
import re
import secrets
import sys
import threading
import time
import traceback
import uuid
from contextlib import ExitStack, contextmanager, nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .. import __version__, beneath, config, diagnostics, paths
from ..agents import registry
from ..agents.base import Adapter, Target
from ..render import RenderError, render_file
from ..source import STAMP_FORMAT, file_lock, lock_key, md_hash
from . import archive as archive_mod
from . import assets as assets_mod
from . import boxwait
from . import forwards as forwards_mod
from . import loose as loose_mod
from . import outgoing
from . import moves as moves_mod
from . import place
from . import projects
from . import proxy as proxy_mod
from . import readthrough
from . import roots as roots_mod
from . import team as team_mod
from . import sheaf_view
from . import state
from . import targets as targets_mod
from . import the_list
from . import waiting as waiting_mod
from . import session_tells as session_tells_mod
from . import visibility
from . import work as work_mod
from .tell import Tell, who as session_who
from .auth import Auth
from .commits import Author, Commits
from .events import Bus
from .index import Index
from .jobs import Jobs
from .writelog import WriteLog
from .live import LiveDocument

# What a render may set (SPEC 8.3). Every other key of docs.json is the hub's own.
SETTING_KEYS = ("title", "toc", "max_image_width", "by", "for", "theme", "credit")

_META_RE = re.compile(r'(<script id="rd-edit-meta" type="application/json">)(.*?)(</script>)', re.S)
_ALIAS_RE = re.compile(r"s-[0-9a-f]{16}\.md")        # the opaque name `Hub.alias` gives a Shared page (9.11)


@dataclass(frozen=True)
class MemberTarget:
    """What a member's page is told of its target (10.1): the agent shape or None, what the reader can do, the
    lines under Tell, and the targets they may pick."""
    agent: dict | None
    can: list
    lines: dict
    picks: list


@dataclass
class Entry:
    address: str
    file: Callable[[], Path]     # where its file is now: a rectoverso of the list's root is found by its name (9.11)
    root_id: str = ""            # the id of the root it was made for (SPEC 8.2), which its page carries (10.1)
    file_root: str = ""          # the id of the root its file was found in when it was opened (rule I): see `Hub._entry`
    live: LiveDocument | None = None
    bus: Bus = field(default_factory=Bus)
    html: str = ""
    opened: bool = False         # a tab connected since this document was last rendered
    rendered: bool = False       # `sheaf open` rendered it since this hub started
    last_stat: tuple | None = None
    rebuild_failure: tuple | None = None  # (the file's (mtime, size), the error) of the last failed rebuild
    log: list = field(default_factory=list)        # the render log of the last build
    warnings: list = field(default_factory=list)   # link-rule warnings not yet handed to a command
    first: bool = True                             # no build has run yet
    images_scope: tuple | None = None              # the image rule its last build read: `Hub._image_scope` (9.9)

    where: Callable[[], tuple] | None = None     # (the root's folder, the path in it) of its file now: what is opened beneath
    last_where: tuple | None = None              # what `where` last found: kept for a root forgotten under a write
    judge: Callable | None = None                # raises for an opened file that is not the one this document is of

    @property
    def path(self) -> Path:
        """The document's file as it is found now (9.11: a move renames the file of a rectoverso, never its entry)."""
        return self.file()

    def open(self):
        """Its file opened beneath its root, the one open (`sheafmd.beneath`), judged: NotFound-like OSError for a file of
        a private root this document is not of, or one that left the root."""
        top, rel = self.where()
        op = beneath.open_beneath(top, rel)
        try:
            self.judge(op)
        except BaseException:
            op.close()
            raise
        return op

    def stat(self):
        """The `os.stat_result` of its file, of the descriptor that was opened and judged."""
        with self.open() as op:
            return os.fstat(op.fd)

    def read(self) -> str:
        """Its file's text, read from the descriptor that was judged."""
        with self.open() as op:
            return op.text()


RESTART_TOLD_TTL = 30            # seconds a restart that was announced is still expected


def _project(address: str) -> str:
    """`<client>/<project>` of a rectoverso of the list's root at that address (9.10)."""
    return "/".join(roots_mod.Address.parse(address).rel.split("/")[:2])


class Hub:
    def __init__(self, port: int, key: str, *, started_by: str = "cli", service: bool = False,
                 version: str = __version__, clock=time.time, proxy=None, person: str | None = None):
        self.port, self.version, self.service = port, version, service
        self.assets = assets_mod.load(version)   # /_/mount.js and .css as this hub serves them to its end (#179)
        self.proxy = proxy                       # the checked `[proxy]` table (9.9), None in loopback mode
        # the agency tiroir's client tiroirs, read through (9.9); None for a tiroir with none. The call is the channel's (`outgoing.call`).
        self.clients = readthrough.Clients(proxy.clients, self.peer_call) if proxy is not None and proxy.clients else None
        self.started_by, self.clock = started_by, clock
        self.auth = Auth(key, port)
        self.boot = str(uuid.uuid4())
        self.started = time.time()
        self.person = person if person is not None else config.user_name()   # the start hands over the one it read
        self.roots = roots_mod.Roots()
        self.roots.placer = lambda root, rel: place.physical(self, root, rel)
        self.versions = state.Versions()
        self.writes = WriteLog()                 # one line per write to a page, whatever the path (the Write log)
        self.commits = Commits(self.record, self._writers_out, self.roots.all,
                               lambda: bool(self._private_paths), pulling=self.pulling, pulled=self.pulled, renamed=self.renamed)   # the roots that commit (8.11); the rewrite guard while a private root is configured
        self._told_projects: set = set()         # what check_projects warned of this run (8.12)
        self._projects: dict = {}                # root id -> (stat key, entries | Invalid | None) of its projects.toml
        self._listing = threading.local()        # per thread: what `projects_remembered` keeps for the listing in progress
        self._grants_seen: dict = {}             # root id -> the projects_of answer the open tabs were last told (8.12)
        self._grants_last: dict = {}             # root id -> what projects_of gave the last tick
        self.told_place: set = set()             # (address, quarantined | "undecided") a place-refused row named this run (9.11)
        self.told_link: set = set()              # the (root id, path) a link-ignored row named this run (9.11)
        self.told_ignored: set = set()           # the roots a private-ignored row named this run (9.11)
        self._front: dict = {}                   # {file: (its stat, its front matter, its assignees)}, for 9.11
        self._private_seen: dict = {}            # {address: the member a private root held it for}, `place.private_member`
        self.the_list = None                     # the list (9.10): a the_list.TheList, set by the server
        self.transcribe = None                   # the dictation relay (8.5): a transcribe.Relay, set by the server
        self.blamed: dict = {}                   # {(real path, md_hash): (pressers, monotonic time or None)}: once per text,
                                                 # for the list's rows and the pages' buttons alike (9.10, 10.11)
        self.docs = state.Docs()
        self.seen = state.Seen()
        self.member_seen = state.MemberSeen()
        self.shared_ids = state.SharedIds()           # the opaque names of the pages Shared with a member
        self.forwards = forwards_mod.Forwards()        # where an address a page left now leads (9.11)
        self.member_opened = state.MemberOpened()     # the change of each Shared page that a member last had open
        self.index = Index(self)
        self.tokens = state.Tokens()
        self.waiting_tells = waiting_mod.Waiting(self)    # the Tells that wait for an agent (9.8)
        self.session_tells = session_tells_mod.SessionTells(self)    # the Tells that wait for a laptop session (9.8)
        self.box_waits = boxwait.BoxWaits(lambda: self.clock())    # the drops for James's window (9.12, #115)
        self.entries: dict[str, Entry] = {}
        self.index_bus = Bus()                   # the index streams (SPEC 8.8)
        self._index_opening = threading.Lock()   # one index stream opens at a time
        self._lock = threading.RLock()
        self.pdf_lock = threading.Lock()         # one headless Chrome at a time
        # Stands in for the CSP nonce in the HTML kept in memory; the handler swaps in a fresh
        # nonce per response. Unguessable, so no document can hold it.
        self.placeholder = secrets.token_hex(12)
        self.stop_requested: str | None = None
        self.on_stop = None                      # the server's callback: (reason) -> None
        # One lock for "may a job start" and "may an upgrade stop be taken": under it, no job
        # starts once an upgrade stop is taken, and no upgrade stop is taken while a job runs
        # (SPEC 8.4). Locks taken inside it: the job runner's, then a document's.
        # Re-entrant, like `_stop_lock`: a second SIGTERM can interrupt the signal handler of the
        # first, in the same thread, while the first holds either, and must not wait for it.
        self.admit = threading.RLock()
        self.moving: set = set()                 # addresses a move is renaming: no Tell starts on one (moves.py), read and written under `admit`
        self._stop_lock = threading.RLock()
        self.upgrading = False
        self.told_restart = False                # an upgrade stop that came as a signal, after `expect_restart`
        self._restart_told_at: float | None = None
        self.tell_wait = config.tell_wait()
        self.versions.prune()
        # Every Tell child, and the address a push says it comes from (SPEC 8.10, 11.4).
        self.runner = Jobs()
        self.sender = f"uds:{paths.hub_socket(port)}"
        self.tell = Tell(self)
        # Real path of every CONFIGURED private root -> id of the member whose it is: recorded before any validation,
        # whether the root registers or is refused, and never shrunk (`place.in_private`, SPEC 9.11 rule A).
        self._private_paths: dict[str, str] = {}
        self._repos = None          # the clones of the repos whose pages are reported (13): `hub.repos.Repos` where the tiroir makes them
        self._private_ids: dict[tuple, str] = {}    # (st_dev, st_ino) of each, so a spelling in another case is the same folder
        self._private_by_identity: set[str] = set()     # ids of roots whose folder is a private one, spelled otherwise
        self._private_good: set[str] = set()       # those that registered: placement only, never privacy
        self.roots.private_paths = lambda: self._private_paths
        self.roots.hidden = self._is_private_root
        self.roots.registered = self._note_identity       # rule E: no address of its own, registered or refused
        self._register_private_roots()
        self.loose = loose_mod.Loose(self)       # a member's loose root, by their id (the door's `create` with no root)
        self.team = None                         # the agency's Team comments (SPEC 9.11): none until `keep_team`
        self.team_gate = None                    # who may open a client page: set with the store
        if self.clients is not None:
            self.keep_team()
        self.loose.attach()
        self.archive = archive_mod.Archive(self)      # archived, kept and trashed loose pages (8.6)
        for r in self.roots.all():
            self._note_identity(r)      # the roots of an earlier run, registered before the private folders were known
        self.commits.seed(self.roots.all())      # the rewrite guard's first pull is guarded, not free

    def _is_private_root(self, root) -> bool:
        """Whether `root` is a private root: by its path, and by the identity of its folder, so a second spelling of
        it (a bind mount, a case-folded name) is no address either."""
        return str(root.path) in self._private_paths or root.id in self._private_by_identity

    def _note_identity(self, root) -> None:
        """Once, as `root` is registered (never at a request, where a folder exchanged for a link would be read
        as the private one for as long as it is cached): whether its folder is a private one under another spelling."""
        if self._private_ids and place.identity(str(root.path)) in self._private_ids:
            self._private_by_identity.add(root.id)

    @property
    def private_roots(self) -> dict[str, str]:
        """Root id -> id of the member whose private root it is; empty without one. Judged by the root's real path,
        not by its id: a root forgotten and registered again has a new id and is still private."""
        return {r.id: self._private_paths[str(r.path)] for r in self.roots.all() if str(r.path) in self._private_good}

    def _register_private_roots(self):
        """Register the private root of each member that has one, as the list's root is registered. A folder that
        is gone, or is not the top of a git work tree of its own, is none: git is asked first, so such a folder
        writes nothing to the roots registry, and the row says so. A root registered at an earlier start whose
        `.git` has gone since is refused again here, whatever the registry still says."""
        for m in self.proxy.members.values() if self.proxy is not None else ():
            if not m.private_root:
                continue
            folder = Path(os.path.realpath(m.private_root))
            if (ident := place.identity(str(folder))) is None or not folder.is_dir():
                raise proxy_mod.ProxyError(f"the private root {folder} of {m.name} is not a folder: the hub does not start "
                                           "without it (SPEC 9.11)")
            self._private_ids[ident] = m.id
            self._private_paths[str(folder)] = m.id     # before the checks below: a refused root is as private as any
            root = None
            if folder.is_dir() and proxy_mod.git_top(str(folder)).casefold() == str(folder).casefold():
                root = self.roots.for_document(folder / projects.FILE)
            if root is None or root.path != folder or not root.git:
                self.record("private-root-refused", None, member=m.id,
                            error="the private root is not the top folder of a git work tree")
                continue
            self._private_good.add(str(folder))
        for r in self.roots.all():              # rule A: no root encloses, or lies inside, a private root
            if (inner := next((p for p in self._private_paths if roots_mod.nests(r.path, p)), None)) is not None:
                raise proxy_mod.ProxyError(f"the root {r.path} encloses or lies inside the private root {inner}: "
                                           "the hub does not start with one (SPEC 9.11)")

    # ── documents ────────────────────────────────────────────────────────────
    def _versions_of(self, root, named: str = "", strict: bool = False) -> state.Versions | None:
        """The versions store of `root`'s documents: inside it with `versions = "root"` (7.4), else the
        state folder's, also when its `.sheaf.toml` cannot be read; with `strict` (a private root's) that is
        None instead, so its text never reaches the state folder. `named` is the root of the documents'
        addresses when it is not `root` (a private rectoverso is addressed under the list's root): the prefix the
        store strips, so its folder is the one a commit of the file names."""
        try:
            inside = config.load_root_config(root.path, warn=lambda line: None).versions_inside
        except config.ConfigError:
            if strict:
                return None
            inside = False
        if inside:
            return state.Versions(root.path, named or root.name)
        return None if strict else self.versions

    def _store_of(self, address: str, root, bound: str):
        """The versions store of the rectoverso named `address` as its file is now placed, found at each call, not when
        its document was opened, for a document bound to the root `bound`: one opened for a file of the list's root
        keeps no private text there once a private file holds the name, and one opened for a private file stores
        nothing once that file is gone. None when the file cannot be decided (a name two roots hold, a private root
        that cannot be looked at, a file that left the root the document was made for): nothing is stored, a full
        disk's cost."""
        try:
            at = place.file_at(self, address, bound)
        except roots_mod.NotFound:
            return None
        if at is None:
            return self._versions_of(root)
        return self._versions_of(at[0], root.name, strict=at[0].id in self.private_roots)

    def check_projects(self, root, rels):
        """Warn of each rectoverso folder of `root` (its documents `rels`) that the root's `projects.toml`
        does not name, and of a file that cannot be read, once per hub run (8.12)."""
        try:
            entries = projects.read(root.path, self)
        except projects.Invalid as e:
            if (root.id, None) not in self._told_projects:
                self._told_projects.add((root.id, None))
                self.record("projects-invalid", None, root=root.name, error=str(e))
                print(f"sheaf: {root.path / projects.FILE}: {e}", file=sys.stderr, flush=True)
            return
        if entries is None:
            return
        for folder in projects.unlisted(entries, rels):
            if (root.id, folder) in self._told_projects:
                continue
            self._told_projects.add((root.id, folder))
            self.record("project-unlisted", None, root=root.name, folder=folder)
            print(f"sheaf: {root.name}/{folder} holds rectoversos and {projects.FILE} has no entry for it",
                  file=sys.stderr, flush=True)

    @contextmanager
    def _writers_out(self, root, files):
        """Hold what a writer of each of `files` (absolute paths in `root`'s repo) holds before the repo's commit
        lock: the lock of its rectoverso's name, in every root that holds the file and whose rectoversos the hub places, then
        its file lock (9.11). A pull (8.11, #62) holds it while it changes them, so no write lands between its look
        at a file and its new text. A pull of one root changes the files of every root of its repo, so the names are
        those of all of them, not of `root` alone, taken in one order, that of their locks' keys: a writer that
        moves a rectoverso of another root holds its name before its files, as the pull does, and the two never wait on
        each other (#76)."""
        names = set()
        listed = next((r for r in self.roots.all() if place.applies(self, r.name)), None)
        for r in self.roots.all():
            if place.applies(self, r.name):
                at = r
            elif r.id in self.private_roots and listed is not None:
                at = listed                  # a file of a private root is named, and locked, as the list's
            else:
                continue
            top = os.path.realpath(r.path)
            for f in files:
                rel = os.path.relpath(f, top)
                if not rel.startswith("..") and (name := place.logical(rel.replace(os.sep, "/"))):
                    names.add((os.path.realpath(at.path), name, at.name))
        with ExitStack() as held:
            for _, name, at in sorted(names):
                held.enter_context(place.held(self, f"{at}/{name}"))
            # One lock per file, not per path: a link and its file are one lock, and flock taken twice waits on itself.
            for _, f in sorted({lock_key(f): f for f in files}.items()):
                held.enter_context(file_lock(f))
            yield

    @property
    def repos(self):
        return self._repos

    @repos.setter
    def repos(self, repos):
        """The clone store: it registers the clones it serves in this hub's registry, moves a clone's HEAD as a pull moves its
        files (`Commits.moved`), and a clone already registered (a restart) gets its token for git again (SPEC 14)."""
        self._repos = repos
        if repos is not None:
            repos.roots = self.roots
            repos.mover = self.commits.moved
            repos.holding = self.commits._repo_lock
            for root in self.roots.all():
                if root.clone:
                    repos.credential(root.clone)

    def clone_of(self, address: str) -> str:
        """The repo whose clone serves `address`, or "" for any other page."""
        root = self.roots.get(roots_mod.Address.parse(address).root)
        return root.clone if root is not None and self._repos is not None else ""

    def wake_for_write(self, doc, key=None) -> None:
        """A write names the page `doc` (an address, the name a page was Shared under, or the absolute path of its file): when
        it is a page of a clone that sleeps, or whose folders are out, the clone wakes first, so the write finds its file
        (SPEC 13). Only the page's recorded owner (`key`, as a render report
        recorded it) or a caller bound to no member (`key` None) wakes a clone: while it sleeps its front matter cannot be
        read, so who else may see the page is not known, and a caller who may not write is refused by the write itself.
        Any other name is left to the write's own refusal."""
        if not isinstance(doc, str) or self._repos is None:
            return
        try:
            named = [self.unalias(doc)] if not doc.startswith("/") else []
            if doc.startswith("/") and (root := self.roots.lookup(Path(doc))) is not None:
                named = [str(roots_mod.Address(root.name, Path(os.path.realpath(doc)).relative_to(root.path).as_posix()))]
            for address in named:
                if repo := self.may_wake(address, key):
                    self._repos.wake(repo)
        except Exception:
            return

    def may_wake(self, address: str, key=None) -> str:
        """The repo of the clone page `address` when a write by `key` wakes it: the page's recorded owner (the owner its front
        matter names, else the reporter, matched without regard to case) or a caller bound to no member (`key` None).
        "" for any other page and caller."""
        a = roots_mod.Address.parse(address)
        root = self.roots.get(a.root)
        if root is None or not root.clone or self._repos is None:
            return ""
        owner = self._repos.owner_of(root.clone, a.rel)      # `named` before the reporter, as the page is judged
        if isinstance(owner, str) and (key is None or key.casefold() == owner.casefold()):
            return root.clone
        return ""

    def read_only_line(self, address: str, waking: bool = False) -> str:
        """Why the page at `address` may not be written, in one sentence naming the `.sheaf.toml` line that would change
        it; "" for a page that may be written. A page of a repo's clone is read-only while the clone has no save branch
        (no `dev`, and no branch the repo's `.sheaf.toml` names) or its HEAD is not on it (SPEC 14). `waking`: the reader's
        write wakes a sleeping clone (`may_wake`), so its sleep is no reason to refuse the reader."""
        repo = self.clone_of(address)
        if not repo:
            return ""
        return self._repos.read_only_line(repo, waking)

    def committed(self, address: str, member=None, what: str = "edit", by: str | None = None,
                  gone: str | None = None, author: Author | None = None):
        """A write went to `address`, by `member` (a proxy.Member), by `by` (the display name of a door
        caller), by `author` when given (the hub itself, for a move of the poll) or else by the hub's person:
        a commit, in a root that commits (8.11). `gone`: the path in the root the document moved from (9.11). The
        caller holds the rectoverso's name (`place.held`): a write and its commit are one step under it, so no other
        write of the name comes between, and a commit never carries another's write."""
        if not place.owns(self, address):
            raise RuntimeError(f"{address} committed outside its name's lock (9.11)")
        a = roots_mod.Address.parse(address)
        root = self.roots.get(a.root)
        if root is None:
            return
        if place.applies(self, a.root):
            try:
                held = self._bound(address)              # the file an open document was made for, no other
                got = place.file_at(self, address, held.file_root if held else "")
            except roots_mod.NotFound:
                self.record("commit-refused", address, why="its file is not where the rectoverso was opened")
                return
            root, rel = got if got else (root, place.file_rel(self, root, a.rel))
        else:
            rel = a.rel
        if author is not None:
            who = author
        elif member is not None:
            who = Author(member.name, proxy_mod.commit_email(member, self.proxy.origin))
        else:
            who = Author(by or self.person, "")
        self.commits.saved(root, rel, who, what, gone=gone, key=a.rel)

    def file(self, address: str, placed: bool | None = None, bound: str = "") -> Path:
        """The path of the file the document at `address` names, there or not, unchecked: in the list's root the one
        file that holds a rectoverso's name, wherever it lives (9.11), else the address's own path. `placed` is whether
        the hub places the root's rectoversos (`place.applies`), when the caller knows it. `bound`: the private root an
        open document was made for; its file is never found anywhere else (`place.file_at`)."""
        at = roots_mod.Address.parse(address)
        root = self.roots.get(at.root)
        if root is None:
            raise roots_mod.NotFound(address)
        if placed is None:
            placed = place.applies(self, at.root)
        if not placed:
            return root.path / at.rel
        got = place.file_at(self, address, bound)       # raises where the file cannot be decided: never the list's path
        return got[0].path / got[1] if got else root.path / place.file_rel(self, root, at.rel)

    def _where_of(self, e, name: str) -> tuple:
        """`where` for an entry. A root forgotten while a write or a rebuild of the entry is under way leaves it the folder
        it last found: the work finishes there, opened beneath that folder and judged as ever, and never in the folder
        that takes the name next."""
        try:
            e.last_where = self.where(e.address, bound=e.file_root if place.applies(self, name) else "")
        except roots_mod.NotFound:
            if self.roots.get(roots_mod.Address.parse(e.address).root) is not None or e.last_where is None:
                raise
        return e.last_where

    def where(self, address: str, bound: str = "") -> tuple:
        """(the folder of the root, the path in it) of the file the document at `address` names, as `file` finds it, to be
        opened beneath that folder: no path is resolved to a file here. `bound` as in `file`."""
        at = roots_mod.Address.parse(address)
        root = self.roots.get(at.root)
        if root is None:
            raise roots_mod.NotFound(address)
        if not place.applies(self, at.root):
            top, rel = self.roots.locate(address)
            return top.path, rel
        got = place.file_at(self, address, bound)
        return (got[0].path, got[1]) if got else (root.path, place.file_rel(self, root, at.rel))

    def open_in(self, root, rel: str):
        """`rel` below the root `root` opened beneath it (`sheafmd.beneath`), for the hub's own reads: judged on what was
        opened, a file of a private root only where `root` is that private root (rule A, SPEC 9.11). OSError for what is
        not a file below the root, or is a private root's under another root."""
        op = beneath.open_beneath(root.path, rel)
        self.check_opened(op, self.private_roots.get(root.id))
        return op

    def check_opened(self, op, member):
        """`op` closed and a FileNotFoundError raised unless the private root it lies in is `member`'s (None: no private
        root). The one judgement of every document the hub opens for itself."""
        if place.opened_private(self, op) != member:
            op.close()
            raise FileNotFoundError(2, "not a file of this root", op.rel)

    def url(self, address: str) -> str:
        return f"http://127.0.0.1:{self.port}{roots_mod.url_path(address)}"

    def entry(self, address: str) -> Entry:
        """The entry of a document, made on first use. Raises roots.NotFound for an address
        that is no markdown file inside a root, every time: a file that has gone is gone. Nor is a
        file that 8.2 keeps from the root for lying in a git directory, as the door says (12).
        The file is found before the hub's lock is taken, and its root looked at again under it: a
        `forget_root` that took the lock in between makes the address name nothing, as it does for
        a request that comes after it. All of it under the lock of a rectoverso's name (9.11), taken before
        the hub's: the file is found and first read and rendered where no move takes it."""
        with place.held(self, address):
            return self._entry(address)

    def _bound(self, address: str):
        """The entry the hub holds for `address`, None when there is none or when another root now holds its file,
        which drops it: a write that does not go through `entry` (the door's) commits in the root of the file."""
        e = self.entries.get(address)
        if e is not None and self.private_roots:
            got = place.where_is(self, address)
            if got is not None and got[0].id != e.file_root \
                    and not place.undecided(self, roots_mod.Address.parse(address).rel):     # as `_entry`: kept, so the commit raises
                with self._lock:
                    if self.entries.get(address) is e:
                        del self.entries[address]
                return None
        return e

    def _entry(self, address: str) -> Entry:
        name = roots_mod.Address.parse(address).root
        root = self.roots.get(name)
        path = self.roots.document(address)
        with self._lock:
            e = self.entries.get(address)
            if e is not None and self.private_roots and place.applies(self, name):
                # The store and the file an entry uses cannot outlive the root they were chosen for: one bound to
                # a private root is refused when its file is not there (`file_at`); one bound to a root other than the one that now holds the file is
                # dropped, and made again.
                got = place.where_is(self, address)
                if got is not None and got[0].id != e.file_root \
                        and not place.undecided(self, roots_mod.Address.parse(address).rel):     # never rebound while a private root is not seen
                    del self.entries[address]
                    e = None
                elif e.file_root in self.private_roots:
                    place.file_at(self, address, e.file_root)
            if e is not None:
                return e
            if self.roots.get(name) != root:
                raise roots_mod.NotFound(address)
            if place.applies(self, name):
                # Keyed by the rectoverso's name: its file is found again at each read, and under the name's lock at
                # each write, so a move of the file changes nothing the hub keeps (9.11).
                def file():
                    return Path(os.path.realpath(self.file(address, placed=True, bound=e.file_root)))

                def hold():
                    return place.held(self, address)
            else:
                file, hold = (lambda: path), None
            e = Entry(address, file, root.id)
            at = place.file_at(self, address) if self.private_roots and place.applies(self, name) else None
            e.file_root = at[0].id if at else root.id
            e.where = lambda: self._where_of(e, name)
            e.judge = lambda op: self.check_opened(op, self.private_roots.get(e.file_root))
            e.live = LiveDocument(file, render=lambda text: self._rendered(e, text), entry=e,
                                  publish=e.bus.publish, by=self.person, clock=self.clock,
                                  versions=(lambda: self._store_of(address, root, e.file_root)) if self.private_roots and place.applies(self, name)
                                  else self._versions_of(root), address=address, hold=hold)
            e.live.session_to = lambda: self.session_name(address)
            e.live.agent_tells = lambda: self.waiting_tells.waits(address, None, sweep=False)   # the hub person's (9.8)
            e.live.tells_lock = self.waiting_tells._lock
            e.live.refresh(force=True)           # the first render: e.html
            self.entries[address] = e
            return e

    def _rendered(self, e: Entry, text: str) -> str | None:
        """Render `text` for `e`; answers the branch the page was rendered on (a clone's page), which the live document keeps
        with the hash. The render runs under the pages' lock, which a switch of the clone takes, so HEAD is the text's."""
        repo = self.clone_of(e.address)
        branch = self._repos.head_of(repo) if repo else None
        e.html = self._build(e, text, branch=branch)
        e.rebuild_failure = None         # every rebuild that works passes here: the next failure is news
        return branch

    def _settings(self, address: str) -> dict:
        s = self.docs.get(address)
        return {k: s.get(k) for k in SETTING_KEYS}

    def _build(self, e: Entry, text: str, *, mount: bool = False, count: bool = True, branch: str | None = None) -> str:
        s = self._settings(e.address)
        root = self._file_root(e)
        meta = {"doc": e.address, "root": e.root_id, "boot": self.boot, "version": self.version,
                "service": self.service, "me": self.person,
                "agent": None, "can": [], "lines": {}, "seen": {}}
        if self.clone_of(e.address):
            # The branch this page is read on, the one `_rendered` read with the text its `hash` is of: its save carries it
            # back and a switch since is refused (SPEC 14). `_fresh_meta` keeps it, whatever HEAD is when the page is sent.
            meta["branch"] = branch
        log = []
        scope = self._image_scope(root, e.address)
        # The link rule is a warning for whoever renders the document, said once: the hub's
        # re-renders after a save say nothing, so a bare host name is not reported on every save.
        html = render_file(e.path, share=False, src=text, title=s["title"],
                           toc=s["toc"] or "auto", max_image_width=s["max_image_width"] or 1400,
                           by=s["by"], for_=s["for"], theme=s["theme"], credit=s["credit"], log=log,
                           root=root.path if root else None, extra_meta=meta,
                           script_nonce=self.placeholder, image_ok=self._image_rule(root, e.path, e.address, scope),
                           image_read=self._image_read(root) if self.proxy is not None else None,
                           warn=e.warnings.append if e.first and count else None, mount=mount)
        if count:
            e.log, e.first = log, False
            e.images_scope = scope          # once the build worked
        return html

    def share_copy(self, e: Entry) -> str:
        """The share copy of the document as the file is now, with the settings it is shown with."""
        s = self._settings(e.address)
        root = self._file_root(e)
        return render_file(e.path, share=True, src=e.read(), title=s["title"], toc=s["toc"] or "auto",
                           max_image_width=s["max_image_width"] or 1400, by=s["by"],
                           for_=s["for"], theme=s["theme"], credit=s["credit"], log=[],
                           root=root.path if root else None, image_ok=self._image_rule(root, e.path, e.address),
                           image_read=self._image_read(root) if self.proxy is not None else None)

    def _file_root(self, e: Entry):
        """The root the image rules judge the page of `e` against: the root its file is in, so the images of a rectoverso of
        a member's private root are judged there and show (rule H); the root of its address for any other rectoverso."""
        at = self.roots.get(roots_mod.Address.parse(e.address).root)
        if at is None or not self.private_roots:
            return at
        found = self.roots.lookup(e.path)
        return found if found is not None and found.id in self.private_roots else at

    def _image_read(self, root):
        """The bytes of a local image, from one open beneath `root` (`sheafmd.beneath`), refused when what was opened is
        in a private root other than `root` itself (9.11): the rule above judges the image's real path, this judges what
        is read. A private `root` is the one its rectoverso is in, and opens only beneath itself."""
        if root is None:                    # the image rule leaves every image out of a document in no root
            return None
        top = os.path.realpath(root.path)
        own = self.private_roots.get(root.id)

        def read(path) -> bytes:
            rel = os.path.relpath(path, top)
            if rel == ".." or rel.startswith("../"):
                raise PermissionError(errno.EACCES, "outside the root", str(path))
            with beneath.open_beneath(top, rel) as op:
                if place.opened_private(self, op) not in (None, own):
                    raise PermissionError(errno.EACCES, "in a private root", str(path))
                return op.bytes()
        return read

    def _image_rule(self, root, doc, address: str, scope: tuple | None = None):
        """In proxy mode, a local image is embedded only when the root 8.2 finds for its file is the
        document's own root (9.9 "Local images"), and, in a root with a `projects.toml`, when its
        `<client>/<project>` is in reach of the document's file `doc` for every reader of the rectoverso at `address`
        (8.12, #81): in every render of the hub, the page and the share copy alike. None in loopback mode: every
        local image, as 6.2 says. `scope`, when given, is the `_image_scope` a page's build read (`_build` keeps it
        on the entry once the build worked, so `catch_up` builds the page again once it changes)."""
        if self.proxy is None:
            return None
        if root is None:
            return lambda path: False
        by_project, outsider = scope if scope is not None else self._image_scope(root, address)
        top = os.path.realpath(root.path)
        at = os.path.relpath(os.path.realpath(doc), top)

        def ok(path) -> bool:
            if self.roots.lookup(path) != root:
                return False
            return not by_project or projects.image_in_reach(at, os.path.relpath(os.path.realpath(path), top),
                                                             outsider)
        return ok

    def _image_scope(self, root, address: str) -> tuple | None:
        """(whether a page of `root` judges its images by project, whether the rectoverso at `address` has a reader the
        project does not name). By project when the root has a `projects.toml`, read or not (8.12: a root without
        one grants as before). A reader the project does not name is an owner its `members` do not hold, since an
        owner opens their rectoverso whatever the file says; judged at the address and where its file is, and every owner
        when the file cannot be read (#81). One the hub cannot judge counts as such a reader. None in loopback mode
        or outside every root."""
        if self.proxy is None or root is None:
            return None
        entries = self.projects_of(root)
        if entries is None:
            return False, False
        try:
            # Judged where the file is as well as by the address, as `granted` judges (a link to another project).
            top = os.path.realpath(root.path)
            rels = {roots_mod.Address.parse(address).rel, os.path.relpath(os.path.realpath(self.file(address)), top)}
            owners = self.owners(address, list(self.proxy.members.values()))
        except Exception:
            return True, True               # an owner the hub cannot judge is no member: no project image goes in
        return True, any(not projects.grants(entries, rel, o.short) for o in owners for rel in rels)

    def _images_moved(self, e: Entry) -> bool:
        """Whether the page of `e` was built by another image rule than its root's `projects.toml` and its owners
        give now."""
        if e.images_scope is None:
            return False
        return e.images_scope != self._image_scope(self._file_root(e), e.address)

    def page(self, e: Entry, nonce: str, member=None, mount: str = "") -> str:
        """The page to send: the nonce of this response on its script, and the read state as it
        is now (it changes without the page being rendered again). For a `member` of proxy mode
        (9.9, 10.1) the meta block is theirs: their name and seen state, no agent and nothing it
        can do, the line of 10.6, `proxy` and their id, which keys their drafts (10.8). Both keep `root`,
        the id of the root the entry was made for (10.1): it is random and names no folder (9.9)."""
        html = e.html
        needle = f'nonce="{self.placeholder}"'
        at = html.rfind(needle)
        if at >= 0:
            html = html[:at] + f'nonce="{nonce}"' + html[at + len(needle):]
        found = list(_META_RE.finditer(html))
        if found:
            m = found[-1]
            meta = self._fresh_meta(e, json.loads(m.group(2)), member, mount)
            html = (html[:m.start(2)] + json.dumps(meta).replace("<", "\\u003c") + html[m.end(2):])
        return html

    def _fresh_meta(self, e: Entry, meta: dict, member, mount: str = "") -> dict:
        """The meta block as it is now: the read state and what changes without the page being rendered again. The page
        route and the mount route (#116) both send this, so a page mounted in the front reads what a framed one does."""
        # The buttons of the text the page draws: a write since its render brings a `changed` and a reload,
        # so none are drawn on the old text meanwhile (10.11).
        h, text = e.live.current()
        meta["actions"] = self.actions(e, member, text) if h == meta.get("hash") else []
        key = visibility.owner_key(member) if member is not None else None
        if line := self.read_only_line(e.address, waking=bool(self.may_wake(e.address, key))):
            meta["readonly"], meta["why_readonly"] = True, line
        if "branch" in meta and meta.get("readonly"):
            del meta["branch"]                  # a read-only page saves nowhere: it carries no branch to save on
        if member is None:
            meta["seen"] = self.seen.get(e.address)
            v = self.tell.view(e.address)
            meta["agent"], meta["can"], meta["lines"] = v.agent(), v.can(), v.lines
            meta["targets"] = targets_mod.choices(self, e.address)
        else:
            meta["doc"] = (f"{mount}/" if mount else "") + self.alias(member, e.address)      # a read-through page is told under `Clients/<client>` (9.9)
            meta.update(me=member.name, seen=self.member_seen.get(member.id, e.address), proxy=True,
                        member=member.id)
            work, can = self.member_work(e, member)
            if work is not None:
                meta["work"] = work
            mt = self.member_target(e.address, member, can)
            meta["agent"], meta["can"], meta["lines"], meta["targets"] = mt.agent, mt.can, mt.lines, mt.picks
            meta["way_back"] = sheaf_view.byline(self, e.address, member)
            if mount:                           # read through for another tiroir's member (9.9): read and comment, never edit, press or Tell here
                meta["edit"], meta["actions"], meta["targets"], meta["can"] = False, [], [], []
                meta.pop("work", None), meta.pop("way_back", None)
        return meta

    def member_target(self, address: str, member, can: list) -> MemberTarget:
        """The target of a member's page (SPEC 9.8, 10.1): their own, an agent of theirs, never the hub account's
        session. On a rectoverso whose Tells go to James's window (9.12) the target is not theirs to
        choose: none is shown and `picks` is empty."""
        lines = proxy_mod.member_lines()
        if "box-tell" in can:
            return MemberTarget(None, can, lines, [])
        pickable = targets_mod.choices(self, address, member)
        raw = targets_mod.stored(self, address, member)
        if raw is None:
            return MemberTarget(None, can, lines, pickable)
        v = targets_mod.agent_view(self, raw, member)
        return MemberTarget(v.shape, sorted({*can, "queue"}) if v.reaches else can, {"tell": v.line}, pickable)

    def mount_doc(self, e: Entry, member=None, mount: str = "") -> dict:
        """The rectoverso as the front mounts it (#116): {title, toc, html, config, css, version, script, assets}. The text
        is rendered now through the sanitiser's mount mode; the config is the meta block of `page`, so both read the
        same state."""
        h, text, branch = e.live.current_read()         # the hash and the branch of one render
        got = json.loads(self._build(e, text, mount=True, count=False, branch=branch))
        got["config"] = self._fresh_meta(e, got["config"], member, mount)
        got["version"] = self.version
        got.update(self.mount_fields())
        return got

    def peer_call(self, client: str, verb: str, body: dict) -> tuple:
        """The hub-to-hub channel to the client tiroir `client`: `(status, answer)`, OSError when it does not answer."""
        origin = self.proxy.clients.get(client) if self.proxy is not None else None
        if origin is None:
            raise OSError(f"no client tiroir is called {client}")
        return outgoing.call(origin, verb, body)

    def mount_fields(self) -> dict:
        """What every mount answer carries for mount.js (#179): `script`, the name of the scripts this hub serves, which
        a page running other scripts takes for an upgrade even under the same version; and `assets`, the name (`?v=`)
        of each asset: the style it links, and the script it hands the front's loader to load after an upgrade."""
        return {"script": self.assets["mount.js"].source, "assets": {n: a.tag for n, a in self.assets.items()}}

    def actions(self, e: Entry, member, text: str | None = None) -> list:
        """The buttons at the top of the page of `e` as `member` (None: the hub's own person) reads them (10.11,
        #111): the list's `buttons` of its text (`text`, else the one it holds now), each with `box`, [block, box's
        number among the task boxes of that block] where the document draws it, or None."""
        if text is None:
            text = e.live.current()[1]
        s = the_list.read_rectoverso("x.md", text)       # read for its boxes alone: the name is no matter
        if not (s.actions or s.pressed):
            return []
        fm = visibility.front_matter(text)
        owner = member is None or self.is_owner(member, e.address, fm)
        lines = [line for _, _, line, _ in s.pressed]
        root = self.roots.get(roots_mod.Address.parse(e.address).root)
        who = {}
        if lines and root is not None and root.git:
            try:
                who = the_list.pressers(self.blamed, Path(os.path.realpath(e.path)), text, lines)
            except OSError:
                who = {}
        out = []
        for x in the_list.buttons(s, who, self, member, owner):
            at = the_list.box_place(text, x.pop("line"))
            out.append({**x, "box": list(at) if at else None})
        return out

    def member_work(self, e: Entry, member):
        """The `work` of a member's page (None when it is not a rectoverso of the list's root) and its `can`:
        box-tell while the live session runs on the box and `[list]` names a `tell_dir` (10.1).
        The meta block and every /_/doc answer carry both, so a fork seen by the page changes what it offers."""
        st = work_mod.state(self, e.address, e.live.current()[1], member)
        if st is None:
            return None, []
        return self.work_meta(e, member, st), st.can

    def work_meta(self, e: Entry, member, st) -> dict:
        """What the page's Work on this shows a member (9.12, 10.1): the command that forks the rectoverso's session
        on their machine, the one that attaches to James's window when they have a shell on the box, the
        sessions and where the live one runs. None for a page that is not a rectoverso of the list's root."""
        out = {"sessions": st.sessions, "live": st.live}
        # The fork fetches the live session's transcript from /_/session: one on a laptop, none, or no
        # copy to serve it from (sessions_dir and work_dir, #146), nothing to fork.
        if st.forkable and work_mod.serves(st.cfg, st.member):
            out["fork"] = (f"uvx --from {work_mod.FORK_CLIENT} tiroir work "
                           f"{self.proxy.origin}{roots_mod.url_path(e.address)}")
        # James names a project's window <client>_<project>, and only when both parts are his SLUG
        # (agency-tiroir james.py `project_window`): a part with `_` would let a_b/c and a/b_c share one window,
        # and the `_` between the parts keeps a-b/c and a/b-c apart.
        parts = roots_mod.Address.parse(e.address).rel.split("/")[:2]
        window = "_".join(parts)
        # Kept as a guard: tmux and two shells read the command, so no `.`, `:` or space gets through.
        if (member.shell and st.cfg.attach and all(re.fullmatch(r"[a-z0-9][a-z0-9-]*", p) for p in parts)
                and re.fullmatch(r"[A-Za-z0-9_-]+", window)):
            out["attach"] = st.cfg.attach.replace("{window}", window)
        return out

    # ── the agent of a document ──────────────────────────────────────────────
    def target(self, address: str, kept: bool = False) -> Target | None:
        """The session the document's last render attached, or None (also for a stored target that cannot be
        read: it is never guessed at). `kept`: when the target is not a session now (an agent, or none), the
        session kept beside it, which a Tell already sent to it still runs in (a stop and the watcher use it)."""
        entry = self.docs.get(address)
        raw = entry.get("target")
        if kept and entry.get("session"):       # beside an agent, or beside the session a render replaced
            raw = entry["session"]
        if not raw or targets_mod.is_agent(raw):
            return None
        try:
            return Target.from_dict(raw)
        except ValueError:
            return None

    def tell_live(self, address: str) -> bool:
        """Whether a Tell runs on this document, waits for its reply or is being cancelled. Read without the
        document's lock (as `peek` is): callers ask it beside the docs lock, and a rebuild holds the other
        while it reads the first."""
        e = self.entries.get(address)
        return bool(self.runner.active("tell", address) or self.runner.active("stop", address)
                    or (e is not None and e.live.peek()[0]))

    def drop_kept(self, address: str, cid: str, told, again: bool = False) -> None:
        """The Tell of thread `cid` is about to be sent to `told`, the session the target was when it was
        looked up: the session a render kept beside the target for an earlier Tell is of no use now, and a
        Cancel of this one must not find it. Kept while a Tell of another thread still runs, and when a render
        moved the target off `told` since: that Tell goes to `told`, so it is kept beside the target if none is.
        A re-Tell of a thread still waiting (`again`) leaves what is kept: the first Tell runs there."""
        if again:
            return
        e = self.entries.get(address)
        busy = set(self.runner.active("tell", address)) | set(self.runner.active("stop", address))
        busy |= set(e.live.waiting() if e else ())
        if busy - {cid}:
            return

        def settle(entry: dict) -> dict:
            raw = entry.get("target")
            if isinstance(raw, dict) and not targets_mod.is_agent(raw) and raw.get("session") == told.session:
                entry.pop("session", None)
            elif not entry.get("session"):
                entry["session"] = {"kind": "session", **told.as_dict()}
            return entry
        self.docs.change(address, settle)

    def _told_session(self, entry: dict, live: bool) -> dict | None:
        """The session a Tell running on this document was sent to, as `entry` holds it, or None when no Tell
        runs: a render that would drop or replace it keeps it beside the target (a stop goes there)."""
        if not live:
            return None
        for raw in (entry.get("session"), entry.get("target")):
            if isinstance(raw, dict) and raw and not targets_mod.is_agent(raw):
                return raw
        return None

    def session_name(self, address: str) -> str:
        """What the page calls the session a Tell of this document goes to ("" when there is none)."""
        try:
            t = self.target(address, kept=True)
            return "" if t is None else session_who(t, self.adapter(t.agent))
        except Exception:
            return ""

    def adapter(self, agent: str) -> Adapter:
        return registry.adapter_for(agent, self.sender)

    def stop_jobs(self):
        """Kill every Tell child's process group, and let the pushes due go out within a bound, then end
        the hub's git (a clean stop, SPEC 8.4, 8.11, #95)."""
        self.runner.kill_all()
        self.commits.stop()

    def waiting(self, address: str) -> bool:
        """Whether a Tell waits on a thread of this document for an action reply."""
        e = self.entries.get(address)
        return bool(e and e.live.waiting())

    def tabs(self, address: str) -> int:
        e = self.entries.get(address)
        return e.bus.count() if e else 0

    # ── what the CLI asks (key) ──────────────────────────────────────────────
    def render(self, md: Path, settings: dict, target: dict | None) -> dict:
        """Register `md`, record the settings and target of this render (SPEC 8.3) and make the
        page. A render with other settings re-renders and tells the open tabs; it never
        restarts anything."""
        md = Path(md).resolve()
        try:
            address = self.roots.address(md)       # a file of a private root has no address of its own (9.11)
        except roots_mod.NotFound:
            raise RenderError(f"{md} is not in a root the hub serves.") from None
        with place.held(self, address), self._lock:        # the name's lock first (9.11), as `entry` takes it
            live = self.tell_live(address)         # beside the docs lock, not inside it
            def settle(new: dict) -> dict:
                old = dict(new)
                new["path"] = str(md)
                new["rendered"] = time.strftime(STAMP_FORMAT)
                for k in SETTING_KEYS:
                    new[k] = settings.get(k)
                # The latest render from an agent session sets the target; a render that finds no agent keeps
                # it, an agent's too; only `--agent none` clears it (SPEC 8.3, D19). The session an agent's
                # write took the target from is the new one's, so none is kept beside it, unless a Tell is
                # running: it was sent to the session the render drops or replaces, and a Cancel stops that one.
                if target is not None:
                    kept = self._told_session(old, live or self.tell_live(address))
                    new["target"] = None if target.get("agent") == "none" else {"kind": "session", **target}
                    new.pop("session", None)
                    if kept and (new["target"] or {}).get("session") != kept.get("session"):
                        new["session"] = kept
                else:
                    new.setdefault("target", None)
                return new
            old, new = self.docs.change(address, settle)
            existed = address in self.entries
            e = self.entry(address)
            if existed:
                self._refreshed(e)          # a file written on disk since, seen at this render
            if existed and (any(old.get(k) != new[k] for k in SETTING_KEYS)
                            or old.get("target") != new.get("target")):
                e.live.rebuild()
            e.opened, e.rendered = False, True
            warnings, e.warnings = e.warnings, []
            self.index.touch(address)
            return {"doc": address, "url": self.url(address), "tabs": e.bus.count(),
                    "log": list(e.log), "warnings": warnings}

    @contextmanager
    def page_lock(self, address: str):
        """The writer lock of the page at `address` (`LiveDocument.exclusive`), for a move of its file: held when the hub has
        the page, after the name's lock as a save takes it. Never builds an entry (that reads and renders the page, which a
        page that cannot be read or rendered must not stop a Delete for). A writer of a page with no entry holds the file's
        lock, which the move takes too."""
        e = self.entries.get(address)
        with e.live.exclusive() if e is not None and e.live is not None else nullcontext():
            yield

    def forget_document(self, address: str):
        """A page left its address (deleted into the trash): the entry goes and the pages open on it are told `gone`. Its
        versions stay, and come back with it when it does (8.6)."""
        with self._lock:
            e = self.entries.pop(address, None)
        if e is not None:
            e.bus.publish("gone", {"doc": address})

    def forget_root(self, name: str):
        """`sheaf roots forget`: take the root out, and its documents' entries with it (their
        render settings and read state, and the pages the hub holds). The documents themselves
        are files and stay where they are. Each page open on one of them is told `gone`, the last
        event of its stream (SPEC 8.8). Returns the root, or None when there was none."""
        with self._lock:
            root = roots_mod.forget(self.roots, self.docs, self.seen, self.versions, name,
                                    members=self.member_seen)
            self.member_opened.forget_prefix(roots_mod.Address.prefix(name))
            self.shared_ids.forget_prefix(roots_mod.Address.prefix(name))
            self.forwards.forget_prefix(roots_mod.Address.prefix(name))
            # After the registry lets go (a Tell queued from now on is refused, `Waiting.queue`) and before the
            # entries go, so the pages open on them hear `tell-cancelled` ahead of `gone`. A failure here must not
            # keep the root from being forgotten.
            try:
                self.waiting_tells.end_root(name, "the folder was forgotten")
                self.session_tells.end_root(name, "the folder was forgotten")
            except Exception:
                self.record_exception("tell-end-failed")
            for address in [a for a in self.entries if a.startswith(roots_mod.Address.prefix(name))]:
                e = self.entries.pop(address)
                # Its versions go under its own lock: a write still under way would put its text among
                # them after they went, and the document that takes the address next would know it,
                # and take the old page's requests as made against a version it handed out.
                e.live.forget()
                # After that write's own `changed`, which the page takes in first.
                e.bus.publish("gone", {"doc": address})
            # A Tell still running on a document that is gone: its dot, its
            # answer and its wait have nowhere to go, and the name may be taken at once. Also
            # when the registry no longer holds the root (another process forgot it, and this hub
            # reloaded the file): its entries were popped above all the same.
            self.runner.cancel_under(roots_mod.Address.prefix(name))
            if root is not None:
                self.index.forgot(name)
            return root

    def moved_page(self, old: str, new: str, by: str):
        """The page at `old` is now at `new`, its file moved (9.11): the Forward is written, and every store that is keyed by
        the address follows the page, so its settings, versions, read marks, Tells, Write log, keep, archived and seen
        marks and the opaque name it is Shared under are the page's still. Each store is carried on its own: one that fails is a row in the
        diagnostics log, and the others are carried all the same. The tabs open on `old` are told where it went."""
        root = self.roots.get(roots_mod.Address.parse(new).root)
        rel_old, rel_new = roots_mod.Address.parse(old).rel, roots_mod.Address.parse(new).rel
        steps = [lambda: self.forwards.add(old, new, by),
                 lambda: self.docs.rename(old, new), lambda: self.seen.rename(old, new),
                 lambda: self.member_seen.rename(old, new), lambda: self.member_opened.rename(old, new),
                 lambda: self.shared_ids.rename(old, new), lambda: self.waiting_tells.rename(old, new),
                 lambda: self.session_tells.rename(old, new), lambda: self.writes.rename(old, new),
                 lambda: (self._versions_of(root) or self.versions).rename(old, new),
                 lambda: loose_mod.marks_moved(root.path, rel_old, rel_new)]
        for step in steps:
            try:
                step()
            except Exception:
                self.record_exception("move-store-failed", new)
        with self._lock:
            e = self.entries.pop(old, None)
            self.entries.pop(new, None)         # an entry made for the address before the page came is made again
        if e is not None:
            # After the versions were carried (a version kept under the old key is the last of the old page, none of
            # the new one's): what the entry's document still holds at the old address goes, as `forget_root` does it.
            try:
                e.live.forget()
            except Exception:
                self.record_exception("move-store-failed", new)
            e.bus.publish("moved", {"doc": old, "to": new})
        for address in (old, new):
            try:
                self.index.touch(address)
            except Exception:
                self.record_exception("status-failed")

    def moved_remote(self, old: str, origin: str, to: str, by: str, landed: str, was: str = ""):
        """The page at `old` landed on the tiroir at `origin` as `to` (ticket 20): the Forward is written first, so the old address
        answers from this moment, then the Tells on the page end as cancelled, what the hub keeps of it is dropped, the page's file
        goes, and the tabs open on it are told where it went. The Write log keeps the page's lines: they are all that is left of
        what was written here. Each step is on its own, as `moved_page`'s are: one that fails is a row in the diagnostics log.
        The caller holds the page's writer lock and its file lock, so nothing here takes the hub's lock (it comes before them in
        `lockorder.ORDER`), and the entry's document, which takes the writer lock again to forget its versions, is not touched: the
        entry, the tabs and the index are the returned `finish`, which the caller runs once the file is gone and the locks are let go."""
        at = roots_mod.Address.parse(old)
        root = self.roots.get(at.root)
        opaque = self.shared_ids.known(old)      # the name a recipient's tab holds: told them as it was, once the store forgets it
        self.forwards.add_remote(old, origin, to, by, landed, was)
        for ending in (self.session_tells, self.waiting_tells):
            try:
                ending.end_page(old, "page moved")
            except Exception:
                self.record_exception("tell-end-failed", old)

        def forget(store):
            # Exactly this address: `forget_prefix` takes every address that starts with it, so the key goes under a name no
            # other page has first.
            gone = f"\0moved/{os.urandom(8).hex()}"
            store.rename(old, gone)
            store.forget_prefix(gone)
        steps = [lambda: forget(self.docs), lambda: forget(self.seen), lambda: forget(self.member_seen),
                 lambda: forget(self.member_opened), lambda: forget(self.shared_ids),
                 lambda: (self._versions_of(root) or self.versions).forget(old, inside=True),
                 lambda: loose_mod.marks_gone(root.path, at.rel)]
        for step in steps:
            try:
                step()
            except Exception:
                self.record_exception("move-store-failed", old)

        def finish():
            with self._lock:
                e = self.entries.pop(old, None)
            if e is not None:
                try:
                    e.live.forget()
                except Exception:
                    self.record_exception("move-store-failed", old)
                e.bus.publish("moved", {"doc": old, "to": to, "origin": origin, **({"opaque": opaque} if opaque else {})})
            try:
                self.index.touch(old)       # the file is gone by now: the row goes
            except Exception:
                self.record_exception("status-failed")
        return finish

    def open_index_stream(self, describe, accept=None):
        """A new index stream. The first one to open starts the board afresh, so a stream is
        told only what happens after it connects. Looking, starting the board and subscribing
        are one step: two first streams must not both start it, or the later board would hold
        a change the earlier stream was never told of."""
        with self._index_opening:
            if not self.index_bus.count():
                self.index.arm()
            return self.index_bus.subscribe(describe, self.index.accepting(accept))

    # ── proxy mode: what is a member's (9.9) ─────────────────────────────────
    @staticmethod
    def owns(member, root) -> bool:
        """Whether `root` is one of the member's: matched by the real path of its folder, never by
        its name, which 8.2 gives to the next folder that takes it."""
        real = config.realpath(root.path)
        return any(config.realpath(f) == real for f in member.roots)

    def member_owns(self, member, address: str) -> bool:
        """Whether the document at `address` (it need not exist) is the member's: the root 8.2
        finds for its file is the root its address names, and that root is one of theirs. So a
        root nested inside one of theirs stays another root."""
        return bool(self.members_owning([member], address))

    def members_owning(self, members, address: str) -> list:
        """Those of `members` whose the document at `address` is, as `member_owns` judges, with one lookup of
        its root for them all."""
        at = roots_mod.Address.parse(address)
        root = self.roots.get(at.root)
        if root is None or not at.plain:
            return []
        # A clone the tiroir serves is a shared root: any member reaches it, and each page is theirs by `judged` (SPEC 14).
        shared = bool(root.clone) and self._repos is not None
        mine = [m for m in members if shared or self.owns(m, root) or self.shared_with(m, root, address)]
        if mine and (private := place.private_member(self, address)) is not None:
            mine = [m for m in mine if m.id == private]       # rule A: a private root's file is its member's alone
        return mine if mine and self.roots.lookup(root.path / at.rel) == root else []

    def shared_with(self, member, root, address: str) -> bool:
        """Whether the loose page at `address` in `root`, another member's, is Shared with `member` (9.11): the ticked
        Share line of the page as it is now, read from the file each time, so a withdrawn Share closes it at the next
        request. A root that is no member's loose root shares nothing."""
        if self.proxy is None:
            return False
        owner = self.loose.owner_of(root)
        if owner is None or owner == member.id or owner not in self.proxy.members:
            return False
        return visibility.reaches(self.audience(address), member)

    def opened_by(self, member, address: str) -> None:
        """A member opened the page at `address`: the change they had in front of them is kept, so the Sheaf says "new"
        for a Shared page only while it changed since (8.6). Only a page of another member's loose root is kept."""
        root = self.roots.get(roots_mod.Address.parse(address).root)
        if root is None or self.giver(member, root) is None:
            return
        try:
            top, rel = self.where(address)
            with beneath.open_beneath(top, rel, meta=True) as op:
                self.member_opened.mark(member.id, address, int(os.fstat(op.fd).st_mtime * 1e9))
        except (OSError, roots_mod.NotFound):
            pass

    def giver(self, member, root):
        """The member whose loose root `root` is, when it is another member's and `member` is not in it: the one who may
        Share pages from it with `member`. None for every other root."""
        owner = self.loose.owner_of(root) if self.proxy is not None else None
        giver = self.proxy.members.get(owner) if owner is not None else None
        return giver if giver is not None and giver.id != member.id else None

    def alias(self, member, address: str) -> str:
        """The address under which `member` is told of the page at `address`: for a page of another member's loose root, an
        opaque one in that root's name, so the owner's folder names are never theirs to read (9.11); every other page by
        its own address. Only the member's own roots and the hub's person name a page by its path."""
        if member is None or self.proxy is None:
            return address
        at = roots_mod.Address.parse(address)
        root = self.roots.get(at.root)
        if root is None or self.giver(member, root) is None:
            return address
        return f"{at.root}/{self.shared_ids.of(address)}.md"

    def unalias(self, address: str) -> str:
        """The address an opaque name `alias` made stands for, else `address` itself. It says nothing of who may open it."""
        at = roots_mod.Address.parse(address)
        if not at.plain or not _ALIAS_RE.fullmatch(at.rel):
            return address
        real = self.shared_ids.address(at.rel[:-3])
        return real if real is not None and roots_mod.Address.parse(real).root == at.root else address

    def audience(self, address: str):
        """`visibility.audience` of the page at `address`, None when it cannot be read, or when its front matter cannot
        (`visibility.UNREAD`): a page the hub cannot judge opens to its owner only, whatever its Share line says."""
        try:
            top, rel = self.where(address)
            with beneath.open_beneath(top, rel) as op:
                text = op.text()
            return None if visibility.front_matter(text).get(visibility.UNREAD) else visibility.audience(text)
        except (OSError, UnicodeDecodeError, roots_mod.NotFound):
            return None

    def is_owner(self, member, address: str, fm: dict) -> bool:
        """Whether `member` owns the rectoverso at `address` whose front matter is `fm`: by the front matter (9.11), or
        as the member whose loose root holds the page. A page of a loose root is its root's member's alone: its front matter's
        `owner` and its issue's assignees name no other owner there."""
        if (loose := self.loose_owner(address)) is not None:
            return loose == member.id
        fm = self.clone_fm(address, fm)
        return bool(visibility.owner_of(fm, [member], self.assignees(address, fm)))

    def judged_for(self, member, address: str, fm: dict, assignees):
        """`(fm, assignees)` as `member` is judged on them: for a page of another member's loose root the `owner` line and the
        issue's assignees are not read, so what is written into such a page makes no one its owner (9.11)."""
        if (loose := self.loose_owner(address)) is not None and loose != member.id:
            return {k: v for k, v in fm.items() if k != "owner"}, None
        return fm, assignees

    def clone_fm(self, address: str, fm: dict) -> dict:
        """`fm` as a page of a clone is judged on it, by every door alike: a clone is a shared root, so a page that names
        no owner has the one its first render report recorded, never written into the file, and is its owner's alone
        unless its front matter says otherwise; a page with neither a record nor an owner opens to nobody (SPEC 14).
        `fm` itself for a page of any other root."""
        at = roots_mod.Address.parse(address)
        root = self.roots.get(at.root)
        if root is None or not root.clone or self._repos is None:
            return fm
        fm = dict(fm)
        if not fm.get("owner") and (owner := self._repos.owner_of(root.clone, at.rel)) is not None:
            fm["owner"] = owner
        if not fm.get("visibility"):
            fm["visibility"] = "owner"
        return fm

    def judged(self, address: str):
        """(front matter, assignees) of the rectoverso at `address`, what its visibility is judged on: the front
        matter read again only when its file moved, the assignees the list has for it now. For a file that is
        not there, both as the hub last judged it, so a poll that no longer sees the rectoverso changes nothing;
        None when it never did. ({}, None) in a root the hub does not know. Raises OSError or
        UnicodeDecodeError for a file that is there but cannot be read."""
        at = roots_mod.Address.parse(address)
        root = self.roots.get(at.root)
        if root is None:
            return {}, None
        # Kept by the address's own path, a rectoverso's name (9.11), and read where its file is now: opened beneath its root
        # once, judged on that descriptor, and read from it.
        kept = root.path / at.rel
        try:
            top, rel = self.where(address)
            op = beneath.open_beneath(top, rel)
        except (FileNotFoundError, roots_mod.NotFound):
            hit = self._front.get(kept)
            return None if hit is None else (self.clone_fm(address, hit[1]), hit[2])     # as a page that is there is judged
        with op:
            st = os.fstat(op.fd)
            key = (st.st_ino, st.st_mtime_ns, st.st_ctime_ns, st.st_size)
            hit = self._front.get(kept)
            fm = hit[1] if hit is not None and hit[0] == key else visibility.front_matter(op.text())
            assignees = self.assignees(address, fm)
            self._front[kept] = (key, fm, assignees)
            if self.private_roots:
                place.private_member(self, address, fm, place.opened_private(self, op))   # remembered whoever read the file first (rule A)
        fm = self.clone_fm(address, fm)
        return fm, assignees

    def last_judged(self, address: str):
        """(front matter, assignees) of the rectoverso at `address` as the hub last judged it, whatever its file holds
        now: what the door judges a file that cannot be read on (9.11). None when the hub never read it, or read
        another file there (another inode): what that one said is nothing about this one."""
        at = roots_mod.Address.parse(address)
        root = self.roots.get(at.root)
        hit = None if root is None else self._front.get(root.path / at.rel)
        if hit is None:
            return None
        try:
            top, rel = self.where(address)
            with beneath.open_beneath(top, rel, meta=True) as op:
                same = os.fstat(op.fd).st_ino == hit[0][0]
        except (OSError, roots_mod.NotFound):
            return None
        return hit[1:] if same else None

    def visible(self, member, address: str, never_read: bool = True) -> bool:
        """Whether the member may open the document at `address` by its visibility (9.11): a rectoverso that is
        its owner's alone is no other member's. A file that is not there is judged by the front matter it
        had when the hub last read it, so its going away is told to whom it was visible; one the hub never
        read is `never_read` (a page answers it as a missing document all the same, a stream tells nobody).
        A file that is there but cannot be read, or not as UTF-8, is no member's: the hub may still hold its
        last good page."""
        try:
            judged = self.judged(address)
        except (OSError, UnicodeDecodeError):
            return False
        private = place.private_member(self, address, None if judged is None else judged[0])
        if private is not None and private != member.id:        # rule A, before anything the file or the issue says
            return False
        if self.holds_loose(member, address):                  # a loose page is its member's whatever its front matter says
            return True
        if judged is None:
            return never_read and self.granted(member, address)
        fm, assignees = self.judged_for(member, address, *judged)
        return visibility.visible_to(fm, member, assignees, self.granted(member, address)) or self.opened_by_line(member, address)

    def may_open(self, member, address: str, fm: dict, opened=place.UNJUDGED) -> bool:
        """Whether `member` may open the rectoverso at `address` whose front matter is `fm`, a text read under its lock
        (9.11): as `visible` judges the file on disk, with `projects.toml`'s grant (8.12)."""
        fm = self.clone_fm(address, fm)
        private = place.private_member(self, address, fm, opened)
        if private is not None and private != member.id:        # rule A
            return False
        if self.holds_loose(member, address) or self.opened_by_line(member, address):
            return True
        fm, assignees = self.judged_for(member, address, fm, self.assignees(address, fm))
        return visibility.visible_to(fm, member, assignees, self.granted(member, address))

    def holds_loose(self, member, address: str) -> bool:
        """Whether the page at `address` is in the loose root of `member`: theirs whatever its front matter says, so the
        owner who withdrew a Share (`visibility: owner`, no `owner`) still opens their own page."""
        return self.loose_owner(address) == member.id

    def loose_owner(self, address: str) -> str | None:
        """The id of the member whose loose root holds the page at `address`, None for a page of any other root."""
        if self.proxy is None:
            return None
        root = self.roots.get(roots_mod.Address.parse(address).root)
        return None if root is None else self.loose.owner_of(root)

    def opens_more(self, address: str, old: str, new: str) -> bool:
        """Whether writing `new` over `old` at `address` opens the page to a member it was not open to: judged on the
        hub's own audience of each text (its front matter's visibility, or its ticked Share line), never on the Share lines
        alone, so a write that only takes a private source off a page whose line a hand ticked opens it all the same (9.11)."""
        if self.proxy is None:
            return False
        def opens(member, text):
            return visibility.effective(self.clone_fm(address, visibility.front_matter(text))) == "project" or self.opened_by_line(member, address, text)
        return any(opens(m, new) and not opens(m, old) for m in self.proxy.members.values())

    def opened_by_line(self, member, address: str, text: str | None = None) -> bool:
        """Whether the ticked Share line of the page at `address`, as the file holds it now, opens it to `member` (9.11),
        whatever its `visibility` says: a hand tick in the file gives what the tick of the page gives. In a root that is no
        member's loose root only a ticked `Share with <names>` that names `member` does, such a page staying its owner's
        alone in its front matter (a plain Share is the page's `visibility`). In another member's loose root a plain Share
        does too, and `projects.toml` has no word. `text`: judged on that text instead of the file."""
        if self.proxy is None:
            return False
        loose = self.loose_owner(address)
        if loose is not None and (loose == member.id or loose not in self.proxy.members):
            return False
        if text is None:                        # the file as it is now; a door write asks of the text it would leave
            try:
                top, rel = self.where(address)
                with beneath.open_beneath(top, rel) as op:
                    text = op.text()
            except (OSError, UnicodeDecodeError, roots_mod.NotFound):
                return False
        shared, fm = visibility.audience(text), visibility.front_matter(text)
        if fm.get(visibility.UNREAD):             # a front matter the reader cannot judge: the owner's alone
            return False
        # A page that draws on a private source is opened only by its owner's own Share, which writes `shared`; an
        # agent's write, or a tick by hand, cannot (#40).
        if any(visibility.private(x) for x in visibility.sources(fm)) and not visibility.text(fm, "shared"):
            return False
        if loose is not None:
            return visibility.reaches(shared, member)
        return isinstance(shared, frozenset) and visibility.reaches(shared, member) and self.granted(member, address)

    def granted(self, member, address: str, by_name: bool = False) -> bool:
        """Whether the `projects.toml` of the root of `address` lets `member` into its project (8.12): always in
        loopback mode, and in a root with no such file. `by_name`: judged by the address alone, not by where the file
        is (a `create` on a name a private root holds is answered as one a shared root holds, 9.11)."""
        at = roots_mod.Address.parse(address)
        root = self.roots.get(at.root)
        if self.proxy is None or root is None:
            return True
        entries = self.projects_of(root)
        if entries is None:
            return True
        # Judged where the file is as well as by the address: a link in one project to a rectoverso of another (a root
        # the hub does not place follows it) opens it only to a member both name.
        if by_name:
            return projects.grants(entries, at.rel, member.short)
        top = os.path.realpath(root.path)
        try:
            real = os.path.realpath(self.file(address))
        except roots_mod.NotFound:
            return False                    # a file that cannot be decided (rule B) opens to no one
        if not real.startswith(top.rstrip("/") + "/"):
            return False
        return all(projects.grants(entries, rel, member.short) for rel in {at.rel, os.path.relpath(real, top)})

    def projects_of(self, root):
        """The entries of `root`'s `projects.toml`, None without the file, an `Invalid` for one the hub cannot
        read: read again only when the file changed (its inode, times or size), so an edit takes effect at the
        next request, with no restart."""
        kept = getattr(self._listing, "projects", None)
        if kept is not None and root.id in kept:
            return kept[root.id]
        got = self._projects_read(root)
        if kept is not None:
            kept[root.id] = got
        return got

    @contextmanager
    def projects_remembered(self):
        """Within it, this thread reads each root's `projects.toml` once (SPEC 8.12): a listing asks `projects_of` for every
        page it checks, and the file does not change inside one listing. The answers are dropped when it ends, so the next
        listing reads the file again; a nested use shares the outer one's."""
        if getattr(self._listing, "projects", None) is not None:
            yield
            return
        self._listing.projects = {}
        try:
            yield
        finally:
            self._listing.projects = None

    def _projects_read(self, root):
        key, got = projects.load(root.path, self)       # one open beneath the root: the key and the text are of one file
        if key is None:
            self._grants_seen.setdefault(root.id, None)
            return None
        hit = self._projects.get(root.id)
        if hit is not None and hit[0] == key:
            return hit[1]
        self._projects[root.id] = (key, got)          # a swap of one item: no lock, any reader sees one or the other
        self._grants_seen.setdefault(root.id, got)    # what the tick compares with, from the first read on
        return got

    def owners(self, address: str, members) -> list:
        """Those of `members` who own the rectoverso at `address`, by its front matter now, as `visible` judges."""
        try:
            fm, assignees = self.judged(address) or ({}, None)
        except (OSError, UnicodeDecodeError):
            return []
        return visibility.owner_of(fm, members, assignees)

    def assignees(self, address: str, fm: dict):
        """The record's assignees of the issue of the rectoverso at `address` whose front matter is `fm`, asked by
        the address of the file it names, so a link has the owner of the rectoverso it points to; None when the
        list does not know it, or when `fm` names another issue than the one it polled."""
        if self.the_list is None:
            return None
        at = roots_mod.Address.parse(address)
        root = self.roots.get(at.root)
        if root is not None and at.plain:
            placed = place.applies(self, at.root)
            try:
                rel = Path(config.realpath(self.file(address, placed))).relative_to(config.realpath(root.path))
                rel = rel.as_posix()
                # The list knows a rectoverso by its name (9.11), wherever its file is.
                address = f"{root.name}/{(place.logical(rel) if placed else None) or rel}"
            except (ValueError, roots_mod.NotFound):     # a file that cannot be decided (rule B) renames nothing
                pass
        try:
            return self.the_list.assignees(address, visibility.text(fm, "issue"))
        except roots_mod.NotFound:                       # a name two roots hold: no record's assignees for it
            return None

    def jobs(self) -> dict:
        telling = []
        for address, e in list(self.entries.items()):
            telling += [[address, cid] for cid in e.live.waiting()]
        return {"telling": telling}

    # ── the watcher's step (SPEC 8.9) ────────────────────────────────────────
    def _watch_drops(self):
        """The drops for James's window (9.12): give up on those with no reply after the Tell wait (#115), read in
        the file as it is now, whether a page asked since or not; then read the supervisor's word on the others."""
        def text_of(address):
            # The file, not the hub's copy: `sheaf reply` answers a drop without the hub, and a rectoverso with no tab
            # is not refreshed by the pass.
            e = self.entries.get(address)
            if e is None:
                return None
            self.catch_up(e)
            return e.live.current()[1]
        minutes = max(1, -(-self.tell_wait // 60))
        for address, thread, d in self.box_waits.expire(self.tell_wait, text_of):
            self.record("box-expired", address, what=boxwait.KIND, project=_project(address), thread=thread)
            self._tell_drop(address, "box-failed", {"id": thread, "kind": boxwait.KIND, "minutes": minutes})
        self._read_drop_statuses()
        for address in self.box_waits.cleared():          # however it ended, here or on a page's ask: the orange goes
            self.index.moved_for_members(address)         # each member's orange is their own: another's may stay on

    def _read_drop_statuses(self):
        """What the box's supervisor says of each drop still open, in its `<drop>.status` (9.15, #139): a change
        is a `drop-status` row and the page's `box-status`, or `box-failed` with its error, which ends the drop;
        a `delivered` begun moves a member's dot (one that ends is `cleared`)."""
        if self.the_list is None:
            return
        for address, thread, d in self.box_waits.drops():
            # The folder the drop was written in: the James of the member who sent it (`member_dirs`).
            folder = d.folder if d.folder is not None else self.the_list.cfg.tell_dir
            got = boxwait.read_status(folder, d.name) if d.name and folder is not None else None
            what, was = self.box_waits.observe(address, thread, got, d)
            row = {"what": boxwait.KIND, "project": _project(address), "thread": thread}
            if what == "ignored":
                self.record("drop-status-ignored", address, **row, drop=d.name)
            elif what == "failed":
                self.record("drop-status", address, **row, state="failed", error=got[1])
                self._tell_drop(address, "box-failed", {"id": thread, "kind": boxwait.KIND, "error": got[1]})
            elif what == "state":
                self.record("drop-status", address, **row, state=got[0])
                self._tell_drop(address, "box-status", {"id": thread, "kind": boxwait.KIND, "state": got[0]})
            if what == "state" and got[0] == "delivered":
                self.index.moved_for_members(address)

    def _tell_drop(self, address: str, name: str, data: dict):
        e = self.entries.get(address)
        if e is not None:
            e.bus.publish(name, data)

    def enable_team(self, path, gate) -> None:
        """Keep Team comments in `path`. `gate(member, address)` says whether the member may open that client page."""
        self.team = team_mod.TeamComments(path)
        self.team_gate = gate

    def keep_team(self) -> None:
        """Keep the agency's Team comments in the state folder, gated by what the client tiroir says the member may open."""
        self.enable_team(paths.state_dir() / "team-comments.json", self._may_open_client_page)

    def _may_open_client_page(self, member, address) -> bool:
        found = self.clients.split(address) if self.clients is not None else None
        return found is not None and self.clients.may_open(found[0], member, found[1])

    def tick(self):
        """One pass of the watcher, run every second. For each document with an open tab or a
        Tell wait: give up on waits nobody answers, and when the file's (mtime, size) moved,
        catch up with it and tell the tabs. A failure in one document is written down and never
        stops the pass."""
        for e in list(self.entries.values()):
            try:
                e.live.expire(self.tell_wait, self.tell.product(e.address))
                self._observe(e)
                if not (e.bus.count() or e.live.waiting()):
                    continue
                try:
                    st = e.stat()
                except (OSError, roots_mod.NotFound):      # a bound entry's file may be gone from its root
                    continue
                key = (st.st_mtime_ns, st.st_size)
                if key == e.last_stat:
                    continue
                self._refreshed(e)
                e.last_stat = key        # after: a rebuild that failed is tried again next tick
            except Exception as ex:
                self._rebuild_failed(e, ex)
        try:
            self._watch_drops()                   # after the tabs' refresh: a reply that just landed is in
        except Exception:
            self.record_exception("drops-failed")
        try:
            self.commits.poll(self.roots.all())   # what the remote got, with no save (8.11, #75)
        except Exception:
            self.record_exception("push-failed")
        try:
            self._tell_grants()
        except Exception:
            self.record_exception("grants-failed")
        try:
            self.waiting_tells.watch()            # a revoke or a close from outside ends a waiting Tell (9.8)
        except Exception:
            self.record_exception("tell-end-failed")
        try:
            self.index.tick(self.clock())
        except Exception:               # a traceback, not `error=`: see `record_exception`
            self.record_exception("status-failed")
        try:
            self.archive.tick(self.clock())
        except Exception:
            self.record_exception("archive-failed")

    def _tell_grants(self):
        """Tell the open tabs of a root whose `projects.toml` changed, once the change held for two passes,
        `grants`: each member's stream asks again whether the member may open its document, and one
        `projects.toml` no longer lets in is told `gone` (8.12). A page ignores the event itself."""
        if self.proxy is None:
            return
        by_root: dict = {}
        for address, e in list(self.entries.items()):
            if e.bus.count() and (root := self.roots.get(roots_mod.Address.parse(address).root)) is not None:
                by_root.setdefault(root.id, (root, []))[1].append(e)
        for root_id, (root, open_) in by_root.items():
            got = self.projects_of(root)
            # Told once the new answer held for two passes: a file met empty or cut off mid-write ends no page.
            held, self._grants_last[root_id] = self._grants_last.get(root_id) is got, got
            if got is not self._grants_seen.get(root_id, got) and held:
                self._grants_seen[root_id] = got
                for e in open_:
                    e.bus.publish("grants", {})
                    if self._images_moved(e):
                        try:
                            e.live.rebuild()
                        except Exception as ex:
                            self._rebuild_failed(e, ex)

    def _observe(self, e: Entry):
        """What the session told by this document is doing. A failure here is written down and
        never stops the pass."""
        try:
            self.tell.observe(e)
        except Exception as ex:
            diagnostics.record("hub", "session-state-failed", e.address,
                               error=f"{type(ex).__name__}: {ex}")

    def catch_up(self, e: Entry):
        """Take in a write from outside before a page is served, for a document with no tab
        (the watcher skips it) as for one with: when the file's (mtime, size) moved, refresh,
        which tells the tabs. A rebuild that fails is written down and the last good page is
        served; it is tried again on the next request."""
        try:
            st = e.stat()
            key = (st.st_mtime_ns, st.st_size)
            if key != e.last_stat:
                self._refreshed(e)
                e.last_stat = key
            if self._images_moved(e):           # projects.toml or the owners moved: its images are judged otherwise
                e.live.rebuild()
            elif (repo := self.clone_of(e.address)) and e.live.current_read()[2] != self._repos.head_of(repo):
                e.live.rebuild()                # the clone moved (or left read-only) since the render: its file may be the
                                                # same on both branches, and the page must be read on the branch it saves on
        except Exception as ex:
            self._rebuild_failed(e, ex)

    def _refreshed(self, e: Entry):
        """Take in a write from outside, and write it in the Write log: a text that moved behind the hub's back is a file
        written on disk, whoever wrote it (`?`), unless a pull of its repo is bringing it in (that has its own line)."""
        got = e.live.refresh()
        if got is not None:
            hash_ = e.live.current()[0]
            if not self.writes.is_pull(e.address, hash_) and not self.writes.is_own(e.address, hash_):
                self.writes.add(e.address, "?", "tiroir", "disk")
        return got

    def _page_of(self, path: Path) -> str | None:
        """The name the hub opens the rectoverso at `path` under: where it places rectoversos (9.11), the name under its
        project for a file of `<project>/private/<short>/`, and the list's for a file of a private root, as `_writers_out`
        names them; else the address of its root. A page is whatever the hub serves, never a file of `.sheaf/` or `.git`.
        None for a file no root of the hub holds, or that it does not serve."""
        listed = next((r for r in self.roots.all() if place.applies(self, r.name)), None)
        for r in self.roots.all():
            if place.applies(self, r.name):
                at = r
            elif r.id in self.private_roots and listed is not None:
                at = listed
            else:
                continue
            rel = os.path.relpath(path, os.path.realpath(r.path))
            if not rel.startswith(".."):
                rel = rel.replace(os.sep, "/")
                name = place.logical(rel)
                if name is None and at is r and roots_mod._servable(rel) and not place.names_private(rel):
                    name = rel                                      # served all the same, as a README is (place.physical)
                return f"{at.name}/{name}" if name else None
        try:
            address = self.roots.address(path)
        except roots_mod.NotFound:
            return None
        return None if roots_mod._sheafs_own(address.partition("/")[2]) else address

    def pulling(self, folder: Path, files: list[tuple[Path, str]]):
        """A pull of the repo at `folder` is about to change `files`, (absolute path, last author): the page open on one
        sees it change: until `pulled`, what it sees of the file is the pull's, not a disk write."""
        for path, _ in files:
            address = self._page_of(path)
            if address in self.entries:
                self.writes.expect_pull(address)

    def pulled(self, folder: Path, files: list[tuple[Path, str]], ok: bool, left: dict | None = None):
        """The pull of `files` ended: each open page is known by the text the pull left (`left`: path to hash, read under the
        pull's locks; read now when not given), so the page's next sight of it is the pull's; when the pull went through, a
        line each, `git · <author>`, for each that is a page of a root the hub serves."""
        for path, author in files:
            address = self._page_of(path)
            if address is None:
                continue
            if address in self.entries and ok:
                try:
                    text = md_hash(path.read_bytes().decode("utf-8")) if left is None else left.get(path)
                except (OSError, ValueError):
                    text = None
            else:
                text = None
            self.writes.end_pull(address, text)
            if ok:
                self.writes.add(address, f"git · {author}", "tiroir", "pull")

    def renamed(self, folder: Path, pairs: list[tuple[Path, Path]]):
        """A pull of the repo at `folder` brought in the rename of each `(old path, new path)`, and the files are moved (9.11): a
        repo page moves only by git, and the hub writes the Forward and carries what it keeps of the page, as for a Move. Under
        the moves' lock, which comes before the repo's: the pull lets the repo's lock go first. A rename of a file the hub does
        not serve, or to an address where a page already stood, is none."""
        with moves_mod.exclusive():
            for old, new in pairs:
                a, b = self._page_of(old), self._page_of(new)
                if a is None or b is None or a == b or not new.exists() or old.exists():
                    continue
                if roots_mod.Address.parse(a).root != roots_mod.Address.parse(b).root:
                    self.record("rename-between-roots", a, to=b)      # 9.11: no move between roots; the page's stores stay
                    continue
                # A rename cannot be refused as a Move is: the address is marked, so no Tell starts on it meanwhile, and a Tell
                # already running is a row (its answer meets a page that is gone from where it began). A Forward at the new
                # address, which `Forwards.add` drops, the page being there, is a row too.
                with self.admit:
                    live = self.tell_live(a)
                    self.moving.add(a)
                try:
                    if live:
                        self.record("rename-under-tell", a, to=b)
                    was = self.forwards.follow(b)
                    if was is not None and was != a:
                        self.record("forward-replaced", b, was=was)
                    with place.held(self, a), place.held(self, b):
                        self.moved_page(a, b, "git")
                except Exception:
                    self.record_exception("move-store-failed", b)
                finally:
                    with self.admit:
                        self.moving.discard(a)

    def wrote(self, address: str, moved: bool = False):
        """The door made or changed this document's file (SPEC 12): tell its open tabs now, as the
        watcher would within a second, and the open indexes. Compared by its text, not by
        `(mtime, size)`, which a write of the same length within one clock tick leaves as it was.
        `moved`: the file of a rectoverso moved (9.11), its text the same; the page is rendered again all
        the same, since its relative images are now found in the new folder."""
        e = self.entries.get(address)
        if e is not None:
            try:
                st = e.stat()
                if moved:
                    e.live.rebuild()
                else:
                    e.live.refresh()
                e.last_stat = (st.st_mtime_ns, st.st_size)
            except Exception as ex:
                self._rebuild_failed(e, ex)
        self.writes.told(address)
        try:
            self.index.touch(address)
        except Exception:
            self.record_exception("status-failed")       # the write is done; the next sweep shows it

    def _rebuild_failed(self, e: Entry, ex: Exception):
        """A rebuild that fails is tried again every tick and on every request while the file
        stays broken; the log hears of it once, so the retry cannot push older rows out of
        the capped file. The same failure is the same only while no rebuild has worked in
        between (`_rendered` clears it) and the file is the same."""
        try:
            st = e.stat()
            key = (st.st_mtime_ns, st.st_size)
        except (OSError, roots_mod.NotFound):
            key = None
        failure = (key, f"{type(ex).__name__}: {ex}")
        if failure != e.rebuild_failure:
            e.rebuild_failure = failure
            diagnostics.record("hub", "rebuild-failed", e.address, error=failure[1])

    # ── stopping ─────────────────────────────────────────────────────────────
    def announce_stop(self, reason: str):
        for e in list(self.entries.values()):
            e.bus.publish("hub-stopping", {"reason": reason})
        self.index_bus.publish("hub-stopping", {"reason": reason})

    def rotate(self):
        """A new hub key (SPEC 9.3): the file first, then what every request reads. The old key,
        the old cookies and the old proofs stop working at once, and every open tab is told, so
        it shows the sign-in page instead of failing quietly on its next save."""
        self.auth = Auth(paths.rotate_key(), self.port)
        self.record("key-rotated")                      # why every tab signed out; never the key
        for e in list(self.entries.values()):
            e.bus.publish("signed-out", {})
        self.index_bus.publish("signed-out", {})        # the index pages too: they hold the list

    def request_stop(self, reason: str, force: bool = True) -> bool:
        """Ask the hub to stop. An upgrade stop is taken only while no Tell runs, unless
        `force` (`sheaf restart`: the person's own decision): False when it was refused, and the
        hub goes on. Once an upgrade stop is taken no job starts, so none is killed by it (8.4).
        A stop or a signal that is under way is not turned into an upgrade by a later upgrade stop:
        under the service that would exit 75 and start the hub again, which the person stopped.
        Only an upgrade stop gives way: a stop or a signal that comes after one ends the hub for good.
        A stop wins over a signal, in either order: they exit differently under the service (#79: a
        signal is restarted, `sheaf stop` is not), and a person who asked for a stop is told the hub
        stopped, so a stray signal before or after it must not bring the hub back.
        The look at `stop_requested` and the write of it are one step, because the signal handler and
        the request threads both come here."""
        with self._stop_lock:
            told = False
            if reason == "signal" and self._restart_told_at is not None \
                    and self.clock() - self._restart_told_at < RESTART_TOLD_TTL:
                reason, told = "upgrade", True               # the manager's SIGTERM of `sheaf restart`
            if reason == "upgrade":
                if self.stop_requested not in (None, "upgrade"):
                    return True                              # it is stopping already, as the caller wants
                with self.admit:
                    if not force and self.busy():
                        return False
                    self.upgrading = True
                self.told_restart = self.told_restart or told
            elif self.stop_requested == "stop" or (self.stop_requested == "signal" and reason == "signal"):
                return True                                  # a stop under way stays; a second signal adds nothing
            self.stop_requested = reason
        if self.on_stop:
            self.on_stop(reason)
        return True

    def expect_restart(self):
        """`sheaf restart` through the service tells the hub before the service manager stops it
        (SPEC 8.4): the SIGTERM that follows within RESTART_TOLD_TTL is an upgrade stop, so the
        exit row and the tabs say `upgrade`, as on the direct path. A restart that never comes
        is forgotten, and a later logout is a signal again."""
        self._restart_told_at = self.clock()

    def forget_restart(self):
        """The restart that `expect_restart` announced will not come: the service manager failed to
        make it. The next SIGTERM is a logout or a `systemctl stop`, a signal again (8.4)."""
        self._restart_told_at = None

    def busy(self) -> bool:
        """Whether a Tell waits anywhere (what `GET /_/jobs` lists), or a Tell's
        delivery or a stop message is still on its way: a delivery whose wait has ended (the
        reply came first, or the clock gave up) and the stop message of a cancelled Tell have
        no wait to show, and an upgrade stop would kill them half-way (8.4)."""
        j = self.jobs()
        return bool(j["telling"]
                    or self.runner.active("tell") or self.runner.active("stop"))

    # ── the diagnostics log, as the hub ──────────────────────────────────────
    def record(self, kind: str, doc=None, **detail):
        diagnostics.record("hub", kind, doc, **detail)

    def record_exception(self, kind: str, doc=None, **detail):
        # Two idioms, two meanings: a traceback is for a bug (an exception nothing expected, so
        # the pass is cut short); `record(..., error=...)` is one line for a failure that is
        # known and tried again (a rebuild that failed, a session state that could not be read).
        # The log clips a field at its start; what matters in a traceback is its end.
        diagnostics.record("hub", kind, doc, traceback=traceback.format_exc()[-1900:], **detail)
