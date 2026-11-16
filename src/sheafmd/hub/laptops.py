"""A member's laptops (SPEC 9.7, 9.12): "Connect a laptop" names a laptop and makes an agent token for that laptop
and that member. The token is an ordinary agent token (`Tokens.add`) whose row also keeps the member's front id and
the laptop's name. The hub reads `tokens.json` on every request, so revoking a laptop is deleting its row and the
next call with the token is a 401; and the member comes from the row, so the token sees what its member sees and
nothing more (`ProxyConfig.member_of_row`)."""
import secrets

from . import proxy
from .auth import clean_display
from .state import TokenError, TokenRow

CLIENT = "Claude Code"         # whose token a laptop's is signed as, `Claude Code (Member)`; a client's own name comes from the door
NAME_MAX = 60


class LaptopError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def check_name(name) -> str:
    """The laptop's name as the member typed it, or a 400: one printable line the display-name rule leaves as it is."""
    if not isinstance(name, str) or not name.strip() or clean_display(name) != name or len(name) > NAME_MAX:
        raise LaptopError(400, f"a laptop's name is 1 to {NAME_MAX} printable characters on one line")
    return name


def _same(a: str, b: str) -> bool:
    return a.casefold() == b.casefold()


def of(hub, member_id: str) -> list[TokenRow]:
    return [r for r in hub.tokens.list() if r.member == member_id and r.laptop is not None and not r.invalid]


def make(hub, member_id: str, name) -> tuple[str, TokenRow]:
    """(the token, its row) for a new laptop of the member. The token is shown here and nowhere else."""
    name = check_name(name)

    def clash(rows):
        if any(r.member == member_id and r.laptop is not None and _same(r.laptop, name) for r in rows):
            return f"you already have a laptop named {name!r}: revoke it first, or give this one another name"
        # a name another token signs would stop the hub at its next start (9.7): refuse it here, with the reason
        new = TokenRow("laptop-new", None, True, client=CLIENT, member=member_id, laptop=name)
        try:
            proxy.check_agent_names(proxy.signed_names(hub.proxy, hub.person, [*rows, new]))
        except proxy.ProxyError as e:
            return str(e)
        return None

    try:
        token = hub.tokens.add(f"laptop-{secrets.token_hex(6)}", client=CLIENT, write=True, member=member_id, laptop=name, clash=clash)
    except TokenError as e:
        raise LaptopError(409, str(e)) from None
    return str(token), next(r for r in hub.tokens.list() if r.id == token.id)


def revoke(hub, member_id: str, name) -> None:
    """End the member's laptop `name`. A laptop of another member answers as one that does not exist."""
    name = name if isinstance(name, str) else ""
    row = next((r for r in of(hub, member_id) if _same(r.laptop, name)), None)
    if row is None or not hub.tokens.revoke(row.name):
        raise LaptopError(404, "you have no laptop of that name")
