"""sheafmd.hub.outgoing — the sending end of a move to another tiroir (ticket 20).

    owner_email(cfg, member)    (the e-mail the receiving tiroir will match, "") or (None, the sentence why not)
    call(origin, verb, body)    (status, answer) of another tiroir's channel, OSError when it does not answer

The move itself (the bundle, the call, confirm-then-Forward) is hooked up once ticket 17's Forward is in main.
"""
import http.client
import json
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

