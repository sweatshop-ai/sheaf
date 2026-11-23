"""sheafmd.hub.incoming — the receiving end of a move to this tiroir (ticket 20).

    owner_for(hub, email)       (the member the e-mail names, "") or (None, why)
    land(hub, door, bundle)     (200, the answer) of a page landed in its owner's loose root, or (409, {why, say}) of one refused

A page lands whole or not at all: its file, versions, Write log lines and keep mark are made together under the name's lock,
and a failure takes back what was made. `transfers.json` keeps the answer to each `id`, so a send whose confirmation was
lost is answered again and never lands twice.
"""
import contextlib
import json
import os
import time
from pathlib import Path

from .. import mcp, paths
from . import channel, loose, proxy, root_moves, state, visibility
from . import repos as repos_mod
from .roots import NotFound
from .state import TokenRow

SAYS = {
    "no_email": "this shared Sheaf does not know the e-mail address of the person who owns the page, or that person has none "
                "here: a member's e-mail must be set in its configuration before pages can be moved to them",
    "no_owner": "no one on this shared Sheaf has the owner's e-mail address",
    "ambiguous_owner": "more than one person on this shared Sheaf has the owner's e-mail address",
    "name_taken": "a page of that name is there already, in that folder: it may be an older copy of this one",
    "not_landed": "the page was not accepted",
    "too_slow": "the landing took longer than the time the sender waits for it, so nothing was kept: send the page again",
}
MAX_VERSIONS = 60       # `Versions` keeps no more
MAX_WRITES = 200


def owner_for(hub, email) -> tuple:
    """The one member of this hub whose `email` is `email`, ignoring case. The e-mail is the only key: never the name or the
    short name. An e-mail that is empty, or the made-up one a member without a block gets (`proxy.default_email`), names
    no one (`no_email`); no member, or two, is `no_owner` and `ambiguous_owner`: never the first of two."""
    cfg = hub.proxy
    if cfg is None or not isinstance(email, str) or not email.strip():
        return None, "no_email"
    wanted = email.strip().lower()
    if any(wanted == proxy.default_email(m.id, cfg.origin).lower() for m in cfg.members.values()):
        return None, "no_email"
    found = [m for m in cfg.members.values() if m.email and m.email.strip().lower() == wanted]
    if not found:
        return None, "no_owner"
    return (found[0], "") if len(found) == 1 else (None, "ambiguous_owner")


def _answers() -> Path:
    return paths.state_dir() / "transfers.json"


def _refused(why: str, say: str | None = None) -> tuple:
    return 409, {"ok": False, "why": why, "say": say or SAYS[why]}


def _shape(b) -> str | None:
    """Why `b` is not a bundle, or None."""
    if not isinstance(b, dict):
        return "the bundle is not an object"
    if not (isinstance(b.get("id"), str) and 0 < len(b["id"]) <= 64):
        return "the bundle has no id"
    if not (isinstance(b.get("name"), str) and b["name"].endswith(".md") and "/" not in b["name"] and "\\" not in b["name"]
            and not b["name"].startswith(".") and "\0" not in b["name"]):
        return "the bundle's name is not a file name"
    if not isinstance(b.get("text"), str):
        return "the bundle has no text"
    if b.get("folder") is not None and not isinstance(b["folder"], str):
        return "the bundle's folder is not text"
    if not (isinstance(b.get("versions", []), list) and len(b.get("versions", [])) <= MAX_VERSIONS
            and all(isinstance(v, dict) and isinstance(v.get("text"), str) for v in b.get("versions", []))):
        return "the bundle's versions are not versions"
    if not (isinstance(b.get("writes", []), list) and len(b.get("writes", [])) <= MAX_WRITES
            and all(isinstance(w, dict) for w in b.get("writes", []))):
        return "the bundle's Write log lines are not lines"
    if not isinstance(b.get("keep", False), bool):
        return "keep is not true or false"
    if not isinstance(b.get("archived", False), bool):
        return "archived is not true or false"
    return None


def land(hub, door, b, peer: str | None = None, deadline: float | None = None) -> tuple:
    """Land bundle `b` for the member its `owner_email` names. (200, {ok, address, hash, origin}) or (409, {ok: False, why, say});
    a bundle that is not one is a Refuse of the handler's (`ValueError` here, with the reason), never a half-landed page.
    `peer` is the origin the channel's token names, passed by the caller: a page moves back only from the tiroir the token is of.
    `deadline` is when the sender stops waiting (`time.monotonic()`): the moment the request arrived, plus the time it waits, so a
    landing that waited for `transfers.lock` has that wait counted. Without it, from the call."""
    deadline = time.monotonic() + channel.SECONDS if deadline is None else deadline
    if (bad := _shape(b)) is not None:
        raise ValueError(bad)
    with state.file_locked("transfers.lock"):     # held to the end: two sends of one id land one page, the second told the first's answer
        known = state.read_json(_answers(), {}).get(b["id"])
        if isinstance(known, dict):             # before the owner is looked for: an owner that went since is no reason to forget the answer
            return 200, {"ok": True, **known}
        owner, why = owner_for(hub, b.get("owner_email"))
        if owner is None:
            return _refused(why)
        try:
            return _landed(hub, door, b, owner, deadline, peer)
        except _TooSlow:
            return _refused("too_slow")


class _TooSlow(Exception):
    """The landing ran past the time the sender waits for its answer: what it made is taken back, and nothing is remembered."""


def _landed(hub, door, b, owner, deadline, peer: str | None = None) -> tuple:
    """The landing of `land`, with `transfers.lock` held. The deadline is the sender's: past it the sender has given up and
    keeps its page, so a page landed after it would be a second one. It is checked between the steps, never inside one.
    The landing holds no writer lock: a failed one takes back the Write log lines it wrote itself, never those another writer
    added at the address meanwhile."""
    with hub.writes.own_lines() as mine:
        return _land_steps(hub, door, b, owner, deadline, peer, mine)


def _land_steps(hub, door, b, owner, deadline, peer: str | None, mine) -> tuple:
    caller = mcp.Caller(owner.name, TokenRow("peer-transfer", owner.name, True, member=owner.id))
    # The Share does not travel: its audience is text, and the people it names are not this tiroir's. The page lands the
    # owner's alone, every Share box unticked and no `shared` line, whatever the sender's text said.
    text = visibility.unshare(visibility.without_ticked_share(b["text"]))
    args = {"doc": b["name"], "folder": b.get("folder"), "text": text, **({"keep": True} if b.get("keep") else {})}
    # A page that comes back to the address it once left for the tiroir it comes from takes the Forward there away; any other Forward at
    # the address stays, and refuses the landing as it refuses a create.
    back = _forward_back(hub, owner, b, peer)
    lifted = hub.forwards.lift_remote(back) if back is not None else {}
    try:
        made = door._create(args, caller)
    except BaseException as e:
        hub.forwards.put_back(lifted)
        if isinstance(e, mcp.ToolError):
            return _refused("name_taken") if e.why == "exists" else _refused("not_landed", str(e))
        raise
    address = made["doc"]
    made_at = _made_file(hub, owner, address)     # a failed landing takes back this file, no other
    store = _versions_store(hub, owner)
    try:
        for v in b.get("versions", []):
            store.put(address, visibility.set_keys(visibility.without_ticked_share(v["text"]), {"shared": None}))     # a version restored brings back no audience
            _in_time(deadline)
        by = (b.get("from") or {}).get("by") if isinstance(b.get("from"), dict) else None
        came_from = (b.get("from") or {}).get("origin") if isinstance(b.get("from"), dict) else None
        hub.writes.carry(address, b.get("writes", []), came_from if isinstance(came_from, str) else "",
                         by if isinstance(by, str) else owner.name)
        _in_time(deadline)
        if b.get("archived"):
            _archive(hub, owner, address)
        _in_time(deadline)
        answer = {"address": address, "hash": made["hash"], "origin": hub.proxy.origin}
        state.write_json(_answers(), {**state.read_json(_answers(), {}), b["id"]: answer})
    except BaseException:
        if made_at is not None:     # never the file of a folder that took the loose root's name since (8.11)
            with contextlib.suppress(OSError):
                os.unlink(made_at)
        with contextlib.suppress(Exception):
            store.forget(address, inside=True)
        with contextlib.suppress(Exception):
            hub.writes.undo(address, mine)
        if (loose_root := hub.loose.known(owner)) is not None:
            with contextlib.suppress(loose.Refused, OSError):
                _unkeep(loose_root, address)
            with contextlib.suppress(loose.Refused, OSError):
                _unarchive(loose_root, address)
        hub.forwards.put_back(lifted)
        raise
    for earlier, was in lifted.items():     # the addresses the page had before it left lead to where it is again
        if earlier != address:
            hub.forwards.add(earlier, address, was.get("by", owner.name))
    return 200, {"ok": True, **answer}


def _made_file(hub, owner, address: str) -> Path | None:
    """The real path of the file a landing just made at `address`, in the root registered at `owner`'s loose folder, found by
    that folder and never by the name alone; None when the address names no such root now (its root forgotten, and maybe
    its name taken, since the create)."""
    held = hub.loose.known(owner)
    root = hub.roots.lookup(held / "x.md") if held is not None else None
    if root is None:
        return None
    try:
        return Path(os.path.realpath(hub.file(address, root_id=root.id)))
    except NotFound:
        return None


def _unkeep(root_path, address: str) -> None:
    """Take back the keep mark a landing made for `address`, when it made one."""
    rel = address.split("/", 1)[1]
    with state.file_locked("loose-keep.lock"):
        held = loose.marks(root_path)
        if rel in held:
            state.write_text_private(root_path / loose.KEEP, json.dumps(sorted(x for x in held if x != rel)) + "\n", inside=True)


def _forward_back(hub, owner, b, peer: str | None) -> str | None:
    """The address when the bundle's page would land at an address that a Forward of this tiroir leads away from, to the
    tiroir that sent it: the page is moving back. The sender is the origin of the peer token that authenticated the call, never the
    bundle's own `from.origin`, which any paired tiroir may write as it likes."""
    held = hub.loose.known(owner)
    root = hub.roots.lookup(held / "x.md") if held is not None else None
    if root is None or not peer:
        return None
    try:
        folder = loose.folder_path(b.get("folder"))
    except ValueError:
        return None
    address = f"{root.name}/{folder + '/' if folder else ''}{b['name']}"
    far = hub.forwards.remote(address)
    return address if far is not None and root_moves.origin(far["origin"]) == root_moves.origin(peer) else None


def _versions_store(hub, owner):
    """Where the versions of the owner's loose root are kept: inside the root with `versions = "root"`, else the state folder's."""
    held = hub.loose.known(owner)
    root = hub.roots.lookup(held / "x.md") if held is not None else None
    return (hub._versions_of(root) if root is not None else None) or hub.versions


def _in_time(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise _TooSlow


def _archive(hub, owner, address: str) -> None:
    """The page lands archived, as it left: the mark is its landing's, so it is the page's last write that it is not older than."""
    root = hub.loose.known(owner)
    rel = address.split("/", 1)[1]
    with state.file_locked("loose-keep.lock"):
        loose.stamp_held(root, loose.ARCHIVED, {rel: max(hub.clock(), os.stat(hub.file(address)).st_mtime)})


def _unarchive(root_path, address: str) -> None:
    with state.file_locked("loose-keep.lock"):
        loose.stamp_held(root_path, loose.ARCHIVED, {address.split("/", 1)[1]: None})


# ── a whole root (ticket 21) ─────────────────────────────────────────────────

MAX_PAGES = 5000


def _root_shape(b) -> str | None:
    """Why `b` is not a root's move, or None."""
    if not isinstance(b, dict):
        return "the root's move is not an object"
    for key in ("id", "repo", "branch", "tip"):
        if not (isinstance(b.get(key), str) and 0 < len(b[key]) <= 200):
            return f"the root's move has no {key}"
    pages = b.get("pages")
    if not (isinstance(pages, list) and len(pages) <= MAX_PAGES):
        return "the root's move has no list of pages"
    if len({p.get("path") for p in pages if isinstance(p, dict)}) != len(pages):
        return "a page of the root's move is listed twice"
    for p in pages:
        if not (isinstance(p, dict) and isinstance(p.get("path"), str) and p["path"] and "\0" not in p["path"]
                and "\\" not in p["path"] and not p["path"].startswith("/") and ".." not in p["path"].split("/")):
            return "a page of the root's move has no path"
        if not (isinstance(p.get("owner_email"), str) and isinstance(p.get("blob"), str) and p["blob"]):
            return "a page of the root's move has no owner e-mail or no blob"
    return None


def check_root(hub, b, peer: str | None = None) -> tuple:
    """First stage of landing a root moved here: which of its pages this tiroir can take. The clone is made by the same report
    a laptop's would be (same App, same private-root rule, so the peer token never widens what this tiroir may clone); each
    page's owner is the member its e-mail names; the page's blob must be what this tiroir's own clone holds at the save
    branch. `(202, {state: cloning})` while the clone is made or the tip not here yet; `(409, {why})` for the whole root;
    else `(200, {pages: {path: {ready: True} | {ok: False, why}}})`. A repo whose root moved away from here is refused whole
    (`moved`), unless `peer` (the origin the channel's token names, passed by the caller) is the tiroir it moved to: that root is coming back,
    and is unmoved once nothing in this check refuses it. This writes nothing of its own: the report is the laptop's, so it dates the clone as used and records the first
    owner's page, as a laptop's would; the page's own state is landing's."""
    if (bad := _root_shape(b)) is not None:
        raise ValueError(bad)
    repos = getattr(hub, "repos", None)
    if repos is None:
        return 409, {"why": "no_clones"}
    if getattr(hub, "proxy", None) is None:
        return 409, {"why": "no_origin"}
    judged, first = {}, None
    for p in b["pages"]:
        owner, why = owner_for(hub, p["owner_email"])
        if owner is None:
            judged[p["path"]] = {"ok": False, "why": why}
        elif first is None:
            first = (owner, p["path"])
    if first is not None:
        privates = [(m.short or m.id, m.private_root) for m in hub.proxy.members.values() if m.private_root]
        if peer and root_moves.origin(peer) == repos.moved_to(b["repo"]):
            # the root comes back from the tiroir it moved to, the peer the channel's token names (never the body's `from`):
            # it is unmoved only once nothing in this check would refuse it
            if (why := repos.refusal(first[0].short or first[0].id, b["repo"], privates)) is not None:
                return 409, {"why": why.replace("-", "_"),
                             **({"install": url} if why == repos_mod.NO_APP and (url := repos.install_url(b["repo"])) else {})}
            repos.unmove(b["repo"])
        try:
            said = repos.report(first[0].short or first[0].id, b["repo"], first[1], b["tip"], privates, {})
        except repos_mod.Refused:
            return 409, {"why": "refused"}
        clone = said.get("clone")
        if clone == repos_mod.NO_APP:
            return 409, {"why": "no_app", **({"install": said["install"]} if said.get("install") else {})}
        if clone in (repos_mod.PRIVATE_ROOT, repos_mod.NOT_CLONED, repos_mod.MOVED):
            return 409, {"why": clone.replace("-", "_")}
        if clone != repos_mod.OK or not said.get("commit_known"):
            return 202, {"state": "cloning"}
        dest = repos.clone_dir(b["repo"])
        for p in b["pages"]:
            if p["path"] not in judged:
                judged[p["path"]] = {"ready": True} if root_moves.tip_holds(dest, b["branch"], p["path"], p["blob"]) \
                    else {"ok": False, "why": "text_differs"}
    return 200, {"pages": judged}
