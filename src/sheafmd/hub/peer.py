"""
sheafmd.hub.peer — which user is at the other end of a connection (SPEC 9.1, 9.3).

The launcher of `sheaf open` hands the browser a sign-in nonce in its command line, and any user of
the machine can read a command line while the process lives (`/proc/<pid>/cmdline`). So the nonce is
redeemed only by a connection whose owner is the hub's own user. Linux keeps the owner of every TCP
socket in /proc/net/tcp (IPv4) and /proc/net/tcp6 (IPv6; an IPv4 address on an IPv6 socket shows there
as `::ffff:a.b.c.d`): one row per socket with its local address, remote address and uid.

The row to read is the one of the *client's* socket, whose local address is the client's and whose
remote address is the hub's. The hub's own end of the same connection is a row too, owned by the hub
whoever called; reading that one would let every caller through.

Fail closed: a row that is not found, two rows that name two users, a file that is there and cannot be
read, or no connection to look up at all, refuse. A platform that is not Linux (macOS) is not checked:
the nonce is redeemed as it always was, and 9.1 says what that leaves open. Linux is told by
`sys.platform`, so a Linux machine with no /proc/net at all refuses.

Functions over two files and a pair of addresses; the handler decides what to show.
"""
import ipaddress
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple

PROC_NET = Path("/proc/net")         # a test points it at files of its own
PLATFORM = sys.platform              # and says which platform this is

_ENDPOINT_RE = re.compile(r"([0-9A-F]{8}|[0-9A-F]{32}):([0-9A-F]{4})", re.IGNORECASE)
TABLES = ("tcp", "tcp6")
OTHER_USER, UNKNOWN = "other-user", "unknown"


class Conn(NamedTuple):
    """The two ends of one connection, (address, port) each: the caller's and the hub's."""
    client: tuple
    hub: tuple


class Refusal(NamedTuple):
    kind: str                        # OTHER_USER, or UNKNOWN: the hub could not tell
    message: str                     # what any caller is told: no uid, no path
    detail: str                      # what the row of the log says, for the person who runs `sheaf diag`


def supported() -> bool:
    """Whether this platform lets the hub read who owns a connection (Linux)."""
    return PLATFORM.startswith("linux")


def _normal(ip):
    """An IPv4 address on an IPv6 socket is the IPv4 address."""
    if ip.version == 6 and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def _endpoint(text: str):
    """`0100007F:C350` or `00000000000000000000000001000000:C350` as (address, port). The kernel
    prints each 32-bit word of an address in the machine's byte order. ValueError for anything else."""
    m = _ENDPOINT_RE.fullmatch(text)
    if not m:
        raise ValueError(text)
    host = m.group(1)
    raw = b"".join(int(host[i:i + 8], 16).to_bytes(4, sys.byteorder) for i in range(0, len(host), 8))
    return _normal(ipaddress.ip_address(raw)), int(m.group(2), 16)


def _address(pair):
    return _normal(ipaddress.ip_address(pair[0])), int(pair[1])


def _owners(table: Path, local, remote) -> list[int]:
    """The uid of every row of `table` whose local and remote ends are these. OSError when the
    file cannot be read; a line that is no row (the header, a damaged one) is skipped."""
    owners = []
    for line in table.read_bytes().decode("ascii", "replace").splitlines():
        f = line.split()
        try:
            if len(f) >= 8 and _endpoint(f[1]) == local and _endpoint(f[2]) == remote:
                owners.append(int(f[7]))
        except ValueError:
            continue
    return owners


def _unknown(why: str) -> Refusal:
    said = "the hub could not tell which user followed that sign-in link"
    return Refusal(UNKNOWN, said, f"{said}: {why}")


def check(conn) -> Refusal | None:
    """None when the connection may redeem a sign-in link: it is the hub's own user's, or this
    platform cannot say. Otherwise why not."""
    if not supported():
        return None
    if conn is None:
        return _unknown("the request carried no connection to look up")
    try:
        local, remote = _address(conn.client), _address(conn.hub)
    except (ValueError, TypeError, IndexError):
        return _unknown("the address of the connection is not one it can look up")
    owners = []
    for name in TABLES:
        try:
            owners += _owners(PROC_NET / name, local, remote)
        except FileNotFoundError:
            if name == TABLES[0]:        # a machine with IPv6 off has no tcp6; a Linux with no tcp cannot say
                return _unknown(f"{PROC_NET / name} could not be read (it is not there)")
        except OSError as e:
            return _unknown(f"{PROC_NET / name} could not be read ({e.strerror or type(e).__name__})")
    if not owners:
        return _unknown("the connection could not be found in /proc/net/tcp or /proc/net/tcp6")
    if len(set(owners)) > 1:
        return _unknown("the connection has rows that name more than one user")
    hub_uid = os.geteuid()
    if owners[0] != hub_uid:
        return Refusal(OTHER_USER, "that sign-in link was followed by another user of this machine",
                       f"that sign-in link was followed by another user of this machine "
                       f"(uid {owners[0]}); the hub runs as uid {hub_uid}")
    return None
