"""sheafmd.hub.incoming — the receiving end of a move to this tiroir (ticket 20).

    owner_for(hub, email)       (the member the e-mail names, "") or (None, why)
"""
from . import proxy

MADE_UP = "this tiroir does not know your e-mail address"


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
