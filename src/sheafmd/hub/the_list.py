"""
sheafmd.hub.the_list — the list (SPEC 9.10): per `<client>/<project>`, the sheaves that wait on a member
and the ones in progress, at `/<root>` of the root that config.toml's `[list]` names, for a member of
proxy mode (9.9).

    load()                  the `[list]` table of config.toml, checked; None without one
    parse(table, where)     the same for a table already read (the tests build one)
    TheList(hub, cfg)       the rows, rebuilt by `poll()`; `start()` polls on a thread of its own
    TheList.page(...)       the list as a member reads it, filtered

A sheaf carries no status. Its status and owner are its issue's, in the record: an issues repo and its
GitHub Project. `waiting` is the Project's option named by `waiting`, `open` the one named by
`in_progress`; any other option, no item in the Project or a closed issue keeps the sheaf off the list.
The owner is the issue's assignee, told by the member whose `github` it is. The rest is the sheaf's front
matter: `issue` (`owner/repo#n`; empty for a documentation sheaf, which is never listed), `assistant`,
`kind`, `visibility`; its title is its first `# ` heading and its actions are its unticked boxes that
carry one of the seven words (`- [ ] Approve`, `- [ ] Done @nell`).

The record is read as the GitHub App the deployment installs: the hub reads an installation token from
`token_file` at every poll and never mints one, so the App's key stays where the hub cannot read it.
"""
import calendar
import dataclasses
import html
import itertools
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from .. import config, paths
from ..blocks import _split_lines, split_md_blocks
from ..edit import TASK_MARK_RE, ticked_html
from . import place, projects
from . import roots as roots_mod
from . import visibility
from .visibility import front_matter, text as fm_text

TABLE_KEYS = {"root": str, "repo": str, "project": int, "token_file": str}
OPTIONAL_KEYS = {"api": str, "poll": int, "waiting": str, "in_progress": str, "stop_dir": str,
                 "tell_dir": str, "sessions_dir": str, "box": str, "attach": str, "work_dir": str}
# The folders of `[list]` the hub writes in or serves from: absolute, and never inside the list's root or a
# member's root, where a file would be a document (9.11, 9.12).
FOLDER_KEYS = ("stop_dir", "tell_dir", "sessions_dir")
DEFAULTS = {"api": "https://api.github.com", "poll": 60, "waiting": "Waiting on member",
            "in_progress": "In progress"}
WORDS = ("Approve", "Run it", "Don't run", "Undo skip", "Done", "Share", "Stop James")
SHOWS = {"projects": "My projects", "mine": "Only mine", "all": "All of the team"}
BATCH = 50                      # issues per GraphQL request
HTTP_SECONDS = 20

_BOX_RE = re.compile(r"[A-Za-z0-9.-]{1,63}")
_REPO_RE = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+")
_ISSUE_RE = re.compile(r"([A-Za-z0-9-]+)/([A-Za-z0-9._-]+)#([0-9]+)")
_ACTION_RE = re.compile(r"\s*[-*+] \[ \] (" + "|".join(re.escape(w).replace("'", "['’]") for w in WORDS)
                        + r")(?:\s+@([A-Za-z0-9._-]+))?\s*")


class ListError(Exception):
    """A `[list]` table the hub cannot start with. The message names the reason."""


@dataclass(frozen=True)
class ListConfig:
    root: Path                  # the folder of the root whose page is the list, absolute
    repo: str                   # the record's issues repo, `owner/name`; its owner holds the Project
    project: int                # the record's Project number
    token_file: Path            # holds the App's installation token; read at every poll
    api: str = DEFAULTS["api"]
    poll: int = DEFAULTS["poll"]
    waiting: str = DEFAULTS["waiting"]          # the Project's Status option of `waiting`
    in_progress: str = DEFAULTS["in_progress"]  # and of `open`
    stop_dir: Path | None = None                # where a Stop James tick drops its file (9.11)
    tell_dir: Path | None = None                # where Ask and Tell on a box-hosted sheaf drop theirs (9.12)
    sessions_dir: Path | None = None            # the copy of James's transcripts, <folder>/<id>.jsonl (9.12)
    box: str = ""                               # the host name of a box-hosted session (9.12)
    attach: str = ""                            # the attach command, `{window}` for <client>_<project> (9.12)
    work_dir: Path | None = None                # the folder James works in, <work_dir>/<client>/<project> (9.12)

    @property
    def owner(self) -> str:
        return self.repo.split("/")[0]


def load() -> ListConfig | None:
    try:
        data = config.read_toml(paths.config_file(), config.USER_KEYS, warn=lambda line: None)
    except config.ConfigError as e:
        raise ListError(str(e)) from None
    if "list" not in data:
        return None
    return parse(data["list"], paths.config_file())


def _within(path: str, folder: str) -> bool:
    """Whether `path` is `folder` or under it, by their real paths."""
    p, f = os.path.realpath(path), os.path.realpath(folder)
    return p == f or p.startswith(f.rstrip("/") + "/")


def parse(t: dict, where) -> ListConfig:
    here = f"[list] of {where}"
    for key in t:
        if key not in TABLE_KEYS and key not in OPTIONAL_KEYS:
            raise ListError(f"unknown key '{key}' in {here}")
    for key, typ in {**TABLE_KEYS, **OPTIONAL_KEYS}.items():
        if key not in t:
            if key in TABLE_KEYS:
                raise ListError(f"'{key}' is missing from {here}")
            continue
        if not isinstance(t[key], typ) or (typ is int and isinstance(t[key], bool)):
            raise ListError(f"'{key}' must be {'a number' if typ is int else 'text'}, not {t[key]!r}, in {here}")
    for key in ("root", "token_file"):
        if not t[key].startswith("/"):
            raise ListError(f"'{key}' must be an absolute path, in {here}: {t[key]!r}")
    for key in FOLDER_KEYS:
        if key not in t:
            continue
        folder = t[key].rstrip("/") or "/"
        if not folder.startswith("/"):
            raise ListError(f"'{key}' must be an absolute path, in {here}: {t[key]!r}")
        if _within(folder, t["root"]):
            raise ListError(f"'{key}' must not be inside the list's root, in {here}: {t[key]!r}")
    if "work_dir" in t and not t["work_dir"].startswith("/"):
        raise ListError(f"'work_dir' must be an absolute path, in {here}: {t['work_dir']!r}")
    if "box" in t and not _BOX_RE.fullmatch(t["box"]):
        raise ListError(f"'box' must be a host name, 1 to 63 letters, digits, dots or dashes, in {here}: {t['box']!r}")
    if "attach" in t and (not t["attach"].strip() or any(ord(c) < 32 or ord(c) == 127 for c in t["attach"])):
        raise ListError(f"'attach' must be one line of a command, in {here}: {t['attach']!r}")
    if not _REPO_RE.fullmatch(t["repo"]):
        raise ListError(f"'repo' must be owner/name, in {here}: {t['repo']!r}")
    if t["project"] < 1:
        raise ListError(f"'project' must be a Project's number, in {here}: {t['project']!r}")
    if t.get("poll", DEFAULTS["poll"]) < 1:
        raise ListError(f"'poll' must be a number of seconds, in {here}: {t['poll']!r}")
    api = t.get("api", DEFAULTS["api"]).rstrip("/")
    if not api.startswith(("https://", "http://127.0.0.1:", "http://localhost:")):
        raise ListError(f"'api' must be an https:// address, in {here}: {api!r}")
    return ListConfig(Path(t["root"].rstrip("/") or "/"), t["repo"], t["project"], Path(t["token_file"]),
                      api, t.get("poll", DEFAULTS["poll"]), t.get("waiting", DEFAULTS["waiting"]),
                      t.get("in_progress", DEFAULTS["in_progress"]),
                      *(Path(t[k].rstrip("/") or "/") if k in t else None for k in FOLDER_KEYS),
                      t.get("box", ""), t.get("attach", ""),
                      Path(t["work_dir"].rstrip("/") or "/") if "work_dir" in t else None)


# ── a sheaf, as its file says ───────────────────────────────────────────────

@dataclass(frozen=True)
class Sheaf:
    rel: str                    # the path in the root
    title: str
    issue: tuple | None         # (owner, repo, number)
    assistant: str
    kind: str
    visibility: str             # what the hub enforces (9.11): `owner` or `project`, never as written alone
    actions: tuple              # ((word, short name or "", 0-based line in the file), ...)
    sources: tuple = ()
    owner: str = ""
    shared: str = ""


def issue_of(written: str) -> tuple | None:
    """The issue a front matter's `issue` names, (owner, repo, number); None when it names none."""
    m = _ISSUE_RE.fullmatch(written)
    return (m.group(1), m.group(2), int(m.group(3))) if m else None


def _same_issue(a: tuple | None, b: tuple | None) -> bool:
    """Whether `a` and `b` are one issue: GitHub reads an owner and a repo name in any case."""
    def norm(i):
        return None if i is None else (i[0].casefold(), i[1].casefold(), i[2])
    return norm(a) == norm(b)


def read_sheaf(rel: str, text: str) -> Sheaf:
    fm = front_matter(text)
    issue = issue_of(fm_text(fm, "issue"))
    # The title and the actions are read from the blocks the page draws, so an action in a fence, an
    # indented code block or an HTML comment is no action, and every action is one the tick can reach.
    title, actions = "", []
    for b in split_md_blocks(text):
        own = b.content.removesuffix("\n").split("\n")
        if b.kind == "heading" and not title and own[0].startswith("# "):
            title = own[0][2:].strip()
        elif b.kind == "list":
            for k, line in enumerate(own):
                if m := _ACTION_RE.fullmatch(line.removesuffix("\r")):
                    actions.append((m.group(1).replace("’", "'"), m.group(2) or "", b.start + k))
    return Sheaf(rel, title or rel.rsplit("/", 1)[-1][:-3], issue, fm_text(fm, "assistant"),
                 fm_text(fm, "kind"), visibility.effective(fm), tuple(actions), visibility.sources(fm),
                 fm_text(fm, "owner"), fm_text(fm, "shared"))


def tick_edit(text: str, n: int, word: str):
    """The page's edit `{i, html}` that ticks the `n`th action of the sheaf `text`, if that action's word is
    `word`; None when the sheaf holds no such action now, or when its box cannot be ticked this way."""
    actions = read_sheaf("x.md", text).actions
    if not 0 <= n < len(actions) or actions[n][0] != word:
        return None
    line = actions[n][2]
    blocks = split_md_blocks(text)
    i = max(x for x, b in enumerate(blocks) if b.start <= line)
    b = blocks[i]
    own = _split_lines(b.content)
    offset = sum(len(x) for x in own[:line - b.start])
    marks = list(TASK_MARK_RE.finditer(b.content))
    k = sum(1 for m in marks if m.start() < offset)
    if k >= len(marks) or marks[k].start() != offset:
        return None                 # the mark found is not on the action's own line
    fragment = ticked_html(b, k)
    return None if fragment is None else {"i": i, "html": fragment}


# ── the record ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Record:
    status: str | None          # "waiting", "open", or None (not on the list)
    assignees: tuple            # GitHub logins
    updated: float              # when the issue last changed, epoch seconds


class RecordError(Exception):
    """The record could not be read this poll. The message says why, never the token."""


def _query(issues: list) -> str:
    parts = []
    for i, (owner, repo, number) in enumerate(issues):
        parts.append(
            f'i{i}: repository(owner: "{owner}", name: "{repo}") {{ issue(number: {number}) {{ '
            "state updatedAt assignees(first: 10) { nodes { login } } "
            "projectItems(first: 20) { nodes { project { number owner { ... on Organization { login } "
            "... on User { login } } } status: fieldValueByName(name: \"Status\") { "
            "... on ProjectV2ItemFieldSingleSelectValue { name } } } } } }")
    return "query { " + " ".join(parts) + " }"


def fetch(cfg: ListConfig, issues: list) -> dict:
    """{(owner, repo, number): Record} for `issues`, read from the record. Raises RecordError."""
    try:
        token = cfg.token_file.read_text(encoding="utf-8").strip()
    except OSError as e:
        raise RecordError(f"the token file {cfg.token_file} cannot be read ({e.strerror or e})") from None
    if not token or "\n" in token:
        raise RecordError(f"the token file {cfg.token_file} holds no token")
    out = {}
    for start in range(0, len(issues), BATCH):
        batch = issues[start:start + BATCH]
        req = urllib.request.Request(
            cfg.api + "/graphql", data=json.dumps({"query": _query(batch)}).encode(), method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                     "Accept": "application/json", "User-Agent": "sheaf-list"})
        try:
            with urllib.request.urlopen(req, timeout=HTTP_SECONDS) as r:
                answer = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise RecordError(f"GitHub answered {e.code} to the record's query") from None
        except (OSError, ValueError) as e:
            raise RecordError(f"GitHub could not be read ({type(e).__name__})") from None
        data = answer.get("data") if isinstance(answer, dict) else None
        if not isinstance(data, dict):
            kinds = sorted({str(e.get("type") or "?") for e in answer.get("errors") or [] if isinstance(e, dict)}) \
                if isinstance(answer, dict) else []
            raise RecordError(f"GitHub answered the record's query with errors and no data ({', '.join(kinds) or 'none named'})")
        for i, key in enumerate(batch):
            issue = (data.get(f"i{i}") or {}).get("issue")
            if issue is not None:
                out[key] = _record(cfg, issue)
    return out


def _record(cfg: ListConfig, issue: dict) -> Record:
    assignees = tuple(n["login"] for n in (issue.get("assignees") or {}).get("nodes", []) if n)
    try:
        updated = float(calendar.timegm(time.strptime(issue.get("updatedAt") or "", "%Y-%m-%dT%H:%M:%SZ")))
    except ValueError:
        updated = 0.0
    status = None
    if issue.get("state") == "OPEN":
        for item in (issue.get("projectItems") or {}).get("nodes", []):
            project = (item or {}).get("project") or {}
            if project.get("number") == cfg.project and \
                    ((project.get("owner") or {}).get("login") or "").lower() == cfg.owner.lower():
                name = ((item.get("status") or {}).get("name"))
                status = {cfg.waiting: "waiting", cfg.in_progress: "open"}.get(name)
    return Record(status, assignees, updated)


# ── the list ────────────────────────────────────────────────────────────────

@dataclass
class Row:
    sheaf: Sheaf
    record: Record
    group: str                  # `<client>/<project>`
    read: tuple | None = None   # `_stat_key` of the file the sheaf was read from


@dataclass
class Snapshot:
    rows: list = field(default_factory=list)
    projects: dict = field(default_factory=dict)    # `projects.toml`'s entries, {} without the file
    polled: float | None = None


def _stat_key(st: os.stat_result) -> tuple:
    """What tells a file from the one read before at its address: another file, or a change of it."""
    return (st.st_dev, st.st_ino, st.st_mtime_ns, st.st_ctime_ns, st.st_size)


def _drop(snap: Snapshot, row: Row):
    """Take `row` off `snap` as a new list: a page reading the old one keeps it."""
    snap.rows = [r for r in snap.rows if r is not row]


class TheList:
    def __init__(self, hub, cfg: ListConfig):
        self.hub, self.cfg = hub, cfg
        self._snap = Snapshot()
        self._records: dict = {}            # the last record read of each issue, kept through a failed poll
        self._answered: dict = {}           # {rel: the record's `updated` when a member ticked it}
        self._poll_lock = threading.Lock()
        self._ask = itertools.count(1)      # numbers each poll's start and each time a file is seen gone, in order
        self._gone: dict = {}               # {real path: the number of the last time the hub saw its file gone}
        self._gone_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    # ── the poll ────────────────────────────────────────────────────────────
    def root(self):
        """The registered root of the list's folder, registered on the first ask."""
        return self.hub.roots.for_document(self.cfg.root / projects.FILE)

    def poll(self):
        """Read every sheaf of the root and the record of their issues, and keep the rows."""
        with self._poll_lock:
            with self._gone_lock:
                started = next(self._ask)
            root = self.root()
            if root.path != Path(os.path.realpath(self.cfg.root)):
                # Inside a git work tree the root is the tree's top: its sheaves are not the list's.
                self.hub.record("list-poll-failed", None, root=root.name,
                                error=f"{self.cfg.root} is not the top folder of its root ({root.path})")
                self._records, self._answered, self._snap = {}, {}, Snapshot()
                return
            sheaves, read = [], {}
            for found in roots_mod.list_documents(root).docs:
                if found.rel.count("/") < 2:
                    continue                # above `<client>/<project>`: no sheaf
                if self.hub.roots.lookup(root.path / found.rel) != root:
                    continue                # a nested root's (8.2): 9.9 keeps it from the list's members
                try:
                    key = _stat_key((root.path / found.rel).stat())     # before the read: a change after it shows
                    text = (root.path / found.rel).read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                read[found.rel] = key
                try:
                    s = read_sheaf(found.rel, text)
                except Exception:           # one sheaf the reader trips on leaves the rest of the list
                    self.hub.record_exception("list-poll-failed", None)
                    continue
                if s.issue is not None:
                    sheaves.append(s)
            try:
                entries = projects.read(root.path) or {}
            except projects.Invalid:
                entries = {}
            wanted = sorted({s.issue for s in sheaves})
            try:
                self._records = fetch(self.cfg, wanted) if wanted else {}   # an issue it does not hold is off
            except RecordError as e:
                self.hub.record("list-poll-failed", None, root=root.name, error=str(e))
            rows = [Row(s, self._records[s.issue], "/".join(s.rel.split("/")[:2]), read.get(s.rel))
                    for s in sheaves if s.issue in self._records]
            # A ticked sheaf waits on nobody until the record routine has moved its issue: a new change of the
            # issue, or a Status other than waiting (moving a Project's Status leaves the issue's change as it was).
            moved = {r.sheaf.rel for r in rows
                     if r.record.status != "waiting" or self._answered.get(r.sheaf.rel, r.record.updated) != r.record.updated}
            for rel in moved | (set(self._answered) - {r.sheaf.rel for r in rows}):
                self._answered.pop(rel, None)
            with self._gone_lock:
                # A file seen gone after this poll began may have been read before it went: its row waits for the
                # next poll, which reads what is there now (#34).
                rows = [r for r in rows if self._gone.get(os.path.realpath(root.path / r.sheaf.rel), 0) < started]
                self._gone = {f: n for f, n in self._gone.items() if n > started}
                self._snap = Snapshot(rows, entries, self.hub.clock())
            # Every sheaf not at its home goes there (9.11), judged with the records just read: the first poll
            # moves what was written before the rule, a later one what an owner change made another's.
            for rel in read:
                if place.logical(rel) is not None:
                    try:
                        place.place(self.hub, f"{root.name}/{rel}")
                    except Exception:       # one sheaf that cannot move leaves the others
                        self.hub.record_exception("place-failed", f"{root.name}/{rel}")

    def start(self):
        def run():
            while not self._stop.is_set():
                try:
                    self.poll()
                except Exception:
                    self.hub.record_exception("list-poll-failed", None)
                self._stop.wait(self.cfg.poll)
        self._thread = threading.Thread(target=run, name="the-list", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def ticked(self, address: str):
        """A member ticked an action of the sheaf at `address`: its row leaves "Waiting on you" now, and
        shows its other actions, rather than at the next poll that sees the record move. A sheaf whose file
        now names another issue, or none, leaves the list until the next poll: its row's record is not that
        issue's, so its assignees are nobody's (9.11)."""
        a = roots_mod.Address.parse(address)
        root = self.root()
        if a.root != root.name:
            return
        with self._gone_lock:           # as `assignees` drops a row, so neither write undoes the other
            snap = self._snap
            for row in snap.rows:
                if row.sheaf.rel == a.rel:
                    try:
                        sheaf = read_sheaf(a.rel, (root.path / a.rel).read_text(encoding="utf-8"))
                    except (OSError, UnicodeDecodeError):
                        sheaf = row.sheaf
                    if not _same_issue(sheaf.issue, row.sheaf.issue):
                        _drop(snap, row)
                        return
                    row.sheaf = sheaf
                    self._answered[a.rel] = row.record.updated

    def moved(self, old: str, new: str):
        """The sheaf at `old` (a path in the root) now lives at `new` (9.11): its row takes the new path at once,
        so the page links where the file is, and a tick waits on it as before."""
        with self._gone_lock:
            for row in self._snap.rows:
                if row.sheaf.rel == old:
                    row.sheaf, row.read = dataclasses.replace(row.sheaf, rel=new), None
            if old in self._answered:
                self._answered[new] = self._answered.pop(old)

    # ── the page ────────────────────────────────────────────────────────────
    def assignees(self, address: str, issue: str):
        """The record's assignees of the issue of the sheaf at `address`, from the last poll, when `issue`, what
        its file names now, is still the issue of its row; None when the list does not know the sheaf (no row:
        another root, no issue, not polled yet, an issue changed since the poll, or a file gone since). The row
        of a file gone since is dropped then, and kept out of the snapshot of a poll that began before, until
        the next poll."""
        a = roots_mod.Address.parse(address)
        root = self.root()
        if root is None or a.root != root.name:
            return None
        with self._gone_lock:
            # Seen gone and numbered in one step, so a poll that begins after this has the larger number.
            if not os.path.lexists(root.path / a.rel):
                # Kept, the row would judge a sheaf a door create makes at its address before the next poll, and
                # tell which issue the one that went named (#34).
                # By its real path, so the row of a link to it goes too.
                gone = os.path.realpath(root.path / a.rel)
                self._gone[gone] = next(self._ask)
                snap = self._snap
                for row in snap.rows:
                    if os.path.realpath(root.path / row.sheaf.rel) == gone:
                        _drop(snap, row)
                return None
        for row in self._snap.rows:
            if row.sheaf.rel == a.rel:
                return tuple(row.record.assignees) if _same_issue(row.sheaf.issue, issue_of(issue)) else None
        return None

    def serves(self, name: str) -> bool:
        """Whether `name` is the root whose page is the list; never the git top of a refused list root."""
        r = self.hub.roots.lookup(self.cfg.root / projects.FILE)
        return r is not None and r.name == name and r.path == Path(os.path.realpath(self.cfg.root))

    def page(self, member, show: str, nonce: str) -> str:
        snap = self._snap
        show = show if show in SHOWS else "projects"
        members = list(self.hub.proxy.members.values())
        root = self.root()
        sections = {"waiting": [], "open": []}
        for row in snap.rows:
            if row.record.status not in sections:
                continue
            if row.record.status == "waiting" and self._answered.get(row.sheaf.rel) == row.record.updated:
                continue
            address = f"{root.name}/{row.sheaf.rel}"
            if not self.hub.visible(member, address):               # the file now, not the poll
                continue
            row = self._now(root, row, member, address)             # and what it says now
            if row is None:
                continue
            owners = self.hub.owners(address, members)              # and its owners, as visible has them
            is_owner = any(o.id == member.id for o in owners)
            addressed = any(short and short.lower() == member.short.lower() for _, short, _ in row.sheaf.actions)
            if show == "mine" and not (is_owner or addressed):
                continue
            if show == "projects":
                entry = snap.projects.get(row.group) or {}
                if not member.short or member.short.lower() not in {str(m).lower() for m in entry.get("members", [])}:
                    continue
            sections[row.record.status].append((row, owners, is_owner))
        body = "".join(self._section(title, sections[key], member, root.name)
                       for key, title in (("waiting", "Waiting on you"), ("open", "In progress")))
        current = ' aria-current="page"'
        filters = "".join(
            f'<a class="list-filter{" on" if key == show else ""}" href="{_href(root.name, key)}"'
            f'{current if key == show else ""}>{html.escape(label)}</a>'
            for key, label in SHOWS.items())
        return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>Actions</title><style>{CSS}</style></head><body>'
                f'<header><h1>Waiting on you</h1><span class="list-sub">and what is in progress</span></header>'
                f'<nav class="list-filters">{filters}</nav><p class="list-error" hidden></p><main>{body}</main>'
                f'<script nonce="{nonce}">{SCRIPT}</script></body></html>')

    def _now(self, root, row: Row, member, address: str):
        """`row` with the sheaf its file holds now when that file is not the one the poll read (another file
        made at its address, or one a link now points to, or a change), so the page never shows what a sheaf
        that went said; None when it now names another issue, cannot be read, or is no longer `member`'s to
        see: it may have changed since `visible` judged it."""
        f = root.path / row.sheaf.rel
        try:
            key = _stat_key(f.stat())
            if key == row.read:
                return row
            text = f.read_text(encoding="utf-8")
            sheaf = read_sheaf(row.sheaf.rel, text)
        except Exception:                   # unreadable, or one the reader trips on, as the poll leaves it out
            return None
        if not _same_issue(sheaf.issue, row.sheaf.issue):
            return None
        fm = visibility.front_matter(text)
        if not visibility.visible_to(fm, member, self.hub.assignees(address, fm)):
            return None
        return Row(sheaf, row.record, row.group, key)

    def _section(self, title: str, rows: list, member, root: str) -> str:
        groups: dict = {}
        for row, owners, is_owner in rows:
            groups.setdefault(row.group, []).append((row, owners, is_owner))
        out = []
        for group in sorted(groups):
            items = sorted(groups[group], key=lambda r: -r[0].record.updated)
            out.append(f'<div class="list-group"><h3>{html.escape(group)}</h3><ul>'
                       + "".join(self._row(r, o, mine, member, root) for r, o, mine in items) + "</ul></div>")
        return (f'<section class="list-section"><h2>{html.escape(title)} <span class="list-count">{len(rows)}'
                f'</span></h2>{"".join(out)}</section>')

    def _row(self, row: Row, owners: list, is_owner: bool, member, root: str) -> str:
        s, rec = row.sheaf, row.record
        chips = "".join(
            f'<span class="list-chip">{html.escape(word)}'
            f'{" @" + html.escape(short) if short and short.lower() != member.short.lower() else ""}</span>'
            for word, short, _ in s.actions)
        if s.assistant:
            chips += f'<span class="list-assistant">{html.escape(s.assistant)}</span>'
        by_login = {m.github.lower(): m for m in self.hub.proxy.members.values() if m.github}
        first = by_login.get(rec.assignees[0].lower()) if rec.assignees else None
        if is_owner:
            owner = "you"
        elif rec.assignees:             # the issue's first assignee, as the record orders them
            owner = "@" + first.short if first is not None and first.short else rec.assignees[0]
        elif owners and owners[0].short:
            owner = "@" + owners[0].short
        else:
            owner = "nobody"
        meta = " · ".join(x for x in (s.kind, owner, f"#{s.issue[2]}", _age(self.hub.clock() - rec.updated)) if x)
        box = ""
        if s.actions:
            word = s.actions[0][0]
            box = (f'<input type="checkbox" aria-label="{html.escape(word)}" data-doc="{html.escape(f"{root}/{s.rel}")}"'
                   f' data-action="0" data-word="{html.escape(word)}">')
        href = roots_mod.url_path(f"{root}/{s.rel}")
        return (f'<li class="list-row">{box}<div><a class="list-title" href="{html.escape(href)}">'
                f'{html.escape(s.title)} {chips}</a><div class="list-meta">{html.escape(meta)}</div></div></li>')


def _href(root: str, show: str) -> str:
    base = "/" + quote(root)
    return base if show == "projects" else f"{base}?show={show}"


def _age(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 3600:
        return f"{max(1, seconds // 60)} min"
    if seconds < 86400:
        return f"{seconds // 3600} h"
    return f"{seconds // 86400} d"


# A tick posts the row's action to the hub and reloads the list; a refusal is said above the rows.
SCRIPT = """
document.querySelectorAll('.list-row input[type=checkbox]').forEach(function (b) {
  b.addEventListener('change', function () {
    b.disabled = true;
    var said = document.querySelector('.list-error');
    fetch('/_/tick', {method: 'POST', headers: {'Content-Type': 'application/json'}, credentials: 'same-origin',
      body: JSON.stringify({doc: b.dataset.doc, action: Number(b.dataset.action), word: b.dataset.word})})
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) {
        if (r.ok) { location.reload(); return; }
        throw new Error(j.error || ('the hub answered ' + r.status));
      }); })
      .catch(function (e) { b.checked = false; b.disabled = false; said.textContent = e.message; said.hidden = false; });
  });
});
"""

CSS = """
:root{--fg:#1d1d1f;--muted:#6e6e73;--line:#e5e5ea;--chip:#1f5fd6;--bg:#fff}
@media (prefers-color-scheme:dark){:root{--fg:#f2f2f7;--muted:#a1a1a6;--line:#38383a;--chip:#6ea2ff;--bg:#1c1c1e}}
body{margin:0;padding:24px 16px;font:15px/1.45 system-ui,sans-serif;color:var(--fg);background:var(--bg)}
header{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
h1{font-size:20px;margin:0}.list-sub{color:var(--muted);font-size:13px}
.list-filters{display:flex;gap:8px;margin:12px 0 20px;flex-wrap:wrap}
.list-filter{border:1px solid var(--line);border-radius:999px;padding:3px 12px;color:var(--muted);text-decoration:none}
.list-filter.on{border-color:var(--fg);color:var(--fg)}
h2{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:24px 0 8px}
h3{font-size:15px;margin:16px 0 4px}
ul{list-style:none;margin:0;padding:0}
.list-row{display:flex;gap:10px;padding:10px 0;border-bottom:1px solid var(--line)}
.list-row input{margin-top:4px}
.list-title{color:var(--fg);text-decoration:none}.list-title:hover{text-decoration:underline}
.list-chip,.list-assistant{display:inline-block;font-size:12px;border:1px solid var(--chip);color:var(--chip);
border-radius:999px;padding:0 8px;margin-left:6px}
.list-assistant{border-color:var(--line);color:var(--muted)}
.list-meta{color:var(--muted);font-size:13px}
.list-error{color:#c62828}
"""
