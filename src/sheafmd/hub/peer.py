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
import socket
import struct
import sys
from pathlib import Path
from typing import NamedTuple

PROC_NET = Path("/proc/net")         # a test points it at files of its own
PLATFORM = sys.platform              # and says which platform this is
NETLINK = True                       # a test turns the kernel's socket diagnostics off, to read /proc/net

_ENDPOINT_RE = re.compile(r"([0-9A-F]{8}|[0-9A-F]{32}):([0-9A-F]{4})", re.IGNORECASE)
TABLES = ("tcp", "tcp6")
OTHER_USER, UNKNOWN = "other-user", "unknown"


class Conn(NamedTuple):
    """The two ends of one connection, (address, port) each: the caller's and the hub's. The server
    asks who owns it once, when it accepts the connection (`look`), and keeps the answer here:
    `looked` is whether it did, `refusal` what it found (None: the hub's own user), `closed` a
    function that says whether the caller has closed its end by now."""
    client: tuple
    hub: tuple
    looked: bool = False
    refusal: "Refusal | None" = None
    closed: object = None


class Refusal(NamedTuple):
    kind: str                        # OTHER_USER, or UNKNOWN: the hub could not tell
    message: str                     # what any caller is told: no uid, no path
    detail: str                      # what the row of the log says, for the person who runs `sheaf diag`
    uid: int | None = None           # the uid found at the caller's end, for the row; never told to a caller


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


# ── the kernel's socket diagnostics (sock_diag over AF_NETLINK) ──────────────

_NETLINK_SOCK_DIAG, _SOCK_DIAG_BY_FAMILY, _NLMSG_ERROR = 4, 20, 2
_NLM_F_REQUEST = 1
_NOCOOKIE = 0xFFFFFFFF
_ENOENT = 2
_NETLINK_TIMEOUT = 2.0
_ESTABLISHED = 1                       # tcpi_state of a connection whose caller has not closed
_HEADER = 16                           # struct nlmsghdr
_UID_AT = _HEADER + 64                 # inet_diag_msg: 4 bytes, the 48-byte id, then expires, rqueue, wqueue
_MSG_LEN = _HEADER + 72                # ... and uid, inode


def _netlink_request(family: int, local, remote) -> bytes:
    """inet_diag_req_v2 for the one TCP socket in any state whose local end is `local` and whose
    remote end is `remote`. The ids name the socket as the kernel looks it up: `src` is its own end."""
    def packed(ip):
        if ip.version == 4 and family == socket.AF_INET6:       # an IPv6 socket holds an IPv4 peer as ::ffff:a.b.c.d
            return b"\0" * 10 + b"\xff\xff" + ip.packed
        return ip.packed.ljust(16, b"\0")
    body = struct.pack("=BBBBI", family, socket.IPPROTO_TCP, 0, 0, 0xFFFFFFFF)
    body += struct.pack(">HH", local[1], remote[1]) + packed(local[0]) + packed(remote[0])
    body += struct.pack("=III", 0, _NOCOOKIE, _NOCOOKIE)    # interface (any), then the cookie that says "any"
    return struct.pack("=IHHII", 16 + len(body), _SOCK_DIAG_BY_FAMILY, _NLM_F_REQUEST, 1, 0) + body


def _netlink_owners(local, remote) -> list[int]:
    """The uid of the TCP socket whose local end is `local` and remote end `remote`, as the kernel
    names it: a list of none or one. OSError when the kernel cannot be asked or answers with an
    error other than "no such socket"."""
    owners = []
    with socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, _NETLINK_SOCK_DIAG) as nl:
        nl.settimeout(_NETLINK_TIMEOUT)
        both_v4 = local[0].version == remote[0].version == 4
        for family in ((socket.AF_INET, socket.AF_INET6) if both_v4 else (socket.AF_INET6,)):
            nl.send(_netlink_request(family, local, remote))
            data = nl.recv(8192)
            if len(data) < 16:
                raise OSError(0, "the kernel's answer was cut short")
            _, kind, _, _, _ = struct.unpack_from("=IHHII", data)
            if kind == _NLMSG_ERROR:
                code = -struct.unpack_from("=i", data, 16)[0]
                if code and code != _ENOENT:
                    raise OSError(code, os.strerror(code))
                continue
            if kind != _SOCK_DIAG_BY_FAMILY or len(data) < _MSG_LEN:
                raise OSError(0, "the kernel's answer was not a socket")
            owners.append(struct.unpack_from("=I", data, _UID_AT)[0])
            break
    return owners


def _proc_owners(local, remote) -> list[int]:
    """The same from /proc/net/tcp and /proc/net/tcp6. OSError when a file cannot be read."""
    owners = []
    for name in TABLES:
        try:
            owners += _owners(PROC_NET / name, local, remote)
        except FileNotFoundError:
            if name == TABLES[0]:        # a machine with IPv6 off has no tcp6; a Linux with no tcp cannot say
                raise OSError(0, f"{PROC_NET / name} is not there")
    return owners


def owners(conn) -> list[int]:
    """The uid of every socket that is the client's end of `conn` (a `Conn`): asked of the kernel's
    socket diagnostics, and of /proc/net/tcp* where the kernel cannot be asked or finds nothing (it
    answers "no such socket" also where no tcp_diag handler is loaded). An empty list is both saying
    there is no such socket. OSError when neither can say."""
    local, remote = _address(conn.client), _address(conn.hub)
    if NETLINK:
        try:
            found = _netlink_owners(local, remote)
            if found:
                return found
        except (OSError, struct.error, AttributeError):    # AttributeError: no AF_NETLINK on this platform
            pass
    return _proc_owners(local, remote)


def selftest() -> str | None:
    """None when the hub can read the owner of a connection it holds itself (a loopback pair, opened
    here) and gets its own uid; on a platform that is not checked, None too. Otherwise why not, for
    the row and the notice of a hub that has to switch the check off."""
    if not supported():
        return None
    try:
        with socket.socket() as srv, socket.socket() as cli:
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            cli.connect(srv.getsockname())
            acc, _ = srv.accept()
            with acc:
                found = owners(Conn(cli.getsockname()[:2], cli.getpeername()[:2]))
    except (OSError, ValueError, TypeError) as e:
        return f"the owner of a loopback connection could not be read ({getattr(e, 'strerror', None) or e})"
    if found != [os.geteuid()]:
        return f"the owner of a loopback connection read as {found}, not the hub's own uid {os.geteuid()}"
    return None


def check(conn) -> Refusal | None:
    """None when the connection may redeem a sign-in link: it is the hub's own user's, or this
    platform cannot say. Otherwise why not."""
    if not supported():
        return None
    if conn is None:
        return _unknown("the request carried no connection to look up")
    try:
        _address(conn.client), _address(conn.hub)
    except (ValueError, TypeError, IndexError):
        return _unknown("the address of the connection is not one it can look up")
    try:
        found = owners(conn)
    except OSError as e:
        return _unknown(f"the owner of the connection could not be read ({e.strerror or type(e).__name__})")
    if not found:
        return _unknown("the connection could not be found (asked the kernel, or /proc/net/tcp and /proc/net/tcp6 where it cannot answer)")
    if len(set(found)) > 1:
        return _unknown("the connection has rows that name more than one user")
    hub_uid = os.geteuid()
    if found[0] != hub_uid:
        return Refusal(OTHER_USER, "that sign-in link was followed by another user of this machine",
                       f"that sign-in link was followed by another user of this machine "
                       f"(uid {found[0]}); the hub runs as uid {hub_uid}", found[0])
    return None


def closed(sock) -> bool:
    """Whether the caller has closed its end of the connection `sock` is the hub's end of: the kernel
    holds the hub's socket in CLOSE_WAIT, or past it, instead of ESTABLISHED. A caller that closed
    first has its own socket owned by no one (uid 0) from then on, so a lookup made after the close
    reads root, not the user who sent the request."""
    try:
        return sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_INFO, 1)[0] != _ESTABLISHED
    except (OSError, AttributeError, IndexError):
        return False


def look(client, hub, sock) -> Conn:
    """The connection `sock` came in on, with the answer to who is at its other end: asked once, as
    soon as it is accepted, before a byte of the request is read."""
    conn = Conn(client, hub)
    no = check(conn)
    if no is None and os.geteuid() == 0 and closed(sock):
        # Asked after the caller closed, the lookup reads root, which is the hub's own user where the hub
        # runs as root: a closed caller is never let through on that answer. Where the hub is not root, a
        # caller that only half-closed still reads as its owner and is judged by that.
        no = _unknown("the connection closed before the hub could tell who sent this")
    return Conn(client, hub, True, no, lambda: closed(sock))


def startup() -> str | None:
    """None when the hub can tell who owns a connection and turns the check on. Otherwise why it
    cannot (this system gives it no way, or it read its own connection wrong): the check is off,
    and the sign-in link goes by the nonce alone, as it did before 9.1."""
    if not supported():
        return f"this system ({PLATFORM}) gives the hub no way to see who owns a connection"
    return selftest()
