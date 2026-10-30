"""A root that commits (SPEC 8.11). A root whose `.sheaf.toml` says `commit = true` and that is a git
work tree gets one commit for every write made on the page (a save, a task box, a comment), authored
by whoever made it, carrying the document and, with `versions = "root"`, its versions folder
(`.sheaf/versions/<doc-key>/`). The commit is made in the request, under the lock of the root's repo (one
for every root of one git dir: they share its index and HEAD, #73), so the page's answer comes after it; with `push = true` a thread of its own pushes after it, one push for
however many commits came meanwhile. Before it pushes, the hub fetches its branch and takes in what the remote
got meanwhile (a pull request merged on GitHub): its own unpushed commits are made again on top, in git's object
store, and the work tree moves only for the files the remote changed, under their locks; a conflict changes
nothing and pushes nothing (#62).

    Author(name, email)          who a commit is by
    Commits(record, guard)       `guard(root, files)`: the locks a writer of `files` holds before the repo's
    Commits.saved(root, rel, author, what)
    Commits.settle(timeout)      wait until no push is due (a test, a stopping hub)
"""
import os
import subprocess
import threading
from contextlib import nullcontext
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
                           *args], capture_output=True, text=True, encoding="utf-8",
                          errors="surrogateescape", timeout=seconds, env=_env(author), input=given)


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


def _again(folder: Path, commit: str, onto: str):
    """`commit` made again on top of `onto`, in the object store alone (a cherry-pick that touches neither the
    index nor the work tree): (the new commit, []), or (None, the paths in conflict). Author, committer and
    message are kept."""
    r = _git(folder, "merge-tree", "--write-tree", "--name-only", "-z", f"--merge-base={commit}^", onto, commit)
    head, _, _ = r.stdout.partition("\0\0")
    tree, *conflicts = head.split("\0")
    if r.returncode != 0:
        return None, sorted(set(conflicts)) if r.returncode == 1 else [_last_line(r)]
    if tree == _git(folder, "rev-parse", f"{onto}^{{tree}}").stdout.strip():
        return onto, []                                # the remote holds this change already: no empty commit
    meta = _git(folder, "log", "-1", "--format=%an%x00%ae%x00%ad%x00%cn%x00%ce%x00%cd", "--date=raw",
                commit).stdout.rstrip("\n").split("\0")
    # The message as bytes: text mode would turn a CR into a LF.
    message = subprocess.run(["git", "-C", str(folder), "cat-file", "commit", commit], capture_output=True,
                             timeout=GIT_SECONDS, env=_env()).stdout.partition(b"\n\n")[2]
    env = dict(zip(["GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_AUTHOR_DATE",
                    "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "GIT_COMMITTER_DATE"], meta))
    made = subprocess.run(["git", "-C", str(folder), "commit-tree", tree, "-p", onto, "-F", "-"], capture_output=True,
                          timeout=GIT_SECONDS, env={**_env(), **env}, input=message)
    if made.returncode != 0:
        return None, [made.stderr.decode("utf-8", "replace").strip()[-300:] or f"git exited {made.returncode}"]
    return made.stdout.decode().strip(), []


class Commits:
    def __init__(self, record, guard=None):
        """`record(kind, doc, **detail)` writes a diagnostics row (15). `guard(root, files)` gives a context that
        holds what a writer of each of `files` (absolute paths) holds before the repo's lock (9.11): a pull takes
        it before it changes them."""
        self._record = record
        self._guard = guard or (lambda root, files: nullcontext())
        self._repos: dict[str, threading.Lock] = {}  # a repo's git dir, links resolved -> its commit lock
        self._lock = threading.Lock()
        self._due: dict[Path, tuple] = {}          # root folder -> (the root, the address of the last commit)
        self._wake = threading.Condition(self._lock)
        self._pushing = False
        self._thread: threading.Thread | None = None

    def _repo_lock(self, folder: Path) -> threading.Lock:
        """The commit lock of the repo `folder` is in, keyed by its git dir: two roots in one repo share an index
        and a HEAD, so one lock (#73). A linked worktree has a git dir, an index and a HEAD of its own."""
        r = _git(folder, "rev-parse", "--absolute-git-dir")
        key = os.path.realpath(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else os.path.realpath(folder)
        with self._lock:
            return self._repos.setdefault(key, threading.Lock())

    def saved(self, root, rel: str, author: Author, what: str, gone: str | None = None, key: str | None = None):
        """`rel`, the file of a document of `root` (a roots.Root), was written by `author`: commit it when the
        root commits. `what` names the write in the subject (`edit`, `comment`). `key` is the document's own path,
        its address in the root, when that is not `rel` (a sheaf's name, 9.11), which names its versions folder.
        `gone` is the path the file was moved from (9.11): the commit is `move: <gone> -> <rel>`, and stages the
        file's going from there with its coming here. Never raises: a commit that fails is a diagnostics row, and
        the write stands."""
        key = key or rel
        address = f"{root.name}/{key}"
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
        def file(d):
            return os.path.relpath(os.path.realpath(root.path / d), top)
        paths = [file(rel)] + ([str(state.INSIDE / state.doc_key(key))] if rc.versions_inside else [])
        subject = f"move: {gone} -> {rel}" if gone else f"{what}: {rel}"
        try:
            with self._repo_lock(root.path):
                if not self._commit(root.path, paths, author, subject, address, gone=[file(gone)] if gone else []):
                    return
        except (OSError, subprocess.SubprocessError) as e:
            self._record("commit-failed", address, error=str(e)[:300])
            return
        if rc.push:
            self._push_later(root, address)

    def _commit(self, folder: Path, paths: list, author: Author, subject: str, address: str,
                gone: list = ()) -> bool:
        """`paths`: the document's file, then its versions folder when the root keeps it; `gone`: the path its file
        moved from (a move). A path that is gone is staged as gone: git still lists it."""
        if _ignored(folder, paths[0]):
            # A document the repo ignores stays out, its versions too; but a move into an ignored folder still
            # takes the file out of the place git holds it (9.11), or git keeps it there.
            if not gone:
                return False
            paths = list(gone)
        else:
            paths = list(paths) + list(gone)
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
    def _push_later(self, root, address: str):
        with self._lock:
            self._due[root.path] = (root, address)
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
                folder, (root, address) = self._due.popitem()
                self._pushing = True
            try:
                if not self._pull(root, address):
                    continue
                # Not under the repo's lock: a save meanwhile commits, and the next push carries it.
                r = _git(folder, "push", "-q", "origin", "HEAD", seconds=PUSH_SECONDS)
                if r.returncode != 0:
                    # The commit stays; the next write's push carries it.
                    self._record("push-failed", address, error=_last_line(r))
            except Exception as e:                     # never a dead thread: a push that never comes is a row
                self._record("push-failed", address, error=str(e)[:300] or type(e).__name__)
            finally:
                with self._lock:
                    self._pushing = False
                    self._wake.notify_all()

    # ── the pull before it ───────────────────────────────────────────────────
    def _pull(self, root, address: str) -> bool:
        """Take in what the remote's branch got that the hub's lacks (#62); whether to push. A failed fetch is a
        `push-failed` row, a remote the hub cannot take in a `push-diverged` row: nothing is pushed, and the next
        write's push tries again. A branch the remote does not have yet is pushed as it is."""
        folder = root.path
        branch = _git(folder, "symbolic-ref", "-q", "--short", "HEAD")
        if branch.returncode != 0:
            return True                                # a detached HEAD: the push says what it says
        r = _git(folder, "fetch", "-q", "--no-tags", "origin", f"refs/heads/{branch.stdout.strip()}",
                 seconds=PUSH_SECONDS)
        if r.returncode != 0:
            if "couldn't find remote ref" in r.stderr:
                return True
            self._record("push-failed", address, error=_last_line(r))
            return False
        theirs = _git(folder, "rev-parse", "--verify", "-q", "FETCH_HEAD^{commit}").stdout.strip()
        base = _git(folder, "merge-base", "HEAD", theirs)
        if base.returncode != 0:
            self._record("push-diverged", address, paths=[], error="the remote's branch shares no history with the hub's")
            return False
        base = base.stdout.strip()
        if base == theirs:
            return True                                # nothing new on the remote
        top = Path(_git(folder, "rev-parse", "--show-toplevel").stdout.strip())
        changed = [p for p in _git(folder, "diff", "--name-only", "--no-renames", "-z", base, theirs).stdout.split("\0")
                   if p]
        # The writers' locks first, the repo's last (9.11): no write of a file the remote changed comes between
        # the look at it and its new text, and no commit of any root of the repo between the hub's HEAD read and moved.
        with self._guard(root, [top / p for p in changed]), self._repo_lock(folder):
            return self._catch_up(folder, theirs, address)

    def _catch_up(self, folder: Path, theirs: str, address: str) -> bool:
        head = _git(folder, "rev-parse", "HEAD").stdout.strip()
        if _git(folder, "rev-list", "--merges", f"{theirs}..{head}").stdout.strip():
            self._record("push-diverged", address, paths=[], error="the hub's unpushed commits hold a merge")
            return False
        new = theirs
        for c in _git(folder, "rev-list", "--reverse", f"{theirs}..{head}").stdout.split():
            new, conflicts = _again(folder, c, new)
            if new is None:
                self._record("push-diverged", address, paths=conflicts, error="the remote changed what the hub did")
                return False
        # The work tree moves for what differs between the two alone, and refuses over a change of the person's.
        r = _git(folder, "read-tree", "-m", "-u", head, new)
        if r.returncode != 0:
            self._record("push-diverged", address, paths=[], error=_last_line(r))
            return False
        r = _git(folder, "update-ref", "-m", "sheaf: on top of the remote's", "HEAD", new, head)
        if r.returncode != 0:
            # The files are the remote's; HEAD is not: put the index and the work tree back to it.
            _git(folder, "read-tree", "-m", "-u", new, head)
            self._record("push-diverged", address, paths=[], error=_last_line(r))
            return False
        return True

    def settle(self, timeout: float = 30) -> bool:
        """Wait until no push is due or running; whether that came within `timeout` seconds."""
        with self._lock:
            return self._wake.wait_for(lambda: not self._due and not self._pushing and self._thread is None,
                                       timeout)
