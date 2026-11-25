"""sheafmd.hub.root_sender — the old tiroir's side of a root that moved: its `.sheaf.toml` names another tiroir.

    run(hub, repo, to)    one try of the move of `repo`'s root to the tiroir at `to`; the state it ends in
    sweep(hub)            `run` for each clone whose `.sheaf.toml` names another tiroir than this one

A try sends the pages the hub keeps something of (a record, versions or Write log lines) that may leave, writes a Forward for each
page the other tiroir confirmed, and puts the clone to sleep once every sent page has its Forward. What a try cannot finish is held
with a reason in `root_moves.json` and tried again at the next sweep: nothing is lost by a missed pull or a refused page. The text of
a page, its comments and its Share lines are in git and reach the other tiroir through its own clone, never over the channel.
"""
import dataclasses
import subprocess
import uuid
from pathlib import Path

from .. import connect, diagnostics, paths
from . import incoming, outgoing, root_moves, roots as roots_mod
from . import repos as repos_mod

NO_BRANCH = "no_branch"
STATES = ("unpaired", "held", "partial", "moved")


def _git(clone: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(clone), *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _member(hub, name: str):
    return next((m for m in hub.proxy.members.values() if (m.short or m.id) == name), None)


def _pages(hub, repo: str, prefix: str) -> list[str]:
    """The paths of the pages of `repo` the hub keeps something of."""
    found = set(hub.repos.records(repo))
    store = incoming._versions_for(hub, repo)
    for address in [*hub.writes.addresses(prefix), *(store.addresses(prefix) if store is not None else [])]:
        found.add(address[len(prefix):])
    return sorted(found)


def _rows(hub, repo: str, branch: str, prefix: str, paths_: list[str]) -> tuple:
    """`(rows, held)`: the page rows a `root` call takes for the pages that may leave, and `{path: why}` for the ones that may not."""
    rows, held, records = [], {}, hub.repos.records(repo)
    store = incoming._versions_for(hub, repo)
    dest = hub.repos.clone_dir(repo)
    for path in paths_:
        owner = hub.repos.owner_of(repo, path)
        member = _member(hub, owner) if owner else None
        if member is None:
            continue                    # opens to nobody: no Forward either, git carries it
        email, _ = outgoing.owner_email(hub.proxy, member)
        blob = _git(dest, "rev-parse", f"origin/{branch}:{path}")
        if email is None or blob is None:
            held[path] = "no_email" if email is None else "differs"
            continue
        address = prefix + path
        row = records.get(path, {})
        rows.append({"path": path, "owner_email": email, "blob": blob,
                     "record": {k: row[k] for k in ("session", "host", "link") if row.get(k)},
                     "versions": [{"text": t} for t in (store.texts(address) if store is not None else [])[-incoming.MAX_VERSIONS:]],
                     "writes": [dataclasses.asdict(w) for w in hub.writes.lines(address)[-incoming.MAX_WRITES:]]})
    return rows, held


def run(hub, repo: str, to: str, *, post=outgoing.call, moves: root_moves.Moves | None = None,
        diag: root_moves.Diag | None = None) -> str:
    """One try of the move of `repo`'s root to the tiroir at `to`. `post(to, verb, body)` is the channel (`outgoing.call`). Returns
    `unpaired` (this hub holds no peer token for `to`: nothing is sent), `held` (nothing could be sent yet, the move holds
    why), `partial` (some pages are confirmed and forwarded, others wait), or `moved` (every page has its Forward and the
    clone sleeps)."""
    moves = moves or root_moves.Moves(paths.state_dir())
    diag = diag or root_moves.Diag()
    if hub.repos.moved_to(repo) == to:
        return "moved"
    if not root_moves.paired(to):
        diag.unpaired(repo, to)
        return "unpaired"
    branch, _ = hub.repos.saves_on(repo)
    dest = hub.repos.clone_dir(repo)
    tip = _git(dest, "rev-parse", f"origin/{branch}") if branch else None
    if tip is None:
        moves.start(repo, to, uuid.uuid4().hex)
        moves.hold(repo, {"": NO_BRANCH})
        return "held"
    if moves.get(repo) is None:
        diag.started(repo, to)
    move = moves.start(repo, to, uuid.uuid4().hex)
    prefix = roots_mod.Address.prefix(repos_mod.root_name(repo))
    todo = _pages(hub, repo, prefix)
    leaving = root_moves.held(dest, branch, todo)
    rows, no = _rows(hub, repo, branch, prefix, [p for p in todo if p not in leaving])
    head = {"id": move["id"], "repo": repo, "branch": branch, "tip": tip, "from": {"origin": hub.proxy.origin, "by": "hub"}}
    if rows:
        outgoing.send_root(post, moves, repo, to, head, rows, diag=diag)
    _forward(hub, repo, to, prefix, moves)
    row = moves.get(repo) or {}
    held = {**leaving, **no, **({p: w for p, w in row.get("held", {}).items() if p not in row.get("sent", [])})}
    if held or not {r["path"] for r in rows} <= set(row.get("sent", [])):
        moves.hold(repo, held)
        return "partial" if row.get("sent") else "held"
    if _sleep(hub, repo, to, diag, len(row.get("sent", []))) != "moved":
        return "partial"                # the move stays as it is: the next try asks the clone to sleep, and sends nothing twice
    moves.done(repo) if rows else moves.cancel(repo)
    return "moved"


def _forward(hub, repo: str, to: str, prefix: str, moves: root_moves.Moves):
    """A Forward for each page the other tiroir confirmed that has none: written before the Tells on the page end, so the old
    address answers from this moment. The page's file stays in the clone (git holds it); the clone's sleep takes it away."""
    for path, landed in moves.pending_forward(repo).items():
        address = prefix + path
        was = _git(hub.repos.clone_dir(repo), "hash-object", "--", path) or ""
        owner = hub.repos.owner_of(repo, path) or "hub"
        hub.forwards.add_remote(address, to, address, owner, landed, was)
        for ending in (hub.session_tells, hub.waiting_tells):
            try:
                ending.end_page(address, "page moved")
            except Exception:
                hub.record_exception("tell-end-failed", address)
        moves.forwarded(repo, path)


def _sleep(hub, repo: str, to: str, diag: root_moves.Diag, count: int) -> str:
    for _ in range(incoming.SLEEP_TRIES):
        if hub.repos.sleep_moved(repo, to):
            diag.done(repo, to, count)
            return "moved"
        hub.repos.settle(1.0, repo=repo)
    diagnostics.record("hub", "root-not-asleep", repo=repo)
    return "partial"


def sweep(hub, **kw) -> dict:
    """`run` for each clone whose `.sheaf.toml` names another tiroir than this hub's own; `{repo: state}`. Never raises for one repo."""
    done = {}
    if getattr(hub, "repos", None) is None or getattr(hub, "proxy", None) is None:
        return done
    for repo in hub.repos.clones():
        try:
            to = root_moves.target(hub.repos.clone_dir(repo), hub.proxy.origin)
            if to is not None:
                done[repo] = run(hub, repo, to, **kw)
        except (connect.ConnectError, OSError):
            continue
        except Exception:
            hub.record_exception("root-move-failed", repo)
    return done
