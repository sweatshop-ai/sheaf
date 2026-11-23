"""sheafmd.hub.outgoing — the sending end of a move to another tiroir (ticket 20).

    owner_email(cfg, member)    (the e-mail the receiving tiroir will match, "") or (None, the sentence why not)
    call(origin, verb, body)    (status, answer) of another tiroir's channel, OSError when it does not answer
    post(origin, verb, body, token, seconds)    (status, answer) of one call of the other tiroir's channel; `OSError` when none came
    move_to_tiroir(hub, member, address, origin)    the page moved there and the Forward written, or `Refusal`

`move_to_tiroir` sends one page and, only after the other tiroir confirms it landed, writes the Forward and drops its own copy.
`send_root` sends a root's pages and keeps what the receiver confirmed; the Forward per confirmed page and the real call are
hooked up once ticket 17's Forward is in main.
"""
import contextlib
import dataclasses
import http.client
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from .. import connect, paths
from ..source import STAMP_FORMAT, file_lock, md_hash
from . import archive, channel, incoming, loose, moves, place, proxy, state
from .roots import NotFound

SECONDS = 3                     # what a read-through waits for a client tiroir: a page that is slow is a page that is not there

NO_EMAIL = ("this shared Sheaf does not know your e-mail address, so the other one cannot tell who you are there: "
            "ask for it to be set in this one's configuration")


def owner_email(cfg, member) -> tuple:
    """The e-mail a move to another tiroir names its owner by: the member's own, from the `[proxy]` table. A member with
    none, or whose address is the made-up one every member without a block gets (`proxy.default_email`), has none to
    give: the other tiroir would match a stranger, or no one."""
    email = (member.email or "").strip()
    if not email or email.lower() == proxy.default_email(member.id, cfg.origin).lower():
        return None, NO_EMAIL
    return email, ""


class Refusal(Exception):
    """A move that did not happen, with everything as it was: the status the route answers, a few fixed words (`why`), and the
    sentence the member reads."""

    def __init__(self, status: int, why: str, say: str):
        super().__init__(say)
        self.status, self.why, self.say = status, why, say


def post(origin: str, verb: str, body: dict, token: str, seconds: float | None = None) -> tuple:
    """One call of the other tiroir's channel, `POST <origin>/_/tiroir/<verb>`: (status, the JSON answer or None). `OSError` when
    there is no answer at all (no route, a timeout, a connection cut): the caller cannot tell whether the other side did the work."""
    req = urllib.request.Request(f"{origin}/_/tiroir/{verb}", data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    try:
        with connect._NO_REDIRECT.open(req, timeout=seconds or channel.SECONDS) as res:   # a 3xx is an answer: the bearer goes to the peer alone
            status, raw = res.status, res.read()
    except (urllib.error.HTTPError, http.client.HTTPException) as e:
        if not isinstance(e, urllib.error.HTTPError):       # a reply cut short or not HTTP: no answer, as a cut connection is none
            raise OSError(f"the other shared Sheaf's reply was not a whole one ({type(e).__name__})") from None
        try:
            status, raw = e.code, e.read()
        except http.client.HTTPException as cut:             # an error reply whose body was cut short is no answer either
            raise OSError(f"the other shared Sheaf's reply was not a whole one ({type(cut).__name__})") from None
    try:
        return status, json.loads(raw.decode("utf-8")) if raw else None
    except ValueError:
        return status, None


def _notes() -> tuple:
    """`outgoing.json`: `{address: {id, hash}}` of the moves sent whose Forward is not written yet, and its path."""
    path = paths.state_dir() / "outgoing.json"
    return state.read_json(path, {}), path


def _note(address: str, entry: dict | None) -> None:
    with state.file_locked("outgoing.lock"):
        held, path = _notes()
        if entry is None:
            if held.pop(address, None) is None:
                return
        else:
            held[address] = entry
        state.write_json(path, held)


def _bundle(hub, member, root, rel: str, address: str, email: str, move_id: str) -> tuple:
    """(the bundle, the hash of the text it carries) of the page at `address`, read under the page's name lock."""
    with place.held(hub, address):
        try:
            path = hub.file(address, root_id=root.id)     # the moving root's file, never one of a folder that took its name since
            text = path.read_text(encoding="utf-8")
            mtime = os.stat(path).st_mtime
        except (OSError, ValueError, NotFound):
            raise Refusal(404, "gone", "no such document") from None
        folder, _, name = rel.rpartition("/")
        versions = (hub._versions_of(root) or hub.versions).texts(address)
        writes = [{k: v for k, v in dataclasses.asdict(line).items() if k != "address"} for line in hub.writes.lines(address)]
        bundle = {"id": move_id, "owner_email": email, "folder": folder or None, "name": name, "text": text,
                  "versions": [{"text": v} for v in versions], "writes": writes,
                  "keep": rel in loose.marks(root.path),
                  "archived": archive.is_archived(loose.times(root.path, loose.ARCHIVED), rel, mtime),
                  "from": {"origin": hub.proxy.origin, "by": member.name, "at": time.strftime(STAMP_FORMAT)}}
    return bundle, md_hash(text)


def move_to_tiroir(hub, member, address: str, origin: str) -> dict:
    """The loose page at `address`, its owner `member`'s, is moved to the tiroir at `origin` (ticket 20): `{doc, origin, hash}` of
    where it landed. Confirm-then-Forward: the Forward is written, and the page dropped here, only after the other tiroir
    answers that the page landed, and only if the page is still the text that was sent. A refusal, a link that is down and an
    answer that is lost leave the page and every store as they were (`Refusal`). The other tiroir matches the owner by e-mail and
    answers the same id once, so a send whose answer was lost is sent again as it was and lands one page."""
    try:
        root, rel = moves._root_of(hub, member, address)
    except moves.Refused as r:
        raise Refusal(r.status, "not_movable", r.message) from None
    try:
        origin = connect.origin_of(origin)
    except Exception:
        raise Refusal(400, "bad_tiroir", "that is not the address of a shared Sheaf") from None
    if origin == hub.proxy.origin:
        raise Refusal(409, "same_tiroir", "the page is on that shared Sheaf already")
    email, why = owner_email(hub.proxy, member)
    if email is None:
        raise Refusal(409, "no_email", why)
    token = connect.peer_token_for(origin)
    if token is None:
        raise Refusal(409, "not_paired", f"this shared Sheaf holds no peer token for {origin}, so nothing was sent: "
                                         "pair the two with `sheaf peer add` on that one and `sheaf peer use` on this one")
    marked = contextlib.ExitStack()      # the page is moving for the whole transfer: a Tell or a save is answered as on a busy page
    try:
        marked.enter_context(moves._marked(hub, address))
    except moves.Refused as r:
        raise Refusal(r.status, "busy" if r.message == moves.BEING_MOVED else "tell_running", r.message) from None
    with marked:
        return _transfer(hub, member, root, rel, address, origin, email, token)


def _transfer(hub, member, root, rel: str, address: str, origin: str, email: str, token: str) -> dict:
    """The transfer of `move_to_tiroir`, with the page marked moving."""
    with state.file_locked("outgoing.lock"):
        held, _ = _notes()
    noted = held.get(address) if isinstance(held.get(address), dict) else {}
    bundle, sent = _bundle(hub, member, root, rel, address, email, noted.get("id") or uuid.uuid4().hex)
    if noted.get("hash") != sent:      # the page is not the one that was sent before: another id, and the answer is the other side's own
        bundle["id"] = uuid.uuid4().hex
    _note(address, {"id": bundle["id"], "hash": sent})
    try:
        status, answer = post(origin, "transfer", bundle, token, channel.SECONDS)
    except OSError:
        raise Refusal(502, "unreachable", f"{origin} did not answer, so it is not known whether the page landed there: the page "
                                          "is where it was, and sending it again lands it once") from None
    answer = answer if isinstance(answer, dict) else {}
    if status == 409:
        _note(address, None)
        why = str(answer.get("why") or "refused")
        raise Refusal(409, why, str(answer.get("say") or incoming.SAYS.get(why) or "the other shared Sheaf refused the page"))
    if status != 200 or not isinstance(answer.get("address"), str) or not isinstance(answer.get("hash"), str):
        raise Refusal(502, "failed", f"{origin} could not take the page ({status}): it is where it was, and sending it again lands it once")
    with moves._LOCK, place.held(hub, address), hub.page_lock(address), contextlib.ExitStack() as locked:
        try:
            # The moving root's file, found once: its root forgotten, and the name taken by another folder, during the
            # transfer, is a page that changed, and the other folder's file is neither read nor dropped (8.11).
            path = hub.file(address, root_id=root.id)
            locked.enter_context(file_lock(path))       # the file lock a save takes: what it wrote is read here or after
            now = md_hash(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, NotFound):
            now = None
        if now != sent:
            _note(address, None)
            raise Refusal(409, "changed", "the page changed while it was moving: the copy there is older, so nothing was dropped "
                                          "here. Move it again once you have looked at both")
        finish = hub.moved_remote(address, origin, answer["address"], member.name, answer["hash"], sent)
        try:
            os.unlink(path)
            moves.tidy(Path(os.path.realpath(root.path)), rel)
        except OSError:
            hub.record_exception("move-store-failed", address)
        _note(address, None)
    finish()        # the hub's lock, the tabs and the index: after the page's locks are let go and its file is gone
    return {"doc": answer["address"], "origin": origin, "hash": answer["hash"]}


def call(origin: str, verb: str, body: dict) -> tuple:
    """(status, answer) of the channel of the tiroir at `origin`: `verb` posted with the token `sheaf peer use` kept for it. No
    token, no answer, a redirect or a reply that is not JSON is an OSError, so the caller says the tiroir is not reachable and
    keeps nothing; a refusal is its status."""
    token = connect.peer_token_for(origin)
    if token is None:
        raise OSError(f"no token is kept for {origin}")
    req = urllib.request.Request(f"{origin}/_/tiroir/{verb}", json.dumps(body).encode(), {
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method="POST")
    try:
        try:
            with connect._NO_REDIRECT.open(req, timeout=SECONDS) as r:
                status, raw = r.status, r.read(channel.MAX_TRANSFER)
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read(channel.MAX_TRANSFER)
    except http.client.HTTPException as e:          # a reply cut short is not an OSError, and is a tiroir that does not answer
        raise OSError(f"{origin} did not finish its answer") from e
    try:
        answer = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        raise OSError(f"{origin} did not answer as a channel does") from None
    return status, answer


# ── a whole root (ticket 21) ─────────────────────────────────────────────────

BATCH_LIMIT = channel.MAX_TRANSFER - 64 * 1024      # what a call's pages may weigh: the head and the framing take the rest


def _weighs(rows) -> int:
    return len(json.dumps(rows))


def too_big(rows, limit: int = BATCH_LIMIT) -> set:
    """The paths of the pages that cannot go in a call of their own."""
    return {r["path"] for r in rows if _weighs([r]) > limit}


def batches(rows, limit: int = BATCH_LIMIT) -> list:
    """`rows` in order, cut into calls of at most `limit` bytes of JSON; a page too big for a call alone is left out (`too_big`)."""
    out, cur = [], []
    for r in rows:
        if _weighs([r]) > limit:
            continue
        if cur and _weighs(cur + [r]) > limit:
            out.append(cur)
            cur = []
        cur.append(r)
    if cur:
        out.append(cur)
    return out


REASON = re.compile(r"[a-z_]{1,64}")


HASH = re.compile(r"[0-9A-Za-z]{1,128}")


def _hash(said) -> str:
    """The hash a peer confirmed a page with, when it is a short token; else empty: what a peer says is not stored as it came."""
    return said if isinstance(said, str) and HASH.fullmatch(said) else ""


def _reason(said) -> str:
    """The reason a peer gave for holding a page, when it is a short word of ours; anything else is `failed`: what a peer
    says never reaches the move file or the diagnostics as it came."""
    return said if isinstance(said, str) and REASON.fullmatch(said) else "failed"


def send_root(post, moves, repo: str, to: str, head: dict, rows, limit: int = BATCH_LIMIT, diag=None) -> dict:
    """Send the pages of a root that is moving to `to`, one `root` call per batch. `post(to, verb, body)` answers
    `(status, body)` or raises `OSError`. Each page the receiver confirms is marked sent with its hash (the caller then writes
    its Forward); every other page is held with a reason, written to the move and, when it changed, to the diagnostics. Returns `{path: the
    receiver's hash}` for the pages confirmed this time."""
    todo = [r for r in rows if r["path"] not in (moves.get(repo) or {}).get("sent", [])]
    held = {p: "too_big" for p in too_big(todo, limit)}
    done = {}
    pending = batches([r for r in todo if r["path"] not in held], limit)
    for n, batch in enumerate(pending):
        try:
            status, answer = post(to, "root", {**head, "pages": batch})
        except OSError:
            status, answer = 0, {}
        if not isinstance(answer, dict):
            answer = {}                 # an empty body, or a list: nothing it says is read
        paths = [r["path"] for r in batch]
        if status == 200 and isinstance(answer.get("pages"), dict):
            for p in paths:
                got = answer["pages"].get(p)
                if isinstance(got, dict) and got.get("ok") is True and (hash := _hash(got.get("hash"))):
                    done[p] = hash
                    moves.sent(repo, p, hash)
                elif isinstance(got, dict) and got.get("ok") is True:
                    held[p] = "failed"          # confirmed with no usable hash: its Forward could not be checked, so it goes again
                else:
                    held[p] = _reason(got.get("why")) if isinstance(got, dict) else "failed"
            continue
        why = "unreachable" if status == 0 else "cloning" if status == 202 else \
            (_reason(answer.get("why")) if status == 409 else "failed")
        for later in pending[n:]:
            held.update({r["path"]: why for r in later})
        break
    if moves.hold(repo, held) and diag is not None:
        diag.held(repo, to, held)
    return done
