"""sheafmd.hub.outgoing — the sending end of a move to another tiroir (ticket 20).

    owner_email(cfg, member)    (the e-mail the receiving tiroir will match, "") or (None, the sentence why not)
    call(origin, verb, body)    (status, answer) of another tiroir's channel, OSError when it does not answer

`send_root` sends a root's pages and keeps what the receiver confirmed; the Forward per confirmed page and the real call are
hooked up once ticket 17's Forward is in main.
"""
import http.client
import json
import re
import urllib.error
import urllib.request

from . import channel, proxy

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


def call(origin: str, verb: str, body: dict) -> tuple:
    """(status, answer) of the channel of the tiroir at `origin`: `verb` posted with the token `sheaf peer use` kept for it. No
    token, no answer, a redirect or a reply that is not JSON is an OSError, so the caller says the tiroir is not reachable and
    keeps nothing; a refusal is its status."""
    from .. import connect
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
    its Forward);     every other page is held with a reason, written to the move and, when it changed, to the diagnostics. Returns `{path: the
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
