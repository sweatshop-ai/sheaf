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
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .. import __version__, beneath, config, diagnostics, paths
from ..agents import registry
from ..agents.base import Adapter, Target
from ..render import RenderError, render_file
from ..source import STAMP_FORMAT, file_lock, lock_key
from . import assets as assets_mod
from . import boxwait
from . import place
from . import projects
from . import proxy as proxy_mod
from . import relay as relay_mod
from . import roots as roots_mod
from . import state
from . import targets as targets_mod
from . import the_list
from . import waiting as waiting_mod
from . import visibility
from . import work as work_mod
from .tell import Tell, who as session_who
from .auth import Auth
from .commits import Author, Commits
from .events import Bus
from .index import Index
from .jobs import Jobs
from .live import LiveDocument

# What a render may set (SPEC 8.3). Every other key of docs.json is the hub's own.
SETTING_KEYS = ("title", "toc", "max_image_width", "by", "for", "theme", "credit")

_META_RE = re.compile(r'(<script id="rd-edit-meta" type="application/json">)(.*?)(</script>)', re.S)


@dataclass
class Entry:
    address: str
    file: Callable[[], Path]     # where its file is now: a sheaf of the list's root is found by its name (9.11)
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
        """The document's file as it is found now (9.11: a move renames the file of a sheaf, never its entry)."""
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
    """`<client>/<project>` of a sheaf of the list's root at that address (9.10)."""
    return "/".join(roots_mod.Address.parse(address).rel.split("/")[:2])


class Hub:
    def __init__(self, port: int, key: str, *, started_by: str = "cli", service: bool = False,
                 version: str = __version__, clock=time.time, proxy=None, person: str | None = None):
        self.port, self.version, self.service = port, version, service
        self.assets = assets_mod.load(version)   # /_/mount.js and .css as this hub serves them to its end (#179)
        self.proxy = proxy                       # the checked `[proxy]` table (9.9), None in loopback mode
        self.started_by, self.clock = started_by, clock
        self.auth = Auth(key, port)
        self.boot = str(uuid.uuid4())
        self.started = time.time()
        self.person = person if person is not None else config.user_name()   # the start hands over the one it read
        self.roots = roots_mod.Roots()
        self.roots.placer = lambda root, rel: place.physical(self, root, rel)
        self.versions = state.Versions()
        self.commits = Commits(self.record, self._writers_out, self.roots.all,
                               lambda: bool(self._private_paths))   # the roots that commit (8.11); the rewrite guard while a private root is configured
        self._told_projects: set = set()         # what check_projects warned of this run (8.12)
        self._projects: dict = {}                # root id -> (stat key, entries | Invalid | None) of its projects.toml
        self._grants_seen: dict = {}             # root id -> the projects_of answer the open tabs were last told (8.12)
        self._grants_last: dict = {}             # root id -> what projects_of gave the last tick
        self.told_place: set = set()             # (address, quarantined | "undecided") a place-refused row named this run (9.11)
        self.told_link: set = set()              # the (root id, path) a link-ignored row named this run (9.11)
        self.told_ignored: set = set()           # the roots a private-ignored row named this run (9.11)
        self._front: dict = {}                   # {file: (its stat, its front matter, its assignees)}, for 9.11
        self._private_seen: dict = {}            # {address: the member a private root held it for}, `place.private_member`
        self.the_list = None                     # the list (9.10): a the_list.TheList, set by the server
        self.blamed: dict = {}                   # {(real path, md_hash): (pressers, monotonic time or None)}: once per text,
                                                 # for the list's rows and the pages' buttons alike (9.10, 10.11)
        self.docs = state.Docs()
        self.seen = state.Seen()
        self.member_seen = state.MemberSeen()
        self.index = Index(self)
        self.tokens = state.Tokens()
        self.waiting_tells = waiting_mod.Waiting(self)    # the Tells that wait for an agent (9.8)
        self.relays = relay_mod.Relays()     # the forks' relay tokens, queued Tells and streams (9.14)
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
        self._private_ids: dict[tuple, str] = {}    # (st_dev, st_ino) of each, so a spelling in another case is the same folder
        self._private_by_identity: set[str] = set()     # ids of roots whose folder is a private one, spelled otherwise
        self._private_good: set[str] = set()       # those that registered: placement only, never privacy
        self.roots.private_paths = lambda: self._private_paths
        self.roots.hidden = self._is_private_root
        self.roots.registered = self._note_identity       # rule E: no address of its own, registered or refused
        self._register_private_roots()
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
        addresses when it is not `root` (a private sheaf is addressed under the list's root): the prefix the
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
        """The versions store of the sheaf named `address` as its file is now placed, found at each call, not when
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
        """Warn of each sheaf folder of `root` (its documents `rels`) that the root's `projects.toml`
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
            print(f"sheaf: {root.name}/{folder} holds sheaves and {projects.FILE} has no entry for it",
                  file=sys.stderr, flush=True)

    @contextmanager
    def _writers_out(self, root, files):
        """Hold what a writer of each of `files` (absolute paths in `root`'s repo) holds before the repo's commit
        lock: the lock of its sheaf's name, in every root that holds the file and whose sheaves the hub places, then
        its file lock (9.11). A pull (8.11, #62) holds it while it changes them, so no write lands between its look
        at a file and its new text. A pull of one root changes the files of every root of its repo, so the names are
        those of all of them, not of `root` alone, taken in one order, that of their locks' keys: a writer that
        moves a sheaf of another root holds its name before its files, as the pull does, and the two never wait on
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

    def committed(self, address: str, member=None, what: str = "edit", by: str | None = None,
                  gone: str | None = None, author: Author | None = None):
        """A write went to `address`, by `member` (a proxy.Member), by `by` (the display name of a door
        caller), by `author` when given (the hub itself, for a move of the poll) or else by the hub's person:
        a commit, in a root that commits (8.11). `gone`: the path in the root the document moved from (9.11). The
        caller holds the sheaf's name (`place.held`): a write and its commit are one step under it, so no other
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
                self.record("commit-refused", address, why="its file is not where the sheaf was opened")
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
        file that holds a sheaf's name, wherever it lives (9.11), else the address's own path. `placed` is whether
        the hub places the root's sheaves (`place.applies`), when the caller knows it. `bound`: the private root an
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
        a request that comes after it. All of it under the lock of a sheaf's name (9.11), taken before
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
                # Keyed by the sheaf's name: its file is found again at each read, and under the name's lock at
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
            e.live.refresh(force=True)           # the first render: e.html
            self.entries[address] = e
            return e

    def _rendered(self, e: Entry, text: str):
        e.html = self._build(e, text)
        e.rebuild_failure = None         # every rebuild that works passes here: the next failure is news

    def _settings(self, address: str) -> dict:
        s = self.docs.get(address)
        return {k: s.get(k) for k in SETTING_KEYS}

    def _build(self, e: Entry, text: str, *, mount: bool = False, count: bool = True) -> str:
        s = self._settings(e.address)
        root = self._file_root(e)
        meta = {"doc": e.address, "root": e.root_id, "boot": self.boot, "version": self.version,
                "service": self.service, "me": self.person,
                "agent": None, "can": [], "lines": {}, "seen": {}}
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
        """The root the image rules judge the page of `e` against: the root its file is in, so the images of a sheaf of
        a member's private root are judged there and show (rule H); the root of its address for any other sheaf."""
        at = self.roots.get(roots_mod.Address.parse(e.address).root)
        if at is None or not self.private_roots:
            return at
        found = self.roots.lookup(e.path)
        return found if found is not None and found.id in self.private_roots else at

    def _image_read(self, root):
        """The bytes of a local image, from one open beneath `root` (`sheafmd.beneath`), refused when what was opened is
        in a private root other than `root` itself (9.11): the rule above judges the image's real path, this judges what
        is read. A private `root` is the one its sheaf is in, and opens only beneath itself."""
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
        `<client>/<project>` is in reach of the document's file `doc` for every reader of the sheaf at `address`
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
        """(whether a page of `root` judges its images by project, whether the sheaf at `address` has a reader the
        project does not name). By project when the root has a `projects.toml`, read or not (8.12: a root without
        one grants as before). A reader the project does not name is an owner its `members` do not hold, since an
        owner opens their sheaf whatever the file says; judged at the address and where its file is, and every owner
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

    def page(self, e: Entry, nonce: str, member=None) -> str:
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
            meta = self._fresh_meta(e, json.loads(m.group(2)), member)
            html = (html[:m.start(2)] + json.dumps(meta).replace("<", "\\u003c") + html[m.end(2):])
        return html

    def _fresh_meta(self, e: Entry, meta: dict, member) -> dict:
        """The meta block as it is now: the read state and what changes without the page being rendered again. The page
        route and the mount route (#116) both send this, so a page mounted in the front reads what a framed one does."""
        # The buttons of the text the page draws: a write since its render brings a `changed` and a reload,
        # so none are drawn on the old text meanwhile (10.11).
        h, text = e.live.current()
        meta["actions"] = self.actions(e, member, text) if h == meta.get("hash") else []
        if member is None:
            meta["seen"] = self.seen.get(e.address)
            v = self.tell.view(e.address)
            meta["agent"], meta["can"], meta["lines"] = v.agent(), v.can(), v.lines
            meta["targets"] = targets_mod.choices(self, e.address)
        else:
            meta.update(me=member.name, seen=self.member_seen.get(member.id, e.address), proxy=True,
                        member=member.id)
            work, can = self.member_work(e, member)
            if work is not None:
                meta["work"] = work
            meta["agent"], meta["can"], meta["lines"], meta["targets"] = self.member_target(e.address, member, can)
        return meta

    def member_target(self, address: str, member, can: list) -> tuple:
        """(agent, can, lines, targets) of a member's page (SPEC 9.8, 10.1): their own target, an agent of theirs,
        never the hub account's session. On a sheaf whose Tells go to James's window or a fork's relay (9.12) the
        target is not theirs to choose: none is shown and `targets` is empty."""
        lines = proxy_mod.member_lines()
        if {"box-tell", "relay-tell"} & set(can):
            return None, can, lines, []
        pickable = targets_mod.choices(self, address, member)
        raw = targets_mod.stored(self, address, member)
        if raw is None:
            return None, can, lines, pickable
        shape, line, reaches = targets_mod.agent_view(self, raw, member)
        return shape, sorted({*can, "queue"}) if reaches else can, {"tell": line}, pickable

    def mount_doc(self, e: Entry, member=None) -> dict:
        """The sheaf as the front mounts it (#116): {title, toc, html, config, css, version, script, assets}. The text
        is rendered now through the sanitiser's mount mode; the config is the meta block of `page`, so both read the
        same state."""
        h, text = e.live.current()
        got = json.loads(self._build(e, text, mount=True, count=False))
        got["config"] = self._fresh_meta(e, got["config"], member)
        got["version"] = self.version
        got.update(self.mount_fields())
        return got

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
        s = the_list.read_sheaf("x.md", text)       # read for its boxes alone: the name is no matter
        if not (s.actions or s.pressed):
            return []
        fm = visibility.front_matter(text)
        owner = member is None or bool(visibility.owner_of(fm, [member], self.assignees(e.address, fm)))
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
        """The `work` of a member's page (None when it is not a sheaf of the list's root) and its `can`:
        box-tell while the live session runs on the box and `[list]` names a `tell_dir` (10.1).
        The meta block and every /_/doc answer carry both, so a fork seen by the page changes what it offers."""
        st = work_mod.state(self, e.address, e.live.current()[1], member)
        if st is None:
            return None, []
        return self.work_meta(e, member, st), st.can

    def work_meta(self, e: Entry, member, st) -> dict:
        """What the page's Work on this shows a member (9.12, 10.1): the command that forks the sheaf's session
        on their machine, the one that attaches to James's window when they have a shell on the box, the
        sessions and where the live one runs. None for a page that is not a sheaf of the list's root."""
        out = {"sessions": st.sessions, "live": st.live}
        if st.live == "laptop":
            out["relay"] = st.relay         # whether Tell reaches the fork now (9.14, 10.1)
        # The fork fetches the live session's transcript from /_/session: one on a laptop, none, or no
        # copy to serve it from (sessions_dir and work_dir, #146), nothing to fork.
        if st.forkable and work_mod.serves(st.cfg, st.member):
            out["fork"] = (f"uvx --from {work_mod.FORK_CLIENT} tiroir work "
                           f"{self.proxy.origin}{roots_mod.url_path(e.address)}")
        # James names a project's window <client>_<project>: with a dash, a-b/c and a/b-c would share one.
        window = "_".join(roots_mod.Address.parse(e.address).rel.split("/")[:2])
        # Two shells and tmux read the command: a name with another character (`.`, `:`, a space) is left out.
        if member.shell and st.cfg.attach and re.fullmatch(r"[A-Za-z0-9_-]+", window):
            out["attach"] = st.cfg.attach.replace("{window}", window)
        return out

    # ── the agent of a document ──────────────────────────────────────────────
    def target(self, address: str, kept: bool = False) -> Target | None:
        """The session the document's last render attached, or None (also for a stored target that cannot be
        read: it is never guessed at). `kept`: when the target is not a session now (an agent, or none), the
        session kept beside it, which a Tell already sent to it still runs in (a stop and the watcher use it)."""
        entry = self.docs.get(address)
        raw = entry.get("target")
        if kept and (not raw or targets_mod.is_agent(raw)):    # an agent is no session (SPEC 9.8)
            raw = entry.get("session")
        if not raw or targets_mod.is_agent(raw):
            return None
        try:
            return Target.from_dict(raw)
        except ValueError:
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
            def settle(new: dict) -> dict:
                new["path"] = str(md)
                new["rendered"] = time.strftime(STAMP_FORMAT)
                for k in SETTING_KEYS:
                    new[k] = settings.get(k)
                # The latest render from an agent session sets the target; a render that finds no agent keeps
                # it, an agent's too; only `--agent none` clears it (SPEC 8.3, D19). The session an agent's
                # write took the target from is the new one's, so none is kept beside it.
                if target is not None:
                    new["target"] = None if target.get("agent") == "none" else {"kind": "session", **target}
                    new.pop("session", None)
                else:
                    new.setdefault("target", None)
                return new
            old, new = self.docs.change(address, settle)
            existed = address in self.entries
            e = self.entry(address)
            if existed and (any(old.get(k) != new[k] for k in SETTING_KEYS)
                            or old.get("target") != new.get("target")):
                e.live.rebuild()
            e.opened, e.rendered = False, True
            warnings, e.warnings = e.warnings, []
            self.index.touch(address)
            return {"doc": address, "url": self.url(address), "tabs": e.bus.count(),
                    "log": list(e.log), "warnings": warnings}

    def forget_root(self, name: str):
        """`sheaf roots forget`: take the root out, and its documents' entries with it (their
        render settings and read state, and the pages the hub holds). The documents themselves
        are files and stay where they are. Each page open on one of them is told `gone`, the last
        event of its stream (SPEC 8.8). Returns the root, or None when there was none."""
        with self._lock:
            root = roots_mod.forget(self.roots, self.docs, self.seen, self.versions, name,
                                    members=self.member_seen)
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
        real = os.path.realpath(root.path)
        return any(os.path.realpath(f) == real for f in member.roots)

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
        mine = [m for m in members if self.owns(m, root)]
        if mine and (private := place.private_member(self, address)) is not None:
            mine = [m for m in mine if m.id == private]       # rule A: a private root's file is its member's alone
        return mine if mine and self.roots.lookup(root.path / at.rel) == root else []

    def judged(self, address: str):
        """(front matter, assignees) of the sheaf at `address`, what its visibility is judged on: the front
        matter read again only when its file moved, the assignees the list has for it now. For a file that is
        not there, both as the hub last judged it, so a poll that no longer sees the sheaf changes nothing;
        None when it never did. ({}, None) in a root the hub does not know. Raises OSError or
        UnicodeDecodeError for a file that is there but cannot be read."""
        at = roots_mod.Address.parse(address)
        root = self.roots.get(at.root)
        if root is None:
            return {}, None
        # Kept by the address's own path, a sheaf's name (9.11), and read where its file is now: opened beneath its root
        # once, judged on that descriptor, and read from it.
        kept = root.path / at.rel
        try:
            top, rel = self.where(address)
            op = beneath.open_beneath(top, rel)
        except (FileNotFoundError, roots_mod.NotFound):
            hit = self._front.get(kept)
            return None if hit is None else hit[1:]
        with op:
            st = os.fstat(op.fd)
            key = (st.st_ino, st.st_mtime_ns, st.st_ctime_ns, st.st_size)
            hit = self._front.get(kept)
            fm = hit[1] if hit is not None and hit[0] == key else visibility.front_matter(op.text())
            assignees = self.assignees(address, fm)
            self._front[kept] = (key, fm, assignees)
            if self.private_roots:
                place.private_member(self, address, fm, place.opened_private(self, op))   # remembered whoever read the file first (rule A)
        return fm, assignees

    def last_judged(self, address: str):
        """(front matter, assignees) of the sheaf at `address` as the hub last judged it, whatever its file holds
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
        """Whether the member may open the document at `address` by its visibility (9.11): a sheaf that is
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
        if judged is None:
            return never_read and self.granted(member, address)
        return visibility.visible_to(judged[0], member, judged[1], self.granted(member, address))

    def may_open(self, member, address: str, fm: dict, opened=place.UNJUDGED) -> bool:
        """Whether `member` may open the sheaf at `address` whose front matter is `fm`, a text read under its lock
        (9.11): as `visible` judges the file on disk, with `projects.toml`'s grant (8.12)."""
        private = place.private_member(self, address, fm, opened)
        if private is not None and private != member.id:        # rule A
            return False
        return visibility.visible_to(fm, member, self.assignees(address, fm), self.granted(member, address))

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
        # Judged where the file is as well as by the address: a link in one project to a sheaf of another (a root
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
        """Those of `members` who own the sheaf at `address`, by its front matter now, as `visible` judges."""
        try:
            fm, assignees = self.judged(address) or ({}, None)
        except (OSError, UnicodeDecodeError):
            return []
        return visibility.owner_of(fm, members, assignees)

    def assignees(self, address: str, fm: dict):
        """The record's assignees of the issue of the sheaf at `address` whose front matter is `fm`, asked by
        the address of the file it names, so a link has the owner of the sheaf it points to; None when the
        list does not know it, or when `fm` names another issue than the one it polled."""
        if self.the_list is None:
            return None
        at = roots_mod.Address.parse(address)
        root = self.roots.get(at.root)
        if root is not None and at.plain:
            placed = place.applies(self, at.root)
            try:
                rel = Path(os.path.realpath(self.file(address, placed))).relative_to(os.path.realpath(root.path))
                rel = rel.as_posix()
                # The list knows a sheaf by its name (9.11), wherever its file is.
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
            # The file, not the hub's copy: `sheaf reply` answers a drop without the hub, and a sheaf with no tab
            # is not refreshed by the pass.
            e = self.entries.get(address)
            if e is None:
                return None
            self.catch_up(e)
            return e.live.current()[1]
        minutes = max(1, -(-self.tell_wait // 60))
        for address, thread, d in self.box_waits.expire(self.tell_wait, text_of):
            self.record("box-expired", address, what=d.kind, project=_project(address), thread=thread)
            self._tell_drop(address, "box-failed", {"id": thread, "kind": d.kind, "minutes": minutes})
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
            row = {"what": d.kind, "project": _project(address), "thread": thread}
            if what == "ignored":
                self.record("drop-status-ignored", address, **row, drop=d.name)
            elif what == "failed":
                self.record("drop-status", address, **row, state="failed", error=got[1])
                self._tell_drop(address, "box-failed", {"id": thread, "kind": d.kind, "error": got[1]})
            elif what == "state":
                self.record("drop-status", address, **row, state=got[0])
                self._tell_drop(address, "box-status", {"id": thread, "kind": d.kind, "state": got[0]})
            if what == "state" and got[0] == "delivered":
                self.index.moved_for_members(address)

    def _tell_drop(self, address: str, name: str, data: dict):
        e = self.entries.get(address)
        if e is not None:
            e.bus.publish(name, data)

    def relay_failed(self, address: str, t, kind: str, error: str, **fields):
        """A relayed Tell that will not be delivered (9.14): its row, and the page's `tellError` by its event."""
        self.record(kind, address, tell=t.id, thread=t.thread, error=error, **fields)
        e = self.entries.get(address)
        if e is not None:
            e.bus.publish("tell-relay-failed", {"id": t.thread, "error": error})

    def expire_relayed(self):
        """Drop every relayed Tell queued an hour ago or more (9.14): each tick, and each relay request, relayed
        Tell and page's /_/doc, so one is dropped within a second of its hour whether or not anything calls in."""
        for address, t in self.relays.expire():
            self.relay_failed(address, t, "tell-expired", relay_mod.EXPIRED)

    def relay_changed(self, address: str, session: str):
        """A relay of the sheaf's live session `session` connected, or its grace ran out: the open pages read
        `/_/doc` again (9.14). A fork that is no longer the live one changes nothing on the page."""
        e = self.entries.get(address)
        if e is None:
            return
        items = work_mod.sessions(visibility.front_matter(e.live.current()[1]))
        if items and items[0]["id"] == session:
            e.bus.publish("relay", {})

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
                e.live.refresh()
                e.last_stat = key        # after: a rebuild that failed is tried again next tick
            except Exception as ex:
                self._rebuild_failed(e, ex)
        try:
            self._watch_drops()                   # after the tabs' refresh: a reply that just landed is in
        except Exception:
            self.record_exception("drops-failed")
        try:
            self.expire_relayed()                 # by the clock, with no relay or page calling in (9.14)
            for address, session in self.relays.lapsed():
                self.relay_changed(address, session)
        except Exception:
            self.record_exception("relays-failed")
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
                e.live.refresh()
                e.last_stat = key
            if self._images_moved(e):           # projects.toml or the owners moved: its images are judged otherwise
                e.live.rebuild()
        except Exception as ex:
            self._rebuild_failed(e, ex)

    def wrote(self, address: str, moved: bool = False):
        """The door made or changed this document's file (SPEC 12): tell its open tabs now, as the
        watcher would within a second, and the open indexes. Compared by its text, not by
        `(mtime, size)`, which a write of the same length within one clock tick leaves as it was.
        `moved`: the file of a sheaf moved (9.11), its text the same; the page is rendered again all
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
