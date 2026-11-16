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

Layout under `base`: `clones/<owner>/<name>/` the clones, `reports.json` the records, written whole and atomically.
"""
import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from contextlib import nullcontext
from pathlib import Path

from .. import config
from ..atomic import write_text_atomic
from . import proxy, visibility

REPO_RE = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}")
COMMIT_RE = re.compile(r"[0-9a-f]{7,40}")
GIT_SECONDS = 300.0
FETCH_SECONDS = 10.0        # the one fetch a report whose commit the clone lacks may cost
LOOK_SECONDS = 5.0          # a look at what the clone holds, on the request path
MAX_QUEUED = 64             # reports waiting for a repo's thread; a report past it is answered and not queued
GITHUB_HOSTS = ("github.com", "ssh.github.com", "www.github.com")

NO_CLONES = "none"
OK, PRIVATE_ROOT, NO_APP, NOT_CLONED, CLONING = "ok", "private-root", "no-app", "not-cloned", "cloning"


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


def credential(folder: Path, token) -> None:
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
        self.ssh_hostname = ssh_hostname
        self.roots = None                       # the hub's registry: a whole clone is registered there (`serve`)
        self.hold = lambda folder: nullcontext()    # the lock a git command that moves a clone's HEAD holds (the hub's repo lock)
        self._saves: dict[str, tuple] = {}      # repo -> (the branch saves go on or None, the line when none), as last decided

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
        listed = self._git(dest, "-c", "core.quotePath=false", "sparse-checkout", "list")
        if listed.returncode == 0 and any(folder == h or folder.startswith(h + "/") for h in listed.stdout.split("\n") if h):
            return False
        return self._git(dest, "sparse-checkout", "add", "--", folder, token=token).returncode == 0

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

    def switch(self, repo: str, branch: str, token: str | None) -> bool:
        """Put the clone's HEAD on `branch` (the remote's), when it is not: only when no commit of the clone is
        unpushed and its work tree has no change of its own; whether HEAD is on `branch` after."""
        dest = self.clone_dir(repo)
        now = self._git(dest, "symbolic-ref", "-q", "--short", "HEAD")
        if now.returncode == 0 and now.stdout.strip() == branch:
            return True
        with self.hold(dest):
            kept = self._git(dest, "rev-list", "--count", "HEAD", "--not", "--remotes", look=True)
            dirty = self._git(dest, "status", "--porcelain", "--untracked-files=no", look=True)
            if kept.returncode != 0 or kept.stdout.strip() != "0" or dirty.returncode != 0 or dirty.stdout.strip():
                return False
            return self._git(dest, "checkout", "-q", "-B", branch, f"origin/{branch}", token=token, seconds=120).returncode == 0

    def credential(self, repo: str):
        """Git run in the clone of `repo` by the hub's commits carries the App's token for it (`CREDENTIALS`)."""
        credential(self.clone_dir(repo), lambda: self.provider.token(repo))

    def serve(self, repo: str, token: str | None):
        """The clone is whole: decide its save branch, put HEAD on it, and register it as a root once."""
        branch, _ = self.decide(repo, token)
        self.credential(repo)
        if branch is not None:
            self.switch(repo, branch, token)
        if self.roots is None:
            return
        try:
            self.roots._add(self.clone_dir(repo).resolve(), True, name=root_name(repo), clone=repo)
        except ValueError:      # a name another root holds, or a private root: the clone is made and not served
            pass

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
        `cloning`, `private-root`, `not-cloned`, `no-app`), `commit_known`, and for `no-app` the link that adds the
        repo. `private_roots` are (member, folder) pairs. A repo that is the caller's own private root is told so;
        one that is another member's is `not-cloned` and nothing else: no clone, no record, no owner named (SPEC 9.11).
        A repo that became a private root after it was cloned keeps its clone and its records, takes no more.
        Nothing here clones or fetches: that is the repo's thread's (see the top of the file)."""
        repo, path, commit = _clean_repo(repo), _clean_path(path), _clean_commit(commit)
        roots = [who for who, root in private_roots if self._is_private_root(repo, root)]
        if member in roots:
            return {"repo": repo, "path": path, "clone": PRIVATE_ROOT, "commit_known": None}
        if roots:
            return {"repo": repo, "path": path, "clone": NOT_CLONED, "commit_known": None}
        with self._guard:
            failed = self._failed.pop(repo, None)
        if failed:
            self._enqueue(repo, (member, path, commit, declared or {}))     # this report starts the clone again
            raise Refused(failed)
        dest = self.clone_dir(repo)
        held = (dest / ".git").exists()
        if not held and repo not in self._queues:
            token = self.provider.token(repo)
            if token is None:
                return {"repo": repo, "path": path, "clone": NO_APP, "commit_known": None,
                        "install": self.provider.install_url(repo)}
        item = (member, path, commit, declared or {})
        self._enqueue(repo, item)
        if not held:
            return {"repo": repo, "path": path, "clone": CLONING, "commit_known": None}
        return {"repo": repo, "path": path, "clone": OK, "commit_known": self._on_branch(dest, commit)}

    def _enqueue(self, repo: str, item: tuple):
        with self._guard:
            queue = self._queues.get(repo)
            if queue is not None:
                if len(queue) < MAX_QUEUED and not any(q[:3] == item[:3] for q in queue):
                    queue.append(item)
                return
            self._queues[repo] = [item]
            t = threading.Thread(target=self._drain, args=(repo,), name=f"repos-{repo}", daemon=True)
            self._threads.add(t)
        t.start()

    def settle(self, seconds: float = 120.0) -> bool:
        """Wait until no repo's thread is left working; whether that came before `seconds` ran out."""
        end = time.monotonic() + seconds
        while True:
            with self._guard:
                threads = list(self._threads)
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
