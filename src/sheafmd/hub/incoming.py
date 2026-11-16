"""sheafmd.hub.incoming — the receiving end of a move to this tiroir (ticket 20).

    owner_for(hub, email)       (the member the e-mail names, "") or (None, why)
    land(hub, door, bundle)     (200, the answer) of a page landed in its owner's loose root, or (409, {why, say}) of one refused

A page lands whole or not at all: its file, versions, Write log lines and keep mark are made together under the name's lock,
and a failure takes back what was made. `transfers.json` keeps the answer to each `id`, so a send whose confirmation was
lost is answered again and never lands twice.
"""
import contextlib
import os

from .. import mcp, paths
from . import loose, proxy, state, visibility
from .state import TokenRow

SAYS = {
    "no_email": "this tiroir does not know the e-mail address of the person who owns the page, or the page's owner has none "
                "here: a member's e-mail must be set in this tiroir's configuration before pages can be moved to them",
    "no_owner": "no one on this tiroir has the owner's e-mail address",
    "ambiguous_owner": "more than one person on this tiroir has the owner's e-mail address",
    "name_taken": "a page of that name is there already, in that folder: it may be an older copy of this one",
    "not_landed": "the page was not accepted",
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


def _answers() -> "state.Path":
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
    return None


def land(hub, door, b) -> tuple:
    """Land bundle `b` for the member its `owner_email` names. (200, {ok, address, hash, origin}) or (409, {ok: False, why, say});
    a bundle that is not one is a Refuse of the handler's (`ValueError` here, with the reason), never a half-landed page."""
    if (bad := _shape(b)) is not None:
        raise ValueError(bad)
    owner, why = owner_for(hub, b.get("owner_email"))
    if owner is None:
        return _refused(why)
    with state.file_locked("transfers.lock"):
        known = state.read_json(_answers(), {}).get(b["id"])
        if isinstance(known, dict):
            return 200, {"ok": True, **known}
    caller = mcp.Caller(owner.name, TokenRow("peer-transfer", owner.name, True, member=owner.id))
    # The Share does not travel: its audience is text, and the people it names are not this tiroir's. The page lands the
    # owner's alone, every Share box unticked and no `shared` line, whatever the sender's text said.
    text = visibility.unshare(visibility.without_ticked_share(b["text"]))
    args = {"doc": b["name"], "folder": b.get("folder"), "text": text, **({"keep": True} if b.get("keep") else {})}
    try:
        made = door._create(args, caller)
    except mcp.ToolError as e:
        return _refused("name_taken") if e.why == "exists" else _refused("not_landed", str(e))
    address = made["doc"]
    try:
        for v in b.get("versions", []):
            hub.versions.put(address, v["text"])
        by = (b.get("from") or {}).get("by") if isinstance(b.get("from"), dict) else None
        came_from = (b.get("from") or {}).get("origin") if isinstance(b.get("from"), dict) else None
        hub.writes.carry(address, b.get("writes", []), came_from if isinstance(came_from, str) else "",
                         by if isinstance(by, str) else owner.name)
        answer = {"address": address, "hash": made["hash"], "origin": hub.proxy.origin}
        with state.file_locked("transfers.lock"):
            rows = state.read_json(_answers(), {})
            state.write_json(_answers(), {**rows, b["id"]: answer})
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(hub.file(address))
        with contextlib.suppress(Exception):
            hub.versions.forget(address)
            hub.writes.told(address)
        if (loose_root := hub.loose.known(owner)) is not None:
            with contextlib.suppress(loose.Refused, OSError):
                _unkeep(loose_root, address)
        raise
    return 200, {"ok": True, **answer}


def _unkeep(root_path, address: str) -> None:
    """Take back the keep mark a landing made for `address`, when it made one."""
    rel = address.split("/", 1)[1]
    held = loose.marks(root_path)
    if rel in held:
        mark = root_path / loose.KEEP
        state.write_text_private(mark, __import__("json").dumps(sorted(x for x in held if x != rel)) + "\n", inside=True)
