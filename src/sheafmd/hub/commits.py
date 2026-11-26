"""A root that commits (SPEC 8.11). A root whose `.sheaf.toml` says `commit = true` and that is a git
work tree gets one commit for every write made on the page (a save, a task box, a comment), authored
by whoever made it, carrying the document and, with `versions = "root"`, its versions folder
(`.sheaf/versions/<doc-key>/`). The commit is made in the request, under the lock of the root's repo (one
for every root of one git dir: they share its index and HEAD, #73), so the page's answer comes after it; with `push = true` a thread of its own pushes after it, one push for
however many commits came meanwhile. Before it pushes, the hub fetches its branch and takes in what the remote
got meanwhile (a pull request merged on GitHub): its own unpushed commits are made again on top, in git's object
store, and the work tree moves only for the files the remote changed, under their locks; a conflict changes
nothing and pushes nothing (#62). The watcher's poll hands each repo that pushes to the same thread at most once a
minute, with no save (#75): a change merged on the remote lands within a minute, and a push that failed goes out.
The pull and the push are the repo's, not a root's: one of either per repo, however many of its roots asked, and
none while the roots of the repo that commit disagree on `push` (#89).
The versions a root keeps inside that no write made (a page opened, a change from outside rendered, a pin) are
committed by the same thread, `versions: <path>`, before its pull and at the poll, push or not (#92): an untracked
version is never pushed, and git refuses to write the remote's over it, even the same text.

    Author(name, email)          who a commit is by
    Commits(record, guard, roots)  `guard(root, files)`: the locks a writer of `files` holds before the repo's;
                                 `roots()`: the registered roots, whose settings the repo's push agrees with
                                 `refuse_rewrite`: refuse a remote branch that lost the tip last seen there
    Commits.saved(root, rel, author, what)
    Commits.poll(roots)          the watcher's tick: hand each repo that pushes to the pusher, once a minute
    Commits.settle(timeout)      wait until no push is due (a test)
    Commits.stop()               a stopping hub: the pushes due go out within STOP_SECONDS, then the hub ends its git
    blame(file, text, lines)     who last changed each of `lines` of `text`, and when: who pressed a box (9.10, #110)

The hub owns its git (#95). Every git it runs is in a session of its own, so a signal to the hub's group (a
Ctrl-C at its terminal) never reaches it, and the unit's `KillMode=mixed` (14.3) leaves it to the hub. A stopping
hub lets the pull and push due finish for STOP_SECONDS, then sends SIGTERM to the group of the fetch or push still
running and, after END_GRACE, SIGKILL; it starts no fetch or push after that. A git the hub ended is a
`push-stopped` row, never a `push-failed`; the commit stays, and the next hub's write or poll pushes it.
"""
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path

from .. import config, signals
from ..source import md_hash
from . import state
from .repos import CREDENTIALS, CREDENTIALS_LOCK, token_env

GIT_SECONDS = 20                # a commit's git commands
BLAME_SECONDS = 2               # a blame the list's page waits for (9.10)
PUSH_SECONDS = 60               # a push
FETCH_SECONDS = 60              # the least time between two of the poll's pulls of one repo (#75)
STOP_SECONDS = 15               # how long a stopping hub lets the pull and push due run: under the poll's fetch (#95)
END_GRACE = 5                   # from the SIGTERM of a git the stop ends to its SIGKILL
# Who a commit is committed by when the repo names nobody: the hub, not the author.
COMMITTER = ("sheaf", "sheaf@localhost")
LAST_SEEN = "refs/sheaf/last-seen"  # per branch: the remote tip the hub last took in or pushed (the rewrite guard)
REWRITTEN = "the remote's branch no longer holds what it held"
EVEN = "even"                   # `_pull`: the hub's branch is the remote's, nothing to push


@dataclass(frozen=True)
class Author:
    name: str
    email: str


def _credential(folder: Path):
    """The token function of the clone that holds `folder` (the clone's folder or one beneath it), None for any other."""
    here = os.path.realpath(folder)
    with CREDENTIALS_LOCK:          # a copy: a serving thread adds a clone meanwhile
        held = list(CREDENTIALS.items())
    for clone, token in held:
        if here == clone or here.startswith(clone + os.sep):
            return token
    return None


def _env(author: Author | None = None, folder: Path | None = None) -> dict:
    """The environment of a git command; `folder`: where it runs. In a clone every command gets the token, asked once a
    call and never kept: the clone is blobless, so any command (`read-tree`, `merge-tree`) may fetch a blob from the remote
    (SPEC 14). It lives in this process's environment only, never in a config or a file."""
    env = {**os.environ, "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0"}
    if folder is not None and (token := _credential(folder)) is not None and (t := token()):
        env.update(token_env(t))
    if author is not None:
        env["GIT_AUTHOR_NAME"], env["GIT_AUTHOR_EMAIL"] = author.name, author.email
    return env


class Stopped(Exception):
    """The hub is stopping: it ended the git (`ended`), or never started it (#95)."""

    def __init__(self, text: str, ended: bool = False):
        super().__init__(text)
        self.ended = ended


class LookFailed(Exception):
    """A look of git's that a pull needs ran out of time, could not start or failed: not knowing, never "none" (ticket 209)."""


class Children:
    """The fetches and pushes running, which a stopping hub ends (#95). Once `end` has run, none starts."""

    def __init__(self):
        self._lock = threading.Lock()
        self._running: set[subprocess.Popen] = set()
        self._signalled: set[subprocess.Popen] = set()   # the ones `end` sent a signal to
        self._ended = False

    def run(self, argv, seconds, env):
        with self._lock:
            if self._ended:
                raise Stopped("the hub is stopping")
            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, encoding="utf-8", errors="surrogateescape", env=env,
                                    start_new_session=True)
            self._running.add(proc)
        try:
            out, err = proc.communicate(timeout=seconds)
        except subprocess.TimeoutExpired:
            # The group: git's ssh or helper holds its pipes. A process that left the group may hold them still,
            # so the pipes are closed, not read to their end: the one pusher never waits on it.
            self._signal(proc, signal.SIGKILL)
            proc.wait()
            for pipe in (proc.stdout, proc.stderr):
                pipe.close()
            raise
        finally:
            with self._lock:
                self._running.discard(proc)
                signalled = proc in self._signalled
                self._signalled.discard(proc)
        if signalled and proc.returncode != 0:
            # Only a git the stop signalled: one that failed on its own just before is the failure it is.
            raise Stopped(f"git ended by the stop ({proc.returncode})", ended=True)
        return subprocess.CompletedProcess(argv, proc.returncode, out, err)

    @staticmethod
    def _signal(proc, sig):
        if proc.returncode is not None:
            return
        try:
            signals.send_group(proc, sig)
        except (ProcessLookupError, PermissionError, signals.Refused):
            pass

    @property
    def ended(self) -> bool:
        return self._ended

    def end(self, sig) -> bool:
        """`sig` to the group of every git running, and none starts from here; whether any ran."""
        with self._lock:
            self._ended = True
            running = [proc for proc in self._running if proc.returncode is None]   # one already reaped ended on its own
            self._signalled.update(running)
        for proc in running:
            self._signal(proc, sig)
        return bool(running)


def _git(root: Path, *args, author=None, seconds=GIT_SECONDS, given=None, children=None, index=None):
    """`children`: given for a fetch or a push, which a stopping hub ends (#95). Every git runs in a session of
    its own: a signal to the hub's group never reaches it. `index`: an index file of the hub's own, not the repo's."""
    # No hook of the repo runs for the hub: hooks are code of whoever wrote `.git/hooks`.
    argv = ["git", "-C", str(root), "-c", "core.hooksPath=/dev/null", "--literal-pathspecs", *args]
    folder = root
    if children is not None:
        return children.run(argv, seconds, _env(author, folder))
    env = _env(author, folder) | ({"GIT_INDEX_FILE": str(index)} if index else {})
    return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="surrogateescape",
                          timeout=seconds, env=env, input=given, start_new_session=True)


def blame(file: Path, text: str, lines, seconds: float = BLAME_SECONDS) -> dict:
    """{0-based line: (author's name, author's e-mail, epoch seconds)} of each of `lines` of `text`, the rectoverso whose
    file is `file`, by the commit that last changed that line (8.11): its tick, on the list (`tick: <path>`) or in the
    page (`edit: <path>`) (9.10, #110). Blamed on `text` itself, so the lines are the ones read. A line no commit holds
    (a root that is no git work tree, a write not committed yet) is left out."""
    if not lines:
        return {}
    ranges = [arg for n in sorted(set(lines)) for arg in ("-L", f"{n + 1},{n + 1}")]
    try:
        r = _git(file.parent, "blame", "--line-porcelain", *ranges, "--contents", "-", "--", file.name,
                         given=text, seconds=seconds)
    except (OSError, subprocess.SubprocessError):
        return {}
    if r.returncode != 0:
        return {}
    out, head = {}, {}
    for line in r.stdout.split("\n"):
        if line.startswith("\t"):              # the line's own text ends its block
            if head.get("sha", "").strip("0") and "time" in head:
                out[head["line"]] = (head.get("name", ""), head.get("mail", ""), head["time"])
            head = {}
        elif not head and line:                 # `<sha> <line in the commit> <line in text>`
            sha, _, final = line.split(" ")[:3]
            head = {"sha": sha, "line": int(final) - 1}
        elif line.startswith("author "):
            head["name"] = line[len("author "):]
        elif line.startswith("author-mail "):
            head["mail"] = line[len("author-mail "):].strip("<>")
        elif line.startswith("author-time "):
            head["time"] = int(line[len("author-time "):])
    return out


def _repo(folder: Path) -> str:
    """The repo `folder` is in, by its git dir, links resolved (#73): two roots in one repo share an index, a HEAD
    and a remote. A linked worktree has a git dir of its own. A folder git cannot place is a repo of its own."""
    r = _git(folder, "rev-parse", "--absolute-git-dir")
    return os.path.realpath(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else os.path.realpath(folder)


def _is_top(folder: Path) -> bool:
    """Whether `folder` is the top of a git work tree now, as a root of a repo is (SPEC 8.2)."""
    try:
        r = _git(folder, "rev-parse", "--show-toplevel")
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and os.path.realpath(r.stdout.strip()) == os.path.realpath(folder)


def _is_git(root) -> bool:
    """Whether `root` is a repo now: the registry's flag is as of its registration, and a folder registered before
    `git init` keeps `git = false`, so git is asked when the flag is false (8.11)."""
    return root.git or _is_top(root.path)


def _ignored(folder: Path, rel: str) -> bool:
    """Whether the repo's ignore rules name `rel` and the index does not hold it. `check-ignore` takes
    paths, not pathspecs: `--literal-pathspecs` makes it fail."""
    return subprocess.run(["git", "-C", str(folder), "check-ignore", "-q", "--", rel], capture_output=True,
                          timeout=GIT_SECONDS, env=_env(), start_new_session=True).returncode == 0


def _address(folder: Path) -> str:
    """The path in the root a versions folder of the root's store is the key of (`state.Versions`), from its
    `address` file: read without following a link, one line, and believed only when it is the folder's key, so a
    file planted there (a link to a token, a forged path) never reaches a commit's subject or the ignore check.
    Else the folder's name."""
    key = state.read_small(folder / "address")
    return key if key is not None and "\n" not in key and state.doc_key(key) == folder.name else folder.name


def _staged(folder: Path, paths: list) -> dict:
    """The index entries of `paths` (folders taken whole): path -> `mode sha stage`. Stage 0 only: a
    path in conflict is never committed (`_commit`)."""
    out = _git(folder, "ls-files", "-s", "-z", "--", *paths).stdout
    return dict(reversed(e.split("\t", 1)) for e in out.split("\0") if e)


def _restage(folder: Path, before: dict, paths: list) -> bool:
    """Put the index entries of `paths` back as `before` held them: what a commit that failed staged
    goes, what the person had staged there comes back. Only the entries whose blob or mode changed are
    written: `--index-info` drops the assume-unchanged and skip-worktree flags of an entry it writes (#49)."""
    now = _staged(folder, paths)
    zero = "0" * (64 if _git(folder, "rev-parse", "--show-object-format").stdout.strip() == "sha256" else 40)
    gone = [f"0 {zero}\t{p}" for p in now if p not in before]
    back = [f"{meta}\t{p}" for p, meta in before.items() if now.get(p) != meta]
    if not gone and not back:
        return True
    return _git(folder, "update-index", "-z", "--index-info",
                given="".join(e + "\0" for e in gone + back)).returncode == 0


def _locking(folder: Path, *args, author=None):
    """`_git` for a command that takes the index lock (`add`, `commit`). Killed on its bound, it leaves the lock: that
    goes (#38), unless it was there before, another git's (the command then fails on it, no timeout). One a person's
    git took while the hub's hung before taking it goes too, a window the repo's lock cannot close."""
    lock = _git(folder, "rev-parse", "--path-format=absolute", "--git-path", "index.lock").stdout.strip()
    held = bool(lock) and os.path.lexists(lock)
    try:
        return _git(folder, *args, author=author)
    except subprocess.TimeoutExpired:
        if lock and not held:
            try:
                os.unlink(lock)
            except FileNotFoundError:
                pass
        raise


def _author(folder: Path, commit: str, rel: str) -> str:
    """Who last changed `rel` as of `commit`: `?` when git cannot say, since a missing name must never stop a pull."""
    try:
        return _git(folder, "log", "-1", "--format=%an", commit, "--", rel).stdout.strip() or "?"
    except (subprocess.SubprocessError, OSError):
        return "?"


def _hash_of(path: Path) -> str | None:
    """The hash of the text of `path`, None for a file that is not there or not text."""
    try:
        return md_hash(path.read_bytes().decode("utf-8"))      # the bytes, as a page reads them: no newline translation
    except (OSError, ValueError):
        return None


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
                             timeout=GIT_SECONDS, env=_env(), start_new_session=True).stdout.partition(b"\n\n")[2]
    env = dict(zip(["GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_AUTHOR_DATE",
                    "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "GIT_COMMITTER_DATE"], meta))
    made = subprocess.run(["git", "-C", str(folder), "commit-tree", tree, "-p", onto, "-F", "-"], capture_output=True,
                          timeout=GIT_SECONDS, env={**_env(), **env}, input=message, start_new_session=True)
    if made.returncode != 0:
        return None, [made.stderr.decode("utf-8", "replace").strip()[-300:] or f"git exited {made.returncode}"]
    return made.stdout.decode().strip(), []


def _untrack_pin_times(folder: Path) -> tuple[bool, str | None]:
    """A pin time is each hub's own (7.4): every one git holds in the versions store of the root at `folder`, in HEAD or
    the index, taken in before the store's `.gitignore` kept it out (an older hub, a `.gitignore` that let it in), leaves
    git; the file stays on disk (ticket 203 C). Only git's index and HEAD change, never a file of the work tree, so who owns
    a folder of the store, or a link there, cannot matter; and only a pin time (`state.is_pin_time`) leaves. The index
    first, through `_locking`: once it holds none, any commit, the hub's or a person's, takes them out. Then HEAD, in a
    commit of its own, `versions: pin times out of git`, made on an index of the hub's own from HEAD less those files
    (`commit -- paths` would take them back from the work tree), in a folder made new for it and removed whole, its lock
    with it, however git ends. Run under the repo's lock before a commit of the store. (made, error): `made`, that commit
    was made, owed a push whatever comes after; `error`, what git refused: the store's versions are then not committed,
    since its index may still hold a pin time."""
    head = _git(folder, "rev-parse", "-q", "--verify", "HEAD").stdout.strip()
    listed = _git(folder, "ls-files", "-z", "--", str(state.INSIDE)).stdout.split("\0")
    if head:
        listed += _git(folder, "ls-tree", "-r", "--name-only", "-z", head, "--", str(state.INSIDE)).stdout.split("\0")
    held = sorted({p for p in listed if state.is_pin_time(p)})
    if not held:
        return False, None
    try:
        if _locking(folder, "update-index", "--force-remove", "--", *held).returncode:
            return False, "a pin time git holds could not be taken out of the index"
    except subprocess.SubprocessError as e:
        return False, str(e)[:300] or type(e).__name__
    in_head = [p for p in _git(folder, "ls-tree", "--name-only", "-z", head, "--", *held).stdout.split("\0") if p] \
        if head else []
    if not in_head:
        return False, None
    new, refused = "", "a pin time git holds could not be taken out of it"
    with tempfile.TemporaryDirectory(prefix="sheaf-untrack-", ignore_cleanup_errors=True) as own:
        index = Path(own) / "index"
        try:
            steps = [("read-tree", head), ("update-index", "--force-remove", "--", *in_head)]
            if any(_git(folder, *step, index=index).returncode for step in steps):
                return False, refused
            tree = _git(folder, "write-tree", index=index).stdout.strip()
            made = _git(folder, "-c", f"user.name={COMMITTER[0]}", "-c", f"user.email={COMMITTER[1]}", "commit-tree",
                        tree, "-p", head, "-m", "versions: pin times out of git", author=Author(*COMMITTER))
            new = made.stdout.strip()
            if made.returncode or not new or _git(folder, "update-ref", "HEAD", new, head).returncode:
                return False, refused
        except subprocess.SubprocessError as e:
            moved = bool(new) and _git(folder, "rev-parse", "-q", "--verify", "HEAD").stdout.strip() == new
            return moved, None if moved else (str(e)[:300] or type(e).__name__)
    return True, None


def _pin_times_out_of_index(folder: Path, paths: list) -> bool:
    """Whatever `add` staged of `paths`, no pin time (`state.is_pin_time`) stays staged: a `.gitignore` may be missing, a
    link, or undone by a `!*.at` lower down, and a pin time is each hub's own (7.4, ticket 203). False: git refused."""
    staged = [p for p in _git(folder, "ls-files", "-z", "--", *paths).stdout.split("\0") if state.is_pin_time(p)]
    return not staged or _locking(folder, "update-index", "--force-remove", "--", *staged).returncode == 0


def root_config(root) -> "config.RootConfig":
    """The settings a root's writes are committed by: its `.sheaf.toml`'s, except for a clone the tiroir serves, which
    always commits and pushes whatever the repo's file says (SPEC 8.11): that file describes a root on a laptop."""
    if getattr(root, "clone", ""):
        return config.RootConfig(commit=True, push=True)
    return config.load_root_config(root.path, warn=lambda line: None)


class Commits:
    def __init__(self, record, guard=None, roots=None, refuse_rewrite=False, pulling=None, pulled=None, renamed=None):
        """`record(kind, doc, **detail)` writes a diagnostics row (15). `guard(root, files)` gives a context that
        holds what a writer of each of `files` (absolute paths) holds before the repo's lock (9.11): a pull takes
        it before it changes them. `roots()` gives the registered roots: the repo of one pushes only when its other
        roots that commit push too (#89), judged by the pusher when it takes the repo. `refuse_rewrite`, a bool or a
        function that gives one: whether a pull refuses a remote branch that no longer holds the tip the hub last
        saw there (a force-push), kept in the repo's own ref `refs/sheaf/last-seen/<branch>`; off, no ref is read
        or written and a pull is as it was. `pulling(folder, [(path, author)])` hears of the files a pull is about to
        change and who last wrote each, before the work tree moves; `pulled(folder, files, ok)` hears it end, `ok` false
        when the pull was refused or failed: the Write log's line of it. `renamed(folder, [(old, new)])` hears of the pages
        a pull that went through renamed (absolute paths, git's own rename detection), after the repo's lock is let go and `pulled` was told: it
        takes the moves' lock, which comes before the repo's (9.11)."""
        self._record = record
        self._pulling = pulling or (lambda folder, files: None)
        self._pulled = pulled or (lambda folder, files, ok, left=None, named=None: None)
        self._renamed = renamed or (lambda folder, pairs: None)
        self._guard = guard or (lambda root, files: nullcontext())
        self._roots = roots or (lambda: ())
        self._refuse = refuse_rewrite if callable(refuse_rewrite) else (lambda: refuse_rewrite)
        # A repo is keyed by its git dir (`_repo`): the pull, the push and their rows are the repo's (#89).
        self._repos: dict[str, threading.Lock] = {}  # repo -> its commit lock
        self._lock = threading.Lock()
        self._due: dict[str, tuple] = {}           # repo -> (the root, the address, whether a write asked)
        self._polled: dict[Path, float] = {}       # root folder -> when the poll last looked at it
        self._fetched: dict[str, float] = {}       # repo -> when the poll last handed it to the pusher
        self._told: dict[str, tuple] = {}          # repo -> the last row a poll's pull wrote (the pusher's)
        self._swept: dict[tuple, tuple] = {}       # (repo, document) -> the last row the sweep wrote for it (#92)
        self._owed: set[str] = set()               # repos with a write's push not yet gone
        self._split: set[tuple] = set()            # the push mixes a row named this run
        self._wake = threading.Condition(self._lock)
        self._pushing = False
        self._thread: threading.Thread | None = None
        self._children = Children()               # the fetch or push running, which a stop ends (#95)

    def _repo_lock(self, folder: Path) -> threading.Lock:
        """The commit lock of the repo `folder` is in, keyed by its git dir: two roots in one repo share an index
        and a HEAD, so one lock (#73). A linked worktree has a git dir, an index and a HEAD of its own."""
        key = _repo(folder)
        with self._lock:
            return self._repos.setdefault(key, threading.Lock())

    def _pushes(self, root, repo: str, address: str) -> bool:
        """Whether `repo` may be pulled and pushed now, `root` the one that asked (#89): the registered roots of the
        repo that commit, `root` among them, all push. A push carries every commit of the repo's HEAD and a pull moves
        any of its files, so one root's `push = false` holds only when no root of its repo pushes. A mix pushes
        nothing and is a `push-settings-differ` row and a line on stderr, once per mix per hub run. A root that does
        not commit, or is no git work tree, is left out: the hub commits none of its paths. One whose settings cannot
        be read counts as one that does not push. The pusher judges when it takes the repo, so a root that stopped
        pushing while the push waited is never carried by it."""
        split = {True: [], False: []}
        for r in [root] + [r for r in self._roots() if r.path != root.path]:
            if not _is_git(r) or (r is not root and _repo(r.path) != repo):
                continue
            try:
                rc = root_config(r)
            except (config.ConfigError, OSError):
                split[False].append(r.name)
                continue
            if rc.commit:
                split[bool(rc.push)].append(r.name)
        if not split[True]:
            return False
        if not split[False]:
            return True
        said = (repo, tuple(sorted(split[True])), tuple(sorted(split[False])))
        with self._lock:
            told = said in self._split
            self._split.add(said)
        if not told:
            self._record("push-settings-differ", address, push=list(said[1]), no_push=list(said[2]))
            print(f"sheaf: the roots {', '.join(said[1])} push and {', '.join(said[2])} do not, in one git repo: "
                  "it pushes nothing until they agree", file=sys.stderr, flush=True)
        return False

    def saved(self, root, rel: str, author: Author, what: str, gone: str | None = None, key: str | None = None):
        """`rel`, the file of a document of `root` (a roots.Root), was written by `author`: commit it when the
        root commits. `what` names the write in the subject (`edit`, `comment`). `key` is the document's own path,
        its address in the root, when that is not `rel` (a rectoverso's name, 9.11), which names its versions folder.
        `gone` is the path the file was moved from (9.11): the commit is `move: <gone> -> <rel>`, and stages the
        file's going from there with its coming here. Never raises: a commit that fails is a diagnostics row, and
        the write stands."""
        key = key or rel
        address = f"{root.name}/{key}"
        try:
            rc = root_config(root)
        except config.ConfigError as e:
            self._record("commit-failed", address, error=str(e)[:300])
            return
        if not rc.commit:
            return
        if not _is_git(root):
            self._record("commit-not-git", address)
            return
        # The file the write went to: a link inside the root is staged as the link, not what it names.
        top = os.path.realpath(root.path)
        def file(d):
            return os.path.relpath(os.path.realpath(root.path / d), top)
        paths = [file(rel)] + ([str(state.INSIDE / state.doc_key(key))] if rc.versions_inside else [])
        subject = f"move: {gone} -> {rel}" if gone else f"{what}: {rel}"
        untracked = False                               # a commit taking pin times out of git: owed a push, whatever follows
        try:
            with self._repo_lock(root.path):
                untracked, error = _untrack_pin_times(root.path) if rc.versions_inside else (False, None)
                if error:
                    self._record("commit-failed", address, error=error)
                    paths = paths[:1]                   # the document alone: its versions folder may hold a pin time
                made = self._commit(root.path, paths, author, subject, address, gone=[file(gone)] if gone else [])
                if not made and not untracked:
                    return
        except (OSError, subprocess.SubprocessError) as e:
            self._record("commit-failed", address, error=str(e)[:300])
            if not untracked:
                return
        if rc.push:
            try:
                self._push_later(_repo(root.path), root, address)
            except (OSError, subprocess.SubprocessError) as e:
                self._record("push-failed", address, error=str(e)[:300])

    def _commit(self, folder: Path, paths: list, author: Author, subject: str, address: str,
                gone: list = (), record=None) -> bool:
        """`paths`: the document's file, then its versions folder when the root keeps it; `gone`: the path its file
        moved from (a move). A path that is gone is staged as gone: git still lists it. `record`: where its rows go."""
        record = record or self._record
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
            record("commit-failed", address, error="the index holds a merge conflict on this document")
            return False
        before = _staged(folder, paths)
        head = _git(folder, "rev-parse", "-q", "--verify", "HEAD").stdout.strip()
        try:
            return self._add_and_commit(folder, paths, before, author, subject, address, record)
        except subprocess.TimeoutExpired as e:
            # A git killed on its bound left the index as far as it got (#38); `_locking` took away its lock.
            if head and _git(folder, "rev-parse", "-q", "--verify", "HEAD^").stdout.strip() == head:
                return True                           # killed once the commit moved the branch on: it is made
            kept = _restage(folder, before, paths)
            record("commit-failed", address, error=str(e)[:300] + ("" if kept else "; the index could not be put back"))
            return False

    def _add_and_commit(self, folder: Path, paths: list, before: dict, author: Author, subject: str, address: str,
                        record) -> bool:
        r = _locking(folder, "add", "-A", "--", *paths)   # a file an ignore rule names, in the folder, stays out
        if r.returncode == 0 and not _pin_times_out_of_index(folder, paths):
            r = subprocess.CompletedProcess(r.args, 1, "", "a pin time could not be kept out of the commit")
        if r.returncode != 0:
            kept = _restage(folder, before, paths)
            record("commit-failed", address,
                         error=_last_line(r) + ("" if kept else "; the index could not be put back"))
            return False
        if _git(folder, "diff", "--cached", "--quiet", "--", *paths).returncode == 0:
            # Nothing of this write is left to commit; what the person had staged there comes back.
            if not _restage(folder, before, paths):
                record("commit-failed", address, error="the index could not be put back")
            return False
        who = []
        # Either one missing and git refuses the commit (`user.useConfigOnly`, no name from the account): the
        # hub commits as itself then, never half as the repo's committer (#38).
        if any(_git(folder, "config", f"user.{k}").returncode != 0 for k in ("name", "email")):
            who = ["-c", f"user.name={COMMITTER[0]}", "-c", f"user.email={COMMITTER[1]}"]
        if not author.email:
            mail = _git(folder, "config", "user.email")
            author = Author(author.name, mail.stdout.strip() if mail.returncode == 0 else COMMITTER[1])
        r = _locking(folder, *who, "commit", "-q", "--no-verify", "-m", subject, "--", *paths, author=author)
        if r.returncode != 0:
            kept = _restage(folder, before, paths)
            record("commit-failed", address,
                         error=_last_line(r) + ("" if kept else "; the index could not be put back"))
            return False
        return True

    # ── the push ─────────────────────────────────────────────────────────────
    def poll(self, roots):
        """The watcher's tick (#75): each repo with a root that commits and pushes, once every `FETCH_SECONDS`, goes
        to the pusher with no write behind it, so what the remote got lands with no save, and a write's push that
        failed goes out; nothing else is pushed (a commit or a branch made by hand). A repo goes once however many of
        its roots push (#89). Never raises for one root."""
        now = time.monotonic()                        # not the wall clock: a clock set back would stop the poll
        for root in roots:
            if now - self._polled.get(root.path, float("-inf")) < FETCH_SECONDS:
                continue
            self._polled[root.path] = now             # before the config: a root that does not push is read once a minute too
            if not _is_git(root):
                continue
            try:
                rc = root_config(root)
                if not (rc.commit and (rc.push or rc.versions_inside)):
                    continue
                repo = _repo(root.path)
                if now - self._fetched.get(repo, float("-inf")) < FETCH_SECONDS:
                    continue                          # another root of the repo handed it on this minute
            except (config.ConfigError, OSError, subprocess.SubprocessError):
                continue                              # a save on it says so (`commit-failed`)
            self._fetched[repo] = now
            self._push_later(repo, root, root.name, wrote=False)

    def _push_later(self, repo: str, root, address: str, wrote: bool = True):
        """`repo` is due a pull and a push, asked by `root`: by a write to `address`, or by the poll."""
        with self._lock:
            was = self._due.get(repo)
            if wrote or was is None or not was[2]:   # a write's address is kept over a poll's
                self._due[repo] = (root, address, wrote or (was is not None and was[2]))
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
                repo, (root, address, wrote) = self._due.popitem()
                if wrote:
                    self._owed.add(repo)               # until a push of it goes through
                self._pushing = True
            folder = root.path
            # A write's rows are each written; the poll meets the same cause every minute, and says it once.
            record = self._record if wrote else self._once(repo)
            try:
                if self._children.ended:
                    raise Stopped("the hub is stopping")
                with self._repo_lock(folder):
                    self._sweep(root, repo)
                if not self._pushes(root, repo, address):
                    continue                           # a write's push stays owed: the poll after the roots agree takes it
                go = self._pull(root, address, record, seconds=PUSH_SECONDS if wrote else GIT_SECONDS)
                if not go:
                    continue
                # The poll pushes a write's push that failed, never what a person committed or branched by hand.
                if go is not EVEN and repo in self._owed:
                    # Not under the repo's lock: a save meanwhile commits, and the next push carries it.
                    # A save meanwhile commits past what is sent; the branch is the one pushed, not where HEAD is later.
                    guarded = self._refuse()
                    sent = on = ""
                    if guarded:
                        sent = _git(folder, "rev-parse", "HEAD").stdout.strip()
                        on = _git(folder, "symbolic-ref", "-q", "--short", "HEAD").stdout.strip()
                    lease, what = [], "HEAD"
                    if guarded and on and sent:
                        # The remote's branch must still be the tip the pull took in: one rewound since is refused.
                        # A lease also forces, so it is used only for a commit that holds that tip (a fast-forward),
                        # and pushes that commit to that branch, not whatever HEAD has become.
                        seen = _git(folder, "rev-parse", "-q", "--verify", f"{LAST_SEEN}/{on}^{{commit}}").stdout.strip()
                        if seen and _git(folder, "merge-base", "--is-ancestor", seen, sent).returncode == 0:
                            lease, what = [f"--force-with-lease=refs/heads/{on}:{seen}"], f"{sent}:refs/heads/{on}"
                    r = _git(folder, "push", "-q", *lease, "origin", what, seconds=PUSH_SECONDS,
                             children=self._children)
                    if r.returncode != 0:
                        # The commit stays; the next write's push, or the next poll, carries it.
                        record("push-failed", address, error=_last_line(r))
                        continue
                    self._last_seen(folder, on, sent)    # the remote's branch holds what was sent
                with self._lock:
                    self._owed.discard(repo)
                self._told.pop(repo, None)
            except Stopped as e:
                # Ended by the stop, or never begun: the commit stays for the next hub (#95). A poll's pull with
                # nothing owed that never began is no news.
                if e.ended or wrote or repo in self._owed:
                    record("push-stopped", address)
            except Exception as e:                     # never a dead thread: a push that never comes is a row
                record("push-failed", address, error=str(e)[:300] or type(e).__name__)
            finally:
                with self._lock:
                    self._pushing = False
                    self._wake.notify_all()

    def _once(self, repo: str):
        """A `record` that writes a row only when it differs from the last the poll wrote for `repo`: a remote
        that cannot be reached is one row, not one a minute. A pull and push that go through forget it."""
        def record(kind, doc, **detail):
            # Digits out: git's "after 3012 ms" is the same cause as "after 2987 ms".
            said = (kind, re.sub(r"\d+", "#", detail.get("error") or ""), tuple(detail.get("paths") or ()))
            if self._told.get(repo) != said:
                self._told[repo] = said
                self._record(kind, doc, **detail)
        return record

    # ── the pull before it ───────────────────────────────────────────────────
    def _pull(self, root, address: str, record=None, seconds=PUSH_SECONDS):
        """Take in what the remote's branch got that the hub's lacks (#62); whether to push: False, True, or
        `EVEN` when the hub's branch is the remote's (nothing to push). A failed fetch is a `push-failed` row, a
        remote the hub cannot take in a `push-diverged` row: nothing is pushed, and the next write's push, or the
        next poll, tries again. A branch the remote does not have yet is pushed as it is. `seconds`: the fetch's
        time; a poll's is short, so a remote that drops packets holds the one pusher, and a clean stop, no longer."""
        record = record or self._record
        folder = root.path
        branch = _git(folder, "symbolic-ref", "-q", "--short", "HEAD")
        if branch.returncode != 0:
            return True                                # a detached HEAD: the push says what it says
        guarded = self._refuse()
        # Read before the fetch, which moves `refs/remotes/origin/<branch>` too; the ref is the hub's own, so a
        # person's `git fetch` in the clone does not move it.
        name = branch.stdout.strip()
        prev = _git(folder, "rev-parse", "-q", "--verify", f"{LAST_SEEN}/{name}^{{commit}}").stdout.strip() \
            if guarded else ""
        if guarded and not prev:                       # a root registered after the start: seed from what was fetched
            prev = _git(folder, "rev-parse", "-q", "--verify", f"refs/remotes/origin/{name}^{{commit}}").stdout.strip()
            if prev:                                   # kept: the fetch moves the tracking ref, this one stays
                self._last_seen(folder, name, prev)
        r = _git(folder, "fetch", "-q", "--no-tags", "origin", f"refs/heads/{branch.stdout.strip()}",
                 seconds=seconds, children=self._children)
        if r.returncode != 0:
            if "couldn't find remote ref" in r.stderr:
                if prev:                               # the branch was there and is gone: not ours to push back
                    record("push-diverged", address, paths=[], error=REWRITTEN)
                    return False
                return True
            record("push-failed", address, error=_last_line(r))
            return False
        theirs = _git(folder, "rev-parse", "--verify", "-q", "FETCH_HEAD^{commit}").stdout.strip()
        if prev and _git(folder, "merge-base", "--is-ancestor", prev, theirs).returncode != 0:
            record("push-diverged", address, paths=[], error=REWRITTEN)
            return False                               # the ref stays, so the next pull is refused too
        base = _git(folder, "merge-base", "HEAD", theirs)
        if base.returncode != 0:
            record("push-diverged", address, paths=[], error="the remote's branch shares no history with the hub's")
            return False
        base = base.stdout.strip()
        if base == theirs:                             # nothing new on the remote
            self._last_seen(folder, name, theirs)
            return EVEN if _git(folder, "rev-parse", "HEAD").stdout.strip() == theirs else True
        top = Path(_git(folder, "rev-parse", "--show-toplevel").stdout.strip())
        listed = _git(folder, "diff", "--name-only", "--no-renames", "-z", base, theirs)
        if listed.returncode != 0:                     # no empty list: the pull would move the files under no lock (ticket 209)
            record("push-failed", address, error=_last_line(listed))
            return False
        changed = [p for p in listed.stdout.split("\0") if p]
        # The writers' locks first, the repo's last (9.11): no write of a file the remote changed comes between
        # the look at it and its new text, and no commit of any root of the repo between the hub's HEAD read and moved.
        # The Write log's window opens now and closes however the pull ends, so the page that takes the pull in is never
        # taken for a disk write, nor a later write for the pull.
        pages = [top / p for p in changed if p.endswith(".md")]
        # The save side and this list read `--no-renames`: a rename is then a delete and an add, and both paths are locked and
        # told to the Write log. Renames are looked at apart, for the Forward a moved page leaves (9.11), which is written once the
        # pull went through. The look itself comes before anything opens or moves (ticket 209): a look that fails holds the whole
        # pull, never "no rename", since a page moved without its Forward is not repaired by a later poll, whose base is then theirs.
        try:
            renames = self._renames(folder, base, theirs, top, self._children)
        except LookFailed as e:
            record("push-failed", address, error=f"the rename look: {e}")
            return False
        named = self._tell(self._pulling, address, folder, [(path, "?") for path in pages])
        go, left = False, {}
        try:
            with self._guard(root, [top / p for p in changed]), self._repo_lock(folder):
                self._sweep(root, _repo(folder))           # what a page made since the pusher's sweep, before the work tree moves
                go = self._catch_up(folder, theirs, address, record)
                if go:
                    self._last_seen(folder, name, theirs)
                left = {path: _hash_of(path) for path in pages}   # the text the pull left, before a writer's lock is let go
        finally:
            # Who last wrote each page, asked of the commit pulled, which the locks do not guard: a slow git holds up no writer.
            ok = go is not False
            authors = [(path, _author(top, theirs, path.relative_to(top).as_posix()) if ok else "?") for path in pages]
            self._tell(self._pulled, address, folder, authors, ok, left, named=named)
        if go and renames:                             # after `pulled`, so its lines for the old paths are carried with the page
            self._tell(self._renamed, address, folder, renames)
        return go

    @staticmethod
    def _renames(folder: Path, base: str, theirs: str, top: Path, children=None) -> list:
        """The pages the remote renamed between `base` and `theirs`, `[(old, new)]` as absolute paths: git's own detection
        (`-M`), `.md` files only. A file copied or changed beyond what git calls a rename is no rename. `LookFailed` when git
        ran out of time, could not start or failed (ticket 209): that is not knowing, never "no rename". It is given a push's
        time, not a commit's: rename detection over a large pull is slower than the other looks. `children`: as a fetch's, so
        a stopping hub ends it; its `Stopped` is no `SubprocessError` and goes up as the stop it is."""
        try:
            r = _git(folder, "diff", "--name-status", "-M", "--diff-filter=R", "-z", base, theirs, seconds=PUSH_SECONDS,
                     children=children)
        except (subprocess.SubprocessError, OSError) as e:
            raise LookFailed(str(e)[:300] or type(e).__name__) from e
        if r.returncode != 0:
            raise LookFailed(_last_line(r))
        out = r.stdout.split("\0")
        found, i = [], 0
        while i + 2 < len(out) and out[i].startswith("R"):
            old, new = out[i + 1], out[i + 2]
            if old.endswith(".md") and new.endswith(".md"):
                found.append((top / old, top / new))
            i += 3
        return found

    def moved(self, root, address: str, target: str, move) -> str:
        """The files of the clone `root` move to `target` (a switch of its branch) by `move()`, which returns "" when they
        did and else why not, as `_pull` moves them and in its order (the writers' locks of every file that differs, then
        the repo's, SPEC 9.11; the Write log's window around both): the page open on a file that changes is told, a save
        cannot land between `move`'s look at the tree and its checkout, and none is carried onto the new branch. The one
        path a clone's files move by besides `_pull`; a checker of the lock order (17) lists both."""
        folder = root.path
        top = Path(_git(folder, "rev-parse", "--show-toplevel").stdout.strip())
        listed = _git(folder, "diff", "--name-only", "--no-renames", "-z", "HEAD", target)
        if listed.returncode != 0:                     # no empty list: the files would move under no lock (ticket 209)
            return _last_line(listed)
        changed = [p for p in listed.stdout.split("\0") if p]
        pages = [top / p for p in changed if p.endswith(".md")]
        named = self._tell(self._pulling, address, folder, [(path, "?") for path in pages])
        why, left = "move failed", {}
        try:
            with self._guard(root, [top / p for p in changed]), self._repo_lock(folder):
                why = move()
                left = {path: _hash_of(path) for path in pages}
        finally:
            ok = why == ""
            authors = [(path, _author(top, target, path.relative_to(top).as_posix()) if ok else "?") for path in pages]
            self._tell(self._pulled, address, folder, authors, ok, left, named=named)
        return why

    def _tell(self, call, address, *args, **kwargs):
        """The Write log's hearing of a pull: its failure is a diagnostics row, never the pull's. Returns what `call`
        returned, None when it failed."""
        try:
            return call(*args, **kwargs)
        except Exception:
            self._record("write-log-failed", address)
            return None

    def seed(self, roots):
        """At hub start: for each repo of `roots` (git work trees) that has no last-seen ref for its branch yet, set it
        from `refs/remotes/origin/<branch>`, what the clone last fetched, so the first pull is guarded. A repo that never
        fetched has none and is guarded from its first pull that passes. Never raises for one root."""
        if not self._refuse():
            return
        seen = set()
        for root in roots:
            try:
                if not _is_git(root) or (repo := _repo(root.path)) in seen:
                    continue
                seen.add(repo)
                branch = _git(root.path, "symbolic-ref", "-q", "--short", "HEAD").stdout.strip()
                if branch and _git(root.path, "rev-parse", "-q", "--verify", f"{LAST_SEEN}/{branch}").returncode != 0:
                    tip = _git(root.path, "rev-parse", "-q", "--verify", f"refs/remotes/origin/{branch}^{{commit}}")
                    if tip.returncode == 0:
                        self._last_seen(root.path, branch, tip.stdout.strip())
            except (OSError, ValueError, subprocess.SubprocessError):
                continue

    def _last_seen(self, folder: Path, branch: str, rev: str):
        """Move `branch`'s last-seen ref (the branch pulled or pushed, not where HEAD is by now) to `rev`, a commit the remote's branch holds: after a pull that passed or
        a push of the hub's HEAD, never after a refused pull. A ref that cannot be written stays behind the remote,
        which a later pull still passes; the guard only loosens by being slow, never by being wrong."""
        if not self._refuse():
            return
        sha = _git(folder, "rev-parse", "-q", "--verify", f"{rev}^{{commit}}").stdout.strip()
        if branch and sha:
            _git(folder, "update-ref", f"{LAST_SEEN}/{branch}", sha)

    def _sweep(self, root, repo: str):
        """Commit what git does not hold yet of the versions stores of `repo`'s roots that commit and keep their
        versions inside (#92): one commit per document, `versions: <path>`, by the hub. A write's commit carries its
        versions folder; this takes the versions made with no write behind it (a page opened, a change from outside
        or from the remote rendered, a pin, the newest 60 pushing an old one out), so the work tree never holds an
        untracked version where the remote's may land: git refuses to write over one, even one that is the same.
        A folder whose document the repo ignores stays out, as a write's does. The caller holds the repo's lock.
        Its commits are owed a push, as a write's are. Never raises: a folder that cannot be committed is a
        `commit-failed` row, written once while its cause stays the same (its own memory, not the pull's: a pull
        that goes through says nothing of a folder), the next sweep tries again, and the pull and push go on."""
        def told(doc):
            said = []

            def record(kind, _doc, **detail):
                said.append(kind)
                cause = (kind, re.sub(r"\d+", "#", detail.get("error") or ""))
                if self._swept.get((repo, doc)) != cause:
                    self._swept[(repo, doc)] = cause
                    self._record(kind, doc, **detail)

            def done():
                if not said:
                    self._swept.pop((repo, doc), None)
            return record, done
        for r in [root] + [r for r in self._roots() if r.path != root.path]:
            if not _is_git(r) or (r is not root and _repo(r.path) != repo):
                continue
            try:
                rc = root_config(r)
            except (config.ConfigError, OSError):
                continue
            if not (rc.commit and rc.versions_inside):
                continue
            record, done = told(r.name)
            try:
                untracked, error = _untrack_pin_times(r.path)
                if untracked and rc.push:
                    with self._lock:
                        self._owed.add(repo)
                if error:
                    record("commit-failed", r.name, error=error)
                    continue
                listed = _git(r.path, "ls-files", "-z", "--others", "--modified", "--deleted", "--exclude-standard",
                              "--", str(state.INSIDE))
            except (OSError, ValueError, subprocess.SubprocessError) as e:
                record("commit-failed", r.name, error=str(e)[:300] or type(e).__name__)
                continue
            done()
            folders: dict[Path, list] = {}
            for p in map(Path, filter(None, listed.stdout.split("\0"))):
                # By name, not the folder: a version half written (`state.write_text_private`) is never staged.
                if len(p.parts) > 3 and not (p.name.startswith(".") and p.name.endswith(".tmp")) \
                        and not state.is_pin_time(p.as_posix()):    # a pin time is this hub's alone (7.4)
                    folders.setdefault(Path(*p.parts[:3]), []).append(str(p))
            for f, files in sorted(folders.items()):
                key = _address(r.path / f)
                record, done = told(f"{r.name}/{key}")
                try:
                    if key != f.name and _ignored(r.path, key):
                        continue                       # a private draft's versions stay out with it
                    made = self._commit(r.path, sorted(files), Author(*COMMITTER), f"versions: {key}",
                                        f"{r.name}/{key}", record=record)
                except (OSError, ValueError, subprocess.SubprocessError) as e:
                    record("commit-failed", f"{r.name}/{key}", error=str(e)[:300] or type(e).__name__)
                    continue
                done()
                if made and rc.push:                    # a repo that never pushes owes no push
                    with self._lock:
                        self._owed.add(repo)

    def _catch_up(self, folder: Path, theirs: str, address: str, record):
        head = _git(folder, "rev-parse", "HEAD").stdout.strip()
        if _git(folder, "rev-list", "--merges", f"{theirs}..{head}").stdout.strip():
            record("push-diverged", address, paths=[], error="the hub's unpushed commits hold a merge")
            return False
        new = theirs
        for c in _git(folder, "rev-list", "--reverse", f"{theirs}..{head}").stdout.split():
            new, conflicts = _again(folder, c, new)
            if new is None:
                record("push-diverged", address, paths=conflicts, error="the remote changed what the hub did")
                return False
        # The work tree moves for what differs between the two alone, and refuses over a change of the person's.
        r = _git(folder, "read-tree", "-m", "-u", head, new)
        if r.returncode != 0:
            record("push-diverged", address, paths=[], error=_last_line(r))
            return False
        r = _git(folder, "update-ref", "-m", "sheaf: on top of the remote's", "HEAD", new, head)
        if r.returncode != 0:
            # The files are the remote's; HEAD is not: put the index and the work tree back to it.
            _git(folder, "read-tree", "-m", "-u", new, head)
            record("push-diverged", address, paths=[], error=_last_line(r))
            return False
        return EVEN if new == theirs else True

    def stop(self) -> bool:
        """A stopping hub (8.4, #95): the pull and push due run for STOP_SECONDS; then the fetch or push still
        running gets SIGTERM, and SIGKILL END_GRACE seconds later, and no fetch or push starts again. Returns
        within STOP_SECONDS and twice END_GRACE: whether the pusher was done by then."""
        if self.settle(STOP_SECONDS):
            self._children.end(signal.SIGTERM)
            return True
        if self._children.end(signal.SIGTERM) and not self.settle(END_GRACE):
            self._children.end(signal.SIGKILL)
        return self.settle(END_GRACE)

    def settle(self, timeout: float = 30) -> bool:
        """Wait until no push is due or running; whether that came within `timeout` seconds."""
        with self._lock:
            return self._wake.wait_for(lambda: not self._due and not self._pushing and self._thread is None,
                                       timeout)
