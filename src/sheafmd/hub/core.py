"""
sheafmd.hub.core — the Hub: every open document, the files it keeps, and the watcher's step.

No socket and no thread here: `Hub` is what the request handler (handler.py) talks to and what
the server (server.py) drives. A test builds one and calls `tick()` itself.

A document is served from an Entry: its LiveDocument, its event bus, and the page's HTML in
memory (no file in /tmp, SPEC 8.9).
"""
import json
import os
import re
import secrets
import sys
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .. import __version__, config, diagnostics, paths
from ..agents import registry
from ..agents.base import Adapter, Target
from ..render import render_file
from ..source import STAMP_FORMAT
from . import commits as commits_mod
from . import projects
from . import proxy as proxy_mod
from . import roots as roots_mod
from . import state
from . import visibility
from . import work as work_mod
from .asktell import AskTell
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
    path: Path
    root_id: str = ""            # the id of the root it was made for (SPEC 8.2), which its page carries (10.1)
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


RESTART_TOLD_TTL = 30            # seconds a restart that was announced is still expected


class Hub:
    def __init__(self, port: int, key: str, *, started_by: str = "cli", service: bool = False,
                 version: str = __version__, clock=time.time, proxy=None):
        self.port, self.version, self.service = port, version, service
        self.proxy = proxy                       # the checked `[proxy]` table (9.9), None in loopback mode
        self.started_by, self.clock = started_by, clock
        self.auth = Auth(key, port)
        self.boot = str(uuid.uuid4())
        self.started = time.time()
        self.person = config.user_name()
        self.roots = roots_mod.Roots()
        self.versions = state.Versions()
        self.commits = Commits(self.record)      # the roots that commit (8.11)
        self._told_projects: set = set()         # what check_projects warned of this run (8.12)
        self._front: dict = {}                   # {file: (its stat, its front matter, its assignees)}, for 9.11
        self.the_list = None                     # the list (9.10): a the_list.TheList, set by the server
        self.docs = state.Docs()
        self.seen = state.Seen()
        self.member_seen = state.MemberSeen()
        self.index = Index(self)
        self.tokens = state.Tokens()
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
        # Every Ask and Tell child, and the address a push says it comes from (SPEC 8.10, 11.4).
        self.runner = Jobs()
        self.sender = f"uds:{paths.hub_socket(port)}"
        self.asktell = AskTell(self)

    # ── documents ────────────────────────────────────────────────────────────
    def _versions_of(self, root) -> state.Versions:
        """The versions store of `root`'s documents: inside it with `versions = "root"` (7.4), else the
        state folder's, also when its `.sheaf.toml` cannot be read."""
        try:
            inside = config.load_root_config(root.path, warn=lambda line: None).versions_inside
        except config.ConfigError:
            inside = False
        if inside:
            return state.Versions(root.path, root.name)
        return self.versions

    def check_projects(self, root, rels):
        """Warn of each sheaf folder of `root` (its documents `rels`) that the root's `projects.toml`
        does not name, and of a file that cannot be read, once per hub run (8.12)."""
        try:
            entries = projects.read(root.path)
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

    def committed(self, address: str, member=None, what: str = "edit", by: str | None = None):
        """A write went to `address`, by `member` (a proxy.Member), by `by` (the display name of a door
        caller) or else by the hub's person: a commit, in a root that commits (8.11)."""
        a = roots_mod.Address.parse(address)
        root = self.roots.get(a.root)
        if root is None:
            return
        if member is not None:
            who = Author(member.name, member.email or proxy_mod.default_email(member.id, self.proxy.origin))
        else:
            who = Author(by or self.person, "")
        self.commits.saved(root, a.rel, who, what)

    def url(self, address: str) -> str:
        return f"http://127.0.0.1:{self.port}{roots_mod.url_path(address)}"

    def entry(self, address: str) -> Entry:
        """The entry of a document, made on first use. Raises roots.NotFound for an address
        that is no markdown file inside a root, every time: a file that has gone is gone. Nor is a
        file that 8.2 keeps from the root for lying in a git directory, as the door says (12).
        The file is found before the hub's lock is taken, and its root looked at again under it: a
        `forget_root` that took the lock in between makes the address name nothing, as it does for
        a request that comes after it."""
        name = roots_mod.Address.parse(address).root
        root = self.roots.get(name)
        path = self.roots.document(address)
        with self._lock:
            e = self.entries.get(address)
            if e is not None:
                return e
            if self.roots.get(name) != root:
                raise roots_mod.NotFound(address)
            e = Entry(address, path, root.id)
            e.live = LiveDocument(path, render=lambda text: self._rendered(e, text),
                                  publish=e.bus.publish, by=self.person, clock=self.clock,
                                  versions=self._versions_of(root), address=address)
            e.live.refresh(force=True)           # the first render: e.html
            self.entries[address] = e
            return e

    def _rendered(self, e: Entry, text: str):
        e.html = self._build(e, text)
        e.rebuild_failure = None         # every rebuild that works passes here: the next failure is news

    def _settings(self, address: str) -> dict:
        s = self.docs.get(address)
        return {k: s.get(k) for k in SETTING_KEYS}

    def _build(self, e: Entry, text: str) -> str:
        s = self._settings(e.address)
        root = self.roots.get(roots_mod.Address.parse(e.address).root)
        meta = {"doc": e.address, "root": e.root_id, "boot": self.boot, "version": self.version,
                "service": self.service, "me": self.person,
                "agent": None, "can": [], "lines": {}, "seen": {}}
        log = []
        # The link rule is a warning for whoever renders the document, said once: the hub's
        # re-renders after a save say nothing, so a bare host name is not reported on every save.
        html = render_file(e.path, share=False, src=text, title=s["title"],
                           toc=s["toc"] or "auto", max_image_width=s["max_image_width"] or 1400,
                           by=s["by"], for_=s["for"], theme=s["theme"], credit=s["credit"], log=log,
                           root=root.path if root else None, extra_meta=meta,
                           script_nonce=self.placeholder, image_ok=self._image_rule(root),
                           warn=e.warnings.append if e.first else None)
        e.log, e.first = log, False
        return html

    def share_copy(self, e: Entry) -> str:
        """The share copy of the document as the file is now, with the settings it is shown with."""
        s = self._settings(e.address)
        root = self.roots.get(roots_mod.Address.parse(e.address).root)
        return render_file(e.path, share=True, title=s["title"], toc=s["toc"] or "auto",
                           max_image_width=s["max_image_width"] or 1400, by=s["by"],
                           for_=s["for"], theme=s["theme"], credit=s["credit"], log=[],
                           root=root.path if root else None, image_ok=self._image_rule(root))

    def _image_rule(self, root):
        """In proxy mode, a local image is embedded only when the root 8.2 finds for its file is the
        document's own root (9.9 "Local images"), in every render of the hub, the page and the share
        copy alike. None in loopback mode: every local image, as 6.2 says."""
        if self.proxy is None:
            return None
        return lambda path: root is not None and self.roots.lookup(path) == root

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
            meta = json.loads(m.group(2))
            if member is None:
                meta["seen"] = self.seen.get(e.address)
                v = self.asktell.view(e.address)
                meta["agent"], meta["can"], meta["lines"] = v.agent(), v.can(), v.lines
            else:
                meta.update(me=member.name, seen=self.member_seen.get(member.id, e.address),
                            agent=None, can=[], lines=proxy_mod.member_lines(), proxy=True,
                            member=member.id)
                work, meta["can"] = self.member_work(e, member)
                if work is not None:
                    meta["work"] = work
            html = (html[:m.start(2)] + json.dumps(meta).replace("<", "\\u003c") + html[m.end(2):])
        return html

    def member_work(self, e: Entry, member):
        """The `work` of a member's page (None when it is not a sheaf of the list's root) and its `can`:
        box-ask and box-tell while the live session runs on the box and `[list]` names a `tell_dir` (10.1).
        The meta block and every /_/doc answer carry both, so a fork seen by the page changes what it offers."""
        st = work_mod.state(self, e.address, e.live.current()[1])
        if st is None:
            return None, []
        return self.work_meta(e, member, st), st.can

    def work_meta(self, e: Entry, member, st) -> dict:
        """What the page's Work on this shows a member (9.12, 10.1): the command that forks the sheaf's session
        on their machine, the one that attaches to James's window when they have a shell on the box, the
        sessions and where the live one runs. None for a page that is not a sheaf of the list's root."""
        out = {"sessions": st.sessions, "live": st.live}
        if st.box:                  # the fork fetches a transcript of the box: none there, nothing to fork
            out["fork"] = f"tiroir work {self.proxy.origin}{roots_mod.url_path(e.address)}"
        # James names a project's window <client>_<project>: with a dash, a-b/c and a/b-c would share one.
        window = "_".join(roots_mod.Address.parse(e.address).rel.split("/")[:2])
        # Two shells and tmux read the command: a name with another character (`.`, `:`, a space) is left out.
        if member.shell and st.cfg.attach and re.fullmatch(r"[A-Za-z0-9_-]+", window):
            out["attach"] = st.cfg.attach.replace("{window}", window)
        return out

    # ── the agent of a document ──────────────────────────────────────────────
    def target(self, address: str) -> Target | None:
        """The session the document's last render attached, or None (also for a stored target
        that cannot be read: it is never guessed at)."""
        raw = self.docs.get(address).get("target")
        if not raw:
            return None
        try:
            return Target.from_dict(raw)
        except ValueError:
            return None

    def adapter(self, agent: str) -> Adapter:
        return registry.adapter_for(agent, self.sender)

    def stop_jobs(self):
        """Kill every Ask and Tell child's process group, and let the pushes due go out (a clean stop,
        SPEC 8.4, 8.11)."""
        self.runner.kill_all()
        self.commits.settle(commits_mod.PUSH_SECONDS)

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
        address = self.roots.address(md)
        with self._lock:
            old = self.docs.get(address)
            new = dict(old)
            new["path"] = str(md)
            new["rendered"] = time.strftime(STAMP_FORMAT)
            for k in SETTING_KEYS:
                new[k] = settings.get(k)
            # The latest render from an agent sets the target; a render that finds no agent keeps
            # it; only `--agent none` clears it (SPEC 8.3, D19).
            if target is not None:
                new["target"] = None if target.get("agent") == "none" else target
            else:
                new.setdefault("target", None)
            self.docs.put(address, new)
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
            # An Ask or a Tell still running on a document that is gone: its dot, its
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
        at = roots_mod.Address.parse(address)
        root = self.roots.get(at.root)
        if root is None or not at.plain:
            return False
        return self.owns(member, root) and self.roots.lookup(root.path / at.rel) == root

    def _judged(self, address: str):
        """(front matter, assignees) of the sheaf at `address`, what its visibility is judged on: the front
        matter read again only when its file moved, the assignees the list has for it now. For a file that is
        not there, both as the hub last judged it, so a poll that no longer sees the sheaf changes nothing;
        None when it never did. ({}, None) in a root the hub does not know. Raises OSError or
        UnicodeDecodeError for a file that is there but cannot be read."""
        at = roots_mod.Address.parse(address)
        root = self.roots.get(at.root)
        if root is None:
            return {}, None
        f = root.path / at.rel
        try:
            st = f.stat()
        except FileNotFoundError:
            hit = self._front.get(f)
            return None if hit is None else hit[1:]
        key = (st.st_ino, st.st_mtime_ns, st.st_ctime_ns, st.st_size)
        hit = self._front.get(f)
        fm = hit[1] if hit is not None and hit[0] == key else visibility.front_matter(f.read_text(encoding="utf-8"))
        assignees = self.assignees(address, fm)
        self._front[f] = (key, fm, assignees)
        return fm, assignees

    def visible(self, member, address: str, never_read: bool = True) -> bool:
        """Whether the member may open the document at `address` by its visibility (9.11): a sheaf that is
        its owner's alone is no other member's. A file that is not there is judged by the front matter it
        had when the hub last read it, so its going away is told to whom it was visible; one the hub never
        read is `never_read` (a page answers it as a missing document all the same, a stream tells nobody).
        A file that is there but cannot be read, or not as UTF-8, is no member's: the hub may still hold its
        last good page."""
        try:
            judged = self._judged(address)
        except (OSError, UnicodeDecodeError):
            return False
        if judged is None:
            return never_read
        return visibility.visible_to(judged[0], member, judged[1])

    def owners(self, address: str, members) -> list:
        """Those of `members` who own the sheaf at `address`, by its front matter now, as `visible` judges."""
        try:
            fm, assignees = self._judged(address) or ({}, None)
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
            try:
                rel = Path(os.path.realpath(root.path / at.rel)).relative_to(os.path.realpath(root.path))
                address = f"{root.name}/{rel.as_posix()}"
            except ValueError:
                pass
        return self.the_list.assignees(address, visibility.text(fm, "issue"))

    def jobs(self) -> dict:
        telling = []
        for address, e in list(self.entries.items()):
            telling += [[address, cid] for cid in e.live.waiting()]
        return {"asking": self.jobs_asking(), "telling": telling}

    def jobs_asking(self) -> list:
        """`[[doc, id], …]` of the Asks that run: what turns a document's dot orange (SPEC 8.6)."""
        return self.runner.active("ask")

    # ── the watcher's step (SPEC 8.9) ────────────────────────────────────────
    def tick(self):
        """One pass of the watcher, run every second. For each document with an open tab or a
        Tell wait: give up on waits nobody answers, and when the file's (mtime, size) moved,
        catch up with it and tell the tabs. A failure in one document is written down and never
        stops the pass."""
        for e in list(self.entries.values()):
            try:
                e.live.expire(self.tell_wait, self.asktell.product(e.address))
                self._observe(e)
                if not (e.bus.count() or e.live.waiting()):
                    continue
                try:
                    st = e.path.stat()
                except OSError:
                    continue
                key = (st.st_mtime_ns, st.st_size)
                if key == e.last_stat:
                    continue
                e.live.refresh()
                e.last_stat = key        # after: a rebuild that failed is tried again next tick
            except Exception as ex:
                self._rebuild_failed(e, ex)
        try:
            self.index.tick(self.clock())
        except Exception:               # a traceback, not `error=`: see `record_exception`
            self.record_exception("status-failed")

    def _observe(self, e: Entry):
        """What the session told by this document is doing. A failure here is written down and
        never stops the pass."""
        try:
            self.asktell.observe(e)
        except Exception as ex:
            diagnostics.record("hub", "session-state-failed", e.address,
                               error=f"{type(ex).__name__}: {ex}")

    def catch_up(self, e: Entry):
        """Take in a write from outside before a page is served, for a document with no tab
        (the watcher skips it) as for one with: when the file's (mtime, size) moved, refresh,
        which tells the tabs. A rebuild that fails is written down and the last good page is
        served; it is tried again on the next request."""
        try:
            st = e.path.stat()
            key = (st.st_mtime_ns, st.st_size)
            if key != e.last_stat:
                e.live.refresh()
                e.last_stat = key
        except Exception as ex:
            self._rebuild_failed(e, ex)

    def wrote(self, address: str):
        """The door made or changed this document's file (SPEC 12): tell its open tabs now, as the
        watcher would within a second, and the open indexes. Compared by its text, not by
        `(mtime, size)`, which a write of the same length within one clock tick leaves as it was."""
        e = self.entries.get(address)
        if e is not None:
            try:
                st = e.path.stat()
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
            st = e.path.stat()
            key = (st.st_mtime_ns, st.st_size)
        except OSError:
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
        """Ask the hub to stop. An upgrade stop is taken only while no Ask or Tell runs, unless
        `force` (`sheaf restart`: the person's own decision): False when it was refused, and the
        hub goes on. Once an upgrade stop is taken no job starts, so none is killed by it (8.4).
        A stop or a signal that is under way is not turned into an upgrade by a later upgrade stop:
        under the service that would exit 75 and start the hub again, which the person stopped.
        Only an upgrade stop gives way: a stop or a signal that comes after one ends the hub for good.
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
        """Whether an Ask runs or a Tell waits anywhere (what `GET /_/jobs` lists), or a Tell's
        delivery or a stop message is still on its way: a delivery whose wait has ended (the
        reply came first, or the clock gave up) and the stop message of a cancelled Tell have
        no wait to show, and an upgrade stop would kill them half-way (8.4)."""
        j = self.jobs()
        return bool(j["asking"] or j["telling"]
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
