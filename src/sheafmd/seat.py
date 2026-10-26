"""
sheafmd.seat — whether the person sits at this machine or reaches it over ssh (SPEC 9.6, 13).

The hub answers on 127.0.0.1 only. A browser started here reaches it; a browser on the person's
own machine, when they work here over ssh, does not: there 127.0.0.1 is their own machine. Such
a seat is remote when an ssh variable is present and no display or named browser is, since a
display (`ssh -X`) or a browser named in `BROWSER` (an editor's remote session sets one that
opens on the person's machine and forwards the port itself) still opens a page that works.
"""
import getpass
import ipaddress
import socket
from dataclasses import dataclass

SSH_VARS = ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY")
BROWSER_VARS = ("DISPLAY", "WAYLAND_DISPLAY", "BROWSER")


@dataclass(frozen=True)
class RemoteSeat:
    user: str
    host: str                  # this machine's address as the ssh server saw the connection, or its name
    ssh_port: int = 22

    def tunnel(self, port: int) -> str:
        """The command to run on the person's own machine: the hub's port to the same local port
        number, so the cookie named after it (9.3) is the one the browser keeps."""
        p = f" -p {self.ssh_port}" if self.ssh_port != 22 else ""
        return f"ssh -N -L {port}:127.0.0.1:{port}{p} {self.user}@{self.host}"


def _present(environ, var) -> bool:
    """Set and not empty, as for the agent variables (11.5)."""
    return bool(environ.get(var, "").strip())


def remote(environ) -> RemoteSeat | None:
    """The remote seat, or None when a browser started here can open the page."""
    if not any(_present(environ, v) for v in SSH_VARS) or any(_present(environ, v) for v in BROWSER_VARS):
        return None
    user = getpass.getuser()
    # SSH_CONNECTION: "<client ip> <client port> <server ip> <server port>".
    parts = environ.get("SSH_CONNECTION", "").split()
    if len(parts) == 4 and parts[3].isdigit():
        try:
            return RemoteSeat(user, str(ipaddress.ip_address(parts[2])), int(parts[3]))
        except ValueError:
            pass
    # SSH_CLIENT: "<client ip> <client port> <server port>"; it names no server address.
    client = environ.get("SSH_CLIENT", "").split()
    port = int(client[2]) if len(client) == 3 and client[2].isdigit() else 22
    return RemoteSeat(user, socket.gethostname(), port)
