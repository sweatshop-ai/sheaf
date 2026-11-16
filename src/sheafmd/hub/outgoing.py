"""sheafmd.hub.outgoing — the sending end of a move to another tiroir (ticket 20).

    owner_email(cfg, member)    (the e-mail the receiving tiroir will match, "") or (None, the sentence why not)

The move itself (the bundle, the call, confirm-then-Forward) is hooked up once ticket 17's Forward is in main.
"""
import json

from . import channel, proxy

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


def send_root(post, moves, repo: str, to: str, head: dict, rows, limit: int = BATCH_LIMIT, diag=None) -> list:
    """Send the pages of a root that is moving to `to`, one `root` call per batch. `post(to, verb, body)` answers
    `(status, body)` or raises `OSError`. Each page the receiver confirms is marked sent (the caller then writes its Forward);
    every other page is held with a reason, written to the move and, when it changed, to the diagnostics. Returns the paths
    confirmed this time."""
    todo = [r for r in rows if r["path"] not in (moves.get(repo) or {}).get("sent", [])]
    held = {p: "too_big" for p in too_big(todo, limit)}
    done = []
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
                if isinstance(got, dict) and got.get("ok") is True:
                    moves.sent(repo, p)
                    done.append(p)
                else:
                    held[p] = got.get("why", "failed") if isinstance(got, dict) else "failed"
            continue
        why = "unreachable" if status == 0 else "cloning" if status == 202 else \
            (answer.get("why") if status == 409 and isinstance(answer.get("why"), str) else "failed")
        for later in pending[n:]:
            held.update({r["path"]: why for r in later})
        break
    if moves.hold(repo, held) and diag is not None:
        diag.held(repo, to, held)
    return done
