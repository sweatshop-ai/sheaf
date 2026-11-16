"""sheafmd.hub.outgoing — the sending end of a move to another tiroir (ticket 20).

    owner_email(cfg, member)    (the e-mail the receiving tiroir will match, "") or (None, the sentence why not)

The move itself (the bundle, the call, confirm-then-Forward) is hooked up once ticket 17's Forward is in main.
"""
from . import proxy

NO_EMAIL = ("this tiroir does not know your e-mail address, so the other tiroir cannot tell who you are there: "
            "ask for it to be set in this tiroir's configuration")


def owner_email(cfg, member) -> tuple:
    """The e-mail a move to another tiroir names its owner by: the member's own, from the `[proxy]` table. A member with
    none, or whose address is the made-up one every member without a block gets (`proxy.default_email`), has none to
    give: the other tiroir would match a stranger, or no one."""
    email = (member.email or "").strip()
    if not email or email.lower() == proxy.default_email(member.id, cfg.origin).lower():
        return None, NO_EMAIL
    return email, ""
