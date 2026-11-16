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

The credential is a seam, `provider`, with two methods: `token(repo)` is an installation token for the repo or None when
the App cannot reach it, and `install_url(repo)` is the link that adds the repo to the installation. The token reaches
git in the environment (`GIT_CONFIG_*`), never in an argument, a file or an answer. `remote_url(repo)` is where the clone
comes from (GitHub's address; a test gives a local bare repo).

Layout under `base`: `clones/<owner>/<name>/` the clones, `reports.json` the records, written whole and atomically.
"""
import base64
import json
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

from ..atomic import write_text_atomic
from . import proxy, visibility

REPO_RE = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}")
COMMIT_RE = re.compile(r"[0-9a-f]{7,40}")
GIT_SECONDS = 300.0

NO_CLONES = "none"
OK, PRIVATE_ROOT, NO_APP, NOT_CLONED = "ok", "private-root", "no-app", "not-cloned"


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


class Repos:
    def __init__(self, base: Path, provider, remote_url=None):
        self.base, self.provider = Path(base), provider
        self.remote_url = remote_url or (lambda repo: f"https://github.com/{repo}.git")
        self._records = threading.RLock()       # the records file, held for a read or a read-modify-write, never across git
        self._guard, self._repo_locks = threading.Lock(), {}

    def _repo_lock(self, repo: str) -> threading.Lock:
        """The lock of one repo's clone: a clone or fetch that stalls holds that repo's reports and no other's."""
        with self._guard:
            return self._repo_locks.setdefault(repo, threading.Lock())

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
    def _git(self, at, *args, token: str | None = None, seconds: float = GIT_SECONDS):
        env = {**os.environ, "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0"}
        if token:
            basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
            env.update({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.extraHeader",
                        "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}"})
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
        gives no answer) counts as one, since git would read a parent folder's repo for it and a clone cannot be taken
        back."""
        if not os.path.lexists(os.path.join(folder, ".git")):
            return True
        try:
            places = proxy.repo_places(folder)
        except proxy.ProxyError:
            return True
        return places is None or proxy.normal_place(self.remote_url(repo)) in places

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
        listed = self._git(dest, "sparse-checkout", "list")
        if listed.returncode == 0 and any(folder == h or folder.startswith(h + "/") for h in listed.stdout.split("\n") if h):
            return False
        return self._git(dest, "sparse-checkout", "add", "--", folder, token=token).returncode == 0

    def _knows(self, dest: Path, commit: str, token: str | None) -> bool:
        """Whether a branch of the remote holds `commit`, bringing the clone up to the remote's branch first when it does
        not (a partial clone fetches a missing commit on its own, so being able to read it proves nothing)."""
        def on_branch():       # on any branch the clone has fetched: the CLI takes a commit on any remote-tracking one
            r = self._git(dest, "branch", "-r", "--contains", commit, seconds=30)
            return r.returncode == 0 and bool(r.stdout.strip())
        if on_branch():
            return True
        self._git(dest, "pull", "-q", "--ff-only", "--no-tags", token=token)     # the files come with the commit
        return on_branch()

    def _holds(self, dest: Path, commit: str, path: str) -> bool:
        """Whether the page is in the tree of `commit`: no record is made for a page that is not there."""
        r = self._git(dest, "ls-tree", "--name-only", commit, "--", path, seconds=30)
        return r.returncode == 0 and r.stdout.strip() == path

    # ── the report ───────────────────────────────────────────────────────────
    def report(self, member: str, repo, path, commit, private_roots=(), declared=None) -> dict:
        """The tiroir hears that `member` works on the page `path` of `repo` at `commit`. Raises `Refused` for a name
        that is none; otherwise the answer: `clone` (`ok`, `private-root`, `not-cloned`, `no-app`), `commit_known`, and
        for `no-app` the link that adds the repo. `private_roots` are (member, folder) pairs. A repo that is the
        caller's own private root is told so; one that is another member's is `not-cloned` and nothing else: no
        clone, no record, no owner named, and an answer that does not depend on what the tiroir holds (SPEC 9.11).
        A repo that became a private root after it was cloned keeps its clone and its records, takes no more."""
        repo, path, commit = _clean_repo(repo), _clean_path(path), _clean_commit(commit)
        declared = declared or {}
        folder = path.rpartition("/")[0]
        roots = [who for who, root in private_roots if self._is_private_root(repo, root)]
        if member in roots:
            return {"repo": repo, "path": path, "clone": PRIVATE_ROOT, "commit_known": None}
        if roots:
            return {"repo": repo, "path": path, "clone": NOT_CLONED, "commit_known": None}
        with self._repo_lock(repo):
            token = self.provider.token(repo)       # the provider renews it: asked each time git reaches the remote
            return self._answer(self.clone_dir(repo), member, repo, path, commit, folder, token, declared)

    def _named_owner(self, dest: Path, commit: str, path: str, token: str | None) -> str | None:
        """The `owner` of the page's front matter in the tree of `commit` (git fetches the blob when the clone lacks it)."""
        r = self._git(dest, "show", f"{commit}:{path}", token=token, seconds=60)
        named = visibility.front_matter(r.stdout).get("owner") if r.returncode == 0 and r.stdout else None
        return named if isinstance(named, str) and named else None

    def _answer(self, dest: Path, member, repo, path, commit, folder, token, declared) -> dict:
        made = not (dest / ".git").exists()
        if token is None and made:
            return {"repo": repo, "path": path, "clone": NO_APP, "commit_known": None,
                    "install": self.provider.install_url(repo)}
        if made:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if (failed := self._clone(repo, token, folder, dest)) is not None:
                raise Refused(failed)
        elif token is not None:
            self._widen(dest, folder, token)
        known = self._knows(dest, commit, token)
        if not known or not self._holds(dest, commit, path):
            return {"repo": repo, "path": path, "clone": OK, "commit_known": known}
        named = self._named_owner(dest, commit, path, token)
        with self._records:
            data = self._read()
            row = data.setdefault(repo, {}).get(path)
            owner = row["owner"] if isinstance(row, dict) else member
            data[repo][path] = {"owner": owner, "commit": commit, **({"named": named} if named else {}),
                                **{k: v for k, v in declared.items() if k in ("session", "host", "link") and v}}
            self._write(data)
        return {"repo": repo, "path": path, "clone": OK, "commit_known": known}
