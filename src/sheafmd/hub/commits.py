"""A root that commits (SPEC 8.11). A root whose `.sheaf.toml` says `commit = true` and that is a git
work tree gets one commit for every write made on the page (a save, a task box, a comment), authored
by whoever made it, carrying the document and, with `versions = "root"`, its versions folder
(`.sheaf/versions/<doc-key>/`). The commit is made in the request, under a lock of the root, so the
page's answer comes after it; with `push = true` a thread of its own pushes after it, one push for
however many commits came meanwhile.

    Author(name, email)          who a commit is by
    Commits.saved(root, rel, author, what)
    Commits.settle(timeout)      wait until no push is due (a test, a stopping hub)
"""
import os
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from .. import config
from . import state

GIT_SECONDS = 20                # a commit's git commands
PUSH_SECONDS = 60               # a push
# Who a commit is committed by when the repo names nobody: the hub, not the author.
COMMITTER = ("sheaf", "sheaf@localhost")


@dataclass(frozen=True)
class Author:
    name: str
    email: str


def _env(author: Author | None = None) -> dict:
    env = {**os.environ, "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0"}
    if author is not None:
        env["GIT_AUTHOR_NAME"], env["GIT_AUTHOR_EMAIL"] = author.name, author.email
    return env


def _git(root: Path, *args, author=None, seconds=GIT_SECONDS, given=None):
    # No hook of the repo runs for the hub: hooks are code of whoever wrote `.git/hooks`.
    return subprocess.run(["git", "-C", str(root), "-c", "core.hooksPath=/dev/null", "--literal-pathspecs",
                           *args], capture_output=True, text=True, timeout=seconds, env=_env(author),
                          input=given)


def _ignored(folder: Path, rel: str) -> bool:
    """Whether the repo's ignore rules name `rel` and the index does not hold it. `check-ignore` takes
    paths, not pathspecs: `--literal-pathspecs` makes it fail."""
    return subprocess.run(["git", "-C", str(folder), "check-ignore", "-q", "--", rel], capture_output=True,
                          timeout=GIT_SECONDS, env=_env()).returncode == 0


def _staged(folder: Path, paths: list) -> dict:
    """The index entries of `paths` (folders taken whole): path -> `mode sha stage`. Stage 0 only: a
    path in conflict is never committed (`_commit`)."""
    out = _git(folder, "ls-files", "-s", "-z", "--", *paths).stdout
    return dict(reversed(e.split("\t", 1)) for e in out.split("\0") if e)


def _restage(folder: Path, before: dict, paths: list) -> bool:
    """Put the index entries of `paths` back as `before` held them: what a commit that failed staged
    goes, what the person had staged there comes back."""
    zero = "0" * (64 if _git(folder, "rev-parse", "--show-object-format").stdout.strip() == "sha256" else 40)
    gone = [f"0 {zero}\t{p}" for p in _staged(folder, paths) if p not in before]
    back = [f"{meta}\t{p}" for p, meta in before.items()]
    return _git(folder, "update-index", "-z", "--index-info",
                given="".join(e + "\0" for e in gone + back)).returncode == 0


def _last_line(r) -> str:
    lines = (r.stderr or r.stdout or "").strip().splitlines()
    return lines[-1][:300] if lines else f"git exited {r.returncode}"


class Commits:
    def __init__(self, record):
        """`record(kind, doc, **detail)` writes a diagnostics row (15)."""
        self._record = record
        self._roots: dict[Path, threading.Lock] = {}
        self._lock = threading.Lock()
        self._due: dict[Path, str] = {}            # root folder -> the address of the last commit, for the row
        self._wake = threading.Condition(self._lock)
        self._pushing = False
        self._thread: threading.Thread | None = None

    def _root_lock(self, folder: Path) -> threading.Lock:
        with self._lock:
            return self._roots.setdefault(folder, threading.Lock())

    def saved(self, root, rel: str, author: Author, what: str, gone: str | None = None):
        """`rel`, a document of `root` (a roots.Root), was written by `author`: commit it when the root
        commits. `what` names the write in the subject (`edit`, `comment`). `gone` is the path the document
        was moved from (9.11): the commit is `move: <gone> -> <rel>`, and stages the file's going from there
        with its coming here, and its versions folder's, when the root keeps it. Never raises: a commit that
        fails is a diagnostics row, and the write stands."""
        address = f"{root.name}/{rel}"
        try:
            rc = config.load_root_config(root.path, warn=lambda line: None)
        except config.ConfigError as e:
            self._record("commit-failed", address, error=str(e)[:300])
            return
        if not rc.commit:
            return
        if not root.git:
            self._record("commit-not-git", address)
            return
        # The file the write went to: a link inside the root is staged as the link, not what it names.
        top = os.path.realpath(root.path)
        docs = [rel] + ([gone] if gone else [])
        paths = [os.path.relpath(os.path.realpath(root.path / d), top) for d in docs]
        if rc.versions_inside:
            paths += [str(state.INSIDE / state.doc_key(d)) for d in docs]
        subject = f"move: {gone} -> {rel}" if gone else f"{what}: {rel}"
        try:
            with self._root_lock(root.path):
                if not self._commit(root.path, paths, author, subject, address):
                    return
        except (OSError, subprocess.SubprocessError) as e:
            self._record("commit-failed", address, error=str(e)[:300])
            return
        if rc.push:
            self._push_later(root.path, address)

    def _commit(self, folder: Path, paths: list, author: Author, subject: str, address: str) -> bool:
        """`paths`: the document, then the path it moved from (a move), then their versions folders when the
        root keeps them. A path that is gone is staged as gone: git still lists it."""
        if _ignored(folder, paths[0]):
            return False                              # a document the repo ignores stays out, its versions too
        # A versions folder the repo ignores stays out; the document is committed without it.
        paths = paths[:1] + [p for p in paths[1:] if not _ignored(folder, p)]
        # A path git cannot match stops `add`: a versions folder that no page has made yet (a door write).
        paths = [p for p in paths if (folder / p).exists() or _git(folder, "ls-files", "--", p).stdout]
        if not paths:                                 # never `add -A` with no path: that is the whole tree
            return False
        if _git(folder, "ls-files", "-u", "--", *paths).stdout:
            # A merge stopped on this document: its index is the person's to settle, never the hub's.
            self._record("commit-failed", address, error="the index holds a merge conflict on this document")
            return False
        before = _staged(folder, paths)
        r = _git(folder, "add", "-A", "--", *paths)   # a file an ignore rule names, in the folder, stays out
        if r.returncode != 0:
            kept = _restage(folder, before, paths)
            self._record("commit-failed", address,
                         error=_last_line(r) + ("" if kept else "; the index could not be put back"))
            return False
        if _git(folder, "diff", "--cached", "--quiet", "--", *paths).returncode == 0:
            # Nothing of this write is left to commit; what the person had staged there comes back. An
            # index `add` left as it was is not rewritten: `--index-info` would drop its assume-unchanged flags.
            if _staged(folder, paths) != before and not _restage(folder, before, paths):
                self._record("commit-failed", address, error="the index could not be put back")
            return False
        who = []
        if _git(folder, "config", "user.email").returncode != 0:
            who = ["-c", f"user.name={COMMITTER[0]}", "-c", f"user.email={COMMITTER[1]}"]
        if not author.email:
            mail = _git(folder, "config", "user.email")
            author = Author(author.name, mail.stdout.strip() if mail.returncode == 0 else COMMITTER[1])
        r = _git(folder, *who, "commit", "-q", "--no-verify", "-m", subject, "--", *paths, author=author)
        if r.returncode != 0:
            kept = _restage(folder, before, paths)
            self._record("commit-failed", address,
                         error=_last_line(r) + ("" if kept else "; the index could not be put back"))
            return False
        return True

    # ── the push ─────────────────────────────────────────────────────────────
    def _push_later(self, folder: Path, address: str):
        with self._lock:
            self._due[folder] = address
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._pusher, name="sheaf-push", daemon=True)
                self._thread.start()
            self._wake.notify_all()

    def _pusher(self):
        while True:
            with self._lock:
                if not self._due:
                    self._thread = None
                    self._wake.notify_all()
                    return
                folder, address = self._due.popitem()
                self._pushing = True
            try:
                # Not under the root's lock: a save meanwhile commits, and the next push carries it.
                r = _git(folder, "push", "-q", "origin", "HEAD", seconds=PUSH_SECONDS)
                if r.returncode != 0:
                    # The commit stays; the next write's push carries it.
                    self._record("push-failed", address, error=_last_line(r))
            except (OSError, subprocess.SubprocessError) as e:
                self._record("push-failed", address, error=str(e)[:300])
            finally:
                with self._lock:
                    self._pushing = False
                    self._wake.notify_all()

    def settle(self, timeout: float = 30) -> bool:
        """Wait until no push is due or running; whether that came within `timeout` seconds."""
        with self._lock:
            return self._wake.wait_for(lambda: not self._due and not self._pushing and self._thread is None,
                                       timeout)
