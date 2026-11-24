"""
sheafmd.hub.repos — the tiroir's clones of the repos whose pages members work on (SPEC 13, 14).

A render report (repo, path, commit, and what the session declares) makes the tiroir clone the repo the first time it
hears of it: blobless (`--filter=blob:none`) and sparse (cone mode), one clone per repo per tiroir whoever reports. A
report for a page in a folder the clone does not hold widens the sparse set by that folder. The owner of a page is a
record kept here (repo + path -> member), made at the page's first report and never moved by a later one; a page's
front matter `owner` wins over it. A repo that is the private root of any member on this tiroir is never cloned and its
pages get no record: they have one home. A report for such a repo by another member is answered `not-cloned`, once and the
same whatever the tiroir holds: nothing is cloned for it, not even to throw away, and the answer names no owner. The
limit, written in the PR: a member who knows a repo's URL can tell that this tiroir will not clone it; nothing of its
pages or its owner shows.

Nothing on the request path clones or fetches. A report for a repo with no clone answers at once (`cloning`) and queues
the work: one thread per repo makes the clone (into a folder of its own, moved into place when whole), then settles each
queued report (widens the sparse set, looks for the commit, records the owner). A report for a repo that has a clone
answers from what the clone already holds (`commit_known` from the fetched branches) and queues the same work. A commit
the clone lacks costs one fetch of about 10 seconds in that thread, at most once in `FETCH_EVERY` seconds per repo, so a
stream of made-up commit ids does nothing more. A clone that failed is told to the next report once (as a refusal), and
that same report queues the clone again, so the refusal and the new attempt come together.

The credential is a seam, `provider`, with two methods: `token(repo)` is an installation token for the repo or None when
the App cannot reach it, and `install_url(repo)` is the link that adds the repo to the installation. The token reaches
git in the environment (`GIT_CONFIG_*`), never in an argument, a file or an answer. `remote_url(repo)` is where the clone
comes from (GitHub's address; a test gives a local bare repo).

Saves (SPEC 14): once a clone is whole the hub serves it as a root named `owner--name`, and its HEAD is the branch saves
go on: `dev` where the remote has it, else the branch the `branch` key of the remote's default branch's `.sheaf.toml`
names (and the remote has), else none, and the page is read-only with a line saying which `.sheaf.toml` line would
change that. The hub never guesses whether a branch deploys and never makes a branch. The clone's files move only
through `Commits._pull`; a report's fetch only looks.

A clone nobody has reported a page of for `SLEEP_DAYS` days sleeps (`sleep_idle`, run on the hub's tick): nothing fetches
it, and its sparse set is shrunk to nothing, the folders it held kept to widen again. A page of it still reads at its last
text from the commit (`page_text`), whatever the work tree holds. A report for the repo wakes it. Nothing here deletes a
clone: only the member does.

Layout under `base`: `clones/<owner>/<name>/` the clones, `reports.json` the records, `clones.json` when each clone was last
used and whether it sleeps, written whole and atomically.
"""
import base64
import contextlib
import functools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from .. import config, diagnostics
from ..atomic import write_text_atomic
from . import proxy, visibility

REPO_RE = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}")
COMMIT_RE = re.compile(r"[0-9a-f]{7,40}")
GIT_SECONDS = 300.0
FETCH_SECONDS = 10.0        # the one fetch a report whose commit the clone lacks may cost
LOOK_SECONDS = 5.0          # a look at what the clone holds, on the request path
MAX_QUEUED = 64             # reports waiting for a repo's thread; a report past it is answered and not queued
SLEEP_DAYS = 30             # a clone nobody reported a page of for this long sleeps
SLEEP_WAIT = 60.0           # how long one round of `sleep_idle` waits for the clones' threads; the rest finish behind it
GITHUB_HOSTS = ("github.com", "ssh.github.com", "www.github.com")

NO_CLONES = "none"
OK, PRIVATE_ROOT, NO_APP, NOT_CLONED, CLONING = "ok", "private-root", "no-app", "not-cloned", "cloning"
MOVED = "moved"             # the clone's root went to another tiroir: its answer carries the new origin (`moved_to`)
NO_LAZY_FETCH_FROM = (2, 44)    # the git that honours GIT_NO_LAZY_FETCH; an older one ignores it without an error


def parse_git_version(said: str) -> tuple[int, int] | None:
    """(major, minor) from the output of `git --version`, or None when it is not one."""
    m = re.match(r"git version (\d+)\.(\d+)", said)
    return (int(m[1]), int(m[2])) if m else None


RETRY_READ_EVERY = 60.0     # seconds between reads of the git version while it cannot be read


def _cache_good(read):
    """Keep what `read()` gave once it is not None. A None (a failed read) is asked again, but not sooner than
    RETRY_READ_EVERY seconds after the last try, so a git that hangs costs one read in that time and not one per request;
    the read that finally works is said on stderr when an earlier one had failed. The lock is held across the `git --version`
    read on purpose: it is bounded, and a second caller waiting for it is no defect."""
    kept, state = [], {"failed_at": None}
    lock = threading.Lock()

    @functools.wraps(read)
    def cached():
        with lock:
            if kept:
                return kept[0]
            failed_at = state["failed_at"]
            if failed_at is not None and time.monotonic() - failed_at < RETRY_READ_EVERY:
                return None
            value = read()
            if value is None:
                state["failed_at"] = time.monotonic()
                return None
            kept.append(value)
            if failed_at is not None:
                print(f"sheaf hub: git {value[0]}.{value[1]} read: commit look {'on' if value >= NO_LAZY_FETCH_FROM else 'off'}",
                      file=sys.stderr, flush=True)
            return value

    def cache_clear():
        kept.clear()
        state["failed_at"] = None

    cached.cache_clear = cache_clear
    return cached


@_cache_good
def _git_version() -> tuple[int, int] | None:
    """The git the hub runs, read once when it reads; None when it cannot be run or read (and then read again)."""
    try:
        r = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=10, env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_git_version(r.stdout) if r.returncode == 0 else None


class Refused(ValueError):
    """A report that names something no repo, path or commit is: one sentence, handed back to the caller."""


def _clean_repo(repo) -> str:
    """The repo in lower case: GitHub names are case-insensitive, and one repo has one clone and one set of records."""
    if not isinstance(repo, str) or not REPO_RE.fullmatch(repo) or repo.startswith((".", "-")) or "/." in repo \
            or "/-" in repo:
        raise Refused(f"{repo!r} is not a repo named owner/name.")
    return repo.lower()


def _clean_path(path) -> str:
    if (not isinstance(path, str) or not path.endswith(".md") or path.startswith("/") or "\\" in path
            or "\0" in path or any(part in ("", ".", "..") for part in path.split("/"))):
        raise Refused(f"{path!r} is not a markdown page's path inside a repo.")
    return path


def _clean_commit(commit) -> str:
    if not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit):
        raise Refused(f"{commit!r} is not a commit id.")
    return commit


# Folder (real path) of a clone the tiroir serves -> a function that gives the installation token for its remote, None
# when the App cannot reach it. A git the hub runs in that folder gets the token in its environment (SPEC 14), never in
# an argument, a file or an answer; asked at each git, so a renewed token is the one used.
CREDENTIALS: dict[str, "callable"] = {}
CREDENTIALS_LOCK = threading.Lock()     # a clone's first serve adds a key from its own thread while a commit or pull looks one up


def credential(folder: Path, token) -> None:
    with CREDENTIALS_LOCK:
        CREDENTIALS[os.path.realpath(folder)] = token


def token_env(token: str) -> dict:
    """The environment that gives git the installation token for its HTTPS remote: never an argument, a file or an answer."""
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.extraHeader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}"}


def root_name(repo: str) -> str:
    """The name of the root that serves the clone of `repo`: from the repo, never from its arrival order (SPEC 14)."""
    return repo.replace("/", "--").lower()


def ssh_hostname(host: str, config: str | None = None) -> str | None:
    """The host name `ssh` would connect to for `host` (an alias of ~/.ssh/config resolves to its HostName), from
    `ssh -G`; None when ssh gives no answer."""
    argv = ["ssh", *(["-F", config] if config else []), "-G", "--", host]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    for line in r.stdout.splitlines() if r.returncode == 0 else ():
        if line.startswith("hostname "):
            return line.split(None, 1)[1].strip().casefold() or None
    return None


class Repos:
    def __init__(self, base: Path, provider, remote_url=None):
        self.base, self.provider = Path(base), provider
        self.remote_url = remote_url or (lambda repo: f"https://github.com/{repo}.git")
        self._records = threading.RLock()       # the records file, held for a read or a read-modify-write, never across git
        self._guard = threading.Lock()          # the queues below, never held across git
        self._queues: dict[str, list] = {}      # repo -> reports waiting for its thread; a repo with a key has one running
        self._threads: set = set()
        self._failed: dict[str, str] = {}       # repo -> why its last clone failed, told once to the next report
        self._fetched: dict[str, float] = {}    # repo -> when a fetch for an unknown commit last started
        self._hosts: dict[str, str | None] = {}  # ssh host -> the name ssh -G gives it
        self.FETCH_EVERY = 30.0
        self.SLEEP_WAIT = SLEEP_WAIT
        self.clock = time.time                  # the sleep of a clone counts in this clock's days; a test sets it
        self.ssh_hostname = ssh_hostname
        self.roots = None                       # the hub's registry: a whole clone is registered there (`serve`)
        # Runs `move()` as a pull moves a clone's files: `mover(root, address, target, move)` is the hub's `Commits.moved`,
        # which gives it the pages' writer locks, the repo's lock and the Write log's window (the one path files move by).
        self.mover = lambda root, address, target, move: move()
        # The commit lock of the clone at `dest` (`Commits._repo_lock`), as a context manager: a change of the sparse set moves
        # the clone's files, so it runs under the lock a save and a pull take.
        self.holding = lambda dest: contextlib.nullcontext()
        self._saves: dict[str, tuple] = {}      # repo -> (the branch saves go on or None, the line when none), as last decided
        self._why: dict[str, tuple[str, str]] = {}          # repo -> why its HEAD is not on the save branch, after a switch that did not happen
        version = _git_version()
        if version is None or version < NO_LAZY_FETCH_FROM:     # said at each Repos construction (one per hub)
            print("sheaf hub: " + ("git version unreadable" if version is None else "git below 2.44") + ": commit look off",
                  file=sys.stderr, flush=True)

    # ── the records ──────────────────────────────────────────────────────────
    @property
    def _records_file(self) -> Path:
        return self.base / "reports.json"

    def _read(self) -> dict:
        try:
            data = json.loads(self._records_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict):
        self.base.mkdir(parents=True, exist_ok=True)
        write_text_atomic(self._records_file, json.dumps(data, indent=1, sort_keys=True) + "\n")

    # ── when a clone was used, and whether it sleeps ─────────────────────────
    @property
    def _usage_file(self) -> Path:
        return self.base / "clones.json"

    def _usage(self) -> dict:
        try:
            data = json.loads(self._usage_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _use(self, repo: str):
        """A report for `repo`: the clone was used now, and a sleeping one is to wake (its folders come back in its thread)."""
        with self._records:
            data = self._usage()
            row = data.get(repo) if isinstance(data.get(repo), dict) else {}
            data[repo] = {**row, "last_used": self.clock(), "sleeping": False}
            self.base.mkdir(parents=True, exist_ok=True)
            write_text_atomic(self._usage_file, json.dumps(data, indent=1, sort_keys=True) + "\n")

    def sleeping(self, repo: str) -> bool:
        with self._records:
            row = self._usage().get(repo)
        return isinstance(row, dict) and row.get("sleeping") is True

    def moved_to(self, repo: str) -> str | None:
        """The origin the root of `repo` moved to, or None when it did not move."""
        with self._records:
            row = self._usage().get(repo)
        to = row.get("moved") if isinstance(row, dict) else None
        return to if isinstance(to, str) and to else None

    def sleep_moved(self, repo: str, to: str) -> bool:
        """The root of `repo` moved to the tiroir `to`: its clone sleeps now, whatever its last use, and a report for it is
        answered `moved` without waking it. A clone already asleep keeps what it will restore. False for a repo with no
        clone, and for one a report is being settled on (the caller asks again); True once it sleeps as moved."""
        dest = self.clone_dir(repo)
        if not (dest / ".git").exists():
            return False
        with self._records:
            data = self._usage()
            row = data.get(repo) if isinstance(data.get(repo), dict) else {}
            if row.get("sleeping") is True:
                if row.get("moved") != to:
                    data[repo] = {**row, "moved": to}
                    write_text_atomic(self._usage_file, json.dumps(data, indent=1, sort_keys=True) + "\n")
                return True
        with self._guard:
            if repo in self._queues:
                return False                    # a report is being settled: the caller asks again
            self._queues[repo] = []
            t = self._start(repo, self._sleep_one, repo, dest, [], to)   # under the guard: a settle() that sees the thread in `_threads` finds it started
        t.join(self.SLEEP_WAIT)
        if t.is_alive():
            diagnostics.record("hub", "clone-sleep-slow", repo=repo)
        return self.moved_to(repo) == to

    def unmove(self, repo: str) -> bool:
        """The root of `repo` came back: a report for it is answered as for any clone, and the first one wakes it (its folders
        come back in its thread). False for a repo that did not move."""
        with self._records:
            data = self._usage()
            row = data.get(repo)
            if not isinstance(row, dict) or "moved" not in row:
                return False
            data[repo] = {k: v for k, v in row.items() if k != "moved"}
            write_text_atomic(self._usage_file, json.dumps(data, indent=1, sort_keys=True) + "\n")
        return True

    def sleep_idle(self) -> list:
        """Put to sleep each clone not used for `SLEEP_DAYS` days: its sparse set is shrunk to nothing and kept to be widened
        again. A clone with no record is first dated now. The repos put to sleep. The git calls run in the repo's own thread,
        which a clone with a report waiting or being settled already has: that one is not put to sleep under it."""
        now, slept, claimed = self.clock(), [], []
        for git_dir in sorted((self.base / "clones").glob("*/*/.git")):
            dest = git_dir.parent
            repo = f"{dest.parent.name}/{dest.name}"
            with self._records:
                data = self._usage()
                row = data.get(repo) if isinstance(data.get(repo), dict) else None
                if row is None or not isinstance(row.get("last_used"), (int, float)):
                    data[repo] = {"last_used": now, "sleeping": False}
                    write_text_atomic(self._usage_file, json.dumps(data, indent=1, sort_keys=True) + "\n")
                    continue
                if row.get("sleeping") or now - row["last_used"] <= SLEEP_DAYS * 86400:
                    continue
            with self._guard:
                if repo in self._queues:
                    continue                    # a report is being settled: not asleep under it
                self._queues[repo] = []         # this repo's thread is the one below; a report that comes waits in its queue
                t = self._start(repo, self._sleep_one, repo, dest, slept)   # under the guard, as in sleep()
            claimed.append((repo, t))
        end = time.monotonic() + self.SLEEP_WAIT
        for repo, t in claimed:
            t.join(max(0.0, end - time.monotonic()))
            if t.is_alive():                    # left to finish in its thread: the next round skips the repo while it works
                diagnostics.record("hub", "clone-sleep-slow", repo=repo)
        return list(slept)

    def _sleep_one(self, repo: str, dest: Path, slept: list, moved: str | None = None):
        """The repo's thread, for one clone going to sleep (for good, as moved to the tiroir `moved`, when that is given);
        then it settles whatever reports came meanwhile (its `_wake` widens the set again, a moved clone's does not), like
        any thread of the repo."""
        try:
            # The shrink and the record of what to restore are one step under the clone's lock: a write that takes the lock
            # after it finds `restore` and widens, and one before it is dated by `_use`, which the check below reads.
            with self.holding(dest):
                with self._records:
                    row = self._usage().get(repo)
                row = row if isinstance(row, dict) else {}
                # A write or a report since the check (`_use`) has dated the clone anew: it is no longer idle, and its folders
                # stay where they are, so the write that dated it finds its file.
                idle = moved is not None or self.clock() - row.get("last_used", 0) > SLEEP_DAYS * 86400
                if not idle and row.get("sleeping") is not True:
                    return
                listed = self._git(dest, "-c", "core.quotePath=false", "sparse-checkout", "list")
                shrunk = listed.returncode == 0 and self._git(dest, "sparse-checkout", "set", "--cone").returncode == 0
                if shrunk:
                    with self._records:
                        data = self._usage()
                        row = data.get(repo) if isinstance(data.get(repo), dict) else {}
                        # A report that came during the shrink dates the clone anew (it takes no lock): it stays awake and
                        # the thread's drain widens the set again.
                        idle = moved is not None or self.clock() - row.get("last_used", 0) > SLEEP_DAYS * 86400
                        # A clone already shrunk lists the shrunk set: the folders it is to get back stay, and one a report
                        # widened since (a failed wake leaves them out) joins them.
                        kept = list(row.get("restore") or [])
                        data[repo] = {**row, "sleeping": idle or row.get("sleeping") is True,
                                      "restore": kept + [f for f in listed.stdout.split("\n") if f and f not in kept]}
                        if moved is not None:
                            data[repo]["moved"] = moved
                        write_text_atomic(self._usage_file, json.dumps(data, indent=1, sort_keys=True) + "\n")
                else:
                    idle = False
            if idle:
                slept.append(repo)
        finally:
            self._drain(repo)

    def _wake(self, repo: str, dest: Path, token: str | None):
        """The folders a sleeping clone held come back into its sparse set, once, in the thread of the report that woke it."""
        with self.holding(dest):
            self._restore(repo, dest, token)

    def _restore(self, repo: str, dest: Path, token: str | None) -> bool:
        """The folders `restore` names come back, under the clone's lock (the caller's); False when they are to come back and
        did not (the record is kept, so the next try is made). True when nothing is left to restore."""
        with self._records:
            row = self._usage().get(repo)
        folders = row.get("restore") if isinstance(row, dict) else None
        if not folders or row.get("moved"):
            return True
        woken = self._git(dest, "sparse-checkout", "set", "--cone", "--", *folders, token=token).returncode == 0
        if woken:
            with self._records:
                data = self._usage()
                data[repo] = {k: v for k, v in data.get(repo, {}).items() if k != "restore"}
                write_text_atomic(self._usage_file, json.dumps(data, indent=1, sort_keys=True) + "\n")
        return woken

    def wake(self, repo: str) -> bool:
        """A write is about to go to a page of `repo`: the folders of a clone that sleeps, or that went to sleep while a write
        was dating it, come back before the write looks for its file. A write is a use of the clone. Decided from `restore`
        (the folders still out), not from the flag, and under the clone's lock, which a clone going to sleep holds: no
        shrink lands between the check and the widen. False for a clone that moved to another tiroir (it never wakes) or
        whose folders did not come back."""
        if self.moved_to(repo) is not None:
            return False
        dest = self.clone_dir(repo)
        if not (dest / ".git").exists():
            return False
        with self.holding(dest):
            if self.moved_to(repo) is not None:     # a move that landed since the check above: the clone never wakes
                return False
            with self._records:
                row = self._usage().get(repo)
            self._use(repo)
            if not (isinstance(row, dict) and (row.get("sleeping") is True or row.get("restore"))):
                return True                         # nothing is out: no token is asked for
            token = self.provider.token(repo)
            return self._restore(repo, dest, token)

    def page_text(self, repo: str, path: str, commit: str) -> str | None:
        """The text of the page `path` at `commit`, read from git and not from the work tree, so a sleeping clone's pages open
        at their last text. Nothing is fetched: None for a page the clone does not hold."""
        r = self._git(self.clone_dir(repo), "show", f"{_clean_commit(commit)}:{_clean_path(path)}", look=True, seconds=LOOK_SECONDS)
        return r.stdout if r.returncode == 0 else None

    def root_toml(self, repo: str, commit: str) -> str | None:
        """The text of the root's `.sheaf.toml` at `commit`, read from git as `page_text` reads a page (nothing is fetched); None
        when the clone does not hold it. `page_text` takes markdown pages' paths only, so the root file has its own door."""
        r = self._git(self.clone_dir(_clean_repo(repo)), "show", f"{_clean_commit(commit)}:.sheaf.toml", look=True, seconds=LOOK_SECONDS)
        return r.stdout if r.returncode == 0 else None

    def clone_dir(self, repo: str) -> Path:
        owner, name = repo.split("/")
        return self.base / "clones" / owner / name

    def owner_of(self, repo: str, path: str) -> str | None:
        """The member of a repo page: the `owner` of its front matter at the commit of the latest report when it names
        one, else the one the first report recorded; None for a page no report made."""
        with self._records:
            row = self._read().get(repo, {}).get(path)
        if not isinstance(row, dict):
            return None
        return row["named"] if isinstance(row.get("named"), str) and row["named"] else row["owner"]

    def attribution(self, repo: str, path: str) -> dict:
        """What a row says of the page's last writer: the session of the latest report, else the `Sheaf-Session:` and
        `Sheaf-Host:` trailers of the page's last commit, else `git · <author>`."""
        with self._records:
            row = self._read().get(repo, {}).get(path) or {}
        if row.get("session"):
            return {"session": row["session"], "host": row.get("host"), "link": row.get("link"),
                    "label": f"session {row['session']}"}
        r = self._git(self.clone_dir(repo), "log", "-1", "--format=%an%x00%(trailers:key=Sheaf-Session,valueonly,"
                      "separator=%x01)%x00%(trailers:key=Sheaf-Host,valueonly,separator=%x01)", "--", path)
        author, session, host = (r.stdout.rstrip("\n").split("\x00") + ["", "", ""])[:3] if r.returncode == 0 else ("",) * 3
        session, host = (v.split("\x01")[0].strip() for v in (session, host))
        if session:
            return {"session": session, "host": host or None, "link": None, "label": f"session {session}"}
        return {"session": None, "host": None, "link": None, "label": f"git · {author}" if author else "git"}

    def land_record(self, repo: str, path: str, owner: str, commit: str, record: dict) -> dict | None:
        """Write the row of a page that landed from another tiroir, as `_settle` writes one (`owner`, `commit`, and the
        `session`, `host`, `link` of `record` that are set; never its `named`, which only a report reads, from the page's own front matter; the `named` a report read at this same commit is kept). Returns the row it replaced, or None, for `drop_record`."""
        repo = _clean_repo(repo)        # the key a report writes under
        with self._records:
            data = self._read()
            prior = data.get(repo, {}).get(path)
            named = prior.get("named") if isinstance(prior, dict) and prior.get("commit") == commit else None    # read by a report from this commit's own front matter
            data.setdefault(repo, {})[path] = {
                "owner": owner, "commit": commit, **({"named": named} if isinstance(named, str) and named else {}),
                **{k: v for k, v in record.items() if k in ("session", "host", "link") and v}}
            self._write(data)
        return prior if isinstance(prior, dict) else None

    def drop_record(self, repo: str, path: str, prior: dict | None):
        """Undo `land_record`: put back the row it returned, or take the page's row away when there was none."""
        repo = _clean_repo(repo)
        with self._records:
            data = self._read()
            if prior is None:
                data.get(repo, {}).pop(path, None)
                if repo in data and not data[repo]:
                    del data[repo]
            else:
                data.setdefault(repo, {})[path] = prior
            self._write(data)

    # ── git ──────────────────────────────────────────────────────────────────
    def _git(self, at, *args, token: str | None = None, seconds: float = GIT_SECONDS, look: bool = False):
        env = {**os.environ, "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0"}
        if look:
            env["GIT_NO_LAZY_FETCH"] = "1"      # a blobless clone fetches a missing object from its remote unasked (git 2.44)
        if token:
            env.update(token_env(token))
        argv = ["git", "-c", "core.hooksPath=/dev/null", "--literal-pathspecs"]
        if at is not None:
            argv += ["-C", str(at)]
        try:
            return subprocess.run([*argv, *args], capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=seconds, env=env, start_new_session=True)
        except (OSError, subprocess.SubprocessError) as e:
            return subprocess.CompletedProcess(args, 124, "", str(e))

    def _is_private_root(self, repo: str, folder: str) -> bool:
        """Whether `repo` is the repo of the private root `folder`: any remote of the root, fetch or push, names it.
        Decided from the configured root: one that cannot be looked at (missing, no `.git` of its own, unreadable, git
        gives no answer) counts as one, since git would read a parent folder's repo for it and a clone cannot be
        taken back. A remote on a host that cannot be told from GitHub is the repo's when its path is."""
        if not os.path.lexists(os.path.join(folder, ".git")):
            return True
        try:
            places = proxy.repo_places(folder)
        except proxy.ProxyError:
            return True
        if places is None or proxy.normal_place(self.remote_url(repo)) in places:
            return True
        return any(self._names_repo(place, repo) for place in places)

    def _names_repo(self, place: str, repo: str) -> bool:
        """Whether a root's remote (`host/owner/name`, as the proxy spells it) is `repo` on GitHub, however it is
        reached: `ssh.github.com`, an ssh alias (resolved with `ssh -G`), or a host nothing can tell from GitHub."""
        host, _, path = place.partition("/")
        if place.startswith("/") or not host or path.casefold() != repo:
            return False
        if host in GITHUB_HOSTS:
            return True
        if host not in self._hosts:
            self._hosts[host] = self.ssh_hostname(host)
        named = self._hosts[host]
        if named is None or "." not in named:
            return True                   # no answer, or a name that is no domain: fail closed
        return named in GITHUB_HOSTS

    def _clone(self, repo: str, token: str, folder: str, dest: Path) -> str | None:
        """Clone `repo` into `dest` blobless and sparse with `folder` in its set; an error sentence, or None when made."""
        r = self._git(None, "clone", "-q", "--filter=blob:none", "--sparse", "--no-tags", "--", self.remote_url(repo),
                      str(dest), token=token)
        if r.returncode != 0:
            return f"the clone of {repo} failed: {r.stderr.strip()[-300:] or 'git gave no reason'}"
        r = self._git(dest, "sparse-checkout", "set", "--cone", "--", *([folder] if folder else []), token=token)
        if r.returncode != 0:
            shutil.rmtree(dest, ignore_errors=True)         # a clone without its sparse set is none: the next report makes it again
            return f"the sparse set of {repo} could not be made: {r.stderr.strip()[-300:]}"
        return None

    def _widen(self, dest: Path, folder: str, token: str | None) -> bool:
        """Add `folder` to the sparse set when it is not in it; whether it was added."""
        if not folder:
            return False
        with self.holding(dest):
            listed = self._git(dest, "-c", "core.quotePath=false", "sparse-checkout", "list")
            if listed.returncode == 0 and any(folder == h or folder.startswith(h + "/") for h in listed.stdout.split("\n") if h):
                return False
            return self._git(dest, "sparse-checkout", "add", "--", folder, token=token).returncode == 0

    @staticmethod
    def _look_is_safe() -> bool:
        """Whether a look at the clone on the request path cannot fetch: a git before 2.44 (or one that cannot be read)
        ignores GIT_NO_LAZY_FETCH, so there the look is not made and the answer is that of a look that found nothing.
        The repo's own thread, which may fetch, keeps its looks."""
        version = _git_version()
        return version is not None and version >= NO_LAZY_FETCH_FROM

    def _on_branch(self, dest: Path, commit: str, seconds: float = LOOK_SECONDS) -> bool:
        """Whether a remote-tracking branch the clone holds contains `commit`: a look at the clone, no network."""
        r = self._git(dest, "branch", "-r", "--contains", commit, seconds=seconds, look=True)
        return r.returncode == 0 and bool(r.stdout.strip())

    def _knows(self, dest: Path, repo: str, commit: str, token: str | None) -> bool:
        """Whether a branch of the remote holds `commit`. A commit the clone lacks costs one fetch of `FETCH_SECONDS`,
        at most once in `FETCH_EVERY` seconds per repo. The fetch only looks: the clone's files move through
        `Commits._pull`, under the pages' locks."""
        if self._on_branch(dest, commit, 30):
            return True
        if self.sleeping(repo):
            return False                        # a clone that sleeps fetches nothing
        now = time.monotonic()
        with self._guard:
            last = self._fetched.get(repo)
            if last is not None and now - last < self.FETCH_EVERY:
                return False
            self._fetched[repo] = now
        if self._git(dest, "fetch", "-q", "--no-tags", "origin", token=token, seconds=FETCH_SECONDS).returncode != 0:
            return False
        return self._on_branch(dest, commit, 30)

    # ── the save branch ──────────────────────────────────────────────────────
    def _has_branch(self, dest: Path, name: str) -> bool:
        return self._git(dest, "rev-parse", "-q", "--verify", f"refs/remotes/origin/{name}^{{commit}}",
                         look=True).returncode == 0

    def decide(self, repo: str, token: str | None = None) -> tuple:
        """(the branch saves go on, or None; the line that says why not, or "") from the clone as it is now, and
        remembered. `dev` where the remote has it, else the `branch` of the `.sheaf.toml` the remote's default branch
        holds when the remote has that branch; nothing else is ever a save branch."""
        dest = self.clone_dir(repo)
        if self._has_branch(dest, "dev"):
            got = ("dev", "")
        else:
            default = self._git(dest, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD", look=True)
            default = default.stdout.strip().removeprefix("origin/") if default.returncode == 0 else ""
            shown = self._git(dest, "show", "origin/HEAD:.sheaf.toml", token=token, seconds=60, look=token is None)
            named = config.branch_named(shown.stdout) if shown.returncode == 0 else None
            on = f" on {default}" if default else ""
            if named is None:
                got = (None, f'To edit this page here, add branch = "<a branch that does not deploy>" to .sheaf.toml{on} of {repo}.')
            elif not self._has_branch(dest, named):
                got = (None, f".sheaf.toml names the branch {named}, which {repo} does not have.")
            else:
                got = (named, "")
        with self._guard:
            self._saves[repo] = got
        return got

    def saves_on(self, repo: str) -> tuple:
        """What `decide` last found for `repo`; decided from the clone itself (no network) for a repo it has not been
        asked of since the hub started."""
        with self._guard:
            known = self._saves.get(repo)
        if known is not None:
            return known
        return self.decide(repo) if (self.clone_dir(repo) / ".git").exists() else (None, "")

    def head_of(self, repo: str) -> str | None:
        """The branch the clone's HEAD is on, read from the clone's own file; None when it is on no branch."""
        try:
            head = (self.clone_dir(repo) / ".git" / "HEAD").read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return head.removeprefix("ref: refs/heads/") if head.startswith("ref: refs/heads/") else None

    def read_only_line(self, repo: str, waking: bool = False) -> str:
        """Why the pages of the clone of `repo` may not be written, "" when they may. `waking`: the reader's write wakes the
        clone, so its sleep is not a reason (a move is). A page is writable only when the
        clone's HEAD is on the branch saves go on: what a save commits and pushes is HEAD's branch, whatever was decided."""
        if (to := self.moved_to(repo)) is not None:       # first: a moved clone sleeps too, and no report wakes it
            return f"The repo {repo} moved to {to}: its pages are saved there, not here."
        if self.sleeping(repo) and not waking:
            return (f"The clone of {repo} is asleep: nobody reported a page of it for {SLEEP_DAYS} days and its folders are "
                    "out of the work tree; it wakes at the next render report, or at a write by the page's owner.")
        branch, line = self.saves_on(repo)
        if branch is None:
            return line
        on = self.head_of(repo)
        if on == branch:
            return ""
        return self._why_of(repo, branch) or (f"The clone of {repo} is on {on or 'no branch'}, not on {branch}, where its pages "
                                        f"are saved; it moves at the next render report.")

    def _why_of(self, repo: str, branch: str) -> str:
        """The reason the last switch to `branch` did not happen; none for a reason given for another branch."""
        with self._guard:
            got = self._why.get(repo)
        return got[1] if got and got[0] == branch else ""

    def switch(self, repo: str, branch: str, token: str | None) -> str:
        """Put the clone's HEAD on `branch` (the remote's), when it is not: only when no commit of the clone is
        unpushed and its work tree has no change of its own. "" when HEAD is on `branch` after, else why it is not (the
        line the page shows). The move is a pull's: under the pages' writer locks and the repo's lock, in the Write log's
        window (`mover`), so no save comes between the check and the checkout and none is carried onto the new branch."""
        dest = self.clone_dir(repo)
        if self.head_of(repo) == branch:
            return ""
        now = self.head_of(repo) or "no branch"

        def move() -> str:
            kept = self._git(dest, "rev-list", "--count", "HEAD", "--not", "--remotes", look=True)
            dirty = self._git(dest, "status", "--porcelain", "--untracked-files=no", look=True)
            if kept.returncode != 0 or dirty.returncode != 0:
                return f"The clone of {repo} could not be looked at, so it stays on {now} until the next render report."
            if kept.stdout.strip() != "0":
                return f"The clone of {repo} has a save that is not pushed yet, so it stays on {now} until it is."
            if dirty.stdout.strip():
                return f"The clone of {repo} has a change of its own, so it stays on {now} until that is gone."
            r = self._git(dest, "checkout", "-q", "-B", branch, f"origin/{branch}", token=token, seconds=120)
            return "" if r.returncode == 0 else (f"The clone of {repo} could not be moved to {branch}, so it stays on "
                                                  f"{now}; it is tried again at the next render report.")
        root = self.roots.get(root_name(repo)) if self.roots is not None else None
        why = self.mover(root, root_name(repo), f"origin/{branch}", move) if root is not None else move()
        with self._guard:
            if why:
                self._why[repo] = (branch, why)
            else:
                self._why.pop(repo, None)
        return why

    def credential(self, repo: str):
        """Git run in the clone of `repo` by the hub's commits carries the App's token for it (`CREDENTIALS`)."""
        credential(self.clone_dir(repo), lambda: self.provider.token(repo))

    def serve(self, repo: str, token: str | None):
        """The clone is whole: decide its save branch, register it as a root once, then put HEAD on the branch. The page
        is read-only until HEAD is there (`read_only_line`), so what is served meanwhile cannot be saved onto another branch."""
        branch, _ = self.decide(repo, token)
        self.credential(repo)
        if self.roots is not None:
            try:
                self.roots._add(self.clone_dir(repo).resolve(), True, name=root_name(repo), clone=repo)
            except ValueError:      # a name another root holds, or a private root: the clone is made and not served
                return
        if branch is not None:
            self.switch(repo, branch, token)

    def _holds(self, dest: Path, commit: str, path: str) -> bool:
        """Whether the page is in the tree of `commit`: no record is made for a page that is not there."""
        r = self._git(dest, "ls-tree", "-z", "--name-only", commit, "--", path, seconds=30)      # -z: git quotes a non-ASCII path otherwise
        return r.returncode == 0 and r.stdout == path + "\0"

    def _named_owner(self, dest: Path, commit: str, path: str, token: str | None) -> tuple[bool, str | None]:
        """(whether git could read the page at `commit`, the `owner` of its front matter there); git fetches the blob
        when the clone lacks it. A page it could not read says nothing of its owner."""
        r = self._git(dest, "show", f"{commit}:{path}", token=token, seconds=60)
        if r.returncode != 0:
            return False, None
        named = visibility.front_matter(r.stdout).get("owner") if r.stdout else None
        return True, named if isinstance(named, str) and named else None

    # ── the report ───────────────────────────────────────────────────────────
    def report(self, member: str, repo, path, commit, private_roots=(), declared=None) -> dict:
        """The tiroir hears that `member` works on the page `path` of `repo` at `commit`. Raises `Refused` for a name
        that is none, and for a clone that failed since the last report; otherwise the answer: `clone` (`ok`,
        `cloning`, `private-root`, `not-cloned`, `no-app`, `moved`), `commit_known`, for `no-app` the link that adds the
        repo, and for `moved` the origin the root went to (`moved_to`): that answer comes first, wakes nothing and records
        nothing. `private_roots` are (member, folder) pairs. A repo that is the caller's own private root is told so;
        one that is another member's is `not-cloned` and nothing else: no clone, no record, no owner named (SPEC 9.11).
        A repo that became a private root after it was cloned keeps its clone and its records, takes no more.
        Nothing here clones or fetches: that is the repo's thread's (see the top of the file)."""
        repo, path, commit = _clean_repo(repo), _clean_path(path), _clean_commit(commit)
        if (private := self._private(member, repo, private_roots)) is not None:
            return {"repo": repo, "path": path, "clone": private, "commit_known": None}
        if (to := self.moved_to(repo)) is not None:
            return {"repo": repo, "path": path, "clone": MOVED, "moved_to": to, "commit_known": None}
        with self._guard:
            failed = self._failed.pop(repo, None)
        if failed:
            self._enqueue(repo, (member, path, commit, declared or {}))     # this report starts the clone again
            raise Refused(failed)
        dest = self.clone_dir(repo)
        held = (dest / ".git").exists()
        if not held and not self._queued(repo):
            token = self.provider.token(repo)
            if token is None:
                return {"repo": repo, "path": path, "clone": NO_APP, "commit_known": None,
                        "install": self.provider.install_url(repo)}
        item = (member, path, commit, declared or {})
        self._use(repo)
        self._enqueue(repo, item)
        if not held:
            return {"repo": repo, "path": path, "clone": CLONING, "commit_known": None}
        return {"repo": repo, "path": path, "clone": OK, "commit_known": self._look_is_safe() and self._on_branch(dest, commit)}

    def report_rest(self, repo: str, commit: str, owned, private_roots=()) -> dict:
        """The reports of the rest of a root's owned pages, after `report` of the first told the clone is held: each `(member,
        path)` of `owned` is queued for its member at `commit`, as `report` queues one, but all of them, whatever `MAX_QUEUED` says
        (a root has up to thousands of pages, and a page left out keeps no row of its owner), and with one look at the clone
        and one date of use for the lot. Returns `{path: answer}` for each page a member may not have (`private-root`,
        `not-cloned`); those are not queued. Raises `Refused` for a name that is none."""
        repo, commit = _clean_repo(repo), _clean_commit(commit)
        refused, items = {}, []
        with self._records:
            rows = self._read().get(repo, {})
        for member, path in owned:
            if (private := self._private(member, repo, private_roots)) is not None:
                refused[_clean_path(path)] = private
            elif not (isinstance(row := rows.get(_clean_path(path)), dict) and row.get("commit") == commit):
                # a page whose row is at this commit already was settled by an earlier try of the same check: asked again, a big root
                # would redo every page each time and never get past the wait
                items.append((member, _clean_path(path), commit, {}))
        if items:
            self._use(repo)
            self._enqueue(repo, *items, cap=False)
        return refused

    def _private(self, member: str, repo: str, private_roots) -> str | None:
        """`private-root` for the member whose private root `repo` is, `not-cloned` when it is another member's, else None."""
        roots = [who for who, root in private_roots if self._is_private_root(repo, root)]
        return PRIVATE_ROOT if member in roots else NOT_CLONED if roots else None

    def install_url(self, repo: str) -> str:
        """The link that adds `repo` to the App."""
        return self.provider.install_url(_clean_repo(repo))

    def refusal(self, member: str, repo, private_roots=()) -> str | None:
        """What `report` would refuse for `repo`, with nothing written: `private-root`, `not-cloned` or `no-app`; None when it
        would not refuse. A clone that failed before is not looked at: the report that follows raises it, once, and starts the
        clone again. Nothing here records, dates, queues or pops anything."""
        repo = _clean_repo(repo)
        if (private := self._private(member, repo, private_roots)) is not None:
            return private
        if not (self.clone_dir(repo) / ".git").exists() and not self._queued(repo) and self.provider.token(repo) is None:
            return NO_APP
        return None

    def _queued(self, repo: str) -> bool:
        """Whether `repo` has a thread working (a queue): the membership test only, under the guard, never across a call to the provider."""
        with self._guard:
            return repo in self._queues

    def _enqueue(self, repo: str, *items: tuple, cap: bool = True):
        """Queue the reports `items` for the repo's thread, which is started when there is none. A report whose member, path and
        commit are queued already is not queued twice; past `MAX_QUEUED` a report is dropped, unless `cap` is False."""
        with self._guard:
            queue = self._queues.get(repo)
            if queue is not None:
                queued = {q[:3] for q in queue}
                for item in items:
                    if (not cap or len(queue) < MAX_QUEUED) and item[:3] not in queued:
                        queue.append(item)
                        queued.add(item[:3])
                return
            self._queues[repo] = list(items)
            self._start(repo, self._drain, repo)           # under the guard, as in sleep()

    def _start(self, repo: str, target, *args) -> threading.Thread:
        """The thread of `repo`, started with its queue (`_queues[repo]`) already made, under the guard. A start that fails
        leaves neither the thread in `_threads` nor the queue, which no thread would ever empty: every report of the repo
        would wait on it."""
        t = threading.Thread(target=target, args=args, name=f"repos-{repo}", daemon=True)
        self._threads.add(t)
        try:
            t.start()
        except BaseException:
            self._threads.discard(t)
            self._queues.pop(repo, None)
            raise
        return t

    def settle(self, seconds: float = 120.0, repo: str | None = None) -> bool:
        """Wait until no repo's thread is left working, or only `repo`'s when it is given (another repo's slow clone is not its
        business); whether that came before `seconds` ran out."""
        end = time.monotonic() + seconds
        name = f"repos-{_clean_repo(repo)}" if repo is not None else None
        while True:
            with self._guard:
                threads = [t for t in self._threads if name is None or t.name == name]
            if not threads:
                return True
            for t in threads:
                t.join(max(0.0, end - time.monotonic()))
            if time.monotonic() >= end:
                return False

    def _drain(self, repo: str):
        """The repo's thread: settle the queued reports until none is left; the one place a repo is cloned or fetched."""
        try:
            while True:
                with self._guard:
                    items = self._queues.get(repo)
                    if not items:
                        self._queues.pop(repo, None)
                        self._threads.discard(threading.current_thread())
                        return
                    batch, self._queues[repo] = list(items), []
                try:
                    self._settle(repo, batch)
                except Exception as e:      # a bug here must not leave the repo with a thread that never ends
                    with self._guard:
                        self._failed[repo] = f"the tiroir could not settle the report for {repo}: {type(e).__name__}"
        except BaseException:
            with self._guard:
                self._queues.pop(repo, None)
                self._threads.discard(threading.current_thread())
            raise

    def _settle(self, repo: str, batch: list):
        dest = self.clone_dir(repo)
        token = self.provider.token(repo)       # the provider renews it: asked each time git reaches the remote
        if not (dest / ".git").exists():
            if token is None:
                return
            if (failed := self._make_clone(repo, token, batch[0][1].rpartition("/")[0], dest)) is not None:
                with self._guard:
                    self._failed[repo] = failed
                    self._queues[repo] = []     # what waited for the clone waits no more: the next report asks again
                return
        self._wake(repo, dest, token)
        for member, path, commit, declared in batch:
            folder = path.rpartition("/")[0]
            if token is not None:
                self._widen(dest, folder, token)
            if not self._knows(dest, repo, commit, token) or not self._holds(dest, commit, path):
                continue
            readable, named = self._named_owner(dest, commit, path, token)
            with self._records:
                data = self._read()
                row = data.setdefault(repo, {}).get(path)
                if not readable:        # a page git could not read says nothing of its owner: keep what is known
                    named = row.get("named") if isinstance(row, dict) else None
                    if not isinstance(row, dict):
                        continue
                owner = row["owner"] if isinstance(row, dict) else member
                data[repo][path] = {"owner": owner, "commit": commit, **({"named": named} if named else {}),
                                    **{k: v for k, v in declared.items() if k in ("session", "host", "link") and v}}
                self._write(data)
        if token is not None:
            self.serve(repo, token)

    def _make_clone(self, repo: str, token: str, folder: str, dest: Path) -> str | None:
        """Clone into a folder of its own and move it into place when whole, so a report never meets half a clone. The
        folder is made in `clones/.partial/`: a GitHub owner cannot start with a dot, so no repo's clone is ever there,
        and it is on the clones' filesystem, so the move is one rename. Only the folder made here is ever removed."""
        parked = self.base / "clones" / ".partial"
        parked.mkdir(parents=True, exist_ok=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        partial = Path(tempfile.mkdtemp(prefix=repo.replace("/", "--") + "-", dir=parked))
        if (failed := self._clone(repo, token, folder, partial)) is not None:
            shutil.rmtree(partial, ignore_errors=True)
            return failed
        os.replace(partial, dest)
        return None


class CommandProvider:
    """The App's token from a command the box gives (SPEC 14): `token_command` run with the repo (`owner/name`) as its last
    word prints an installation token, or nothing when the App cannot reach the repo. With no command it is none: every
    repo is `no-app` and nothing is cloned, so a tiroir that has not been given its App clones nothing."""

    def __init__(self, token_command=(), install_url: str = ""):
        self.command, self.url = list(token_command), install_url

    def token(self, repo: str) -> str | None:
        if not self.command:
            return None
        try:
            r = subprocess.run([*self.command, repo], capture_output=True, text=True, timeout=30,
                               stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            return None
        return r.stdout.strip() or None if r.returncode == 0 else None

    def install_url(self, repo: str) -> str:
        return self.url


def from_config(t: dict) -> Repos:
    """The `Repos` a `[proxy.repos]` table (`dir`, and `token_command`, `install_url`) describes."""
    return Repos(Path(t["dir"]), CommandProvider(t.get("token_command", ()), t.get("install_url", "")))
