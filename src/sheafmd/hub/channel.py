"""sheafmd.hub.channel — the hub-to-hub channel (ticket 20): what a peer tiroir may ask of this one, on `/_/tiroir/*`.

    tailnet_source(headers)     whether the front says the request came from the tailnet
    peer_for(hub, req)          the peer token's row when the request may use the channel, else None
    VERBS                       the verbs, each with the scope it needs

The route is the one thing on the proxy socket that needs no member: a peer tiroir has no sign-in here. The front lets
this prefix through from the tailnet only, and this module judges it again: the front is a pipe, not a check. A request
that fails any of the checks below is answered as a route this hub does not have, whichever check it was, so a caller
learns nothing about which part it lacked; the hub's own row says which.
"""
import ipaddress

from . import auth

MAX_TRANSFER = 8 * 1024 * 1024  # a bundle: a page, its versions, its Write log lines. A bigger one is refused (413), not cut; the move says so in a sentence
MAX_ASK = 64 * 1024             # a `resolve`
SECONDS = 60                    # what a sender waits for an answer to a transfer
TAILNET = (ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48"))
VERBS = {"resolve": "transfer", "transfer": "transfer", "root": "transfer", "read": "read", "comment": "read"}     # verb -> the scope its token needs


def tailnet_source(headers: dict) -> bool:
    """Whether the request came from the tailnet, by the address the front appended to `X-Forwarded-For`: the last entry,
    the one the front saw, never one a caller wrote before it. None, or one that is no address, is no tailnet."""
    last = headers.get("x-forwarded-for", "").split(",")[-1].strip()
    try:
        ip = ipaddress.ip_address(last)
    except ValueError:
        return False
    return any(ip in net for net in TAILNET)


def peer_for(hub, req) -> tuple:
    """(the peer token's row, "") when the request is a POST of a verb that exists, from the tailnet, with a peer token
    that holds the scope the verb needs; else (None, the reason, for the hub's row)."""
    verb = req.path.removeprefix("/_/tiroir/")
    if req.method != "POST" or verb not in VERBS:
        return None, "route"
    if not tailnet_source(req.headers):
        return None, "source"
    row = hub.tokens.verify_peer(auth.bearer(req.headers.get("authorization")))
    if row is None:
        return None, "token"
    if not row.allows(VERBS[verb]):
        return None, "scope"
    return row, ""
